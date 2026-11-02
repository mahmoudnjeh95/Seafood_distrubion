"""The effets that need someone today (P9-T09e, D-254): ours to cash when due, ours to pay a day (cheque) or
fifteen days (traite) before they fall due."""

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.tests.factories import MembershipFactory
from apps.treasury import selectors
from apps.treasury.models import Instrument

pytestmark = pytest.mark.django_db

TODAY = dt.date(2026, 11, 2)


@pytest.fixture
def organization():
    return MembershipFactory.create().organization


def effet(organization, number, *, direction, kind, status, due_in):
    return Instrument.objects.create(
        organization=organization,
        direction=direction,
        kind=kind,
        number=number,
        amount=Decimal("100.000"),
        issued_on=TODAY - dt.timedelta(days=30),
        due_on=TODAY + dt.timedelta(days=due_in),
        status=status,
    )


def numbers(organization):
    return [row.number for row in selectors.due_alerts(organization, today=TODAY)]


def test_a_received_effet_still_to_cash_shows_from_its_due_day(organization):
    effet(organization, "R-late", direction="received", kind="cheque", status="portfolio", due_in=-3)
    effet(organization, "R-today", direction="received", kind="bill", status="deposited", due_in=0)
    effet(organization, "R-later", direction="received", kind="cheque", status="portfolio", due_in=1)

    assert numbers(organization) == ["R-late", "R-today"]


def test_a_received_effet_that_is_cashed_or_unpaid_no_longer_shows(organization):
    effet(organization, "R-cashed", direction="received", kind="cheque", status="cashed", due_in=-3)
    effet(organization, "R-unpaid", direction="received", kind="cheque", status="unpaid", due_in=-3)

    assert numbers(organization) == []


def test_our_cheque_shows_the_day_before_it_falls_due_and_our_traite_fifteen_days_before(organization):
    effet(organization, "C-tomorrow", direction="issued", kind="cheque", status="issued", due_in=1)
    effet(organization, "C-in-two-days", direction="issued", kind="cheque", status="issued", due_in=2)
    effet(organization, "T-in-15", direction="issued", kind="bill", status="issued", due_in=15)
    effet(organization, "T-in-16", direction="issued", kind="bill", status="issued", due_in=16)

    assert numbers(organization) == ["C-tomorrow", "T-in-15"]


def test_our_effet_the_bank_debited_no_longer_shows(organization):
    effet(organization, "C-debited", direction="issued", kind="cheque", status="debited", due_in=0)

    assert numbers(organization) == []


def test_another_organizations_effets_never_show(organization):
    other = MembershipFactory.create().organization
    effet(other, "X-1", direction="received", kind="cheque", status="portfolio", due_in=-1)

    assert numbers(organization) == []
