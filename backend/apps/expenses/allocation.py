"""Splitting an amount over lots by weight, to the millime (D-041, D-053). Pure functions: no database."""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction

from apps.core.money import GRAM, MILLIME


def split_by_weight(amount: Decimal, weights: Mapping[int, Decimal]) -> dict[int, Decimal]:
    """`amount` shared over the keys of `weights` in proportion to their weight, each part in millimes.

    The parts always add up to `amount` exactly: each key first gets its exact share rounded down to the
    millime, then the millimes left over go one each to the largest remainders (ties: the heavier key, then
    the smaller key). Keys with no weight get nothing. Empty when there is nothing to split over.
    Integer arithmetic in millimes and grams, so no rounding error can creep in.
    """
    grams = {key: int(weight / GRAM) for key, weight in weights.items() if weight > 0}
    total_grams = sum(grams.values())
    if total_grams == 0:
        return {}
    millimes = int(amount / MILLIME)
    floors: dict[int, int] = {}
    remainders: dict[int, int] = {}
    for key, weight in grams.items():
        floors[key], remainders[key] = divmod(millimes * weight, total_grams)
    left_over = millimes - sum(floors.values())
    for key in sorted(grams, key=lambda key: (-remainders[key], -grams[key], key))[:left_over]:
        floors[key] += 1
    return {key: Decimal(floors[key]) * MILLIME for key in sorted(grams)}


def split_by_weight_carrying(
    amount: Decimal, weights: Mapping[int, Decimal], carry: dict[int, Fraction]
) -> dict[int, Decimal]:
    """`split_by_weight`, but each key's part of a millime left over by the earlier splits in `carry` is
    added to its share here, and what is left over now goes back into `carry`. Used over the hours of a
    month, where the same split comes back every hour: a key then gets its exact share over the whole run,
    to within one millime, instead of the same rounding every hour. The parts add up to `amount` exactly.
    """
    grams = {key: int(weight / GRAM) for key, weight in weights.items() if weight > 0}
    total_grams = sum(grams.values())
    if total_grams == 0:
        return {}
    millimes = int(amount / MILLIME)
    ideal = {
        key: Fraction(millimes * weight, total_grams) + carry.get(key, Fraction(0)) for key, weight in grams.items()
    }
    floors = {key: math.floor(value) for key, value in ideal.items()}
    left_over = millimes - sum(floors.values())
    for key in sorted(grams, key=lambda key: (-(ideal[key] - floors[key]), -grams[key], key))[:left_over]:
        floors[key] += 1
    for key in grams:
        carry[key] = ideal[key] - floors[key]
    return {key: Decimal(floors[key]) * MILLIME for key in sorted(grams)}


@dataclass(frozen=True)
class TruckDayExpense:
    """An approved expense tagged to a truck and a day (only what the split needs)."""

    expense_id: int
    amount: Decimal


@dataclass(frozen=True)
class LoadedLot:
    """Kilos of one lot loaded on the truck that day."""

    batch_id: int
    quantity: Decimal


@dataclass(frozen=True)
class TruckCostShare:
    """The part of one truck-day expense charged to one lot."""

    expense_id: int
    batch_id: int
    quantity: Decimal
    amount: Decimal


def allocate_truck_day_costs(expenses: Sequence[TruckDayExpense], loads: Sequence[LoadedLot]) -> list[TruckCostShare]:
    """Each truck cost of a day split over the lots loaded on that truck that day, by kg loaded (D-041,
    provisional until Q24 is answered).

    Every expense is split on its own, so the shares of one expense add up to it to the millime. A day
    with no lot loaded gives no share: those costs stay general costs. Shares come per expense, then by
    lot id.
    """
    weights: dict[int, Decimal] = {}
    for load in loads:
        weights[load.batch_id] = weights.get(load.batch_id, Decimal("0.000")) + load.quantity
    shares: list[TruckCostShare] = []
    for expense in expenses:
        for batch_id, amount in split_by_weight(expense.amount, weights).items():
            shares.append(
                TruckCostShare(
                    expense_id=expense.expense_id, batch_id=batch_id, quantity=weights[batch_id], amount=amount
                )
            )
    return shares
