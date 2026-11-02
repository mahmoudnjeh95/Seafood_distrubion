"""The cash of a driver (D-262): the fund the office hands out leaves the Caisse for the driver's cash, the cash counted
at the approval goes back, and a port purchase paid in cash leaves the driver's cash the day of the purchase."""

import datetime as dt
from decimal import Decimal

import pytest
from django.db.models import Sum

from apps.core.tests.factories import MembershipFactory, UserFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import services as purchasing
from apps.treasury import services
from apps.treasury.models import AccountKind, TreasuryMovement

pytestmark = pytest.mark.django_db

DAY = dt.date(2026, 11, 2)
D = Decimal


@pytest.fixture
def organization():
    return MembershipFactory.create().organization


@pytest.fixture
def driver():
    return UserFactory.create()


def balance(organization, account):
    return TreasuryMovement.objects.filter(organization=organization, account=account).aggregate(total=Sum("amount"))[
        "total"
    ] or D("0")


def accounts(organization, driver):
    return services.default_account(organization, AccountKind.CASH), services.driver_account(organization, driver)


def fund(organization, driver, given):
    services.sync_driver_fund(
        organization=organization, actor=None, driver=driver, day=DAY, given=D(given), source_id=7
    )


def test_the_fund_leaves_the_caisse_for_the_drivers_cash(organization, driver):
    fund(organization, driver, "150.000")

    caisse, cash = accounts(organization, driver)
    assert balance(organization, cash) == D("150.000")
    assert balance(organization, caisse) == D("-150.000")


def test_changing_the_money_for_purchases_moves_only_the_difference(organization, driver):
    fund(organization, driver, "150.000")
    fund(organization, driver, "400.000")
    fund(organization, driver, "400.000")
    fund(organization, driver, "100.000")

    caisse, cash = accounts(organization, driver)
    assert balance(organization, cash) == D("100.000")
    assert balance(organization, caisse) == D("-100.000")


def test_the_counted_cash_goes_back_to_the_caisse(organization, driver):
    fund(organization, driver, "150.000")

    services.hand_over_driver_cash(
        organization=organization, actor=None, driver=driver, day=DAY, amount=D("120.000"), source_id=3
    )

    caisse, cash = accounts(organization, driver)
    assert balance(organization, cash) == D("30.000")
    assert balance(organization, caisse) == D("-30.000")


def test_a_day_approved_again_after_a_new_load_hands_over_what_is_counted_then(organization, driver):
    fund(organization, driver, "100.000")
    services.hand_over_driver_cash(
        organization=organization, actor=None, driver=driver, day=DAY, amount=D("100.000"), source_id=3
    )
    services.hand_over_driver_cash(
        organization=organization, actor=None, driver=driver, day=DAY, amount=D("80.000"), source_id=3
    )

    caisse, cash = accounts(organization, driver)
    assert balance(organization, cash) == D("-80.000")
    assert balance(organization, caisse) == D("80.000")


def test_cash_paid_at_the_port_leaves_the_drivers_cash_the_day_of_the_purchase(organization, driver):
    supplier = SupplierFactory.create(organization=organization)
    payment = purchasing.record_payment(
        organization=organization,
        actor=None,
        supplier=supplier,
        paid_on=DAY,
        amount=D("60.000"),
        method="cash",
        allocations=[],
        driver=driver,
        movement_kind="field_purchase",
    )

    row = TreasuryMovement.objects.get(source="purchasing.payment_line", source_id=payment.lines.get().pk)
    assert row.account == services.driver_account(organization, driver)
    assert (row.kind, row.day, row.amount) == ("field_purchase", DAY, D("-60.000"))
