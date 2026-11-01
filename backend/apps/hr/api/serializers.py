from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.hr import selectors
from apps.hr.models import (
    Employee,
    LotWorkDay,
    SalaryAdjustment,
    SalaryAdjustmentKind,
    SalaryPayment,
    SalaryPaymentAllocation,
    SalaryPaymentKind,
    SalaryPaymentMethod,
    SalaryRecord,
    SalaryStatus,
)

AMOUNT = serializers.DecimalField(max_digits=14, decimal_places=3)


def _name_of(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or str(user.username)


class LoginRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    username = serializers.CharField(read_only=True)


class EmployeeSerializer(serializers.ModelSerializer[Employee]):
    user = serializers.SerializerMethodField()
    # Approved salaries not paid yet, over every month (context `unpaid`).
    unpaid = serializers.SerializerMethodField()

    class Meta:
        model = Employee
        fields = (
            "id",
            "reference",
            "name",
            "position",
            "phone",
            "hire_date",
            "monthly_salary",
            "cnss_number",
            "cnss_rate",
            "employee_cnss_rate",
            "user",
            "notes",
            "unpaid",
            "is_active",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(LoginRefSerializer(allow_null=True))
    def get_user(self, employee: Employee) -> dict[str, Any] | None:
        if employee.user is None:
            return None
        return {"id": employee.user.pk, "username": employee.user.username}

    @extend_schema_field(AMOUNT)
    def get_unpaid(self, employee: Employee) -> str:
        unpaid: dict[int, Decimal] = self.context.get("unpaid", {})
        return str(unpaid.get(employee.pk, Decimal("0.000")))


class EmployeeWriteSerializer(serializers.Serializer[Any]):
    # Empty on creation: the server gives the next E-NNN.
    reference = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=150)
    position = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    hire_date = serializers.DateField(required=False, allow_null=True, default=None)
    monthly_salary = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, required=False, default=Decimal("0"), coerce_to_string=True
    )
    cnss_number = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    # Percent of the gross salary paid by the employer, two decimals.
    cnss_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False, coerce_to_string=True
    )
    # Percent of the gross salary withheld from the employee for their own CNSS (provisional 9.18, D-119).
    employee_cnss_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False, coerce_to_string=True
    )
    # The id of the login of the employee (a driver, for instance), or null.
    user = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)


class EmployeeFilterSerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    status = serializers.ChoiceField(
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")], required=False, default="active"
    )


# ---- Salary records ----


class EmployeeRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    position = serializers.CharField(read_only=True)


