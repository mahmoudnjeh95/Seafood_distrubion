import uuid
from decimal import Decimal
from typing import Any

from django.conf import settings
from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, OrganizationScopedQuerySet, TimeStampedModel
from apps.core.money import MoneyField, QuantityField


class LocationKind(models.TextChoices):
    COLD_ROOM = "cold_room", _("Chambre froide")
    TRUCK = "truck", _("Camion")
    OTHER = "other", _("Autre")


class StockLocation(OrganizationScopedModel, TimeStampedModel):
    """A place that holds stock: a cold room, a truck, or anything else (a freezer at a market stall).

    Every stock movement goes from one location to another (P1-T06). A truck's location is created and
    named with its `fleet.Truck`, never on its own.
    """

    kind = models.CharField(max_length=20, choices=LocationKind.choices)
    name = models.CharField(max_length=100)
    # Customers also buy at the counter of a cold room (Q8). Trucks always sell; this is for the others.
    counter_sales = models.BooleanField(default=False)
    # Archived locations keep their history but receive no more stock.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["kind", "name", "id"]
        constraints = [
            models.UniqueConstraint("organization", Lower("name"), name="location_name_unique_per_organization"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def sells(self) -> bool:
        """Whether sales may be made from here (P2-T04)."""
        return self.kind == LocationKind.TRUCK or self.counter_sales


# Oldest batch first: by receipt date, then in the order they were received the same day (D-009, Q7).
FIFO_ORDER = ("received_on", "id")


class Batch(OrganizationScopedModel, TimeStampedModel):
    """A lot: one product delivered by one supplier on one day, at one cost per kg.

    Kilos of different batches never mix, so every kilo sold knows its supplier and its cost (D-009, Q4,
    Q7). How much of a batch is where comes from the stock ledger (P1-T06), and goods receipts create the
    batches (P1-T07). A batch is never edited once created: a mistake is corrected by a new document.
    """

    # "L-0001", "L-0002"... given by `services.create_batch`, never typed.
    number = models.CharField(max_length=20)
    # By name, not by import: an app only uses another app's services and selectors (ARCHITECTURE §3).
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="batches")
    supplier = models.ForeignKey("partners.Supplier", on_delete=models.PROTECT, related_name="batches")
    # The supplier's delivery note or invoice number, as printed on their paper. P1-T07 adds the receipt itself.
    receipt_reference = models.CharField(max_length=50, blank=True)
    received_on = models.DateField()
    # Purchase cost in DT per kg, without VAT. Costs change daily, so each batch carries its own (D-020).
    unit_cost = MoneyField()
    use_by = models.DateField(null=True, blank=True)
    # Bought with VAT (the supplier's paper carries it): what is sold from this lot is invoiced with VAT (D-202).
    bought_with_vat = models.BooleanField(default=False)

    class Meta:
        ordering = list(FIFO_ORDER)
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="batch_number_unique_per_organization"),
            models.CheckConstraint(condition=models.Q(unit_cost__gte=0), name="batch_unit_cost_not_negative"),
        ]
        indexes = [models.Index(fields=["organization", "product", "received_on"], name="batch_fifo_idx")]
        verbose_name_plural = "batches"

    def __str__(self) -> str:
        return self.number


class BatchCounter(OrganizationScopedModel):
    """The last batch number given in an organization. Its row is locked while a number is taken, so two
    receipts saved at the same moment never get the same number."""

    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["organization"], name="one_batch_counter_per_organization")]

    def __str__(self) -> str:
        return f"{self.organization} · {self.last_number}"


class MovementKind(models.TextChoices):
    RECEIPT = "receipt", _("Réception")
    TRANSFER = "transfer", _("Transfert")
    SALE = "sale", _("Vente")
    CUSTOMER_RETURN = "customer_return", _("Retour client")
    SUPPLIER_RETURN = "supplier_return", _("Retour fournisseur")
    LOSS = "loss", _("Perte")
    ADJUSTMENT = "adjustment", _("Ajustement")
    COUNT_CORRECTION = "count_correction", _("Correction d'inventaire")


