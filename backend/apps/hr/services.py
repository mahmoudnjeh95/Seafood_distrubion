"""Every write on employees, salaries and days on a lot goes through these functions (ARCHITECTURE §3)."""

import datetime as dt
from collections.abc import Sequence
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit, numbering
from apps.core.models import Membership, Organization, User
from apps.core.money import MAX_AMOUNT, Number, checked_amount, display_money, money

from . import selectors
from .models import (
    DEFAULT_EMPLOYEE_CNSS_RATE,
    DEFAULT_EMPLOYER_CNSS_RATE,
    Employee,
    LotWorkDay,
    SalaryAdjustment,
    SalaryPayment,
    SalaryPaymentAllocation,
    SalaryPaymentMethod,
    SalaryRecord,
    SalaryStatus,
)
from .selectors import employee_cost_for_lot_days as employee_cost_for_lot_days  # re-exported

if TYPE_CHECKING:
    from apps.inventory.models import Batch

ZERO = Decimal("0.000")
HUNDREDTH = Decimal("0.01")


def first_of_month(day: dt.date) -> dt.date:
    return day.replace(day=1)


def _last_of_month(first: dt.date) -> dt.date:
    return (first + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)


def employer_contribution(gross: Number, rate: Number) -> Decimal:
    """The employer's CNSS contribution: gross × rate % rounded once to the millime (D-055)."""
    return money(Decimal(gross) * Decimal(rate) / 100)


def employee_contribution(gross: Number, rate: Number) -> Decimal:
    """The employee's own CNSS contribution, withheld from the gross: gross × rate % rounded once (D-119)."""
    return money(Decimal(gross) * Decimal(rate) / 100)


# ---- Employees ----


class EmployeeFields(TypedDict, total=False):
    reference: str
    name: str
    position: str
    phone: str
    hire_date: dt.date | None
    monthly_salary: Number
    cnss_number: str
    cnss_rate: Number
    employee_cnss_rate: Number
    user: User | None
    notes: str


def _employee_snapshot(employee: Employee) -> dict[str, Any]:
    return {
        "reference": employee.reference,
        "name": employee.name,
        "position": employee.position,
        "phone": employee.phone,
        "hire_date": employee.hire_date.isoformat() if employee.hire_date else None,
        "monthly_salary": str(employee.monthly_salary),
        "cnss_number": employee.cnss_number,
        "cnss_rate": str(employee.cnss_rate),
        "employee_cnss_rate": str(employee.employee_cnss_rate),
        "user": employee.user.username if employee.user else None,
        "is_active": employee.is_active,
    }


def _clean_employee(employee: Employee) -> None:
    errors: dict[str, str] = {}
    for field in ("reference", "name", "position", "phone", "cnss_number", "notes"):
        setattr(employee, field, getattr(employee, field).strip())
    others = Employee.objects.for_organization(employee.organization).exclude(pk=employee.pk)
    if not employee.reference:
        errors["reference"] = _("La référence est obligatoire.")
    elif others.filter(reference__iexact=employee.reference).exists():
        errors["reference"] = _("Un autre employé porte déjà cette référence.")
    if not employee.name:
        errors["name"] = _("Le nom est obligatoire.")
    try:
        employee.monthly_salary = checked_amount(employee.monthly_salary)
    except (ValueError, TypeError, InvalidOperation):
        errors["monthly_salary"] = _("Indiquez un salaire en DT, au millime près.")
    try:
        rate = Decimal(employee.cnss_rate)
        if rate != rate.quantize(HUNDREDTH) or not Decimal(0) <= rate <= Decimal(100):
            raise ValueError
        employee.cnss_rate = rate.quantize(HUNDREDTH)
    except (ValueError, TypeError, InvalidOperation):
        errors["cnss_rate"] = _("Le taux doit être entre 0 et 100 %, avec au plus 2 décimales.")
    try:
        own = Decimal(employee.employee_cnss_rate)
        if own != own.quantize(HUNDREDTH) or not Decimal(0) <= own <= Decimal(100):
            raise ValueError
        employee.employee_cnss_rate = own.quantize(HUNDREDTH)
    except (ValueError, TypeError, InvalidOperation):
        errors["employee_cnss_rate"] = _("Le taux doit être entre 0 et 100 %, avec au plus 2 décimales.")
    if employee.user is not None:
        user = employee.user
        if not Membership.objects.filter(user=user, organization=employee.organization, is_active=True).exists():
            errors["user"] = _("Cet utilisateur n'appartient pas à la société.")
        elif others.filter(user=user).exists():
            errors["user"] = _("Cet utilisateur est déjà lié à un autre employé.")
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def create_employee(*, organization: Organization, actor: User | None, **fields: Unpack[EmployeeFields]) -> Employee:
    """A new employee. Without a reference it gets the next free `E-NNN`; the CNSS rate defaults to 17.07 %."""
    Organization.objects.select_for_update().filter(pk=organization.pk).first()  # one reference at a time
    values: dict[str, Any] = {
        "cnss_rate": DEFAULT_EMPLOYER_CNSS_RATE,
        "employee_cnss_rate": DEFAULT_EMPLOYEE_CNSS_RATE,
        "monthly_salary": ZERO,
        **fields,
    }
    employee = Employee(organization=organization, **values)
    if not employee.reference.strip():
        employee.reference = numbering.next_free_reference(
            organization, "employee", Employee.objects.for_organization(organization)
        )
    _clean_employee(employee)
    employee.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="employee.created",
        target=employee,
        after=_employee_snapshot(employee),
    )
    return employee


