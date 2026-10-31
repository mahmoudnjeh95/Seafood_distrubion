"""Reusable read queries of purchases."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Literal

from django.db.models import (
    Case,
    DecimalField,
    Exists,
    ExpressionWrapper,
    F,
    OuterRef,
    Prefetch,
    Q,
    QuerySet,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core.documents import DocumentFilters, DocumentRow, Tone, document_key
from apps.core.models import Organization

from .models import (
    RECEIVABLE_ORDER_STATUSES,
    FieldPurchase,
    FieldPurchaseLine,
    FieldPurchasePayment,
    FieldPurchaseRevision,
    FieldPurchaseStatus,
    GoodsReceipt,
    GoodsReceiptLine,
    PaymentMethod,
    PlanLineStatus,
    PurchaseOrder,
    PurchaseOrderLine,
    PurchaseOrderStatus,
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

if TYPE_CHECKING:
    from .statements import SupplierStatement

# A line differs when the accepted weight is not the invoiced one, or not the ordered one when there was an order.
DIFFERENT = ~Q(accepted_quantity=F("invoiced_quantity")) | (
    Q(ordered_quantity__isnull=False) & ~Q(accepted_quantity=F("ordered_quantity"))
)


def receipts_of(
    organization: Organization,
    *,
    supplier_id: int | None = None,
    search: str = "",
    with_differences: bool = False,
    uninvoiced: bool = False,
    purchase_order_id: int | None = None,
) -> QuerySet[GoodsReceipt]:
    """Receipts newest first, with supplier, location, lines (product and batch), their invoice if any,
    and `has_differences`.

    `search` matches the receipt number, the supplier's reference and the supplier's name. `uninvoiced`
    keeps the receipts not on any supplier invoice yet, draft or posted.
    """
    lines = GoodsReceiptLine.objects.select_related("product", "batch").order_by("id")
    receipts = (
        GoodsReceipt.objects.for_organization(organization)
        .select_related("supplier", "location", "created_by", "invoice_link__invoice", "purchase_order")
        .prefetch_related(Prefetch("lines", queryset=lines))
        .annotate(has_differences=Exists(GoodsReceiptLine.objects.filter(DIFFERENT, receipt=OuterRef("pk"))))
        .order_by("-received_on", "-id")
    )
    if supplier_id is not None:
        receipts = receipts.filter(supplier_id=supplier_id)
    if purchase_order_id is not None:
        receipts = receipts.filter(purchase_order_id=purchase_order_id)
    if search := search.strip():
        receipts = receipts.filter(
            Q(number__icontains=search) | Q(supplier_reference__icontains=search) | Q(supplier__name__icontains=search)
        )
    if with_differences:
        receipts = receipts.filter(has_differences=True)
    if uninvoiced:
        receipts = receipts.filter(invoice_link__isnull=True)
    return receipts


def receipt_of(organization: Organization, receipt_id: int) -> GoodsReceipt:
    """One receipt with its lines. Raises GoodsReceipt.DoesNotExist outside the organization."""
    return receipts_of(organization).get(pk=receipt_id)


def difference_lines(
    organization: Organization,
    *,
    supplier_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> QuerySet[GoodsReceiptLine]:
    """Receipt lines whose accepted weight differs from the invoiced or ordered weight, newest first."""
    lines = (
        GoodsReceiptLine.objects.for_organization(organization)
        .filter(DIFFERENT)
        .select_related("receipt", "receipt__supplier", "product", "batch")
        .order_by("-receipt__received_on", "-receipt_id", "id")
    )
    if supplier_id is not None:
        lines = lines.filter(receipt__supplier_id=supplier_id)
    if date_from is not None:
        lines = lines.filter(receipt__received_on__gte=date_from)
    if date_to is not None:
        lines = lines.filter(receipt__received_on__lte=date_to)
    return lines


def receipt_totals(receipt: GoodsReceipt) -> tuple[Decimal, Decimal]:
    """(invoiced total, accepted total): line amounts rounded to the millime, then added (ARCHITECTURE §4.1)."""
    lines = list(receipt.lines.all())
    invoiced = sum((line.invoiced_amount for line in lines), Decimal("0.000"))
    accepted = sum((line.accepted_amount for line in lines), Decimal("0.000"))
    return invoiced, accepted


ZERO = Decimal("0.000")


# ---- Purchase orders (D-076) ----

type OrderStatusFilter = Literal["open", "partly_received", "received", "closed", "cancelled", "pending"]


def orders_of(
    organization: Organization,
    *,
    supplier_id: int | None = None,
    status: OrderStatusFilter | None = None,
    search: str = "",
) -> QuerySet[PurchaseOrder]:
    """Purchase orders newest first, with supplier, receipts and lines carrying `received_quantity`.

    `status="pending"` keeps the orders still waiting for goods (open or partly received). `search`
    matches the order number and the supplier's name.
    """
    lines = (
        PurchaseOrderLine.objects.select_related("product")
        .annotate(received_quantity=Coalesce(Sum("receipt_lines__accepted_quantity"), ZERO, output_field=QUANTITY))
        .order_by("id")
    )
    receipts = GoodsReceipt.objects.order_by("received_on", "id")
    orders = (
        PurchaseOrder.objects.for_organization(organization)
        .select_related("supplier", "created_by")
        .prefetch_related(Prefetch("lines", queryset=lines))
        .prefetch_related(Prefetch("receipts", queryset=receipts))
        .order_by("-ordered_on", "-id")
    )
    if supplier_id is not None:
        orders = orders.filter(supplier_id=supplier_id)
    if status == "pending":
        orders = orders.filter(status__in=RECEIVABLE_ORDER_STATUSES)
    elif status is not None:
        orders = orders.filter(status=status)
    if search := search.strip():
        orders = orders.filter(Q(number__icontains=search) | Q(supplier__name__icontains=search))
    return orders


def order_of(organization: Organization, order_id: int) -> PurchaseOrder:
    """One order with its lines and receipts. Raises PurchaseOrder.DoesNotExist outside the organization."""
    return orders_of(organization).get(pk=order_id)


def order_line_remaining(line: PurchaseOrderLine) -> Decimal:
    """Weight still to come on a line (never negative: a delivery of more than asked leaves nothing)."""
    return max(line.ordered_quantity - getattr(line, "received_quantity", ZERO), ZERO)


# ---- Supplier invoices, payments and balances (P1-T08, D-043) ----
AMOUNT = DecimalField(max_digits=14, decimal_places=3)
QUANTITY = DecimalField(max_digits=12, decimal_places=3)
# Posted and not fully paid: what is still owed on invoices.
OPEN_STATUSES = (SupplierInvoiceStatus.POSTED, SupplierInvoiceStatus.PARTLY_PAID)

type InvoiceStatusFilter = Literal["draft", "posted", "partly_paid", "paid", "open"]


def _sum_of_allocations(**match: Any) -> Coalesce:
    """The sum of the allocations matching `match` (an OuterRef), as a subquery: no join, no duplicate rows.
    Those of a voided règlement count for nothing (D-211)."""
    group = next(iter(match))
    allocations = (
        SupplierPaymentAllocation.objects.filter(**match, payment__voided_at__isnull=True)
        .order_by()
        .values(group)
        .annotate(total=Sum("amount"))
        .values("total")
    )
    return Coalesce(Subquery(allocations, output_field=AMOUNT), Value(ZERO), output_field=AMOUNT)


def _sum_of_releases(**match: Any) -> Coalesce:
    """The sum of what rejected effets took back (`RejectedRelease`) matching `match`, as a subquery (D-218)."""
    group = next(iter(match))
    releases = (
        RejectedRelease.objects.filter(**match).order_by().values(group).annotate(total=Sum("amount")).values("total")
    )
    return Coalesce(Subquery(releases, output_field=AMOUNT), Value(ZERO), output_field=AMOUNT)


def _sum_of_rejected(**match: Any) -> Coalesce:
    group = next(iter(match))
    rows = RejectedEffet.objects.filter(**match).order_by().values(group).annotate(total=Sum("amount")).values("total")
    return Coalesce(Subquery(rows, output_field=AMOUNT), Value(ZERO), output_field=AMOUNT)


def invoices_of(
    organization: Organization,
    *,
    supplier_id: int | None = None,
    status: InvoiceStatusFilter | None = None,
    search: str = "",
    overdue: bool = False,
) -> QuerySet[SupplierInvoice]:
    """Supplier invoices newest first, with their receipts and allocations, `paid_amount` and `outstanding`.

    `status="open"` keeps the posted invoices not fully paid; `overdue` keeps those whose due date has
    passed. `search` matches our number, the supplier's invoice number and the supplier's name.
    """
    links = SupplierInvoiceReceipt.objects.select_related("receipt").order_by("receipt__received_on", "receipt_id")
    allocations = (
        SupplierPaymentAllocation.objects.filter(payment__voided_at__isnull=True)
        .select_related("payment")
        .order_by("payment__paid_on", "id")
    )
    invoices = (
        SupplierInvoice.objects.for_organization(organization)
        .select_related("supplier", "created_by", "posted_by")
        .prefetch_related(Prefetch("receipt_links", queryset=links))
        .prefetch_related(Prefetch("allocations", queryset=allocations))
        .annotate(
            paid_amount=ExpressionWrapper(
                _sum_of_allocations(invoice=OuterRef("pk")) - _sum_of_releases(invoice=OuterRef("pk")),
                output_field=AMOUNT,
            )
        )
        .annotate(outstanding=ExpressionWrapper(F("total") - F("paid_amount"), output_field=AMOUNT))
        .order_by("-invoice_date", "-id")
    )
    if supplier_id is not None:
        invoices = invoices.filter(supplier_id=supplier_id)
    if status == "open":
        invoices = invoices.filter(status__in=OPEN_STATUSES)
    elif status is not None:
        invoices = invoices.filter(status=status)
    if overdue:
        invoices = invoices.filter(status__in=OPEN_STATUSES, due_date__lt=timezone.localdate())
    if search := search.strip():
        invoices = invoices.filter(
            Q(number__icontains=search) | Q(supplier_reference__icontains=search) | Q(supplier__name__icontains=search)
        )
    return invoices


def invoice_of(organization: Organization, invoice_id: int) -> SupplierInvoice:
    """One invoice with its receipts and payments. Raises SupplierInvoice.DoesNotExist outside the organization."""
    return invoices_of(organization).get(pk=invoice_id)


def open_invoices_of(organization: Organization, *, supplier_id: int) -> QuerySet[SupplierInvoice]:
    """A supplier's posted invoices still to pay, the oldest due date first: the order a payment settles them."""
    return invoices_of(organization, supplier_id=supplier_id, status="open").order_by("due_date", "invoice_date", "id")