class StockMovementQuerySet(OrganizationScopedQuerySet["StockMovement"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("Stock movements are append-only: post a correcting movement instead")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("Stock movements are append-only: they are never deleted")


class StockMovement(OrganizationScopedModel):
    """One quantity of one batch leaving a location, entering one, or going from one to another.

    The ledger is append-only (ARCHITECTURE §4.3, D-006): a mistake is corrected by a new movement.
    Stock on hand is the sum of the movements; `StockOnHand` only caches it. Written only by
    `services.post_movement`.
    """

    kind = models.CharField(max_length=20, choices=MovementKind.choices)
    # Always the batch's product, kept here so stock per product is read without a join.
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="movements")
    # Empty on the outside side: a receipt has no `from`, a sale or a loss has no `to`.
    from_location = models.ForeignKey(
        StockLocation, null=True, blank=True, on_delete=models.PROTECT, related_name="movements_out"
    )
    to_location = models.ForeignKey(
        StockLocation, null=True, blank=True, on_delete=models.PROTECT, related_name="movements_in"
    )
    # Always positive, in kg; the locations give the direction.
    quantity = QuantityField()
    # Cost per kg of what moved: the batch's cost when posted, kept even if a later correction changes it.
    unit_cost = MoneyField()
    # The document that caused it (goods receipt, sale, count...), when there is one.
    source_type = models.ForeignKey(ContentType, null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    source = GenericForeignKey("source_type", "source_id")
    # Null when the system acts on its own.
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # When it happened (a driver offline may sync later); `created_at` is when it was posted.
    occurred_at = models.DateTimeField(default=timezone.now)
    created_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField(blank=True)
    # Sent by the driver app so a retried request never posts twice (ARCHITECTURE §4.7).
    client_uuid = models.UUIDField(null=True, blank=True)

    # mypy sees the base manager as a class variable; replacing it per model is the Django way.
    objects = StockMovementQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["-occurred_at", "-id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="movement_quantity_positive"),
            models.CheckConstraint(
                condition=models.Q(from_location__isnull=False) | models.Q(to_location__isnull=False),
                name="movement_has_a_location",
            ),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="movement_client_uuid_unique_per_organization",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "product", "occurred_at"], name="movement_product_idx"),
            models.Index(fields=["source_type", "source_id"], name="movement_source_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} · {self.batch} · {self.quantity} kg"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise TypeError("Stock movements are append-only: post a correcting movement instead")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise TypeError("Stock movements are append-only: they are never deleted")


class StockOnHand(OrganizationScopedModel):
    """How many kg of one batch one location holds now: a cache of the movements, updated in the same
    transaction by `services.post_movement` and rebuilt from the ledger when in doubt (D-006)."""

    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="on_hand")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="on_hand")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField(default=0)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["location", "batch"]
        constraints = [
            models.UniqueConstraint(fields=["location", "batch"], name="one_on_hand_row_per_location_and_batch"),
            models.CheckConstraint(condition=models.Q(quantity__gte=0), name="on_hand_never_negative"),
        ]
        indexes = [models.Index(fields=["organization", "product"], name="on_hand_product_idx")]
        verbose_name_plural = "stock on hand"

    def __str__(self) -> str:
        return f"{self.location} · {self.batch} · {self.quantity} kg"


class DocumentCounter(OrganizationScopedModel):
    """The last number given to one series of stock documents ("TR" transfers...) in an organization.

    Locked while a number is taken, like `BatchCounter`, so two documents saved at once never share one.
    """

    series = models.CharField(max_length=10)
    last_number = models.PositiveIntegerField(default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization", "series"], name="one_document_counter_per_series"),
        ]

    def __str__(self) -> str:
        return f"{self.organization} · {self.series} · {self.last_number}"


# ---- Transfers between locations (P1-T09, D-044) ----


class TransferKind(models.TextChoices):
    """Given by the two locations, never typed: into a truck, out of a truck, or between two other places."""

    LOAD = "load", _("Chargement")
    RETURN = "return", _("Retour")
    INTERNAL = "internal", _("Entre emplacements")


class TransferStatus(models.TextChoices):
    # Prepared, nothing moved yet: lines and prices may still change.
    DRAFT = "draft", _("Brouillon")
    # Validated by the owner or a manager: the stock moved (FIFO) and the document is frozen.
    VALIDATED = "validated", _("Validé")
    # A draft given up; it never moved stock.
    CANCELLED = "cancelled", _("Annulé")


