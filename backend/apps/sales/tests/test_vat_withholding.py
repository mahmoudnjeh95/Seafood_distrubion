"""A public buyer keeps part of the VAT on invoices of 1 000 DT and more (D-313, P11-T09)."""

from decimal import Decimal

from apps.sales import invoicing

D = Decimal


def amounts(total, *, vat_withholding_rate):
    return invoicing.compute(
        [invoicing.LineInput(amount=D(total), vat_rate=D("19.00"))],
        apply_vat=True,
        prices_include_vat=False,
        fiscal_stamp=D("1.000"),
        withholding_rate=D("1.00"),
        vat_withholding_rate=vat_withholding_rate,
    )


def test_a_public_buyer_keeps_a_quarter_of_the_vat_and_the_retenue():
    result = amounts("1000.000", vat_withholding_rate=D("25.00"))

    # 1 000 HT + 190 TVA + 1 timbre = 1 191 ; retenue 1 % de 1 190 = 11,900 ; 25 % de 190 = 47,500.
    assert result.total_incl_tax == D("1191.000")
    assert result.withholding_amount == D("11.900")
    assert result.vat_withholding_amount == D("47.500")
    assert result.net_to_pay == D("1131.600")


def test_any_other_customer_keeps_no_vat():
    result = amounts("1000.000", vat_withholding_rate=None)

    assert result.vat_withholding_amount == D("0.000")
    assert result.net_to_pay == D("1179.100")


def test_below_1000_dt_nothing_is_kept():
    result = amounts("800.000", vat_withholding_rate=D("25.00"))

    assert (result.withholding_amount, result.vat_withholding_amount) == (D("0.000"), D("0.000"))
    assert result.net_to_pay == result.total_incl_tax