class SalaryAdjustmentSerializer(serializers.ModelSerializer[SalaryAdjustment]):
    kind = serializers.ChoiceField(choices=SalaryAdjustmentKind.choices, read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = SalaryAdjustment
        fields = ("id", "kind", "amount", "reason", "created_by", "created_at")
        read_only_fields = fields

    def get_created_by(self, adjustment: SalaryAdjustment) -> str:
        return _name_of(adjustment.created_by)


class TreasuryDebitSerializer(serializers.Serializer[Any]):
    """What a salary payment took out of our treasury (D-234): absent on payments made before the accounts."""

    amount = AMOUNT
    account = serializers.CharField(read_only=True)
    day = serializers.DateField(read_only=True)


class SalaryPaymentRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    paid_on = serializers.DateField(read_only=True)
    kind = serializers.ChoiceField(choices=SalaryPaymentKind.choices, read_only=True)
    method = serializers.ChoiceField(choices=SalaryPaymentMethod.choices, read_only=True)


class RecordPaymentSerializer(serializers.Serializer[Any]):
    """The part of one payment that settled the salary."""

    id = serializers.IntegerField(read_only=True)
    payment = SalaryPaymentRefSerializer(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    treasury_debit = serializers.SerializerMethodField()

    @extend_schema_field(TreasuryDebitSerializer)
    def get_treasury_debit(self, allocation: SalaryPaymentAllocation) -> dict[str, Any] | None:
        return selectors.payment_debit(allocation.payment)


class SalaryRecordSerializer(serializers.ModelSerializer[SalaryRecord]):
    employee = EmployeeRefSerializer(read_only=True)
    status = serializers.ChoiceField(choices=SalaryStatus.choices, read_only=True)
    # gross + employer contribution: the month's expense once approved.
    expense_amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # net plus signed adjustments: what the employee must receive.
    due_amount = serializers.SerializerMethodField()
    paid_amount = serializers.SerializerMethodField()
    outstanding = serializers.SerializerMethodField()
    adjustments = SalaryAdjustmentSerializer(many=True, read_only=True)
    payments = RecordPaymentSerializer(source="allocations", many=True, read_only=True)
    approved_by = serializers.SerializerMethodField()

    class Meta:
        model = SalaryRecord
        fields = (
            "id",
            "employee",
            "month",
            "base_salary",
            "bonus",
            "overtime",
            "deductions",
            "cnss_rate",
            "employee_cnss_rate",
            "gross",
            "employer_cnss",
            "employee_cnss",
            "net",
            "expense_amount",
            "due_amount",
            "paid_amount",
            "outstanding",
            "status",
            "notes",
            "adjustments",
            "payments",
            "approved_at",
            "approved_by",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(AMOUNT)
    def get_due_amount(self, record: SalaryRecord) -> str:
        return str(selectors.due_amount(record))

    @extend_schema_field(AMOUNT)
    def get_paid_amount(self, record: SalaryRecord) -> str:
        return str(selectors.paid_amount(record))

    @extend_schema_field(AMOUNT)
    def get_outstanding(self, record: SalaryRecord) -> str:
        return str(selectors.outstanding_amount(record))

    def get_approved_by(self, record: SalaryRecord) -> str:
        return _name_of(record.approved_by)


class SalaryRecordFilterSerializer(serializers.Serializer[Any]):
    # Any day of the month; the first of it is used.
    month = serializers.DateField(required=False)
    employee = serializers.IntegerField(required=False, min_value=1)
    status = serializers.ChoiceField(choices=SalaryStatus.choices, required=False)


class SalaryRecordUpdateSerializer(serializers.Serializer[Any]):
    base_salary = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, required=False, coerce_to_string=True
    )
    bonus = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, required=False, coerce_to_string=True
    )
    overtime = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, required=False, coerce_to_string=True
    )
    deductions = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=0, required=False, coerce_to_string=True
    )
    cnss_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False, coerce_to_string=True
    )
    # The employee's own CNSS rate for this month (D-119); the amount is recomputed.
    employee_cnss_rate = serializers.DecimalField(
        max_digits=5, decimal_places=2, min_value=0, max_value=100, required=False, coerce_to_string=True
    )
    notes = serializers.CharField(required=False, allow_blank=True, max_length=2000)


class MonthSerializer(serializers.Serializer[Any]):
    # Any day of the month; the first of it is used.
    month = serializers.DateField()


class GeneratedMonthSerializer(serializers.Serializer[Any]):
    month = serializers.DateField(read_only=True)
    created = serializers.IntegerField(read_only=True)
    records = SalaryRecordSerializer(many=True, read_only=True)


class ApprovedMonthSerializer(serializers.Serializer[Any]):
    month = serializers.DateField(read_only=True)
    approved = serializers.IntegerField(read_only=True)


class AdjustmentWriteSerializer(serializers.Serializer[Any]):
    # Signed, as a string ("-20.000"): checked by the service.
    amount = serializers.CharField(allow_blank=True)
    reason = serializers.CharField(max_length=200, allow_blank=True)


class PayrollSummarySerializer(serializers.Serializer[Any]):
    month = serializers.DateField()
    records = serializers.IntegerField()
    drafts = serializers.IntegerField()
    gross = serializers.DecimalField(max_digits=14, decimal_places=3)
    employer_cnss = serializers.DecimalField(max_digits=14, decimal_places=3)
    employee_cnss = serializers.DecimalField(max_digits=14, decimal_places=3)
    net = serializers.DecimalField(max_digits=14, decimal_places=3)
    expense = serializers.DecimalField(max_digits=14, decimal_places=3)
    paid = serializers.DecimalField(max_digits=14, decimal_places=3)
    outstanding = serializers.DecimalField(max_digits=14, decimal_places=3)
    unpaid_total = serializers.DecimalField(max_digits=14, decimal_places=3)
    unpaid_records = serializers.IntegerField()