class Transfer(OrganizationScopedModel, TimeStampedModel):
    """Stock moved from one location to another: the morning load of a truck, its evening return, or
    goods moved between cold rooms. Its lines name products and kg; batches are taken oldest first when
    it is validated (D-009, D-037). A validated transfer is never edited: a mistake is corrected by a
    transfer the other way.
    """

    # "TR-0001", "TR-0002"... per organization, given by `services.create_transfer`.
    number = models.CharField(max_length=20)
    kind = models.CharField(max_length=20, choices=TransferKind.choices)
    status = models.CharField(max_length=20, choices=TransferStatus.choices, default=TransferStatus.DRAFT)
    from_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="transfers_out")
    to_location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="transfers_in")
    # A load "from the cold rooms" (D-174): each line takes its kg from whichever cold rooms hold them, the first room
    # by id first; `from_location` is then one of the cold rooms, the one the boxes leave from.
    from_cold_rooms = models.BooleanField(default=False)
    # The working day it belongs to: the truck's day for a load or a return.
    transferred_on = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    # Phase 3 (P3-T01): the driver confirms on the phone that the load is on the truck. Empty until then.
    confirmed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    confirmed_at = models.DateTimeField(null=True, blank=True)
    # Sent by an app that may retry (the driver app in Phase 3, the demo seed): the same request never
    # creates two transfers (ARCHITECTURE §4.7).
    client_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["-transferred_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="transfer_number_unique_per_organization"),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="transfer_client_uuid_unique_per_organization",
            ),
            models.CheckConstraint(
                condition=~models.Q(from_location=models.F("to_location")), name="transfer_between_two_locations"
            ),
        ]
        indexes = [models.Index(fields=["organization", "transferred_on"], name="transfer_day_idx")]

    def __str__(self) -> str:
        return self.number


class TransferLine(OrganizationScopedModel):
    """One product of a transfer: how many kg, and for a truck load the sale price per kg of the day.

    The price is what the driver sells at (client meeting 2026-10-11): it starts from the price in force
    (`catalog.ProductPrice`) and may be changed on the load; it is kept here, so a later price change never
    rewrites it. The batches come from the movements posted for the line (their source document).
    """

    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField()
    # DT per kg; only on a load (empty on returns and moves between cold rooms).
    unit_price = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=14, decimal_places=3, null=True, blank=True
    )
    # The client this part of a load is for (D-160); empty is the part kept on the truck for the road.
    customer = models.ForeignKey("partners.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["transfer", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="transfer_line_quantity_positive"),
            models.CheckConstraint(
                condition=models.Q(unit_price__isnull=True) | models.Q(unit_price__gt=0),
                name="transfer_line_price_positive",
            ),
            models.UniqueConstraint(
                fields=["transfer", "product"],
                condition=models.Q(customer__isnull=True),
                name="one_transfer_line_per_product",
            ),
            models.UniqueConstraint(
                fields=["transfer", "customer", "product"],
                condition=models.Q(customer__isnull=False),
                name="one_transfer_line_per_client_product",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transfer} · {self.product_id} · {self.quantity} kg"


class TransferBoxLine(OrganizationScopedModel):
    """Boxes of one type that go with a transfer: a count, not kg (D-122). Posted with the transfer when it
    is validated; only a load, or a return from a truck to a cold room, carries boxes (P1-T14e, D-124).
    The box type is checked by `boxes.services`, not here, so this app never imports the boxes models."""

    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name="box_lines")
    box_type = models.CharField(max_length=10)
    count = models.PositiveIntegerField()
    # The client these boxes are for (D-160); empty is the part kept on the truck.
    customer = models.ForeignKey("partners.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["transfer", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(count__gt=0), name="transfer_box_line_count_positive"),
            models.UniqueConstraint(
                fields=["transfer", "box_type"],
                condition=models.Q(customer__isnull=True),
                name="one_transfer_box_line_per_type",
            ),
            models.UniqueConstraint(
                fields=["transfer", "customer", "box_type"],
                condition=models.Q(customer__isnull=False),
                name="one_transfer_box_line_per_client_type",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.transfer} · {self.box_type} · {self.count}"


class TransferDelivery(OrganizationScopedModel):
    """One client of a truck load (D-160): who the part of the load is for, and where it is delivered.

    The address starts from the client's own and may be changed here, for this load only: it is copied to the
    client's delivery note (BL), never written back to the client. The BL itself is a draft sale made by
    `sales` when the load is validated (`Sale.transfer`)."""

    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, related_name="deliveries")
    customer = models.ForeignKey("partners.Customer", on_delete=models.PROTECT, related_name="+")
    delivery_address = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["transfer", "id"]
        constraints = [
            models.UniqueConstraint(fields=["transfer", "customer"], name="one_delivery_per_client_per_transfer"),
        ]

    def __str__(self) -> str:
        return f"{self.transfer} · {self.customer_id}"


# ---- Losses and stock counts (P1-T10, D-045) ----


class StockSettings(OrganizationScopedModel):
    """Stock rules an owner sets for the organization. A missing row means the defaults."""

    # A loss heavier than this waits for the owner's approval; the owner's own losses never wait.
    loss_approval_threshold = QuantityField(default=Decimal("2.000"))
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization"], name="one_stock_settings_per_organization"),
            models.CheckConstraint(
                condition=models.Q(loss_approval_threshold__gte=0), name="loss_threshold_not_negative"
            ),
        ]
        verbose_name_plural = "stock settings"

    def __str__(self) -> str:
        return f"{self.organization} · {self.loss_approval_threshold} kg"


