"""What customers owe (P2-T06, D-062): the receivable of each sale, a customer's balance, ageing, history.

Everything is computed from the documents themselves, never stored twice: a confirmed sale owes its total,
or once invoiced what its issued invoices say (VAT and stamp included, credit notes taken off, withholding
kept by the customer taken off); what was paid on the spot and what payments were allocated to it is taken
off that. The balance of a customer is what their sales owe minus everything they paid (allocated or not), so
an unallocated payment, a sale cancelled after payment or a credit note beyond what was owed shows up as
credit (a negative balance). `Sale.amount_due` is only the denormalised outstanding of one sale, refreshed by
`services.refresh_sale_due` for lists.
"""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.core.models import Organization
from apps.core.money import money

from .models import (
    CreditNote,
    CustomerPayment,
    Invoice,
    InvoiceLine,
    InvoiceSale,
    InvoiceStatus,
    PaymentAllocation,
    Sale,
    SaleStatus,
    UnpaidEffet,
    UnpaidRelease,
    WithholdingCertificate,
)

ZERO = Decimal("0.000")

# Ageing buckets, in days since the document date (the invoice's, else the sale's): 0-30, 31-60, 60+. The
# last one starts at 61 days. Provisional (D-062): the client has not said whether they age from the invoice
# date or from the due date; `overdue` gives the due-date view.
BUCKETS: tuple[tuple[str, int, int | None], ...] = (("d0_30", 0, 30), ("d31_60", 31, 60), ("d60_plus", 61, None))


@dataclass(frozen=True)
class SaleReceivable:
    """One confirmed sale and what is left to collect on it."""

    sale_id: int
    customer_id: int
    number: str
    sold_at: dt.datetime
    # The invoice's number when it is invoiced (the live issued one).
    invoice_number: str
    invoice_id: int | None
    document_date: dt.date
    due_on: dt.date
    owed: Decimal
    on_spot: Decimal
    allocated: Decimal
    # What is still to collect, never below zero; `overpaid` is what was paid beyond what is owed.
    outstanding: Decimal
    overpaid: Decimal

    def age_days(self, today: dt.date) -> int:
        return max((today - self.document_date).days, 0)

    def is_overdue(self, today: dt.date) -> bool:
        return self.outstanding > 0 and self.due_on < today


def bucket_of(days: int) -> str:
    for key, low, high in BUCKETS:
        if days >= low and (high is None or days <= high):
            return key
    return BUCKETS[-1][0]


@dataclass
class CustomerBalance:
    """What one customer owes now, split by age, with the sales still open (oldest first)."""

    customer_id: int
    # owed − paid − payments: positive = the customer owes, negative = we hold their credit.
    balance: Decimal = ZERO
    # The sum of the open sales' outstanding amounts, and the credit held (payments not yet allocated...).
    open_total: Decimal = ZERO
    credit: Decimal = ZERO
    overdue: Decimal = ZERO
    buckets: dict[str, Decimal] = field(default_factory=lambda: {key: ZERO for key, _, _ in BUCKETS})
    open_sales: list[SaleReceivable] = field(default_factory=list)


def split(amount: Decimal, weights: list[Decimal]) -> list[Decimal]:
    """`amount` shared over `weights` (each part rounded once, the last takes the rest, so the parts add up).
    One weight gets all of it; weights that are all zero give everything to the last."""
    total = sum(weights, ZERO)
    if len(weights) == 1 or total == 0:
        return [*([ZERO] * (len(weights) - 1)), amount]
    parts = [money(amount * weight / total) for weight in weights[:-1]]
    return [*parts, amount - sum(parts, ZERO)]


def _sales_filter(organization: Organization, customer_id: int | None, sale_ids: list[int] | None) -> Q:
    query = Q(organization=organization, status=SaleStatus.CONFIRMED)
    if customer_id is not None:
        query &= Q(customer_id=customer_id)
    if sale_ids is not None:
        query &= Q(pk__in=sale_ids)
    return query


