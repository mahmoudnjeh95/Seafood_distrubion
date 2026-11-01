"""An approved expense is money out of our accounts the day it was spent (P9-T05b, D-237): the driver's cash when the
driver paid in cash, else the Caisse for cash, else the main bank account. Nothing is written before approval."""

from decimal import Decimal

import pytest
from django.utils import timezone

from apps.expenses import services
from apps.treasury.models import AccountKind, TreasuryAccount, TreasuryMovement

pytestmark = pytest.mark.django_db


def spend(organization, actor, cat, amount, **fields):
    fields.setdefault("spent_on", timezone.localdate())
    return services.create_expense(organization=organization, actor=actor, category=cat, amount=amount, **fields)


def movement_of(expense):
    return TreasuryMovement.objects.get(source="expenses.expense", source_id=expense.pk)


def test_an_expense_moves_no_money_until_it_is_approved(organization, actor, fuel):
    spend(organization, actor, fuel, Decimal("12.500"), payment_method="cash")

    assert not TreasuryMovement.objects.filter(source="expenses.expense").exists()


def test_an_approved_cash_expense_leaves_the_caisse_the_day_it_was_spent(organization, actor, fuel):
    expense = spend(organization, actor, fuel, Decimal("12.500"), payment_method="cash")

    services.approve_expense(expense=expense, actor=actor)

    row = movement_of(expense)
    assert row.account.kind == AccountKind.CASH
    assert row.amount == Decimal("-12.500")
    assert row.kind == "expense"
    assert row.day == expense.spent_on


def test_a_cash_expense_the_driver_paid_leaves_the_drivers_cash(organization, actor, fuel):
    expense = spend(organization, actor, fuel, Decimal("7.000"), payment_method="cash")
    # The road path sets the flag after saving the expense.
    expense.paid_by_driver = True
    expense.save(update_fields=["paid_by_driver"])

    services.approve_expense(expense=expense, actor=actor)

    assert movement_of(expense).account.kind == AccountKind.DRIVER


def test_a_transfer_leaves_the_main_bank_account(organization, actor, fuel):
    expense = spend(organization, actor, fuel, Decimal("30.000"), payment_method="transfer")

    services.approve_expense(expense=expense, actor=actor)

    row = movement_of(expense)
    assert row.account.kind == AccountKind.BANK
    assert row.account == TreasuryAccount.objects.get(organization=organization, kind=AccountKind.BANK, is_default=True)


def test_the_history_writes_approved_expenses_once(organization, actor, fuel):
    expense = spend(organization, actor, fuel, Decimal("5.000"), payment_method="cash")
    services.approve_expense(expense=expense, actor=actor)

    services.post_treasury_history(organization=organization)
    services.post_treasury_history(organization=organization)

    assert TreasuryMovement.objects.filter(source="expenses.expense", source_id=expense.pk).count() == 1
