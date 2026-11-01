"""Reusable read queries of sales documents."""

import datetime as dt
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, replace
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.db.models import (
    Case,
    CharField,
    Count,
    DecimalField,
    Exists,
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

from apps.core.documents import DocumentFilters, DocumentRow, DocumentType, PartyDocuments, Tone, document_key
from apps.core.models import Organization

from .models import (
    CreditNote,
    CreditNoteKind,
    CreditNoteLine,
    CreditNoteLineBatch,
    CustomerPayment,
    DeliveryStatus,
    FinanceSettings,
    Invoice,
    InvoiceLine,
    InvoiceSale,
    InvoiceStatus,
    InvoiceVatLine,
    Quote,
    QuoteLine,
    QuoteStatus,
    Sale,
    SaleLine,
    SaleLineBatch,
    SaleRevision,
    SaleStatus,
)

if TYPE_CHECKING:
    from .statements import CustomerStatement

# ---- Quotes (P2-T03, D-050) ----


def current_quote_status(today: dt.date) -> Case:
    """The status a quote shows on `today`: a sent quote whose validity date has passed is expired, even
    before the nightly `expire_quotes` writes it down."""
    return Case(
        When(status=QuoteStatus.SENT, valid_until__lt=today, then=Value(QuoteStatus.EXPIRED.value)),
        default=F("status"),
        output_field=CharField(),
    )


def quotes_of(
    organization: Organization,
    *,
    status: str | None = None,
    customer_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    search: str = "",
    today: dt.date | None = None,
) -> QuerySet[Quote]:
    """Quotes newest first, each with `current_status` (see `current_quote_status`), `line_count`, its
    customer, location and lines (product). `status` filters on the current status; `search` matches the
    number and the customer's name or reference."""
    today = today or timezone.localdate()
    lines = QuoteLine.objects.select_related("product").order_by("id")
    quotes = (
        Quote.objects.for_organization(organization)
        .select_related("customer", "location", "created_by", "sent_by", "answered_by")
        .prefetch_related(Prefetch("lines", queryset=lines))
        .prefetch_related(
            Prefetch(
                "sales",
                queryset=Sale.objects.exclude(status=SaleStatus.CANCELLED).prefetch_related("lines").order_by("-id"),
                to_attr="live_sales",
            )
        )
        .annotate(current_status=current_quote_status(today), line_count=Count("lines"))
        .order_by("-quoted_on", "-id")
    )
    if status:
        quotes = quotes.filter(current_status=status)
    if customer_id is not None:
        quotes = quotes.filter(customer_id=customer_id)
    if date_from is not None:
        quotes = quotes.filter(quoted_on__gte=date_from)
    if date_to is not None:
        quotes = quotes.filter(quoted_on__lte=date_to)
    if search := search.strip():
        quotes = quotes.filter(
            Q(number__icontains=search) | Q(customer__name__icontains=search) | Q(customer__reference__icontains=search)
        )
    return quotes


def quote_of(organization: Organization, quote_id: int) -> Quote:
    """One quote with its lines. Raises Quote.DoesNotExist outside the organization."""
    return quotes_of(organization).get(pk=quote_id)


def quotes_to_expire(organization: Organization, *, today: dt.date) -> QuerySet[Quote]:
    """Sent quotes whose validity date is before `today`: the customer never answered."""
    return Quote.objects.for_organization(organization).filter(status=QuoteStatus.SENT, valid_until__lt=today)


def live_sale_of(quote: Quote) -> "Sale | None":
    """The last sale (BL) made from an accepted quote, cancelled ones left out (P2-T04, D-051). A quote may
    be delivered in several (D-115): see `live_sales_of`."""
    sales = live_sales_of(quote)
    return sales[-1] if sales else None


def live_sales_of(quote: Quote) -> list[Sale]:
    """The sales (BL, drafts included) made from a quote, oldest first, cancelled ones left out (D-115)."""
    sales: list[Sale] | None = getattr(quote, "live_sales", None)  # prefetched by `quotes_of`
    if sales is None:
        sales = list(quote.sales.exclude(status=SaleStatus.CANCELLED).prefetch_related("lines"))
    return sorted(sales, key=lambda sale: sale.pk)


@dataclass(frozen=True)
class LineDelivery:
    """How far one quote line went: kg already on a BL, and kg still to deliver."""

    delivered: Decimal
    remaining: Decimal


def quote_delivery(quote: Quote) -> dict[int, LineDelivery]:
    """Per quote line id, the kg already on the quote's BL and the kg left to deliver (D-115).

    Every sale made from the quote counts, a draft too (its kilos are spoken for), except the cancelled
    ones. Kilos are matched by product, so a BL whose lines were retyped still counts; when a quote names
    a product twice, its first line fills first. Kilos beyond what was quoted are ignored.
    """
    taken: dict[int, Decimal] = {}
    for sale in live_sales_of(quote):
        for sale_line in sale.lines.all():
            taken[sale_line.product_id] = taken.get(sale_line.product_id, Decimal("0.000")) + sale_line.quantity
    delivery: dict[int, LineDelivery] = {}
    for line in sorted(quote.lines.all(), key=lambda item: item.pk):
        delivered = min(line.quantity, taken.get(line.product_id, Decimal("0.000")))
        taken[line.product_id] = taken.get(line.product_id, Decimal("0.000")) - delivered
        delivery[line.pk] = LineDelivery(delivered=delivered, remaining=line.quantity - delivered)
    return delivery


def quote_remaining(quote: Quote) -> Decimal:
    """Kg of the quote not on any BL yet; zero once it is delivered in full."""
    return sum((line.remaining for line in quote_delivery(quote).values()), Decimal("0.000"))


# ---- Sales (P2-T04, D-051) ----


def sale_by_client_uuid(organization: Organization, client_uuid: uuid.UUID | None) -> Sale | None:
    """The sale the phone sent under this `client_uuid`, if the server has it already (a retried send)."""
    if client_uuid is None:
        return None
    return Sale.objects.for_organization(organization).filter(client_uuid=client_uuid).first()


def sales_of(
    organization: Organization,
    *,
    status: str | None = None,
    customer_id: int | None = None,
    location_id: int | None = None,
    created_by_id: int | None = None,
    load_location_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    search: str = "",
    uninvoiced: bool = False,
    delivery_status: str | None = None,
) -> QuerySet[Sale]:
    """Sales newest first, each with `line_count`, its customer, place, quote and lines (product, batches).
    Days are those of `sold_at` in local time, both included; `search` matches the number and the
    customer's name or reference. `uninvoiced`: the BL still to invoice (confirmed, of a named customer,
    on no live invoice)."""
    lines = (
        SaleLine.objects.select_related("product")
        .prefetch_related(Prefetch("batches", queryset=SaleLineBatch.objects.select_related("batch").order_by("id")))
        .order_by("id")
    )
    sales = (
        Sale.objects.for_organization(organization)
        .select_related(
            "customer",
            "location",
            "quote",
            "transfer",
            "created_by",
            "confirmed_by",
            "cancelled_by",
            "credit_decided_by",
        )
        .prefetch_related(Prefetch("lines", queryset=lines), "box_lines")
        .prefetch_related(Prefetch("revisions", queryset=SaleRevision.objects.select_related("actor").order_by("id")))
        .prefetch_related(
            Prefetch(
                "invoices",
                queryset=Invoice.objects.exclude(status=InvoiceStatus.CANCELLED).order_by("-id"),
                to_attr="live_invoices",
            )
        )
        .annotate(line_count=Count("lines"))
        .order_by("-sold_at", "-id")
    )
    if status:
        sales = sales.filter(status=status)
    if delivery_status:
        # The BL of the truck loads only, by where their delivery stands (D-178).
        sales = sales.filter(delivery_status=delivery_status)
    if customer_id is not None:
        sales = sales.filter(customer_id=customer_id)
    if location_id is not None:
        sales = sales.filter(location_id=location_id)
    if created_by_id is not None:
        # A driver also sees the BL prepared for their truck's load (D-160), not only the sales they made.
        own = Q(created_by_id=created_by_id)
        if load_location_id is not None:
            own |= Q(transfer__isnull=False, location_id=load_location_id)
        sales = sales.filter(own)
    if date_from is not None:
        sales = sales.filter(sold_at__date__gte=date_from)
    if date_to is not None:
        sales = sales.filter(sold_at__date__lte=date_to)
    if uninvoiced:
        sales = sales.filter(status=SaleStatus.CONFIRMED, customer__is_walk_in=False, is_opening=False).exclude(
            Exists(InvoiceSale.objects.filter(sale=OuterRef("pk"), is_live=True))
        )
    if search := search.strip():
        sales = sales.filter(
            Q(number__icontains=search) | Q(customer__name__icontains=search) | Q(customer__reference__icontains=search)
        )
    return sales


def sale_of(organization: Organization, sale_id: int) -> Sale:
    """One sale with its lines and their batches. Raises Sale.DoesNotExist outside the organization."""
    return sales_of(organization).get(pk=sale_id)


def load_delivery_notes(organization: Organization, transfer_id: int) -> list[tuple[int, int]]:
    """(sale id, customer id) of the BL of a truck load (D-160), live ones only, ordered by customer name."""
    return list(
        sales_of(organization)
        .filter(transfer_id=transfer_id)
        .exclude(status=SaleStatus.CANCELLED)
        .order_by("customer__name", "pk")
        .values_list("pk", "customer_id")
    )


def returned_by_sale_batch(sale_line_batch_ids: Iterable[int]) -> dict[int, Decimal]:
    """Kilos credit notes already took back, per sale line batch id (customer returns, D-070)."""
    rows = (
        CreditNoteLineBatch.objects.filter(sale_line_batch_id__in=list(sale_line_batch_ids))
        .values("sale_line_batch_id")
        .annotate(quantity=Sum("quantity"))
        .order_by("sale_line_batch_id")
    )
    return {row["sale_line_batch_id"]: row["quantity"] for row in rows}


def _credit_sum(field: str) -> Coalesce:
    """What the credit notes took back of `field`, for the sale line batch row being read."""
    subquery = (
        CreditNoteLineBatch.objects.filter(sale_line_batch_id=OuterRef("pk"))
        .values("sale_line_batch_id")
        .annotate(total=Sum(field))
        .values("total")
    )
    return Coalesce(
        Subquery(subquery, output_field=DecimalField(max_digits=14, decimal_places=3)),
        Value(Decimal("0.000")),
        output_field=DecimalField(max_digits=14, decimal_places=3),
    )


@dataclass(frozen=True)
class NetSale:
    """What a `batch_sales` row still counts after the credit notes: kg, revenue and cost of goods."""

    quantity: Decimal
    revenue: Decimal
    cost: Decimal


def net_of(row: SaleLineBatch) -> NetSale:
    """A row of `batch_sales` net of what credit notes took back of it (D-070)."""
    annotated: Any = row  # the three annotations of `batch_sales`
    return NetSale(
        quantity=row.quantity - annotated.returned_quantity,
        revenue=row.revenue_amount - annotated.credited_revenue,
        cost=row.cost_amount - annotated.returned_cost,
    )


def batch_sales(organization: Organization, *, batch_id: int) -> QuerySet[SaleLineBatch]:
    """What one lot (batch) sold, line by line, oldest sale first: confirmed sales only (a cancelled sale's
    kilos came back). Each row has its line (price, product) and sale (number, moment, customer, place), and
    what credit notes took back of it: `returned_quantity`, `credited_revenue`, `returned_cost` (D-070)."""
    return (
        SaleLineBatch.objects.for_organization(organization)
        .filter(batch_id=batch_id, line__sale__status=SaleStatus.CONFIRMED)
        .annotate(
            returned_quantity=_credit_sum("quantity"),
            credited_revenue=_credit_sum("revenue_amount"),
            returned_cost=_credit_sum("cost_amount"),
        )
        .select_related("line__product", "line__sale__customer", "line__sale__location", "batch")
        .order_by("line__sale__sold_at", "line__sale_id", "id")
    )


@dataclass(frozen=True)
class BatchSalesTotal:
    """What one lot sold over its confirmed sales: kg, revenue without VAT and cost of the goods (COGS)."""

    batch_id: int
    quantity: Decimal
    revenue: Decimal
    cost: Decimal

    @property
    def margin(self) -> Decimal:
        return self.revenue - self.cost


def batch_sales_totals(
    organization: Organization, *, batch_ids: Iterable[int] | None = None
) -> dict[int, BatchSalesTotal]:
    """Kg sold, revenue and cost of goods per lot (batch id), over confirmed sales, net of what credit notes
    took back (D-070): the sales side of a lot's result (D-040; Phase 6 adds the lot's own costs). Lots that
    sold nothing are left out."""
    rows = SaleLineBatch.objects.for_organization(organization).filter(line__sale__status=SaleStatus.CONFIRMED)
    if batch_ids is not None:
        rows = rows.filter(batch_id__in=list(batch_ids))
    totals = rows.values("batch_id").annotate(
        quantity=Sum("quantity"), revenue=Sum("revenue_amount"), cost=Sum("cost_amount")
    )
    credits = CreditNoteLineBatch.objects.for_organization(organization).filter(
        sale_line_batch__line__sale__status=SaleStatus.CONFIRMED
    )
    if batch_ids is not None:
        credits = credits.filter(sale_line_batch__batch_id__in=list(batch_ids))
    credited = {
        row["sale_line_batch__batch_id"]: row
        for row in credits.values("sale_line_batch__batch_id").annotate(
            quantity=Sum("quantity"), revenue=Sum("revenue_amount"), cost=Sum("cost_amount")
        )
    }
    zero = Decimal("0.000")
    result = {}
    for row in totals.order_by("batch_id"):
        back = credited.get(row["batch_id"])
        result[row["batch_id"]] = BatchSalesTotal(
            batch_id=row["batch_id"],
            quantity=row["quantity"] - (back["quantity"] if back else zero),
            revenue=row["revenue"] - (back["revenue"] if back else zero),
            cost=row["cost"] - (back["cost"] if back else zero),
        )
    return result


# ---- Finance settings (P2-T05, D-056) ----


def finance_settings_history(organization: Organization) -> QuerySet[FinanceSettings]:
    """Every version of the finance settings, the latest start first (planned ones included)."""
    return (
        FinanceSettings.objects.for_organization(organization)
        .select_related("created_by")
        .order_by("-valid_from", "-id")
    )


def finance_settings_on(organization: Organization, day: dt.date | None = None) -> FinanceSettings | None:
    """The version in force on `day` (today by default): the latest one that started on or before it. None
    only before the first version (every organization gets one when created, D-056)."""
    day = day or timezone.localdate()
    return finance_settings_history(organization).filter(valid_from__lte=day).first()


# ---- Invoices and credit notes (P2-T05, D-057) ----


def live_invoice_of(sale: Sale) -> Invoice | None:
    """The sale's invoice, draft or issued, unless it was cancelled by a credit note."""
    invoices: list[Invoice] | None = getattr(sale, "live_invoices", None)  # prefetched by `sales_of`
    if invoices is None:
        invoices = list(sale.invoices.exclude(status=InvoiceStatus.CANCELLED).order_by("-id"))
    return invoices[0] if invoices else None


def invoices_of(
    organization: Organization,
    *,
    status: str | None = None,
    customer_id: int | None = None,
    sale_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    search: str = "",
) -> QuerySet[Invoice]:
    """Invoices, drafts first then the newest issued, each with its sale, customer, lines, VAT per rate and
    credit notes, and `credited_total` (what its credit notes gave back, net). Days are the issue dates, both
    included (a draft has none and is left out by a day filter); `search` matches the number, the sale's
    number and the customer's name or reference."""
    credit_lines = CreditNoteLine.objects.select_related("invoice_line").order_by("id")
    credit_notes = (
        CreditNote.objects.select_related("created_by")
        .prefetch_related(Prefetch("lines", queryset=credit_lines))
        .order_by("id")
    )
    invoices = (
        Invoice.objects.for_organization(organization)
        .select_related("organization", "customer", "settings_version", "created_by", "issued_by")
        .prefetch_related(Prefetch("sales", queryset=Sale.objects.order_by("sold_at", "id")))
        .prefetch_related(
            Prefetch("lines", queryset=InvoiceLine.objects.select_related("product", "sale_line__sale").order_by("id"))
        )
        .prefetch_related(Prefetch("vat_lines", queryset=InvoiceVatLine.objects.order_by("-rate")))
        .prefetch_related(Prefetch("credit_notes", queryset=credit_notes))
        .prefetch_related("certificates")
        .annotate(
            line_count=Count("lines", distinct=True),
            credited_total=Coalesce(
                Subquery(
                    CreditNote.objects.filter(invoice=OuterRef("pk"))
                    .values("invoice")
                    .annotate(total=Sum("net_amount"))
                    .values("total")
                ),
                Value(Decimal("0.000")),
                output_field=DecimalField(max_digits=14, decimal_places=3),
            ),
        )
        .order_by(F("issued_on").desc(nulls_first=True), "-id")
    )
    if status:
        invoices = invoices.filter(status=status)
    if customer_id is not None:
        invoices = invoices.filter(customer_id=customer_id)
    if sale_id is not None:
        invoices = invoices.filter(Exists(InvoiceSale.objects.filter(invoice=OuterRef("pk"), sale_id=sale_id)))
    if date_from is not None:
        invoices = invoices.filter(issued_on__gte=date_from)
    if date_to is not None:
        invoices = invoices.filter(issued_on__lte=date_to)
    if search := search.strip():
        invoices = invoices.filter(
            Q(number__icontains=search)
            | Exists(InvoiceSale.objects.filter(invoice=OuterRef("pk"), sale__number__icontains=search))
            | Q(customer__name__icontains=search)
            | Q(customer__reference__icontains=search)
        )
    return invoices


def invoice_of(organization: Organization, invoice_id: int) -> Invoice:
    """One invoice with everything it prints. Raises Invoice.DoesNotExist outside the organization."""
    return invoices_of(organization).get(pk=invoice_id)


@dataclass(frozen=True)
class CreditedLine:
    """What the credit notes already gave back on one invoice line."""

    quantity: Decimal
    amount_excl_tax: Decimal
    vat_amount: Decimal


def credited_by_line(invoice: Invoice) -> dict[int, CreditedLine]:
    """Kilos and amounts already given back per invoice line id, over the invoice's credit notes."""
    rows = (
        CreditNoteLine.objects.filter(credit_note__invoice=invoice)
        .values("invoice_line_id")
        .annotate(quantity=Sum("quantity"), excl=Sum("amount_excl_tax"), vat=Sum("vat_amount"))
        .order_by("invoice_line_id")
    )
    return {
        row["invoice_line_id"]: CreditedLine(
            quantity=row["quantity"], amount_excl_tax=row["excl"], vat_amount=row["vat"]
        )
        for row in rows
    }


def credit_notes_of(
    organization: Organization,
    *,
    customer_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    search: str = "",
) -> QuerySet[CreditNote]:
    """Credit notes, newest first, each with its invoice (and customer) and lines."""
    notes = (
        CreditNote.objects.for_organization(organization)
        .select_related("invoice", "invoice__customer", "created_by")
        .prefetch_related(Prefetch("lines", queryset=CreditNoteLine.objects.select_related("invoice_line")))
        .order_by("-issued_on", "-id")
    )
    if customer_id is not None:
        notes = notes.filter(invoice__customer_id=customer_id)
    if date_from is not None:
        notes = notes.filter(issued_on__gte=date_from)
    if date_to is not None:
        notes = notes.filter(issued_on__lte=date_to)
    if search := search.strip():
        notes = notes.filter(
            Q(number__icontains=search)
            | Q(invoice__number__icontains=search)
            | Q(invoice__customer__name__icontains=search)
        )
    return notes


# ---- Receivables for other apps (P2-T06, D-062) ----


def outstanding_by_sale(organization: Organization, sale_ids: list[int]) -> dict[int, Decimal]:
    """What customers still owe on the given confirmed sales, by sale id (only the sales with something left):
    after payments, credit notes and withholding. The "customers paid" check of lot closing reads it (D-068)."""
    from . import receivables  # receivables imports models only; kept local to avoid a cycle with selectors

    rows = receivables.sale_receivables(organization, sale_ids=sale_ids)
    return {row.sale_id: row.outstanding for row in rows if row.outstanding > 0}


# ---- Month figures (P6-T05, D-073) ----


@dataclass(frozen=True)
class MonthSales:
    """What a period sold, from the sale-line snapshots (never from purchases): revenue without VAT and the
    cost of the goods sold (COGS), each net of what credit notes took back in the period."""

    sales: int
    quantity: Decimal
    revenue: Decimal
    cogs: Decimal
    # What credit notes issued in the period took back (already taken off the figures above).
    credited_revenue: Decimal
    returned_cost: Decimal


def month_sales(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> MonthSales:
    """Confirmed sales made from `date_from` to `date_to` (local days, inclusive): revenue and COGS from their
    batch rows, less the revenue and cost credit notes issued in the same days gave back. A sale cancelled
    later no longer counts (its kilos came back)."""
    start = timezone.make_aware(dt.datetime.combine(date_from, dt.time.min))
    end = timezone.make_aware(dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min))
    zero = Decimal("0.000")
    sold = SaleLineBatch.objects.for_organization(organization).filter(
        line__sale__status=SaleStatus.CONFIRMED, line__sale__sold_at__gte=start, line__sale__sold_at__lt=end
    )
    totals = sold.aggregate(quantity=Sum("quantity"), revenue=Sum("revenue_amount"), cost=Sum("cost_amount"))
    count = (
        Sale.objects.for_organization(organization)
        .filter(status=SaleStatus.CONFIRMED, is_opening=False, sold_at__gte=start, sold_at__lt=end)
        .count()
    )
    credited = CreditNoteLineBatch.objects.for_organization(organization).filter(
        line__credit_note__issued_on__gte=date_from,
        line__credit_note__issued_on__lte=date_to,
        sale_line_batch__line__sale__status=SaleStatus.CONFIRMED,
    )
    back = credited.aggregate(quantity=Sum("quantity"), revenue=Sum("revenue_amount"), cost=Sum("cost_amount"))
    credited_revenue = back["revenue"] or zero
    returned_cost = back["cost"] or zero
    return MonthSales(
        sales=count,
        quantity=(totals["quantity"] or zero) - (back["quantity"] or zero),
        revenue=(totals["revenue"] or zero) - credited_revenue,
        cogs=(totals["cost"] or zero) - returned_cost,
        credited_revenue=credited_revenue,
        returned_cost=returned_cost,
    )


@dataclass(frozen=True)
class ReportRow:
    """One slice of what was sold (or given back by a credit note) for the commercial reports: the kilos,
    revenue without VAT and cost of one sale line batch. A credit note's row carries negative figures."""

    sale_id: int
    day: dt.date
    sold_on: dt.date
    customer_id: int
    customer_name: str
    product_id: int
    product_name: str
    location_id: int
    location_name: str
    quantity: Decimal
    revenue: Decimal
    cost: Decimal
    is_credit: bool


def report_rows(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> list[ReportRow]:
    """The rows `month_sales` adds up, one per sale line batch, so every report agrees with the closing
    (D-113): confirmed sales made from `date_from` to `date_to`, and, with negative figures, what credit notes
    issued in those days gave back. `day` is the day the row counts in (sale day, or credit note day);
    `sold_on` is always the sale's own day."""
    start = timezone.make_aware(dt.datetime.combine(date_from, dt.time.min))
    end = timezone.make_aware(dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min))
    fields = (
        "line__sale_id",
        "line__sale__sold_at",
        "line__sale__customer_id",
        "line__sale__customer__name",
        "line__product_id",
        "line__product__name",
        "line__sale__location_id",
        "line__sale__location__name",
        "quantity",
        "revenue_amount",
        "cost_amount",
    )
    rows: list[ReportRow] = []
    sold = (
        SaleLineBatch.objects.for_organization(organization)
        .filter(line__sale__status=SaleStatus.CONFIRMED, line__sale__sold_at__gte=start, line__sale__sold_at__lt=end)
        .order_by("id")
        .values_list(*fields)
    )
    for sale_id, sold_at, customer_id, customer, product_id, product, location_id, location, kg, revenue, cost in sold:
        local_day = timezone.localtime(sold_at).date()
        rows.append(
            ReportRow(
                sale_id,
                local_day,
                local_day,
                customer_id,
                customer,
                product_id,
                product,
                location_id,
                location,
                kg,
                revenue,
                cost,
                False,
            )
        )
    given_back = (
        CreditNoteLineBatch.objects.for_organization(organization)
        .filter(
            line__credit_note__issued_on__gte=date_from,
            line__credit_note__issued_on__lte=date_to,
            sale_line_batch__line__sale__status=SaleStatus.CONFIRMED,
        )
        .order_by("id")
        .values_list(
            "line__credit_note__issued_on",
            *(f"sale_line_batch__{name}" for name in fields[:8]),
            "quantity",
            "revenue_amount",
            "cost_amount",
        )
    )
    for (
        issued_on,
        sale_id,
        sold_at,
        customer_id,
        customer,
        product_id,
        product,
        location_id,
        location,
        kg,
        revenue,
        cost,
    ) in given_back:
        rows.append(
            ReportRow(
                sale_id,
                issued_on,
                timezone.localtime(sold_at).date(),
                customer_id,
                customer,
                product_id,
                product,
                location_id,
                location,
                -kg,
                -revenue,
                -cost,
                True,
            )
        )
    return rows


def draft_sales_count(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> int:
    """Sales still drafts, dated in the period: they have not left the stock nor counted anywhere."""
    start = timezone.make_aware(dt.datetime.combine(date_from, dt.time.min))
    end = timezone.make_aware(dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min))
    return (
        Sale.objects.for_organization(organization)
        .filter(status=SaleStatus.DRAFT, sold_at__gte=start, sold_at__lt=end)
        .count()
    )


# ---- The "Documents" page (P2-T11, D-102) ----

_QUOTE_TONES: dict[str, Tone] = {
    QuoteStatus.DRAFT: "draft",
    QuoteStatus.SENT: "waiting",
    QuoteStatus.ACCEPTED: "waiting",
    QuoteStatus.REFUSED: "cancelled",
    QuoteStatus.EXPIRED: "cancelled",
}
_SALE_TONES: dict[str, Tone] = {
    SaleStatus.DRAFT: "draft",
    SaleStatus.CONFIRMED: "done",
    SaleStatus.CANCELLED: "cancelled",
}
_DELIVERY_TONES: dict[str, Tone] = {
    DeliveryStatus.TO_DELIVER: "waiting",
    DeliveryStatus.DELIVERED: "done",
    DeliveryStatus.PARTIAL: "done",
    DeliveryStatus.CANCELLED: "cancelled",
}
_INVOICE_TONES: dict[str, Tone] = {
    InvoiceStatus.DRAFT: "draft",
    InvoiceStatus.ISSUED: "done",
    InvoiceStatus.CANCELLED: "cancelled",
}


def _days(queryset: QuerySet[Any], field: str, filters: DocumentFilters) -> QuerySet[Any]:
    if filters.date_from is not None:
        queryset = queryset.filter(**{f"{field}__gte": filters.date_from})
    if filters.date_to is not None:
        queryset = queryset.filter(**{f"{field}__lte": filters.date_to})
    return queryset


def _search(queryset: QuerySet[Any], customer: str, filters: DocumentFilters) -> QuerySet[Any]:
    if search := filters.search.strip():
        queryset = queryset.filter(Q(number__icontains=search) | Q(**{f"{customer}__name__icontains": search}))
    return queryset


def _wanted(kind: DocumentType, filters: DocumentFilters) -> bool:
    return not filters.types or kind in filters.types


def document_rows(organization: Organization, filters: DocumentFilters, *, may_write: bool) -> list[DocumentRow]:
    """Quotes (DV), BL (a sale, D-095), invoices (FA) and credit notes (AV) as rows of the "Documents" page.

    `may_write` is whether the person may change sales documents (owner or manager): it decides `actions`,
    which follow the same rules as the services so the page offers only what would succeed. The services
    still check everything: an action offered here can be refused if the document changed meanwhile.
    """
    today = timezone.localdate()
    rows: list[DocumentRow] = []

    if _wanted("DV", filters):
        quotes = (
            Quote.objects.for_organization(organization)
            .select_related("customer")
            .prefetch_related("lines")
            .prefetch_related(
                Prefetch(
                    "sales",
                    queryset=Sale.objects.exclude(status=SaleStatus.CANCELLED).prefetch_related("lines"),
                    to_attr="live_sales",
                )
            )
            .annotate(current_status=current_quote_status(today))
        )
        for quote in _search(_days(quotes, "quoted_on", filters), "customer", filters):
            status = QuoteStatus(quote.current_status)
            # Delivered in full once every kilo is on a BL; until then another BL can take the rest (D-115).
            delivered_in_full = status == QuoteStatus.ACCEPTED and quote_remaining(quote) == 0
            actions: list[str] = []
            if may_write:
                if status == QuoteStatus.DRAFT:
                    actions = ["edit", "send"]
                elif status == QuoteStatus.SENT:
                    actions = ["accept", "refuse"]
                elif status == QuoteStatus.ACCEPTED and quote.valid_until >= today and not delivered_in_full:
                    actions = ["to_sale"]
            rows.append(
                DocumentRow(
                    type="DV",
                    id=quote.pk,
                    number=quote.number,
                    partner_side="customer",
                    partner_id=quote.customer_id,
                    partner_name=quote.customer.name,
                    date=quote.quoted_on,
                    amount=quote.total,
                    status=status.value,
                    status_label=str(status.label),
                    # An accepted quote wholly on its BL has done its job.
                    tone="done" if delivered_in_full else _QUOTE_TONES[status],
                    actions=actions,
                    pdf="quote",
                )
            )

    if _wanted("BL", filters):
        sales = (
            Sale.objects.for_organization(organization)
            .select_related("customer")
            .annotate(
                live_invoices=Count("invoices", filter=~Q(invoices__status=InvoiceStatus.CANCELLED)),
                issued_invoices=Count("invoices", filter=Q(invoices__status=InvoiceStatus.ISSUED)),
            )
        )
        for sale in _search(_days(sales, "sold_at__date", filters), "customer", filters):
            sale_status = SaleStatus(sale.status)
            actions = []
            delivery = DeliveryStatus(sale.delivery_status) if sale.delivery_status else None
            if may_write:
                if delivery == DeliveryStatus.TO_DELIVER:
                    # The driver delivers it (D-178); the office marks it delivered from its page, after a question.
                    actions = ["edit", "cancel"]
                elif sale_status == SaleStatus.DRAFT:
                    actions = ["edit", "confirm", "cancel"]
                elif sale_status == SaleStatus.CONFIRMED:
                    actions = [] if sale.live_invoices else ["to_invoice"]
                    if not sale.issued_invoices:
                        actions.append("cancel")
            rows.append(
                DocumentRow(
                    type="BL",
                    id=sale.pk,
                    number=sale.number,
                    partner_side="customer",
                    partner_id=sale.customer_id,
                    partner_name=sale.customer.name,
                    date=timezone.localtime(sale.sold_at).date(),
                    amount=sale.total,
                    status=sale_status.value,
                    status_label=str(delivery.label) if delivery is not None else str(sale_status.label),
                    tone=_DELIVERY_TONES[delivery] if delivery is not None else _SALE_TONES[sale_status],
                    parents=[document_key("DV", sale.quote_id)] if sale.quote_id else [],
                    actions=actions,
                    # A BL exists once the sale was validated, even if it was cancelled afterwards; the BL of a load
                    # from the load on (D-178).
                    pdf="delivery_note" if sale.confirmed_at is not None or sale.issued_at is not None else "",
                )
            )

    if _wanted("FA", filters):
        invoices = (
            Invoice.objects.for_organization(organization)
            .select_related("customer")
            .prefetch_related(Prefetch("sale_links", queryset=InvoiceSale.objects.order_by("sale__sold_at", "sale_id")))
            .annotate(day=Coalesce("issued_on", "created_at__date"))
        )
        for invoice in _search(_days(invoices, "day", filters), "customer", filters):
            invoice_status = InvoiceStatus(invoice.status)
            actions = []
            if may_write:
                if invoice_status == InvoiceStatus.DRAFT:
                    actions = ["edit", "issue", "delete"]
                elif invoice_status == InvoiceStatus.ISSUED:
                    actions = ["credit_note"]
            rows.append(
                DocumentRow(
                    type="FA",
                    id=invoice.pk,
                    # A draft has no number yet (taken when issued): the page says "Brouillon".
                    number=invoice.number,
                    partner_side="customer",
                    partner_id=invoice.customer_id,
                    partner_name=invoice.customer.name,
                    date=invoice.day,
                    amount=invoice.net_to_pay,
                    status=invoice_status.value,
                    status_label=str(invoice_status.label),
                    tone=_INVOICE_TONES[invoice_status],
                    # One or several BL (D-101), oldest first.
                    parents=[document_key("BL", link.sale_id) for link in invoice.sale_links.all()],
                    actions=actions,
                    pdf="" if invoice_status == InvoiceStatus.DRAFT else "invoice",
                )
            )

    if _wanted("AV", filters):
        notes = CreditNote.objects.for_organization(organization).select_related("invoice__customer")
        for note in _search(_days(notes, "issued_on", filters), "invoice__customer", filters):
            rows.append(
                DocumentRow(
                    type="AV",
                    id=note.pk,
                    number=note.number,
                    partner_side="customer",
                    partner_id=note.invoice.customer_id,
                    partner_name=note.invoice.customer.name,
                    date=note.issued_on,
                    amount=note.net_amount,
                    # A credit note has no status: it is final when made.
                    status="issued",
                    status_label=str(CreditNoteKind(note.kind).label),
                    tone="done",
                    parents=[document_key("FA", note.invoice_id)],
                    pdf="credit_note",
                )
            )
    return rows


def load_customer_ids(organization: Organization, *, location_id: int, day: dt.date) -> list[int]:
    """The clients a truck was loaded for on a day (their BL made from a load of that day, D-160), delivered or not;
    a cancelled BL leaves its client out. Empty when the day's loads named no client."""
    return list(
        Sale.objects.for_organization(organization)
        .filter(location_id=location_id, transfer__isnull=False, transfer__transferred_on=day)
        .exclude(status=SaleStatus.CANCELLED)
        .order_by("customer_id")
        .values_list("customer_id", flat=True)
        .distinct()
    )


def recent_customer_ids(organization: Organization, *, user_id: int, limit: int = 8) -> list[int]:
    """The customers this person sold to most recently, most recent first (the walk-in customer included)."""
    seen: list[int] = []
    rows = (
        Sale.objects.for_organization(organization)
        .filter(created_by_id=user_id, status="confirmed")
        .order_by("-sold_at", "-id")
        .values_list("customer_id", flat=True)[:200]
    )
    for customer_id in rows:
        if customer_id not in seen:
            seen.append(customer_id)
        if len(seen) == limit:
            break
    return seen


def payments_received_by(organization: Organization, *, user_id: int, day: dt.date) -> list[CustomerPayment]:
    """The customer payments this person recorded for a day (voided ones left out), newest first."""
    return list(
        CustomerPayment.objects.for_organization(organization)
        .filter(created_by_id=user_id, received_on=day, voided_at__isnull=True)
        .select_related("customer")
        .order_by("-id")
    )


def owed_by_customer(organization: Organization) -> dict[int, Decimal]:
    """What each customer owes now (only those who owe something), from the receivables of D-062."""
    from . import receivables

    return {
        customer_id: balance.balance
        for customer_id, balance in receivables.customer_balances(organization).items()
        if balance.balance > 0
    }


# ---- The owner's dashboard (P7-T01, D-104) ----


@dataclass(frozen=True)
class OverdueCustomer:
    customer_id: int
    overdue: Decimal
    balance: Decimal


@dataclass(frozen=True)
class ReceivablesOverview:
    """What customers owe now (the customers who owe, as the ageing page counts it), the part past its due
    date, and the customers with something overdue, biggest first."""

    total: Decimal
    overdue: Decimal
    overdue_customers: tuple[OverdueCustomer, ...]


def receivables_overview(organization: Organization, *, today: dt.date | None = None) -> ReceivablesOverview:
    from . import receivables  # kept local to avoid a cycle with selectors (see outstanding_by_sale)

    zero = Decimal("0.000")
    balances = receivables.customer_balances(organization, today=today)
    owing = [value for value in balances.values() if value.balance > 0]
    late = sorted((value for value in owing if value.overdue > 0), key=lambda value: -value.overdue)
    return ReceivablesOverview(
        total=sum((value.balance for value in owing), zero),
        overdue=sum((value.overdue for value in owing), zero),
        overdue_customers=tuple(
            OverdueCustomer(customer_id=value.customer_id, overdue=value.overdue, balance=value.balance)
            for value in late
        ),
    )


def cash_collected(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> Decimal:
    """Money received from customers from `date_from` to `date_to` (local days, inclusive): what they paid on the
    spot at a confirmed sale plus the payments they made later (voided ones left out). It is cash, not profit."""
    zero = Decimal("0.000")
    start = timezone.make_aware(dt.datetime.combine(date_from, dt.time.min))
    end = timezone.make_aware(dt.datetime.combine(date_to + dt.timedelta(days=1), dt.time.min))
    on_the_spot = (
        Sale.objects.for_organization(organization)
        .filter(status=SaleStatus.CONFIRMED, sold_at__gte=start, sold_at__lt=end)
        .aggregate(total=Sum("amount_paid"))["total"]
    )
    later = (
        CustomerPayment.objects.for_organization(organization)
        .filter(voided_at__isnull=True, received_on__gte=date_from, received_on__lte=date_to)
        .aggregate(total=Sum("amount"))["total"]
    )
    return (on_the_spot or zero) + (later or zero)


def cash_in_by_day(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> dict[dt.date, Decimal]:
    """Money received per day from customers: what was paid on the spot at confirmed sales (by the day of the
    sale) plus the customer payments recorded since (by the day received, voided ones left out)."""
    from django.db.models.functions import TruncDate

    result: dict[dt.date, Decimal] = {}
    on_the_spot = (
        Sale.objects.for_organization(organization)
        .filter(confirmed_at__isnull=False, amount_paid__gt=0)
        .annotate(day=TruncDate("sold_at"))
        .filter(day__gte=date_from, day__lte=date_to)
        .values("day")
        .annotate(total=Sum("amount_paid"))
    )
    for spot in on_the_spot:
        result[spot["day"]] = result.get(spot["day"], Decimal("0.000")) + spot["total"]
    later = (
        CustomerPayment.objects.for_organization(organization)
        .filter(voided_at__isnull=True, received_on__gte=date_from, received_on__lte=date_to)
        .values("received_on")
        .annotate(total=Sum("amount"))
    )
    for row in later:
        result[row["received_on"]] = result.get(row["received_on"], Decimal("0.000")) + row["total"]
    return result


def receivable_balances(organization: Organization) -> dict[int, Any]:
    """Every customer's balance, credit and ageing (`receivables.CustomerBalance`), keyed by customer id."""
    from . import receivables

    return dict(receivables.customer_balances(organization))


def customer_statement(
    organization: Organization, customer_id: int, *, date_from: dt.date | None, date_to: dt.date
) -> "CustomerStatement":
    """One customer's sales (line by line), payments and account from `date_from` (the beginning when None) to
    `date_to` (`statements.CustomerStatement`, D-156)."""
    from . import statements

    return statements.customer_statement(organization, customer_id, date_from=date_from, date_to=date_to)


# ---- Customer documents for the règlement forms (D-211) ----


def customer_documents(organization: Organization) -> dict[int, PartyDocuments]:
    """Per customer with a BL or an invoice: its confirmed BL, its issued invoices and their net to pay (D-211)."""
    documents: dict[int, PartyDocuments] = {}
    deliveries = (
        Sale.objects.for_organization(organization)
        .filter(status=SaleStatus.CONFIRMED)
        .values("customer_id")
        .annotate(count=Count("id"))
        .order_by()
    )
    for row in deliveries:
        documents[row["customer_id"]] = PartyDocuments(party_id=row["customer_id"], deliveries=row["count"])
    invoices = (
        Invoice.objects.for_organization(organization)
        .filter(status=InvoiceStatus.ISSUED)
        .values("customer_id")
        .annotate(count=Count("id"), total=Sum("net_to_pay"))
        .order_by()
    )
    for row in invoices:
        current = documents.get(row["customer_id"], PartyDocuments(party_id=row["customer_id"]))
        documents[row["customer_id"]] = replace(current, invoices=row["count"], total=row["total"])
    return documents