# ---- Salary payments ----


class SalaryPaymentAllocationSerializer(serializers.ModelSerializer[SalaryPaymentAllocation]):
    month = serializers.DateField(source="salary_record.month", read_only=True)
    salary_record_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = SalaryPaymentAllocation
        fields = ("id", "salary_record_id", "month", "amount")
        read_only_fields = fields


class SalaryPaymentSerializer(serializers.ModelSerializer[SalaryPayment]):
    employee = EmployeeRefSerializer(read_only=True)
    kind = serializers.ChoiceField(choices=SalaryPaymentKind.choices, read_only=True)
    method = serializers.ChoiceField(choices=SalaryPaymentMethod.choices, read_only=True)
    allocations = SalaryPaymentAllocationSerializer(many=True, read_only=True)
    unallocated = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    treasury_debit = serializers.SerializerMethodField()

    class Meta:
        model = SalaryPayment
        fields = (
            "id",
            "number",
            "employee",
            "paid_on",
            "amount",
            "kind",
            "method",
            "reference",
            "notes",
            "allocations",
            "unallocated",
            "created_by",
            "treasury_debit",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(AMOUNT)
    def get_unallocated(self, payment: SalaryPayment) -> str:
        return str(selectors.unallocated_amount(payment))

    def get_created_by(self, payment: SalaryPayment) -> str:
        return _name_of(payment.created_by)

    @extend_schema_field(TreasuryDebitSerializer)
    def get_treasury_debit(self, payment: SalaryPayment) -> dict[str, Any] | None:
        return selectors.payment_debit(payment)


class SalaryAllocationWriteSerializer(serializers.Serializer[Any]):
    salary_record = serializers.IntegerField(min_value=1)
    amount = serializers.CharField(allow_blank=True)


class SalaryPaymentWriteSerializer(serializers.Serializer[Any]):
    employee = serializers.IntegerField(min_value=1)
    paid_on = serializers.DateField()
    amount = serializers.CharField(allow_blank=True)
    method = serializers.ChoiceField(choices=SalaryPaymentMethod.choices)
    # Salary by default; an advance (D-234) is allocated in full to the salary of the payment's month.
    kind = serializers.ChoiceField(choices=SalaryPaymentKind.choices, required=False, default=SalaryPaymentKind.SALARY)
    # Refused by default: an advance above what the month still owes goes through only once the office confirms.
    confirm_overpay = serializers.BooleanField(required=False, default=False)
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    allocations = SalaryAllocationWriteSerializer(many=True, required=False, default=list)


class SalaryPaymentAllocateSerializer(serializers.Serializer[Any]):
    allocations = SalaryAllocationWriteSerializer(many=True)


class SalaryPaymentFilterSerializer(serializers.Serializer[Any]):
    employee = serializers.IntegerField(required=False, min_value=1)
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)


# ---- Days on a lot ----


class BatchRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)


class LotWorkDaySerializer(serializers.ModelSerializer[LotWorkDay]):
    employee = EmployeeRefSerializer(read_only=True)
    batch = serializers.SerializerMethodField()

    class Meta:
        model = LotWorkDay
        fields = ("id", "employee", "work_date", "batch", "days", "monthly_salary", "cost", "notes", "created_at")
        read_only_fields = fields

    @extend_schema_field(BatchRefSerializer(allow_null=True))
    def get_batch(self, work_day: LotWorkDay) -> dict[str, Any] | None:
        if work_day.batch is None:
            return None
        return {"id": work_day.batch.pk, "number": work_day.batch.number}


class LotWorkDayWriteSerializer(serializers.Serializer[Any]):
    employee = serializers.IntegerField(min_value=1)
    work_date = serializers.DateField()
    # Id of the batch (lot), or null.
    batch = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    days = serializers.CharField(allow_blank=True)
    notes = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class LotWorkDayFilterSerializer(serializers.Serializer[Any]):
    employee = serializers.IntegerField(required=False, min_value=1)
    batch = serializers.IntegerField(required=False, min_value=1)
    month = serializers.DateField(required=False)
