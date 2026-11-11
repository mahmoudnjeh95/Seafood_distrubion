"""Every write on purchases goes through these functions (ARCHITECTURE §3)."""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.boxes import services as box_services
from apps.core import audit, numbering, periods
from apps.core.images import reencoded_photo
from apps.core.models import Organization, User
from apps.core.money import MAX_AMOUNT, Number, checked_amount, checked_quantity, display_money, line_total, money
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory
from apps.inventory.services import MovementKind
from apps.partnerships import selectors as partnership_selectors
from apps.partnerships import services as partnerships
from apps.sales import selectors as sales_selectors
from apps.treasury import services as treasury

from . import selectors
from .models import (
    INSTRUMENT_METHODS,
    LINE_METHOD_CHOICES,
    RECEIVABLE_ORDER_STATUSES,
    FieldPurchase,
    FieldPurchaseAction,
    FieldPurchaseLine,
    FieldPurchasePayment,
    FieldPurchaseRevision,
    FieldPurchaseStatus,
    GoodsReceipt,
    GoodsReceiptLine,
    GoodsReceiptRevision,
    PaymentTerms,
    PlanLineStatus,
    PriceRequest,
    PriceRequestLine,
    PriceRequestStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
    ReceiptDisputeStatus,
    RejectedEffet,
    RejectedRelease,
    SupplierBalanceWriteOff,
    SupplierCreditAllocation,
    SupplierCreditKind,
    SupplierCreditNote,
    SupplierCreditNoteLine,
    SupplierInvoice,
    SupplierInvoiceReceipt,
    SupplierInvoiceStatus,
    SupplierOffer,
    SupplierOfferLine,
    SupplierPayment,
    SupplierPaymentAllocation,
    SupplierPaymentLine,
    SupplierPaymentPlanLine,
    SupplierWriteOffAllocation,
    SupplierWriteOffLotShare,
)
from .models import PaymentMethod as PaymentMethod  # re-exported for apps that record payments (the demo)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from apps.catalog.models import Product
    from apps.inventory.models import StockLocation
    from apps.partners.models import Supplier
    from apps.treasury.models import Bank, TreasuryAccount

ZERO = Decimal("0.000")
# The methods one line, a plan line or a sum given at the port may use: every method but "several" (D-208).
LINE_METHODS = frozenset(value for value, _label in LINE_METHOD_CHOICES)


class ReceiptLineFields(TypedDict, total=False):
    product: "Product"
    ordered_quantity: Number | None
    invoiced_quantity: Number
    accepted_quantity: Number
    unit_cost: Number
    use_by: dt.date | None
    # Where the fish comes from (D-302), copied onto the lot.
    catch_area: str
    production_method: str
    origin: str
    # The lot is bought together with this supplier (D-100); may be the receipt's own supplier.
    partner: "Supplier | None"


def line_error_key(index: int, field: str) -> str:
    """Errors of a line are reported on `lines.<index>.<field>`, so each one shows under its own input."""
    return f"lines.{index}.{field}"


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
        "catch_area": line.get("catch_area", "") or "",
        "production_method": line.get("production_method", "") or "",
        "origin": line.get("origin", "") or "",
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
    arrival_temperature: Decimal | None = None,
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
    periods.ensure_open(organization, received_on, field="received_on")
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
        number=numbering.next_number(organization, "receipt"),
        supplier=supplier,
        location=location,
        purchase_order=order,
        received_on=received_on,
        supplier_reference=supplier_reference,
        with_vat=with_vat,
        arrival_temperature=arrival_temperature,
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
            catch_area=values["catch_area"],
            production_method=values["production_method"],
            origin=values["origin"],
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


# ---- Changing a goods receipt after it was saved (D-269) ----
# Allowed while no supplier invoice carries it. What it moved out of the stock is never edited: a change of an
# accepted weight is a correction movement, and a price or VAT change waits until nothing valued has left the lot.


class ReceiptRevisionLineFields(TypedDict, total=False):
    id: int
    invoiced_quantity: Number
    accepted_quantity: Number
    unit_cost: Number
    use_by: dt.date | None


class ReceiptRevisionFields(TypedDict, total=False):
    supplier_reference: str
    notes: str
    with_vat: bool
    lines: Sequence[ReceiptRevisionLineFields]


def receipt_snapshot(receipt: GoodsReceipt) -> dict[str, Any]:
    """What a receipt says, as plain values: what a change keeps, and what two versions are compared on."""
    lines = list(receipt.lines.select_related("product", "batch").order_by("id"))
    return {
        "supplier_reference": receipt.supplier_reference,
        "notes": receipt.notes,
        "with_vat": receipt.with_vat,
        "lines": [
            {
                "product": line.product.name,
                "invoiced_quantity": str(line.invoiced_quantity),
                "accepted_quantity": str(line.accepted_quantity),
                "unit_cost": str(line.unit_cost),
                "use_by": line.batch.use_by.isoformat() if line.batch.use_by else None,
            }
            for line in lines
        ],
    }


def _locked_receipt(receipt: GoodsReceipt, revision: int) -> GoodsReceipt:
    """The receipt re-read under a row lock: refused while an invoice carries it, or when someone changed it since
    `revision`."""
    locked = (
        GoodsReceipt.objects.select_for_update(of=("self",))
        .select_related("organization", "location", "purchase_order")
        .get(pk=receipt.pk)
    )
    link = getattr(locked, "invoice_link", None)
    if link is not None:
        invoice = link.invoice
        if invoice.status == SupplierInvoiceStatus.DRAFT:
            raise ValidationError(
                _("La réception %(number)s est sur la facture brouillon %(invoice)s : supprimez d'abord ce brouillon.")
                % {"number": locked.number, "invoice": invoice.number}
            )
        raise ValidationError(
            _(
                "La réception %(number)s est sur la facture validée %(invoice)s : elle ne se modifie plus. "
                "Corrigez par la facture ou par un retour fournisseur."
            )
            % {"number": locked.number, "invoice": invoice.number}
        )
    if revision != locked.revision:
        raise ValidationError(
            {
                "revision": _(
                    "La réception %(number)s a été modifiée entre-temps (version %(revision)s) : rechargez-la."
                )
                % {"number": locked.number, "revision": locked.revision}
            }
        )
    return locked


