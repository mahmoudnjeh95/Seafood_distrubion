from decimal import Decimal
from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.dayclose import selectors
from apps.dayclose.models import DayClosing, DayClosingStatus, DayReopening, SyncProblem


class DayProductSerializer(serializers.Serializer[Any]):
    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    # What the truck held at the start of the day, from the ledger (kept over from earlier days).
    opening = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    loaded = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    sold = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    lost = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    returned = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    remaining = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    # Left on the truck minus what the day's records explain: negative when kilos went out without a record.
    unexplained = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)


def _purchase_figure() -> Any:
    return serializers.DecimalField(
        max_digits=14, decimal_places=3, read_only=True, required=False, default=Decimal("0.000")
    )


class DaySummarySerializer(serializers.Serializer[Any]):
    date = serializers.DateField(read_only=True)
    truck_name = serializers.CharField(read_only=True)
    driver_name = serializers.CharField(read_only=True)
    opening_cash = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    sales_count = serializers.IntegerField(read_only=True)
    sales_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    cash_received = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Cash collected from customers on their old debts (D-111).
    payments_cash = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    other_payments = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    on_credit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    expenses_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Expenses the driver paid out of pocket (owed back) and by card: not taken from the cash (D-205).
    expenses_pocket = _purchase_figure()
    expenses_other = _purchase_figure()
    # Cash already given to the office that day: counted at the sends a new load undid (D-134).
    handed_over = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # What the driver should hold now: the day's cash less `handed_over`, less what purchases took from it.
    expected_cash = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Purchases at the port, counted apart (D-158); zero in a closing sent before them. The money the office gave
    # for them, the purchases (count, what they owe), what was given in cash and otherwise (cheques, traites), the
    # part of the cash beyond the purchase money that the sales cash paid, and the purchase money that should be left.
    purchase_float = _purchase_figure()
    purchases_count = serializers.IntegerField(read_only=True, required=False, default=0)
    purchases_total = _purchase_figure()
    purchases_cash = _purchase_figure()
    purchases_other = _purchase_figure()
    purchases_from_sales = _purchase_figure()
    # The rest of the cash beyond the purchase money, which the sales cash could not cover: paid by the driver out of
    # pocket, owed back by the office. With `purchases_from_sales` it adds up to the cash beyond the purchase money.
    owed_to_driver = _purchase_figure()
    expected_purchase_cash = _purchase_figure()
    products = DayProductSerializer(many=True, read_only=True)


class DayClosingStateSerializer(serializers.ModelSerializer[DayClosing]):
    """What the driver sees of their closing."""

    # The driver worked after sending: the day must be sent again (D-132).
    changed_since_sent = serializers.SerializerMethodField()

    class Meta:
        model = DayClosing
        fields = (
            "id",
            "status",
            "expected_cash",
            "counted_cash",
            "difference",
            "expected_purchase_cash",
            "counted_purchase_cash",
            "purchase_difference",
            "driver_note",
            "review_note",
            "submitted_at",
            "changed_since_sent",
        )
        read_only_fields = fields

    def get_changed_since_sent(self, closing: DayClosing) -> bool:
        return selectors.changed_since_sent(closing)


class MyDaySummarySerializer(serializers.Serializer[Any]):
    summary = DaySummarySerializer(read_only=True)
    closing = DayClosingStateSerializer(read_only=True, allow_null=True)


class DayClosingWriteSerializer(serializers.Serializer[Any]):
    # The cash in the driver's hands, in DT as a string ("250.500").
    counted_cash = serializers.CharField(allow_blank=True)
    # The purchase money left, counted apart (D-158); "0" for a driver who did not buy.
    counted_purchase_cash = serializers.CharField(required=False, allow_blank=True, default="0")
    note = serializers.CharField(required=False, allow_blank=True, default="")


class MyDayRowSerializer(serializers.Serializer[Any]):
    """One of the driver's days in their history, with its closing when sent."""

    id = serializers.IntegerField(read_only=True)
    date = serializers.DateField(read_only=True)
    truck_name = serializers.CharField(source="truck.location.name", read_only=True)
    opening_cash = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    # Null while the day runs: not sent yet, or opened again by a new load (D-134).
    ended_at = serializers.DateTimeField(read_only=True, allow_null=True)
    # Not sent yet: null.
    closing = DayClosingStateSerializer(read_only=True, allow_null=True)


