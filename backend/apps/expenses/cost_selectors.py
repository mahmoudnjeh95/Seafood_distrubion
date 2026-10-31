"""Reads behind the cold-room cost and the general costs of a lot (P5-T02, P5-T05, D-058, D-059).

The kilos held each day come from the stock ledger through `inventory.selectors`; the amounts are split by
the pure functions of `costing`. `selectors.lot_cost_lines` puts these lines next to the others.
"""

import datetime as dt
from collections import defaultdict
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import TYPE_CHECKING

from django.db.models import QuerySet

from apps.core.models import Organization
from apps.inventory import selectors as inventory
from apps.inventory.services import LocationKind

if TYPE_CHECKING:
    from apps.inventory.models import StockLocation

from .costing import (
    ZERO,
    allocate_general_days,
    allocate_room_days,
    estimate_day_amount,
    first_of_month,
    last_of_month,
    month_days,
    next_month,
    room_day_amounts,
    room_month_amounts,
    spread_over_months,
)
from .models import (
    ColdRoomEstimate,
    ColdRoomMonthRate,
    ColdRoomWeight,
    ElectricityBill,
    Expense,
    ExpenseStatus,
    GeneralCostPeriod,
    LotCostAdjustment,
    LotCostKind,
    RecurringCost,
)

# ---- Rooms, weights and bills ----


def cold_rooms(organization: Organization) -> list["StockLocation"]:
    """The active cold rooms, by name: the places the electricity is shared between."""
    return list(inventory.locations_of(organization, kinds=[LocationKind.COLD_ROOM], status="active"))


def room_weights(organization: Organization) -> dict[int, Decimal]:
    """Each active cold room's weight (equal, 1, unless the owner set another)."""
    set_by_owner = dict(ColdRoomWeight.objects.for_organization(organization).values_list("location_id", "weight"))
    return {room.pk: set_by_owner.get(room.pk, Decimal("1.000")) for room in cold_rooms(organization)}


def bills_of(organization: Organization) -> QuerySet[ElectricityBill]:
    """Electricity bills, newest month first, with their expense."""
    return (
        ElectricityBill.objects.for_organization(organization)
        .select_related("expense__category", "expense__entered_by", "expense__decided_by")
        .order_by("-month", "-id")
    )


def bill_of(organization: Organization, bill_id: int) -> ElectricityBill:
    """One bill. Raises ElectricityBill.DoesNotExist outside the organization."""
    return bills_of(organization).get(pk=bill_id)


def _frozen_rates(organization: Organization) -> dict[dt.date, dict[int, ColdRoomMonthRate]]:
    """The frozen rates of every approved bill: `{month: {room id: rate}}`."""
    rates: dict[dt.date, dict[int, ColdRoomMonthRate]] = defaultdict(dict)
    for rate in (
        ColdRoomMonthRate.objects.for_organization(organization)
        .filter(bill__finalized_at__isnull=False)
        .select_related("bill", "location")
    ):
        rates[rate.bill.month][rate.location_id] = rate
    return dict(rates)


def typed_estimates(organization: Organization) -> dict[dt.date, Decimal]:
    """The estimates the owner typed, by month (D-227)."""
    return {row.month: row.amount for row in ColdRoomEstimate.objects.for_organization(organization)}


@dataclass(frozen=True)
class Estimate:
    """What an unbilled month costs in the cold rooms until its bill is approved (D-058, D-227)."""

    # True when the owner typed the month's estimate; then it is shared by weight, as a bill is.
    typed: bool
    # The billed month whose daily rate is copied (None when typed, or when no earlier month is billed).
    source_month: dt.date | None
    # Per room: its part of the typed month (empty when copied).
    month_amounts: dict[int, Decimal]
    # Per room: the daily rate of the estimate (empty when there is none).
    day_amounts: dict[int, Decimal]


