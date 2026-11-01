"""Reusable read queries of employees, salaries and days on a lot (P5-T04)."""

import datetime as dt
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Literal

from django.db.models import Prefetch, Q, QuerySet, Sum

from apps.core.models import Organization
from apps.core.money import Number, money
from apps.treasury import selectors as treasury

from .models import (
    TREASURY_SOURCE,
    Employee,
    LotWorkDay,
    SalaryAdjustment,
    SalaryPayment,
    SalaryPaymentAllocation,
    SalaryRecord,
    SalaryStatus,
)

type EmployeeStatus = Literal["active", "archived", "all"]

ZERO = Decimal("0.000")
# The client's rule (2026-10-11, D-041): a day is a 26th of the monthly salary.
WORKING_DAYS_PER_MONTH = 26


def employee_cost_for_lot_days(days: Number, monthly_salary: Number) -> Decimal:
    """What `days` worked on a lot cost: days × monthly salary / 26, rounded once to the millime (D-041).

    Pure: no database, no rounding of the intermediate values.
    """
    return money(Decimal(days) * Decimal(monthly_salary) / WORKING_DAYS_PER_MONTH)


# ---- Employees ----


def employees_of(
    organization: Organization, *, search: str = "", status: EmployeeStatus = "active"
) -> QuerySet[Employee]:
    employees = Employee.objects.for_organization(organization).select_related("user").order_by("name", "id")
    if status == "active":
        employees = employees.filter(is_active=True)
    elif status == "archived":
        employees = employees.filter(is_active=False)
    if search := search.strip():
        employees = employees.filter(
            Q(name__icontains=search)
            | Q(reference__icontains=search)
            | Q(position__icontains=search)
            | Q(phone__icontains=search)
        )
    return employees


def employee_of(organization: Organization, employee_id: int) -> Employee:
    """One employee. Raises Employee.DoesNotExist outside the organization."""
    return employees_of(organization, status="all").get(pk=employee_id)


# ---- Salary records ----


def salary_records_of(
    organization: Organization,
    *,
    month: dt.date | None = None,
    employee_id: int | None = None,
    status: str = "",
) -> QuerySet[SalaryRecord]:
    """Salary records, newest month first, each with its payments and adjustments loaded."""
    records = (
        SalaryRecord.objects.for_organization(organization)
        .select_related("employee")
        .prefetch_related(
            Prefetch(
                "allocations",
                queryset=SalaryPaymentAllocation.objects.select_related("payment").order_by("id"),
            )
        )
        .prefetch_related(Prefetch("adjustments", queryset=SalaryAdjustment.objects.order_by("id")))
    )
    if month is not None:
        records = records.filter(month=month.replace(day=1))
    if employee_id is not None:
        records = records.filter(employee_id=employee_id)
    if status:
        records = records.filter(status=status)
    return records


def salary_record_of(organization: Organization, record_id: int) -> SalaryRecord:
    """One salary record. Raises SalaryRecord.DoesNotExist outside the organization."""
    return salary_records_of(organization).get(pk=record_id)


def adjustments_total(record: SalaryRecord) -> Decimal:
    return sum((adjustment.amount for adjustment in record.adjustments.all()), ZERO)


def due_amount(record: SalaryRecord) -> Decimal:
    """What the employee must receive: net plus the signed adjustments."""
    return record.net + adjustments_total(record)


def paid_amount(record: SalaryRecord) -> Decimal:
    return sum((allocation.amount for allocation in record.allocations.all()), ZERO)


def outstanding_amount(record: SalaryRecord) -> Decimal:
    """What is still to pay on an approved salary; a draft is not owed yet."""
    if record.status != SalaryStatus.APPROVED:
        return ZERO
    return max(due_amount(record) - paid_amount(record), ZERO)


def unpaid_by_employee(organization: Organization) -> dict[int, Decimal]:
    """Still to pay per employee on approved salaries (what the "unpaid" badges show)."""
    result: dict[int, Decimal] = {}
    for record in salary_records_of(organization, status=SalaryStatus.APPROVED):
        left = outstanding_amount(record)
        if left > 0:
            result[record.employee_id] = result.get(record.employee_id, ZERO) + left
    return result


@dataclass(frozen=True)
class PayrollSummary:
    month: dt.date
    records: int
    drafts: int
    gross: Decimal
    employer_cnss: Decimal
    employee_cnss: Decimal
    net: Decimal
    # The month's personnel expense: approved records only (gross + employer contribution + adjustments).
    expense: Decimal
    paid: Decimal
    outstanding: Decimal
    # Over every month: approved salaries not fully paid.
    unpaid_total: Decimal
    unpaid_records: int


