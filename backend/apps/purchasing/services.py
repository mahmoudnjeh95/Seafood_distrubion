"""Every write on purchases goes through these functions (ARCHITECTURE §3)."""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.boxes import services as box_services
from apps.core import audit
from apps.core.images import reencoded_photo
from apps.core.models import Organization, User
from apps.core.money import MAX_AMOUNT, Number, checked_amount, checked_quantity, display_money, line_total
from apps.inventory import services as inventory
from apps.inventory.services import MovementKind
from apps.partnerships import services as partnerships
from apps.treasury import services as treasury

from . import selectors
from .models import (
    INSTRUMENT_METHODS,
    LINE_METHOD_CHOICES,
    RECEIVABLE_ORDER_STATUSES,
    DocumentCounter,
    DocumentKind,
    FieldPurchase,
    FieldPurchaseAction,
    FieldPurchaseLine,
    FieldPurchasePayment,
    FieldPurchaseRevision,
    FieldPurchaseStatus,
    GoodsReceipt,
    GoodsReceiptLine,
    PaymentTerms,
    PlanLineStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    ReceiptCounter,
    RejectedEffet,
    RejectedRelease,
    SupplierInvoice,
    SupplierInvoiceReceipt,
    SupplierInvoiceStatus,
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierPaymentLine,
    SupplierPaymentPlanLine,
)
from .models import PaymentMethod as PaymentMethod  # re-exported for apps that record payments (the demo)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from apps.catalog.models import Product
    from apps.inventory.models import StockLocation
    from apps.partners.models import Supplier
    from apps.treasury.models import Bank, TreasuryAccount

ZERO = Decimal("0.000")
RECEIPT_NUMBER_PREFIX = "BR-"
INVOICE_NUMBER_PREFIX = "FF-"
ORDER_NUMBER_PREFIX = "BA-"
PAYMENT_NUMBER_PREFIX = "RF-"
# The methods one line, a plan line or a sum given at the port may use: every method but "several" (D-208).
LINE_METHODS = frozenset(value for value, _label in LINE_METHOD_CHOICES)


class ReceiptLineFields(TypedDict, total=False):
    product: "Product"
    ordered_quantity: Number | None
    invoiced_quantity: Number
    accepted_quantity: Number
    unit_cost: Number
    use_by: dt.date | None
    # The lot is bought together with this supplier (D-100); may be the receipt's own supplier.
    partner: "Supplier | None"


def line_error_key(index: int, field: str) -> str:
    """Errors of a line are reported on `lines.<index>.<field>`, so each one shows under its own input."""
    return f"lines.{index}.{field}"


def _next_receipt_number(organization: Organization) -> str:
    """BR-0001, BR-0002... per organization, taken under a row lock (same scheme as batch numbers, D-034)."""
    ReceiptCounter.objects.bulk_create([ReceiptCounter(organization=organization)], ignore_conflicts=True)
    counter = ReceiptCounter.objects.select_for_update().get(organization=organization)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"{RECEIPT_NUMBER_PREFIX}{counter.last_number:04d}"


