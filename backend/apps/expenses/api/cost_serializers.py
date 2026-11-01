"""Serializers of the cold-room cost and the general costs (P5-T02, P5-T05)."""

from typing import Any

from rest_framework import serializers

from apps.expenses.models import ElectricityBill, ExpensePaymentMethod, ExpenseStatus, GeneralCostPeriod, RecurringCost

from .serializers import ExpenseCategoryRefSerializer, person_name

# ---- Cold room ----


class ColdRoomWeightSerializer(serializers.Serializer[Any]):
    location_id = serializers.IntegerField(read_only=True)
    location_name = serializers.CharField(read_only=True)
    weight = serializers.DecimalField(read_only=True, max_digits=8, decimal_places=3)
    # Share of the bill this weight gives the room, in % of the active rooms' weights.
    share_percent = serializers.DecimalField(read_only=True, max_digits=6, decimal_places=2)


class ColdRoomWeightWriteSerializer(serializers.Serializer[Any]):
    # A positive number with at most 3 decimals ("1.500"), checked by the service.
    weight = serializers.CharField()


class ColdRoomShareWriteSerializer(serializers.Serializer[Any]):
    location_id = serializers.IntegerField()
    # Percent with at most 3 decimals ("20.000"), checked by the service.
    percent = serializers.CharField()


class ColdRoomSharesWriteSerializer(serializers.Serializer[Any]):
    shares = ColdRoomShareWriteSerializer(many=True)


class ElectricityBillSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    month = serializers.DateField(read_only=True)
    amount = serializers.DecimalField(source="expense.amount", read_only=True, max_digits=14, decimal_places=3)
    expense_id = serializers.IntegerField(read_only=True)
    expense_number = serializers.CharField(source="expense.number", read_only=True)
    status = serializers.ChoiceField(source="expense.status", choices=ExpenseStatus.choices, read_only=True)
    payment_method = serializers.ChoiceField(
        source="expense.payment_method", choices=ExpensePaymentMethod.choices, read_only=True
    )
    payee = serializers.CharField(source="expense.payee", read_only=True)
    notes = serializers.CharField(source="expense.notes", read_only=True)
    entered_by = serializers.SerializerMethodField()
    # Approved: the rooms' shares are frozen and the lots corrected.
    finalized = serializers.SerializerMethodField()
    estimate_source_month = serializers.DateField(read_only=True, allow_null=True)

    def get_entered_by(self, bill: ElectricityBill) -> str:
        return person_name(bill.expense.entered_by)

    def get_finalized(self, bill: ElectricityBill) -> bool:
        return bill.finalized_at is not None


class ElectricityBillFilterSerializer(serializers.Serializer[Any]):
    pass


class ElectricityBillWriteSerializer(serializers.Serializer[Any]):
    # The first day of the month the bill is for (a finished month); ignored when changing a bill.
    month = serializers.DateField()
    # An amount in DT as a string ("512.350"), checked by the service.
    amount = serializers.CharField(allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=ExpensePaymentMethod.choices, required=False, default=ExpensePaymentMethod.TRANSFER
    )
    payee = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    approve_now = serializers.BooleanField(required=False, default=False)


class ColdRoomMonthFilterSerializer(serializers.Serializer[Any]):
    # Any day of the month; the current month when omitted.
    month = serializers.DateField(required=False)


class ColdRoomMonthRowSerializer(serializers.Serializer[Any]):
    location_id = serializers.IntegerField(read_only=True)
    location_name = serializers.CharField(read_only=True)
    weight = serializers.DecimalField(read_only=True, max_digits=8, decimal_places=3)
    month_amount = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)
    day_amount = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)
    estimated = serializers.BooleanField(read_only=True)