def sale_receivables(
    organization: Organization,
    *,
    customer_id: int | None = None,
    sale_ids: list[int] | None = None,
) -> list[SaleReceivable]:
    """The receivable of every confirmed sale (of a customer, or the given ones), oldest document first.

    Owed is the sale's total until it has an issued invoice; then it is, per issued or cancelled invoice,
    what the customer must pay (`net_to_pay`) less its credit notes, with the certificate's amount replacing
    the planned withholding of a live invoice. Cancelled sales are not here: what was paid on them is credit
    (see `customer_balances`).
    """
    sales = list(
        Sale.objects.filter(_sales_filter(organization, customer_id, sale_ids))
        .select_related("customer")
        .order_by("sold_at", "id")
    )
    if not sales:
        return []
    ids = [sale.pk for sale in sales]
    invoices_by_sale: dict[int, list[Invoice]] = defaultdict(list)
    invoice_ids = list(
        InvoiceSale.objects.filter(sale_id__in=ids, invoice__status__in=[InvoiceStatus.ISSUED, InvoiceStatus.CANCELLED])
        .values_list("invoice_id", flat=True)
        .distinct()
    )
    invoices = {invoice.pk: invoice for invoice in Invoice.objects.filter(pk__in=invoice_ids)}
    # An invoice may bill several BLs: what it asks is shared over them by what each BL holds on it.
    held: dict[int, dict[int, Decimal]] = defaultdict(dict)
    for row in (
        InvoiceLine.objects.filter(invoice_id__in=invoice_ids)
        .values("invoice_id", "sale_line__sale_id")
        .annotate(total=Sum("amount"))
    ):
        held[row["invoice_id"]][row["sale_line__sale_id"]] = row["total"]
    linked: dict[int, list[int]] = defaultdict(list)
    for invoice_id, sale_id in InvoiceSale.objects.filter(invoice_id__in=invoice_ids).values_list(
        "invoice_id", "sale_id"
    ):
        linked[invoice_id].append(sale_id)
    credited = {
        row["invoice_id"]: row["net"]
        for row in CreditNote.objects.filter(invoice_id__in=invoice_ids)
        .values("invoice_id")
        .annotate(net=Sum("net_amount"))
    }
    certified = {
        certificate.invoice_id: certificate.amount
        for certificate in WithholdingCertificate.objects.filter(invoice_id__in=invoice_ids, voided_at__isnull=True)
    }
    allocated = {
        row["sale_id"]: row["total"]
        for row in PaymentAllocation.objects.filter(sale_id__in=ids, payment__voided_at__isnull=True)
        .values("sale_id")
        .annotate(total=Sum("amount"))
    }
    # What an impayé took back from a règlement's allocations: those sales owe it again (D-217).
    for release in UnpaidRelease.objects.filter(sale_id__in=ids).values("sale_id").annotate(total=Sum("amount")):
        allocated[release["sale_id"]] = allocated.get(release["sale_id"], ZERO) - release["total"]
    shares: dict[tuple[int, int], Decimal] = {}
    for invoice in invoices.values():
        part = invoice.net_to_pay - credited.get(invoice.pk, ZERO)
        if invoice.status == InvoiceStatus.ISSUED and invoice.pk in certified:
            part += certified[invoice.pk] * -1 + invoice.withholding_amount
        sale_ids_of_invoice = sorted(linked[invoice.pk])
        parts = split(part, [held[invoice.pk].get(sale_id, ZERO) for sale_id in sale_ids_of_invoice])
        for sale_id, share in zip(sale_ids_of_invoice, parts, strict=True):
            shares[(invoice.pk, sale_id)] = share
            invoices_by_sale[sale_id].append(invoice)
    rows: list[SaleReceivable] = []
    for sale in sales:
        sale_invoices = sorted(invoices_by_sale.get(sale.pk, []), key=lambda invoice: invoice.pk)
        owed = ZERO
        live: Invoice | None = None
        if sale_invoices:
            for invoice in sale_invoices:
                if invoice.status == InvoiceStatus.ISSUED:
                    live = invoice
                owed += shares[(invoice.pk, sale.pk)]
        else:
            owed = sale.total
        paid = sale.amount_paid + allocated.get(sale.pk, ZERO)
        sold_day = timezone.localtime(sale.sold_at).date()
        if live is not None and live.issued_on is not None:
            document_date = live.issued_on
            due_on = live.due_on or live.issued_on
        else:
            document_date = sold_day
            due_on = sold_day + dt.timedelta(days=sale.customer.payment_terms_days)
        rows.append(
            SaleReceivable(
                sale_id=sale.pk,
                customer_id=sale.customer_id,
                number=sale.number,
                sold_at=sale.sold_at,
                invoice_number=live.number if live is not None else "",
                invoice_id=live.pk if live is not None else None,
                document_date=document_date,
                due_on=due_on,
                owed=owed,
                on_spot=sale.amount_paid,
                allocated=allocated.get(sale.pk, ZERO),
                outstanding=max(owed - paid, ZERO),
                overpaid=max(paid - owed, ZERO),
            )
        )
    rows.sort(key=lambda row: (row.document_date, row.sale_id))
    return rows