def _estimate(
    month: dt.date,
    frozen: dict[dt.date, dict[int, ColdRoomMonthRate]],
    typed: Mapping[dt.date, Decimal],
    weights: Mapping[int, Decimal],
) -> Estimate:
    """The estimate of a month: the amount the owner typed for it, else the daily rate of the latest billed
    month before it (the previous month's, when there is one)."""
    if month in typed:
        parts = room_month_amounts(typed[month], weights)
        days = {room_id: estimate_day_amount(part, month) for room_id, part in parts.items()}
        return Estimate(typed=True, source_month=None, month_amounts=parts, day_amounts=days)
    earlier = [billed for billed in frozen if billed < month]
    if not earlier:
        return Estimate(typed=False, source_month=None, month_amounts={}, day_amounts={})
    source = max(earlier)
    days = {room_id: estimate_day_amount(rate.month_amount, source) for room_id, rate in frozen[source].items()}
    return Estimate(typed=False, source_month=source, month_amounts={}, day_amounts=days)


@dataclass(frozen=True)
class ComputedLine:
    """A cost line of a lot worked out from the ledger (not an expense row of its own)."""

    kind: str
    spent_on: dt.date
    month: dt.date
    amount: Decimal
    description: str
    location_name: str = ""
    # Kg-days: the lot's kg summed over the days charged.
    quantity: Decimal | None = None
    estimated: bool = False
    expense: Expense | None = None
    expense_amount: Decimal = ZERO


# ---- Cold room: lines of one lot ----


def _months_between(first: dt.date, last: dt.date) -> list[dt.date]:
    months = []
    month = first_of_month(first)
    while month <= last:
        months.append(month)
        month = next_month(month)
    return months


def cold_room_lines(organization: Organization, *, batch_id: int, today: dt.date) -> list[ComputedLine]:
    """A lot's cold-room costs: for each cold room and month it spent time in, one line = the room's cost
    of that time charged by the hour and split by kg held (D-041, D-142), **estimated** (flagged) until the
    month's bill is approved. After the bill the estimate line stays as it was charged and the difference is a
    `cold_room_adjustment` line dated when the bill was typed (D-041: a closed lot is never reopened)."""
    first = inventory.first_movement_day(organization, batch_id=batch_id)
    if first is None or first > today:
        return []
    rooms = {
        room.pk: room for room in inventory.locations_of(organization, kinds=[LocationKind.COLD_ROOM], status="all")
    }
    if not rooms:
        return []
    held = inventory.held_slices_by_hour(organization, date_from=first, date_to=today, location_ids=list(rooms))
    frozen = _frozen_rates(organization)
    typed = typed_estimates(organization)
    weights = room_weights(organization)
    bills = {bill.month: bill for bill in bills_of(organization).filter(finalized_at__isnull=False)}
    lines: list[ComputedLine] = []
    for month in _months_between(first, today):
        days = [day for day in month_days(month) if first <= day <= today]
        if month in frozen:
            estimates = {room_id: rate.estimate_day_amount for room_id, rate in frozen[month].items()}
        else:
            estimates = _estimate(month, frozen, typed, weights).day_amounts
        for room_id, room in rooms.items():
            estimate = estimates.get(room_id)
            if estimate is None or estimate <= 0:
                continue
            charge = allocate_room_days(dict.fromkeys(days, estimate), held.get(room_id, {})).get(batch_id)
            if charge is None or charge.amount == 0:
                continue
            bill = bills.get(month)
            lines.append(
                ComputedLine(
                    kind=LotCostKind.COLD_ROOM,
                    spent_on=min(last_of_month(month), today),
                    month=month,
                    amount=charge.amount,
                    description=room.name,
                    location_name=room.name,
                    quantity=charge.kg_days,
                    estimated=True,
                    expense=bill.expense if bill is not None else None,
                    expense_amount=bill.expense.amount if bill is not None else ZERO,
                )
            )
    adjustments = (
        LotCostAdjustment.objects.for_organization(organization)
        .filter(batch_id=batch_id)
        .select_related("location", "bill__expense")
        .order_by("dated_on", "id")
    )
    for adjustment in adjustments:
        lines.append(
            ComputedLine(
                kind=LotCostKind.COLD_ROOM_ADJUSTMENT,
                spent_on=adjustment.dated_on,
                month=adjustment.month,
                amount=adjustment.amount,
                description=adjustment.location.name if adjustment.location is not None else "",
                location_name=adjustment.location.name if adjustment.location is not None else "",
                expense=adjustment.bill.expense if adjustment.bill is not None else None,
                expense_amount=adjustment.bill.expense.amount if adjustment.bill is not None else ZERO,
            )
        )
    return lines


