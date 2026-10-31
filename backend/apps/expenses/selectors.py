"""Reusable read queries of expenses, and the costs they put on each lot (D-041, D-053)."""

import datetime as dt
from collections import defaultdict
from dataclasses import dataclass
from decimal import Decimal
from typing import Literal

from django.db.models import Count, Q, QuerySet, Sum
from django.utils import timezone

from apps.core.models import Organization
from apps.fleet import selectors as fleet
from apps.inventory import selectors as inventory

from . import cost_selectors
from .allocation import LoadedLot, TruckDayExpense, allocate_truck_day_costs
from .models import DayLabourEntry, DayLabourer, Expense, ExpenseCategory, ExpenseStatus

# What other apps read of the cold-room cost and the general costs (ARCHITECTURE §3: through `selectors`).
cold_rooms = cost_selectors.cold_rooms
room_weights = cost_selectors.room_weights
cold_room_month = cost_selectors.cold_room_month
electricity_bills_of = cost_selectors.bills_of
recurring_costs_of = cost_selectors.recurring_costs_of
general_periods_of = cost_selectors.general_periods_of

type CategoryStatus = Literal["active", "archived", "all"]

ZERO = Decimal("0.000")
_OPEN = (ExpenseStatus.DRAFT, ExpenseStatus.PENDING)


# ---- Categories ----


def categories_of(organization: Organization, *, status: CategoryStatus = "active") -> QuerySet[ExpenseCategory]:
    """Expense categories: the default ones in the brief's order, then the owner's by name."""
    categories = ExpenseCategory.objects.for_organization(organization).order_by("position", "name", "id")
    if status == "active":
        categories = categories.filter(is_active=True)
    elif status == "archived":
        categories = categories.filter(is_active=False)
    return categories


def category_of(organization: Organization, category_id: int) -> ExpenseCategory:
    """One category. Raises ExpenseCategory.DoesNotExist outside the organization."""
    return ExpenseCategory.objects.for_organization(organization).get(pk=category_id)


def category_by_code(organization: Organization, code: str) -> ExpenseCategory:
    """A default category by its code ("day_labour"...). Raises ExpenseCategory.DoesNotExist when missing."""
    return ExpenseCategory.objects.for_organization(organization).get(code=code)


# ---- Expenses ----


def expenses_of(
    organization: Organization,
    *,
    status: str | None = None,
    category_id: int | None = None,
    batch_id: int | None = None,
    truck_id: int | None = None,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    search: str = "",
) -> QuerySet[Expense]:
    """Expenses newest day first, with category, lot, truck and who typed and decided them. `search`
    matches the number, the description, the payee and the lot number."""
    expenses = (
        Expense.objects.for_organization(organization)
        .select_related(
            "category", "batch__product", "truck__location", "entered_by", "decided_by", "day_labour__labourer"
        )
        .order_by("-spent_on", "-id")
    )
    if status:
        expenses = expenses.filter(status=status)
    if category_id is not None:
        expenses = expenses.filter(category_id=category_id)
    if batch_id is not None:
        expenses = expenses.filter(batch_id=batch_id)
    if truck_id is not None:
        expenses = expenses.filter(truck_id=truck_id)
    if date_from is not None:
        expenses = expenses.filter(spent_on__gte=date_from)
    if date_to is not None:
        expenses = expenses.filter(spent_on__lte=date_to)
    if search := search.strip():
        expenses = expenses.filter(
            Q(number__icontains=search)
            | Q(description__icontains=search)
            | Q(payee__icontains=search)
            | Q(batch__number__icontains=search)
        )
    return expenses


def expense_of(organization: Organization, expense_id: int) -> Expense:
    """One expense. Raises Expense.DoesNotExist outside the organization."""
    return expenses_of(organization).get(pk=expense_id)


@dataclass(frozen=True)
class ExpenseTotals:
    """How many expenses a filter keeps and what they add up to, per status."""

    count: int
    approved: Decimal
    waiting: Decimal


def expense_totals(expenses: QuerySet[Expense]) -> ExpenseTotals:
    """Totals of a list of expenses: approved, and still waiting (drafts and pending). Refused ones count
    in neither."""
    sums = expenses.order_by().aggregate(
        count=Count("id"),
        approved=Sum("amount", filter=Q(status=ExpenseStatus.APPROVED)),
        waiting=Sum("amount", filter=Q(status__in=[ExpenseStatus.DRAFT, ExpenseStatus.PENDING])),
    )
    return ExpenseTotals(count=sums["count"], approved=sums["approved"] or ZERO, waiting=sums["waiting"] or ZERO)