@transaction.atomic
def update_employee(*, employee: Employee, actor: User | None, **fields: Unpack[EmployeeFields]) -> Employee:
    """Change an employee. A new salary applies to the months generated afterwards: salary records and days on
    a lot already typed keep theirs (ARCHITECTURE §4.4)."""
    employee = (
        Employee.objects.select_for_update(of=("self",)).select_related("user", "organization").get(pk=employee.pk)
    )
    before = _employee_snapshot(employee)
    for field, value in fields.items():
        setattr(employee, field, value)
    _clean_employee(employee)
    employee.save()
    after = _employee_snapshot(employee)
    if after != before:
        audit.record(
            organization=employee.organization,
            actor=actor,
            action="employee.updated",
            target=employee,
            before=before,
            after=after,
        )
    return employee


@transaction.atomic
def set_employee_active(*, employee: Employee, actor: User | None, is_active: bool) -> Employee:
    """An archived employee keeps their history but gets no new salary record."""
    employee = Employee.objects.select_for_update(of=("self",)).select_related("organization").get(pk=employee.pk)
    if employee.is_active != is_active:
        employee.is_active = is_active
        employee.save(update_fields=["is_active", "updated_at"])
        audit.record(
            organization=employee.organization,
            actor=actor,
            action="employee.restored" if is_active else "employee.archived",
            target=employee,
        )
    return employee


# ---- Salary records ----


def _amount(value: Any, errors: dict[str, str], field: str) -> Decimal:
    try:
        return checked_amount(value)
    except (ValueError, TypeError, InvalidOperation):
        errors[field] = _("Indiquez un montant en DT, au millime près.")
        return ZERO


def _figures(
    *, base: Decimal, bonus: Decimal, overtime: Decimal, deductions: Decimal, rate: Decimal, employee_rate: Decimal
) -> tuple[Decimal, Decimal, Decimal, Decimal]:
    """(gross, employer contribution, employee contribution, net) of a month. The net is what the employee
    receives: gross − their own CNSS − the other deductions (D-119)."""
    gross = base + bonus + overtime
    own = employee_contribution(gross, employee_rate)
    return gross, employer_contribution(gross, rate), own, gross - own - deductions


def _record_snapshot(record: SalaryRecord) -> dict[str, Any]:
    return {
        "employee": record.employee.reference,
        "month": record.month.isoformat(),
        "base_salary": str(record.base_salary),
        "bonus": str(record.bonus),
        "overtime": str(record.overtime),
        "deductions": str(record.deductions),
        "cnss_rate": str(record.cnss_rate),
        "employee_cnss_rate": str(record.employee_cnss_rate),
        "gross": str(record.gross),
        "employer_cnss": str(record.employer_cnss),
        "employee_cnss": str(record.employee_cnss),
        "net": str(record.net),
        "status": record.status,
        "notes": record.notes,
    }


