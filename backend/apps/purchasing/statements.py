"""A supplier's statement for a period or up to a day (D-156): the goods received, line by line, the invoices,
the payments, and the trade account with the balance carried in and out.

The account is the trade payable of D-043 (`selectors.supplier_balance`): posted invoices raise what the company
owes, payments lower it; a receipt is not owed until it is on an invoice, so receipts are listed but do not move
the balance. A partner's capital and profit share are other balances (D-040) and are not here. Public through
`selectors.supplier_statement`.
"""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal

from django.db.models import Prefetch

from apps.core.models import Organization

from .models import (
    GoodsReceipt,
    GoodsReceiptLine,
    PaymentMethod,
    RejectedEffet,
    SupplierBalanceWriteOff,
    SupplierInvoice,
    SupplierInvoiceReceipt,
    SupplierInvoiceStatus,
    SupplierPayment,
)

ZERO = Decimal("0.000")


@dataclass(frozen=True)
class StatementReceiptLine:
    product_reference: str
    product_name: str
    # What the supplier charges for (invoiced kg) and what entered stock (accepted kg).
    invoiced_quantity: Decimal
    accepted_quantity: Decimal
    unit_cost: Decimal
    amount: Decimal


@dataclass(frozen=True)
class StatementReceipt:
    receipt_id: int
    number: str
    day: dt.date
    supplier_reference: str
    # The posted invoice it is on; empty while not invoiced (or only on a draft).
    invoice_number: str
    lines: tuple[StatementReceiptLine, ...]
    quantity: Decimal
    total: Decimal


@dataclass(frozen=True)
class StatementPayment:
    day: dt.date
    number: str
    method: str
    reference: str
    amount: Decimal


@dataclass(frozen=True)
class StatementEntry:
    kind: str  # "invoice", "payment", "rejected", "written_off" (D-252)
    day: dt.date
    number: str
    reference: str
    # Positive: the company owes more (an invoice); negative: it paid.
    amount: Decimal
    balance: Decimal


@dataclass(frozen=True)
class SupplierStatement:
    date_from: dt.date | None
    date_to: dt.date
    opening_balance: Decimal
    closing_balance: Decimal
    receipts: tuple[StatementReceipt, ...]
    payments: tuple[StatementPayment, ...]
    entries: tuple[StatementEntry, ...]
    # Received up to `date_to` and on no posted invoice by then: not owed yet (D-043).
    uninvoiced_total: Decimal


def _method_label(method: str) -> str:
    return str(PaymentMethod(method).label) if method in PaymentMethod.values else method


def supplier_statement(
    organization: Organization, supplier_id: int, *, date_from: dt.date | None, date_to: dt.date
) -> SupplierStatement:
    """Everything of one supplier from `date_from` (the beginning when None) to `date_to`, both included."""
    invoices = (
        SupplierInvoice.objects.for_organization(organization)
        .filter(supplier_id=supplier_id, invoice_date__lte=date_to)
        .exclude(status=SupplierInvoiceStatus.DRAFT)
    )
    # A voided règlement never happened for the account (D-211).
    payments = SupplierPayment.objects.for_organization(organization).filter(
        supplier_id=supplier_id, paid_on__lte=date_to, voided_at__isnull=True
    )
    # (day, invoices before payments of the same day, id) gives the running balance its order.
    moves: list[tuple[dt.date, int, int, str, str, str, Decimal]] = [
        (invoice.invoice_date, 0, invoice.pk, "invoice", invoice.number, invoice.supplier_reference, invoice.total)
        for invoice in invoices
    ]
    moves += [
        (payment.paid_on, 1, payment.pk, "payment", payment.number, payment.reference, -payment.amount)
        for payment in payments
    ]
    rejected = (
        RejectedEffet.objects.for_organization(organization)
        .filter(supplier_id=supplier_id, rejected_on__lte=date_to)
        .select_related("line__instrument", "payment")
    )
    moves += [
        (
            row.rejected_on,
            2,
            row.pk,
            "rejected",
            row.payment.number,
            row.line.instrument.number if row.line.instrument else "",
            row.amount,
        )
        for row in rejected
    ]
    # What the balance write-offs gave up: no money moved, the balance falls by it (D-252).
    write_offs = SupplierBalanceWriteOff.objects.for_organization(organization).filter(
        supplier_id=supplier_id, written_on__lte=date_to
    )
    moves += [(row.written_on, 3, row.pk, "written_off", "", row.reason, -row.amount) for row in write_offs]
    moves.sort(key=lambda move: (move[0], move[1], move[2]))
    running = ZERO
    opening = ZERO
    entries: list[StatementEntry] = []
    for day, _order, _pk, kind, number, reference, amount in moves:
        running += amount
        if date_from is not None and day < date_from:
            opening = running
            continue
        entries.append(StatementEntry(kind, day, number, reference, amount, running))

    lines = GoodsReceiptLine.objects.select_related("product").order_by("id")
    receipts = (
        GoodsReceipt.objects.for_organization(organization)
        .filter(supplier_id=supplier_id, received_on__lte=date_to)
        .prefetch_related(Prefetch("lines", queryset=lines))
        .order_by("received_on", "id")
    )
    on_invoice = {
        link.receipt_id: link.invoice
        for link in SupplierInvoiceReceipt.objects.for_organization(organization)
        .filter(receipt__supplier_id=supplier_id)
        .exclude(invoice__status=SupplierInvoiceStatus.DRAFT)
        .select_related("invoice")
    }
    statement_receipts: list[StatementReceipt] = []
    uninvoiced = ZERO
    for receipt in receipts:
        receipt_lines = tuple(
            StatementReceiptLine(
                product_reference=line.product.reference,
                product_name=line.product.name,
                invoiced_quantity=line.invoiced_quantity,
                accepted_quantity=line.accepted_quantity,
                unit_cost=line.unit_cost,
                amount=line.invoiced_amount,
            )
            for line in receipt.lines.all()
        )
        total = sum((line.amount for line in receipt_lines), ZERO)
        invoice = on_invoice.get(receipt.pk)
        invoiced_by_then = invoice is not None and invoice.invoice_date <= date_to
        if not invoiced_by_then:
            uninvoiced += total
        if date_from is not None and receipt.received_on < date_from:
            continue
        statement_receipts.append(
            StatementReceipt(
                receipt_id=receipt.pk,
                number=receipt.number,
                day=receipt.received_on,
                supplier_reference=receipt.supplier_reference,
                invoice_number=invoice.number if invoice is not None and invoiced_by_then else "",
                lines=receipt_lines,
                quantity=sum((line.invoiced_quantity for line in receipt_lines), ZERO),
                total=total,
            )
        )

    in_period = payments if date_from is None else payments.filter(paid_on__gte=date_from)
    statement_payments = tuple(
        StatementPayment(
            day=payment.paid_on,
            number=payment.number,
            method=_method_label(payment.method),
            reference=payment.reference,
            amount=payment.amount,
        )
        for payment in in_period.order_by("paid_on", "id")
    )
    return SupplierStatement(
        date_from=date_from,
        date_to=date_to,
        opening_balance=opening,
        closing_balance=running,
        receipts=tuple(statement_receipts),
        payments=statement_payments,
        entries=tuple(entries),
        uninvoiced_total=uninvoiced,
    )
