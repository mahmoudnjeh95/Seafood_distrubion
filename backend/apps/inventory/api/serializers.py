from decimal import Decimal
from typing import Any

from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.core.money import line_total
from apps.inventory.models import (
    Batch,
    CountStatus,
    LocationKind,
    LossReason,
    LossStatus,
    MovementKind,
    StockCount,
    StockCountLine,
    StockLocation,
    StockLoss,
    StockSettings,
    Transfer,
    TransferDelivery,
    TransferKind,
    TransferLine,
    TransferLinePick,
    TransferStatus,
)


class StockLocationSerializer(serializers.ModelSerializer[StockLocation]):
    # Whether sales may be made from here: always for a truck, at the counter for the others (Q8).
    sells = serializers.BooleanField(read_only=True)

    class Meta:
        model = StockLocation
        fields = ("id", "kind", "name", "counter_sales", "sells", "is_active", "updated_at")
        read_only_fields = fields


class StockLocationCreateSerializer(serializers.Serializer[Any]):
    # Trucks are created with their truck (`createTruck`), which makes their location.
    kind = serializers.ChoiceField(
        choices=[(LocationKind.COLD_ROOM, LocationKind.COLD_ROOM.label), (LocationKind.OTHER, LocationKind.OTHER.label)]
    )
    name = serializers.CharField(max_length=100)
    counter_sales = serializers.BooleanField(required=False, default=False)


class StockLocationUpdateSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=100, required=False)
    counter_sales = serializers.BooleanField(required=False)


class StockLocationFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")], required=False, default="active"
    )
    kind = serializers.ChoiceField(choices=LocationKind.choices, required=False)


class BatchProductSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)
    # Lot pickers leave out the lots of an archived product (D-145).
    is_active = serializers.BooleanField(read_only=True)


class BatchSupplierSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class BatchSerializer(serializers.ModelSerializer[Batch]):
    product = BatchProductSerializer(read_only=True)
    supplier = BatchSupplierSerializer(read_only=True)

    class Meta:
        model = Batch
        fields = (
            "id",
            "number",
            "product",
            "supplier",
            "receipt_reference",
            "received_on",
            "unit_cost",
            "use_by",
            "created_at",
        )
        read_only_fields = fields


class BatchFilterSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(required=False, min_value=1)
    supplier = serializers.IntegerField(required=False, min_value=1)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class LocationStockSerializer(serializers.Serializer[Any]):
    """How many kg of one product a location holds, all batches together."""

    product_id = serializers.IntegerField(read_only=True)
    product_reference = serializers.CharField(source="product__reference", read_only=True)
    product_name = serializers.CharField(source="product__name", read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)


class VatProductsSerializer(serializers.Serializer[Any]):
    """The products with kilos in stock bought with VAT (D-202)."""

    products = serializers.ListField(child=serializers.IntegerField(), read_only=True)


class LocationBatchSerializer(serializers.Serializer[Any]):
    """One lot of a product at a location, for picking it by hand on a sale (default: FIFO, D-121).

    `location_name` is a hint for the till, never printed on a devis or a BL.
    """

    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(source="batch.number", read_only=True)
    received_on = serializers.DateField(source="batch.received_on", read_only=True)
    supplier_id = serializers.IntegerField(source="batch.supplier_id", read_only=True)
    supplier_name = serializers.CharField(source="batch.supplier.name", read_only=True)
    location_id = serializers.IntegerField(read_only=True)
    location_name = serializers.CharField(source="location.name", read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)


# ---- Transfers (P1-T09) ----


