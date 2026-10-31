"""Amounts in Tunisian dinars and weights in kg: Decimal with 3 places, never floats (ARCHITECTURE §4.1-2).

Round only at defined points (a line total, a document total), with `money()` or `quantity()`.
"""

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Any

from django.db import models
from django.utils.translation import gettext as _

DECIMAL_PLACES = 3
MILLIME = Decimal("0.001")
GRAM = Decimal("0.001")
MAX_QUANTITY = Decimal("999999999.999")  # the largest value a QuantityField holds
MAX_AMOUNT = Decimal("99999999999.999")  # the largest value a MoneyField holds

type Number = Decimal | int | str


def _to_decimal(value: Number) -> Decimal:
    # bool is an int subclass, and a float has already lost precision: both are programming errors here.
    if isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        raise TypeError(f"Expected Decimal, int or str, got {type(value).__name__}: floats are never allowed")
    return Decimal(value)


def money(value: Number) -> Decimal:
    """Round an amount to millimes, half up."""
    return _to_decimal(value).quantize(MILLIME, rounding=ROUND_HALF_UP)


def quantity(value: Number) -> Decimal:
    """Round a weight to grams (3 decimals of a kg), half up."""
    return _to_decimal(value).quantize(GRAM, rounding=ROUND_HALF_UP)


def checked_quantity(value: Number, *, allow_zero: bool = False) -> Decimal:
    """A weight typed by a person or read from a scale: checked, never silently rounded.

    Refused with ValueError: more than 3 decimals (finer than a gram), a negative value (the movement
    type carries the direction), zero unless `allow_zero`, text that is not a number, and anything
    larger than a QuantityField can store.
    """
    try:
        result = _to_decimal(value)
    except InvalidOperation:
        raise ValueError(_("« %(value)s » n'est pas une quantité.") % {"value": value}) from None
    if not result.is_finite():
        raise ValueError(_("« %(value)s » n'est pas une quantité.") % {"value": value})
    if result != result.quantize(GRAM):
        raise ValueError(_("%(value)s kg : au plus 3 décimales (le gramme).") % {"value": value})
    if result < 0:
        raise ValueError(_("%(value)s kg : une quantité ne peut pas être négative.") % {"value": value})
    if result == 0 and not allow_zero:
        raise ValueError(_("La quantité doit être supérieure à zéro."))
    if result > MAX_QUANTITY:
        raise ValueError(_("%(value)s kg : quantité trop grande.") % {"value": value})
    return result.quantize(GRAM)


def checked_amount(value: Number) -> Decimal:
    """An amount typed by a person (a purchase cost, a payment): checked, never silently rounded.

    Refused with ValueError: more than 3 decimals (finer than a millime), a negative value, text that
    is not a number, and anything larger than a MoneyField can store. Zero is a valid amount.
    """
    try:
        result = _to_decimal(value)
    except InvalidOperation:
        raise ValueError(_("« %(value)s » n'est pas un montant.") % {"value": value}) from None
    if not result.is_finite():
        raise ValueError(_("« %(value)s » n'est pas un montant.") % {"value": value})
    if result != result.quantize(MILLIME):
        raise ValueError(_("%(value)s DT : au plus 3 décimales (le millime).") % {"value": value})
    if result < 0:
        raise ValueError(_("%(value)s DT : un montant ne peut pas être négatif.") % {"value": value})
    if result > MAX_AMOUNT:
        raise ValueError(_("%(value)s DT : montant trop grand.") % {"value": value})
    return result.quantize(MILLIME)


def line_total(qty: Number, unit_price: Number) -> Decimal:
    """Amount of one document line: quantity × unit price, rounded once."""
    return money(_to_decimal(qty) * _to_decimal(unit_price))


# Between thousands in an amount, as on the printed documents: a narrow no-break space.
THIN_SPACE = " "


def display_money(value: Number) -> str:
    """An amount as people read it in a message: 1 250,000 (a space between thousands, a comma, 3 decimals; D-199).
    The printed documents use the same format (`documents.templatetags.pdf_format.money`)."""
    number = money(value)
    sign = "-" if number < 0 else ""
    whole, _dot, fraction = f"{abs(number):f}".partition(".")
    groups: list[str] = []
    while len(whole) > 3:
        groups.insert(0, whole[-3:])
        whole = whole[:-3]
    groups.insert(0, whole)
    return f"{sign}{THIN_SPACE.join(groups)},{fraction}"


class MoneyField(models.DecimalField[Decimal, Decimal]):
    """An amount in dinars: up to 99 999 999 999.999."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 14)
        kwargs.setdefault("decimal_places", DECIMAL_PLACES)
        super().__init__(*args, **kwargs)


class QuantityField(models.DecimalField[Decimal, Decimal]):
    """A quantity in the product's base unit (kg): up to 999 999 999.999."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        kwargs.setdefault("max_digits", 12)
        kwargs.setdefault("decimal_places", DECIMAL_PLACES)
        super().__init__(*args, **kwargs)