@dataclass(frozen=True)
class RoomAdjustment:
    batch_id: int
    location_id: int
    amount: Decimal


def bill_adjustments(
    organization: Organization,
    *,
    month: dt.date,
    rates: dict[int, tuple[Decimal, Decimal | None]],
) -> list[RoomAdjustment]:
    """For an approved bill, what each lot owes more (or less) than its estimate: real minus estimate, per
    lot and cold room. `rates` is `{room id: (the room's part of the month, the estimate's daily rate or
    None)}`. A lot with no difference is left out."""
    days = month_days(month)
    held = inventory.held_slices_by_hour(organization, date_from=days[0], date_to=days[-1], location_ids=list(rates))
    adjustments: list[RoomAdjustment] = []
    for room_id, (month_amount, estimate) in rates.items():
        real = allocate_room_days(room_day_amounts(month_amount, month), held.get(room_id, {}))
        guessed = (
            allocate_room_days(dict.fromkeys(days, estimate), held.get(room_id, {})) if estimate is not None else {}
        )
        for batch_id in sorted(set(real) | set(guessed)):
            difference = (real[batch_id].amount if batch_id in real else ZERO) - (
                guessed[batch_id].amount if batch_id in guessed else ZERO
            )
            if difference != 0:
                adjustments.append(RoomAdjustment(batch_id=batch_id, location_id=room_id, amount=difference))
    return adjustments


def estimate_for_new_bill(organization: Organization, *, month: dt.date) -> Estimate:
    """The estimate a bill for `month` replaces: the typed amount or the copied daily rate, per room."""
    return _estimate(month, _frozen_rates(organization), typed_estimates(organization), room_weights(organization))


# ---- Cold room: the month screen ----


@dataclass(frozen=True)
class RoomMonthRow:
    location_id: int
    location_name: str
    weight: Decimal
    # Share of the bill in %, and what the room costs for the month and per day. For a month not billed
    # yet these are the estimate (the previous month's daily rate).
    month_amount: Decimal | None
    day_amount: Decimal | None
    estimated: bool


@dataclass(frozen=True)
class ColdRoomMonth:
    month: dt.date
    days: int
    bill: ElectricityBill | None
    # True until the month's bill is approved.
    estimated: bool
    # The estimate the owner typed for the month (None when there is none), and whether it is in use.
    typed_amount: Decimal | None
    estimate_typed: bool
    estimate_source_month: dt.date | None
    rooms: list[RoomMonthRow]
    # Real once the bill is approved, else the estimate.
    total: Decimal | None
    # What the month was estimated at (None when there was no estimate), and the real bill minus it.
    estimate_total: Decimal | None
    difference: Decimal | None


def cold_room_month(organization: Organization, *, month: dt.date) -> ColdRoomMonth:
    """One month of cold-room costs: the bill if there is one, and for each room its weight, its cost for
    the month and per day, real once the bill is approved, else the estimate."""
    month = first_of_month(month)
    days = len(month_days(month))
    bill = bills_of(organization).filter(month=month).first()
    frozen = _frozen_rates(organization)
    typed = typed_estimates(organization)
    rooms: list[RoomMonthRow] = []
    if bill is not None and bill.finalized_at is not None:
        for rate in sorted(frozen[month].values(), key=lambda rate: (rate.location.name, rate.pk)):
            rooms.append(
                RoomMonthRow(
                    location_id=rate.location_id,
                    location_name=rate.location.name,
                    weight=rate.weight,
                    month_amount=rate.month_amount,
                    day_amount=rate.month_amount / days,
                    estimated=False,
                )
            )
        # What the rooms were estimated at: the daily rates that were used, over the days of the month.
        daily_rates = [rate.estimate_day_amount for rate in frozen[month].values()]
        known_rates = [daily for daily in daily_rates if daily is not None]
        estimate_total = sum((daily * days for daily in known_rates), ZERO) if known_rates else None
        return ColdRoomMonth(
            month=month,
            days=days,
            bill=bill,
            estimated=False,
            typed_amount=typed.get(month),
            estimate_typed=month in typed,
            estimate_source_month=None,
            rooms=rooms,
            total=bill.expense.amount,
            estimate_total=estimate_total,
            difference=bill.expense.amount - estimate_total if estimate_total is not None else None,
        )
    weights = room_weights(organization)
    estimate = _estimate(month, frozen, typed, weights)
    names = {room.pk: room.name for room in cold_rooms(organization)}
    for room_id, weight in weights.items():
        daily = estimate.day_amounts.get(room_id)
        if estimate.typed:
            month_amount = estimate.month_amounts.get(room_id)
        else:
            month_amount = daily * days if daily is not None else None
        rooms.append(
            RoomMonthRow(
                location_id=room_id,
                location_name=names[room_id],
                weight=weight,
                month_amount=month_amount,
                day_amount=daily,
                estimated=True,
            )
        )
    known = [row.month_amount for row in rooms if row.month_amount is not None]
    total = sum(known, ZERO) if known else None
    return ColdRoomMonth(
        month=month,
        days=days,
        bill=bill,
        estimated=True,
        typed_amount=typed.get(month),
        estimate_typed=estimate.typed,
        estimate_source_month=estimate.source_month,
        rooms=rooms,
        total=total,
        estimate_total=total,
        difference=None,
    )