def _checked_revised_line(
    index: int, item: ReceiptRevisionLineFields, received_on: dt.date, errors: dict[str, str]
) -> dict[str, Any]:
    checked: dict[str, Any] = {"use_by": item.get("use_by")}
    try:
        checked["invoiced_quantity"] = checked_quantity(item.get("invoiced_quantity", ""))
    except (ValueError, TypeError):
        errors[line_error_key(index, "invoiced_quantity")] = _("Indiquez un poids net en kg, supérieur à zéro.")
    try:
        checked["accepted_quantity"] = checked_quantity(item.get("accepted_quantity", ""))
    except (ValueError, TypeError):
        errors[line_error_key(index, "accepted_quantity")] = _("Indiquez un poids net en kg, supérieur à zéro.")
    try:
        checked["unit_cost"] = checked_amount(item.get("unit_cost", ""))
    except (ValueError, TypeError):
        errors[line_error_key(index, "unit_cost")] = _("Indiquez un coût en DT par kg, au millime près.")
    if "unit_cost" in checked and "invoiced_quantity" in checked and "accepted_quantity" in checked:
        biggest = max(checked["invoiced_quantity"], checked["accepted_quantity"])
        if line_total(biggest, checked["unit_cost"]) > MAX_AMOUNT:
            errors[line_error_key(index, "unit_cost")] = _(
                "Le montant de cette ligne est trop grand : vérifiez le coût au kg."
            )
    use_by = checked["use_by"]
    if use_by is not None and use_by < received_on:
        errors[line_error_key(index, "use_by")] = _("La date limite ne peut pas précéder la réception.")
    return checked


@transaction.atomic
def revise_receipt(
    *,
    receipt: GoodsReceipt,
    actor: User | None,
    revision: int,
    reason: str,
    fields: ReceiptRevisionFields,
) -> GoodsReceipt:
    """Change a goods receipt after it was saved (D-269): its supplier reference, notes and VAT flag, and each of
    its lines' invoiced and accepted weight, cost per kg and use-by date. Every line is sent, by its id.

    Refused while an invoice carries the receipt (a draft one is deleted first), when `revision` is not its current
    one, and without a reason. A changed accepted weight posts a receipt correction on the lot, from the receipt's
    place,
    and the original movement stays as it was; it is refused when it would take the lot below what already left it.
    A changed cost or VAT flag is refused once something valued has left the lot (a sale, a loss, a return, a count).
    Each change is kept as a revision with its before and after, and audited. Problems come back together.
    """
    receipt = _locked_receipt(receipt, revision)
    organization = receipt.organization
    before = receipt_snapshot(receipt)
    errors: dict[str, str] = {}
    reason = reason.strip()
    if not reason:
        errors["reason"] = _("Indiquez la raison de la modification.")
    lines = {line.pk: line for line in receipt.lines.select_related("product", "batch")}
    sent = list(fields.get("lines", []))
    if sorted(item["id"] for item in sent) != sorted(lines):
        errors["lines"] = _("Renvoyez toutes les lignes de la réception, sans en ajouter ni en retirer.")
    checked: list[tuple[int, GoodsReceiptLine, dict[str, Any]]] = []
    for index, item in enumerate(sent):
        if item["id"] in lines:
            checked.append((index, lines[item["id"]], _checked_revised_line(index, item, receipt.received_on, errors)))
    if errors:
        raise ValidationError(errors)
    supplier_reference = fields.get("supplier_reference", "").strip()
    notes = fields.get("notes", "").strip()
    with_vat = fields["with_vat"]

    for index, line, values in checked:
        if values["unit_cost"] != line.unit_cost and inventory_selectors.batch_valued_outside(
            organization, batch_id=line.batch_id
        ):
            errors[line_error_key(index, "unit_cost")] = _(
                "Des kilos de ce lot ont déjà été vendus, perdus ou corrigés : son prix ne se change plus."
            )
        delta = values["accepted_quantity"] - line.accepted_quantity
        if delta < 0:
            on_hand = inventory_selectors.quantity_on_hand(organization, batch_id=line.batch_id)
            if on_hand + delta < 0:
                errors[line_error_key(index, "accepted_quantity")] = _(
                    "Il est déjà sorti %(left)s kg de ce lot : la quantité acceptée ne descend pas sous ce poids."
                ) % {"left": line.accepted_quantity - on_hand}
    if with_vat != receipt.with_vat and any(
        inventory_selectors.batch_valued_outside(organization, batch_id=line.batch_id)
        for _index, line, _values in checked
    ):
        errors["with_vat"] = _(
            "Des kilos de ce lot ont déjà été vendus, perdus ou corrigés : la TVA ne se change plus."
        )
    if errors:
        raise ValidationError(errors)

    receipt.supplier_reference = supplier_reference
    receipt.notes = notes
    receipt.with_vat = with_vat
    occurred_at = timezone.now()
    correction_reason = _("Correction du bon %(number)s : %(reason)s") % {"number": receipt.number, "reason": reason}
    for index, line, values in checked:
        inventory.correct_batch(
            batch=line.batch,
            unit_cost=values["unit_cost"],
            use_by=values["use_by"],
            bought_with_vat=with_vat,
            receipt_reference=supplier_reference or receipt.number,
        )
        delta = values["accepted_quantity"] - line.accepted_quantity
        if delta:
            try:
                inventory.post_movement(
                    organization=organization,
                    actor=actor,
                    kind=MovementKind.RECEIPT_CORRECTION,
                    batch=line.batch,
                    quantity=abs(delta),
                    from_location=receipt.location if delta < 0 else None,
                    to_location=receipt.location if delta > 0 else None,
                    reason=correction_reason,
                    source=line,
                    occurred_at=occurred_at,
                )
            except ValidationError as error:
                raise ValidationError({line_error_key(index, "accepted_quantity"): error.messages[0]}) from None
        line.invoiced_quantity = values["invoiced_quantity"]
        line.accepted_quantity = values["accepted_quantity"]
        line.unit_cost = values["unit_cost"]
        line.save(update_fields=["invoiced_quantity", "accepted_quantity", "unit_cost"])

    receipt.revision += 1
    receipt.save(update_fields=["supplier_reference", "notes", "with_vat", "revision", "updated_at"])
    after = receipt_snapshot(receipt)
    if after == before:
        raise ValidationError({"lines": _("Rien n'a changé : modifiez au moins une valeur.")})
    GoodsReceiptRevision.objects.create(
        organization=organization,
        receipt=receipt,
        number=receipt.revision,
        created_by=actor,
        reason=reason,
        before=before,
        after=after,
    )
    order = receipt.purchase_order
    if order is not None:
        refresh_order_status(order)
    audit.record(
        organization=organization,
        actor=actor,
        action="receipt.edited",
        target=receipt,
        before=before,
        after=after,
    )
    return receipt


# ---- Disputes with the supplier ("bon de réception contesté", D-285) ----
# The stock is in either way; an open dispute only keeps the receipt off supplier invoices until it is lifted.


def _dispute_snapshot(receipt: GoodsReceipt) -> dict[str, Any]:
    return {
        "dispute_status": receipt.dispute_status,
        "dispute_reason": receipt.dispute_reason,
        "dispute_resolution": receipt.dispute_resolution,
    }


