from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel


class TruckCondition(models.TextChoices):
    OK = "ok", _("En service")
    MAINTENANCE = "maintenance", _("En maintenance")
    BREAKDOWN = "breakdown", _("En panne")


class Truck(OrganizationScopedModel, TimeStampedModel):
    """A refrigerated truck and the driver who sells from it.

    Its stock lives in its own `inventory.StockLocation` (one to one), which also carries its name.
    """

    # By name, not by import: an app only uses another app's services and selectors (ARCHITECTURE §3).
    location = models.OneToOneField("inventory.StockLocation", on_delete=models.PROTECT, related_name="truck")
    # Tunisian plate as written on the truck, such as "123 TU 4567"; stored in capitals with single spaces.
    plate = models.CharField(max_length=20)
    # The usual driver: the default proposal and the fallback when nobody was assigned for the day (D-046).
    # Who drives it on a given date is a `TruckAssignment`; a driver may be the usual driver of several trucks.
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="trucks"
    )
    is_active = models.BooleanField(default=True)
    # A truck in maintenance or broken down cannot be taken by a driver (D-163).
    condition = models.CharField(max_length=12, choices=TruckCondition.choices, default=TruckCondition.OK)

    class Meta:
        ordering = ["location__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "plate"], name="truck_plate_unique_per_organization"),
        ]

    def __str__(self) -> str:
        return f"{self.location.name} · {self.plate}"


class TruckAssignment(OrganizationScopedModel, TimeStampedModel):
    """Which driver takes which truck on a date (D-042, D-046).

    One driver per truck and one truck per driver each day. Phase 3's driver day builds on it.
    """

    truck = models.ForeignKey(Truck, on_delete=models.PROTECT, related_name="assignments")
    # Empty: the truck is left free that day, also for its usual driver (D-163).
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="truck_assignments"
    )
    date = models.DateField()

    class Meta:
        ordering = ["date", "truck__location__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "truck", "date"], name="one_driver_per_truck_per_day"),
            models.UniqueConstraint(fields=["organization", "driver", "date"], name="one_truck_per_driver_per_day"),
        ]

    def __str__(self) -> str:
        return f"{self.date} · {self.truck.location.name} · {self.driver.username if self.driver else '-'}"


class DriverDay(OrganizationScopedModel, TimeStampedModel):
    """A driver's working day on a truck, opened from the phone with the cash float in hand (P3-T01).

    One per driver and date. Sending the closing ends it (D-134): it covers its date up to that moment
    (`selectors.day_window`) and takes nothing made after it, until a load validated that date opens it again.
    """

    truck = models.ForeignKey(Truck, on_delete=models.PROTECT, related_name="driver_days")
    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="driver_days")
    date = models.DateField()
    # Cash the driver starts the day with (millimes).
    opening_cash = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    # Money the office gave for buying at the port, kept apart from the sales cash (D-158).
    purchase_float = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    # When the driver sent the closing; null while the day is running, and again once a new load reopened it.
    ended_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "driver", "date"], name="one_driver_day_per_driver_per_day"
            ),
            models.CheckConstraint(condition=models.Q(opening_cash__gte=0), name="driver_day_cash_not_negative"),
            models.CheckConstraint(
                condition=models.Q(purchase_float__gte=0), name="driver_day_purchase_float_not_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date} · {self.truck.location.name} · {self.driver.username}"


class DayFund(OrganizationScopedModel, TimeStampedModel):
    """The cash the office hands a driver for a day, before it starts (D-203): the starting cash and the money for
    buying at the port. The driver accepts it on the phone, which starts the day with these amounts."""

    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="day_funds")
    date = models.DateField()
    opening_cash = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    purchase_float = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    set_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    # When the driver accepted it (and so started the day); null while it waits.
    accepted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-date", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "driver", "date"], name="one_day_fund_per_driver_per_day"),
            models.CheckConstraint(
                condition=models.Q(opening_cash__gte=0, purchase_float__gte=0), name="day_fund_not_negative"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.date} · {self.driver} · {self.opening_cash}"


class LocationPing(OrganizationScopedModel, TimeStampedModel):
    """One GPS point of a driver's phone during a running day (D-164). Append-only: points are never changed.

    `recorded_at` is the phone's clock at the moment of the fix (a point queued without signal arrives later);
    `client_uuid` makes a resent batch store each point once.
    """

    driver_day = models.ForeignKey(DriverDay, on_delete=models.PROTECT, related_name="pings")
    client_uuid = models.UUIDField()
    recorded_at = models.DateTimeField()
    latitude = models.DecimalField(max_digits=9, decimal_places=6)
    longitude = models.DecimalField(max_digits=9, decimal_places=6)
    # Radius of the fix in metres, as the phone reports it.
    accuracy = models.DecimalField(max_digits=8, decimal_places=1, null=True, blank=True)

    class Meta:
        ordering = ["recorded_at", "id"]
        indexes = [models.Index(fields=["driver_day", "recorded_at"], name="ping_day_time")]
        constraints = [
            models.UniqueConstraint(fields=["organization", "client_uuid"], name="location_ping_uuid_unique"),
            models.CheckConstraint(
                condition=models.Q(latitude__gte=-90, latitude__lte=90, longitude__gte=-180, longitude__lte=180),
                name="location_ping_on_earth",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.driver_day} · {self.recorded_at:%H:%M:%S}"
