"""A cash expense at or above the legal cash limit is kept but flagged (D-311, P11-T11)."""

import pytest
from django.utils import timezone

from apps.expenses import services
from apps.expenses.api.serializers import ExpenseSerializer
from apps.expenses.models import ExpensePaymentMethod

pytestmark = pytest.mark.django_db


def flagged(expense):
    return ExpenseSerializer(expense, context={}).data["cash_over_limit"]


@pytest.mark.parametrize(
    ("amount", "method", "expected"),
    [
        ("4999.999", ExpensePaymentMethod.CASH, False),
        ("5000.000", ExpensePaymentMethod.CASH, True),
        ("8000.000", ExpensePaymentMethod.TRANSFER, False),
    ],
)
def test_cash_at_or_above_the_limit_is_flagged(organization, actor, fuel, amount, method, expected):
    expense = services.create_expense(
        organization=organization,
        actor=actor,
        spent_on=timezone.localdate(),
        category=fuel,
        amount=amount,
        payment_method=method,
    )

    assert flagged(expense) is expected