@transaction.atomic
def dispute_receipt(*, receipt: GoodsReceipt, actor: User | None, reason: str) -> GoodsReceipt:
    """Contest a goods receipt with its supplier: the reason ("motif de contestation") is required. Refused while an
    invoice carries it (a draft is changed or deleted first; a posted one is corrected otherwise) and while a dispute
    is already open. A receipt whose dispute was lifted may be contested again."""
    reason = reason.strip()
    locked = GoodsReceipt.objects.select_for_update(of=("self",)).select_related("organization").get(pk=receipt.pk)
    link = SupplierInvoiceReceipt.objects.filter(receipt=locked).select_related("invoice").first()
    if link is not None:
        raise ValidationError(
            _("La réception %(number)s est sur la facture %(invoice)s : retirez-la de la facture pour la contester.")
            % {"number": locked.number, "invoice": link.invoice.number}
        )
    if locked.is_disputed:
        raise ValidationError(_("La réception %(number)s est déjà contestée.") % {"number": locked.number})
    if not reason:
        raise ValidationError({"reason": _("Indiquez le motif de la contestation.")})
    before = _dispute_snapshot(locked)
    locked.dispute_status = ReceiptDisputeStatus.OPEN
    locked.dispute_reason = reason
    locked.disputed_at = timezone.now()
    locked.disputed_by = actor
    locked.dispute_resolution = ""
    locked.dispute_resolved_at = None
    locked.dispute_resolved_by = None
    locked.save(
        update_fields=[
            "dispute_status",
            "dispute_reason",
            "disputed_at",
            "disputed_by",
            "dispute_resolution",
            "dispute_resolved_at",
            "dispute_resolved_by",
            "updated_at",
        ]
    )
    audit.record(
        organization=locked.organization,
        actor=actor,
        action="receipt.disputed",
        target=locked,
        before=before,
        after=_dispute_snapshot(locked),
    )
    return locked


@transaction.atomic
def resolve_receipt_dispute(*, receipt: GoodsReceipt, actor: User | None, resolution: str) -> GoodsReceipt:
    """Lift an open dispute, saying how it was settled (required): the receipt may then go on a supplier invoice.
    A weight or cost the supplier agreed to change is corrected on the receipt itself (`revise_receipt`)."""
    resolution = resolution.strip()
    locked = GoodsReceipt.objects.select_for_update(of=("self",)).select_related("organization").get(pk=receipt.pk)
    if not locked.is_disputed:
        raise ValidationError(_("La réception %(number)s n'est pas contestée.") % {"number": locked.number})
    if not resolution:
        raise ValidationError({"resolution": _("Indiquez comment la contestation a été réglée.")})
    before = _dispute_snapshot(locked)
    locked.dispute_status = ReceiptDisputeStatus.RESOLVED
    locked.dispute_resolution = resolution
    locked.dispute_resolved_at = timezone.now()
    locked.dispute_resolved_by = actor
    locked.save(
        update_fields=[
            "dispute_status",
            "dispute_resolution",
            "dispute_resolved_at",
            "dispute_resolved_by",
            "updated_at",
        ]
    )
    audit.record(
        organization=locked.organization,
        actor=actor,
        action="receipt.dispute_resolved",
        target=locked,
        before=before,
        after=_dispute_snapshot(locked),
    )
    return locked


# ---- Purchase orders, the "commande d'achat" (D-076) ----
# An order moves no stock and owes nothing; its receipts do. Its status follows them.


class OrderLineFields(TypedDict, total=False):
    product: "Product"
    ordered_quantity: Number
    unit_cost: Number


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
        number=numbering.next_number(organization, "purchase_order"),
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
            elif receipt.is_disputed:
                problems.append(
                    _("La réception %(number)s est contestée : levez la contestation avant de la facturer.")
                    % {"number": receipt.number}
                )
    if len(locked) != len(ids):
        problems.append(_("Réception inconnue."))
    if problems:
        errors["receipts"] = " ".join(dict.fromkeys(problems))
    return locked


def _checked_paper_total(value: Number | None, errors: dict[str, str]) -> Decimal | None:
    """The total typed from the supplier's paper (D-301), or None when not typed."""
    if value is None or value == "":
        return None
    try:
        amount = checked_amount(value)
    except (ValueError, TypeError) as error:
        errors["paper_total"] = str(error)
        return None
    return amount


def _checked_stamp(value: Number | None, errors: dict[str, str]) -> Decimal | None:
    """A typed droit de timbre, or None when none was typed (the default applies)."""
    if value in (None, ""):
        return None
    try:
        return checked_amount(value)
    except (ValueError, TypeError):
        errors["fiscal_stamp"] = _("Indiquez un montant en DT, au millime près.")
        return None


def _set_receipts(invoice: SupplierInvoice, receipts: Sequence[GoodsReceipt], fiscal_stamp: Decimal | None) -> None:
    """Charge exactly these receipts on the invoice and keep its amounts (D-294): without VAT, the sum of their
    invoiced amounts; the VAT of those bought with VAT; the stamp typed, else the settings' stamp when a receipt
    is bought with VAT (a supplier who invoices with VAT puts the droit de timbre on it) and none otherwise; the
    total owed is the three together."""
    SupplierInvoiceReceipt.objects.filter(invoice=invoice).delete()
    links = [
        SupplierInvoiceReceipt(
            organization_id=invoice.organization_id,
            invoice=invoice,
            receipt=receipt,
            # What the supplier charges for the receipt: invoiced kg × cost per line (D-039), and its VAT.
            amount=selectors.receipt_totals(receipt)[0],
            vat_amount=selectors.receipt_vat(receipt),
        )
        for receipt in receipts
    ]
    SupplierInvoiceReceipt.objects.bulk_create(links)
    default_stamp = (
        sales_selectors.fiscal_stamp_on(invoice.organization, invoice.invoice_date)
        if any(receipt.with_vat for receipt in receipts)
        else Decimal("0.000")
    )
    invoice.total_excl_tax = sum((link.amount for link in links), Decimal("0.000"))
    invoice.vat_total = sum((link.vat_amount for link in links), Decimal("0.000"))
    invoice.fiscal_stamp = default_stamp if fiscal_stamp is None else fiscal_stamp
    invoice.fiscal_stamp_overridden = fiscal_stamp is not None and fiscal_stamp != default_stamp
    invoice.total = invoice.total_excl_tax + invoice.vat_total + invoice.fiscal_stamp
    invoice.save(
        update_fields=[
            "total_excl_tax",
            "vat_total",
            "fiscal_stamp",
            "fiscal_stamp_overridden",
            "total",
            "updated_at",
        ]
    )


