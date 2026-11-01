from decimal import Decimal

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel
from apps.core.money import MoneyField

# Provisional (D-055): the employer rate of the sample data (`docs/spec/sample/employees.csv`), 17.07 %.
DEFAULT_EMPLOYER_CNSS_RATE = Decimal("17.07")
# Provisional (D-119): the employee's own CNSS contribution, withheld from the gross salary, 9.18 %. To be confirmed
# by the accountant, like the employer rate.
DEFAULT_EMPLOYEE_CNSS_RATE = Decimal("9.18")


class Employee(OrganizationScopedModel, TimeStampedModel):
    """A person paid a fixed monthly salary (Q6). Day labourers are not employees (P5-T03).

    No fixed truck (D-042): the truck of a driver is chosen per day. `user` is the login of a driver or
    office member, when there is one.
    """

    # "E-001", "E-002"... given by `services.create_employee` when not typed.
    reference = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    position = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    hire_date = models.DateField(null=True, blank=True)
    # Gross monthly salary in DT. Also the base of the cost of a day on a lot: days × salary / 26 (D-041).
    monthly_salary = MoneyField()
    cnss_number = models.CharField(max_length=30, blank=True)
    # Employer contribution in percent of the gross salary (two decimals).
    cnss_rate = models.DecimalField(max_digits=5, decimal_places=2, default=DEFAULT_EMPLOYER_CNSS_RATE)
    # The employee's own contribution in percent of the gross salary: withheld, so it lowers what they receive.
    employee_cnss_rate = models.DecimalField(max_digits=5, decimal_places=2, default=DEFAULT_EMPLOYEE_CNSS_RATE)
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="employee"
    )
    notes = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "reference"], name="employee_reference_unique_per_organization"
            ),
            models.CheckConstraint(condition=models.Q(monthly_salary__gte=0), name="employee_salary_not_negative"),
            models.CheckConstraint(
                condition=models.Q(cnss_rate__gte=0) & models.Q(cnss_rate__lte=100), name="employee_cnss_rate_percent"
            ),
            models.CheckConstraint(
                condition=models.Q(employee_cnss_rate__gte=0) & models.Q(employee_cnss_rate__lte=100),
                name="employee_own_cnss_rate_percent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.name}"


class SalaryStatus(models.TextChoices):
    # Typed, still changing, not an expense yet.
    DRAFT = "draft", _("Brouillon")
    # Final: the month's expense. Only adjustments and payments follow.
    APPROVED = "approved", _("Approuvée")


class SalaryRecord(OrganizationScopedModel, TimeStampedModel):
    """One employee's salary for one month. Approved, it is the month's personnel expense and immutable;
    a correction is a `SalaryAdjustment`. What is paid is a separate record (`SalaryPayment`)."""

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="salary_records")
    # First day of the month.
    month = models.DateField()
    base_salary = MoneyField()
    bonus = MoneyField(default=Decimal("0.000"))
    overtime = MoneyField(default=Decimal("0.000"))
    # Advances recovered, absences...: lowers what the employee receives, not the cost to the company. The
    # employee's own CNSS is not in here: it has its own line (`employee_cnss`).
    deductions = MoneyField(default=Decimal("0.000"))
    # The rate used, kept so that a later change of the employee's rate leaves this month alone.
    cnss_rate = models.DecimalField(max_digits=5, decimal_places=2)
    # base + bonus + overtime.
    gross = MoneyField()
    # Employer contribution: gross × rate, rounded once. Paid to the CNSS, not to the employee.
    employer_cnss = MoneyField()
    # The employee's own contribution, withheld from the gross: gross × rate, rounded once (D-119). The rate is
    # kept like the employer's, and can be changed on a draft. Records approved before D-119 have 0.
    employee_cnss_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("0.00"))
    employee_cnss = MoneyField(default=Decimal("0.000"))
    # What the employee receives: gross − employee CNSS − deductions.
    net = MoneyField()
    status = models.CharField(max_length=20, choices=SalaryStatus.choices, default=SalaryStatus.DRAFT)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-month", "employee__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "employee", "month"], name="one_salary_per_month"),
            models.CheckConstraint(condition=models.Q(net__gte=0), name="salary_net_not_negative"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.name} · {self.month:%Y-%m}"

    @property
    def expense_amount(self) -> Decimal:
        """The cost to the company: gross salary plus the employer contribution (D-055)."""
        return self.gross + self.employer_cnss