@transaction.atomic
def generate_month(*, organization: Organization, actor: User | None, month: dt.date) -> list[SalaryRecord]:
    """Create the salary records of a month for every active employee who has none yet, approved (D-228).

    The base is each employee's monthly salary today; an employee hired after the month, or without a salary,
    is left out. Running it twice creates nothing the second time. Returns the records created.
    """
    month = first_of_month(month)
    if month > first_of_month(timezone.localdate()):
        raise ValidationError({"month": _("Le mois ne peut pas être dans le futur.")})
    Organization.objects.select_for_update().filter(pk=organization.pk).first()  # one generation at a time
    existing = set(
        SalaryRecord.objects.for_organization(organization).filter(month=month).values_list("employee_id", flat=True)
    )
    last_day = _last_of_month(month)
    created: list[SalaryRecord] = []
    for employee in selectors.employees_of(organization, status="active"):
        if employee.pk in existing or employee.monthly_salary <= 0:
            continue
        if employee.hire_date is not None and employee.hire_date > last_day:
            continue
        gross, cnss, own, net = _figures(
            base=employee.monthly_salary,
            bonus=ZERO,
            overtime=ZERO,
            deductions=ZERO,
            rate=employee.cnss_rate,
            employee_rate=employee.employee_cnss_rate,
        )
        record = SalaryRecord.objects.create(
            organization=organization,
            employee=employee,
            month=month,
            base_salary=employee.monthly_salary,
            cnss_rate=employee.cnss_rate,
            employee_cnss_rate=employee.employee_cnss_rate,
            gross=gross,
            employer_cnss=cnss,
            employee_cnss=own,
            net=net,
            # Approved by default (D-228): adjusted by an adjustment, then paid. A draft is only left from before.
            status=SalaryStatus.APPROVED,
            approved_at=timezone.now(),
            approved_by=actor,
            created_by=actor,
        )
        created.append(record)
    audit.record(
        organization=organization,
        actor=actor,
        action="salary.month_generated",
        after={"month": month.isoformat(), "employees": [record.employee.reference for record in created]},
    )
    return created


class SalaryFields(TypedDict, total=False):
    base_salary: Number
    bonus: Number
    overtime: Number
    deductions: Number
    cnss_rate: Number
    employee_cnss_rate: Number
    notes: str


def _locked_draft(record: SalaryRecord) -> SalaryRecord:
    locked = (
        SalaryRecord.objects.select_for_update(of=("self",))
        .select_related("employee", "organization")
        .get(pk=record.pk)
    )
    if locked.status != SalaryStatus.DRAFT:
        raise ValidationError({"status": _("Une paie approuvée ne change plus : corrigez-la par un ajustement.")})
    return locked


@transaction.atomic
def update_salary_record(*, record: SalaryRecord, actor: User | None, **fields: Unpack[SalaryFields]) -> SalaryRecord:
    """Change a draft: base, bonus, overtime, deductions, rate, notes. Gross, contribution and net are recomputed."""
    record = _locked_draft(record)
    before = _record_snapshot(record)
    errors: dict[str, str] = {}
    values = {
        name: _amount(fields[name], errors, name) if name in fields else getattr(record, name)
        for name in ("base_salary", "bonus", "overtime", "deductions")
    }
    rate = record.cnss_rate
    if "cnss_rate" in fields:
        try:
            rate = Decimal(fields["cnss_rate"])
            if rate != rate.quantize(HUNDREDTH) or not Decimal(0) <= rate <= Decimal(100):
                raise ValueError
        except (ValueError, TypeError, InvalidOperation):
            errors["cnss_rate"] = _("Le taux doit être entre 0 et 100 %, avec au plus 2 décimales.")
    own_rate = record.employee_cnss_rate
    if "employee_cnss_rate" in fields:
        try:
            own_rate = Decimal(fields["employee_cnss_rate"])
            if own_rate != own_rate.quantize(HUNDREDTH) or not Decimal(0) <= own_rate <= Decimal(100):
                raise ValueError
        except (ValueError, TypeError, InvalidOperation):
            errors["employee_cnss_rate"] = _("Le taux doit être entre 0 et 100 %, avec au plus 2 décimales.")
    gross, cnss, own, net = _figures(
        base=values["base_salary"],
        bonus=values["bonus"],
        overtime=values["overtime"],
        deductions=values["deductions"],
        rate=rate,
        employee_rate=own_rate,
    )
    if net < 0 and not errors:
        errors["deductions"] = _("Les retenues dépassent le salaire brut.")
    if errors:
        raise ValidationError(errors)
    record.base_salary, record.bonus = values["base_salary"], values["bonus"]
    record.overtime, record.deductions = values["overtime"], values["deductions"]
    record.cnss_rate = rate.quantize(HUNDREDTH, rounding=ROUND_HALF_UP)
    record.employee_cnss_rate = own_rate.quantize(HUNDREDTH, rounding=ROUND_HALF_UP)
    record.gross, record.employer_cnss, record.net = gross, cnss, net
    record.employee_cnss = own
    if "notes" in fields:
        record.notes = fields["notes"].strip()
    record.save()
    audit.record(
        organization=record.organization,
        actor=actor,
        action="salary.updated",
        target=record,
        before=before,
        after=_record_snapshot(record),
    )
    return record