class ColdRoomMonthSerializer(serializers.Serializer[Any]):
    month = serializers.DateField(read_only=True)
    days = serializers.IntegerField(read_only=True)
    bill = ElectricityBillSerializer(read_only=True, allow_null=True)
    # True until the month's bill is approved: the amounts are the estimate (typed, or the previous month's daily rate).
    estimated = serializers.BooleanField(read_only=True)
    # The estimate the owner typed for the month (empty when none), and whether it is the one in use.
    typed_amount = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)
    estimate_typed = serializers.BooleanField(read_only=True)
    estimate_source_month = serializers.DateField(read_only=True, allow_null=True)
    rooms = ColdRoomMonthRowSerializer(many=True, read_only=True)
    # Real once the bill is approved, else the estimate.
    total = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)
    # What the month was estimated at, and the real bill minus that estimate (once approved).
    estimate_total = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)
    difference = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)


class ColdRoomEstimateWriteSerializer(serializers.Serializer[Any]):
    # The first day of the month (the current month or an earlier one).
    month = serializers.DateField()
    # An amount in DT as a string ("512.350"), checked by the service.
    amount = serializers.CharField(allow_blank=True)
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


# ---- General costs ----


class RecurringCostSerializer(serializers.ModelSerializer[RecurringCost]):
    category = ExpenseCategoryRefSerializer(read_only=True)

    class Meta:
        model = RecurringCost
        fields: tuple[str, ...] = (
            "id",
            "name",
            "category",
            "monthly_amount",
            "payment_method",
            "payee",
            "start_month",
            "end_month",
            "is_active",
        )
        read_only_fields: tuple[str, ...] = fields


class RecurringCostFilterSerializer(serializers.Serializer[Any]):
    active_only = serializers.BooleanField(required=False, default=False)


class RecurringCostWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=100)
    category = serializers.IntegerField(min_value=1)
    monthly_amount = serializers.CharField(allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=ExpensePaymentMethod.choices, required=False, default=ExpensePaymentMethod.TRANSFER
    )
    payee = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    # First day of the first month, and of the last one (empty: no end).
    start_month = serializers.DateField()
    end_month = serializers.DateField(required=False, allow_null=True, default=None)
    is_active = serializers.BooleanField(required=False, default=True)


class GenerateRecurringSerializer(serializers.Serializer[Any]):
    # The first day of the month to generate.
    month = serializers.DateField()
    approve_now = serializers.BooleanField(required=False, default=False)


class GeneralCostSerializer(serializers.ModelSerializer[GeneralCostPeriod]):
    expense_id = serializers.IntegerField(read_only=True)
    expense_number = serializers.CharField(source="expense.number", read_only=True)
    status = serializers.ChoiceField(source="expense.status", choices=ExpenseStatus.choices, read_only=True)
    spent_on = serializers.DateField(source="expense.spent_on", read_only=True)
    category = ExpenseCategoryRefSerializer(source="expense.category", read_only=True)
    amount = serializers.DecimalField(source="expense.amount", read_only=True, max_digits=14, decimal_places=3)
    # The part of the amount each covered month carries is amount / months (to the millime).
    description = serializers.CharField(source="expense.description", read_only=True)
    payee = serializers.CharField(source="expense.payee", read_only=True)
    recurring_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        model = GeneralCostPeriod
        fields: tuple[str, ...] = (
            "id",
            "expense_id",
            "expense_number",
            "status",
            "spent_on",
            "category",
            "amount",
            "description",
            "payee",
            "first_month",
            "months",
            "recurring_id",
        )
        read_only_fields: tuple[str, ...] = fields


class GeneralCostFilterSerializer(serializers.Serializer[Any]):
    # Only the costs covering this month.
    month = serializers.DateField(required=False)


class GeneralCostWriteSerializer(serializers.Serializer[Any]):
    spent_on = serializers.DateField()
    category = serializers.IntegerField(min_value=1)
    amount = serializers.CharField(allow_blank=True)
    first_month = serializers.DateField()
    months = serializers.IntegerField(min_value=1, max_value=60, default=1)
    payment_method = serializers.ChoiceField(
        choices=ExpensePaymentMethod.choices, required=False, default=ExpensePaymentMethod.TRANSFER
    )
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    payee = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    approve_now = serializers.BooleanField(required=False, default=False)