def customer_balances(
    organization: Organization,
    *,
    customer_id: int | None = None,
    today: dt.date | None = None,
) -> dict[int, CustomerBalance]:
    """The balance, credit and ageing of one customer, or of every customer with something to show.

    balance = what their confirmed sales owe − what they paid on the spot (including on sales cancelled
    since) − the payments they made (voided ones left out). The credit (what we hold for them) is the open
    amounts minus the balance: unallocated payments, money paid on a cancelled sale, credit notes beyond
    what was owed.
    """
    today = today or timezone.localdate()
    receivables = sale_receivables(organization, customer_id=customer_id)
    result: dict[int, CustomerBalance] = {}

    def entry(key: int) -> CustomerBalance:
        if key not in result:
            result[key] = CustomerBalance(customer_id=key)
        return result[key]

    for row in receivables:
        item = entry(row.customer_id)
        item.balance += row.owed
        if row.outstanding > 0:
            item.open_total += row.outstanding
            item.buckets[bucket_of(row.age_days(today))] += row.outstanding
            if row.is_overdue(today):
                item.overdue += row.outstanding
            item.open_sales.append(row)
    sales_filter = Q(organization=organization, confirmed_at__isnull=False)
    payments_filter = Q(organization=organization, voided_at__isnull=True)
    if customer_id is not None:
        sales_filter &= Q(customer_id=customer_id)
        payments_filter &= Q(customer_id=customer_id)
    for agg in Sale.objects.filter(sales_filter).values("customer_id").annotate(total=Sum("amount_paid")):
        entry(agg["customer_id"]).balance -= agg["total"]
    for agg in CustomerPayment.objects.filter(payments_filter).values("customer_id").annotate(total=Sum("amount")):
        entry(agg["customer_id"]).balance -= agg["total"]
    # A cheque or traite the bank refused: the customer owes it again (D-217).
    unpaid_filter = Q(organization=organization)
    if customer_id is not None:
        unpaid_filter &= Q(customer_id=customer_id)
    for agg in UnpaidEffet.objects.filter(unpaid_filter).values("customer_id").annotate(total=Sum("amount")):
        entry(agg["customer_id"]).balance += agg["total"]
    for item in result.values():
        item.credit = max(item.open_total - item.balance, ZERO)
    if customer_id is not None:
        entry(customer_id)
    return result


def customer_balance(organization: Organization, customer_id: int, *, today: dt.date | None = None) -> CustomerBalance:
    return customer_balances(organization, customer_id=customer_id, today=today)[customer_id]


@dataclass(frozen=True)
class HistoryEntry:
    """One line of a customer's account: a sale (what it owes now) or a payment, with the running balance."""

    kind: str  # "sale", "on_spot", "payment"
    day: dt.date
    at: dt.datetime
    number: str
    object_id: int
    # Positive raises what the customer owes, negative lowers it.
    amount: Decimal
    method: str = ""
    voided: bool = False
    balance: Decimal = ZERO


def customer_history(organization: Organization, customer_id: int) -> list[HistoryEntry]:
    """The customer's account, oldest first with a running balance that ends on `customer_balance().balance`.

    A confirmed sale appears at what it owes now (credit notes and withholding already taken off), the money
    paid on the spot as its own line, and each payment; voided payments are shown but do not count.
    """
    entries: list[HistoryEntry] = []
    for row in sale_receivables(organization, customer_id=customer_id):
        entries.append(
            HistoryEntry("sale", timezone.localtime(row.sold_at).date(), row.sold_at, row.number, row.sale_id, row.owed)
        )
    paid_sales = Sale.objects.filter(
        organization=organization, customer_id=customer_id, confirmed_at__isnull=False, amount_paid__gt=0
    )
    for sale in paid_sales:
        entries.append(
            HistoryEntry(
                "on_spot",
                timezone.localtime(sale.sold_at).date(),
                sale.sold_at,
                sale.number,
                sale.pk,
                -sale.amount_paid,
                method=sale.payment_method,
            )
        )
    for payment in CustomerPayment.objects.filter(organization=organization, customer_id=customer_id):
        when = payment.created_at
        entries.append(
            HistoryEntry(
                "payment",
                payment.received_on,
                when,
                payment.number,
                payment.pk,
                ZERO if payment.voided_at else -payment.amount,
                method=payment.method,
                voided=payment.voided_at is not None,
            )
        )
    for unpaid in UnpaidEffet.objects.filter(organization=organization, customer_id=customer_id).select_related(
        "line__instrument"
    ):
        entries.append(
            HistoryEntry(
                "unpaid",
                unpaid.unpaid_on,
                unpaid.created_at,
                unpaid.line.instrument.number if unpaid.line.instrument else "",
                unpaid.payment_id,
                unpaid.amount,
                method=unpaid.line.method,
            )
        )
    kind_order = {"sale": 0, "on_spot": 1, "payment": 2, "unpaid": 3}
    entries.sort(key=lambda entry: (entry.day, kind_order[entry.kind], entry.at, entry.object_id))
    running = ZERO
    result: list[HistoryEntry] = []
    for entry in entries:
        running += entry.amount
        result.append(
            HistoryEntry(
                entry.kind,
                entry.day,
                entry.at,
                entry.number,
                entry.object_id,
                entry.amount,
                entry.method,
                entry.voided,
                running,
            )
        )
    return result