@transaction.atomic
def delete_salary_record(*, record: SalaryRecord, actor: User | None) -> None:
    """Delete a draft (it was generated by mistake). An approved salary is never deleted."""
    record = _locked_draft(record)
    audit.record(
        organization=record.organization,
        actor=actor,
        action="salary.deleted",
        target=record,
        before=_record_snapshot(record),
    )
    record.delete()


@transaction.atomic
def approve_salary_record(*, record: SalaryRecord, actor: User | None) -> SalaryRecord:
    """Approve a draft: it becomes the month's personnel expense and no longer changes."""
    record = _locked_draft(record)
    before = _record_snapshot(record)
    record.status = SalaryStatus.APPROVED
    record.approved_at = timezone.now()
    record.approved_by = actor
    record.save(update_fields=["status", "approved_at", "approved_by", "updated_at"])
    audit.record(
        organization=record.organization,
        actor=actor,
        action="salary.approved",
        target=record,
        before=before,
        after=_record_snapshot(record),
    )
    return record


@transaction.atomic
def approve_month(*, organization: Organization, actor: User | None, month: dt.date) -> list[SalaryRecord]:
    """Approve every draft of a month at once. Returns the records approved."""
    drafts = SalaryRecord.objects.for_organization(organization).filter(
        month=first_of_month(month), status=SalaryStatus.DRAFT
    )
    return [approve_salary_record(record=record, actor=actor) for record in drafts.order_by("id")]


@transaction.atomic
def add_adjustment(*, record: SalaryRecord, actor: User | None, amount: Number, reason: str) -> SalaryAdjustment:
    """Correct an approved salary with a signed amount (positive: more is due) and a reason."""
    record = (
        SalaryRecord.objects.select_for_update(of=("self",))
        .select_related("employee", "organization")
        .get(pk=record.pk)
    )
    errors: dict[str, str] = {}
    if record.status != SalaryStatus.APPROVED:
        errors["status"] = _("Seule une paie approuvée reçoit un ajustement : modifiez le brouillon.")
    value = ZERO
    try:
        value = Decimal(amount)
        if value != value.quantize(Decimal("0.001")) or value == 0 or abs(value) > MAX_AMOUNT:
            raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        errors["amount"] = _("Indiquez un montant en DT, au millime près, différent de zéro.")
    reason = reason.strip()
    if not reason:
        errors["reason"] = _("Le motif est obligatoire.")
    if not errors:
        if selectors.due_amount(record) + value < 0:
            errors["amount"] = _("L'ajustement ferait passer le salaire sous zéro.")
        elif _remaining(record) + value < 0:
            errors["amount"] = _("L'ajustement ferait passer le salaire sous ce qui est déjà payé.")
    if errors:
        raise ValidationError(errors)
    adjustment = SalaryAdjustment.objects.create(
        organization=record.organization, salary_record=record, amount=value, reason=reason, created_by=actor
    )
    audit.record(
        organization=record.organization,
        actor=actor,
        action="salary.adjusted",
        target=record,
        after={"adjustment": str(value), "reason": reason},
    )
    return adjustment


# ---- Salary payments ----


class AllocationFields(TypedDict):
    salary_record: SalaryRecord
    amount: Number


def allocation_error_key(index: int, field: str) -> str:
    """Errors of an allocation are reported on `allocations.<index>.<field>`, like supplier payments."""
    return f"allocations.{index}.{field}"


def _remaining(record: SalaryRecord) -> Decimal:
    paid = SalaryPaymentAllocation.objects.filter(salary_record=record).aggregate(total=Sum("amount"))["total"]
    adjusted = SalaryAdjustment.objects.filter(salary_record=record).aggregate(total=Sum("amount"))["total"]
    return record.net + (adjusted or ZERO) - (paid or ZERO)


