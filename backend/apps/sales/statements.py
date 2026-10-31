"""A customer's statement for a period or up to a day (D-156): what they bought, line by line, what they paid,
and their account with the balance carried in and out.

It reads the account of D-062 (`receivables.customer_history`): a sale counts at what it owes now (its invoice's
VAT and stamp, credit notes and withholding taken off), what was paid on the spot and each payment as their own
lines. A day is the sale's local day and the payment's `received_on`. Public through `selectors.customer_statement`.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Prefetch
from django.utils import timezone

from apps.core.models import Organization

from . import receivables
from .models import CustomerPayment, CustomerPaymentMethod, SaleLine, SaleStatus
from .models import Sale as SaleModel

ZERO = Decimal("0.000")


@dataclass(frozen=True)
class StatementLine:
    product_reference: str
    product_name: str
    quantity: Decimal
    unit_price: Decimal
    discount_rate: Decimal
    amount: Decimal


@dataclass(frozen=True)
class StatementSale:
    sale_id: int
    number: str
    day: dt.date
    invoice_number: str
    is_opening: bool
    lines: tuple[StatementLine, ...]
    # The lines as charged (`Sale.total`), and what the account counts for it now (with the invoice's VAT...).
    total: Decimal
    owed: Decimal
    quantity: Decimal


@dataclass(frozen=True)
class StatementPayment:
    # "on_spot": paid at the sale; "payment": a customer payment recorded later.
    kind: str
    day: dt.date
    number: str
    method: str
    reference: str
    amount: Decimal
    voided: bool


@dataclass(frozen=True)
class StatementEntry:
    kind: str  # "sale", "on_spot", "payment"
    day: dt.date
    number: str
    method: str
    # Positive: the customer owes more (debit); negative: they paid (credit). A voided payment is 0.
    amount: Decimal
    voided: bool
    balance: Decimal


@dataclass(frozen=True)
class CustomerStatement:
    date_from: dt.date | None
    date_to: dt.date
    opening_balance: Decimal
    closing_balance: Decimal
    sales: tuple[StatementSale, ...]
    payments: tuple[StatementPayment, ...]
    entries: tuple[StatementEntry, ...]


def _method_label(method: str) -> str:
    # The règlement's methods hold every method of a sale paid on the spot.
    return str(CustomerPaymentMethod(method).label) if method in CustomerPaymentMethod.values else method


def _in_period(day: dt.date, date_from: dt.date | None, date_to: dt.date) -> bool:
    return (date_from is None or day >= date_from) and day <= date_to


def customer_statement(
    organization: Organization, customer_id: int, *, date_from: dt.date | None, date_to: dt.date
) -> CustomerStatement:
    """Everything of one customer from `date_from` (the beginning when None) to `date_to`, both included."""
    history = receivables.customer_history(organization, customer_id)
    opening = ZERO
    closing = ZERO
    entries: list[StatementEntry] = []
    owed_by_sale: dict[int, Decimal] = {}
    # The history is in day order with a running balance: the last row up to a day carries the balance then.
    for row in history:
        if row.day > date_to:
            break
        closing = row.balance
        if date_from is not None and row.day < date_from:
            opening = row.balance
            continue
        if row.kind == "sale":
            owed_by_sale[row.object_id] = row.amount
        entries.append(
            StatementEntry(
                kind=row.kind,
                day=row.day,
                number=row.number,
                method=_method_label(row.method) if row.method else "",
                amount=row.amount,
                voided=row.voided,
                balance=row.balance,
            )
        )

    lines = SaleLine.objects.select_related("product").order_by("id")
    sales = (
        SaleModel.objects.for_organization(organization)
        .filter(customer_id=customer_id, status=SaleStatus.CONFIRMED, pk__in=list(owed_by_sale))
        .prefetch_related(Prefetch("lines", queryset=lines))
        .order_by("sold_at", "id")
    )
    invoice_numbers = {
        row.sale_id: row.invoice_number
        for row in receivables.sale_receivables(organization, sale_ids=list(owed_by_sale))
    }
    statement_sales: list[StatementSale] = []
    for sale in sales:
        sale_lines = tuple(
            StatementLine(
                product_reference=line.product.reference,
                product_name=line.product.name,
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_rate=line.discount_rate,
                amount=line.amount,
            )
            for line in sale.lines.all()
        )
        statement_sales.append(
            StatementSale(
                sale_id=sale.pk,
                number=sale.number,
                day=timezone.localtime(sale.sold_at).date(),
                invoice_number=invoice_numbers.get(sale.pk, ""),
                is_opening=sale.is_opening,
                lines=sale_lines,
                total=sale.total,
                owed=owed_by_sale[sale.pk],
                quantity=sum((line.quantity for line in sale_lines), ZERO),
            )
        )

    payments: list[StatementPayment] = []
    paid_on_spot = SaleModel.objects.for_organization(organization).filter(
        customer_id=customer_id, confirmed_at__isnull=False, amount_paid__gt=0
    )
    for sale in paid_on_spot:
        day = timezone.localtime(sale.sold_at).date()
        if _in_period(day, date_from, date_to):
            payments.append(
                StatementPayment(
                    kind="on_spot",
                    day=day,
                    number=sale.number,
                    method=_method_label(sale.payment_method) if sale.payment_method else "",
                    reference=sale.payment_reference,
                    amount=sale.amount_paid,
                    voided=False,
                )
            )
    later = CustomerPayment.objects.for_organization(organization).filter(
        customer_id=customer_id, received_on__lte=date_to
    )
    if date_from is not None:
        later = later.filter(received_on__gte=date_from)
    for payment in later:
        payments.append(
            StatementPayment(
                kind="payment",
                day=payment.received_on,
                number=payment.number,
                method=_method_label(payment.method),
                reference=payment.reference,
                amount=payment.amount,
                voided=payment.voided_at is not None,
            )
        )
    payments.sort(key=lambda payment: (payment.day, payment.kind != "on_spot", payment.number))
    return CustomerStatement(
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        closing_balance=closing,
        sales=tuple(statement_sales),
        payments=tuple(payments),
        entries=tuple(entries),
    )