type PaymentState = Literal["active", "voided", "unallocated"]


def payments_of(
    organization: Organization,
    *,
    supplier_id: int | None = None,
    search: str = "",
    unallocated: bool = False,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    method: str | None = None,
    state: PaymentState | None = None,
) -> QuerySet[SupplierPayment]:
    """Supplier payments newest first (voided ones too), with their lines, allocations, `allocated_amount` and
    `unallocated_amount` (0 for a voided one: it allocates nothing and is no advance, D-211).

    `unallocated` (or `state="unallocated"`) keeps the payments not voided with a part not allocated yet
    (advances); `state` "active" or "voided" the others. `method` keeps those with a line of that means (or
    "mixed": several means). Days paid are inclusive. `search` matches our number, the cheque or transfer
    reference (of any line) and the supplier's name.
    """
    allocations = SupplierPaymentAllocation.objects.select_related("invoice").order_by("id")
    lines = SupplierPaymentLine.objects.select_related("instrument__bank").order_by("id")
    payments = (
        SupplierPayment.objects.for_organization(organization)
        .select_related("supplier", "created_by", "voided_by")
        .prefetch_related(Prefetch("allocations", queryset=allocations))
        .prefetch_related(Prefetch("lines", queryset=lines))
        .annotate(
            allocated_amount=ExpressionWrapper(
                _sum_of_allocations(payment=OuterRef("pk")) - _sum_of_releases(rejected__payment=OuterRef("pk")),
                output_field=AMOUNT,
            ),
            rejected_amount=_sum_of_rejected(payment=OuterRef("pk")),
        )
        .annotate(
            unallocated_amount=Case(
                When(voided_at__isnull=False, then=Value(ZERO)),
                default=ExpressionWrapper(
                    F("amount") - F("rejected_amount") - F("allocated_amount"), output_field=AMOUNT
                ),
                output_field=AMOUNT,
            )
        )
        .order_by("-paid_on", "-id")
    )
    if supplier_id is not None:
        payments = payments.filter(supplier_id=supplier_id)
    if unallocated or state == "unallocated":
        payments = payments.filter(unallocated_amount__gt=0)
    elif state == "active":
        payments = payments.filter(voided_at__isnull=True)
    elif state == "voided":
        payments = payments.filter(voided_at__isnull=False)
    if date_from is not None:
        payments = payments.filter(paid_on__gte=date_from)
    if date_to is not None:
        payments = payments.filter(paid_on__lte=date_to)
    if method == PaymentMethod.MIXED:
        payments = payments.filter(method=PaymentMethod.MIXED)
    elif method:
        payments = payments.filter(Exists(SupplierPaymentLine.objects.filter(payment=OuterRef("pk"), method=method)))
    if search := search.strip():
        in_lines = SupplierPaymentLine.objects.filter(payment=OuterRef("pk")).filter(
            Q(reference__icontains=search) | Q(instrument__number__icontains=search)
        )
        payments = payments.filter(
            Q(number__icontains=search)
            | Q(reference__icontains=search)
            | Q(supplier__name__icontains=search)
            | Exists(in_lines)
        )
    return payments


