import uuid

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel

# Defaults of the maintenance settings (P10-T01, D-295): a light delivery truck rarely drives more in a day.
DEFAULT_MAX_DAY_KM = 600


def default_paper_warn_days() -> list[int]:
    return [30, 15, 7]


class MaintenanceSettings(OrganizationScopedModel, TimeStampedModel):
    """The organization's maintenance settings (Paramètres entretien, D-295). One row per organization, made with
    the defaults the first time it is read. P10-T02 adds the maintenance types and their intervals."""

    # Above this many km per day since the last reading, a compteur reading is kept with a warning for the office.
    max_day_km = models.PositiveIntegerField(default=DEFAULT_MAX_DAY_KM)
    # Days before a paper expires when the office is warned (P10-T04: 30, 15, 7, and on the day).
    paper_warn_days = models.JSONField(default=default_paper_warn_days)

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
    (P10-T01, D-295). There is no GPS for the km: these readings are the base of the km-based maintenance.

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


# ---- Maintenance types, plans and records (P10-T02, P10-T03) ----


class MaintenanceTarget(models.TextChoices):
    # The truck itself: by km and/or months (vidange, filtres, freins…).
    TRUCK = "truck", _("Camion")
    # The truck's refrigeration unit: by months (monthly service, owner answer 4).
    FRIGO = "frigo", _("Groupe frigo du camion")
    # A cold room of the company (`inventory.StockLocation` of kind cold room): by months.
    COLD_ROOM = "cold_room", _("Chambre froide")


