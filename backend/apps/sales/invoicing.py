"""The arithmetic of an invoice (D-057): VAT per rate, line shares, stamp, withholding. Pure functions, no
database: the services feed them the lines and the values in force, then store what comes out.

Rounding (ARCHITECTURE §4.1): half up to the millime, once per rate and once per total.

- Prices without VAT: base of a rate = sum of its lines as charged; VAT = base × rate / 100.
- Prices with VAT: the lines as charged hold the VAT; base = charged × 100 / (100 + rate), VAT = charged − base.
- A typed VAT amount (`vat_overrides`) replaces the computed one of its rate. With prices without VAT the
  base stays and the total with VAT moves; with prices with VAT what was charged stays and the base moves.
- Each line gets its share of its rate's VAT by amount (the last line of the rate takes the rest), so the
  lines always add up to the totals.
- Without VAT (`apply_vat` false) nothing is added or taken out: every line is without VAT as charged.
- Withholding = (total without VAT + VAT) × rate / 100, the stamp excluded; net to pay = total with VAT
  (stamp included) − withholding. Only an invoice whose total with VAT reaches 1 000 DT has one (owner rule).
"""

from collections.abc import Sequence
from dataclasses import dataclass, field
from decimal import Decimal

from apps.core.money import money

ZERO = Decimal("0.000")
HUNDRED = Decimal("100")
# The rate stored on the lines of an invoice without VAT.
NO_RATE = Decimal("0.00")
# An invoice whose total with tax (stamp and fees included) reaches this amount carries the withholding; below
# it none is taken, whatever the settings say.
WITHHOLDING_FROM = Decimal("1000.000")


@dataclass(frozen=True)
class LineInput:
    # The line's amount as charged on the sale (after its discount).
    amount: Decimal
    # The line's VAT rate in percent (ignored without VAT).
    vat_rate: Decimal
    unit_price: Decimal = ZERO


@dataclass(frozen=True)
class LineResult:
    vat_rate: Decimal
    unit_price_excl_tax: Decimal
    amount_excl_tax: Decimal
    vat_amount: Decimal
    amount_incl_tax: Decimal


@dataclass(frozen=True)
class VatGroup:
    rate: Decimal
    base: Decimal
    computed_amount: Decimal
    amount: Decimal

    @property
    def overridden(self) -> bool:
        return self.amount != self.computed_amount


@dataclass(frozen=True)
class InvoiceAmounts:
    lines: list[LineResult]
    vat_groups: list[VatGroup]
    total_excl_tax: Decimal
    vat_total: Decimal
    fiscal_stamp: Decimal
    total_incl_tax: Decimal
    withholding_amount: Decimal
    net_to_pay: Decimal
    fees: Decimal = ZERO
    # Typed VAT amounts that cannot apply, by rate, with the reason (an amount above what the rate holds).
    refused_overrides: dict[Decimal, str] = field(default_factory=dict)


def shared_by(amount: Decimal, weights: Sequence[Decimal]) -> list[Decimal]:
    """`amount` shared in proportion to `weights`, each part rounded once; the last part takes the rest, so
    the parts always add up to `amount`. All zero when the weights add up to zero."""
    if not weights:
        return []
    total = sum(weights, ZERO)
    if total == 0:
        return [ZERO] * len(weights)
    parts = [money(amount * weight / total) for weight in weights[:-1]]
    return [*parts, amount - sum(parts, ZERO)]


def excl_tax(amount: Decimal, rate: Decimal) -> Decimal:
    """An amount holding VAT at `rate`, without it (rounded once)."""
    return money(amount * HUNDRED / (HUNDRED + rate))


def withholding_applies(total_incl_tax: Decimal) -> bool:
    """Whether an invoice with this total carries a withholding: from 1 000 DT, never below (owner rule)."""
    return total_incl_tax >= WITHHOLDING_FROM


def compute(
    lines: Sequence[LineInput],
    *,
    apply_vat: bool,
    prices_include_vat: bool,
    fiscal_stamp: Decimal,
    withholding_rate: Decimal | None,
    vat_overrides: dict[Decimal, Decimal] | None = None,
    fees: Decimal = ZERO,
) -> InvoiceAmounts:
    """Every amount of an invoice from its lines. `withholding_rate` None means no withholding, and so does a total
    under 1 000 DT. `fees` (Frais) add to the total like the stamp: no VAT on them and no withholding (D-126)."""
    overrides = vat_overrides or {}
    refused: dict[Decimal, str] = {}
    results: list[LineResult | None] = [None] * len(lines)
    groups: list[VatGroup] = []
    rates = sorted({line.vat_rate for line in lines}, reverse=True) if apply_vat else []
    if not apply_vat:
        for index, line in enumerate(lines):
            results[index] = LineResult(NO_RATE, line.unit_price, line.amount, ZERO, line.amount)
    for rate in rates:
        members = [index for index, line in enumerate(lines) if line.vat_rate == rate]
        charged = sum((lines[index].amount for index in members), ZERO)
        if rate == 0:
            computed = ZERO
        elif prices_include_vat:
            computed = charged - excl_tax(charged, rate)
        else:
            computed = money(charged * rate / HUNDRED)
        amount = computed
        typed = overrides.get(rate)
        if typed is not None and rate > 0:
            if typed > charged:
                refused[rate] = "too_high"
            else:
                amount = typed
        base = charged - amount if prices_include_vat else charged
        groups.append(VatGroup(rate=rate, base=base, computed_amount=computed, amount=amount))
        vat_parts = shared_by(amount, [lines[index].amount for index in members])
        for index, vat in zip(members, vat_parts, strict=True):
            line = lines[index]
            line_excl = line.amount - vat if prices_include_vat else line.amount
            unit_excl = excl_tax(line.unit_price, rate) if prices_include_vat else line.unit_price
            results[index] = LineResult(rate, unit_excl, line_excl, vat, line_excl + vat)
    final = [result for result in results if result is not None]
    total_excl_tax = sum((result.amount_excl_tax for result in final), ZERO)
    vat_total = sum((group.amount for group in groups), ZERO)
    total_incl_tax = total_excl_tax + vat_total + fiscal_stamp + fees
    withholding = ZERO
    if withholding_rate is not None and withholding_rate > 0 and withholding_applies(total_incl_tax):
        withholding = money((total_excl_tax + vat_total) * withholding_rate / HUNDRED)
    return InvoiceAmounts(
        lines=final,
        vat_groups=groups,
        total_excl_tax=total_excl_tax,
        vat_total=vat_total,
        fiscal_stamp=fiscal_stamp,
        total_incl_tax=total_incl_tax,
        withholding_amount=withholding,
        net_to_pay=total_incl_tax - withholding,
        fees=fees,
        refused_overrides=refused,
    )