def _checked_allocations(
    organization: Organization,
    employee: Employee,
    allocations: Sequence[AllocationFields],
    available: Decimal | None,
    errors: dict[str, str],
) -> list[tuple[SalaryRecord, Decimal]]:
    ids = sorted({line["salary_record"].pk for line in allocations})
    records = {
        record.pk: record
        for record in SalaryRecord.objects.select_for_update()
        .select_related("employee")
        .filter(pk__in=ids)
        .order_by("id")
    }
    checked: list[tuple[SalaryRecord, Decimal]] = []
    seen: set[int] = set()
    for index, line in enumerate(allocations):
        record = records.get(line["salary_record"].pk)
        key = allocation_error_key(index, "salary_record")
        if record is None or record.organization_id != organization.pk:
            errors[key] = _("Paie inconnue.")
            continue
        if record.employee_id != employee.pk:
            errors[key] = _("Cette paie est d'un autre employé.")
            continue
        if record.pk in seen:
            errors[key] = _("Cette paie est déjà dans la liste.")
            continue
        seen.add(record.pk)
        if record.status != SalaryStatus.APPROVED:
            errors[key] = _("Cette paie est un brouillon : approuvez-la avant de la payer.")
            continue
        amount_key = allocation_error_key(index, "amount")
        try:
            value: Any = line.get("amount", "")
            amount = checked_amount(value)
        except (ValueError, TypeError, InvalidOperation):
            errors[amount_key] = _("Indiquez un montant en DT, au millime près.")
            continue
        if amount == 0:
            errors[amount_key] = _("Le montant doit être supérieur à zéro.")
            continue
        remaining = _remaining(record)
        if amount > remaining:
            errors[amount_key] = _("Il ne reste que %(remaining)s DT à payer sur cette paie.") % {
                "remaining": display_money(max(remaining, ZERO))
            }
            continue
        checked.append((record, amount))
    allocated = sum((amount for _record, amount in checked), ZERO)
    if available is not None and allocated > available:
        errors["allocations"] = _(
            "Les affectations (%(allocated)s DT) dépassent le montant disponible (%(available)s DT)."
        ) % {"allocated": display_money(allocated), "available": display_money(available)}
    return checked


def _payment_snapshot(payment: SalaryPayment) -> dict[str, Any]:
    allocations = SalaryPaymentAllocation.objects.filter(payment=payment).select_related("salary_record")
    return {
        "number": payment.number,
        "employee": payment.employee.reference,
        "paid_on": payment.paid_on.isoformat(),
        "amount": str(payment.amount),
        "method": payment.method,
        "reference": payment.reference,
        "allocations": [
            {"month": line.salary_record.month.isoformat(), "amount": str(line.amount)}
            for line in allocations.order_by("id")
        ],
    }


def _allocate(payment: SalaryPayment, actor: User | None, allocations: Sequence[tuple[SalaryRecord, Decimal]]) -> None:
    for record, amount in allocations:
        SalaryPaymentAllocation.objects.create(
            organization_id=payment.organization_id,
            payment=payment,
            salary_record=record,
            amount=amount,
            created_by=actor,
        )


@transaction.atomic
def record_payment(
    *,
    organization: Organization,
    actor: User | None,
    employee: Employee,
    paid_on: dt.date,
    amount: Number,
    method: str,
    allocations: Sequence[AllocationFields] = (),
    reference: str = "",
    notes: str = "",
) -> SalaryPayment:
    """Record cash paid to an employee and the approved salaries it settles (all, part, or none: an advance)."""
    errors: dict[str, str] = {}
    if employee.organization_id != organization.pk:
        errors["employee"] = _("Employé inconnu.")
    if paid_on > timezone.localdate():
        errors["paid_on"] = _("La date du paiement ne peut pas être dans le futur.")
    if method not in SalaryPaymentMethod.values:
        errors["method"] = _("Mode de paiement inconnu.")
    checked: Decimal | None = None
    try:
        checked = checked_amount(amount)
        if checked == 0:
            checked = None
            errors["amount"] = _("Le montant doit être supérieur à zéro.")
    except (ValueError, TypeError, InvalidOperation):
        errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    allocated = (
        _checked_allocations(organization, employee, allocations, checked, errors) if "employee" not in errors else []
    )
    if errors:
        raise ValidationError(errors)
    assert checked is not None  # an amount error would have been raised above
    payment = SalaryPayment.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "salary_payment"),
        employee=employee,
        paid_on=paid_on,
        amount=checked,
        method=method,
        reference=reference.strip(),
        notes=notes.strip(),
        created_by=actor,
    )
    _allocate(payment, actor, allocated)
    audit.record(
        organization=organization,
        actor=actor,
        action="salary_payment.recorded",
        target=payment,
        after=_payment_snapshot(payment),
    )
    return payment


