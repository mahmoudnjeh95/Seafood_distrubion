import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import AuditLog
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.hr import selectors, services
from apps.hr.models import SalaryRecord, SalaryStatus

from .factories import EmployeeFactory

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year

THIS_MONTH = timezone.localdate().replace(day=1)


def test_a_day_on_a_lot_costs_days_times_salary_over_26_rounded_once():
    cost = selectors.employee_cost_for_lot_days

    assert cost("1", "1300.000") == Decimal("50.000")
    assert cost("0.5", "1300.000") == Decimal("25.000")
    # 1250 / 26 = 48.0769...: rounded once, half up, at the end.
    assert cost("1", "1250.000") == Decimal("48.077")
    assert cost("0.25", "1250.000") == Decimal("12.019")
    # Three half days are NOT three rounded half days: no intermediate rounding.
    assert cost("0.75", "1000.000") == Decimal("28.846")
    assert cost(Decimal("1.00"), 0) == Decimal("0.000")


def test_the_employer_contribution_is_the_rate_of_the_gross_rounded_once():
    assert services.employer_contribution("1600.000", "17.07") == Decimal("273.120")
    assert services.employer_contribution("1250.000", "17.07") == Decimal("213.375")
    assert services.employer_contribution("1000.001", "17.07") == Decimal("170.700")


def test_creating_an_employee_gives_a_reference_the_default_rate_and_an_audit_entry():
    organization = EmployeeFactory.create(reference="E-001").organization
    employee = services.create_employee(
        organization=organization, actor=None, name=" Hedi Z. ", monthly_salary=Decimal("1100.000")
    )

    assert (employee.reference, employee.name, employee.cnss_rate) == ("E-002", "Hedi Z.", Decimal("17.07"))
    assert AuditLog.objects.filter(action="employee.created", target_id=str(employee.pk)).exists()


def test_a_duplicate_reference_or_a_login_of_another_organization_is_refused():
    first = EmployeeFactory.create()
    other_login = MembershipFactory.create().user

    with pytest.raises(ValidationError) as error:
        services.create_employee(
            organization=first.organization,
            actor=None,
            reference=first.reference.lower(),
            name="X",
            user=other_login,
        )

    assert set(error.value.message_dict) == {"reference", "user"}


def test_one_login_belongs_to_one_employee():
    first = EmployeeFactory.create()
    membership = MembershipFactory.create(organization=first.organization)
    services.update_employee(employee=first, actor=None, user=membership.user)

    with pytest.raises(ValidationError) as error:
        services.create_employee(organization=first.organization, actor=None, name="Y", user=membership.user)

    assert "user" in error.value.message_dict


def test_generating_a_month_approves_the_salaries_of_active_employees_once():
    organization = EmployeeFactory.create(monthly_salary=Decimal("1600.000")).organization
    EmployeeFactory.create(organization=organization, monthly_salary=Decimal("1250.000"), cnss_rate=Decimal("0"))
    EmployeeFactory.create(organization=organization, is_active=False)
    EmployeeFactory.create(organization=organization, monthly_salary=Decimal("0"))  # the owner, not paid
    EmployeeFactory.create(organization=organization, hire_date=THIS_MONTH + dt.timedelta(days=40))

    created = services.generate_month(organization=organization, actor=None, month=THIS_MONTH + dt.timedelta(days=3))
    again = services.generate_month(organization=organization, actor=None, month=THIS_MONTH)

    assert len(created) == 2
    assert again == []
    first, second = sorted(created, key=lambda record: record.gross, reverse=True)
    assert (first.month, first.status) == (THIS_MONTH, SalaryStatus.APPROVED)
    assert first.approved_at is not None
    assert (first.base_salary, first.gross, first.employer_cnss, first.net) == (
        Decimal("1600.000"),
        Decimal("1600.000"),
        Decimal("273.120"),
        Decimal("1600.000"),
    )
    assert second.employer_cnss == Decimal("0.000")


def test_a_future_month_cannot_be_generated():
    organization = EmployeeFactory.create().organization
    future = (THIS_MONTH + dt.timedelta(days=40)).replace(day=1)

    with pytest.raises(ValidationError) as error:
        services.generate_month(organization=organization, actor=None, month=future)

    assert "month" in error.value.message_dict


def as_draft(record):
    """A salary still a draft: drafts are no longer made (D-228), only the ones of before it are left."""
    SalaryRecord.objects.filter(pk=record.pk).update(status=SalaryStatus.DRAFT, approved_at=None, approved_by=None)
    return selectors.salary_record_of(record.organization, record.pk)


def draft_record(**fields):
    employee = EmployeeFactory.create(monthly_salary=Decimal("1000.000"))
    services.generate_month(organization=employee.organization, actor=None, month=THIS_MONTH)
    record = as_draft(selectors.salary_records_of(employee.organization).get())
    if fields:
        record = services.update_salary_record(record=record, actor=None, **fields)
    return record


