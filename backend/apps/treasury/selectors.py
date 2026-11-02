"""Read queries of the treasury: banks and effets (D-197); our accounts and their movements (D-219)."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from django.db.models import Count, DecimalField, F, OuterRef, Prefetch, Q, QuerySet, Subquery, Sum, Value
from django.db.models.functions import Coalesce

from apps.core.models import Organization

from .models import (
    AccountKind,
    AccountTransfer,
    Bank,
    BankStatementLine,
    CashCount,
    Deposit,
    Instrument,
    InstrumentDirection,
    InstrumentKind,
    InstrumentStatus,
    MovementKind,
    TreasuryAccount,
    TreasuryMovement,
)


def banks_of(organization: Organization, *, active_only: bool = False) -> QuerySet[Bank]:
    banks = Bank.objects.for_organization(organization)
    return banks.filter(is_active=True) if active_only else banks


def bank_of(organization: Organization, bank_id: int) -> Bank:
    """One bank of the organization. Raises Bank.DoesNotExist outside it."""
    return Bank.objects.for_organization(organization).get(pk=bank_id)


def instruments_of(
    organization: Organization,
    *,
    direction: str | None = None,
    kind: str | None = None,
    statuses: list[str] | None = None,
    customer_id: int | None = None,
    supplier_id: int | None = None,
    due_from: dt.date | None = None,
    due_to: dt.date | None = None,
    search: str = "",
    bank_id: int | None = None,
    deposit_id: int | None = None,
) -> QuerySet[Instrument]:
    """Effets, soonest due first, with their bank and party. `search` looks in the number, the drawer, the
    règlement number and the party's name."""
    rows = Instrument.objects.for_organization(organization).select_related("bank", "customer", "supplier", "deposit")
    if direction:
        rows = rows.filter(direction=direction)
    if kind:
        rows = rows.filter(kind=kind)
    if statuses:
        rows = rows.filter(status__in=statuses)
    if customer_id is not None:
        rows = rows.filter(customer_id=customer_id)
    if supplier_id is not None:
        rows = rows.filter(supplier_id=supplier_id)
    if bank_id is not None:
        rows = rows.filter(bank_id=bank_id)
    if deposit_id is not None:
        rows = rows.filter(deposit_id=deposit_id)
    if due_from is not None:
        rows = rows.filter(due_on__gte=due_from)
    if due_to is not None:
        rows = rows.filter(due_on__lte=due_to)
    search = search.strip()
    if search:
        rows = rows.filter(
            Q(number__icontains=search)
            | Q(drawer__icontains=search)
            | Q(source_number__icontains=search)
            | Q(customer__name__icontains=search)
            | Q(supplier__name__icontains=search)
        )
    return rows.order_by("due_on", "id")


@dataclass(frozen=True)
class InstrumentTotals:
    """The count and amount of filtered effets, by status, and those whose échéance has passed while not done."""

    count: int
    total: Decimal
    by_status: dict[str, dict[str, Any]]
    overdue_count: int
    overdue_total: Decimal


# Waiting for the bank: an échéance past while in one of these is late.
WAITING_STATUSES = (InstrumentStatus.PORTFOLIO, InstrumentStatus.DEPOSITED, InstrumentStatus.ISSUED)


def instrument_totals(rows: QuerySet[Instrument], *, today: dt.date) -> InstrumentTotals:
    """The totals of an `instruments_of` queryset (its filters applied)."""
    by_status = {
        row["status"]: {"count": row["count"], "total": row["total"]}
        for row in rows.order_by().values("status").annotate(count=Count("id"), total=Sum("amount"))
    }
    late = rows.filter(status__in=WAITING_STATUSES, due_on__lt=today).aggregate(count=Count("id"), total=Sum("amount"))
    return InstrumentTotals(
        count=sum(row["count"] for row in by_status.values()),
        total=sum((row["total"] for row in by_status.values()), Decimal("0.000")),
        by_status=by_status,
        overdue_count=late["count"] or 0,
        overdue_total=late["total"] or Decimal("0.000"),
    )


def deposits_of(organization: Organization) -> QuerySet[Deposit]:
    """Bordereaux, newest first, with their bank, effets, `effets_count` and `effets_total`."""
    effets = Instrument.objects.select_related("bank", "customer").order_by("due_on", "id")
    return (
        Deposit.objects.for_organization(organization)
        .select_related("bank", "account", "created_by")
        .prefetch_related(Prefetch("instruments", queryset=effets))
        .annotate(effets_count=Count("instruments"), effets_total=Sum("instruments__amount"))
        .order_by("-deposited_on", "-id")
    )