def _invoice_snapshot(invoice: SupplierInvoice) -> dict[str, Any]:
    links = SupplierInvoiceReceipt.objects.filter(invoice=invoice).select_related("receipt").order_by("receipt_id")
    return {
        "number": invoice.number,
        "supplier": invoice.supplier.reference,
        "supplier_reference": invoice.supplier_reference,
        "invoice_date": invoice.invoice_date.isoformat(),
        "due_date": invoice.due_date.isoformat(),
        "status": invoice.status,
        "total_excl_tax": str(invoice.total_excl_tax),
        "vat_total": str(invoice.vat_total),
        "fiscal_stamp": str(invoice.fiscal_stamp),
        "total": str(invoice.total),
        "paper_total": None if invoice.paper_total is None else str(invoice.paper_total),
        "receipts": {link.receipt.number: str(link.amount) for link in links},
    }


def _post(invoice: SupplierInvoice, actor: User | None) -> None:
    if invoice.total <= 0:
        raise ValidationError({"receipts": _("Le montant de la facture est nul : il n'y a rien à valider.")})
    invoice.status = SupplierInvoiceStatus.POSTED
    invoice.posted_at = timezone.now()
    invoice.posted_by = actor
    # The definitive number only now, once validated (D-283): a draft never uses one.
    invoice.draft_number = invoice.number
    invoice.number = numbering.next_number(invoice.organization, "supplier_invoice")
    invoice.save(update_fields=["status", "posted_at", "posted_by", "number", "draft_number", "updated_at"])
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
    # A credit note the supplier gave before this invoice settles it first (D-300).
    _apply_credits(invoice, selectors.unapplied_credit_notes(invoice.organization, supplier_id=invoice.supplier_id))


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
    fiscal_stamp: Number | None = None,
    paper_total: Number | None = None,
) -> SupplierInvoice:
    """Record a supplier's invoice for some of their receipts, as a draft, or posted at once with `post`.

    Its amount is the receipts' invoiced amount; a receipt goes on one invoice only. Every problem comes
    back at once, on its field. With `post` and `apply_advances`, what the supplier was already given and is not
    on an invoice yet (cash given at the port, advances) pays it, oldest first (D-200).
    """
    periods.ensure_open(organization, invoice_date, field="invoice_date")
    errors = _invoice_header_errors(organization, supplier, invoice_date, due_date)
    stamp = _checked_stamp(fiscal_stamp, errors)
    paper = _checked_paper_total(paper_total, errors)
    locked = _locked_receipts(organization, supplier, receipts, errors) if "supplier" not in errors else []
    if errors:
        raise ValidationError(errors)
    invoice = SupplierInvoice.objects.create(
        organization=organization,
        number=numbering.next_draft_number(organization, "supplier_invoice"),
        supplier=supplier,
        supplier_reference=supplier_reference.strip(),
        invoice_date=invoice_date,
        due_date=due_date,
        notes=notes.strip(),
        paper_total=paper,
        created_by=actor,
    )
    _set_receipts(invoice, locked, stamp)
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
        number=numbering.next_draft_number(organization, "supplier_invoice"),
        supplier=supplier,
        supplier_reference=supplier_reference.strip(),
        invoice_date=invoice_date,
        due_date=due_date,
        notes=notes.strip(),
        total=total,
        total_excl_tax=total,
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
    fiscal_stamp: Number | None = None,
    paper_total: Number | None = None,
) -> SupplierInvoice:
    """Change a draft invoice (its receipts, dates, reference, notes); with `post`, post it afterwards.

    The supplier does not change: a draft for the wrong supplier is deleted and typed again.
    """
    periods.ensure_open(invoice.organization, invoice_date, field="invoice_date")
    invoice = _locked_draft(invoice)
    organization = invoice.organization
    errors = _invoice_header_errors(organization, invoice.supplier, invoice_date, due_date)
    stamp = _checked_stamp(fiscal_stamp, errors)
    paper = _checked_paper_total(paper_total, errors)
    locked = _locked_receipts(organization, invoice.supplier, receipts, errors, invoice=invoice)
    if errors:
        raise ValidationError(errors)
    before = _invoice_snapshot(invoice)
    invoice.supplier_reference = supplier_reference.strip()
    invoice.invoice_date = invoice_date
    invoice.due_date = due_date
    invoice.notes = notes.strip()
    invoice.paper_total = paper
    invoice.save(update_fields=["supplier_reference", "invoice_date", "due_date", "notes", "paper_total", "updated_at"])
    _set_receipts(invoice, locked, stamp)
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
    """What settles the invoice: its payments, less what rejected effets took back, plus what a balance write-off
    gave up on it (D-252: settled though nothing was paid)."""
    paid = SupplierPaymentAllocation.objects.filter(invoice=invoice, payment__voided_at__isnull=True).aggregate(
        total=Sum("amount")
    )["total"]
    released = RejectedRelease.objects.filter(invoice=invoice).aggregate(total=Sum("amount"))["total"]
    if released:
        paid = (paid or Decimal("0.000")) - released
    given_up = SupplierWriteOffAllocation.objects.filter(invoice=invoice).aggregate(total=Sum("amount"))["total"]
    if given_up:
        paid = (paid or Decimal("0.000")) + given_up
    credited = SupplierCreditAllocation.objects.filter(invoice=invoice).aggregate(total=Sum("amount"))["total"]
    if credited:
        paid = (paid or Decimal("0.000")) + credited
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
    driver: User | None = None,
    movement_kind: str = "supplier_payment",
) -> None:
    """Write the règlement's lines; each cheque or traite becomes an effet issued to the supplier, the money of the
    others leaves its account at once (D-219). Cash a `driver` paid leaves that driver's cash."""
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
            _post_line_money(payment, row, line.get("account"), actor, driver=driver, kind=movement_kind)


# The treasury movement of a supplier règlement line paid in cash, by transfer or by card (D-219).
PAYMENT_LINE_SOURCE = "purchasing.payment_line"