def test_an_approved_salary_is_adjusted_then_paid():
    employee = EmployeeFactory.create(monthly_salary=Decimal("1000.000"))
    services.generate_month(organization=employee.organization, actor=None, month=THIS_MONTH)
    record = selectors.salary_records_of(employee.organization).get()
    with pytest.raises(ValidationError):  # approved: no direct change
        services.update_salary_record(record=record, actor=None, bonus="10.000")

    services.add_adjustment(record=record, actor=None, amount="-100.000", reason="Retard")
    services.record_payment(
        organization=employee.organization,
        actor=None,
        employee=employee,
        paid_on=timezone.localdate(),
        amount="900.000",
        method="cash",
        allocations=[{"salary_record": record, "amount": "900.000"}],
    )

    assert selectors.unpaid_by_employee(employee.organization) == {}


def test_a_draft_can_be_deleted_and_regenerated():
    record = draft_record()

    services.delete_salary_record(record=record, actor=None)

    assert not selectors.salary_records_of(record.organization).exists()
    assert len(services.generate_month(organization=record.organization, actor=None, month=THIS_MONTH)) == 1


def test_approving_the_month_approves_every_draft():
    employee = EmployeeFactory.create()
    EmployeeFactory.create(organization=employee.organization)
    services.generate_month(organization=employee.organization, actor=None, month=THIS_MONTH)
    for record in selectors.salary_records_of(employee.organization):
        as_draft(record)

    approved = services.approve_month(organization=employee.organization, actor=None, month=THIS_MONTH)

    assert len(approved) == 2
    expense = selectors.monthly_personnel_expense(employee.organization, month=THIS_MONTH)
    assert expense == Decimal("1300.000") * 2 + Decimal("221.910") * 2


def test_the_payroll_summary_expense_includes_adjustments_like_the_month_figure():
    record = draft_record(bonus="100.000")
    services.approve_salary_record(record=record, actor=None)
    services.add_adjustment(record=record, actor=None, amount="-30.000", reason="Absence")
    organization = record.organization

    summary = selectors.payroll_summary(organization, month=THIS_MONTH)

    assert summary.expense == selectors.monthly_personnel_expense(organization, month=THIS_MONTH)
    assert summary.expense == record.expense_amount - Decimal("30.000")


def approved(record):
    return services.approve_salary_record(record=record, actor=None)


def test_a_payment_settles_salaries_and_the_unpaid_amount_falls():
    record = approved(draft_record())  # net 1000.000
    organization, employee = record.organization, record.employee

    payment = services.record_payment(
        organization=organization,
        actor=None,
        employee=employee,
        paid_on=timezone.localdate(),
        amount="400.000",
        method="cash",
        allocations=[{"salary_record": record, "amount": "400.000"}],
    )

    assert payment.number == f"PS-{YEAR}-0001"
    assert selectors.unpaid_by_employee(organization) == {employee.pk: Decimal("600.000")}
    summary = selectors.payroll_summary(organization, month=THIS_MONTH)
    assert (summary.paid, summary.outstanding, summary.unpaid_total, summary.unpaid_records) == (
        Decimal("400.000"),
        Decimal("600.000"),
        Decimal("600.000"),
        1,
    )
    # The rest, with an advance on top: 600 allocated, 50 kept as an advance.
    services.record_payment(
        organization=organization,
        actor=None,
        employee=employee,
        paid_on=timezone.localdate(),
        amount="650.000",
        method="transfer",
        reference="VIR-1",
        allocations=[{"salary_record": record, "amount": "600.000"}],
    )
    assert selectors.unpaid_by_employee(organization) == {}
    last = selectors.payments_of(organization).first()
    assert last is not None
    assert selectors.unallocated_amount(last) == Decimal("50.000")


def test_allocations_are_checked_like_supplier_payments():
    record = approved(draft_record())
    other = approved(_another_draft(record.organization))
    kwargs: dict[str, Any] = {
        "organization": record.organization,
        "actor": None,
        "employee": record.employee,
        "paid_on": timezone.localdate(),
        "method": "cash",
    }

    with pytest.raises(ValidationError) as error:
        services.record_payment(
            **kwargs,
            amount="100.000",
            allocations=[
                {"salary_record": other, "amount": "10.000"},
                {"salary_record": record, "amount": "1000.001"},
            ],
        )
    assert set(error.value.message_dict) == {"allocations.0.salary_record", "allocations.1.amount"}

    with pytest.raises(ValidationError) as error:
        services.record_payment(
            **kwargs, amount="100.000", allocations=[{"salary_record": record, "amount": "150.000"}]
        )
    assert "allocations" in error.value.message_dict

    with pytest.raises(ValidationError) as error:
        services.record_payment(
            **{**kwargs, "paid_on": timezone.localdate() + dt.timedelta(days=1)}, amount="0", allocations=[]
        )
    assert set(error.value.message_dict) == {"paid_on", "amount"}


def _another_draft(organization):
    employee = EmployeeFactory.create(organization=organization)
    services.generate_month(organization=organization, actor=None, month=THIS_MONTH)
    return as_draft(selectors.salary_records_of(organization, employee_id=employee.pk).get())