def _header_errors(
    organization: Organization, supplier: "Supplier", location: "StockLocation", received_on: dt.date
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if supplier.organization_id != organization.pk:
        errors["supplier"] = _("Fournisseur inconnu.")
    elif not supplier.is_active:
        errors["supplier"] = _("Ce fournisseur est archivé.")
    if location.organization_id != organization.pk:
        errors["location"] = _("Emplacement inconnu.")
    elif not location.is_active:
        errors["location"] = _("Cet emplacement est archivé.")
    if received_on > timezone.localdate():
        errors["received_on"] = _("La date de réception ne peut pas être dans le futur.")
    return errors


def _checked_line(
    organization: Organization, index: int, line: ReceiptLineFields, received_on: dt.date, errors: dict[str, str]
) -> dict[str, Any]:
    """The line's values once checked; every problem is added to `errors` under the line's own keys."""
    checked: dict[str, Any] = {
        "product": line.get("product"),
        "use_by": line.get("use_by"),
        "partner": line.get("partner"),
    }
    product = checked["product"]
    if product is None or product.organization_id != organization.pk:
        errors[line_error_key(index, "product")] = _("Produit inconnu.")
    elif not product.is_active:
        errors[line_error_key(index, "product")] = _("Ce produit est archivé.")
    partner = checked["partner"]
    if partner is not None and (partner.organization_id != organization.pk or not partner.is_active):
        errors[line_error_key(index, "partner")] = _("Ce fournisseur est inconnu ou archivé.")
    for field in ("invoiced_quantity", "accepted_quantity"):
        try:
            value: Any = line.get(field, "")
            checked[field] = checked_quantity(value)
        except (ValueError, TypeError):
            errors[line_error_key(index, field)] = _("Indiquez un poids net en kg, supérieur à zéro.")
    ordered = line.get("ordered_quantity")
    checked["ordered_quantity"] = None
    if ordered not in (None, ""):
        try:
            checked["ordered_quantity"] = checked_quantity(ordered)
        except (ValueError, TypeError):
            errors[line_error_key(index, "ordered_quantity")] = _("Indiquez un poids en kg, ou laissez vide.")
    try:
        cost: Any = line.get("unit_cost", "")
        checked["unit_cost"] = checked_amount(cost)
    except (ValueError, TypeError):
        errors[line_error_key(index, "unit_cost")] = _("Indiquez un coût en DT par kg, au millime près.")
    biggest = max(checked.get("invoiced_quantity", ZERO), checked.get("accepted_quantity", ZERO))
    if "unit_cost" in checked and line_total(biggest, checked["unit_cost"]) > MAX_AMOUNT:
        errors[line_error_key(index, "unit_cost")] = _(
            "Le montant de cette ligne est trop grand : vérifiez le coût au kg."
        )
    use_by = checked["use_by"]
    if use_by is not None and use_by < received_on:
        errors[line_error_key(index, "use_by")] = _("La date limite ne peut pas précéder la réception.")
    return checked


def _snapshot(receipt: GoodsReceipt, lines: Sequence[GoodsReceiptLine]) -> dict[str, Any]:
    return {
        "number": receipt.number,
        "purchase_order": receipt.purchase_order.number if receipt.purchase_order else None,
        "supplier": receipt.supplier.reference,
        "location": receipt.location.name,
        "received_on": receipt.received_on.isoformat(),
        "supplier_reference": receipt.supplier_reference,
        "lines": [
            {
                "batch": line.batch.number,
                "product": line.product.reference,
                "ordered_quantity": str(line.ordered_quantity) if line.ordered_quantity is not None else None,
                "invoiced_quantity": str(line.invoiced_quantity),
                "accepted_quantity": str(line.accepted_quantity),
                "unit_cost": str(line.unit_cost),
            }
            for line in lines
        ],
    }


@transaction.atomic
def create_receipt(
    *,
    organization: Organization,
    actor: User | None,
    supplier: "Supplier",
    location: "StockLocation",
    received_on: dt.date,
    lines: Sequence[ReceiptLineFields],
    supplier_reference: str = "",
    notes: str = "",
    purchase_order: PurchaseOrder | None = None,
    boxes: Mapping[str, int] | None = None,
    with_vat: bool = False,
) -> GoodsReceipt:
    """Record goods received from a supplier: one batch per line, and its accepted weight into stock.

    `boxes` counts the returnable boxes that came with the delivery, per box type (D-122): they
    move from the supplier to the receiving location, in the same transaction as the stock.

    Everything is checked before anything is written; problems come back together, the header's on
    their field and each line's on `lines.<index>.<field>`. The receipt, its batches and its movements
    are saved in one transaction, so a refused receipt leaves nothing behind.

    Against a purchase order (D-076) the receipt may carry only some of its products and only part of
    their weight: the order stays open until every line is delivered or it is closed by hand. A line's
    product must be on the order; its accepted weight counts as received there.
    """
    errors = _header_errors(organization, supplier, location, received_on)
    order = _locked_order_to_receive(organization, supplier, purchase_order, errors) if purchase_order else None
    order_lines = {line.product_id: line for line in order.lines.all()} if order else {}
    if not lines:
        errors["lines"] = _("Ajoutez au moins un produit.")
    checked_lines = [_checked_line(organization, index, line, received_on, errors) for index, line in enumerate(lines)]
    if order:
        for index, values in enumerate(checked_lines):
            product = values["product"]
            if product is not None and product.pk not in order_lines:
                errors[line_error_key(index, "product")] = _(
                    "Ce produit n'est pas sur la commande d'achat %(number)s."
                ) % {"number": order.number}
            # The order says what was asked for; a delivery of part of it is not a difference.
            values["ordered_quantity"] = None
    box_counts = box_services.checked_box_counts(boxes, errors, prefix="boxes")
    if errors:
        raise ValidationError(errors)

    supplier_reference = supplier_reference.strip()
    receipt = GoodsReceipt.objects.create(
        organization=organization,
        number=_next_receipt_number(organization),
        supplier=supplier,
        location=location,
        purchase_order=order,
        received_on=received_on,
        supplier_reference=supplier_reference,
        with_vat=with_vat,
        notes=notes.strip(),
        created_by=actor,
    )
    # Received today: now. Typed later for an earlier day: noon of that day keeps the ledger in date order.
    occurred_at = (
        timezone.now()
        if received_on == timezone.localdate()
        else timezone.make_aware(dt.datetime.combine(received_on, dt.time(12, 0)))
    )
    saved: list[GoodsReceiptLine] = []
    for values in checked_lines:
        batch = inventory.create_batch(
            organization=organization,
            actor=actor,
            product=values["product"],
            supplier=supplier,
            received_on=received_on,
            unit_cost=values["unit_cost"],
            receipt_reference=supplier_reference or receipt.number,
            use_by=values["use_by"],
            bought_with_vat=with_vat,
        )
        line = GoodsReceiptLine.objects.create(
            organization=organization,
            receipt=receipt,
            product=values["product"],
            batch=batch,
            order_line=order_lines.get(values["product"].pk),
            ordered_quantity=values["ordered_quantity"],
            invoiced_quantity=values["invoiced_quantity"],
            accepted_quantity=values["accepted_quantity"],
            unit_cost=values["unit_cost"],
        )
        inventory.post_movement(
            organization=organization,
            actor=actor,
            kind=MovementKind.RECEIPT,
            batch=batch,
            quantity=values["accepted_quantity"],
            to_location=location,
            source=line,
            occurred_at=occurred_at,
        )
        if values["partner"] is not None:
            # Capital and rates come later (D-100); the stock is in, so the lot is open.
            partnerships.designate_partner(
                organization=organization, actor=actor, batch=batch, partner=values["partner"]
            )
        saved.append(line)
    if box_counts:
        box_services.post_box_counts(
            organization=organization,
            actor=actor,
            kind=box_services.BoxMovementKind.RECEIVE,
            counts=box_counts,
            from_holder=box_services.holder_for(organization=organization, supplier=supplier),
            to_holder=box_services.holder_for(organization=organization, location=location),
            source=receipt,
        )
    if order:
        refresh_order_status(order)
    audit.record(
        organization=organization,
        actor=actor,
        action="receipt.created",
        target=receipt,
        after=_snapshot(receipt, saved),
    )
    return receipt


# ---- Purchase orders, the "commande d'achat" (D-076) ----
# An order moves no stock and owes nothing; its receipts do. Its status follows them.


class OrderLineFields(TypedDict, total=False):
    product: "Product"
    ordered_quantity: Number
    unit_cost: Number


def _next_order_number(organization: Organization) -> str:
    DocumentCounter.objects.bulk_create(
        [DocumentCounter(organization=organization, kind=DocumentKind.PURCHASE_ORDER)], ignore_conflicts=True
    )
    counter = DocumentCounter.objects.select_for_update().get(
        organization=organization, kind=DocumentKind.PURCHASE_ORDER
    )
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"{ORDER_NUMBER_PREFIX}{counter.last_number:04d}"


def _order_snapshot(order: PurchaseOrder) -> dict[str, Any]:
    return {
        "number": order.number,
        "supplier": order.supplier.reference,
        "ordered_on": order.ordered_on.isoformat(),
        "expected_on": order.expected_on.isoformat() if order.expected_on else None,
        "status": order.status,
        "lines": {
            line.product.reference: {"ordered_quantity": str(line.ordered_quantity), "unit_cost": str(line.unit_cost)}
            for line in order.lines.select_related("product")
        },
    }


@transaction.atomic
def create_order(
    *,
    organization: Organization,
    actor: User | None,
    supplier: "Supplier",
    ordered_on: dt.date,
    lines: Sequence[OrderLineFields],
    expected_on: dt.date | None = None,
    notes: str = "",
) -> PurchaseOrder:
    """Record what we ask a supplier to deliver: products, weights and agreed prices.

    Every problem comes back at once, the header's on their field and each line's on
    `lines.<index>.<field>`. A product appears once per order.
    """
    errors: dict[str, str] = {}
    if supplier.organization_id != organization.pk:
        errors["supplier"] = _("Fournisseur inconnu.")
    elif not supplier.is_active:
        errors["supplier"] = _("Ce fournisseur est archivé.")
    if ordered_on > timezone.localdate():
        errors["ordered_on"] = _("La date de la commande d'achat ne peut pas être dans le futur.")
    if expected_on is not None and expected_on < ordered_on:
        errors["expected_on"] = _("La livraison prévue ne peut pas précéder la commande d'achat.")
    if not lines:
        errors["lines"] = _("Ajoutez au moins un produit.")
    checked_lines: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, line in enumerate(lines):
        product = line.get("product")
        checked: dict[str, Any] = {"product": product}
        if product is None or product.organization_id != organization.pk:
            errors[line_error_key(index, "product")] = _("Produit inconnu.")
        elif not product.is_active:
            errors[line_error_key(index, "product")] = _("Ce produit est archivé.")
        elif product.pk in seen:
            errors[line_error_key(index, "product")] = _("Ce produit est déjà sur la commande d'achat.")
        else:
            seen.add(product.pk)
        try:
            value: Any = line.get("ordered_quantity", "")
            checked["ordered_quantity"] = checked_quantity(value)
        except (ValueError, TypeError):
            errors[line_error_key(index, "ordered_quantity")] = _("Indiquez un poids net en kg, supérieur à zéro.")
        try:
            cost: Any = line.get("unit_cost", "")
            checked["unit_cost"] = checked_amount(cost)
        except (ValueError, TypeError):
            errors[line_error_key(index, "unit_cost")] = _("Indiquez un prix en DT par kg, au millime près.")
        if (
            "ordered_quantity" in checked
            and "unit_cost" in checked
            and line_total(checked["ordered_quantity"], checked["unit_cost"]) > MAX_AMOUNT
        ):
            errors[line_error_key(index, "unit_cost")] = _(
                "Le montant de cette ligne est trop grand : vérifiez le prix au kg."
            )
        checked_lines.append(checked)
    if errors:
        raise ValidationError(errors)

    order = PurchaseOrder.objects.create(
        organization=organization,
        number=_next_order_number(organization),
        supplier=supplier,
        ordered_on=ordered_on,
        expected_on=expected_on,
        notes=notes.strip(),
        created_by=actor,
    )
    PurchaseOrderLine.objects.bulk_create(
        [PurchaseOrderLine(organization=organization, order=order, **values) for values in checked_lines]
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="purchase_order.created",
        target=order,
        after=_order_snapshot(order),
    )
    return order


def _locked_order(order: PurchaseOrder) -> PurchaseOrder:
    return (
        PurchaseOrder.objects.select_for_update(of=("self",))
        .select_related("supplier")
        .prefetch_related("lines")
        .get(pk=order.pk)
    )


def _locked_order_to_receive(
    organization: Organization, supplier: "Supplier", order: PurchaseOrder, errors: dict[str, str]
) -> PurchaseOrder | None:
    """The order re-read under a row lock so two deliveries cannot be counted at once; problems go to `errors`."""
    if order.organization_id != organization.pk:
        errors["purchase_order"] = _("Commande d'achat inconnue.")
        return None
    locked = _locked_order(order)
    if locked.supplier_id != supplier.pk:
        errors["purchase_order"] = _("La commande d'achat %(number)s est d'un autre fournisseur.") % {
            "number": locked.number
        }
    elif locked.status not in RECEIVABLE_ORDER_STATUSES:
        errors["purchase_order"] = _("La commande d'achat %(number)s est %(status)s : on ne peut plus y recevoir.") % {
            "number": locked.number,
            "status": PurchaseOrderStatus(locked.status).label.lower(),
        }
    return locked


def refresh_order_status(order: PurchaseOrder) -> PurchaseOrder:
    """Set the status from what was received: nothing → open; every line in full → received; else partly.

    Only an order still waiting for goods changes; a closed or cancelled one stays as it was decided.
    """
    if order.status not in RECEIVABLE_ORDER_STATUSES:
        return order
    received = {
        row["order_line"]: row["total"]
        for row in GoodsReceiptLine.objects.filter(order_line__order=order)
        .values("order_line")
        .annotate(total=Sum("accepted_quantity"))
    }
    lines = list(order.lines.all())
    if lines and all(received.get(line.pk, Decimal("0")) >= line.ordered_quantity for line in lines):
        status = PurchaseOrderStatus.RECEIVED
    elif received:
        status = PurchaseOrderStatus.PARTLY_RECEIVED
    else:
        status = PurchaseOrderStatus.OPEN
    if status != order.status:
        order.status = status
        order.save(update_fields=["status", "updated_at"])
    return order


@transaction.atomic
def cancel_order(*, order: PurchaseOrder, actor: User | None) -> PurchaseOrder:
    """Cancel an order nothing was delivered against. Once goods came, it is closed instead."""
    order = _locked_order(order)
    if order.receipts.exists():
        raise ValidationError(
            _("La commande d'achat %(number)s a déjà reçu des marchandises : clôturez-la au lieu de l'annuler.")
            % {"number": order.number}
        )
    if order.status != PurchaseOrderStatus.OPEN:
        raise ValidationError(_("La commande d'achat %(number)s ne peut plus être annulée.") % {"number": order.number})
    before = _order_snapshot(order)
    order.status = PurchaseOrderStatus.CANCELLED
    order.closed_at = timezone.now()
    order.save(update_fields=["status", "closed_at", "updated_at"])
    audit.record(
        organization=order.organization,
        actor=actor,
        action="purchase_order.cancelled",
        target=order,
        before=before,
        after=_order_snapshot(order),
    )
    return order


@transaction.atomic
def close_order(*, order: PurchaseOrder, actor: User | None) -> PurchaseOrder:
    """Close an order partly delivered: the rest will not come. What was received stays as received."""
    order = _locked_order(order)
    if order.status != PurchaseOrderStatus.PARTLY_RECEIVED:
        raise ValidationError(
            _("Seule une commande d'achat reçue en partie peut être clôturée : %(number)s est %(status)s.")
            % {"number": order.number, "status": PurchaseOrderStatus(order.status).label.lower()}
        )
    before = _order_snapshot(order)
    order.status = PurchaseOrderStatus.CLOSED
    order.closed_at = timezone.now()
    order.save(update_fields=["status", "closed_at", "updated_at"])
    audit.record(
        organization=order.organization,
        actor=actor,
        action="purchase_order.closed",
        target=order,
        before=before,
        after=_order_snapshot(order),
    )
    return order


# ---- Supplier invoices and payments (P1-T08, D-043) ----
# A trade payable only: a partner's capital and profit share are separate balances (D-040, Phase 6).


def _next_document_number(organization: Organization, kind: DocumentKind, prefix: str, *, yearly: bool = False) -> str:
    """FF-0001 for invoices... per organization, taken under a row lock. With `yearly` (supplier payments,
    D-120) the number is RF-2026-0001 and restarts every year."""
    year = timezone.localdate().year if yearly else 0
    DocumentCounter.objects.bulk_create(
        [DocumentCounter(organization=organization, kind=kind, year=year)], ignore_conflicts=True
    )
    counter = DocumentCounter.objects.select_for_update().get(organization=organization, kind=kind, year=year)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"{prefix}{year}-{counter.last_number:04d}" if yearly else f"{prefix}{counter.last_number:04d}"


def _invoice_header_errors(
    organization: Organization, supplier: "Supplier", invoice_date: dt.date, due_date: dt.date
) -> dict[str, str]:
    errors: dict[str, str] = {}
    # An archived supplier is still owed what was bought from them: invoices and payments stay possible.
    if supplier.organization_id != organization.pk:
        errors["supplier"] = _("Fournisseur inconnu.")
    if invoice_date > timezone.localdate():
        errors["invoice_date"] = _("La date de facture ne peut pas être dans le futur.")
    if due_date < invoice_date:
        errors["due_date"] = _("L'échéance ne peut pas précéder la date de facture.")
    return errors


def _locked_receipts(
    organization: Organization,
    supplier: "Supplier",
    receipts: Sequence[GoodsReceipt],
    errors: dict[str, str],
    invoice: SupplierInvoice | None = None,
) -> list[GoodsReceipt]:
    """The receipts to charge, locked so two invoices cannot take the same one; problems go to `errors`."""
    if not receipts:
        errors["receipts"] = _("Choisissez au moins une réception.")
        return []
    ids = sorted({receipt.pk for receipt in receipts})
    locked = list(
        GoodsReceipt.objects.select_for_update(of=("self",))
        .filter(pk__in=ids)
        .order_by("received_on", "id")
        .select_related("invoice_link__invoice")
        .prefetch_related("lines")
    )
    problems: list[str] = []
    for receipt in locked:
        if receipt.organization_id != organization.pk:
            problems.append(_("Réception inconnue."))
        elif receipt.supplier_id != supplier.pk:
            problems.append(_("La réception %(number)s est d'un autre fournisseur.") % {"number": receipt.number})
        else:
            link = getattr(receipt, "invoice_link", None)
            if link is not None and (invoice is None or link.invoice_id != invoice.pk):
                problems.append(
                    _("La réception %(number)s est déjà sur la facture %(invoice)s.")
                    % {"number": receipt.number, "invoice": link.invoice.number}
                )
    if len(locked) != len(ids):
        problems.append(_("Réception inconnue."))
    if problems:
        errors["receipts"] = " ".join(dict.fromkeys(problems))
    return locked


def _set_receipts(invoice: SupplierInvoice, receipts: Sequence[GoodsReceipt]) -> None:
    """Charge exactly these receipts on the invoice, and keep its total as the sum of their amounts."""
    SupplierInvoiceReceipt.objects.filter(invoice=invoice).delete()
    links = [
        SupplierInvoiceReceipt(
            organization_id=invoice.organization_id,
            invoice=invoice,
            receipt=receipt,
            # What the supplier charges for the receipt: invoiced kg × cost per line (D-039).
            amount=selectors.receipt_totals(receipt)[0],
        )
        for receipt in receipts
    ]
    SupplierInvoiceReceipt.objects.bulk_create(links)
    invoice.total = sum((link.amount for link in links), Decimal("0.000"))
    invoice.save(update_fields=["total", "updated_at"])


def _invoice_snapshot(invoice: SupplierInvoice) -> dict[str, Any]:
    links = SupplierInvoiceReceipt.objects.filter(invoice=invoice).select_related("receipt").order_by("receipt_id")
    return {
        "number": invoice.number,
        "supplier": invoice.supplier.reference,
        "supplier_reference": invoice.supplier_reference,
        "invoice_date": invoice.invoice_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "status": invoice.status,
        "total": str(invoice.total),
        "receipts": {link.receipt.number: str(link.amount) for link in links},
    }


def _post(invoice: SupplierInvoice, actor: User | None) -> None:
    if invoice.total <= 0:
        raise ValidationError({"receipts": _("Le montant de la facture est nul : il n'y a rien à valider.")})
    invoice.status = SupplierInvoiceStatus.POSTED
    invoice.posted_at = timezone.now()
    invoice.posted_by = actor
    invoice.save(update_fields=["status", "posted_at", "posted_by", "updated_at"])
    # An invoice for the receipt of one port purchase is that purchase's invoice (its page links it, D-200).
    purchases = FieldPurchase.objects.filter(receipt__invoice_link__invoice=invoice, invoice__isnull=True)
    if len(purchases) == 1:
        purchases[0].invoice = invoice
        purchases[0].save(update_fields=["invoice", "updated_at"])
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="supplier_invoice.posted",
        target=invoice,
        after=_invoice_snapshot(invoice),
    )