class SalaryAdjustmentKind(models.TextChoices):
    ADJUSTMENT = "adjustment", _("Ajustement")
    # Owner point 13 (D-234): an amount added to what is due for the month, with its reason. Always positive.
    PRIME = "prime", _("Prime")


class SalaryAdjustment(OrganizationScopedModel, TimeStampedModel):
    """A correction of an approved salary: signed amount (positive = more due to the employee), with a
    reason. The record itself never changes (ARCHITECTURE §4.5). A prime is a positive one (D-234)."""

    salary_record = models.ForeignKey(SalaryRecord, on_delete=models.PROTECT, related_name="adjustments")
    amount = MoneyField()
    kind = models.CharField(
        max_length=20, choices=SalaryAdjustmentKind.choices, default=SalaryAdjustmentKind.ADJUSTMENT
    )
    reason = models.CharField(max_length=200)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["salary_record", "id"]
        constraints = [models.CheckConstraint(condition=~models.Q(amount=0), name="salary_adjustment_not_zero")]

    def __str__(self) -> str:
        return f"{self.salary_record} · {self.amount}"


class SalaryPaymentMethod(models.TextChoices):
    CASH = "cash", _("Espèces")
    CHEQUE = "cheque", _("Chèque")
    TRANSFER = "transfer", _("Virement")
    OTHER = "other", _("Autre")


class SalaryPaymentKind(models.TextChoices):
    SALARY = "salary", _("Salaire")
    # An advance on the month's salary: allocated to that month's record in full (D-234, provisional kind code).
    ADVANCE = "advance", _("Avance sur salaire")


# The treasury movement a salary payment writes (D-234): `source` and `source_id` of the movement.
TREASURY_SOURCE = "hr.salary_payment"


class SalaryPayment(OrganizationScopedModel, TimeStampedModel):
    """Cash paid to an employee (a salary, an advance): separate from the expense, allocated to approved
    salary records. What is not allocated is an advance. A recorded payment is never edited. Each one writes
    one outgoing treasury movement (D-234)."""

    # "PS-0001"... per organization ("paiement de salaire").
    number = models.CharField(max_length=20)
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="payments")
    paid_on = models.DateField()
    amount = MoneyField()
    kind = models.CharField(max_length=10, choices=SalaryPaymentKind.choices, default=SalaryPaymentKind.SALARY)
    method = models.CharField(max_length=20, choices=SalaryPaymentMethod.choices)
    reference = models.CharField(max_length=50, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-paid_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="salary_payment_number_unique"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="salary_payment_amount_positive"),
        ]

    def __str__(self) -> str:
        return self.number


class SalaryPaymentAllocation(OrganizationScopedModel, TimeStampedModel):
    payment = models.ForeignKey(SalaryPayment, on_delete=models.PROTECT, related_name="allocations")
    salary_record = models.ForeignKey(SalaryRecord, on_delete=models.PROTECT, related_name="allocations")
    amount = MoneyField()
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["payment", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="salary_allocation_positive")]

    def __str__(self) -> str:
        return f"{self.payment} → {self.salary_record}"


class PaymentCounter(OrganizationScopedModel):
    """The last salary payment number given in an organization for one year (0 = the numbers before D-120, which
    had no year), locked while a number is taken."""

    year = models.PositiveIntegerField(default=0)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "year"], name="one_salary_payment_counter_per_year")
        ]

    def __str__(self) -> str:
        return f"{self.organization} · {self.year} · {self.last_number}"


class LotWorkDay(OrganizationScopedModel, TimeStampedModel):
    """An employee worked part of a day on a lot: its cost is days × monthly salary / 26 (D-041).

    The cost is kept as it was when typed (snapshot, ARCHITECTURE §4.4): a later raise does not rewrite a
    lot already costed. The lot is optional: without one it is time not charged to a lot.
    """

    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="lot_work_days")
    work_date = models.DateField()
    # By name, not by import (ARCHITECTURE §3); read through `inventory.selectors.batch_of`.
    batch = models.ForeignKey("inventory.Batch", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # Fraction of a day: 0.25, 0.5, 1.
    days = models.DecimalField(max_digits=4, decimal_places=2)
    monthly_salary = MoneyField()
    cost = MoneyField()
    notes = models.CharField(max_length=200, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-work_date", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(days__gt=0) & models.Q(days__lte=1), name="lot_work_day_range"),
        ]

    def __str__(self) -> str:
        return f"{self.employee.name} · {self.work_date} · {self.days}"