@transaction.atomic
def allocate_payment(
    *, payment: SalaryPayment, actor: User | None, allocations: Sequence[AllocationFields]
) -> SalaryPayment:
    """Allocate the part of a payment not allocated yet (an advance) to approved salaries of its employee."""
    payment = (
        SalaryPayment.objects.select_for_update(of=("self",))
        .select_related("employee", "organization")
        .get(pk=payment.pk)
    )
    errors: dict[str, str] = {}
    if not allocations:
        errors["allocations"] = _("Choisissez au moins une paie.")
    already = SalaryPaymentAllocation.objects.filter(payment=payment).aggregate(total=Sum("amount"))["total"]
    available = payment.amount - (already or ZERO)
    checked = _checked_allocations(payment.organization, payment.employee, allocations, available, errors)
    if errors:
        raise ValidationError(errors)
    before = _payment_snapshot(payment)
    _allocate(payment, actor, checked)
    audit.record(
        organization=payment.organization,
        actor=actor,
        action="salary_payment.allocated",
        target=payment,
        before=before,
        after=_payment_snapshot(payment),
    )
    return payment


# ---- Days on a lot ----


@transaction.atomic
def add_lot_work_day(
    *,
    organization: Organization,
    actor: User | None,
    employee: Employee,
    work_date: dt.date,
    days: Number,
    batch: "Batch | None" = None,
    notes: str = "",
) -> LotWorkDay:
    """Record that an employee worked `days` (a fraction of a day, at most 1 per day in all) on a lot.

    The cost is days × monthly salary / 26 with the salary of today, kept on the entry (D-041).
    """
    errors: dict[str, str] = {}
    employee = Employee.objects.select_for_update().get(pk=employee.pk)
    if employee.organization_id != organization.pk:
        errors["employee"] = _("Employé inconnu.")
    elif not employee.is_active:
        errors["employee"] = _("Cet employé est archivé.")
    if batch is not None and batch.organization_id != organization.pk:
        errors["batch"] = _("Lot inconnu.")
    if work_date > timezone.localdate():
        errors["work_date"] = _("La date ne peut pas être dans le futur.")
    value = ZERO
    try:
        value = Decimal(days)
        if value != value.quantize(HUNDREDTH) or not Decimal(0) < value <= Decimal(1):
            raise ValueError
    except (ValueError, TypeError, InvalidOperation):
        errors["days"] = _("Indiquez une fraction de jour supérieure à 0 et au plus 1 (0,5 = une demi-journée).")
    if not errors:
        worked = LotWorkDay.objects.filter(employee=employee, work_date=work_date).aggregate(total=Sum("days"))
        already = worked["total"] or Decimal(0)
        if already + value > 1:
            errors["days"] = _("Cet employé a déjà %(days)s jour(s) ce jour-là : au plus 1 jour en tout.") % {
                "days": already
            }
    if errors:
        raise ValidationError(errors)
    work_day = LotWorkDay.objects.create(
        organization=organization,
        employee=employee,
        work_date=work_date,
        batch=batch,
        days=value,
        monthly_salary=employee.monthly_salary,
        cost=employee_cost_for_lot_days(value, employee.monthly_salary),
        notes=notes.strip(),
        created_by=actor,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="lot_work_day.created",
        target=work_day,
        after={
            "employee": employee.reference,
            "work_date": work_date.isoformat(),
            "batch": batch.number if batch is not None else None,
            "days": str(value),
            "cost": str(work_day.cost),
        },
    )
    return work_day


@transaction.atomic
def delete_lot_work_day(*, work_day: LotWorkDay, actor: User | None) -> None:
    """Remove a mistaken entry. Provisional (D-055): allowed until lots are closed (Phase 6)."""
    work_day = (
        LotWorkDay.objects.select_for_update(of=("self",))
        .select_related("employee", "organization")
        .get(pk=work_day.pk)
    )
    audit.record(
        organization=work_day.organization,
        actor=actor,
        action="lot_work_day.deleted",
        target=work_day,
        before={
            "employee": work_day.employee.reference,
            "work_date": work_day.work_date.isoformat(),
            "days": str(work_day.days),
            "cost": str(work_day.cost),
        },
    )
    work_day.delete()