def _post_line_money(
    payment: SupplierPayment,
    line: SupplierPaymentLine,
    account: "TreasuryAccount | None",
    actor: User | None,
    *,
    driver: User | None = None,
    kind: str = "supplier_payment",
) -> None:
    """The money of a line leaves an account the day it was paid: the one chosen, else the driver's cash for cash a
    driver paid, the Caisse for other cash, the main bank account for a transfer or a card. Our cheque or traite
    leaves only when the bank debits it."""
    organization = payment.organization
    treasury.post_movement(
        organization=organization,
        account=treasury.line_account(organization, line.method, account, driver=driver),
        day=payment.paid_on,
        amount=-line.amount,
        kind=kind,
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
    driver: User | None = None,
    movement_kind: str = "supplier_payment",
    confirm_cash_limit: bool = False,
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
    leaves that to the caller. Cash a `driver` paid (the port purchase) leaves that driver's cash, as a
    `movement_kind` movement (D-262).
    """
    periods.ensure_open(organization, paid_on, field="paid_on")
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
    over_limit = not errors and sales_selectors.cash_over_limit(
        organization, paid_on, (value for line_method, value, _line in checked if line_method == "cash")
    )
    if over_limit and not confirm_cash_limit:
        # A cash line at or above the limit goes through only when confirmed (D-273).
        errors["cash_limit"] = _(
            "Paiement en espèces au-delà du plafond légal (%(limit)s DT) : confirmez pour continuer."
        ) % {"limit": display_money(sales_selectors.cash_limit_on(organization, paid_on))}
    if errors:
        raise ValidationError(errors)
    assert total is not None  # an amount error would have been raised above
    methods = {line_method for line_method, _value, _line in checked}
    only = checked[0][2] if len(checked) == 1 else None
    payment = SupplierPayment.objects.create(
        organization=organization,
        cash_limit_confirmed=over_limit,
        number=numbering.next_number(organization, "supplier_payment"),
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
    _write_lines(
        payment,
        actor,
        checked,
        partial=partial,
        post_to_treasury=post_to_treasury,
        driver=driver,
        movement_kind=movement_kind,
    )
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
def write_off_supplier_balance(
    *,
    supplier: "Supplier",
    actor: User | None,
    expected: Number,
    reason: str,
    lot_shares: list[dict[str, Any]] | None = None,
) -> SupplierBalanceWriteOff:
    """Clear what we owe a supplier to zero, the rest given up as a gain on them (D-252): the supplier takes less
    than its balance. `expected` must be the balance shown now, typed again by the office, so a balance that moved
    since the screen was read is refused. The amount is spread over the open invoices, oldest due date first, and
    kept as it was written: never edited or deleted.

    The gain is also credited to the lots the owner picks by hand (`lot_shares`: `{"batch", "amount"}` adding up
    to the balance, D-257), so it raises those lots' net result and their partner shares it. A lot already settled
    with its partner is refused; a closed lot takes it as a late adjustment on the partner's next settlement."""
    organization = supplier.organization
    list(
        SupplierInvoice.objects.select_for_update(of=("self",))
        .filter(organization=organization, supplier=supplier)
        .order_by("id")
        .values_list("pk", flat=True)
    )
    balance = selectors.supplier_balance(organization, supplier.pk).balance
    try:
        typed = checked_amount(expected)
    except (ValueError, TypeError) as error:
        raise ValidationError({"expected_amount": str(error)}) from None
    if balance <= 0:
        raise ValidationError(_("Nous ne devons rien à ce fournisseur : rien à remettre à zéro."))
    if typed != balance:
        raise ValidationError(
            {
                "expected_amount": _("Le solde est de %(balance)s DT, pas %(typed)s DT : vérifiez le montant.")
                % {"balance": display_money(balance), "typed": display_money(typed)}
            }
        )
    reason = reason.strip()[:255]
    if not reason:
        raise ValidationError({"reason": _("Indiquez la raison de la remise à zéro.")})
    shares = partnerships.checked_write_off_lot_shares(
        organization,
        total=balance,
        shares=list(lot_shares or []),
        candidates=selectors.supplier_lots(organization, supplier_id=supplier.pk),
    )
    write_off = SupplierBalanceWriteOff.objects.create(
        organization=organization,
        supplier=supplier,
        written_on=timezone.localdate(),
        amount=balance,
        reason=reason,
        created_by=actor,
    )
    # The open invoices, oldest due date first, each settled by what is left; a balance above the open invoices
    # (a rejected effet not released yet) stays on the write-off only.
    left = balance
    for invoice in selectors.open_invoices_of(organization, supplier_id=supplier.pk):
        outstanding: Decimal = getattr(invoice, "outstanding")  # noqa: B009
        if left <= 0:
            break
        if outstanding <= 0:
            continue
        part = min(left, outstanding)
        SupplierWriteOffAllocation.objects.create(
            organization=organization, write_off=write_off, invoice=invoice, amount=part
        )
        invoice.status = _invoice_status_from_payments(invoice)
        invoice.save(update_fields=["status", "updated_at"])
        left -= part
    for batch_id, amount in shares:
        SupplierWriteOffLotShare.objects.create(
            organization=organization, write_off=write_off, batch_id=batch_id, amount=amount
        )
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier.balance_written_off",
        target=write_off,
        after={
            "supplier": supplier.name,
            "amount": str(balance),
            "reason": reason,
            "lots": {str(batch_id): str(amount) for batch_id, amount in shares},
        },
    )
    return write_off


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
        number=numbering.next_number(organization, "field_purchase"),
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
            # The driver's purchase money leaves the driver's cash the day of the purchase, written now that the
            # office validated it (D-262).
            driver=purchase.buyer,
            movement_kind="field_purchase",
            # Paid at the port by the driver, validated by the office: the cash limit flag is recorded (D-273).
            confirm_cash_limit=True,
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


@transaction.atomic
def validate_field_purchase(*, purchase: FieldPurchase, actor: User | None) -> FieldPurchase:
    """Validate a purchase as the driver sent it, from the day's check (D-239): one click, when its supplier,
    products and place are already set (else the validation says what is missing). Its kilos enter stock there."""
    purchase = _locked_field_purchase(purchase, purchase.revision)
    _validate_field_purchase(purchase, actor)
    return purchase


# ---- Paying suppliers (P3-T12c, D-159) ----


