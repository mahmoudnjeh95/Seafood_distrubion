from typing import Any

from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.expenses.models import (
    DayLabourEntry,
    DayLabourer,
    Expense,
    ExpenseCategory,
    ExpensePaymentMethod,
    ExpenseStatus,
    LotCostKind,
    WorkType,
)


def person_name(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or user.username


# ---- Categories (P5-T01) ----


class ExpenseCategorySerializer(serializers.ModelSerializer[ExpenseCategory]):
    class Meta:
        model = ExpenseCategory
        # `code` is set on the default categories only ("fuel", "day_labour"...); empty for the owner's.
        fields = ("id", "code", "name", "is_active", "for_drivers")
        read_only_fields = fields


class ExpenseCategoryFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=["active", "archived", "all"], required=False, default="active")


class ExpenseCategoryWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200)
    # Offered on the drivers' phones (D-205).
    for_drivers = serializers.BooleanField(required=False, default=False)


class ExpenseCategoryUpdateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200, required=False)
    is_active = serializers.BooleanField(required=False)
    for_drivers = serializers.BooleanField(required=False)


# ---- Expenses (P5-T01) ----


class ExpenseLotSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    product_name = serializers.CharField(source="product.name", read_only=True)


class ExpenseTruckSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(source="location.name", read_only=True)
    plate = serializers.CharField(read_only=True)


class ExpenseCategoryRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    code = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class ExpenseSerializer(serializers.ModelSerializer[Expense]):
    category = ExpenseCategoryRefSerializer(read_only=True)
    batch = ExpenseLotSerializer(read_only=True, allow_null=True)
    truck = ExpenseTruckSerializer(read_only=True, allow_null=True)
    receipt_url = serializers.SerializerMethodField()
    # "application/pdf" or "image/webp"; empty without a receipt.
    receipt_type = serializers.SerializerMethodField()
    entered_by = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()
    # A day labourer's day (P5-T03): changed from the calendar, not from the expense form.
    day_labour_id = serializers.SerializerMethodField()
    labourer_name = serializers.SerializerMethodField()

    class Meta:
        model = Expense
        fields: tuple[str, ...] = (
            "id",
            "number",
            "status",
            "spent_on",
            "category",
            "amount",
            "payment_method",
            "description",
            "payee",
            "notes",
            "batch",
            "truck",
            "receipt_url",
            "receipt_type",
            "entered_by",
            "created_at",
            "decided_by",
            "decided_at",
            "rejection_reason",
            "day_labour_id",
            "labourer_name",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_day_labour_id(self, expense: Expense) -> int | None:
        entry = getattr(expense, "day_labour", None)
        return entry.pk if entry is not None else None

    def get_labourer_name(self, expense: Expense) -> str:
        entry = getattr(expense, "day_labour", None)
        return entry.labourer.name if entry is not None else ""

    def get_receipt_url(self, expense: Expense) -> str | None:
        if not expense.receipt.name:
            return None
        return reverse("expense-receipt", args=[expense.pk])

    def get_receipt_type(self, expense: Expense) -> str:
        if not expense.receipt.name:
            return ""
        return "application/pdf" if expense.receipt.name.endswith(".pdf") else "image/webp"

    def get_entered_by(self, expense: Expense) -> str:
        return person_name(expense.entered_by)

    def get_decided_by(self, expense: Expense) -> str:
        return person_name(expense.decided_by)


class TruckDayShareSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    # The lot's kg loaded on the truck that day, and the day's total.
    quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)
    day_quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)
    amount = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)


class ExpenseDetailSerializer(ExpenseSerializer):
    # A truck cost of the day: its split over the lots loaded on the truck that day (empty otherwise, and
    # empty when nothing was loaded that day: it then stays a general cost).
    shares = serializers.SerializerMethodField()

    class Meta(ExpenseSerializer.Meta):
        fields = (*ExpenseSerializer.Meta.fields, "shares")
        read_only_fields = fields

    @extend_schema_field(TruckDayShareSerializer(many=True))
    def get_shares(self, expense: Expense) -> list[dict[str, Any]]:
        shares = self.context.get("shares", [])
        return list(TruckDayShareSerializer(shares, many=True).data)


class ExpenseWriteSerializer(serializers.Serializer[Any]):
    spent_on = serializers.DateField()
    category = serializers.IntegerField(min_value=1)
    # An amount in DT as a string ("45.500"), checked by the service.
    amount = serializers.CharField(allow_blank=True)
    payment_method = serializers.ChoiceField(
        choices=ExpensePaymentMethod.choices, required=False, default=ExpensePaymentMethod.CASH
    )
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    payee = serializers.CharField(required=False, allow_blank=True, default="", max_length=150)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    # A cost of this lot. Or `truck`: a truck cost of that day, split over the lots on board. Not both.
    batch = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    truck = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    # Approve it at once (owner or manager); otherwise it stays a draft.
    approve_now = serializers.BooleanField(required=False, default=False)


class ExpenseRejectSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=255, allow_blank=True)


@extend_schema_field(OpenApiTypes.BINARY)
class UploadedFileField(serializers.FileField):
    """A file sent in a multipart form: a Blob in the generated client, not a URL."""


class ExpenseReceiptSerializer(serializers.Serializer[Any]):
    receipt = UploadedFileField()


class ExpenseFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=ExpenseStatus.choices, required=False)
    category = serializers.IntegerField(required=False, min_value=1)
    batch = serializers.IntegerField(required=False, min_value=1)
    truck = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class ExpenseTotalsSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField(read_only=True)
    # Approved: what counts in the costs. Waiting: drafts and expenses sent for approval.
    approved = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)
    waiting = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)


# ---- Costs of a lot ----