# ---- Truck costs of the day, split over the lots on board (D-041, Q24 provisional) ----


@dataclass(frozen=True)
class TruckDayShare:
    """The part of one truck-day expense charged to one lot."""

    expense_id: int
    batch_id: int
    batch_number: str
    product_name: str
    # The lot's kg loaded on the truck that day, and the day's total kg loaded.
    quantity: Decimal
    day_quantity: Decimal
    amount: Decimal


def _truck_day_expenses(organization: Organization, *, truck_ids: list[int], days: list[dt.date]) -> list[Expense]:
    return list(
        Expense.objects.for_organization(organization)
        .filter(truck_id__in=truck_ids, spent_on__in=days)
        .exclude(status=ExpenseStatus.REJECTED)
        .select_related("category", "truck__location")
        .order_by("spent_on", "id")
    )


def truck_day_shares(organization: Organization, *, expenses: list[Expense]) -> dict[int, list[TruckDayShare]]:
    """For each expense tagged to a truck, its shares over the lots loaded on that truck that day (by
    expense id, shares by lot number). An expense of a day with no lot loaded gets no share: it stays a
    general cost. Drafts and waiting expenses are split too (a preview); only approved ones count."""
    per_day: dict[tuple[int, dt.date], list[Expense]] = defaultdict(list)
    for expense in expenses:
        if expense.truck is not None:
            per_day[(expense.truck.location_id, expense.spent_on)].append(expense)
    shares: dict[int, list[TruckDayShare]] = defaultdict(list)
    for (location_id, day), day_expenses in per_day.items():
        loads = inventory.batches_loaded(organization, location_id=location_id, day=day)
        by_batch = {load.batch_id: load for load in loads}
        day_quantity = sum((load.quantity for load in loads), ZERO)
        split = allocate_truck_day_costs(
            [TruckDayExpense(expense_id=expense.pk, amount=expense.amount) for expense in day_expenses],
            [LoadedLot(batch_id=load.batch_id, quantity=load.quantity) for load in loads],
        )
        for share in split:
            load = by_batch[share.batch_id]
            shares[share.expense_id].append(
                TruckDayShare(
                    expense_id=share.expense_id,
                    batch_id=share.batch_id,
                    batch_number=load.batch_number,
                    product_name=load.product_name,
                    quantity=share.quantity,
                    day_quantity=day_quantity,
                    amount=share.amount,
                )
            )
    for lines in shares.values():
        lines.sort(key=lambda share: (share.batch_number, share.batch_id))
    return dict(shares)


# ---- Costs of a lot (read by the lot result, Phase 6) ----

type LotCostKind = Literal["lot", "truck_day", "cold_room", "cold_room_adjustment", "general"]


@dataclass(frozen=True)
class LotCostLine:
    """One cost charged to a lot: an expense typed on it, or its share of a truck's day costs."""

    kind: LotCostKind
    # None for a cold-room estimate made before the month's bill exists.
    expense_id: int | None
    expense_number: str
    status: str
    spent_on: dt.date
    category_id: int | None
    category_code: str
    category_name: str
    description: str
    # What this lot carries, and the whole expense (equal for a cost typed on the lot).
    amount: Decimal
    expense_amount: Decimal
    # Truck costs of the day: the truck, the lot's kg loaded that day and the day's total kg.
    truck_name: str = ""
    quantity: Decimal | None = None
    day_quantity: Decimal | None = None
    # Cold room and general costs: the room, the month charged, the kg-days (in `quantity`), and whether the
    # amount is still an estimate (no bill for that month yet, or the estimate line that a later
    # `cold_room_adjustment` line corrects).
    location_name: str = ""
    month: dt.date | None = None
    estimated: bool = False


def _label(expense: Expense) -> str:
    return expense.description or expense.payee