def payment_of(organization: Organization, payment_id: int) -> SupplierPayment:
    """One payment with its lines (and each effet's history), allocations. Raises SupplierPayment.DoesNotExist
    outside the organization."""
    return (
        payments_of(organization)
        .prefetch_related("lines__instrument__events__actor", "lines__rejected")
        .get(pk=payment_id)
    )


@dataclass(frozen=True)
class PaymentTotals:
    """What a filtered list of règlements adds up to, voided ones left out; `by_method` from their lines."""

    count: int
    voided: int
    total: Decimal
    allocated: Decimal
    unallocated: Decimal
    by_method: dict[str, Decimal]


def payment_totals(payments: QuerySet[SupplierPayment]) -> PaymentTotals:
    """The totals of `payments` (a `payments_of` queryset, its filters applied)."""
    live = payments.filter(voided_at__isnull=True)
    rows = live.aggregate(total=Sum("amount"))
    allocated = SupplierPaymentAllocation.objects.filter(payment__in=live.values("pk")).aggregate(total=Sum("amount"))[
        "total"
    ]
    released = RejectedRelease.objects.filter(rejected__payment__in=live.values("pk")).aggregate(total=Sum("amount"))[
        "total"
    ]
    rejected = RejectedEffet.objects.filter(payment__in=live.values("pk")).aggregate(total=Sum("amount"))["total"]
    by_method = {
        row["method"]: row["total"]
        for row in SupplierPaymentLine.objects.filter(payment__in=live.values("pk"))
        .values("method")
        .annotate(total=Sum("amount"))
        .order_by("method")
    }
    total = rows["total"] or ZERO
    allocated = (allocated or ZERO) - (released or ZERO)
    return PaymentTotals(
        count=live.count(),
        voided=payments.filter(voided_at__isnull=False).count(),
        total=total,
        allocated=allocated,
        unallocated=total - (rejected or ZERO) - allocated,
        by_method=by_method,
    )


@dataclass(frozen=True)
class SupplierBalance:
    """What the company owes one supplier for goods: the trade payable only (D-040, D-043).

    `balance` = posted invoices − payments. Negative, the supplier holds an advance. A partner's capital
    and profit share are other balances (Phase 6) and never appear here.
    """

    supplier_id: int
    invoiced: Decimal  # posted invoices, paid or not
    paid: Decimal  # every payment, allocated or not
    balance: Decimal
    outstanding: Decimal  # still to pay on posted invoices
    unallocated: Decimal  # paid but not allocated to an invoice yet (advances)
    overdue: Decimal  # still to pay on invoices past their due date
    open_invoices: int
    overdue_invoices: int
    draft_invoices: int
    draft_total: Decimal
    uninvoiced_receipts: int  # received but on no invoice yet: not owed until invoiced
    uninvoiced_total: Decimal