@transaction.atomic
def receive_goods(
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
    payments: Sequence[FieldPaymentFields] = (),
    with_vat: bool = False,
    confirm_cash_limit: bool = False,
    arrival_temperature: Decimal | None = None,
) -> GoodsReceipt:
    """Record goods received: the receipt, its batches, stock and boxes (D-268). No invoice is made here: the
    office makes the supplier's invoice afterwards, from this receipt. `payments` are the sums given now (D-192):
    each is recorded as money not yet allocated to an invoice, an advance that the invoice made from this receipt
    takes (`apply_advances`). More than the receipt's value is refused, as a typing mistake (D-181)."""
    periods.ensure_open(organization, received_on, field="received_on")
    errors: dict[str, str] = {}
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
        arrival_temperature=arrival_temperature,
    )
    given = sum((payment["amount"] for payment in checked_payments), ZERO)
    received = sum((line.invoiced_amount for line in receipt.lines.all()), ZERO)
    if given > received:
        # Rolls the whole receipt back: more given than the receipt is worth is a typing mistake (D-181).
        raise ValidationError(
            {
                payment_error_key(len(checked_payments) - 1, "amount"): _(
                    "L'argent donné (%(given)s DT) dépasse le montant de la réception (%(total)s DT) : "
                    "vérifiez les montants."
                )
                % {"given": display_money(given), "total": display_money(received)}
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
            allocations=[],
            confirm_cash_limit=confirm_cash_limit,
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


# ---- Price requests to several suppliers, their offers, and the purchase orders made from the chosen ones (D-289) ----


class PriceRequestLineFields(TypedDict, total=False):
    product: "Product"
    quantity: Number


def _price_request_snapshot(request: PriceRequest) -> dict[str, Any]:
    return {
        "number": request.number,
        "status": request.status,
        "requested_on": request.requested_on.isoformat(),
        "lines": [
            {"product": line.product.reference, "quantity": str(line.quantity)}
            for line in request.lines.select_related("product").order_by("id")
        ],
        "suppliers": [offer.supplier.reference for offer in request.offers.select_related("supplier").order_by("id")],
    }


def _checked_supplier(organization: Organization, supplier: "Supplier | None") -> str | None:
    if supplier is None or supplier.organization_id != organization.pk:
        return _("Fournisseur inconnu.")
    if not supplier.is_active:
        return _("Ce fournisseur est archivé.")
    return None


@transaction.atomic
def create_price_request(
    *,
    organization: Organization,
    actor: User | None,
    requested_on: dt.date,
    lines: Sequence[PriceRequestLineFields],
    suppliers: Sequence["Supplier"],
    notes: str = "",
) -> PriceRequest:
    """Ask several suppliers for their prices on some products and kilos (a "demande de prix", DD-2026-0001).

    Each supplier gets an offer still to fill in. Every problem comes back at once: `requested_on`, `suppliers`,
    `lines` and `lines.<index>.<field>`."""
    errors: dict[str, str] = {}
    if requested_on > timezone.localdate():
        errors["requested_on"] = _("La date de la demande ne peut pas être dans le futur.")
    if not suppliers:
        errors["suppliers"] = _("Choisissez au moins un fournisseur.")
    for supplier in suppliers:
        problem = _checked_supplier(organization, supplier)
        if problem:
            errors["suppliers"] = problem
    if len({supplier.pk for supplier in suppliers}) != len(suppliers):
        errors["suppliers"] = _("Un fournisseur est choisi deux fois.")
    if not lines:
        errors["lines"] = _("Ajoutez au moins un produit.")
    checked: list[tuple[Product, Decimal]] = []
    seen: set[int] = set()
    for index, line in enumerate(lines):
        product = line.get("product")
        if product is None or product.organization_id != organization.pk:
            errors[line_error_key(index, "product")] = _("Produit inconnu.")
        elif not product.is_active:
            errors[line_error_key(index, "product")] = _("Ce produit est archivé.")
        elif product.pk in seen:
            errors[line_error_key(index, "product")] = _("Ce produit est déjà sur la demande.")
        else:
            seen.add(product.pk)
        try:
            quantity = checked_quantity(line.get("quantity", ""))
        except (ValueError, TypeError):
            errors[line_error_key(index, "quantity")] = _("Indiquez un poids net en kg, supérieur à zéro.")
            continue
        if product is not None:
            checked.append((product, quantity))
    if errors:
        raise ValidationError(errors)
    request = PriceRequest.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "price_request"),
        requested_on=requested_on,
        notes=notes.strip(),
        created_by=actor,
    )
    PriceRequestLine.objects.bulk_create(
        [
            PriceRequestLine(organization=organization, request=request, product=product, quantity=quantity)
            for product, quantity in checked
        ]
    )
    SupplierOffer.objects.bulk_create(
        [SupplierOffer(organization=organization, request=request, supplier=supplier) for supplier in suppliers]
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="price_request.created",
        target=request,
        after=_price_request_snapshot(request),
    )
    return request


def _locked_open_request(request: PriceRequest) -> PriceRequest:
    locked = PriceRequest.objects.select_for_update().select_related("organization").get(pk=request.pk)
    if locked.status != PriceRequestStatus.OPEN:
        raise ValidationError(
            _("La demande %(number)s est %(status)s : elle ne change plus.")
            % {"number": locked.number, "status": locked.get_status_display().lower()}
        )
    return locked


@transaction.atomic
def record_offer(
    *,
    request: PriceRequest,
    actor: User | None,
    supplier: "Supplier",
    prices: Mapping[int, Number | None],
    reference: str = "",
    received_on: dt.date | None = None,
    valid_until: dt.date | None = None,
    notes: str = "",
) -> SupplierOffer:
    """Type what a supplier answered: a price per kg (without VAT) per request line, by line id; a line left empty is
    not offered. A supplier not asked yet is added to the request. Replaces their earlier answer. Only while open.
    Problems come back on `prices.<line id>`, `supplier`, `received_on`, `valid_until`."""
    locked = _locked_open_request(request)
    organization = locked.organization
    errors: dict[str, str] = {}
    problem = _checked_supplier(organization, supplier)
    if problem and not SupplierOffer.objects.filter(request=locked, supplier=supplier).exists():
        errors["supplier"] = problem
    if received_on is not None and received_on > timezone.localdate():
        errors["received_on"] = _("La date de réception ne peut pas être dans le futur.")
    if valid_until is not None and valid_until < (received_on or locked.requested_on):
        errors["valid_until"] = _("La validité ne peut pas précéder la réception de l'offre.")
    lines = {line.pk: line for line in locked.lines.all()}
    costs: dict[int, Decimal] = {}
    for line_id, value in prices.items():
        key = f"prices.{line_id}"
        if line_id not in lines:
            errors[key] = _("Ligne inconnue sur cette demande.")
            continue
        if value in (None, ""):
            continue
        try:
            cost = checked_amount(value)
        except (ValueError, TypeError):
            errors[key] = _("Indiquez un prix en DT par kg, au millime près.")
            continue
        if cost <= 0:
            errors[key] = _("Le prix doit être supérieur à 0.")
            continue
        costs[line_id] = cost
    if errors:
        raise ValidationError(errors)
    offer, _created = SupplierOffer.objects.get_or_create(
        request=locked, supplier=supplier, defaults={"organization": organization}
    )
    offer.reference = reference.strip()[:50]
    offer.received_on = received_on
    offer.valid_until = valid_until
    offer.notes = notes.strip()
    offer.save()
    offer.lines.all().delete()
    SupplierOfferLine.objects.bulk_create(
        [
            SupplierOfferLine(organization=organization, offer=offer, request_line=lines[line_id], unit_cost=cost)
            for line_id, cost in sorted(costs.items())
        ]
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="price_request.offer_recorded",
        target=locked,
        after={
            "supplier": supplier.reference,
            "reference": offer.reference,
            "valid_until": valid_until.isoformat() if valid_until else None,
            "prices": {lines[line_id].product.reference: str(cost) for line_id, cost in costs.items()},
        },
    )
    return offer