def lot_cost_lines(organization: Organization, *, batch_id: int, approved_only: bool = True) -> list[LotCostLine]:
    """The costs charged to one lot, by day: the expenses typed on it (fuel, transport, day labour...) and
    its share of the truck costs of each day it was loaded on a truck (by kg loaded, D-041).

    Only approved expenses count; `approved_only=False` adds drafts and waiting ones (a preview for the
    screens, each line says its status). Refused expenses never appear. The cold room (P5-T02, D-058) and the
    general costs (P5-T05, D-059) are worked out from the stock ledger up to today: kinds `cold_room`
    (estimated until the month's bill is approved), `cold_room_adjustment` (real minus estimate, dated when
    the bill was typed: a closed lot is never reopened, D-041) and `general`. Salaries are `hr`'s.
    """
    statuses = [ExpenseStatus.APPROVED] if approved_only else [ExpenseStatus.APPROVED, *_OPEN]
    lines: list[LotCostLine] = [
        LotCostLine(
            kind="lot",
            expense_id=expense.pk,
            expense_number=expense.number,
            status=expense.status,
            spent_on=expense.spent_on,
            category_id=expense.category_id,
            category_code=expense.category.code,
            category_name=expense.category.name,
            description=_label(expense),
            amount=expense.amount,
            expense_amount=expense.amount,
        )
        for expense in Expense.objects.for_organization(organization)
        .filter(batch_id=batch_id, status__in=statuses)
        .select_related("category")
    ]
    truck_days = inventory.truck_days_of_batch(organization, batch_id=batch_id)
    if truck_days:
        trucks = {
            truck.location_id: truck.pk
            for truck in fleet.trucks_of(organization, status="all").filter(
                location_id__in={location_id for location_id, _day in truck_days}
            )
        }
        wanted = {(trucks[location_id], day) for location_id, day in truck_days if location_id in trucks}
        day_expenses = [
            expense
            for expense in _truck_day_expenses(
                organization,
                truck_ids=sorted({truck_id for truck_id, _day in wanted}),
                days=sorted({day for _truck, day in wanted}),
            )
            if (expense.truck_id, expense.spent_on) in wanted and expense.status in statuses
        ]
        shares = truck_day_shares(organization, expenses=day_expenses)
        for expense in day_expenses:
            for share in shares.get(expense.pk, []):
                if share.batch_id != batch_id:
                    continue
                assert expense.truck is not None  # only truck expenses have shares
                lines.append(
                    LotCostLine(
                        kind="truck_day",
                        expense_id=expense.pk,
                        expense_number=expense.number,
                        status=expense.status,
                        spent_on=expense.spent_on,
                        category_id=expense.category_id,
                        category_code=expense.category.code,
                        category_name=expense.category.name,
                        description=_label(expense),
                        amount=share.amount,
                        expense_amount=expense.amount,
                        truck_name=expense.truck.location.name,
                        quantity=share.quantity,
                        day_quantity=share.day_quantity,
                    )
                )
    lines.extend(_computed_lines(organization, batch_id=batch_id))
    return sorted(lines, key=lambda line: (line.spent_on, line.expense_id or 0, line.kind))


def _computed_lines(organization: Organization, *, batch_id: int) -> list[LotCostLine]:
    """The cold-room and general-cost lines of a lot, worked out from the ledger."""
    today = timezone.localdate()
    cold_storage = category_by_code_or_none(organization, "cold_storage")
    computed = [
        *cost_selectors.cold_room_lines(organization, batch_id=batch_id, today=today),
        *cost_selectors.general_lines(organization, batch_id=batch_id, today=today),
    ]
    lines: list[LotCostLine] = []
    for line in computed:
        expense = line.expense
        category = expense.category if expense is not None else cold_storage
        lines.append(
            LotCostLine(
                kind=line.kind,  # type: ignore[arg-type]
                expense_id=expense.pk if expense is not None else None,
                expense_number=expense.number if expense is not None else "",
                status=ExpenseStatus.APPROVED,
                spent_on=line.spent_on,
                category_id=category.pk if category is not None else None,
                category_code=category.code if category is not None else "",
                category_name=category.name if category is not None else "",
                description=line.description,
                amount=line.amount,
                expense_amount=line.expense_amount,
                quantity=line.quantity,
                location_name=line.location_name,
                month=line.month,
                estimated=line.estimated,
            )
        )
    return lines


def category_by_code_or_none(organization: Organization, code: str) -> ExpenseCategory | None:
    return ExpenseCategory.objects.for_organization(organization).filter(code=code).first()


def lot_cost_total(lines: list[LotCostLine]) -> Decimal:
    """What the approved lines add up to: the lot's costs so far."""
    return sum((line.amount for line in lines if line.status == ExpenseStatus.APPROVED), ZERO)


# ---- Day labour (P5-T03, D-054) ----

type LabourerStatus = Literal["active", "archived", "all"]


def labourers_of(organization: Organization, *, status: LabourerStatus = "active") -> QuerySet[DayLabourer]:
    """Day labourers by name."""
    labourers = DayLabourer.objects.for_organization(organization).order_by("name", "id")
    if status == "active":
        labourers = labourers.filter(is_active=True)
    elif status == "archived":
        labourers = labourers.filter(is_active=False)
    return labourers