class LotCostFilterSerializer(serializers.Serializer[Any]):
    batch = serializers.IntegerField(min_value=1)


class LotCostLineSerializer(serializers.Serializer[Any]):
    # "lot": typed on the lot; "truck_day": its share of a truck's costs that day; "cold_room",
    # "cold_room_adjustment" and "general": worked out from the stock ledger (D-058, D-059).
    kind = serializers.ChoiceField(choices=LotCostKind.choices, read_only=True)
    # Empty for a cold-room estimate made before the month's bill exists.
    expense_id = serializers.IntegerField(read_only=True, allow_null=True)
    expense_number = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=ExpenseStatus.choices, read_only=True)
    spent_on = serializers.DateField(read_only=True)
    category_code = serializers.CharField(read_only=True)
    category_name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    amount = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)
    expense_amount = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)
    truck_name = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(read_only=True, allow_null=True, max_digits=12, decimal_places=3)
    day_quantity = serializers.DecimalField(read_only=True, allow_null=True, max_digits=12, decimal_places=3)
    # Cold room: the room; cold room and general costs: the month charged, with the lot's kg-days in
    # `quantity`. `estimated`: the amount is an estimate (no bill yet for that month).
    location_name = serializers.CharField(read_only=True)
    month = serializers.DateField(read_only=True, allow_null=True)
    estimated = serializers.BooleanField(read_only=True)


class LotCostsSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    # Approved lines only: the lot's costs so far.
    total = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)
    # Approved lines, then drafts and waiting ones (shown, not counted).
    lines = LotCostLineSerializer(many=True, read_only=True)


# ---- Day labour (P5-T03) ----


class DayLabourerSerializer(serializers.ModelSerializer[DayLabourer]):
    class Meta:
        model = DayLabourer
        fields = ("id", "name", "phone", "usual_daily_pay", "notes", "is_active")
        read_only_fields = fields


class DayLabourerFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=["active", "archived", "all"], required=False, default="active")


class DayLabourerWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=200)
    phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=60)
    # DT for a usual day, as a string ("40.000"); empty when it varies.
    usual_daily_pay = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    is_active = serializers.BooleanField(required=False, default=True)


class DayLabourLabourerSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class DayLabourEntrySerializer(serializers.ModelSerializer[DayLabourEntry]):
    """A day worked, with the expense it is (one record, D-054)."""

    labourer = DayLabourLabourerSerializer(read_only=True)
    expense_id = serializers.IntegerField(source="expense.id", read_only=True)
    number = serializers.CharField(source="expense.number", read_only=True)
    status = serializers.ChoiceField(source="expense.status", choices=ExpenseStatus.choices, read_only=True)
    worked_on = serializers.DateField(source="expense.spent_on", read_only=True)
    amount = serializers.DecimalField(source="expense.amount", read_only=True, max_digits=14, decimal_places=3)
    payment_method = serializers.ChoiceField(
        source="expense.payment_method", choices=ExpensePaymentMethod.choices, read_only=True
    )
    batch = ExpenseLotSerializer(source="expense.batch", read_only=True, allow_null=True)
    notes = serializers.CharField(source="expense.notes", read_only=True)
    entered_by = serializers.SerializerMethodField()
    rejection_reason = serializers.CharField(source="expense.rejection_reason", read_only=True)

    class Meta:
        model = DayLabourEntry
        fields = (
            "id",
            "expense_id",
            "number",
            "status",
            "worked_on",
            "labourer",
            "amount",
            "payment_method",
            "batch",
            "work_type",
            "notes",
            "entered_by",
            "rejection_reason",
        )
        read_only_fields = fields

    def get_entered_by(self, entry: DayLabourEntry) -> str:
        return person_name(entry.expense.entered_by)


class DayLabourFilterSerializer(serializers.Serializer[Any]):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    labourer = serializers.IntegerField(required=False, min_value=1)
    batch = serializers.IntegerField(required=False, min_value=1)


class DayLabourWriteSerializer(serializers.Serializer[Any]):
    labourer = serializers.IntegerField(min_value=1)
    worked_on = serializers.DateField()
    # DT paid for the day, as a string; empty takes the labourer's usual daily pay.
    amount = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # The lot worked on; empty for general work (stock, store, cleaning): a general cost.
    batch = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    work_type = serializers.ChoiceField(choices=WorkType.choices, required=False, default=WorkType.OTHER)
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    payment_method = serializers.ChoiceField(
        choices=ExpensePaymentMethod.choices, required=False, default=ExpensePaymentMethod.CASH
    )
    # Approve it at once (owner or manager); otherwise it stays a draft until approved.
    approve_now = serializers.BooleanField(required=False, default=False)


# ---- Driver app (P3-T04) ----


class RoadCategorySerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class RoadExpenseSerializer(serializers.ModelSerializer[Expense]):
    category_name = serializers.CharField(source="category.name", read_only=True)

    class Meta:
        model = Expense
        fields = (
            "id",
            "number",
            "status",
            "category_name",
            "amount",
            "description",
            "rejection_reason",
            "payment_method",
            "paid_by_driver",
        )
        read_only_fields = fields


class RoadExpenseWriteSerializer(serializers.Serializer[Any]):
    category = serializers.IntegerField(min_value=1)
    # An amount in DT as a string ("45.500"), checked by the service.
    amount = serializers.CharField(allow_blank=True)
    description = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    # A photo of the receipt.
    receipt = UploadedFileField(required=False)
    # How it was paid (D-205): the day's cash, the driver's own pocket (owed to them), or a card / another way.
    paid_with = serializers.ChoiceField(choices=["cash", "pocket", "card"], required=False, default="cash")
    # Sent by the app that may retry: the same value never makes two expenses.
    client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)
    # When the driver's phone says it happened (D-133); the server checks it.
    made_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