def test_a_draft_cannot_be_paid_and_an_advance_is_allocated_later():
    record = draft_record()
    kwargs: dict[str, Any] = {"organization": record.organization, "actor": None, "employee": record.employee}
    today = timezone.localdate()

    with pytest.raises(ValidationError):
        services.record_payment(
            **kwargs,
            paid_on=today,
            amount="10.000",
            method="cash",
            allocations=[{"salary_record": record, "amount": "10.000"}],
        )

    advance = services.record_payment(**kwargs, paid_on=today, amount="300.000", method="cash")
    services.approve_salary_record(record=record, actor=None)
    services.allocate_payment(payment=advance, actor=None, allocations=[{"salary_record": record, "amount": "300.000"}])

    assert selectors.unpaid_by_employee(record.organization) == {record.employee_id: Decimal("700.000")}
    with pytest.raises(ValidationError):  # nothing left to allocate
        services.allocate_payment(
            payment=advance, actor=None, allocations=[{"salary_record": record, "amount": "1.000"}]
        )


def test_days_on_a_lot_keep_their_cost_and_cap_a_day_at_one():
    employee = EmployeeFactory.create(monthly_salary=Decimal("1250.000"))
    today = timezone.localdate()
    kwargs: dict[str, Any] = {
        "organization": employee.organization,
        "actor": None,
        "employee": employee,
        "work_date": today,
    }

    morning = services.add_lot_work_day(**kwargs, days="0.5")
    services.update_employee(employee=employee, actor=None, monthly_salary=Decimal("1500.000"))

    assert (morning.cost, morning.monthly_salary) == (Decimal("24.038"), Decimal("1250.000"))
    afternoon = services.add_lot_work_day(**kwargs, days="0.5", notes="Tri")
    assert afternoon.cost == Decimal("28.846")
    with pytest.raises(ValidationError) as error:
        services.add_lot_work_day(**kwargs, days="0.25")
    assert "days" in error.value.message_dict
    for bad in ("0", "1.5", "0.333", "abc"):
        with pytest.raises(ValidationError):
            services.add_lot_work_day(**{**kwargs, "work_date": today - dt.timedelta(days=1)}, days=bad)

    services.delete_lot_work_day(work_day=morning, actor=None)
    assert selectors.lot_work_days_of(employee.organization).count() == 1


# ---- The employee's own CNSS (D-119) ----


def test_the_employee_cnss_is_withheld_from_the_gross_and_shown_on_its_own_line():
    employee = EmployeeFactory.create(monthly_salary=Decimal("1000.000"), employee_cnss_rate=Decimal("9.18"))

    services.generate_month(organization=employee.organization, actor=None, month=THIS_MONTH)
    record = selectors.salary_records_of(employee.organization).get()

    # 1000.000 x 9.18 % = 91.800 withheld; the employer's 17.07 % is on top and not in the net.
    assert (record.gross, record.employee_cnss_rate, record.employee_cnss) == (
        Decimal("1000.000"),
        Decimal("9.18"),
        Decimal("91.800"),
    )
    assert (record.deductions, record.net) == (Decimal("0.000"), Decimal("908.200"))
    assert record.expense_amount == Decimal("1170.700")  # gross + employer 170.700: unchanged by D-119


def test_other_deductions_come_off_after_the_cnss_and_the_rate_can_be_changed_on_a_draft():
    employee = EmployeeFactory.create(monthly_salary=Decimal("1000.000"), employee_cnss_rate=Decimal("9.18"))
    services.generate_month(organization=employee.organization, actor=None, month=THIS_MONTH)
    record = as_draft(selectors.salary_records_of(employee.organization).get())

    changed = services.update_salary_record(
        record=record, actor=None, bonus="100.000", deductions="50.000", employee_cnss_rate="10"
    )

    # Gross 1100.000, own CNSS 10 % = 110.000, advance 50.000: the employee receives 940.000.
    assert (changed.gross, changed.employee_cnss, changed.deductions, changed.net) == (
        Decimal("1100.000"),
        Decimal("110.000"),
        Decimal("50.000"),
        Decimal("940.000"),
    )
    with pytest.raises(ValidationError) as error:
        services.update_salary_record(record=changed, actor=None, employee_cnss_rate="100.5")
    assert "employee_cnss_rate" in error.value.message_dict


def test_a_new_employee_gets_the_provisional_default_rate_and_the_payroll_summary_adds_it_up():
    # Its own organization: the other factories' employees would add to the month's totals.
    employee = services.create_employee(
        organization=OrganizationFactory.create(), actor=None, name="Nouvelle", monthly_salary="2000.000"
    )
    assert employee.employee_cnss_rate == Decimal("9.18")

    services.generate_month(organization=employee.organization, actor=None, month=THIS_MONTH)
    summary = selectors.payroll_summary(employee.organization, month=THIS_MONTH)

    assert (summary.employee_cnss, summary.net) == (Decimal("183.600"), Decimal("1816.400"))