def labourer_of(organization: Organization, labourer_id: int) -> DayLabourer:
    """One day labourer. Raises DayLabourer.DoesNotExist outside the organization."""
    return DayLabourer.objects.for_organization(organization).get(pk=labourer_id)


def day_labour_of(
    organization: Organization,
    *,
    date_from: dt.date | None = None,
    date_to: dt.date | None = None,
    labourer_id: int | None = None,
    batch_id: int | None = None,
) -> QuerySet[DayLabourEntry]:
    """Days worked, by day then labourer name, each with its expense (amount, lot, status). The calendar
    reads a month; a lot reads its own days."""
    entries = (
        DayLabourEntry.objects.for_organization(organization)
        .select_related("labourer", "expense__batch__product", "expense__entered_by", "expense__decided_by")
        .order_by("expense__spent_on", "labourer__name", "id")
    )
    if date_from is not None:
        entries = entries.filter(expense__spent_on__gte=date_from)
    if date_to is not None:
        entries = entries.filter(expense__spent_on__lte=date_to)
    if labourer_id is not None:
        entries = entries.filter(labourer_id=labourer_id)
    if batch_id is not None:
        entries = entries.filter(expense__batch_id=batch_id)
    return entries


def day_labour_entry_of(organization: Organization, entry_id: int) -> DayLabourEntry:
    """One day worked. Raises DayLabourEntry.DoesNotExist outside the organization."""
    return day_labour_of(organization).get(pk=entry_id)


# What a driver can spend on from the road (P3-T04): fuel, tolls and transport, handling (ice...), other.
ROAD_CATEGORY_CODES = ("fuel", "transport", "handling", "miscellaneous")


def road_categories(organization: Organization) -> QuerySet[ExpenseCategory]:
    """The categories a driver picks from, as the owner set them (D-205), in the order of the list."""
    return categories_of(organization).filter(for_drivers=True)


def road_expenses(organization: Organization, *, user_id: int, day: dt.date) -> QuerySet[Expense]:
    """What this driver typed on a day, newest first."""
    return expenses_of(organization, date_from=day, date_to=day).filter(entered_by_id=user_id)


# ---- Month figures (P6-T05, D-073) ----


@dataclass(frozen=True)
class CategoryTotal:
    category_id: int
    code: str
    name: str
    count: int
    total: Decimal


@dataclass(frozen=True)
class MonthExpenses:
    """The period's expenses: approved ones by category (what the books count), and the ones still waiting
    for a decision (drafts and pending), which block the monthly closing."""

    categories: tuple[CategoryTotal, ...]
    total: Decimal
    waiting_count: int
    waiting_amount: Decimal


def month_expenses(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> MonthExpenses:
    rows = (
        expenses_of(organization, date_from=date_from, date_to=date_to)
        .filter(status=ExpenseStatus.APPROVED)
        .order_by()
        .values("category_id", "category__code", "category__name", "category__position")
        .annotate(count=Count("id"), total=Sum("amount"))
        .order_by("category__position", "category__name")
    )
    categories = tuple(
        CategoryTotal(
            category_id=row["category_id"],
            code=row["category__code"],
            name=row["category__name"],
            count=row["count"],
            total=row["total"],
        )
        for row in rows
    )
    waiting = expense_totals(expenses_of(organization, date_from=date_from, date_to=date_to))
    waiting_count = (
        expenses_of(organization, date_from=date_from, date_to=date_to)
        .filter(status__in=[ExpenseStatus.DRAFT, ExpenseStatus.PENDING])
        .order_by()
        .count()
    )
    return MonthExpenses(
        categories=categories,
        total=sum((category.total for category in categories), ZERO),
        waiting_count=waiting_count,
        waiting_amount=waiting.waiting,
    )


def waiting_for_approval(organization: Organization) -> int:
    """Expenses sent for approval and not decided yet (the dashboard's alert; drafts are still being typed)."""
    return Expense.objects.for_organization(organization).filter(status=ExpenseStatus.PENDING).count()


def approved_by_day(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> dict[dt.date, Decimal]:
    """Approved expenses per day (`spent_on`), inclusive. Payroll is not an expense: it is in `hr`."""
    rows = (
        Expense.objects.for_organization(organization)
        .filter(status=ExpenseStatus.APPROVED, spent_on__gte=date_from, spent_on__lte=date_to)
        .values("spent_on")
        .annotate(total=Sum("amount"))
    )
    return {row["spent_on"]: row["total"] for row in rows}