def person_name(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or user.username


class PlaceSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    kind = serializers.ChoiceField(choices=LocationKind.choices, read_only=True)


class MovedBatchSerializer(serializers.Serializer[Any]):
    """One batch a line took, oldest first: the movement posted for it."""

    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(source="batch.number", read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)


class LoadClientSerializer(serializers.Serializer[Any]):
    """The client a part of a load is for (D-160)."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    reference = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)


class TransferLineSerializer(serializers.ModelSerializer[TransferLine]):
    product = BatchProductSerializer(read_only=True)
    # The client this line is for; empty for the part kept on the truck (D-160).
    customer = LoadClientSerializer(read_only=True, allow_null=True)
    # Kg × the day's price, for a load line; empty otherwise.
    amount = serializers.SerializerMethodField()

    class Meta:
        model = TransferLine
        fields: tuple[str, ...] = ("id", "product", "customer", "quantity", "unit_price", "amount")
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True))
    def get_amount(self, line: TransferLine) -> str | None:
        if line.unit_price is None:
            return None
        return str(line_total(line.quantity, line.unit_price))


class TransferLinePickSerializer(serializers.ModelSerializer[TransferLinePick]):
    """A lot picked by hand for a line, with the kilos to take from it first (D-215)."""

    batch = serializers.IntegerField(source="batch_id", read_only=True)
    batch_number = serializers.CharField(source="batch.number", read_only=True)

    class Meta:
        model = TransferLinePick
        fields: tuple[str, ...] = ("batch", "batch_number", "quantity")
        read_only_fields: tuple[str, ...] = fields


class TransferLineDetailSerializer(TransferLineSerializer):
    # Filled once the transfer is validated: which batches the kg came from (FIFO).
    batches = serializers.SerializerMethodField()
    # The lots picked by hand on a draft, so its form reloads them (D-215); empty for FIFO.
    picks = TransferLinePickSerializer(many=True, read_only=True)

    class Meta(TransferLineSerializer.Meta):
        fields = (*TransferLineSerializer.Meta.fields, "batches", "picks")
        read_only_fields = fields

    @extend_schema_field(MovedBatchSerializer(many=True))
    def get_batches(self, line: TransferLine) -> list[dict[str, Any]]:
        movements = self.context.get("movements", {}).get(line.pk, [])
        return list(MovedBatchSerializer(movements, many=True).data)


class TransferSerializer(serializers.ModelSerializer[Transfer]):
    from_location = PlaceSerializer(read_only=True)
    to_location = PlaceSerializer(read_only=True)
    lines = TransferLineSerializer(many=True, read_only=True)
    total_quantity = serializers.SerializerMethodField()
    # Sum of the load lines' amounts at the day's prices; empty for a return or a move between cold rooms.
    total_amount = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    validated_by = serializers.SerializerMethodField()
    confirmed_by = serializers.SerializerMethodField()

    class Meta:
        model = Transfer
        fields: tuple[str, ...] = (
            "id",
            "number",
            "kind",
            "status",
            "from_location",
            "from_cold_rooms",
            "to_location",
            "transferred_on",
            "notes",
            "lines",
            "total_quantity",
            "total_amount",
            "created_by",
            "created_at",
            "validated_by",
            "validated_at",
            "confirmed_by",
            "confirmed_at",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DecimalField(max_digits=12, decimal_places=3))
    def get_total_quantity(self, transfer: Transfer) -> str:
        return str(sum((line.quantity for line in transfer.lines.all()), Decimal("0.000")))

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True))
    def get_total_amount(self, transfer: Transfer) -> str | None:
        priced = [line for line in transfer.lines.all() if line.unit_price is not None]
        if not priced:
            return None
        return str(sum((line_total(line.quantity, line.unit_price or 0) for line in priced), Decimal("0.000")))

    def get_created_by(self, transfer: Transfer) -> str:
        return person_name(transfer.created_by)

    def get_validated_by(self, transfer: Transfer) -> str:
        return person_name(transfer.validated_by)

    def get_confirmed_by(self, transfer: Transfer) -> str:
        return person_name(transfer.confirmed_by)


class DeliveryNoteRefSerializer(serializers.Serializer[Any]):
    """The client's BL made from the load (D-160): validated at the load, then delivered by the driver (D-178)."""

    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.CharField(read_only=True)
    # "to_deliver", "delivered", "partial" or "cancelled" (not delivered); empty for a BL made before D-178.
    delivery_status = serializers.CharField(read_only=True)
    version = serializers.IntegerField(read_only=True)


class TransferDeliverySerializer(serializers.Serializer[Any]):
    """One client of a load: where it goes, their boxes, and their BL once the load is validated."""

    customer = LoadClientSerializer(read_only=True)
    delivery_address = serializers.CharField(read_only=True)
    boxes = serializers.SerializerMethodField()
    delivery_note = serializers.SerializerMethodField()

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_boxes(self, delivery: TransferDelivery) -> dict[str, int]:
        return {
            line.box_type: line.count
            for line in delivery.transfer.box_lines.all()
            if line.customer_id == delivery.customer_id
        }

    @extend_schema_field(DeliveryNoteRefSerializer(allow_null=True))
    def get_delivery_note(self, delivery: TransferDelivery) -> dict[str, Any] | None:
        own = [sale for sale in delivery.transfer.delivery_notes.all() if sale.customer_id == delivery.customer_id]
        # The live BL; once not delivered (D-178), the last one, so the office sees what became of it.
        live = [sale for sale in own if sale.status != "cancelled"] or [sale for sale in own if sale.delivery_status]
        return dict(DeliveryNoteRefSerializer(max(live, key=lambda sale: sale.pk)).data) if live else None


class TransferDetailSerializer(TransferSerializer):
    lines = TransferLineDetailSerializer(many=True, read_only=True)
    # The returnable boxes that go with the part of the transfer not given to a client, per box type (D-122): what
    # a draft's form reloads, since saving a draft replaces them. Empty when none.
    boxes = serializers.SerializerMethodField()
    # The clients of a load, each with their address and BL (D-160). Their kg are the `lines` with that customer.
    deliveries = TransferDeliverySerializer(many=True, read_only=True)

    class Meta(TransferSerializer.Meta):
        fields: tuple[str, ...] = (*TransferSerializer.Meta.fields, "boxes", "deliveries")
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DictField(child=serializers.IntegerField()))
    def get_boxes(self, transfer: Transfer) -> dict[str, int]:
        return {line.box_type: line.count for line in transfer.box_lines.all() if line.customer_id is None}