@transaction.atomic
def order_from_offers(
    *,
    request: PriceRequest,
    actor: User | None,
    choices: Mapping[int, "Supplier"],
    ordered_on: dt.date,
    expected_on: dt.date | None = None,
) -> list[PurchaseOrder]:
    """Turn the chosen offers into purchase orders: `choices` gives, per request line id, the supplier retained.
    One order per supplier with their lines at the request's kilos and their price. A line left out is not
    ordered. Refused for a supplier who gave no price on the line, or whose offer is no longer valid. The request
    is then "commandée" and no longer changes."""
    locked = _locked_open_request(request)
    organization = locked.organization
    lines = {line.pk: line for line in locked.lines.select_related("product")}
    offers = {
        offer.supplier_id: offer
        for offer in locked.offers.select_related("supplier").prefetch_related("lines").order_by("id")
    }
    errors: dict[str, str] = {}
    if not choices:
        errors["choices"] = _("Choisissez au moins un fournisseur pour un produit.")
    today = timezone.localdate()
    by_supplier: dict[int, list[tuple[PriceRequestLine, SupplierOfferLine]]] = {}
    for line_id, supplier in choices.items():
        key = f"choices.{line_id}"
        line = lines.get(line_id)
        offer = offers.get(supplier.pk)
        if line is None:
            errors[key] = _("Ligne inconnue sur cette demande.")
            continue
        price = next((row for row in offer.lines.all() if row.request_line_id == line_id), None) if offer else None
        if offer is None or price is None:
            errors[key] = _("%(supplier)s n'a pas donné de prix pour %(product)s.") % {
                "supplier": supplier.name,
                "product": line.product.name,
            }
            continue
        if offer.valid_until is not None and offer.valid_until < today:
            errors[key] = _("L'offre de %(supplier)s n'est plus valable (jusqu'au %(day)s).") % {
                "supplier": supplier.name,
                "day": offer.valid_until.strftime("%d/%m/%Y"),
            }
            continue
        by_supplier.setdefault(supplier.pk, []).append((line, price))
    if errors:
        raise ValidationError(errors)
    orders: list[PurchaseOrder] = []
    for supplier_id, chosen in by_supplier.items():
        offer = offers[supplier_id]
        notes = _("Demande de prix %(number)s") % {"number": locked.number}
        if offer.reference:
            notes += " · " + _("offre %(reference)s") % {"reference": offer.reference}
        order = create_order(
            organization=organization,
            actor=actor,
            supplier=offer.supplier,
            ordered_on=ordered_on,
            expected_on=expected_on,
            notes=notes,
            lines=[
                {"product": line.product, "ordered_quantity": line.quantity, "unit_cost": price.unit_cost}
                for line, price in sorted(chosen, key=lambda pair: pair[0].pk)
            ],
        )
        offer.order = order
        offer.save(update_fields=["order", "updated_at"])
        SupplierOfferLine.objects.filter(pk__in=[price.pk for _line, price in chosen]).update(retained=True)
        orders.append(order)
    locked.status = PriceRequestStatus.ORDERED
    locked.closed_at = timezone.now()
    locked.save(update_fields=["status", "closed_at", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="price_request.ordered",
        target=locked,
        after={"orders": [order.number for order in orders]},
    )
    return orders


@transaction.atomic
def cancel_price_request(*, request: PriceRequest, actor: User | None) -> PriceRequest:
    """Give up a price request still open: nothing is ordered."""
    locked = _locked_open_request(request)
    locked.status = PriceRequestStatus.CANCELLED
    locked.closed_at = timezone.now()
    locked.save(update_fields=["status", "closed_at", "updated_at"])
    audit.record(organization=locked.organization, actor=actor, action="price_request.cancelled", target=locked)
    return locked


# ---- Supplier credit notes (avoirs fournisseurs, D-300) ----


def credit_line_error_key(index: int, field: str) -> str:
    return f"lines.{index}.{field}"


def _apply_credits(invoice: SupplierInvoice, notes: Sequence[SupplierCreditNote]) -> None:
    """Settle a posted invoice with what is left of `notes`, in their order, up to what it still owes."""
    if invoice.status not in selectors.OPEN_STATUSES:
        return
    left = invoice.total - _paid_on(invoice)
    for note in notes:
        if left <= 0:
            break
        applied = SupplierCreditAllocation.objects.filter(credit_note=note).aggregate(total=Sum("amount"))["total"]
        rest = note.total - (applied or Decimal("0.000"))
        part = min(left, rest)
        if part <= 0:
            continue
        SupplierCreditAllocation.objects.create(
            organization=invoice.organization, credit_note=note, invoice=invoice, amount=part
        )
        left -= part
    invoice.status = _invoice_status_from_payments(invoice)
    invoice.save(update_fields=["status", "updated_at"])


def _checked_credit_lines(
    organization: Organization,
    supplier: "Supplier",
    invoice: SupplierInvoice | None,
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    if not items:
        raise ValidationError({"lines": _("Ajoutez au moins une ligne.")})
    creditable = {
        line.receipt_line_id: line
        for line in selectors.creditable_lines(
            organization, supplier_id=supplier.pk, invoice_id=invoice.pk if invoice is not None else None
        )
    }
    settled = partnership_selectors.settled_batch_ids(
        organization, batch_ids=[line.batch_id for line in creditable.values()]
    )
    errors: dict[str, str] = {}
    checked: list[dict[str, Any]] = []
    used: dict[int, Decimal] = {}
    gaps: dict[int, Decimal] = {}
    for index, item in enumerate(items):

        def key(field: str, index: int = index) -> str:
            return credit_line_error_key(index, field)

        line_id = item.get("receipt_line")
        line = creditable.get(line_id) if isinstance(line_id, int) else None
        if line is None:
            errors[key("receipt_line")] = _(
                "Cette ligne de réception n'est pas proposée : autre fournisseur, autre facture ou déjà créditée."
            )
            continue
        kind = item.get("kind")
        if kind not in SupplierCreditKind.values:
            errors[key("kind")] = _("Choisissez le motif de la ligne.")
            continue
        try:
            quantity = checked_quantity(item.get("quantity", ""))
        except (ValueError, TypeError):
            errors[key("quantity")] = _("Indiquez un poids en kg, supérieur à zéro.")
            continue
        unit_amount = line.unit_cost
        location = None
        if kind == SupplierCreditKind.PRICE:
            try:
                unit_amount = checked_amount(item.get("unit_amount", ""))
            except (ValueError, TypeError):
                errors[key("unit_amount")] = _("Indiquez la remise par kg en DT.")
                continue
            if unit_amount <= 0 or unit_amount > line.unit_cost:
                errors[key("unit_amount")] = _(
                    "La remise par kg doit être entre 0 et le prix d'achat (%(cost)s DT)."
                ) % {"cost": display_money(line.unit_cost)}
                continue
            if quantity > line.invoiced_quantity:
                errors[key("quantity")] = _("Au plus %(kg)s kg facturés.") % {"kg": line.invoiced_quantity}
                continue
        elif kind == SupplierCreditKind.WEIGHT:
            gap = gaps.get(line.receipt_line_id, line.weight_gap)
            if quantity > gap:
                errors[key("quantity")] = _("L'écart restant est de %(kg)s kg (facturé − accepté − déjà réclamé).") % {
                    "kg": gap
                }
                continue
            gaps[line.receipt_line_id] = gap - quantity
        else:
            location_id = item.get("from_location")
            try:
                location = (
                    inventory_selectors.location_of(organization, location_id) if isinstance(location_id, int) else None
                )
            except ObjectDoesNotExist:
                location = None
            if location is None:
                errors[key("from_location")] = _("Indiquez d'où partent les kilos rendus.")
                continue
        if kind != SupplierCreditKind.WEIGHT and line.batch_id in settled:
            errors[key("receipt_line")] = _(
                "Le lot %(lot)s est déjà réglé avec son partenaire : il ne change plus."
            ) % {"lot": line.batch_number}
            continue
        amount = line_total(quantity, unit_amount)
        if amount <= 0:
            errors[key("quantity")] = _("Le montant de la ligne est nul.")
            continue
        room = line.amount_left - used.get(line.receipt_line_id, Decimal("0.000"))
        if amount > room:
            errors[key("quantity")] = _("Au plus %(amount)s DT encore à créditer sur cette ligne.") % {
                "amount": display_money(room)
            }
            continue
        used[line.receipt_line_id] = used.get(line.receipt_line_id, Decimal("0.000")) + amount
        checked.append(
            {
                "line": line,
                "kind": kind,
                "quantity": quantity,
                "unit_amount": unit_amount,
                "amount": amount,
                "location": location,
            }
        )
    if errors:
        raise ValidationError(errors)
    return checked


def _credit_snapshot(note: SupplierCreditNote) -> dict[str, Any]:
    return {
        "number": note.number,
        "supplier": note.supplier.name,
        "invoice": note.invoice.number if note.invoice else "",
        "credited_on": note.credited_on.isoformat(),
        "reason": note.reason,
        "total_excl_tax": str(note.total_excl_tax),
        "vat_total": str(note.vat_total),
        "total": str(note.total),
        "lines": [
            {"batch": line.batch_id, "kind": line.kind, "quantity": str(line.quantity), "amount": str(line.amount)}
            for line in note.lines.all()
        ],
    }


@transaction.atomic
def create_credit_note(
    *,
    organization: Organization,
    actor: User | None,
    supplier: "Supplier",
    invoice: SupplierInvoice | None,
    credited_on: dt.date,
    reason: str,
    lines: Sequence[Mapping[str, Any]],
    supplier_reference: str = "",
) -> SupplierCreditNote:
    """Save an avoir fournisseur (D-300): per receipt line, kilos sent back (they leave the stock as a supplier
    return, from the place named), kilos invoiced but never accepted, or a price cut per kg. VAT is given back at the
    receipt's rate when it was bought with VAT. It settles its invoice first, then the supplier's other open invoices;
    the rest waits for the next invoice. Saved once, never edited nor deleted."""
    periods.ensure_open(organization, credited_on, field="credited_on")
    if supplier.organization_id != organization.pk:
        raise ValidationError({"supplier": _("Fournisseur inconnu.")})
    errors: dict[str, str] = {}
    if invoice is not None:
        if invoice.organization_id != organization.pk or invoice.supplier_id != supplier.pk:
            errors["invoice"] = _("Cette facture n'est pas de ce fournisseur.")
        elif invoice.status == SupplierInvoiceStatus.DRAFT:
            errors["invoice"] = _("Validez d'abord la facture, ou supprimez-la et refaites-la.")
        elif invoice.is_opening:
            errors["invoice"] = _("Un solde d'ouverture n'a pas de réceptions à créditer.")
    reason = reason.strip()
    if not reason:
        errors["reason"] = _("Indiquez la raison de l'avoir.")
    if credited_on > timezone.localdate():
        errors["credited_on"] = _("La date ne peut pas être dans le futur.")
    if errors:
        raise ValidationError(errors)
    # One credit note of a supplier at a time: the receipt lines' remaining amounts are read under this lock.
    list(
        SupplierInvoice.objects.select_for_update()
        .filter(organization=organization, supplier=supplier)
        .values_list("pk", flat=True)
    )
    checked = _checked_credit_lines(organization, supplier, invoice, lines)
    by_rate: dict[Decimal, Decimal] = {}
    for values in checked:
        values["rate"] = None
        if values["line"].with_vat:
            receipt_line = GoodsReceiptLine.objects.select_related("product", "receipt").get(
                pk=values["line"].receipt_line_id
            )
            rate = sales_selectors.vat_rate_of_product_on(
                organization, receipt_line.product, receipt_line.receipt.received_on
            )
            values["rate"] = rate
            by_rate[rate] = by_rate.get(rate, Decimal("0.000")) + values["amount"]
    total_excl = sum((values["amount"] for values in checked), Decimal("0.000"))
    # VAT rounded once per rate, as on the invoice (D-294).
    vat_total = sum((money(base * rate / 100) for rate, base in by_rate.items()), Decimal("0.000"))
    note = SupplierCreditNote.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "supplier_credit_note", year=credited_on.year),
        supplier=supplier,
        invoice=invoice,
        credited_on=credited_on,
        supplier_reference=supplier_reference.strip()[:50],
        reason=reason,
        total_excl_tax=total_excl,
        vat_total=vat_total,
        total=total_excl + vat_total,
        created_by=actor,
    )
    moment = inventory.moment_of(credited_on) if credited_on != timezone.localdate() else timezone.now()
    for values in checked:
        line = values["line"]
        rate = values["rate"]
        row = SupplierCreditNoteLine.objects.create(
            organization=organization,
            credit_note=note,
            receipt_line_id=line.receipt_line_id,
            batch_id=line.batch_id,
            kind=values["kind"],
            quantity=values["quantity"],
            unit_amount=values["unit_amount"],
            amount=values["amount"],
            vat_rate=rate,
            vat_amount=money(values["amount"] * rate / 100) if rate is not None else Decimal("0.000"),
            from_location=values["location"],
        )
        if values["kind"] == SupplierCreditKind.RETURN:
            inventory.post_movement(
                organization=organization,
                actor=actor,
                kind=MovementKind.SUPPLIER_RETURN,
                batch=inventory_selectors.batch_of(organization, line.batch_id),
                quantity=values["quantity"],
                from_location=values["location"],
                reason=_("Retour fournisseur %(number)s") % {"number": note.number},
                source=row,
                occurred_at=moment,
            )
    open_invoices = list(selectors.open_invoices_of(organization, supplier_id=supplier.pk))
    if invoice is not None:
        open_invoices.sort(key=lambda row: row.pk != invoice.pk)
    for target in open_invoices:
        locked = SupplierInvoice.objects.select_for_update().get(pk=target.pk)
        _apply_credits(locked, [note])
    audit.record(
        organization=organization,
        actor=actor,
        action="supplier_credit_note.created",
        target=note,
        after=_credit_snapshot(note),
    )
    return note
