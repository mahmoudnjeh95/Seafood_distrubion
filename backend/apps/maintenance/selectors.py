"""Reads of the maintenance module (P10, D-283)."""

from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.db.models import Count, Q, QuerySet

from apps.core.models import Organization
from apps.fleet import selectors as fleet

from .models import MaintenanceSettings, OdometerReading

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay, Truck


def settings_of(organization: Organization) -> MaintenanceSettings:
    """The organization's maintenance settings; the defaults when nothing was saved yet (not written on read)."""
    found = MaintenanceSettings.objects.for_organization(organization).first()
    return found if found is not None else MaintenanceSettings(organization=organization)


def readings_of_truck(organization: Organization, *, truck_id: int) -> QuerySet[OdometerReading]:
    """Every compteur reading of one truck, the latest first, with who typed it."""
    return (
        OdometerReading.objects.for_organization(organization)
        .filter(truck_id=truck_id)
        .select_related("recorded_by", "driver_day")
        .order_by("-created_at", "-id")
    )


def last_reading(organization: Organization, *, truck_id: int) -> OdometerReading | None:
    """The truck's latest reading: the reference the next one is checked against."""
    return readings_of_truck(organization, truck_id=truck_id).first()


def reading_of(organization: Organization, reading_id: int) -> OdometerReading:
    """One reading. Raises OdometerReading.DoesNotExist outside the organization."""
    return OdometerReading.objects.for_organization(organization).select_related("truck").get(pk=reading_id)


def reading_of_day(driver_day: "DriverDay") -> OdometerReading | None:
    """The latest compteur the driver typed on that day, if any."""
    return (
        OdometerReading.objects.for_organization(driver_day.organization)
        .filter(driver_day=driver_day)
        .order_by("-created_at", "-id")
        .first()
    )


@dataclass(frozen=True)
class TruckOdometer:
    """One truck on the "Flotte & entretien" screen: its last compteur, and how many readings carry a warning."""

    truck: "Truck"
    last: OdometerReading | None
    warnings: int


def fleet_odometer(organization: Organization) -> list[TruckOdometer]:
    """Each active truck with its last reading, by name."""
    trucks = list(fleet.trucks_of(organization))
    readings = OdometerReading.objects.for_organization(organization).filter(truck__in=trucks)
    # PostgreSQL's DISTINCT ON: one latest row per truck, however many readings it has.
    latest = {
        reading.truck_id: reading
        for reading in readings.select_related("recorded_by")
        .order_by("truck_id", "-created_at", "-id")
        .distinct("truck_id")
    }
    warnings = {
        row["truck_id"]: row["count"]
        for row in readings.order_by().values("truck_id").annotate(count=Count("id", filter=~Q(warning="")))
    }
    return [TruckOdometer(truck=t, last=latest.get(t.pk), warnings=warnings.get(t.pk, 0)) for t in trucks]