def _locked_draft(invoice: SupplierInvoice) -> SupplierInvoice:
    """The invoice re-read under a row lock; refused unless it is still a draft."""
    locked = SupplierInvoice.objects.select_for_update().select_related("supplier", "organization").get(pk=invoice.pk)
    if locked.status != SupplierInvoiceStatus.DRAFT:
        raise ValidationError(
            _("La facture %(number)s est validée : elle ne se modifie plus.") % {"number": locked.number}
        )
    return locked


@transaction.atomic
def create_invoice(
    *,
    organization: Organization,
    actor: User | None,
    supplier: "Supplier",
    receipts: Sequence[GoodsReceipt],
    invoice_date: dt.date,
    due_date: dt.date,
    supplier_reference: str = "",
    notes: str = "",
    post: bool = False,
    apply_advances: bool = False,
) -> SupplierInvoice:
    """Record a supplier's invoice for some of their receipts, as a draft, or posted at once with `post`.

    Its amount is the receipts' invoiced amount; a receipt goes on one invoice only. Every problem comes
    back at once, on its field. With `post` and `apply_advances`, what the supplier was already given and is not
    on an invoice yet (cash given at the port, advances) pays it, oldest first (D-200).
    """
    errors = _invoice_header_errors(organization, supplier, invoice_date, due_date)
    locked = _locked_receipts(organization, supplier, receipts, errors) if "supplier" not in errors else []
    if errors:
        raise ValidationError(errors)
    invoice = SupplierInvoice.objects.create(
        organization=organization,
        number=_next_document_number(organization, DocumentKind.SUPPLIER_INVOICE, INVOICE_NUMBER_PREFIX),
        supplier=supplier,
        supplier_reference=supplier_reference.strip(),
        invoice_date=invoice_date,
        due_date=due_date,
        notes=notes.strip(),
        created_by=actor,
    )
    _set_receipts(invoice, locked)
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier_invoice.created",
        target=invoice,
        after=_invoice_snapshot(invoice),
    )
    if post:
        _post(invoice, actor)
        if apply_advances:
            _apply_advances(invoice, actor)
    return invoice


def _apply_advances(invoice: SupplierInvoice, actor: User | None) -> None:
    """Allocate the supplier's unallocated payments to a posted invoice, oldest first, up to what it still owes."""
    left = invoice.total - _paid_on(invoice)
    advances = selectors.payments_of(invoice.organization, supplier_id=invoice.supplier_id, unallocated=True)
    for payment in sorted(advances, key=lambda row: (row.paid_on, row.pk)):
        if left <= 0:
            break
        amount = min(left, getattr(payment, "unallocated_amount"))  # noqa: B009
        locked = SupplierPayment.objects.select_for_update().get(pk=payment.pk)
        before = _payment_snapshot(locked)
        _allocate(locked, actor, [(invoice, amount)])
        audit.record(
            organization=invoice.organization,
            actor=actor,
            action="supplier_payment.allocated",
            target=locked,
            before=before,
            after=_payment_snapshot(locked),
        )
        left -= amount


@transaction.atomic
def create_opening_invoice(
    *,
    organization: Organization,
    actor: User | None,
    supplier: "Supplier",
    amount: Number,
    invoice_date: dt.date,
    due_date: dt.date | None = None,
    supplier_reference: str = "",
    notes: str = "",
) -> SupplierInvoice:
    """What a supplier was already owed when the system started: a posted invoice with its amount typed and no
    receipts (D-112). It is a payable like any other: payments settle it, the balance counts it."""
    due_date = due_date or invoice_date
    errors = _invoice_header_errors(organization, supplier, invoice_date, due_date)
    try:
        total = checked_amount(amount)
    except (ValueError, TypeError):
        total = Decimal("0.000")
        errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    else:
        if total <= 0:
            errors["amount"] = _("Le montant doit être supérieur à 0.")
    if errors:
        raise ValidationError(errors)
    invoice = SupplierInvoice.objects.create(
        organization=organization,
        number=_next_document_number(organization, DocumentKind.SUPPLIER_INVOICE, INVOICE_NUMBER_PREFIX),
        supplier=supplier,
        supplier_reference=supplier_reference.strip(),
        invoice_date=invoice_date,
        due_date=due_date,
        notes=notes.strip(),
        total=total,
        is_opening=True,
        created_by=actor,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier_invoice.opening",
        target=invoice,
        after=_invoice_snapshot(invoice),
    )
    _post(invoice, actor)
    return invoice


@transaction.atomic
def update_invoice(
    *,
    invoice: SupplierInvoice,
    actor: User | None,
    receipts: Sequence[GoodsReceipt],
    invoice_date: dt.date,
    due_date: dt.date,
    supplier_reference: str = "",
    notes: str = "",
    post: bool = False,
) -> SupplierInvoice:
    """Change a draft invoice (its receipts, dates, reference, notes); with `post`, post it afterwards.

    The supplier does not change: a draft for the wrong supplier is deleted and typed again.
    """
    invoice = _locked_draft(invoice)
    organization = invoice.organization
    errors = _invoice_header_errors(organization, invoice.supplier, invoice_date, due_date)
    locked = _locked_receipts(organization, invoice.supplier, receipts, errors, invoice=invoice)
    if errors:
        raise ValidationError(errors)
    before = _invoice_snapshot(invoice)
    invoice.supplier_reference = supplier_reference.strip()
    invoice.invoice_date = invoice_date
    invoice.due_date = due_date
    invoice.notes = notes.strip()
    invoice.save(update_fields=["supplier_reference", "invoice_date", "due_date", "notes", "updated_at"])
    _set_receipts(invoice, locked)
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier_invoice.updated",
        target=invoice,
        before=before,
        after=_invoice_snapshot(invoice),
    )
    if post:
        _post(invoice, actor)
    return invoice


@transaction.atomic
def post_invoice(*, invoice: SupplierInvoice, actor: User | None) -> SupplierInvoice:
    """Post a draft: it is now owed to the supplier, counts in their balance and can be paid. Final."""
    invoice = _locked_draft(invoice)
    _post(invoice, actor)
    return invoice


@transaction.atomic
def delete_invoice(*, invoice: SupplierInvoice, actor: User | None) -> None:
    """Delete a draft invoice; its receipts can go on another invoice. A posted invoice is never deleted."""
    invoice = _locked_draft(invoice)
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="supplier_invoice.deleted",
        target=invoice,
        before=_invoice_snapshot(invoice),
    )
    invoice.delete()


class AllocationFields(TypedDict):
    invoice: SupplierInvoice
    amount: Number


def allocation_error_key(index: int, field: str) -> str:
    """Errors of an allocation are reported on `allocations.<index>.<field>`, like receipt lines."""
    return f"allocations.{index}.{field}"


def _paid_on(invoice: SupplierInvoice) -> Decimal:
    paid = SupplierPaymentAllocation.objects.filter(invoice=invoice, payment__voided_at__isnull=True).aggregate(
        total=Sum("amount")
    )["total"]
    released = RejectedRelease.objects.filter(invoice=invoice).aggregate(total=Sum("amount"))["total"]
    if released:
        paid = (paid or Decimal("0.000")) - released
    return paid if paid is not None else Decimal("0.000")


def _checked_allocations(
    organization: Organization,
    supplier: "Supplier",
    allocations: Sequence[AllocationFields],
    available: Decimal | None,
    errors: dict[str, str],
) -> list[tuple[SupplierInvoice, Decimal]]:
    """The allocations once checked, their invoices locked; every problem is added to `errors`.

    `available` is what the payment can still allocate, or None when its own amount was refused.
    """
    ids = sorted({line["invoice"].pk for line in allocations})
    invoices = {
        invoice.pk: invoice for invoice in SupplierInvoice.objects.select_for_update().filter(pk__in=ids).order_by("id")
    }
    checked: list[tuple[SupplierInvoice, Decimal]] = []
    seen: set[int] = set()
    for index, line in enumerate(allocations):
        invoice = invoices.get(line["invoice"].pk)
        invoice_key = allocation_error_key(index, "invoice")
        if invoice is None or invoice.organization_id != organization.pk:
            errors[invoice_key] = _("Facture inconnue.")
            continue
        if invoice.supplier_id != supplier.pk:
            errors[invoice_key] = _("Cette facture est d'un autre fournisseur.")
            continue
        if invoice.pk in seen:
            errors[invoice_key] = _("Cette facture est déjà dans la liste.")
            continue
        seen.add(invoice.pk)
        if invoice.status == SupplierInvoiceStatus.DRAFT:
            errors[invoice_key] = _("Cette facture est un brouillon : validez-la avant de la payer.")
            continue
        if invoice.status == SupplierInvoiceStatus.PAID:
            errors[invoice_key] = _("Cette facture est déjà payée.")
            continue
        amount_key = allocation_error_key(index, "amount")
        try:
            value: Any = line.get("amount", "")
            amount = checked_amount(value)
        except (ValueError, TypeError):
            errors[amount_key] = _("Indiquez un montant en DT, au millime près.")
            continue
        if amount == 0:
            errors[amount_key] = _("Le montant doit être supérieur à zéro.")
            continue
        remaining = invoice.total - _paid_on(invoice)
        if amount > remaining:
            errors[amount_key] = _("Il ne reste que %(remaining)s DT à payer sur cette facture.") % {
                "remaining": display_money(remaining)
            }
            continue
        checked.append((invoice, amount))
    allocated = sum((amount for _invoice, amount in checked), Decimal("0.000"))
    if available is not None and allocated > available:
        errors["allocations"] = _(
            "Les affectations (%(allocated)s DT) dépassent le montant disponible (%(available)s DT)."
        ) % {
            "allocated": display_money(allocated),
            "available": display_money(available),
        }
    return checked