class TransferLinePickWriteSerializer(serializers.Serializer[Any]):
    # A lot of the line's product at the place the kg leave from (`location_batches`).
    batch = serializers.IntegerField(min_value=1)
    # Kilos to take from this lot first; text, checked by the service like the line's weight.
    quantity = serializers.CharField(allow_blank=True)


class TransferLineWriteSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    # Weights and prices travel as strings ("12.500") and are checked by the service, which reports each
    # problem on `lines.<index>.<field>`.
    quantity = serializers.CharField(allow_blank=True)
    # A load only: DT per kg of the day. Empty takes the sale price in force.
    unit_price = serializers.CharField(required=False, allow_blank=True, allow_null=True, default=None)
    # Lots picked by hand instead of FIFO (D-215), each with the kilos to take from it first. Empty: the oldest
    # lot first, as always. Not with several cold rooms as the source.
    picks = TransferLinePickWriteSerializer(many=True, required=False, default=list)


class TransferDeliveryWriteSerializer(serializers.Serializer[Any]):
    customer = serializers.IntegerField(min_value=1)
    # Empty takes the client's own address; a typed one is for this load's BL only (D-160).
    delivery_address = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    lines = TransferLineWriteSerializer(many=True, allow_empty=True)
    boxes = serializers.DictField(child=serializers.IntegerField(min_value=0), required=False, default=dict)


class TransferWriteSerializer(serializers.Serializer[Any]):
    from_location = serializers.IntegerField(min_value=1)
    # A load from the cold rooms together (D-174): `from_location` is then a cold room (the boxes leave from it) and
    # each line takes its kg from whichever cold rooms hold them.
    from_cold_rooms = serializers.BooleanField(required=False, default=False)
    to_location = serializers.IntegerField(min_value=1)
    transferred_on = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")
    lines = TransferLineWriteSerializer(many=True, allow_empty=True)
    # Validate at once (moves the stock); otherwise the transfer stays a draft.
    validate_now = serializers.BooleanField(required=False, default=False)
    # Returnable boxes that go with a load or with a return from a truck to a cold room, per box type ("small",
    # "big"): a count, never kg (D-122, D-124).
    boxes = serializers.DictField(child=serializers.IntegerField(min_value=0), required=False, default=dict)
    # A load split by client (D-160): each client's kg and boxes, and where they are delivered. `lines` and
    # `boxes` are then the part kept on the truck, and may be empty.
    deliveries = TransferDeliveryWriteSerializer(many=True, required=False, default=list)


class TransferFilterSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=TransferKind.choices, required=False)
    status = serializers.ChoiceField(choices=TransferStatus.choices, required=False)
    location = serializers.IntegerField(required=False, min_value=1)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class MyStockLineSerializer(serializers.Serializer[Any]):
    """What the driver's truck holds of one product, with today's price per kg."""

    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, allow_null=True)
    # The product's photo, empty when it has none; the driver app shows a plain mark then.
    photo_url = serializers.CharField(read_only=True, allow_null=True)


class MyStockFilterSerializer(serializers.Serializer[Any]):
    # The customer about to be sold to: their own price list is shown when it holds the product (D-049).
    customer = serializers.IntegerField(required=False, min_value=1)


class TruckDayFilterSerializer(serializers.Serializer[Any]):
    location = serializers.IntegerField(min_value=1)
    date = serializers.DateField()


class TruckDayLineSerializer(serializers.Serializer[Any]):
    product_id = serializers.IntegerField(read_only=True)
    product_reference = serializers.CharField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    loaded = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    returned = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    # Loaded − returned: sold or lost. Negative when more came back than was loaded that day.
    sold_or_lost = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    unit_price = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, allow_null=True)
    # Sold or lost × the day's price.
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, allow_null=True)


class TruckDaySerializer(serializers.Serializer[Any]):
    location = PlaceSerializer(read_only=True)
    date = serializers.DateField(read_only=True)
    lines = TruckDayLineSerializer(many=True, read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


# ---- Losses and stock counts (P1-T10) ----


class StockSettingsSerializer(serializers.ModelSerializer[StockSettings]):
    class Meta:
        model = StockSettings
        fields = ("loss_approval_threshold",)
        read_only_fields = fields


class StockSettingsWriteSerializer(serializers.Serializer[Any]):
    # A weight in kg as a string ("2.500"), checked by the service.
    loss_approval_threshold = serializers.CharField()


@extend_schema_field(OpenApiTypes.BINARY)
class UploadedPhotoField(serializers.FileField):
    """A file sent in a multipart form: a Blob in the generated client, not a URL."""


class LossPhotoSerializer(serializers.Serializer[Any]):
    photo = UploadedPhotoField()


class LossSerializer(serializers.ModelSerializer[StockLoss]):
    location = PlaceSerializer(read_only=True)
    product = BatchProductSerializer(read_only=True)
    photo_url = serializers.SerializerMethodField()
    created_by = serializers.SerializerMethodField()
    decided_by = serializers.SerializerMethodField()

    class Meta:
        model = StockLoss
        fields: tuple[str, ...] = (
            "id",
            "number",
            "status",
            "location",
            "product",
            "quantity",
            "reason",
            "note",
            "lost_on",
            "photo_url",
            "created_by",
            "created_at",
            "decided_by",
            "decided_at",
            "rejection_reason",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_photo_url(self, loss: StockLoss) -> str | None:
        if not loss.photo.name:
            return None
        return reverse("loss-photo", args=[loss.pk])

    def get_created_by(self, loss: StockLoss) -> str:
        return person_name(loss.created_by)

    def get_decided_by(self, loss: StockLoss) -> str:
        return person_name(loss.decided_by)


class LossDetailSerializer(LossSerializer):
    # Once the loss left the stock: the batches it was taken from (oldest first) and their cost.
    batches = serializers.SerializerMethodField()
    cost_amount = serializers.SerializerMethodField()

    class Meta(LossSerializer.Meta):
        fields = (*LossSerializer.Meta.fields, "batches", "cost_amount")
        read_only_fields = fields

    def _movements(self, loss: StockLoss) -> list[Any]:
        movements: list[Any] = self.context.get("movements", {}).get(loss.pk, [])
        return movements

    @extend_schema_field(MovedBatchSerializer(many=True))
    def get_batches(self, loss: StockLoss) -> list[dict[str, Any]]:
        return list(MovedBatchSerializer(self._movements(loss), many=True).data)

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True))
    def get_cost_amount(self, loss: StockLoss) -> str | None:
        movements = self._movements(loss)
        if not movements:
            return None
        total = sum((line_total(movement.quantity, movement.unit_cost) for movement in movements), Decimal("0.000"))
        return str(total)