def payroll_summary(organization: Organization, *, month: dt.date) -> PayrollSummary:
    month = month.replace(day=1)
    records = list(salary_records_of(organization, month=month))
    approved = [record for record in records if record.status == SalaryStatus.APPROVED]
    everything = salary_records_of(organization, status=SalaryStatus.APPROVED)
    unpaid = [left for record in everything if (left := outstanding_amount(record)) > 0]
    return PayrollSummary(
        month=month,
        records=len(records),
        drafts=len(records) - len(approved),
        gross=sum((record.gross for record in records), ZERO),
        employer_cnss=sum((record.employer_cnss for record in records), ZERO),
        employee_cnss=sum((record.employee_cnss for record in records), ZERO),
        net=sum((due_amount(record) for record in records), ZERO),
        expense=sum((record.expense_amount + adjustments_total(record) for record in approved), ZERO),
        paid=sum((paid_amount(record) for record in approved), ZERO),
        outstanding=sum((outstanding_amount(record) for record in approved), ZERO),
        unpaid_total=sum(unpaid, ZERO),
        unpaid_records=len(unpaid),
    )


def monthly_personnel_expense(organization: Organization, *, month: dt.date) -> Decimal:
    """The month's approved salary expense: gross + employer contribution + signed adjustments. This is what the
    expenses module (P5-T01) and the month closing read."""
    month = month.replace(day=1)
    records = salary_records_of(organization, month=month, status=SalaryStatus.APPROVED)
    return sum((record.expense_amount + adjustments_total(record) for record in records), ZERO)


# ---- Salary payments ----


def payments_of(
    organization: Organization, *, employee_id: int | None = None, search: str = ""
) -> QuerySet[SalaryPayment]:
    payments = (
        SalaryPayment.objects.for_organization(organization)
        .select_related("employee")
        .prefetch_related(
            Prefetch(
                "allocations",
                queryset=SalaryPaymentAllocation.objects.select_related("salary_record").order_by("id"),
            )
        )
    )
    if employee_id is not None:
        payments = payments.filter(employee_id=employee_id)
    if search := search.strip():
        payments = payments.filter(
            Q(number__icontains=search) | Q(reference__icontains=search) | Q(employee__name__icontains=search)
        )
    return payments


def payment_of(organization: Organization, payment_id: int) -> SalaryPayment:
    """One salary payment. Raises SalaryPayment.DoesNotExist outside the organization."""
    return payments_of(organization).get(pk=payment_id)


def unallocated_amount(payment: SalaryPayment) -> Decimal:
    """The part of a payment not on a salary record yet (an advance)."""
    return payment.amount - sum((allocation.amount for allocation in payment.allocations.all()), ZERO)


def payment_debit(payment: SalaryPayment) -> dict[str, Any] | None:
    """What left our treasury for this payment: amount, account name, day (D-234). None for a payment recorded
    before the accounts existed, which has no movement: the screens show nothing then."""
    row = treasury.movement_of_source(payment.organization, source=TREASURY_SOURCE, source_id=payment.pk)
    if row is None:
        return None
    return {"amount": str(-row.amount), "account": row.account.name, "day": row.day}


# ---- Days on a lot ----


def lot_work_days_of(
    organization: Organization,
    *,
    employee_id: int | None = None,
    batch_id: int | None = None,
    month: dt.date | None = None,
) -> QuerySet[LotWorkDay]:
    days = LotWorkDay.objects.for_organization(organization).select_related("employee", "batch")
    if employee_id is not None:
        days = days.filter(employee_id=employee_id)
    if batch_id is not None:
        days = days.filter(batch_id=batch_id)
    if month is not None:
        first = month.replace(day=1)
        following = (first + dt.timedelta(days=32)).replace(day=1)
        days = days.filter(work_date__gte=first, work_date__lt=following)
    return days


def lot_work_day_of(organization: Organization, work_day_id: int) -> LotWorkDay:
    """One entry. Raises LotWorkDay.DoesNotExist outside the organization."""
    return lot_work_days_of(organization).get(pk=work_day_id)


def employee_cost_of_lot(organization: Organization, *, batch_id: int) -> Decimal:
    """Employees' cost charged to one lot: the sum of the costs kept on their days (read by Phase 6)."""
    total = LotWorkDay.objects.for_organization(organization).filter(batch_id=batch_id).aggregate(total=Sum("cost"))
    return total["total"] or ZERO


def payments_by_day(organization: Organization, *, date_from: dt.date, date_to: dt.date) -> dict[dt.date, Decimal]:
    """Salary paid per day (`paid_on`), inclusive."""
    rows = (
        SalaryPayment.objects.for_organization(organization)
        .filter(paid_on__gte=date_from, paid_on__lte=date_to)
        .values("paid_on")
        .annotate(total=Sum("amount"))
    )
    return {row["paid_on"]: row["total"] for row in rows}