def _allocate(
    payment: SupplierPayment, actor: User | None, allocations: Sequence[tuple[SupplierInvoice, Decimal]]
) -> None:
    for invoice, amount in allocations:
        SupplierPaymentAllocation.objects.create(
            organization_id=payment.organization_id, payment=payment, invoice=invoice, amount=amount, created_by=actor
        )
        paid = _paid_on(invoice)
        invoice.status = SupplierInvoiceStatus.PAID if paid >= invoice.total else SupplierInvoiceStatus.PARTLY_PAID
        invoice.save(update_fields=["status", "updated_at"])


def _payment_snapshot(payment: SupplierPayment) -> dict[str, Any]:
    allocations = SupplierPaymentAllocation.objects.filter(payment=payment).select_related("invoice").order_by("id")
    return {
        "number": payment.number,
        "supplier": payment.supplier.reference,
        "paid_on": payment.paid_on.isoformat(),
        "amount": str(payment.amount),
        "method": payment.method,
        "reference": payment.reference,
        "cash_on": payment.cash_on.isoformat() if payment.cash_on else None,
        "reason": payment.reason,
        "lines": [
            _payment_line_snapshot(line)
            for line in SupplierPaymentLine.objects.filter(payment=payment).select_related("instrument__bank")
        ],
        "allocations": [{"invoice": line.invoice.number, "amount": str(line.amount)} for line in allocations],
    }


def _payment_line_snapshot(line: SupplierPaymentLine) -> dict[str, Any]:
    row: dict[str, Any] = {"method": line.method, "amount": str(line.amount), "reference": line.reference}
    if line.instrument is not None:
        row["number"] = line.instrument.number
        row["bank"] = line.instrument.bank.code if line.instrument.bank else ""
        row["due_on"] = line.instrument.due_on.isoformat()
    return row


def _checked_plan_lines(
    organization: Organization,
    supplier: "Supplier",
    plan_lines: Sequence[SupplierPaymentPlanLine],
    allocations: Sequence[tuple[SupplierInvoice, Decimal]],
    errors: dict[str, str],
) -> list[SupplierPaymentPlanLine]:
    """The plan lines a payment settles, locked, once checked; problems go on `plan_lines.<index>`."""
    ids = [line.pk for line in plan_lines]
    found = {
        line.pk: line
        for line in SupplierPaymentPlanLine.objects.select_for_update(of=("self",))
        .select_related("invoice")
        .filter(pk__in=sorted(set(ids)), organization=organization)
        .order_by("id")
    }
    allocated = {invoice.pk for invoice, amount in allocations if amount > 0}
    checked: list[SupplierPaymentPlanLine] = []
    for index, pk in enumerate(ids):
        key = f"plan_lines.{index}"
        line = found.get(pk)
        if line is None:
            errors[key] = _("Ligne de règlement inconnue.")
        elif ids.index(pk) != index:
            errors[key] = _("Cette ligne de règlement est déjà dans la liste.")
        elif line.invoice.supplier_id != supplier.pk:
            errors[key] = _("Cette ligne de règlement est d'un autre fournisseur.")
        elif line.status != PlanLineStatus.OPEN:
            errors[key] = _("Cette ligne de règlement n'est plus planifiée.")
        elif line.invoice_id not in allocated:
            errors[key] = _("Affectez ce paiement à la facture de la ligne de règlement.")
        else:
            checked.append(line)
    return checked


def _oldest_due_first(
    organization: Organization, supplier: "Supplier", available: Decimal | None
) -> list[AllocationFields]:
    """`available` spread over the supplier's posted invoices still to pay, the one due first first (D-208)."""
    if available is None:
        return []
    rows: list[AllocationFields] = []
    left = available
    invoices = SupplierInvoice.objects.for_organization(organization).filter(
        supplier=supplier, status__in=(SupplierInvoiceStatus.POSTED, SupplierInvoiceStatus.PARTLY_PAID)
    )
    for invoice in invoices.order_by("due_date", "invoice_date", "id"):
        if left <= 0:
            break
        part = min(left, invoice.total - _paid_on(invoice))
        if part > 0:
            rows.append({"invoice": invoice, "amount": part})
            left -= part
    return rows


class PaymentLineFields(TypedDict, total=False):
    """One means of a supplier règlement (D-208). Our cheque or traite gives its number, the bank it is drawn on
    and its échéance (`due_on`); other methods may give a reference."""

    method: str
    amount: Number
    reference: str
    number: str
    bank: "Bank | None"
    due_on: dt.date | None
    # The account the money leaves (D-219): a Caisse for cash, a bank account for the rest (for our cheque or
    # traite, the one the bank will debit). Empty: the Caisse, the account of the effet's bank, the main one.
    account: "TreasuryAccount | None"


# At most this many lines in one règlement.
MAX_PAYMENT_LINES = 50


def _checked_settlement_lines(
    organization: Organization,
    paid_on: dt.date,
    lines: Sequence[PaymentLineFields],
    errors: dict[str, str],
    *,
    partial: bool,
) -> list[tuple[str, Decimal, PaymentLineFields]]:
    """The règlement's lines with their amount checked; errors on `lines.<index>.<field>`. `partial`: the effet's
    number, bank and échéance may be missing (one line made of the older single fields, to complete later)."""
    checked: list[tuple[str, Decimal, PaymentLineFields]] = []
    if not lines:
        errors["lines"] = _("Ajoutez au moins un moyen de paiement.")
        return checked
    if len(lines) > MAX_PAYMENT_LINES:
        errors["lines"] = _("%(count)s moyens de paiement au plus par règlement.") % {"count": MAX_PAYMENT_LINES}
        return checked
    taken: list[tuple[str, int | None, str]] = []
    for index, line in enumerate(lines):
        method = line.get("method", "")
        if method not in LINE_METHODS:
            errors[line_error_key(index, "method")] = _("Mode de paiement inconnu.")
        try:
            value = checked_amount(line.get("amount", ""))
            if value <= 0:
                errors[line_error_key(index, "amount")] = _("Le montant doit être supérieur à zéro.")
        except (ValueError, TypeError):
            value = ZERO
            errors[line_error_key(index, "amount")] = _("Indiquez un montant en DT, au millime près.")
        if method not in LINE_METHODS:
            continue
        if method in INSTRUMENT_METHODS:
            bank = line.get("bank")
            number = line.get("number", "")
            found = treasury.instrument_errors(
                organization=organization,
                direction="issued",
                kind=method,
                number=number,
                bank=bank,
                issued_on=paid_on,
                due_on=line.get("due_on"),
                taken=taken,
                partial=partial,
            )
            for field, message in found.items():
                errors[line_error_key(index, field)] = message
            taken.append((method, bank.pk if bank else None, number.strip()))
        message = treasury.line_account_error(organization, method, line.get("account"))
        if message:
            errors[line_error_key(index, "account")] = message
        checked.append((method, value, line))
    return checked


def _write_lines(
    payment: SupplierPayment,
    actor: User | None,
    checked: Sequence[tuple[str, Decimal, PaymentLineFields]],
    *,
    partial: bool,
    post_to_treasury: bool = True,
) -> None:
    """Write the règlement's lines; each cheque or traite becomes an effet issued to the supplier, the money of the
    others leaves its account at once (D-219)."""
    for method, value, line in checked:
        instrument = None
        if method in INSTRUMENT_METHODS:
            instrument = treasury.register_instrument(
                organization=payment.organization,
                actor=actor,
                direction="issued",
                kind=method,
                # A cheque given without its number keeps the règlement's until the office completes it.
                number=line.get("number", "").strip() or payment.number,
                bank=line.get("bank"),
                amount=value,
                issued_on=payment.paid_on,
                due_on=line.get("due_on"),
                supplier=payment.supplier,
                source_number=payment.number,
                partial=partial,
                account=line.get("account"),
            )
        row = SupplierPaymentLine.objects.create(
            organization_id=payment.organization_id,
            payment=payment,
            method=method,
            amount=value,
            reference=(line.get("reference", "") if instrument is None else "").strip()[:50],
            instrument=instrument,
        )
        if instrument is None and post_to_treasury:
            _post_line_money(payment, row, line.get("account"), actor)


# The treasury movement of a supplier règlement line paid in cash, by transfer or by card (D-219).
PAYMENT_LINE_SOURCE = "purchasing.payment_line"


def _post_line_money(
    payment: SupplierPayment, line: SupplierPaymentLine, account: "TreasuryAccount | None", actor: User | None
) -> None:
    """The money of a line leaves an account the day it was paid: the one chosen, else the Caisse for cash, the
    main bank account for a transfer or a card. Our cheque or traite leaves only when the bank debits it."""
    organization = payment.organization
    treasury.post_movement(
        organization=organization,
        account=treasury.line_account(organization, line.method, account),
        day=payment.paid_on,
        amount=-line.amount,
        kind="supplier_payment",
        label=f"{payment.number} · {payment.supplier.name}",
        reference=payment.number,
        source=PAYMENT_LINE_SOURCE,
        source_id=line.pk,
        actor=actor,
    )


def _reverse_line_money(payment: SupplierPayment, actor: User | None, day: dt.date) -> None:
    treasury.reverse_movements(
        organization=payment.organization,
        source=PAYMENT_LINE_SOURCE,
        source_ids=list(
            SupplierPaymentLine.objects.filter(payment=payment, instrument__isnull=True).values_list("pk", flat=True)
        ),
        day=day,
        actor=actor,
        label=_("Annulation"),
    )


def post_treasury_history(*, organization: Organization) -> None:
    """Write the treasury movements of the supplier règlements recorded before the accounts existed (D-219), and
    undo those of the voided ones on the day they were voided. The money given at the port is the driver's (written
    with the driver's day). Safe to run again."""
    done = treasury.posted_source_ids(organization, PAYMENT_LINE_SOURCE)
    lines = (
        SupplierPaymentLine.objects.filter(
            organization=organization, instrument__isnull=True, payment__field_purchase_payment__isnull=True
        )
        .select_related("payment__organization", "payment__supplier", "payment__created_by")
        .order_by("id")
    )
    for line in lines:
        payment = line.payment
        if line.pk not in done:
            _post_line_money(payment, line, None, payment.created_by)
        if payment.voided_at is not None:
            _reverse_line_money(payment, payment.voided_by, timezone.localtime(payment.voided_at).date())