class LossWriteSerializer(serializers.Serializer[Any]):
    location = serializers.IntegerField(min_value=1)
    product = serializers.IntegerField(min_value=1)
    # A weight as a string ("1.500"), checked by the service.
    quantity = serializers.CharField(allow_blank=True)
    reason = serializers.ChoiceField(choices=LossReason.choices)
    lost_on = serializers.DateField()
    note = serializers.CharField(required=False, allow_blank=True, default="")


class LossRejectSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(allow_blank=True)


class LossFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=LossStatus.choices, required=False)
    location = serializers.IntegerField(required=False, min_value=1)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class CountBatchSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)


class CountLineSerializer(serializers.ModelSerializer[StockCountLine]):
    product = BatchProductSerializer(read_only=True)
    batch = CountBatchSerializer(read_only=True)
    # Counted − expected; empty until counted.
    difference = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True, allow_null=True)

    class Meta:
        model = StockCountLine
        fields = ("id", "product", "batch", "expected_quantity", "counted_quantity", "difference")
        read_only_fields = fields


class CountSerializer(serializers.ModelSerializer[StockCount]):
    location = PlaceSerializer(read_only=True)
    lines = CountLineSerializer(many=True, read_only=True)
    created_by = serializers.SerializerMethodField()
    approved_by = serializers.SerializerMethodField()

    class Meta:
        model = StockCount
        fields = (
            "id",
            "number",
            "status",
            "location",
            "counted_on",
            "notes",
            "lines",
            "created_by",
            "created_at",
            "approved_by",
            "approved_at",
        )
        read_only_fields = fields

    def get_created_by(self, count: StockCount) -> str:
        return person_name(count.created_by)

    def get_approved_by(self, count: StockCount) -> str:
        return person_name(count.approved_by)


class CountWriteSerializer(serializers.Serializer[Any]):
    location = serializers.IntegerField(min_value=1)
    counted_on = serializers.DateField()
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class CountedLineSerializer(serializers.Serializer[Any]):
    line = serializers.IntegerField(min_value=1)
    # Kg counted as a string ("12.400"); empty clears it, "0" means nothing found.
    counted_quantity = serializers.CharField(allow_blank=True, allow_null=True)


class CountedSerializer(serializers.Serializer[Any]):
    lines = CountedLineSerializer(many=True)


class CountFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=CountStatus.choices, required=False)
    location = serializers.IntegerField(required=False, min_value=1)


# ---- Stock screens (P1-T11) ----


class LocationTotalSerializer(serializers.Serializer[Any]):
    """A location with the kg it holds and what they cost."""

    id = serializers.IntegerField(source="location.id", read_only=True)
    name = serializers.CharField(source="location.name", read_only=True)
    kind = serializers.ChoiceField(source="location.kind", choices=LocationKind.choices, read_only=True)
    quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)
    value = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)


class ProductLocationQuantitySerializer(serializers.Serializer[Any]):
    location_id = serializers.IntegerField(read_only=True)
    quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)


class ProductStockSerializer(serializers.Serializer[Any]):
    """One product's stock: kg per location, the minimum-stock warning and the purchase prices (D-048)."""

    id = serializers.IntegerField(source="product.id", read_only=True)
    reference = serializers.CharField(source="product.reference", read_only=True)
    name = serializers.CharField(source="product.name", read_only=True)
    illustration = serializers.CharField(source="product.illustration", read_only=True)
    photo_url = serializers.SerializerMethodField()
    is_active = serializers.BooleanField(source="product.is_active", read_only=True)
    min_stock = serializers.DecimalField(source="product.min_stock", read_only=True, max_digits=12, decimal_places=3)
    quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)
    is_low = serializers.BooleanField(read_only=True)
    locations = serializers.SerializerMethodField()
    # Weighted by the kg of each batch still on hand; for pricing information only (D-040). Empty without stock.
    average_cost = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)
    # Unit cost of the latest batch received.
    last_cost = serializers.DecimalField(read_only=True, allow_null=True, max_digits=14, decimal_places=3)

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_photo_url(self, stock: Any) -> str | None:
        product = stock.product
        if not product.photo.name:
            return None
        version = product.photo.name.rsplit("/", 1)[-1].split(".", 1)[0]
        return f"{reverse('product-photo', args=[product.pk])}?v={version}"

    @extend_schema_field(ProductLocationQuantitySerializer(many=True))
    def get_locations(self, stock: Any) -> Any:
        rows = [{"location_id": key, "quantity": quantity} for key, quantity in stock.by_location.items()]
        return ProductLocationQuantitySerializer(rows, many=True).data


