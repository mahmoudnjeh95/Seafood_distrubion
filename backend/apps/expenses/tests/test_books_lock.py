"""A declared month takes no new expense and no money movement (D-315, P11-T16)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core import services as core
from apps.expenses import services
from apps.expenses.models import Expense
from apps.treasury import services as treasury
from apps.treasury.models import AccountKind

pytestmark = pytest.mark.django_db

LAST_MONTH_END = timezone.localdate().replace(day=1) - dt.timedelta(days=1)


def test_an_expense_dated_in_a_locked_month_is_refused(organization, actor, fuel):
    core.set_books_lock(organization=organization, actor=actor, until=LAST_MONTH_END)

    with pytest.raises(ValidationError) as refused:
        services.create_expense(
            organization=organization, actor=actor, spent_on=LAST_MONTH_END, category=fuel, amount="50.000"
        )
    assert set(refused.value.message_dict) == {"spent_on"}
    assert not Expense.objects.exists()

    expense = services.create_expense(
        organization=organization, actor=actor, spent_on=timezone.localdate(), category=fuel, amount="50.000"
    )
    assert expense.amount == Decimal("50.000")


def test_a_money_movement_in_a_locked_month_is_refused(organization, actor):
    core.set_books_lock(organization=organization, actor=actor, until=LAST_MONTH_END)
    treasury.ensure_default_accounts(organization=organization)
    cash = treasury.default_account(organization, AccountKind.CASH)

    with pytest.raises(ValidationError):
        treasury.post_movement(
            organization=organization, account=cash, day=LAST_MONTH_END, amount="10.000", kind="transfer", label="Test"
        )