@transaction.atomic
def record_payment(
    *,
    organization: Organization,
    actor: User | None,
    supplier: "Supplier",
    paid_on: dt.date,
    amount: Number | None = None,
    method: str = "",
    lines: Sequence[PaymentLineFields] | None = None,
    allocations: Sequence[AllocationFields] | None = (),
    reference: str = "",
    notes: str = "",
    reason: str = "",
    cash_on: dt.date | None = None,
    plan_line: SupplierPaymentPlanLine | None = None,
    plan_lines: Sequence[SupplierPaymentPlanLine] = (),
    post_to_treasury: bool = True,
) -> SupplierPayment:
    """Record money paid to a supplier and the posted invoices it settles (D-043, D-208).

    `lines` gives its means (some cash, our cheques, traites, a transfer...): each cheque or traite becomes an
    effet issued, followed by the treasury until the bank debits it. Without `lines`, `amount`, `method`,
    `reference` and `cash_on` make its one line (the port purchase, a receipt paid at once, the older form): its
    effet may lack its bank, to complete later. With `lines`, an `amount` given must equal their sum.

    The allocations may cover all of the amount, part of it or none: what is left is an advance, already
    deducted from the supplier balance, to allocate later (`allocate_payment`). None spreads the amount over the
    supplier's invoices still to pay, the one due first first. An allocation never goes beyond what is left to
    pay on its invoice. Every problem comes back at once, on its field.

    `plan_lines` (or one `plan_line`) are open plan lines (D-192) this payment settles: each one's invoice must be
    among the allocations (with an amount) and its supplier the payment's; they become `paid`, linked to it.

    The money of its cash, transfer and card lines leaves our accounts at once (D-219); `post_to_treasury` False
    leaves that to the caller (the port purchase: the driver's money).
    """
    errors: dict[str, str] = {}
    if supplier.organization_id != organization.pk:
        errors["supplier"] = _("Fournisseur inconnu.")
    if paid_on > timezone.localdate():
        errors["paid_on"] = _("La date du paiement ne peut pas être dans le futur.")
    partial = lines is None
    if lines is None:
        # One line made of the single fields; its errors stay on `amount`, `method` and `cash_on`.
        single: dict[str, str] = {}
        one_line: PaymentLineFields = {
            "method": method,
            "amount": amount if amount is not None else "",
            "reference": reference,
            "number": reference,
            "due_on": cash_on,
        }
        if cash_on is not None and cash_on < paid_on:
            errors["cash_on"] = _("Le jour d'encaissement ne peut pas précéder le paiement.")
        checked = _checked_settlement_lines(organization, paid_on, [one_line], single, partial=True)
        for key, message in single.items():
            field = key.removeprefix("lines.0.")
            errors.setdefault({"due_on": "cash_on", "number": "reference"}.get(field, field), message)
    else:
        checked = _checked_settlement_lines(organization, paid_on, lines, errors, partial=False)
        if amount is not None and not errors:
            try:
                if checked_amount(amount) != sum((value for _method, value, _line in checked), ZERO):
                    errors["amount"] = _("Le total ne correspond pas à la somme des moyens de paiement.")
            except (ValueError, TypeError):
                errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    total: Decimal | None = None
    if not any(key == "amount" or key.endswith(".amount") for key in errors) and checked:
        total = sum((value for _method, value, _line in checked), ZERO)
    if "supplier" in errors:
        allocated: list[tuple[SupplierInvoice, Decimal]] = []
    else:
        requested = _oldest_due_first(organization, supplier, total) if allocations is None else allocations
        allocated = _checked_allocations(organization, supplier, requested, total, errors)
    named = [*plan_lines, *([plan_line] if plan_line is not None else [])]
    settled = _checked_plan_lines(organization, supplier, named, allocated, errors) if named else []
    if plan_line is not None and "plan_lines.0" in errors and not plan_lines:
        errors["plan_line"] = errors.pop("plan_lines.0")
    if errors:
        raise ValidationError(errors)
    assert total is not None  # an amount error would have been raised above
    methods = {line_method for line_method, _value, _line in checked}
    only = checked[0][2] if len(checked) == 1 else None
    payment = SupplierPayment.objects.create(
        organization=organization,
        number=_next_document_number(organization, DocumentKind.SUPPLIER_PAYMENT, PAYMENT_NUMBER_PREFIX, yearly=True),
        supplier=supplier,
        paid_on=paid_on,
        amount=total,
        method=methods.pop() if len(methods) == 1 else PaymentMethod.MIXED,
        reference=_header_reference(reference if partial else None, checked),
        cash_on=only.get("due_on") if only is not None and checked[0][0] in INSTRUMENT_METHODS else None,
        notes=notes.strip(),
        reason=reason.strip(),
        created_by=actor,
    )
    _write_lines(payment, actor, checked, partial=partial, post_to_treasury=post_to_treasury)
    _allocate(payment, actor, allocated)
    for line in settled:
        line.status = PlanLineStatus.PAID
        line.payment = payment
        line.save(update_fields=["status", "payment", "updated_at"])
        audit.record(
            organization=organization,
            actor=actor,
            action="supplier_plan_line.paid",
            target=line,
            after={"invoice": line.invoice.number, "amount": str(line.amount), "payment": payment.number},
        )
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier_payment.recorded",
        target=payment,
        after=_payment_snapshot(payment),
    )
    return payment


def _header_reference(reference: str | None, checked: Sequence[tuple[str, Decimal, PaymentLineFields]]) -> str:
    """The règlement's own reference, shown in its list: the one typed, else that of its only line (a transfer
    reference, a cheque number); none for several lines, each keeping its own."""
    if reference is None:
        reference = ""
        if len(checked) == 1:
            line = checked[0][2]
            reference = line.get("number", "") if checked[0][0] in INSTRUMENT_METHODS else line.get("reference", "")
    return reference.strip()[:50]


@transaction.atomic
def allocate_payment(
    *, payment: SupplierPayment, actor: User | None, allocations: Sequence[AllocationFields]
) -> SupplierPayment:
    """Allocate the part of a payment not allocated yet (an advance) to posted invoices of its supplier."""
    payment = SupplierPayment.objects.select_for_update().select_related("supplier", "organization").get(pk=payment.pk)
    if payment.voided_at is not None:
        raise ValidationError(_("Ce règlement est annulé."))
    errors: dict[str, str] = {}
    if not allocations:
        errors["allocations"] = _("Choisissez au moins une facture.")
    available = payment.amount - _rejected_of(payment) - _allocated_of(payment)
    checked = _checked_allocations(payment.organization, payment.supplier, allocations, available, errors)
    if errors:
        raise ValidationError(errors)
    before = _payment_snapshot(payment)
    _allocate(payment, actor, checked)
    audit.record(
        organization=payment.organization,
        actor=actor,
        action="supplier_payment.allocated",
        target=payment,
        before=before,
        after=_payment_snapshot(payment),
    )
    return payment


def _invoice_status_from_payments(invoice: SupplierInvoice) -> str:
    paid = _paid_on(invoice)
    if paid >= invoice.total:
        return SupplierInvoiceStatus.PAID
    return SupplierInvoiceStatus.PARTLY_PAID if paid > 0 else SupplierInvoiceStatus.POSTED


@transaction.atomic
def void_payment(*, payment: SupplierPayment, actor: User | None, reason: str) -> SupplierPayment:
    """Cancel a supplier règlement typed by mistake (D-211): it stays, marked voided with who, when and why. Its
    allocations stop counting (its invoices owe again), the plan lines it paid are planned again and its cheques
    and traites are cancelled. Never deleted.

    Refused once one of our effets moved on (debited, rejected: the bank handled it), and for the money given at
    the port with a purchase (corrected on the purchase, D-176).
    """
    payment = SupplierPayment.objects.select_for_update().select_related("organization", "supplier").get(pk=payment.pk)
    if payment.voided_at is not None:
        raise ValidationError(_("Ce règlement est déjà annulé."))
    reason = reason.strip()[:255]
    if not reason:
        raise ValidationError({"reason": _("Indiquez la raison de l'annulation.")})
    if FieldPurchasePayment.objects.filter(supplier_payment=payment).exists():
        raise ValidationError(_("Ce règlement vient d'un achat terrain : corrigez l'achat."))
    instrument_ids = [
        pk for pk in SupplierPaymentLine.objects.filter(payment=payment).values_list("instrument_id", flat=True) if pk
    ]
    if instrument_ids:
        treasury.cancel_instruments(
            instrument_ids=instrument_ids,
            actor=actor,
            happened_on=timezone.localdate(),
            note=_("Règlement %(number)s annulé : %(reason)s") % {"number": payment.number, "reason": reason},
        )
    _reverse_line_money(payment, actor, timezone.localdate())
    invoice_ids = sorted(
        set(SupplierPaymentAllocation.objects.filter(payment=payment).values_list("invoice_id", flat=True))
    )
    payment.voided_at = timezone.now()
    payment.voided_by = actor
    payment.void_reason = reason
    payment.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    for invoice in SupplierInvoice.objects.select_for_update().filter(pk__in=invoice_ids).order_by("id"):
        status = _invoice_status_from_payments(invoice)
        if status != invoice.status:
            invoice.status = status
            invoice.save(update_fields=["status", "updated_at"])
    reopened = SupplierPaymentPlanLine.objects.filter(payment=payment, status=PlanLineStatus.PAID).update(
        status=PlanLineStatus.OPEN, payment=None, updated_at=timezone.now()
    )
    audit.record(
        organization=payment.organization,
        actor=actor,
        action="supplier_payment.voided",
        target=payment,
        after={"reason": reason, "amount": str(payment.amount), "plan_lines_reopened": reopened},
    )
    return payment


# ---- Paid, planned or undefined: the settlement plan of an invoice (P3-T16a, D-192) ----
# A plan is not a payment: nothing below touches a payment, an allocation or the supplier balance.


class PlanLineFields(TypedDict, total=False):
    amount: Number
    method: str
    planned_on: dt.date
    reference: str
    cash_on: dt.date | None


def plan_error_key(index: int, field: str) -> str:
    """Errors of a plan line are reported on `lines.<index>.<field>`."""
    return f"lines.{index}.{field}"


def _plan_snapshot(invoice: SupplierInvoice) -> dict[str, Any]:
    lines = SupplierPaymentPlanLine.objects.filter(invoice=invoice, status=PlanLineStatus.OPEN).order_by(
        "planned_on", "id"
    )
    return {
        "invoice": invoice.number,
        "lines": [
            {
                "amount": str(line.amount),
                "method": line.method,
                "planned_on": line.planned_on.isoformat(),
                "reference": line.reference,
                "cash_on": line.cash_on.isoformat() if line.cash_on else None,
            }
            for line in lines
        ],
    }