# ---- General costs ----


def recurring_costs_of(organization: Organization, *, active_only: bool = False) -> QuerySet[RecurringCost]:
    costs = RecurringCost.objects.for_organization(organization).select_related("category").order_by("name", "id")
    return costs.filter(is_active=True) if active_only else costs


def recurring_cost_of(organization: Organization, cost_id: int) -> RecurringCost:
    """One template. Raises RecurringCost.DoesNotExist outside the organization."""
    return recurring_costs_of(organization).get(pk=cost_id)


def general_periods_of(organization: Organization, *, month: dt.date | None = None) -> QuerySet[GeneralCostPeriod]:
    """General costs (templates' months and multi-month bills), newest first, with their expense. With
    `month`, those covering that month."""
    periods = (
        GeneralCostPeriod.objects.for_organization(organization)
        .select_related("expense__category", "recurring")
        .order_by("-first_month", "-id")
    )
    if month is not None:
        month = first_of_month(month)
        covering = [period.pk for period in periods if period.first_month <= month < _end(period)]
        periods = periods.filter(pk__in=covering)
    return periods


def _end(period: GeneralCostPeriod) -> dt.date:
    end = period.first_month
    for _index in range(period.months):
        end = next_month(end)
    return end


def general_period_of(organization: Organization, period_id: int) -> GeneralCostPeriod:
    """One general cost. Raises GeneralCostPeriod.DoesNotExist outside the organization."""
    return general_periods_of(organization).get(pk=period_id)


def general_lines(organization: Organization, *, batch_id: int, today: dt.date) -> list[ComputedLine]:
    """A lot's share of the general costs, "like a salary" (D-041, Q21 confirmed 2026-10-13): each approved general
    cost carries monthly amount / 26 per day, split over the lots in stock that day by kg held; one line
    per cost and month."""
    first = inventory.first_movement_day(organization, batch_id=batch_id)
    if first is None or first > today:
        return []
    periods = list(
        GeneralCostPeriod.objects.for_organization(organization)
        .filter(expense__status=ExpenseStatus.APPROVED)
        .select_related("expense__category")
        .order_by("first_month", "id")
    )
    if not periods:
        return []
    held = inventory.held_slices_by_hour(organization, date_from=first, date_to=today)[inventory.EVERYWHERE]
    lines: list[ComputedLine] = []
    for period in periods:
        amounts = spread_over_months(period.expense.amount, period.months)
        month = period.first_month
        for monthly in amounts:
            days = [day for day in month_days(month) if first <= day <= today]
            charge = allocate_general_days(monthly, month, days, held).get(batch_id)
            if charge is not None and charge.amount != 0:
                lines.append(
                    ComputedLine(
                        kind=LotCostKind.GENERAL,
                        spent_on=min(last_of_month(month), today),
                        month=month,
                        amount=charge.amount,
                        description=period.expense.description or period.expense.payee,
                        quantity=charge.kg_days,
                        expense=period.expense,
                        expense_amount=period.expense.amount,
                    )
                )
            month = next_month(month)
    return lines