def _total(queryset: QuerySet[Any], field: str) -> Decimal:
    value = queryset.aggregate(total=Sum(field))["total"]
    return value if value is not None else ZERO


# ---- The "Documents" page (P2-T11, D-102) ----

_ORDER_TONES: dict[str, Tone] = {
    PurchaseOrderStatus.OPEN: "waiting",
    PurchaseOrderStatus.PARTLY_RECEIVED: "waiting",
    PurchaseOrderStatus.RECEIVED: "done",
    PurchaseOrderStatus.CLOSED: "done",
    PurchaseOrderStatus.CANCELLED: "cancelled",
}


def _in_days(queryset: QuerySet[Any], field: str, filters: DocumentFilters) -> QuerySet[Any]:
    if filters.date_from is not None:
        queryset = queryset.filter(**{f"{field}__gte": filters.date_from})
    if filters.date_to is not None:
        queryset = queryset.filter(**{f"{field}__lte": filters.date_to})
    if search := filters.search.strip():
        queryset = queryset.filter(Q(number__icontains=search) | Q(supplier__name__icontains=search))
    return queryset


def document_rows(organization: Organization, filters: DocumentFilters, *, may_write: bool) -> list[DocumentRow]:
    """Purchase orders (BA), goods receipts (BR) and supplier invoices (FF) as rows of the "Documents" page.

    `may_write` is whether the person may change purchases (owner or manager); `actions` follow the services'
    rules, which still check everything when an action runs.
    """
    rows: list[DocumentRow] = []
    wanted = filters.types

    if not wanted or "BA" in wanted:
        lines = PurchaseOrderLine.objects.order_by("id")
        orders = (
            PurchaseOrder.objects.for_organization(organization)
            .select_related("supplier")
            .prefetch_related(Prefetch("lines", queryset=lines))
            .annotate(has_receipts=Exists(GoodsReceipt.objects.filter(purchase_order=OuterRef("pk"))))
        )
        for order in _in_days(orders, "ordered_on", filters):
            status = PurchaseOrderStatus(order.status)
            actions: list[str] = []
            if may_write and status in RECEIVABLE_ORDER_STATUSES:
                actions.append("receive")
                if status == PurchaseOrderStatus.OPEN and not order.has_receipts:
                    actions.append("cancel")
                if status == PurchaseOrderStatus.PARTLY_RECEIVED:
                    actions.append("close")
            rows.append(
                DocumentRow(
                    type="BA",
                    id=order.pk,
                    number=order.number,
                    partner_side="supplier",
                    partner_id=order.supplier_id,
                    partner_name=order.supplier.name,
                    date=order.ordered_on,
                    amount=sum((line.ordered_amount for line in order.lines.all()), ZERO),
                    status=status.value,
                    status_label=str(status.label),
                    tone=_ORDER_TONES[status],
                    actions=actions,
                )
            )

    if not wanted or "BR" in wanted:
        receipt_lines = GoodsReceiptLine.objects.order_by("id")
        receipts = (
            GoodsReceipt.objects.for_organization(organization)
            .select_related("supplier")
            .prefetch_related(Prefetch("lines", queryset=receipt_lines))
            .annotate(invoiced=Exists(SupplierInvoiceReceipt.objects.filter(receipt=OuterRef("pk"))))
        )
        for receipt in _in_days(receipts, "received_on", filters):
            rows.append(
                DocumentRow(
                    type="BR",
                    id=receipt.pk,
                    number=receipt.number,
                    partner_side="supplier",
                    partner_id=receipt.supplier_id,
                    partner_name=receipt.supplier.name,
                    date=receipt.received_on,
                    # What the supplier charges for it (invoiced kg × cost, D-039).
                    amount=receipt_totals(receipt)[0],
                    # A receipt has no status: the goods are in stock once it is saved.
                    status="received",
                    status_label=str(_("Reçu")),
                    tone="done",
                    parents=[document_key("BA", receipt.purchase_order_id)] if receipt.purchase_order_id else [],
                    actions=["to_supplier_invoice"] if may_write and not receipt.invoiced else [],
                )
            )

    if not wanted or "FF" in wanted:
        links = SupplierInvoiceReceipt.objects.order_by("receipt__received_on", "receipt_id")
        invoices = (
            SupplierInvoice.objects.for_organization(organization)
            .select_related("supplier")
            .prefetch_related(Prefetch("receipt_links", queryset=links))
        )
        for invoice in _in_days(invoices, "invoice_date", filters):
            invoice_status = SupplierInvoiceStatus(invoice.status)
            actions = []
            if may_write:
                if invoice_status == SupplierInvoiceStatus.DRAFT:
                    actions = ["edit", "post", "delete"]
                elif invoice_status in OPEN_STATUSES:
                    actions = ["pay"]
            rows.append(
                DocumentRow(
                    type="FF",
                    id=invoice.pk,
                    number=invoice.number,
                    partner_side="supplier",
                    partner_id=invoice.supplier_id,
                    partner_name=invoice.supplier.name,
                    date=invoice.invoice_date,
                    amount=invoice.total,
                    status=invoice_status.value,
                    status_label=str(invoice_status.label),
                    tone="draft" if invoice_status == SupplierInvoiceStatus.DRAFT else "done",
                    parents=[document_key("BR", link.receipt_id) for link in invoice.receipt_links.all()],
                    actions=actions,
                )
            )
    return rows