@transaction.atomic
def set_payment_plan(
    *, invoice: SupplierInvoice, actor: User | None, lines: Sequence[PlanLineFields]
) -> SupplierInvoice:
    """Replace the open plan lines of a posted invoice (an empty list clears the plan).

    Their sum may not exceed what is left to pay (total - allocated). Lines already paid stay as they are; the
    replaced open lines are kept as `cancelled`. Never touches the supplier balance.
    """
    invoice = SupplierInvoice.objects.select_for_update().select_related("organization").get(pk=invoice.pk)
    errors: dict[str, str] = {}
    if invoice.status == SupplierInvoiceStatus.DRAFT:
        errors["invoice"] = _("Cette facture est un brouillon : validez-la avant de planifier son règlement.")
    elif invoice.status == SupplierInvoiceStatus.PAID:
        errors["invoice"] = _("Cette facture est déjà payée.")
    remaining = invoice.total - _paid_on(invoice)
    checked: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        amount = ZERO
        try:
            value: Any = line.get("amount", "")
            amount = checked_amount(value)
            if amount == 0:
                errors[plan_error_key(index, "amount")] = _("Le montant doit être supérieur à zéro.")
        except (ValueError, TypeError):
            errors[plan_error_key(index, "amount")] = _("Indiquez un montant en DT, au millime près.")
        method = line.get("method", "")
        if method not in LINE_METHODS:
            errors[plan_error_key(index, "method")] = _("Mode de paiement inconnu.")
        planned_on = line.get("planned_on")
        if planned_on is None:
            errors[plan_error_key(index, "planned_on")] = _("Indiquez la date prévue.")
        cash_on = line.get("cash_on")
        if cash_on is not None and planned_on is not None and cash_on < planned_on:
            errors[plan_error_key(index, "cash_on")] = _("Le jour d'encaissement ne peut pas précéder la date prévue.")
        checked.append(
            {
                "amount": amount,
                "method": method,
                "planned_on": planned_on,
                "reference": (line.get("reference") or "").strip(),
                "cash_on": cash_on,
            }
        )
    if not errors:
        planned = sum((row["amount"] for row in checked), ZERO)
        if planned > remaining:
            errors["lines"] = _("Les lignes (%(planned)s DT) dépassent ce qu'il reste à payer (%(remaining)s DT).") % {
                "planned": display_money(planned),
                "remaining": display_money(remaining),
            }
    if errors:
        raise ValidationError(errors)
    before = _plan_snapshot(invoice)
    SupplierPaymentPlanLine.objects.filter(invoice=invoice, status=PlanLineStatus.OPEN).update(
        status=PlanLineStatus.CANCELLED, updated_at=timezone.now()
    )
    for row in checked:
        SupplierPaymentPlanLine.objects.create(
            organization=invoice.organization, invoice=invoice, created_by=actor, **row
        )
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="supplier_invoice.plan_set",
        target=invoice,
        before=before,
        after=_plan_snapshot(invoice),
    )
    return invoice


@transaction.atomic
def cancel_plan_line(*, line: SupplierPaymentPlanLine, actor: User | None) -> SupplierPaymentPlanLine:
    """Cancel an open plan line: its amount goes back to "undefined". A paid line stays (400)."""
    line = SupplierPaymentPlanLine.objects.select_for_update().select_related("invoice", "organization").get(pk=line.pk)
    if line.status != PlanLineStatus.OPEN:
        raise ValidationError({"line": _("Seule une ligne planifiée peut être annulée.")})
    before = _plan_snapshot(line.invoice)
    line.status = PlanLineStatus.CANCELLED
    line.save(update_fields=["status", "updated_at"])
    audit.record(
        organization=line.organization,
        actor=actor,
        action="supplier_plan_line.cancelled",
        target=line,
        before=before,
        after=_plan_snapshot(line.invoice),
    )
    return line


# ---- Buying at the port, the "achat terrain" (P3-T12, D-176) ----
# A driver's purchase counts only once the owner or the manager validates it: then it becomes a receipt (stock),
# a posted invoice (what is owed for the kg received, due by the deal) and payments (what was given at the port).

FIELD_PURCHASE_NUMBER_PREFIX = "AT-"


class FieldLineFields(TypedDict, total=False):
    product: "Product | None"
    # The name the driver typed for a product not in the catalogue yet.
    proposed_product: str
    declared_quantity: Number
    received_quantity: Number | None
    unit_cost: Number
    partner: "Supplier | None"


class FieldPaymentFields(TypedDict, total=False):
    method: str
    amount: Number
    reference: str
    cash_on: dt.date | None


class FieldPurchaseFields(TypedDict, total=False):
    """What a purchase says. The office alone sets `location`, `boxes`, the received kg and the partners."""

    supplier: "Supplier | None"
    proposed_supplier: str
    proposed_supplier_phone: str
    bought_on: dt.date
    terms: str
    due_days: int
    supplier_reference: str
    notes: str
    lines: Sequence[FieldLineFields]
    payments: Sequence[FieldPaymentFields]
    location: "StockLocation | None"
    boxes: Mapping[str, int]


def payment_error_key(index: int, field: str) -> str:
    """Errors of a sum given at the port are reported on `payments.<index>.<field>`, like lines."""
    return f"payments.{index}.{field}"


def _checked_payment_lines(
    payments: Sequence[FieldPaymentFields], bought_on: dt.date, errors: dict[str, str]
) -> list[dict[str, Any]]:
    """Check the sums given with a purchase or a receipt (D-176, D-192); problems go on `payments.<index>.<field>`."""
    checked_payments: list[dict[str, Any]] = []
    for index, payment in enumerate(payments):
        method = payment.get("method", "")
        if method not in LINE_METHODS:
            errors[payment_error_key(index, "method")] = _("Mode de paiement inconnu.")
        values: dict[str, Any] = {
            "method": method,
            "reference": payment.get("reference", "").strip()[:50],
            "cash_on": payment.get("cash_on"),
        }
        try:
            amount: Any = payment.get("amount", "")
            values["amount"] = checked_amount(amount)
            if values["amount"] == 0:
                errors[payment_error_key(index, "amount")] = _("Le montant doit être supérieur à zéro.")
        except (ValueError, TypeError):
            errors[payment_error_key(index, "amount")] = _("Indiquez un montant en DT, au millime près.")
        if values["cash_on"] is not None and values["cash_on"] < bought_on:
            errors[payment_error_key(index, "cash_on")] = _("Le jour d'encaissement ne peut pas précéder l'achat.")
        checked_payments.append(values)
    return checked_payments