def deposit_of(organization: Organization, deposit_id: int) -> Deposit:
    """One bordereau. Raises Deposit.DoesNotExist outside the organization."""
    return deposits_of(organization).get(pk=deposit_id)


# The choices of an effet, for other apps' serializers (they may not import this app's models).
INSTRUMENT_KIND_CHOICES = InstrumentKind.choices
INSTRUMENT_STATUS_CHOICES = InstrumentStatus.choices
INSTRUMENT_DIRECTION_CHOICES = InstrumentDirection.choices


# ---- Accounts and movements (D-219) ----

ZERO = Decimal("0.000")
MONEY = DecimalField(max_digits=14, decimal_places=3)


def _counted(movements: QuerySet[TreasuryMovement]) -> QuerySet[TreasuryMovement]:
    """The movements an account's balance counts: those from its opening day on (all of them without one)."""
    return movements.filter(Q(account__opening_on__isnull=True) | Q(day__gte=F("account__opening_on")))


def accounts_of(
    organization: Organization, *, active_only: bool = False, on: dt.date | None = None
) -> QuerySet[TreasuryAccount]:
    """Our accounts in the list's order (Caisses, bank accounts, drivers' cash), each with its `balance` at the end
    of `on` (today's when None)."""
    movements = _counted(TreasuryMovement.objects.filter(account=OuterRef("pk")))
    if on is not None:
        movements = movements.filter(day__lte=on)
    total = movements.order_by().values("account").annotate(total=Sum("amount")).values("total")
    rows = (
        TreasuryAccount.objects.for_organization(organization)
        .select_related("bank", "driver")
        .annotate(balance=F("opening_balance") + Coalesce(Subquery(total, output_field=MONEY), Value(ZERO)))
    )
    return rows.filter(is_active=True) if active_only else rows


def account_of(organization: Organization, account_id: int) -> TreasuryAccount:
    """One account with its balance. Raises TreasuryAccount.DoesNotExist outside the organization."""
    return accounts_of(organization).get(pk=account_id)


def account_balance(account: TreasuryAccount, *, on: dt.date) -> Decimal:
    """What the account holds at the end of `on`."""
    total = _counted(TreasuryMovement.objects.filter(account=account, day__lte=on)).aggregate(total=Sum("amount"))
    return account.opening_balance + (total["total"] or ZERO)


@dataclass(frozen=True)
class MovementRow:
    movement: TreasuryMovement
    # The account's balance just after this movement.
    balance: Decimal


@dataclass(frozen=True)
class AccountStatement:
    """An account's movements over a period with the balance after each one."""

    account: TreasuryAccount
    date_from: dt.date | None
    date_to: dt.date | None
    # The balance at the start of `date_from` (the opening balance without one).
    opening: Decimal
    total_in: Decimal
    total_out: Decimal
    closing: Decimal
    rows: list[MovementRow]


def account_statement(
    account: TreasuryAccount,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    kind: str | None = None,
    search: str = "",
) -> AccountStatement:
    """The movements of `account` between the two days (inclusive), oldest first, each with the balance after it.
    `kind` and `search` (label, reference) narrow the rows shown and their totals; the balances stay the
    account's own."""
    counted = _counted(TreasuryMovement.objects.filter(account=account)).select_related("created_by")
    opening = account.opening_balance
    if date_from is not None:
        before = counted.filter(day__lt=date_from).aggregate(total=Sum("amount"))["total"]
        opening += before or ZERO
        counted = counted.filter(day__gte=date_from)
    if date_to is not None:
        counted = counted.filter(day__lte=date_to)
    search = search.strip().casefold()
    balance = opening
    rows: list[MovementRow] = []
    for movement in counted.order_by("day", "id"):
        balance += movement.amount
        if kind and movement.kind != kind:
            continue
        if search and search not in movement.label.casefold() and search not in movement.reference.casefold():
            continue
        rows.append(MovementRow(movement=movement, balance=balance))
    return AccountStatement(
        account=account,
        date_from=date_from,
        date_to=date_to,
        opening=opening,
        total_in=sum((row.movement.amount for row in rows if row.movement.amount > 0), ZERO),
        total_out=-sum((row.movement.amount for row in rows if row.movement.amount < 0), ZERO),
        closing=balance,
        rows=rows,
    )


