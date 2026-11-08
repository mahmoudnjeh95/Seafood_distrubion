import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel

# Defaults of the maintenance settings (P10-T01, D-283): a light delivery truck rarely drives more in a day.
DEFAULT_MAX_DAY_KM = 600


class MaintenanceSettings(OrganizationScopedModel, TimeStampedModel):
    """The organization's maintenance settings (Paramètres entretien, D-283). One row per organization, made with
    the defaults the first time it is read. P10-T02 adds the maintenance types and their intervals."""

    # Above this many km per day since the last reading, a compteur reading is kept with a warning for the office.
    max_day_km = models.PositiveIntegerField(default=DEFAULT_MAX_DAY_KM)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["organization"], name="one_maintenance_settings_per_organization"),
        ]


class OdometerSource(models.TextChoices):
    DRIVER = "driver", _("Chauffeur")
    OFFICE = "office", _("Bureau")


class OdometerWarning(models.TextChoices):
    NONE = "", _("Aucun")
    # More km since the last reading than the settings allow per day: a typo or a long trip, the office looks.
    BIG_JUMP = "big_jump", _("Saut important")


def odometer_photo_path(reading: "OdometerReading", filename: str) -> str:
    # A random name: the photo's address cannot be guessed from the reading.
    return f"odometer/{reading.organization_id}/{uuid.uuid4().hex}.webp"


class OdometerReading(OrganizationScopedModel, TimeStampedModel):
    """The compteur (odometer) of a truck at a moment, typed by the driver when he sends his day or by the office
    (P10-T01, D-283). There is no GPS for the km: these readings are the base of the km-based maintenance.

    Append-only: a wrong reading is never changed. The office types a correction (a new reading with a reason,
    which may be lower) and the truck's latest reading is the reference for the next one.
    """

    # By name, not by import: an app only uses another app's services and selectors (ARCHITECTURE §3).
    truck = models.ForeignKey("fleet.Truck", on_delete=models.PROTECT, related_name="odometer_readings")
    # The driver's day it was typed on; empty for an office correction.
    driver_day = models.ForeignKey(
        "fleet.DriverDay", null=True, blank=True, on_delete=models.PROTECT, related_name="odometer_readings"
    )
    km = models.PositiveIntegerField()
    source = models.CharField(max_length=8, choices=OdometerSource.choices)
    photo = models.ImageField(upload_to=odometer_photo_path, blank=True)
    # The driver's remark, or the office's reason for a correction (required then).
    note = models.CharField(max_length=300, blank=True)
    warning = models.CharField(max_length=12, choices=OdometerWarning.choices, blank=True, default="")
    # The km driven since the truck's previous reading (None for its first reading or a correction).
    driven_km = models.PositiveIntegerField(null=True, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [models.Index(fields=["organization", "truck", "-created_at"], name="odometer_truck_latest")]

    def __str__(self) -> str:
        return f"{self.truck_id} · {self.km} km"