def supplier_balance(organization: Organization, supplier_id: int) -> SupplierBalance:
    """The trade balance of one supplier of the organization (an unknown supplier simply has zeros)."""
    invoices = SupplierInvoice.objects.for_organization(organization).filter(supplier_id=supplier_id)
    posted = invoices.exclude(status=SupplierInvoiceStatus.DRAFT)
    drafts = invoices.filter(status=SupplierInvoiceStatus.DRAFT)
    payments = SupplierPayment.objects.for_organization(organization).filter(
        supplier_id=supplier_id, voided_at__isnull=True
    )
    allocations = SupplierPaymentAllocation.objects.for_organization(organization).filter(
        payment__supplier_id=supplier_id, payment__voided_at__isnull=True
    )
    open_invoices = list(invoices_of(organization, supplier_id=supplier_id, status="open"))
    today = timezone.localdate()
    late = [invoice for invoice in open_invoices if invoice.due_date < today]
    uninvoiced = list(receipts_of(organization, supplier_id=supplier_id, uninvoiced=True))
    invoiced = _total(posted, "total")
    # A rejected effet of ours was never paid: the supplier is owed it again (D-218).
    rejected = _total(RejectedEffet.objects.for_organization(organization).filter(supplier_id=supplier_id), "amount")
    released = _total(
        RejectedRelease.objects.for_organization(organization).filter(rejected__supplier_id=supplier_id), "amount"
    )
    paid = _total(payments, "amount") - rejected
    return SupplierBalance(
        supplier_id=supplier_id,
        invoiced=invoiced,
        paid=paid,
        balance=invoiced - paid,
        outstanding=sum((getattr(invoice, "outstanding") for invoice in open_invoices), ZERO),  # noqa: B009
        unallocated=paid - (_total(allocations, "amount") - released),
        overdue=sum((getattr(invoice, "outstanding") for invoice in late), ZERO),  # noqa: B009
        open_invoices=len(open_invoices),
        overdue_invoices=len(late),
        draft_invoices=drafts.count(),
        draft_total=_total(drafts, "total"),
        uninvoiced_receipts=len(uninvoiced),
        uninvoiced_total=sum((receipt_totals(receipt)[0] for receipt in uninvoiced), ZERO),
    )


