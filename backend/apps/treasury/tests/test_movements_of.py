"""Where the money of a record went (P9-T09c, D-242): the movements one source wrote for the given records, each with
the account it went through."""

import datetime as dt
from decimal import Decimal

import pytest

from apps.core.tests.factories import MembershipFactory
from apps.treasury import selectors, services
from apps.treasury.models import AccountKind

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return MembershipFactory.create().organization


def test_the_movements_of_the_given_records_come_with_their_account(organization):
    caisse = services.create_account(organization=organization, actor=None, kind=AccountKind.CASH, name="Caisse test")
    day = dt.date(2026, 10, 30)
    services.post_movement(
        organization=organization,
        account=caisse,
        day=day,
        amount=Decimal("50.000"),
        kind="sale_cash",
        label="BL-1",
        source="sales.sale",
        source_id=7,
    )
    services.post_movement(
        organization=organization,
        account=caisse,
        day=day,
        amount=Decimal("20.000"),
        kind="sale_cash",
        label="BL-2",
        source="sales.sale",
        source_id=8,
    )

    rows = list(selectors.movements_of(organization, source="sales.sale", source_ids=[7]))

    assert [(row.source_id, row.amount, row.account) for row in rows] == [(7, Decimal("50.000"), caisse)]


def test_another_source_or_organization_shows_nothing(organization):
    caisse = services.create_account(organization=organization, actor=None, kind=AccountKind.CASH, name="Caisse B")
    services.post_movement(
        organization=organization,
        account=caisse,
        day=dt.date(2026, 10, 30),
        amount=Decimal("5.000"),
        kind="expense",
        label="DEP-1",
        source="expenses.expense",
        source_id=3,
    )
    other = MembershipFactory.create().organization

    assert list(selectors.movements_of(organization, source="sales.sale", source_ids=[3])) == []
    assert list(selectors.movements_of(other, source="expenses.expense", source_ids=[3])) == []
