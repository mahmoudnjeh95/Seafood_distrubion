from decimal import Decimal

import pytest

from apps.core.money import (
    MoneyField,
    QuantityField,
    checked_amount,
    checked_quantity,
    display_money,
    line_total,
    money,
    quantity,
)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("1.0004", "1.000"),
        ("1.0005", "1.001"),  # half goes up, not to the even neighbour
        ("1.0015", "1.002"),
        ("2.0025", "2.003"),
        ("-1.0005", "-1.001"),  # half goes away from zero
        ("0", "0.000"),
        (12, "12.000"),
        (Decimal("99999999999.9994"), "99999999999.999"),
    ],
)
def test_money_rounds_half_up_to_millimes(value, expected):
    result = money(value)

    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -3


def test_quantity_rounds_half_up_to_grams():
    assert quantity("12.3455") == Decimal("12.346")


@pytest.mark.parametrize("value", [1.5, 0.1 + 0.2, True, None])
def test_floats_and_other_types_are_refused(value):
    with pytest.raises(TypeError):
        money(value)


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("12.345", "12.345"),
        ("12.3450", "12.345"),  # trailing zeros are not extra precision
        (5, "5.000"),
        ("999999999.999", "999999999.999"),
    ],
)
def test_checked_quantity_keeps_valid_weights(value, expected):
    result = checked_quantity(value)

    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -3


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("12.3456", "3 décimales"),  # finer than a gram: refused, not rounded
        ("-1", "négative"),
        ("0", "supérieure à zéro"),
        ("1000000000", "trop grande"),
        ("abc", "pas une quantité"),
        ("NaN", "pas une quantité"),
        ("Infinity", "pas une quantité"),
    ],
)
def test_checked_quantity_refuses_invalid_weights(value, message):
    with pytest.raises(ValueError, match=message):
        checked_quantity(value)


def test_checked_quantity_accepts_zero_only_when_asked():
    # A stock count may find nothing left on a shelf.
    assert checked_quantity("0", allow_zero=True) == Decimal("0.000")


def test_checked_quantity_refuses_floats():
    with pytest.raises(TypeError):
        checked_quantity(1.5)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("value", "expected"), [("34", "34.000"), ("20.5", "20.500"), ("0", "0.000"), (Decimal("5.2"), "5.200")]
)
def test_checked_amount_keeps_valid_amounts(value, expected):
    result = checked_amount(value)

    assert result == Decimal(expected)
    assert result.as_tuple().exponent == -3


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("12.3456", "3 décimales"),  # finer than a millime: refused, not rounded
        ("-1", "négatif"),
        ("100000000000", "trop grand"),
        ("abc", "pas un montant"),
        ("NaN", "pas un montant"),
    ],
)
def test_checked_amount_refuses_invalid_amounts(value, message):
    with pytest.raises(ValueError, match=message):
        checked_amount(value)


def test_line_total_rounds_once_after_multiplying():
    # 2.345 kg at 42.500 DT = 99.6625, which rounds up to 99.663.
    assert line_total("2.345", "42.500") == Decimal("99.663")
    # The product is rounded, not the inputs: rounding 0.3335 first would give 1.002.
    assert line_total("0.3335", "3") == Decimal("1.001")


def test_fields_default_to_three_decimal_places():
    money_field = MoneyField()
    quantity_field = QuantityField()

    assert (money_field.max_digits, money_field.decimal_places) == (14, 3)
    assert (quantity_field.max_digits, quantity_field.decimal_places) == (12, 3)


@pytest.mark.parametrize(
    ("value", "shown"),
    [
        ("0", "0,000"),
        ("12.5", "12,500"),
        ("1250", "1 250,000"),
        ("1234567.891", "1 234 567,891"),
        ("-1250.5", "-1 250,500"),
    ],
)
def test_display_money_groups_thousands_with_three_decimals(value, shown):
    assert display_money(value) == shown