class DayClosingRowSerializer(serializers.ModelSerializer[DayClosing]):
    date = serializers.DateField(source="driver_day.date", read_only=True)
    truck_name = serializers.CharField(source="driver_day.truck.location.name", read_only=True)
    driver_name = serializers.SerializerMethodField()
    status = serializers.ChoiceField(choices=DayClosingStatus.choices, read_only=True)
    # Office count - driver count (D-204); null until the office counted at approval.
    office_gap = serializers.SerializerMethodField()
    office_purchase_gap = serializers.SerializerMethodField()

    class Meta:
        model = DayClosing
        fields: tuple[str, ...] = (
            "id",
            "date",
            "truck_name",
            "driver_name",
            "status",
            "expected_cash",
            "counted_cash",
            "difference",
            "expected_purchase_cash",
            "counted_purchase_cash",
            "purchase_difference",
            "office_counted_cash",
            "office_counted_purchase_cash",
            "office_gap",
            "office_purchase_gap",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True))
    def get_office_gap(self, closing: DayClosing) -> str | None:
        """Office count - driver count of the sales cash (D-204); null until the office counted."""
        if closing.office_counted_cash is None:
            return None
        return str(closing.office_counted_cash - closing.counted_cash)

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True))
    def get_office_purchase_gap(self, closing: DayClosing) -> str | None:
        if closing.office_counted_purchase_cash is None:
            return None
        return str(closing.office_counted_purchase_cash - closing.counted_purchase_cash)

    def get_driver_name(self, closing: DayClosing) -> str:
        driver = closing.driver_day.driver
        return f"{driver.first_name} {driver.last_name}".strip() or driver.username


class ChangedFigureSerializer(serializers.Serializer[Any]):
    """One figure of a day that the records, read now, no longer give as the driver sent it (D-134)."""

    # Which figure: one of the day (`sales_total`...) or of a product (`sold`...).
    figure = serializers.ChoiceField(choices=[(name, name) for name in selectors.CHANGED_FIGURES], read_only=True)
    # Empty for a figure of the whole day.
    product_name = serializers.CharField(read_only=True)
    # DT, kg, or a number of sales for `sales_count`.
    sent = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    live = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


def _person(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or user.username


class DayReopeningSerializer(serializers.ModelSerializer[DayReopening]):
    """A send that a new load undid (D-134), as it was: its cash was handed to the office."""

    status = serializers.ChoiceField(choices=DayClosingStatus.choices, read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    reopened_at = serializers.DateTimeField(source="created_at", read_only=True)
    load_number = serializers.CharField(source="load.number", read_only=True)

    class Meta:
        model = DayReopening
        fields = (
            "status",
            "expected_cash",
            "counted_cash",
            "difference",
            "counted_purchase_cash",
            "driver_note",
            "submitted_at",
            "reviewed_by_name",
            "reviewed_at",
            "reopened_at",
            "load_number",
        )
        read_only_fields = fields

    def get_reviewed_by_name(self, reopening: DayReopening) -> str:
        return _person(reopening.reviewed_by)


class DayClosingDetailSerializer(DayClosingRowSerializer):
    summary = DaySummarySerializer(read_only=True)
    reviewed_by_name = serializers.SerializerMethodField()
    # The earlier sends of this day that a new load undid, oldest first.
    reopenings = DayReopeningSerializer(many=True, read_only=True)
    # Where the day's records now differ from `summary`, the figures as sent (a sale received after the send,
    # D-134). Empty when nothing changed, and once approved.
    changes_since_sent = serializers.SerializerMethodField()
    # Any such difference: the office waits for the day sent again (D-132).
    changed_since_sent = serializers.SerializerMethodField()

    class Meta(DayClosingRowSerializer.Meta):
        fields: tuple[str, ...] = (
            *DayClosingRowSerializer.Meta.fields,
            "driver_note",
            "review_note",
            "submitted_at",
            "reviewed_at",
            "reviewed_by_name",
            "summary",
            "reopenings",
            "changes_since_sent",
            "changed_since_sent",
        )
        read_only_fields = fields

    @extend_schema_field(ChangedFigureSerializer(many=True))
    def get_changes_since_sent(self, closing: DayClosing) -> Any:
        return ChangedFigureSerializer(selectors.changes_since_sent(closing), many=True).data

    def get_changed_since_sent(self, closing: DayClosing) -> bool:
        return selectors.changed_since_sent(closing)

    def get_reviewed_by_name(self, closing: DayClosing) -> str:
        return _person(closing.reviewed_by)


class DayClosingFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=DayClosingStatus.choices, required=False)
    # Matches the driver's name or login, or the truck.
    search = serializers.CharField(required=False, allow_blank=True, default="")
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class DayClosingApproveSerializer(serializers.Serializer[Any]):
    # What the office counted when the driver handed the cash over (D-204).
    office_counted_cash = serializers.DecimalField(
        max_digits=14, decimal_places=3, required=False, allow_null=True, default=None
    )
    office_counted_purchase_cash = serializers.DecimalField(
        max_digits=14, decimal_places=3, required=False, allow_null=True, default=None
    )
    # Needed when the office count differs from the driver's.
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=300)


class JustificationSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(allow_blank=True, max_length=300)


class SyncProblemWriteSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(
        choices=[
            ("sale", "sale"),
            ("expense", "expense"),
            ("loss", "loss"),
            ("payment", "payment"),
            ("pickup", "pickup"),
            ("purchase", "purchase"),
            ("delivery", "delivery"),
            ("not_delivered", "not_delivered"),
        ]
    )
    # What the driver would call it: the customer, the category, the product.
    what = serializers.CharField(allow_blank=True, max_length=150)
    reason = serializers.CharField(allow_blank=True, max_length=500)
    client_uuid = serializers.UUIDField()


class SyncProblemSerializer(serializers.ModelSerializer[SyncProblem]):
    driver_name = serializers.SerializerMethodField()

    class Meta:
        model = SyncProblem
        fields = ("id", "kind", "label", "reason", "driver_name", "created_at", "resolved_at")
        read_only_fields = fields

    def get_driver_name(self, problem: SyncProblem) -> str:
        driver = problem.driver
        return f"{driver.first_name} {driver.last_name}".strip() or driver.username


_STATES = [("running", "running"), *DayClosingStatus.choices]


def _money() -> Any:
    return serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class DayOverviewRowSerializer(DaySummarySerializer):
    """One driver's day for the office, running or sent: its money, its sales and how many deliveries are done."""

    id = serializers.IntegerField(read_only=True)
    phase = serializers.ChoiceField(choices=_STATES, read_only=True)
    deliveries_done = serializers.IntegerField(read_only=True)
    deliveries_todo = serializers.IntegerField(read_only=True)
    # The closing the driver sent, to check it on the page of the closings; null while the day runs.
    closing_id = serializers.IntegerField(read_only=True, allow_null=True)

    class Meta:
        ref_name = "DayOverviewRow"


class DayOverviewSaleSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    delivery_address = serializers.CharField(read_only=True)
    sold_at = serializers.DateTimeField(read_only=True)
    total = _money()
    amount_paid = _money()
    amount_due = _money()
    payment_method = serializers.CharField(read_only=True)
    # The BL of a truck load (D-160), not a sale made on the road.
    from_load = serializers.BooleanField(read_only=True)
    products = serializers.CharField(read_only=True)


class DayOverviewPaymentSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    method = serializers.CharField(read_only=True)
    amount = _money()
    made_at = serializers.DateTimeField(read_only=True)


class DayOverviewExpenseSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    category_name = serializers.CharField(read_only=True)
    description = serializers.CharField(read_only=True)
    amount = _money()
    status = serializers.CharField(read_only=True)
    payment_method = serializers.CharField(read_only=True)
    made_at = serializers.DateTimeField(read_only=True)


class DayOverviewDetailSerializer(DayOverviewRowSerializer):
    closing = DayClosingStateSerializer(read_only=True, allow_null=True)
    sales = DayOverviewSaleSerializer(many=True, read_only=True)
    deliveries = DayOverviewSaleSerializer(many=True, read_only=True)
    payments = DayOverviewPaymentSerializer(many=True, read_only=True)
    expenses = DayOverviewExpenseSerializer(many=True, read_only=True)

    class Meta:
        ref_name = "DayOverviewDetail"


class DayOverviewFilterSerializer(serializers.Serializer[Any]):
    driver_id = serializers.IntegerField(required=False)
    truck_id = serializers.IntegerField(required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


class DayOverviewDriverSerializer(serializers.Serializer[Any]):
    """A driver who opened days, for the filter."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)


class RoutePointSerializer(serializers.Serializer[Any]):
    recorded_at = serializers.DateTimeField(read_only=True)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    # Radius of the fix in metres.
    accuracy = serializers.FloatField(read_only=True, allow_null=True)


class RouteStopCustomerSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    # His place is saved: the office can still replace it from another stop.
    has_place = serializers.BooleanField(read_only=True)


class RouteStopSerializer(serializers.Serializer[Any]):
    """Where the truck stayed five minutes or more."""

    started_at = serializers.DateTimeField(read_only=True)
    ended_at = serializers.DateTimeField(read_only=True)
    minutes = serializers.IntegerField(read_only=True)
    latitude = serializers.FloatField(read_only=True)
    longitude = serializers.FloatField(read_only=True)
    # The customers at the stop: served then, or whose saved place is within 75 m.
    customers = RouteStopCustomerSerializer(many=True, read_only=True)


class DayRouteSerializer(serializers.Serializer[Any]):
    """The GPS route of one driver's day, in time order; `last` is where the truck was last seen."""

    points = RoutePointSerializer(many=True, read_only=True)
    last = RoutePointSerializer(read_only=True, allow_null=True)
    stops = RouteStopSerializer(many=True, read_only=True)
