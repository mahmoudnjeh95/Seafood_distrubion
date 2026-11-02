"""The arithmetic of an invoice (D-057): no database."""

from decimal import Decimal

from apps.sales.invoicing import LineInput, compute, shared_by

D = Decimal
STAMP = D("1.000")


def line(amount: str, rate: str = "19.00", unit_price: str = "0.000") -> LineInput:
    return LineInput(amount=D(amount), vat_rate=D(rate), unit_price=D(unit_price))


def test_the_sample_invoice_with_vat_on_top():
    """docs/spec/sample/sample-invoice.md: 531.000 without VAT, 19 %, stamp 1.000 → 632.890."""
    result = compute(
        [line("210.000", unit_price="42.000"), line("245.000"), line("76.000")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=None,
    )

    assert result.total_excl_tax == D("531.000")
    assert result.vat_total == D("100.890")
    assert result.total_incl_tax == D("632.890")
    assert result.net_to_pay == D("632.890")
    assert [(g.rate, g.base, g.amount) for g in result.vat_groups] == [(D("19.00"), D("531.000"), D("100.890"))]
    assert sum(r.vat_amount for r in result.lines) == D("100.890")
    assert result.lines[0].unit_price_excl_tax == D("42.000")


def test_vat_is_rounded_once_per_rate_half_up_to_the_millime():
    # Per rate: 20.015 × 19 % = 3.80285 → 3.803. Per line it would be 1.901 + 1.901 + 0.001 = 3.803 here, but
    # only the rate's total is rounded; the lines share it.
    result = compute(
        [line("10.005"), line("10.005"), line("0.005")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=None,
    )

    assert result.vat_total == D("3.803")  # 20.015 × 0.19 = 3.80285 → 3.803
    assert sum(r.vat_amount for r in result.lines) == D("3.803")
    assert all(r.amount_incl_tax == r.amount_excl_tax + r.vat_amount for r in result.lines)


def test_prices_including_vat_take_the_vat_out():
    result = compute(
        [line("119.000"), line("50.000")],
        apply_vat=True,
        prices_include_vat=True,
        fiscal_stamp=STAMP,
        withholding_rate=None,
    )

    # 169.000 / 1.19 = 142.0168... → 142.017; VAT = 169.000 − 142.017 = 26.983
    assert result.total_excl_tax == D("142.017")
    assert result.vat_total == D("26.983")
    # What the customer was charged stays: 169.000 + the stamp.
    assert result.total_incl_tax == D("170.000")
    assert sum(r.amount_incl_tax for r in result.lines) == D("169.000")
    assert sum(r.amount_excl_tax for r in result.lines) == D("142.017")


def test_unit_price_without_vat_is_shown_when_prices_include_vat():
    result = compute(
        [line("119.000", unit_price="23.800")],
        apply_vat=True,
        prices_include_vat=True,
        fiscal_stamp=STAMP,
        withholding_rate=None,
    )

    assert result.lines[0].unit_price_excl_tax == D("20.000")


def test_mixed_rates_and_an_exempt_product():
    result = compute(
        [line("100.000", "19.00"), line("100.000", "7.00"), line("80.000", "0.00"), line("50.000", "19.00")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=None,
    )

    groups = {g.rate: (g.base, g.amount) for g in result.vat_groups}
    assert groups == {
        D("19.00"): (D("150.000"), D("28.500")),
        D("7.00"): (D("100.000"), D("7.000")),
        D("0.00"): (D("80.000"), D("0.000")),
    }
    assert [g.rate for g in result.vat_groups] == [D("19.00"), D("7.00"), D("0.00")]
    assert result.vat_total == D("35.500")
    assert result.total_incl_tax == D("366.500")
    assert result.lines[2].vat_amount == D("0.000")


def test_an_invoice_without_vat_adds_nothing():
    result = compute(
        [line("100.000"), line("50.500", "7.00")],
        apply_vat=False,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=None,
    )

    assert result.vat_groups == []
    assert result.vat_total == D("0.000")
    assert result.total_excl_tax == D("150.500")
    assert result.total_incl_tax == D("151.500")
    assert all(r.vat_rate == 0 for r in result.lines)


def test_without_vat_prices_including_vat_stay_as_charged():
    result = compute(
        [line("119.000")], apply_vat=False, prices_include_vat=True, fiscal_stamp=STAMP, withholding_rate=None
    )

    assert result.total_excl_tax == D("119.000")
    assert result.total_incl_tax == D("120.000")


def test_a_typed_vat_amount_replaces_the_computed_one():
    result = compute(
        [line("100.000"), line("33.333")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=None,
        vat_overrides={D("19.00"): D("25.000")},
    )

    group = result.vat_groups[0]
    assert group.computed_amount == D("25.333")
    assert group.amount == D("25.000")
    assert group.overridden
    assert result.vat_total == D("25.000")
    assert sum(r.vat_amount for r in result.lines) == D("25.000")
    assert result.total_incl_tax == D("159.333")


def test_a_typed_vat_amount_with_prices_including_vat_moves_the_base():
    result = compute(
        [line("119.000")],
        apply_vat=True,
        prices_include_vat=True,
        fiscal_stamp=STAMP,
        withholding_rate=None,
        vat_overrides={D("19.00"): D("18.000")},
    )

    assert result.total_excl_tax == D("101.000")
    assert result.vat_total == D("18.000")
    assert result.total_incl_tax == D("120.000")


def test_a_typed_vat_amount_above_the_lines_is_refused():
    result = compute(
        [line("10.000")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=None,
        vat_overrides={D("19.00"): D("10.001")},
    )

    assert result.refused_overrides == {D("19.00"): "too_high"}
    assert result.vat_total == D("1.900")


def test_withholding_is_taken_on_the_amount_with_vat_without_the_stamp():
    result = compute(
        [line("1000.000")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=D("1.50"),
    )

    # (1000 + 190) × 1.5 % = 17.850
    assert result.withholding_amount == D("17.850")
    assert result.total_incl_tax == D("1191.000")
    assert result.net_to_pay == D("1173.150")


def test_a_zero_withholding_rate_withholds_nothing():
    result = compute(
        [line("1000.000")], apply_vat=True, prices_include_vat=False, fiscal_stamp=STAMP, withholding_rate=D("0")
    )

    assert result.withholding_amount == D("0.000")
    assert result.net_to_pay == result.total_incl_tax


def test_the_withholding_starts_at_1000_dt_with_tax():
    """Owner rule: an invoice whose total with tax reaches 1 000 DT carries the withholding, one below none."""
    below = compute(
        [line("998.999", rate="0")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=D("1.50"),
    )
    assert below.total_incl_tax == D("999.999")
    assert below.withholding_amount == D("0.000")

    at = compute(
        [line("999.000", rate="0")],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=STAMP,
        withholding_rate=D("1.50"),
    )
    assert at.total_incl_tax == D("1000.000")
    assert at.withholding_amount == D("14.985")  # 999.000 × 1.5 %


def test_shared_by_adds_up_and_survives_zero():
    assert shared_by(D("10.000"), [D("1"), D("1"), D("1")]) == [D("3.333"), D("3.333"), D("3.334")]
    assert shared_by(D("5.000"), [D("0"), D("0")]) == [D("0.000"), D("0.000")]
    assert shared_by(D("5.000"), []) == []