class StockOverviewSerializer(serializers.Serializer[Any]):
    locations = LocationTotalSerializer(many=True, read_only=True)
    products = ProductStockSerializer(many=True, read_only=True)


class BatchLocationSerializer(serializers.Serializer[Any]):
    location = PlaceSerializer(read_only=True)
    quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)


class BatchHoldingSerializer(serializers.Serializer[Any]):
    """A batch of the product still on hand."""

    batch_id = serializers.IntegerField(source="batch.id", read_only=True)
    number = serializers.CharField(source="batch.number", read_only=True)
    supplier_name = serializers.CharField(source="batch.supplier.name", read_only=True)
    received_on = serializers.DateField(source="batch.received_on", read_only=True)
    unit_cost = serializers.DecimalField(source="batch.unit_cost", read_only=True, max_digits=14, decimal_places=3)
    quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)
    value = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)
    locations = serializers.SerializerMethodField()

    @extend_schema_field(BatchLocationSerializer(many=True))
    def get_locations(self, holding: Any) -> Any:
        rows = [{"location": location, "quantity": quantity} for location, quantity in holding.by_location]
        return BatchLocationSerializer(rows, many=True).data


class ProductStockDetailSerializer(ProductStockSerializer):
    batches = BatchHoldingSerializer(many=True, read_only=True)


class StockMovementSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=MovementKind.choices, read_only=True)
    occurred_at = serializers.DateTimeField(read_only=True)
    product = BatchProductSerializer(read_only=True)
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(source="batch.number", read_only=True)
    from_location = PlaceSerializer(read_only=True, allow_null=True)
    to_location = PlaceSerializer(read_only=True, allow_null=True)
    quantity = serializers.DecimalField(read_only=True, max_digits=12, decimal_places=3)
    unit_cost = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)
    reason = serializers.CharField(read_only=True)
    user_name = serializers.SerializerMethodField()

    def get_user_name(self, movement: Any) -> str:
        return person_name(movement.user)


class StockMovementFilterSerializer(serializers.Serializer[Any]):
    location = serializers.IntegerField(required=False, min_value=1)
    product = serializers.IntegerField(required=False, min_value=1)
    batch = serializers.IntegerField(required=False, min_value=1)
    kind = serializers.ChoiceField(choices=MovementKind.choices, required=False)
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)


# ---- Driver app: losses and returns (P3-T05) ----


class RoadLossWriteSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    # A weight as a string ("1.500"), checked by the service.
    quantity = serializers.CharField(allow_blank=True)
    reason = serializers.ChoiceField(choices=LossReason.choices)
    note = serializers.CharField(required=False, allow_blank=True, default="")
    photo = UploadedPhotoField(required=False)
    # Sent by the app that may retry: the same value never makes two losses.
    client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)
    # When the driver's phone says it happened (D-133); the server checks it.
    made_at = serializers.DateTimeField(required=False, allow_null=True, default=None)


class RoadLossSerializer(serializers.ModelSerializer[StockLoss]):
    product_name = serializers.CharField(source="product.name", read_only=True)

    class Meta:
        model = StockLoss
        fields = ("id", "number", "status", "product_name", "quantity", "reason", "rejection_reason")
        read_only_fields = fields


class RoadReturnSerializer(serializers.Serializer[Any]):
    number = serializers.CharField(read_only=True)
    to_location = serializers.CharField(source="to_location.name", read_only=True)
    total_quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
