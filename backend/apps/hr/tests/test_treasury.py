"""Salary payments in the treasury, advances and primes (D-234)."""

from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.hr import selectors, services
from apps.hr.models import (
    TREASURY_SOURCE,
    SalaryAdjustment,
    SalaryAdjustmentKind,
    SalaryPayment,
    SalaryPaymentKind,
)
from apps.treasury.models import AccountKind, TreasuryMovement

from .factories import EmployeeFactory

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
THIS_MONTH = TODAY.replace(day=1)


def approved_salary(net: str = "1000.000"):
    """An approved salary of `net` (no employee's own CNSS: the factory's rate is 0), for this month."""
    employee = EmployeeFactory.create(monthly_salary=Decimal(net))
    services.generate_month(organization=employee.organization, actor=None, month=THIS_MONTH)
    return selectors.salary_records_of(employee.organization).get()


def pay(record, amount: str, method: str = "cash", **extra: Any):
    return services.record_payment(
        organization=record.organization,
        actor=None,
        employee=record.employee,
        paid_on=TODAY,
        amount=amount,
        method=method,
        allocations=[{"salary_record": record, "amount": amount}],
        **extra,
    )


def movements_of_salaries():
    return TreasuryMovement.objects.filter(source=TREASURY_SOURCE)


def test_a_cash_salary_payment_writes_one_outgoing_movement_on_the_caisse():
    record = approved_salary()

    payment = pay(record, "400.000")

    row = movements_of_salaries().get()
    assert (row.source_id, row.amount, row.kind, row.day) == (payment.pk, Decimal("-400.000"), "salary", TODAY)
    assert (row.account.kind, row.account.is_default) == (AccountKind.CASH, True)
    assert row.label == f"Salaire : {record.employee.name}"
    assert row.reference == payment.number


def test_a_bank_payment_leaves_the_main_bank_account():
    record = approved_salary()

    pay(record, "250.000", method="transfer")

    row = movements_of_salaries().get()
    assert (row.amount, row.account.kind, row.account.is_default) == (Decimal("-250.000"), AccountKind.BANK, True)


def test_the_backfill_never_counts_a_salary_payment_twice():
    record = approved_salary()
    payment = pay(record, "400.000")
    assert selectors.payment_debit(payment) is not None

    # A payment recorded before the accounts has no movement: the backfill writes it, then leaves it alone.
    movements_of_salaries().delete()
    assert selectors.payment_debit(payment) is None
    services.post_treasury_history(organization=record.organization)
    services.post_treasury_history(organization=record.organization)

    assert movements_of_salaries().count() == 1
    assert selectors.payment_debit(payment) == {"amount": "400.000", "account": "Caisse", "day": TODAY}


def test_an_advance_is_allocated_to_the_month_and_reduces_what_is_still_due():
    record = approved_salary("1000.000")
    employee = record.employee

    advance = pay(record, "300.000", kind=SalaryPaymentKind.ADVANCE)

    assert advance.kind == SalaryPaymentKind.ADVANCE
    assert selectors.unpaid_by_employee(record.organization) == {employee.pk: Decimal("700.000")}
    assert movements_of_salaries().get().label == f"Avance : {employee.name}"


def test_an_advance_above_what_is_due_is_refused_unless_the_office_confirms():
    record = approved_salary("1000.000")
    organization = record.organization

    with pytest.raises(ValidationError) as error:
        pay(record, "1200.000", kind=SalaryPaymentKind.ADVANCE)

    assert "allocations.0.amount" in error.value.message_dict
    assert not SalaryPayment.objects.filter(organization=organization).exists()
    assert not movements_of_salaries().exists()

    pay(record, "1200.000", kind=SalaryPaymentKind.ADVANCE, confirm_overpay=True)

    assert selectors.unpaid_by_employee(organization) == {}
    assert movements_of_salaries().count() == 1


def add_prime(record, amount: str = "150.000", method: str = "cash", reason: str = "Prime de rendement"):
    return services.add_prime(record=record, actor=None, amount=amount, reason=reason, method=method, paid_on=TODAY)


def test_a_prime_raises_what_is_due_and_is_paid_on_the_day_it_is_added():
    record = approved_salary("1000.000")
    organization = record.organization

    add_prime(record)

    fresh = selectors.salary_record_of(organization, record.pk)
    assert selectors.due_amount(fresh) == Decimal("1150.000")
    # The prime is paid with its own payment: only the salary itself is still owed.
    assert selectors.unpaid_by_employee(organization) == {record.employee_id: Decimal("1000.000")}
    prime = fresh.adjustments.get()
    assert (prime.kind, prime.reason) == (SalaryAdjustmentKind.PRIME, "Prime de rendement")
    payment = SalaryPayment.objects.get()
    assert (payment.kind, payment.amount, payment.method) == (SalaryPaymentKind.PRIME, Decimal("150.000"), "cash")
    assert [(line.salary_record_id, line.amount) for line in payment.allocations.all()] == [
        (record.pk, Decimal("150.000"))
    ]


def test_a_prime_paid_in_cash_leaves_the_caisse_under_its_own_label():
    record = approved_salary("1000.000")

    add_prime(record)

    payment = SalaryPayment.objects.get()
    row = movements_of_salaries().get()
    assert (row.source_id, row.amount, row.kind, row.day) == (payment.pk, Decimal("-150.000"), "salary", TODAY)
    assert (row.account.kind, row.account.is_default) == (AccountKind.CASH, True)
    assert row.label == f"Prime : {record.employee.name}"
    assert row.reference == payment.number


def test_a_prime_paid_by_transfer_leaves_the_main_bank_account():
    record = approved_salary("1000.000")

    add_prime(record, method="transfer")

    row = movements_of_salaries().get()
    assert (row.amount, row.account.kind, row.account.is_default) == (Decimal("-150.000"), AccountKind.BANK, True)


def test_a_prime_is_positive_and_needs_a_reason():
    record = approved_salary("1000.000")

    with pytest.raises(ValidationError) as error:
        add_prime(record, amount="-10.000")
    assert "amount" in error.value.message_dict

    with pytest.raises(ValidationError) as error:
        add_prime(record, reason="  ")
    assert "reason" in error.value.message_dict

    assert not SalaryAdjustment.objects.exists()
    assert not SalaryPayment.objects.exists()


def test_a_prime_with_an_unknown_method_is_refused_and_adds_nothing():
    record = approved_salary("1000.000")

    with pytest.raises(ValidationError) as error:
        add_prime(record, method="bitcoin")

    assert "method" in error.value.message_dict
    assert not record.adjustments.exists()
    assert not SalaryPayment.objects.exists()
    assert not movements_of_salaries().exists()