class MaintenanceType(OrganizationScopedModel, TimeStampedModel):
    """A kind of maintenance with its default interval and warning thresholds (Paramètres entretien, D-295).

    Due after `every_km` km or `every_months` months, whichever comes first; either may be empty, not both. Warned
    `warn_km` km or `warn_days` days before. A plan may set its own interval for one truck or cold room.
    """

    name = models.CharField(max_length=100)
    target = models.CharField(max_length=10, choices=MaintenanceTarget.choices, default=MaintenanceTarget.TRUCK)
    every_km = models.PositiveIntegerField(null=True, blank=True)
    every_months = models.PositiveSmallIntegerField(null=True, blank=True)
    warn_km = models.PositiveIntegerField(default=1000)
    warn_days = models.PositiveSmallIntegerField(default=15)
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=100)

    class Meta:
        ordering = ["target", "position", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "target", "name"], name="maintenance_type_name_unique_per_target"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class MaintenancePlan(OrganizationScopedModel, TimeStampedModel):
    """One maintenance type followed on one truck (or its frigo unit), or on one cold room.

    `last_done_on` / `last_done_km` are copied from the latest `MaintenanceRecord` (or typed once when the plan is
    made, for a job done before the app): the next one is due from there.
    """

    type = models.ForeignKey(MaintenanceType, on_delete=models.PROTECT, related_name="plans")
    # By name, not by import (ARCHITECTURE §3). A truck for the truck and frigo types, a cold room for the others.
    truck = models.ForeignKey("fleet.Truck", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    location = models.ForeignKey(
        "inventory.StockLocation", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # Empty: the type's interval.
    every_km = models.PositiveIntegerField(null=True, blank=True)
    every_months = models.PositiveSmallIntegerField(null=True, blank=True)
    last_done_on = models.DateField(null=True, blank=True)
    last_done_km = models.PositiveIntegerField(null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["type__target", "type__position", "type__name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "type", "truck"],
                condition=models.Q(truck__isnull=False),
                name="one_plan_per_type_and_truck",
            ),
            models.UniqueConstraint(
                fields=["organization", "type", "location"],
                condition=models.Q(location__isnull=False),
                name="one_plan_per_type_and_location",
            ),
            models.CheckConstraint(
                condition=(models.Q(truck__isnull=False) & models.Q(location__isnull=True))
                | (models.Q(truck__isnull=True) & models.Q(location__isnull=False)),
                name="plan_on_a_truck_or_a_location",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.type.name} · {self.truck_id or self.location_id}"


class MaintenancePaymentMethod(models.TextChoices):
    """How a maintenance job or a paper was paid: the expenses' list (D-043)."""

    CASH = "cash", _("Espèces")
    CHEQUE = "cheque", _("Chèque")
    TRANSFER = "transfer", _("Virement")
    BILL = "bill", _("Traite")
    OTHER = "other", _("Autre")


class MaintenanceRecord(OrganizationScopedModel, TimeStampedModel):
    """ "Entretien effectué": a job done on a plan, with its cost. Append-only; its cost is an approved expense of
    the general overhead (owner answer 6: not charged to the lots)."""

    plan = models.ForeignKey(MaintenancePlan, on_delete=models.PROTECT, related_name="records")
    done_on = models.DateField()
    # The compteur when it was done (truck types); empty for a frigo unit or a cold room.
    km = models.PositiveIntegerField(null=True, blank=True)
    garage = models.CharField(max_length=150, blank=True)
    note = models.CharField(max_length=300, blank=True)
    cost = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    # The expense the cost made (by name, not by import); empty when it cost nothing.
    expense = models.ForeignKey("expenses.Expense", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-done_on", "-id"]

    def __str__(self) -> str:
        return f"{self.plan_id} · {self.done_on}"


# ---- Papers with expiry dates (P10-T04) ----


class PaperKind(models.TextChoices):
    # A truck's papers (owner answer 5).
    INSURANCE = "insurance", _("Assurance")
    VIGNETTE = "vignette", _("Vignette")
    TECHNICAL_VISIT = "technical_visit", _("Visite technique")
    FRIGO_CERTIFICATE = "frigo_certificate", _("Certificat engin frigorifique")
    EXTINGUISHER = "extinguisher", _("Extincteur")
    # A person's papers.
    LICENCE = "licence", _("Permis de conduire")
    MEDICAL = "medical", _("Certificat médical")
    HEALTH_CARD = "health_card", _("Carnet sanitaire")


TRUCK_PAPERS = (
    PaperKind.INSURANCE,
    PaperKind.VIGNETTE,
    PaperKind.TECHNICAL_VISIT,
    PaperKind.FRIGO_CERTIFICATE,
    PaperKind.EXTINGUISHER,
)
PERSON_PAPERS = (PaperKind.LICENCE, PaperKind.MEDICAL, PaperKind.HEALTH_CARD)
# Without these valid the truck does not go out (owner answer 5b), unless the owner allows the day.
BLOCKING_PAPERS = (PaperKind.INSURANCE, PaperKind.TECHNICAL_VISIT)


def paper_scan_path(paper: "Paper", filename: str) -> str:
    extension = ".pdf" if filename.lower().endswith(".pdf") else ".webp"
    return f"papers/{paper.organization_id}/{uuid.uuid4().hex}{extension}"


class Paper(OrganizationScopedModel, TimeStampedModel):
    """One paper of a truck or a person, valid until `expires_on` (P10-T04).

    A renewal is a new row; the one valid the longest is the current one. Append-only: a typing mistake is fixed by
    typing the paper again (the newest row of the same validity wins).
    """

    kind = models.CharField(max_length=20, choices=PaperKind.choices)
    truck = models.ForeignKey("fleet.Truck", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    employee = models.ForeignKey("hr.Employee", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    number = models.CharField(max_length=60, blank=True)
    # The insurer, the ATTT centre, the doctor…
    issuer = models.CharField(max_length=150, blank=True)
    issued_on = models.DateField(null=True, blank=True)
    expires_on = models.DateField()
    scan = models.FileField(upload_to=paper_scan_path, blank=True)
    cost = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    expense = models.ForeignKey("expenses.Expense", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    note = models.CharField(max_length=300, blank=True)
    recorded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-expires_on", "-id"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(truck__isnull=False) & models.Q(employee__isnull=True))
                | (models.Q(truck__isnull=True) & models.Q(employee__isnull=False)),
                name="paper_of_a_truck_or_a_person",
            ),
        ]
        indexes = [models.Index(fields=["organization", "kind", "expires_on"], name="paper_kind_expiry")]

    def __str__(self) -> str:
        return f"{self.kind} · {self.expires_on}"


class TruckDayAllowance(OrganizationScopedModel, TimeStampedModel):
    """The owner lets a truck go out one day although its assurance or visite technique has expired (owner answer
    5b), with the reason. Kept as the history; one per truck and day."""

    truck = models.ForeignKey("fleet.Truck", on_delete=models.PROTECT, related_name="+")
    date = models.DateField()
    reason = models.CharField(max_length=300)
    allowed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")

    class Meta:
        ordering = ["-date", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "truck", "date"], name="one_allowance_per_truck_day"),
        ]