def due_date_of(bought_on: dt.date, terms: str, due_days: int) -> dt.date:
    """When a purchase is due by its deal: the day itself (comptant), N days later, or the end of its month + N days."""
    if terms == PaymentTerms.DAYS:
        return bought_on + dt.timedelta(days=due_days)
    if terms == PaymentTerms.MONTH_END:
        next_month = (bought_on.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
        return next_month - dt.timedelta(days=1) + dt.timedelta(days=due_days)
    return bought_on


def _checked_field_purchase(organization: Organization, fields: FieldPurchaseFields) -> dict[str, Any]:
    """The purchase's values once checked. Every problem comes back at once, the header's on their field, a line's
    on `lines.<index>.<field>`, a payment's on `payments.<index>.<field>`."""
    errors: dict[str, str] = {}
    supplier = fields.get("supplier")
    proposed_supplier = fields.get("proposed_supplier", "").strip()
    if supplier is not None:
        if supplier.organization_id != organization.pk:
            errors["supplier"] = _("Fournisseur inconnu.")
        elif not supplier.is_active:
            errors["supplier"] = _("Ce fournisseur est archivé.")
        # A supplier picked from the list replaces a name typed earlier.
        proposed_supplier = ""
    elif not proposed_supplier:
        errors["supplier"] = _("Choisissez le fournisseur, ou donnez le nom d'un nouveau.")
    bought_on = fields["bought_on"]
    if bought_on > timezone.localdate():
        errors["bought_on"] = _("La date de l'achat ne peut pas être dans le futur.")
    terms = fields.get("terms", PaymentTerms.CASH)
    due_days = fields.get("due_days", 0)
    if terms not in PaymentTerms.values:
        errors["terms"] = _("Accord de paiement inconnu.")
    elif not 0 <= due_days <= 365:
        errors["due_days"] = _("Indiquez un nombre de jours entre 0 et 365.")
    elif terms == PaymentTerms.DAYS and due_days == 0:
        errors["due_days"] = _("Indiquez dans combien de jours l'achat est payé.")
    if terms == PaymentTerms.CASH:
        due_days = 0
    location = fields.get("location")
    if location is not None and (location.organization_id != organization.pk or not location.is_active):
        errors["location"] = _("Cet emplacement est inconnu ou archivé.")

    lines = fields.get("lines", ())
    if not lines:
        errors["lines"] = _("Ajoutez au moins un produit.")
    checked_lines: list[dict[str, Any]] = []
    for index, line in enumerate(lines):
        product = line.get("product")
        proposed_product = line.get("proposed_product", "").strip()
        if product is not None:
            proposed_product = ""
            if product.organization_id != organization.pk:
                errors[line_error_key(index, "product")] = _("Produit inconnu.")
            elif not product.is_active:
                errors[line_error_key(index, "product")] = _("Ce produit est archivé.")
        elif not proposed_product:
            errors[line_error_key(index, "product")] = _("Choisissez le produit, ou donnez le nom d'un nouveau.")
        partner = line.get("partner")
        if partner is not None and (partner.organization_id != organization.pk or not partner.is_active):
            errors[line_error_key(index, "partner")] = _("Ce fournisseur est inconnu ou archivé.")
        checked: dict[str, Any] = {
            "product": product,
            "proposed_product": proposed_product[:150],
            "partner": partner,
            "received_quantity": None,
        }
        try:
            declared: Any = line.get("declared_quantity", "")
            checked["declared_quantity"] = checked_quantity(declared)
        except (ValueError, TypeError):
            errors[line_error_key(index, "declared_quantity")] = _("Indiquez un poids net en kg, supérieur à zéro.")
        received = line.get("received_quantity")
        if received not in (None, ""):
            try:
                checked["received_quantity"] = checked_quantity(received)
            except (ValueError, TypeError):
                errors[line_error_key(index, "received_quantity")] = _(
                    "Indiquez un poids net en kg, supérieur à zéro, ou laissez vide."
                )
        try:
            cost: Any = line.get("unit_cost", "")
            checked["unit_cost"] = checked_amount(cost)
        except (ValueError, TypeError):
            errors[line_error_key(index, "unit_cost")] = _("Indiquez un prix en DT par kg, au millime près.")
        biggest = max(checked.get("declared_quantity", ZERO), checked["received_quantity"] or ZERO)
        if "unit_cost" in checked and line_total(biggest, checked["unit_cost"]) > MAX_AMOUNT:
            errors[line_error_key(index, "unit_cost")] = _(
                "Le montant de cette ligne est trop grand : vérifiez le prix au kg."
            )
        checked_lines.append(checked)

    checked_payments = _checked_payment_lines(fields.get("payments", ()), bought_on, errors)

    # More given than the purchase is worth is a typing mistake, not an advance: refused. The ceiling takes the
    # bigger of the driver's kg and the kg received per line, so a lot counted lighter at the office keeps what was
    # really given; the part beyond what is owed then stays an advance at validation.
    if not errors and checked_payments:
        ceiling = sum(
            (
                line_total(max(line["declared_quantity"], line["received_quantity"] or ZERO), line["unit_cost"])
                for line in checked_lines
            ),
            ZERO,
        )
        given = sum((payment["amount"] for payment in checked_payments), ZERO)
        if given > ceiling:
            errors[payment_error_key(len(checked_payments) - 1, "amount")] = _(
                "L'argent donné (%(given)s DT) dépasse le montant de l'achat (%(total)s DT) : vérifiez les montants."
            ) % {"given": display_money(given), "total": display_money(ceiling)}

    boxes = box_services.checked_box_counts(fields.get("boxes"), errors, prefix="boxes")
    if errors:
        raise ValidationError(errors)
    return {
        "supplier": supplier,
        "proposed_supplier": proposed_supplier[:150],
        "proposed_supplier_phone": fields.get("proposed_supplier_phone", "").strip()[:30] if supplier is None else "",
        "bought_on": bought_on,
        "terms": terms,
        "due_days": due_days,
        "supplier_reference": fields.get("supplier_reference", "").strip()[:50],
        "notes": fields.get("notes", "").strip(),
        "location": location,
        "boxes": boxes,
        "lines": checked_lines,
        "payments": checked_payments,
    }


def field_purchase_snapshot(purchase: FieldPurchase) -> dict[str, Any]:
    """Everything a purchase says, as plain values: what a revision keeps, and what two revisions are compared on."""
    lines = list(purchase.lines.select_related("product", "partner").order_by("id"))
    payments = list(purchase.payments.order_by("id"))

    def ref(row: Any) -> dict[str, Any] | None:
        return None if row is None else {"id": row.pk, "name": row.name}

    return {
        "supplier": ref(purchase.supplier),
        "proposed_supplier": purchase.proposed_supplier,
        "proposed_supplier_phone": purchase.proposed_supplier_phone,
        "bought_on": purchase.bought_on.isoformat(),
        "terms": purchase.terms,
        "due_days": purchase.due_days,
        "supplier_reference": purchase.supplier_reference,
        "notes": purchase.notes,
        "location": ref(purchase.location),
        "boxes": dict(purchase.boxes),
        "lines": [
            {
                "product": ref(line.product),
                "proposed_product": line.proposed_product,
                "declared_quantity": str(line.declared_quantity),
                "received_quantity": str(line.received_quantity) if line.received_quantity is not None else None,
                "unit_cost": str(line.unit_cost),
                "partner": ref(line.partner),
            }
            for line in lines
        ],
        "payments": [
            {
                "method": payment.method,
                "amount": str(payment.amount),
                "reference": payment.reference,
                "cash_on": payment.cash_on.isoformat() if payment.cash_on else None,
            }
            for payment in payments
        ],
        "total": str(sum((line.amount for line in lines), ZERO)),
        "paid": str(sum((payment.amount for payment in payments), ZERO)),
    }


def _write_field_purchase(purchase: FieldPurchase, values: dict[str, Any]) -> None:
    """Put the checked values on the purchase, its lines and its payments (lines and payments are replaced)."""
    for field in (
        "supplier",
        "proposed_supplier",
        "proposed_supplier_phone",
        "bought_on",
        "terms",
        "due_days",
        "supplier_reference",
        "notes",
        "location",
        "boxes",
    ):
        setattr(purchase, field, values[field])
    purchase.save()
    purchase.lines.all().delete()
    purchase.payments.all().delete()
    FieldPurchaseLine.objects.bulk_create(
        [
            FieldPurchaseLine(organization_id=purchase.organization_id, purchase=purchase, **line)
            for line in values["lines"]
        ]
    )
    FieldPurchasePayment.objects.bulk_create(
        [
            FieldPurchasePayment(organization_id=purchase.organization_id, purchase=purchase, **payment)
            for payment in values["payments"]
        ]
    )


def _add_revision(purchase: FieldPurchase, actor: User | None, action: str, note: str = "") -> FieldPurchaseRevision:
    return FieldPurchaseRevision.objects.create(
        organization_id=purchase.organization_id,
        purchase=purchase,
        number=purchase.revision,
        action=action,
        created_by=actor,
        note=note,
        snapshot=field_purchase_snapshot(purchase),
    )


@transaction.atomic
def submit_field_purchase(
    *,
    organization: Organization,
    buyer: User,
    fields: FieldPurchaseFields,
    client_uuid: uuid.UUID | None = None,
    made_at: dt.datetime | None = None,
) -> FieldPurchase:
    """Record what a driver bought at the port, sent to be checked. Nothing enters stock and nothing is owed yet.

    The supplier and each product are picked from the lists, or given as a new name for the office to create.
    The first revision keeps it as the driver sent it. From the phone (D-158), `client_uuid` makes a retry answer
    with the purchase already saved, and `made_at` is when the phone says it was bought.
    """
    if client_uuid is not None:
        existing = FieldPurchase.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    values = _checked_field_purchase(organization, fields)
    purchase = FieldPurchase(
        organization=organization,
        number=_next_document_number(
            organization, DocumentKind.FIELD_PURCHASE, FIELD_PURCHASE_NUMBER_PREFIX, yearly=True
        ),
        buyer=buyer,
        client_uuid=client_uuid,
        made_at=made_at,
    )
    _write_field_purchase(purchase, values)
    _add_revision(purchase, buyer, FieldPurchaseAction.SUBMITTED)
    audit.record(
        organization=organization,
        actor=buyer,
        action="field_purchase.submitted",
        target=purchase,
        after=field_purchase_snapshot(purchase),
    )
    return purchase


def _locked_field_purchase(purchase: FieldPurchase, revision: int) -> FieldPurchase:
    """The purchase re-read under a row lock; refused once decided, or when someone saved it since `revision`."""
    locked = FieldPurchase.objects.select_for_update().select_related("organization").get(pk=purchase.pk)
    if locked.status != FieldPurchaseStatus.SUBMITTED:
        raise ValidationError(
            _("L'achat %(number)s est %(status)s : il ne se modifie plus.")
            % {"number": locked.number, "status": FieldPurchaseStatus(locked.status).label.lower()}
        )
    if revision != locked.revision:
        raise ValidationError(
            {
                "revision": _("L'achat %(number)s a été modifié entre-temps (version %(revision)s) : rechargez-le.")
                % {"number": locked.number, "revision": locked.revision}
            }
        )
    return locked


@transaction.atomic
def update_field_purchase(
    *,
    purchase: FieldPurchase,
    actor: User | None,
    revision: int,
    fields: FieldPurchaseFields,
    office_note: str | None = None,
    validate: bool = False,
) -> FieldPurchase:
    """Change a purchase not decided yet: a new revision when anything changed; with `validate`, validate it after.

    `revision` is the one the person was looking at: a save on an older one is refused, so nobody overwrites a
    change they have not seen. `office_note` is the office's note to the driver (None keeps it).
    """
    purchase = _locked_field_purchase(purchase, revision)
    organization = purchase.organization
    values = _checked_field_purchase(organization, fields)
    before = field_purchase_snapshot(purchase)
    note = purchase.office_note if office_note is None else office_note.strip()
    note_changed = note != purchase.office_note
    _write_field_purchase(purchase, values)
    after = field_purchase_snapshot(purchase)
    if after != before or note_changed:
        purchase.office_note = note
        purchase.revision += 1
        purchase.save(update_fields=["office_note", "revision", "updated_at"])
        _add_revision(purchase, actor, FieldPurchaseAction.EDITED, note if note_changed else "")
        audit.record(
            organization=organization,
            actor=actor,
            action="field_purchase.edited",
            target=purchase,
            before=before,
            after=after,
        )
    if validate:
        _validate_field_purchase(purchase, actor)
    return purchase


def _validate_field_purchase(purchase: FieldPurchase, actor: User | None) -> None:
    organization = purchase.organization
    lines = list(purchase.lines.select_related("product", "partner").order_by("id"))
    payments = list(purchase.payments.order_by("id"))
    errors: dict[str, str] = {}
    if purchase.supplier is None:
        errors["supplier"] = _("Choisissez le fournisseur dans la liste (créez « %(name)s » s'il est nouveau).") % {
            "name": purchase.proposed_supplier
        }
    if purchase.location is None:
        errors["location"] = _("Choisissez où vont les marchandises.")
    for index, line in enumerate(lines):
        if line.product is None:
            errors[line_error_key(index, "product")] = _(
                "Choisissez le produit dans la liste (créez « %(name)s » s'il est nouveau)."
            ) % {"name": line.proposed_product}
    total = sum((line.amount for line in lines), ZERO)
    if not errors and total <= 0:
        errors["lines"] = _("Le montant de l'achat est nul : il n'y a rien à valider.")
    if errors:
        raise ValidationError(errors)
    supplier = purchase.supplier
    location = purchase.location
    # Both checked above.
    assert supplier is not None
    assert location is not None

    # The kg really received are what entered stock and what is owed (Q28); the kg typed at the port stay on
    # the receipt as its "ordered" weight, so a difference shows on the receipt and in the differences report.
    receipt = create_receipt(
        organization=organization,
        actor=actor,
        supplier=supplier,
        location=location,
        received_on=purchase.bought_on,
        lines=[
            {
                "product": line.product,
                "ordered_quantity": line.declared_quantity,
                "invoiced_quantity": line.owed_quantity,
                "accepted_quantity": line.owed_quantity,
                "unit_cost": line.unit_cost,
                "partner": line.partner,
            }
            for line in lines
            if line.product is not None
        ],
        supplier_reference=purchase.supplier_reference,
        notes=_("Achat terrain %(number)s") % {"number": purchase.number},
        boxes=purchase.boxes,
    )
    # No invoice here (D-200): the office makes it later from the receipts it picks ("Nouvelle facture"), and
    # the money given at the port waits as an advance of the supplier until then.
    for payment in payments:
        payment.supplier_payment = record_payment(
            organization=organization,
            actor=actor,
            supplier=supplier,
            paid_on=purchase.bought_on,
            amount=payment.amount,
            method=payment.method,
            reference=payment.reference,
            cash_on=payment.cash_on,
            notes=_("Donné au port, achat terrain %(number)s") % {"number": purchase.number},
            allocations=[],
            # The driver's purchase money, written with the driver's day (P9-T05b).
            post_to_treasury=False,
        )
        payment.save(update_fields=["supplier_payment"])
    purchase.status = FieldPurchaseStatus.VALIDATED
    purchase.receipt = receipt
    purchase.decided_at = timezone.now()
    purchase.decided_by = actor
    purchase.revision += 1
    purchase.save(update_fields=["status", "receipt", "decided_at", "decided_by", "revision", "updated_at"])
    _add_revision(purchase, actor, FieldPurchaseAction.VALIDATED)
    audit.record(
        organization=organization,
        actor=actor,
        action="field_purchase.validated",
        target=purchase,
        after={"receipt": receipt.number, "total": str(total)},
    )


@transaction.atomic
def update_field_purchase_by_buyer(
    *, purchase: FieldPurchase, buyer: User, revision: int, fields: FieldPurchaseFields
) -> FieldPurchase:
    """The driver changes a purchase they sent, while the office has not decided it (D-158). What the office set
    stays: the place, the boxes, the office's note, and the kg received and the partner of a line still buying the
    same product at the same position. The day of the purchase does not change."""
    current = FieldPurchase.objects.select_related("location").get(pk=purchase.pk)
    if current.buyer_id != buyer.pk:
        raise ValidationError(_("Cet achat n'est pas le vôtre."))
    kept = list(current.lines.order_by("id"))
    lines: list[FieldLineFields] = []
    for index, line in enumerate(fields.get("lines", ())):
        office = kept[index] if index < len(kept) else None
        product = line.get("product")
        same = office is not None and (
            (product is not None and office.product_id == product.pk)
            or (
                product is None
                and office.product_id is None
                and office.proposed_product == line.get("proposed_product", "").strip()
            )
        )
        lines.append(
            {
                **line,
                "received_quantity": office.received_quantity if same and office is not None else None,
                "partner": office.partner if same and office is not None else None,
            }
        )
    merged: FieldPurchaseFields = {
        **fields,
        "bought_on": current.bought_on,
        "location": current.location,
        "boxes": current.boxes,
        "lines": lines,
    }
    return update_field_purchase(purchase=current, actor=buyer, revision=revision, fields=merged)


@transaction.atomic
def refuse_field_purchase(*, purchase: FieldPurchase, actor: User | None, revision: int, note: str) -> FieldPurchase:
    """Turn a purchase down, with the reason for the driver: nothing enters stock and nothing is owed. Final."""
    purchase = _locked_field_purchase(purchase, revision)
    note = note.strip()
    if not note:
        raise ValidationError({"office_note": _("Dites au chauffeur pourquoi l'achat est refusé.")})
    purchase.status = FieldPurchaseStatus.REFUSED
    purchase.office_note = note
    purchase.decided_at = timezone.now()
    purchase.decided_by = actor
    purchase.revision += 1
    purchase.save(update_fields=["status", "office_note", "decided_at", "decided_by", "revision", "updated_at"])
    _add_revision(purchase, actor, FieldPurchaseAction.REFUSED, note)
    audit.record(
        organization=purchase.organization,
        actor=actor,
        action="field_purchase.refused",
        target=purchase,
        after={"note": note},
    )
    return purchase


# ---- Paying suppliers (P3-T12c, D-159) ----


@transaction.atomic
def receive_and_invoice(
    *,
    organization: Organization,
    actor: User | None,
    supplier: "Supplier",
    location: "StockLocation",
    received_on: dt.date,
    lines: Sequence[ReceiptLineFields],
    terms: str,
    due_days: int = 0,
    supplier_reference: str = "",
    notes: str = "",
    purchase_order: PurchaseOrder | None = None,
    boxes: Mapping[str, int] | None = None,
    payments: Sequence[FieldPaymentFields] = (),
    with_vat: bool = False,
) -> GoodsReceipt:
    """Record goods received and, in the same step, what is owed for them (D-159): a posted supplier invoice for the
    receipt, due by the deal made for this delivery, as a purchase at the port is (D-176). The debt starts at the
    reception; a paper invoice of the supplier, if one comes, is only matched by its number. `payments` are the
    sums given now (D-192), recorded and allocated to that invoice; more than its total is refused."""
    errors: dict[str, str] = {}
    if terms not in PaymentTerms.values:
        errors["terms"] = _("Accord de paiement inconnu.")
    elif not 0 <= due_days <= 365:
        errors["due_days"] = _("Indiquez un nombre de jours entre 0 et 365.")
    elif terms == PaymentTerms.DAYS and due_days == 0:
        errors["due_days"] = _("Indiquez dans combien de jours la livraison est payée.")
    checked_payments = _checked_payment_lines(payments, received_on, errors)
    if errors:
        raise ValidationError(errors)
    receipt = create_receipt(
        organization=organization,
        actor=actor,
        supplier=supplier,
        location=location,
        received_on=received_on,
        lines=lines,
        supplier_reference=supplier_reference,
        notes=notes,
        purchase_order=purchase_order,
        boxes=boxes,
        with_vat=with_vat,
    )
    invoice = create_invoice(
        organization=organization,
        actor=actor,
        supplier=supplier,
        receipts=[receipt],
        invoice_date=received_on,
        due_date=due_date_of(received_on, terms, due_days if terms != PaymentTerms.CASH else 0),
        supplier_reference=receipt.supplier_reference,
        post=True,
    )
    given = sum((payment["amount"] for payment in checked_payments), ZERO)
    if given > invoice.total:
        # Rolls the whole receipt back: more given than owed is a typing mistake (D-181).
        raise ValidationError(
            {
                payment_error_key(len(checked_payments) - 1, "amount"): _(
                    "L'argent donné (%(given)s DT) dépasse le montant de la réception (%(total)s DT) : "
                    "vérifiez les montants."
                )
                % {"given": display_money(given), "total": display_money(invoice.total)}
            }
        )
    for payment in checked_payments:
        record_payment(
            organization=organization,
            actor=actor,
            supplier=supplier,
            paid_on=received_on,
            amount=payment["amount"],
            method=payment["method"],
            reference=payment["reference"],
            cash_on=payment["cash_on"],
            notes=_("Donné à la réception %(number)s") % {"number": receipt.number},
            allocations=[{"invoice": invoice, "amount": payment["amount"]}],
        )
    return receipt


@transaction.atomic
def add_field_purchase_paper(
    *, purchase: FieldPurchase, actor: User | None, upload: "UploadedFile[bytes]"
) -> FieldPurchase:
    """Join the photo of the supplier's paper (D-159): turned upright, shrunk, stored as WebP. It can be replaced
    while the purchase waits for the office; once decided, it is joined only if there was none."""
    content = reencoded_photo(upload, field="paper")
    purchase = FieldPurchase.objects.select_for_update().get(pk=purchase.pk)
    if purchase.status != FieldPurchaseStatus.SUBMITTED and purchase.paper:
        raise ValidationError({"paper": _("Cet achat est décidé : la photo de son papier ne change plus.")})
    previous = purchase.paper.name
    storage = purchase.paper.storage
    purchase.paper.save("paper.webp", content, save=False)
    try:
        purchase.save(update_fields=["paper", "updated_at"])
        audit.record(
            organization=purchase.organization, actor=actor, action="field_purchase.paper_added", target=purchase
        )
    except BaseException:
        # The file is written before the row: never leave it behind when the change is rolled back.
        if purchase.paper.name:
            purchase.paper.storage.delete(purchase.paper.name)
        raise
    if previous:
        transaction.on_commit(lambda: storage.delete(previous))
    return purchase


# ---- Our effets the bank refused (rejeté, P9-T04c, D-218) ----


def _allocated_of(payment: SupplierPayment) -> Decimal:
    """What the règlement settles on invoices now: its allocations less what its rejected effets took back."""
    allocated = SupplierPaymentAllocation.objects.filter(payment=payment).aggregate(total=Sum("amount"))["total"]
    released = RejectedRelease.objects.filter(rejected__payment=payment).aggregate(total=Sum("amount"))["total"]
    return (allocated or ZERO) - (released or ZERO)


def _rejected_of(payment: SupplierPayment) -> Decimal:
    return RejectedEffet.objects.filter(payment=payment).aggregate(total=Sum("amount"))["total"] or ZERO


@transaction.atomic
def reject_issued_effet(
    *, organization: Organization, actor: User | None, instrument_id: int, rejected_on: dt.date | None, reason: str
) -> RejectedEffet:
    """Our bank refused to pay one of our cheques or traites: the supplier is owed its amount again (D-218).

    A new record, the règlement untouched: `RejectedEffet` takes the amount out of what was paid; the règlement's
    advance left absorbs it first, then what it settled on invoices is taken back, newest allocation first
    (`RejectedRelease`), so those invoices owe again. The effet becomes "Rejeté" in the treasury.
    """
    reason = " ".join(reason.split())[:255]
    errors: dict[str, str] = {}
    if not reason:
        errors["reason"] = _("Indiquez le motif du rejet.")
    line = (
        SupplierPaymentLine.objects.select_related("payment", "payment__supplier", "instrument")
        .filter(organization=organization, instrument_id=instrument_id)
        .first()
    )
    if line is None:
        errors["instrument"] = _("Cet effet n'est pas celui d'un règlement fournisseur.")
    if errors:
        raise ValidationError(errors)
    assert line is not None
    payment = SupplierPayment.objects.select_for_update().select_related("supplier").get(pk=line.payment_id)
    if payment.voided_at is not None:
        raise ValidationError({"instrument": _("Ce règlement est annulé.")})
    treasury.mark_rejected(
        organization=organization, actor=actor, instrument_id=instrument_id, rejected_on=rejected_on, note=reason
    )
    assert rejected_on is not None  # checked by the treasury
    free = payment.amount - _rejected_of(payment) - _allocated_of(payment)
    to_release = max(line.amount - max(free, ZERO), ZERO)
    rejected = RejectedEffet.objects.create(
        organization=organization,
        payment=payment,
        line=line,
        supplier=payment.supplier,
        amount=line.amount,
        rejected_on=rejected_on,
        reason=reason,
        created_by=actor,
    )
    # Each invoice's part still settled by this règlement, the newest allocation first.
    net: dict[int, Decimal] = {}
    for allocation in SupplierPaymentAllocation.objects.filter(payment=payment).order_by("-id"):
        net[allocation.invoice_id] = net.get(allocation.invoice_id, ZERO) + allocation.amount
    for row in (
        RejectedRelease.objects.filter(rejected__payment=payment).values("invoice_id").annotate(total=Sum("amount"))
    ):
        net[row["invoice_id"]] = net.get(row["invoice_id"], ZERO) - row["total"]
    released: dict[int, Decimal] = {}
    for invoice_id, settled in net.items():
        if to_release <= 0:
            break
        part = min(settled, to_release)
        if part <= 0:
            continue
        RejectedRelease.objects.create(organization=organization, rejected=rejected, invoice_id=invoice_id, amount=part)
        released[invoice_id] = part
        to_release -= part
    for invoice in SupplierInvoice.objects.select_for_update().filter(pk__in=sorted(released)).order_by("id"):
        status = _invoice_status_from_payments(invoice)
        if status != invoice.status:
            invoice.status = status
            invoice.save(update_fields=["status", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier_payment.rejected",
        target=payment,
        after={
            "effet": str(line.instrument),
            "amount": str(line.amount),
            "reason": reason,
            "released": {str(invoice_id): str(amount) for invoice_id, amount in released.items()},
        },
    )
    return rejected
