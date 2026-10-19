"""Cold-room cost per day and general costs per day, to the millime (D-041, D-058, D-059).

Pure functions: no database. Every split goes through `allocation.split_by_weight`, so the shares of an
amount always add up to it exactly.
"""

import calendar
import datetime as dt
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal

from apps.core.money import money, quantity

from .allocation import split_by_weight

ZERO = Decimal("0.000")


def first_of_month(day: dt.date) -> dt.date:
    return day.replace(day=1)


def next_month(month: dt.date) -> dt.date:
    return (month.replace(day=28) + dt.timedelta(days=4)).replace(day=1)


def add_months(month: dt.date, count: int) -> dt.date:
    """The first day of the month `count` months after (or before, if negative) `month`."""
    index = month.year * 12 + (month.month - 1) + count
    return dt.date(index // 12, index % 12 + 1, 1)


def days_in_month(month: dt.date) -> int:
    return calendar.monthrange(month.year, month.month)[1]


def last_of_month(month: dt.date) -> dt.date:
    return month.replace(day=days_in_month(month))


def month_days(month: dt.date) -> list[dt.date]:
    return [month + dt.timedelta(days=offset) for offset in range(days_in_month(month))]


def split_evenly(amount: Decimal, parts: int) -> list[Decimal]:
    """`amount` in `parts` equal parts to the millime: they add up to `amount` exactly (the first parts
    take the extra millimes)."""
    shares = split_by_weight(amount, {index: Decimal(1) for index in range(parts)})
    return [shares[index] for index in range(parts)]


def room_month_amounts(bill: Decimal, weights: Mapping[int, Decimal]) -> dict[int, Decimal]:
    """The electricity bill shared between the cold rooms by weight: each room's part of the month, adding
    up to the bill exactly. Rooms are the keys of `weights`."""
    return split_by_weight(bill, weights)


def room_day_amounts(room_month_amount: Decimal, month: dt.date) -> dict[dt.date, Decimal]:
    """A room's part of the month spread over the days of the month (to the millime, adding up exactly)."""
    days = month_days(month)
    return dict(zip(days, split_evenly(room_month_amount, len(days)), strict=True))


def estimate_day_amount(room_month_amount: Decimal, month: dt.date) -> Decimal:
    """The daily rate of a billed month, used as the estimate for a month not billed yet: the room's
    part of that month divided by its days, rounded once to the millime."""
    return money(room_month_amount / days_in_month(month))


HOURS_PER_DAY = 24
SECONDS_PER_HOUR = 3600
SECONDS_PER_DAY = HOURS_PER_DAY * SECONDS_PER_HOUR

# What a room held, hour by hour (`inventory.selectors.held_slices_by_hour`): `{day: {hour: [(seconds, {batch
# id: kg}), ...]}}`. Each entry is a stretch of time inside one hour in which the same lots were in the room.
HeldByHour = Mapping[dt.date, Mapping[int, Sequence[tuple[int, Mapping[int, Decimal]]]]]


@dataclass(frozen=True)
class RoomCharge:
    """What one lot carries for one cold room over some days."""

    amount: Decimal
    # Kg held, over the time it was there, in kg-days (kg x hours / 24).
    kg_days: Decimal


def _hour_shares(hour_amount: Decimal, slices: Sequence[tuple[int, Mapping[int, Decimal]]]) -> dict[int, Decimal]:
    """One hour's amount over the stretches of time in it: each stretch takes its seconds' part of the hour,
    the seconds the room was empty take nothing, and each stretch shares its part over its lots by kg."""
    weights = {index: Decimal(seconds) for index, (seconds, _lots) in enumerate(slices)}
    empty = SECONDS_PER_HOUR - sum(seconds for seconds, _lots in slices)
    if empty > 0:
        weights[-1] = Decimal(empty)
    parts = split_by_weight(hour_amount, weights)
    shares: dict[int, Decimal] = {}
    for index, (_seconds, lots) in enumerate(slices):
        for batch_id, share in split_by_weight(parts.get(index, ZERO), lots).items():
            shares[batch_id] = shares.get(batch_id, ZERO) + share
    return shares


def allocate_room_days(day_amounts: Mapping[dt.date, Decimal], held: HeldByHour) -> dict[int, RoomCharge]:
    """A cold room's cost charged by the hour (D-142): each day's amount is 24 equal hours (to the millime),
    and each hour is shared over the time the lots spent in the room during it, by kg. Time the room was
    empty is nobody's: a lot that stayed from 00:28 to 21:38 pays those 21 h 10 min and no more. Every hour
    adds up to its amount exactly, so every day does too."""
    totals: dict[int, Decimal] = {}
    kg_seconds: dict[int, Decimal] = {}
    for day, amount in day_amounts.items():
        hour_amounts = split_evenly(amount, HOURS_PER_DAY)
        for hour, slices in held.get(day, {}).items():
            for batch_id, share in _hour_shares(hour_amounts[hour], slices).items():
                totals[batch_id] = totals.get(batch_id, ZERO) + share
            for seconds, lots in slices:
                for batch_id, kg in lots.items():
                    kg_seconds[batch_id] = kg_seconds.get(batch_id, ZERO) + kg * seconds
    return {
        batch_id: RoomCharge(
            amount=totals.get(batch_id, ZERO), kg_days=quantity(kg_seconds[batch_id] / SECONDS_PER_DAY)
        )
        for batch_id in sorted(kg_seconds)
    }


def general_day_amounts(monthly_amount: Decimal, month: dt.date) -> dict[dt.date, Decimal]:
    """A month's general cost spread over its calendar days, to the millime, adding up to the month exactly: a lot
    in stock all month carries the whole amount once (D-190, provisional: a day is a calendar day, not a 26th)."""
    days = month_days(month)
    return dict(zip(days, split_evenly(monthly_amount, len(days)), strict=True))


def spread_over_months(amount: Decimal, months: int) -> list[Decimal]:
    """A bill covering several months, spread equally over them (adding up to the bill exactly)."""
    return split_evenly(amount, months)


def allocate_general_days(
    monthly_amount: Decimal, month: dt.date, days: list[dt.date], held: HeldByHour
) -> dict[int, RoomCharge]:
    """A month's general cost: each of `days` (days of `month`) costs its share of the month, charged by the hour
    over the lots in stock (D-142, the same split as the cold room, Q21 confirmed 2026-10-13). Time with nothing
    in stock is not charged to anyone."""
    shares = general_day_amounts(monthly_amount, month)
    return allocate_room_days({day: shares[day] for day in days}, held)
