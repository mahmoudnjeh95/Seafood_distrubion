import datetime as dt
from decimal import Decimal

import pytest
from django.core.management import call_command
from django.utils import timezone

from apps.core.models import Organization
from apps.hr import selectors

pytestmark = pytest.mark.django_db


def test_the_seed_gives_employees_last_months_payroll_and_days_on_a_lot(settings):
    settings.DEBUG = True

    call_command("seed_dev")
    call_command("seed_dev")  # running it again creates nothing

    organization = Organization.objects.get()
    employees = list(selectors.employees_of(organization))
    assert len(employees) == 7
    sami = next(employee for employee in employees if employee.reference == "E-003")
    assert sami.user is not None
    assert sami.user.username == "driver"

    last_month = (timezone.localdate().replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    records = list(selectors.salary_records_of(organization, month=last_month))
    assert len(records) == 7
    assert all(record.status == "approved" for record in records)
    # What is owed is the net: gross less the employee's own CNSS (D-119), for the two employees left unpaid.
    due = {record.employee.reference: selectors.due_amount(record) for record in records}
    assert sorted(selectors.unpaid_by_employee(organization).values()) == sorted(due[ref] for ref in ("E-007", "E-008"))
    assert all(record.employee_cnss > 0 and record.net < record.gross for record in records)
    this_month = selectors.salary_records_of(organization, month=timezone.localdate())
    assert this_month.count() == 7
    assert all(record.status == "approved" for record in this_month)

    days = list(selectors.lot_work_days_of(organization))
    assert len(days) == 3
    assert sum((day.cost for day in days), Decimal("0")) == Decimal("42.308") + Decimal("18.269") + Decimal("21.154")