def payments_by_day(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> dict[dt.date, Decimal]:
    """Money paid to suppliers per day (`paid_on`), inclusive."""
    rows = (
        SupplierPayment.objects.for_organization(organization)
        .filter(paid_on__gte=date_from, paid_on__lte=date_to, voided_at__isnull=True)
        .values("paid_on")
        .annotate(total=Sum("amount"))
    )
    return {row["paid_on"]: row["total"] for row in rows}


def supplier_statement(
    organization: Organization, supplier_id: int, *, date_from: dt.date | None, date_to: dt.date
) -> "SupplierStatement":
    """One supplier's receipts (line by line), invoices, payments and trade account from `date_from` (the beginning
    when None) to `date_to` (`statements.SupplierStatement`, D-156)."""
    from . import statements

    return statements.supplier_statement(organization, supplier_id, date_from=date_from, date_to=date_to)


# ---- Buying at the port, the "achat terrain" (P3-T12, D-176) ----

type FieldPurchaseStatusFilter = Literal["submitted", "validated", "refused"]

# A purchase still to check this long after it was sent raises an alert (provisional, Q28).
FIELD_PURCHASE_LATE_AFTER = dt.timedelta(hours=24)


def field_purchases_of(
    organization: Organization,
    *,
    status: FieldPurchaseStatusFilter | None = None,
    buyer_id: int | None = None,
    search: str = "",
) -> QuerySet[FieldPurchase]:
    """Purchases at the port newest first, with their lines, payments, revisions and the documents of a validated one.

    `search` matches the number, the supplier's name (or the new name typed) and the supplier's paper number.
    """
    lines = FieldPurchaseLine.objects.select_related("product", "partner").order_by("id")
    revisions = FieldPurchaseRevision.objects.select_related("created_by").order_by("number")
    purchases = (
        FieldPurchase.objects.for_organization(organization)
        .select_related("supplier", "buyer", "location", "receipt", "invoice", "decided_by")
        .prefetch_related(Prefetch("lines", queryset=lines))
        .prefetch_related(Prefetch("payments", queryset=FieldPurchasePayment.objects.order_by("id")))
        .prefetch_related(Prefetch("revisions", queryset=revisions))
        .order_by("-bought_on", "-id")
    )
    if status is not None:
        purchases = purchases.filter(status=status)
    if buyer_id is not None:
        purchases = purchases.filter(buyer_id=buyer_id)
    if search := search.strip():
        purchases = purchases.filter(
            Q(number__icontains=search)
            | Q(supplier__name__icontains=search)
            | Q(proposed_supplier__icontains=search)
            | Q(supplier_reference__icontains=search)
        )
    return purchases


def field_purchase_of(organization: Organization, purchase_id: int) -> FieldPurchase:
    """One purchase. Raises FieldPurchase.DoesNotExist outside the organization."""
    return field_purchases_of(organization).get(pk=purchase_id)


def field_purchase_is_late(purchase: FieldPurchase, *, now: dt.datetime | None = None) -> bool:
    """Still to check, and sent more than FIELD_PURCHASE_LATE_AFTER ago."""
    now = now or timezone.now()
    return purchase.status == FieldPurchaseStatus.SUBMITTED and purchase.created_at < now - FIELD_PURCHASE_LATE_AFTER


@dataclass(frozen=True)
class FieldPurchasesWaiting:
    waiting: int  # sent, not validated nor refused yet
    late: int  # of which sent more than FIELD_PURCHASE_LATE_AFTER ago


def field_purchases_waiting(organization: Organization, *, now: dt.datetime | None = None) -> FieldPurchasesWaiting:
    """How many purchases at the port wait for the office, and how many of them for too long (the dashboard alert)."""
    now = now or timezone.now()
    waiting = FieldPurchase.objects.for_organization(organization).filter(status=FieldPurchaseStatus.SUBMITTED)
    return FieldPurchasesWaiting(
        waiting=waiting.count(), late=waiting.filter(created_at__lt=now - FIELD_PURCHASE_LATE_AFTER).count()
    )


@dataclass(frozen=True)
class RevisionChange:
    """One value that differs between a revision and the one before: `line` is the line's or payment's position
    (from 0) for a field of a line (`lines.product`…) or of a payment (`payments.amount`…), else None."""

    field: str
    line: int | None
    before: str | None
    after: str | None


def _shown(value: Any) -> str | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        return str(value.get("name", ""))
    return str(value)


def _row_changes(prefix: str, before: list[dict[str, Any]], after: list[dict[str, Any]]) -> list[RevisionChange]:
    changes: list[RevisionChange] = []
    for index in range(max(len(before), len(after))):
        old = before[index] if index < len(before) else None
        new = after[index] if index < len(after) else None
        if old is None or new is None:
            # A row added or removed: named by its product (a line) or its amount (a payment).
            row = new if old is None else old
            assert row is not None
            label = _shown(row.get("product")) or _shown(row.get("proposed_product")) or _shown(row.get("amount"))
            changes.append(
                RevisionChange(
                    field=f"{prefix}.added" if old is None else f"{prefix}.removed",
                    line=index,
                    before=None if old is None else label,
                    after=label if old is None else None,
                )
            )
            continue
        for key in new:
            if old.get(key) != new[key]:
                changes.append(
                    RevisionChange(
                        field=f"{prefix}.{key}", line=index, before=_shown(old.get(key)), after=_shown(new[key])
                    )
                )
    return changes


def revision_changes(before: dict[str, Any] | None, after: dict[str, Any]) -> list[RevisionChange]:
    """What one revision changed against the one before (nothing for the first one, or when only a note was given)."""
    if before is None:
        return []
    changes: list[RevisionChange] = []
    for key, value in after.items():
        if key in ("lines", "payments", "total", "paid"):
            continue
        if key == "boxes":
            old_boxes = before.get("boxes", {})
            for box_type in sorted(set(old_boxes) | set(value)):
                if old_boxes.get(box_type) != value.get(box_type):
                    changes.append(
                        RevisionChange(
                            field=f"boxes.{box_type}",
                            line=None,
                            before=_shown(old_boxes.get(box_type)),
                            after=_shown(value.get(box_type)),
                        )
                    )
            continue
        if before.get(key) != value:
            changes.append(RevisionChange(field=key, line=None, before=_shown(before.get(key)), after=_shown(value)))
    changes += _row_changes("lines", before.get("lines", []), after.get("lines", []))
    changes += _row_changes("payments", before.get("payments", []), after.get("payments", []))
    return changes


# ---- A driver's own purchases (P3-T12b, D-158) ----

# The phone lists the purchases of this many days back.
MY_FIELD_PURCHASE_DAYS = 30


def field_purchases_of_buyer(organization: Organization, *, buyer_id: int) -> QuerySet[FieldPurchase]:
    """A driver's own purchases of the last MY_FIELD_PURCHASE_DAYS days, newest first."""
    since = timezone.localdate() - dt.timedelta(days=MY_FIELD_PURCHASE_DAYS)
    return field_purchases_of(organization, buyer_id=buyer_id).filter(bought_on__gte=since)


@dataclass(frozen=True)
class DayPurchases:
    """What a driver gave at the port over a span of time: cash (out of the purchase money, D-158) and the rest
    (cheques, traites…), over the purchases the office has not refused."""

    count: int
    total: Decimal  # what the purchases owe
    cash: Decimal
    other: Decimal


def purchases_paid_between(
    organization: Organization, *, buyer_id: int, start: dt.datetime, end: dt.datetime
) -> DayPurchases:
    """A driver's purchases made in [start, end) (by the phone's time, else when they were recorded) and the money
    given at the port for them. A refused purchase counts for nothing: no money was owed for it."""
    purchases = [
        purchase
        for purchase in field_purchases_of(organization, buyer_id=buyer_id)
        .exclude(status=FieldPurchaseStatus.REFUSED)
        # Recorded at or after the moment it was made: nothing recorded before `start` can fall in the span.
        .filter(created_at__gte=start)
        if start <= (purchase.made_at or purchase.created_at) < end
    ]
    payments = [payment for purchase in purchases for payment in purchase.payments.all()]
    return DayPurchases(
        count=len(purchases),
        total=sum((line.amount for purchase in purchases for line in purchase.lines.all()), ZERO),
        cash=sum((p.amount for p in payments if p.method == PaymentMethod.CASH), ZERO),
        other=sum((p.amount for p in payments if p.method != PaymentMethod.CASH), ZERO),
    )


# ---- Paying suppliers: what is owed, and the cheques to come (P3-T12c, D-159) ----

# "Due soon": within this many days from today.
DUE_SOON_DAYS = 7
# Cheques and traites shown: those to be cashed from this many days back (just cashed) on.
CHEQUES_SINCE_DAYS = 7


@dataclass(frozen=True)
class SupplierDebt:
    """What the company owes one supplier for goods, from its posted invoices still to pay (D-043)."""

    supplier_id: int
    name: str
    outstanding: Decimal  # still to pay on posted invoices
    overdue: Decimal  # of which past the due date
    due_soon: Decimal  # of which due from today to DUE_SOON_DAYS days
    advances: Decimal  # paid and not allocated yet: the supplier holds it
    open_invoices: int
    next_due: dt.date | None  # the earliest due date of what is still to pay


@dataclass(frozen=True)
class ChequeToCash:
    """A cheque or a traite given to a supplier with the day it may be cashed."""

    payment_id: int
    number: str
    supplier_id: int
    supplier_name: str
    method: str
    reference: str
    amount: Decimal
    paid_on: dt.date
    cash_on: dt.date


@dataclass(frozen=True)
class SupplierDebts:
    rows: list[SupplierDebt]
    total_outstanding: Decimal
    total_overdue: Decimal
    total_due_soon: Decimal
    total_advances: Decimal
    cheques: list[ChequeToCash]
    cheques_total: Decimal


def supplier_debts(organization: Organization, *, today: dt.date | None = None) -> SupplierDebts:
    """Every supplier the company owes, biggest first, with what is overdue and what falls due within a week; and
    the cheques and traites given with a cashing day, from a week back on, the soonest first. The trade payable only:
    a partner's capital and profit share are other balances (D-040)."""
    today = today or timezone.localdate()
    soon = today + dt.timedelta(days=DUE_SOON_DAYS)
    rows: dict[int, dict[str, Any]] = {}

    def row_of(supplier_id: int, name: str) -> dict[str, Any]:
        return rows.setdefault(
            supplier_id,
            {
                "supplier_id": supplier_id,
                "name": name,
                "outstanding": ZERO,
                "overdue": ZERO,
                "due_soon": ZERO,
                "advances": ZERO,
                "open_invoices": 0,
                "next_due": None,
            },
        )

    for invoice in invoices_of(organization, status="open"):
        left: Decimal = getattr(invoice, "outstanding")  # noqa: B009
        if left <= 0:
            continue
        row = row_of(invoice.supplier_id, invoice.supplier.name)
        row["outstanding"] += left
        row["open_invoices"] += 1
        if invoice.due_date < today:
            row["overdue"] += left
        elif invoice.due_date <= soon:
            row["due_soon"] += left
        if row["next_due"] is None or invoice.due_date < row["next_due"]:
            row["next_due"] = invoice.due_date
    for payment in payments_of(organization, unallocated=True):
        row = row_of(payment.supplier_id, payment.supplier.name)
        row["advances"] += getattr(payment, "unallocated_amount")  # noqa: B009
    debts = sorted((SupplierDebt(**row) for row in rows.values()), key=lambda r: (-r.outstanding, r.name))

    # Our cheques and traites still to be debited or just debited, from the treasury's effets (D-208).
    cheques = [
        ChequeToCash(
            payment_id=line.payment_id,
            number=line.payment.number,
            supplier_id=line.payment.supplier_id,
            supplier_name=line.payment.supplier.name,
            method=line.method,
            reference=line.instrument.number,
            amount=line.amount,
            paid_on=line.payment.paid_on,
            cash_on=line.instrument.due_on,
        )
        for line in SupplierPaymentLine.objects.for_organization(organization)
        .filter(
            instrument__isnull=False,
            instrument__due_on__gte=today - dt.timedelta(days=CHEQUES_SINCE_DAYS),
        )
        # A cancelled effet was never handed over (its règlement was voided); a rejected one is owed again.
        .exclude(instrument__status__in=("cancelled", "rejected"))
        .select_related("payment__supplier", "instrument")
        .order_by("instrument__due_on", "id")
        if line.instrument is not None
    ]
    return SupplierDebts(
        rows=debts,
        total_outstanding=sum((r.outstanding for r in debts), ZERO),
        total_overdue=sum((r.overdue for r in debts), ZERO),
        total_due_soon=sum((r.due_soon for r in debts), ZERO),
        total_advances=sum((r.advances for r in debts), ZERO),
        cheques=cheques,
        cheques_total=sum((c.amount for c in cheques if c.cash_on >= today), ZERO),
    )


# ---- Paid, planned or undefined, per supplier invoice (P3-T16a, D-192) ----

type SettlementState = Literal["settled", "overdue", "planned", "undefined"]
type PurchaseType = Literal["port", "office", "opening"]
# An invoice undefined for longer than this since it was posted is an alert (provisional, as D-176's window).
UNDEFINED_ALERT_AFTER = dt.timedelta(hours=24)


@dataclass(frozen=True)
class SettlementRow:
    invoice: SupplierInvoice
    purchase_type: PurchaseType
    total: Decimal
    paid: Decimal
    planned: Decimal
    undefined: Decimal
    state: SettlementState
    plan_lines: list[SupplierPaymentPlanLine]  # open and paid lines, soonest first
    age_hours: int  # since the invoice was posted


@dataclass(frozen=True)
class SettlementSummary:
    paid: Decimal
    planned: Decimal
    undefined: Decimal
    overdue: Decimal  # what is left to pay on the invoices in the "overdue" state
    counts: dict[str, int]  # invoices per state


@dataclass(frozen=True)
class Settlements:
    rows: list[SettlementRow]
    summary: SettlementSummary


def purchase_type_of(invoice: SupplierInvoice) -> PurchaseType:
    """Port when the invoice comes from a driver's purchase at the port, opening when typed as an opening
    balance, else an office receipt."""
    if invoice.is_opening:
        return "opening"
    return "port" if hasattr(invoice, "field_purchase") else "office"


def _settlement_row(invoice: SupplierInvoice, *, today: dt.date, now: dt.datetime) -> SettlementRow:
    paid: Decimal = getattr(invoice, "paid_amount")  # noqa: B009
    remaining = max(invoice.total - paid, ZERO)
    lines = [line for line in invoice.plan_lines.all() if line.status in (PlanLineStatus.OPEN, PlanLineStatus.PAID)]
    open_lines = [line for line in lines if line.status == PlanLineStatus.OPEN]
    # Payments recorded without naming a line can leave the open lines above the remainder: never plan more than owed.
    planned = min(sum((line.amount for line in open_lines), ZERO), remaining)
    undefined = remaining - planned
    if remaining <= 0:
        state: SettlementState = "settled"
    elif any(line.planned_on < today for line in open_lines) or (undefined > 0 and invoice.due_date < today):
        state = "overdue"
    elif undefined == 0:
        state = "planned"
    else:
        state = "undefined"
    posted_at = invoice.posted_at or invoice.created_at
    return SettlementRow(
        invoice=invoice,
        purchase_type=purchase_type_of(invoice),
        total=invoice.total,
        paid=min(paid, invoice.total),
        planned=planned,
        undefined=undefined,
        state=state,
        plan_lines=lines,
        age_hours=max(int((now - posted_at).total_seconds() // 3600), 0),
    )


def _settlement_rows(
    organization: Organization,
    *,
    supplier_id: int | None = None,
    purchase_type: PurchaseType | None = None,
    invoice_id: int | None = None,
    today: dt.date | None = None,
    now: dt.datetime | None = None,
) -> list[SettlementRow]:
    now = now or timezone.now()
    today = today or timezone.localtime(now).date()
    lines = SupplierPaymentPlanLine.objects.exclude(status=PlanLineStatus.CANCELLED).order_by("planned_on", "id")
    invoices = (
        invoices_of(organization, supplier_id=supplier_id)
        .exclude(status=SupplierInvoiceStatus.DRAFT)
        .select_related("field_purchase")
        .prefetch_related(Prefetch("plan_lines", queryset=lines))
    )
    if invoice_id is not None:
        invoices = invoices.filter(pk=invoice_id)
    rows = [_settlement_row(invoice, today=today, now=now) for invoice in invoices]
    if purchase_type is not None:
        rows = [row for row in rows if row.purchase_type == purchase_type]
    return rows


def supplier_settlements(
    organization: Organization,
    *,
    state: SettlementState | None = None,
    purchase_type: PurchaseType | None = None,
    supplier_id: int | None = None,
    today: dt.date | None = None,
    now: dt.datetime | None = None,
) -> Settlements:
    """Every posted supplier invoice with what is paid, planned and still undefined, and its state.

    The summary covers the invoices matching the type and supplier filters, whatever the state, so the tabs
    show their counts; `rows` are further kept to `state`. Newest invoice first, as `invoices_of` sorts them.
    """
    everything = _settlement_rows(
        organization, supplier_id=supplier_id, purchase_type=purchase_type, today=today, now=now
    )
    counts = {"settled": 0, "overdue": 0, "planned": 0, "undefined": 0}
    for row in everything:
        counts[row.state] += 1
    summary = SettlementSummary(
        paid=sum((row.paid for row in everything), ZERO),
        planned=sum((row.planned for row in everything), ZERO),
        undefined=sum((row.undefined for row in everything), ZERO),
        overdue=sum((row.total - row.paid for row in everything if row.state == "overdue"), ZERO),
        counts=counts,
    )
    rows = [row for row in everything if state is None or row.state == state]
    return Settlements(rows=rows, summary=summary)


def settlement_of(organization: Organization, invoice_id: int) -> SettlementRow:
    """One posted invoice's settlement. Raises SupplierInvoice.DoesNotExist for a draft or outside the organization."""
    rows = _settlement_rows(organization, invoice_id=invoice_id)
    if not rows:
        raise SupplierInvoice.DoesNotExist
    return rows[0]


def undefined_settlements_late(organization: Organization, *, now: dt.datetime | None = None) -> int:
    """Invoices with part of what is owed still undefined more than UNDEFINED_ALERT_AFTER after they were posted
    (the dashboard alert, whichever state the invoice shows)."""
    now = now or timezone.now()
    return sum(
        1
        for row in _settlement_rows(organization, now=now)
        if row.undefined > 0 and row.age_hours >= UNDEFINED_ALERT_AFTER.total_seconds() // 3600
    )


def plan_line_of(organization: Organization, line_id: int) -> SupplierPaymentPlanLine:
    """One plan line. Raises SupplierPaymentPlanLine.DoesNotExist outside the organization."""
    return SupplierPaymentPlanLine.objects.for_organization(organization).select_related("invoice").get(pk=line_id)