def transfers_of(organization: Organization, *, account_id: int | None = None) -> QuerySet[AccountTransfer]:
    """Moves between our accounts, newest first; `account_id` keeps those in or out of one account."""
    rows = AccountTransfer.objects.for_organization(organization).select_related(
        "from_account", "to_account", "created_by", "voided_by"
    )
    if account_id is not None:
        rows = rows.filter(Q(from_account_id=account_id) | Q(to_account_id=account_id))
    return rows.order_by("-transferred_on", "-id")


def transfer_of(organization: Organization, transfer_id: int) -> AccountTransfer:
    """One transfer. Raises AccountTransfer.DoesNotExist outside the organization."""
    return transfers_of(organization).get(pk=transfer_id)


def counts_of(organization: Organization, *, account_id: int | None = None) -> QuerySet[CashCount]:
    """Arrêtés de caisse, newest first."""
    rows = CashCount.objects.for_organization(organization).select_related("account", "created_by")
    if account_id is not None:
        rows = rows.filter(account_id=account_id)
    return rows.order_by("-counted_on", "-id")


def movement_of_source(organization: Organization, *, source: str, source_id: int) -> TreasuryMovement | None:
    """The movement a record of another app wrote (D-234: a salary payment), its account included. None when it
    wrote none (records made before the accounts) or when it was undone."""
    return (
        TreasuryMovement.objects.for_organization(organization)
        .select_related("account")
        .filter(source=source, source_id=source_id)
        .exclude(role__startswith="void")
        .first()
    )


# The choices of an account and a movement, for other apps' serializers.
ACCOUNT_KIND_CHOICES = AccountKind.choices
MOVEMENT_KIND_CHOICES = MovementKind.choices


def movements_of(organization: Organization, *, source: str, source_ids: list[int]) -> QuerySet[TreasuryMovement]:
    """The movements the given records of one source wrote (a règlement's lines, a sale, an expense...), in day order:
    each one shows the account it went through. Reversals (`role` "void") come too, so a voided money shows both."""
    return (
        TreasuryMovement.objects.filter(organization=organization, source=source, source_id__in=source_ids)
        .select_related("account")
        .order_by("day", "id")
    )


def statement_lines_of(
    organization: Organization,
    account: TreasuryAccount,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
) -> QuerySet[BankStatementLine]:
    """The imported lines of a bank account between two days (inclusive), oldest first."""
    lines = BankStatementLine.objects.filter(organization=organization, account=account).select_related(
        "customer", "supplier"
    )
    if date_from is not None:
        lines = lines.filter(day__gte=date_from)
    if date_to is not None:
        lines = lines.filter(day__lte=date_to)
    return lines.order_by("day", "id")


def statement_line_of(organization: Organization, line_id: int) -> BankStatementLine:
    """One imported line. Raises BankStatementLine.DoesNotExist outside the organization."""
    return BankStatementLine.objects.select_related("customer", "supplier", "account").get(
        organization=organization, pk=line_id
    )


# Our cheques are watched from the day before they fall due, our traites from 15 days before (D-254).
ISSUED_CHEQUE_WARNING_DAYS = 1
ISSUED_BILL_WARNING_DAYS = 15
DUE_ALERTS_LIMIT = 200


def due_alerts(organization: Organization, *, today: dt.date) -> QuerySet[Instrument]:
    """The effets that need someone today, soonest due first: a cheque or traite we received and still hold or have
    at the bank (due today or before: cash it, or chase the bank); a cheque of ours from the day before it falls due
    and a traite of ours from 15 days before, until the bank debits it."""
    received = Q(
        direction=InstrumentDirection.RECEIVED,
        status__in=(InstrumentStatus.PORTFOLIO, InstrumentStatus.DEPOSITED),
        due_on__lte=today,
    )
    our_cheques = Q(
        direction=InstrumentDirection.ISSUED,
        status=InstrumentStatus.ISSUED,
        kind=InstrumentKind.CHEQUE,
        due_on__lte=today + dt.timedelta(days=ISSUED_CHEQUE_WARNING_DAYS),
    )
    our_bills = Q(
        direction=InstrumentDirection.ISSUED,
        status=InstrumentStatus.ISSUED,
        kind=InstrumentKind.BILL,
        due_on__lte=today + dt.timedelta(days=ISSUED_BILL_WARNING_DAYS),
    )
    return (
        Instrument.objects.filter(organization=organization)
        .filter(received | our_cheques | our_bills)
        .select_related("bank", "customer", "supplier", "deposit")
        .order_by("due_on", "id")
    )