class LossReason(models.TextChoices):
    SPOILED = "spoiled", _("Avarié")
    DAMAGED = "damaged", _("Abîmé ou écrasé")
    EXPIRED = "expired", _("Date dépassée")
    COLD_CHAIN = "cold_chain", _("Rupture du froid")
    OTHER = "other", _("Autre")


class LossStatus(models.TextChoices):
    # Heavier than the threshold: waits for the owner. Nothing has left the stock yet.
    PENDING = "pending", _("En attente")
    # Posted: the kg left the stock, oldest batch first.
    APPROVED = "approved", _("Validée")
    # Refused by the owner: nothing moved.
    REJECTED = "rejected", _("Refusée")


def loss_photo_path(loss: "StockLoss", filename: str) -> str:
    # A random name: the photo's address cannot be guessed from the loss number.
    return f"losses/{loss.organization_id}/{uuid.uuid4().hex}.webp"


class StockLoss(OrganizationScopedModel, TimeStampedModel):
    """Kilos thrown away or spoiled at one location, with why, and a photo as proof when there is one.

    Up to the organization's threshold it leaves the stock at once; above it, it waits for the owner
    (`StockSettings`). Once decided it never changes; a photo may still be added once (evidence).
    """

    # "PE-0001", "PE-0002"... per organization.
    number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=LossStatus.choices)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="losses")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    quantity = QuantityField()
    reason = models.CharField(max_length=20, choices=LossReason.choices)
    note = models.TextField(blank=True)
    lost_on = models.DateField()
    # When the driver's phone says it was lost (D-133); the kilos leave the stock at that moment.
    made_at = models.DateTimeField(null=True, blank=True)
    photo = models.ImageField(upload_to=loss_photo_path, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    rejection_reason = models.TextField(blank=True)
    # The driver app reports losses from the road in Phase 3 and may retry (ARCHITECTURE §4.7).
    client_uuid = models.UUIDField(null=True, blank=True)

    class Meta:
        ordering = ["-lost_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="loss_number_unique_per_organization"),
            models.UniqueConstraint(
                fields=["organization", "client_uuid"],
                condition=models.Q(client_uuid__isnull=False),
                name="loss_client_uuid_unique_per_organization",
            ),
            models.CheckConstraint(condition=models.Q(quantity__gt=0), name="loss_quantity_positive"),
        ]
        verbose_name_plural = "stock losses"

    def __str__(self) -> str:
        return self.number


class CountStatus(models.TextChoices):
    # The sheet is being filled in: nothing moved.
    COUNTING = "counting", _("En cours")
    # Approved: each difference was posted as a count correction.
    APPROVED = "approved", _("Validé")
    CANCELLED = "cancelled", _("Annulé")


class StockCount(OrganizationScopedModel, TimeStampedModel):
    """A stock count of one location: a sheet with what each batch should hold, what was counted, and,
    once approved, a count correction for every difference. One count at a time per location."""

    # "INV-0001", "INV-0002"... per organization.
    number = models.CharField(max_length=20)
    status = models.CharField(max_length=20, choices=CountStatus.choices, default=CountStatus.COUNTING)
    location = models.ForeignKey(StockLocation, on_delete=models.PROTECT, related_name="counts")
    counted_on = models.DateField()
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-counted_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="count_number_unique_per_organization"),
            models.UniqueConstraint(
                fields=["location"],
                condition=models.Q(status="counting"),
                name="one_open_count_per_location",
            ),
        ]

    def __str__(self) -> str:
        return self.number


class StockCountLine(OrganizationScopedModel):
    """One batch of the counted location: what the ledger said when the sheet was made, and what was counted."""

    count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    batch = models.ForeignKey(Batch, on_delete=models.PROTECT, related_name="+")
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT, related_name="+")
    # A snapshot: movements posted while counting do not change it (the difference is what gets posted).
    expected_quantity = QuantityField()
    # Empty until counted; zero when nothing of the batch was found.
    counted_quantity = models.DecimalField[Decimal | None, Decimal | None](
        max_digits=12, decimal_places=3, null=True, blank=True
    )

    class Meta:
        ordering = ["count", "id"]
        constraints = [
            models.UniqueConstraint(fields=["count", "batch"], name="one_count_line_per_batch"),
            models.CheckConstraint(
                condition=models.Q(counted_quantity__isnull=True) | models.Q(counted_quantity__gte=0),
                name="count_line_counted_not_negative",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.count} · {self.batch}"

    @property
    def difference(self) -> Decimal | None:
        """Counted − expected: what the approval posts. Empty until counted."""
        if self.counted_quantity is None:
            return None
        return self.counted_quantity - self.expected_quantity
