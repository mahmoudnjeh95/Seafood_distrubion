"""Reads of the maintenance module (P10, D-295)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from django.db.models import Count, Max, Min, Q, QuerySet
from django.utils import timezone

from apps.core.models import Organization
from apps.fleet import selectors as fleet
from apps.inventory import selectors as inventory

from .models import (
    MaintenancePlan,
    MaintenanceRecord,
    MaintenanceSettings,
    MaintenanceTarget,
    MaintenanceType,
    OdometerReading,
)

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay, Truck
    from apps.inventory.models import StockLocation


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


# ---- Maintenance types and plans (P10-T02, P10-T03) ----

type PlanState = Literal["ok", "soon", "late", "unknown"]
# The km per day are worked out from the readings of the last 60 days.
AVERAGE_WINDOW_DAYS = 60


def add_months(day: dt.date, count: int) -> dt.date:
    """The same day `count` months later; the month's last day when it has fewer days (31 Jan + 1 = 28/29 Feb)."""
    month_index = day.month - 1 + count
    year, month = day.year + month_index // 12, month_index % 12 + 1
    return dt.date(year, month, min(day.day, calendar.monthrange(year, month)[1]))


def types_of(organization: Organization, *, target: str | None = None) -> QuerySet[MaintenanceType]:
    """The maintenance types, by target then position."""
    types = MaintenanceType.objects.for_organization(organization)
    return types.filter(target=target) if target is not None else types


def type_of(organization: Organization, type_id: int) -> MaintenanceType:
    """One type. Raises MaintenanceType.DoesNotExist outside the organization."""
    return MaintenanceType.objects.for_organization(organization).get(pk=type_id)


def plans_of(
    organization: Organization, *, truck_id: int | None = None, location_id: int | None = None
) -> QuerySet[MaintenancePlan]:
    """The active plans, of one truck or one cold room when asked."""
    plans = (
        MaintenancePlan.objects.for_organization(organization)
        .filter(is_active=True, type__is_active=True)
        .select_related("type", "truck__location", "location")
    )
    if truck_id is not None:
        plans = plans.filter(truck_id=truck_id)
    if location_id is not None:
        plans = plans.filter(location_id=location_id)
    return plans


def plan_of(organization: Organization, plan_id: int) -> MaintenancePlan:
    """One plan. Raises MaintenancePlan.DoesNotExist outside the organization."""
    return (
        MaintenancePlan.objects.for_organization(organization)
        .select_related("type", "truck__location", "location")
        .get(pk=plan_id)
    )


def records_of_plan(organization: Organization, *, plan_id: int) -> QuerySet[MaintenanceRecord]:
    """The jobs done on one plan, the latest first."""
    return (
        MaintenanceRecord.objects.for_organization(organization)
        .filter(plan_id=plan_id)
        .select_related("recorded_by", "expense")
        .order_by("-done_on", "-id")
    )


def km_per_day(organization: Organization, *, truck_id: int, today: dt.date | None = None) -> float | None:
    """How many km the truck drives a day, from its readings of the last 60 days; None with too few readings."""
    today = today or timezone.localdate()
    since = timezone.now() - dt.timedelta(days=AVERAGE_WINDOW_DAYS)
    span = (
        OdometerReading.objects.for_organization(organization)
        .filter(truck_id=truck_id, created_at__gte=since)
        .aggregate(low=Min("km"), high=Max("km"), first=Min("created_at"), last=Max("created_at"))
    )
    if span["first"] is None or span["last"] is None:
        return None
    days = (timezone.localdate(span["last"]) - timezone.localdate(span["first"])).days
    if days < 1 or span["high"] <= span["low"]:
        return None
    return float(span["high"] - span["low"]) / days


@dataclass(frozen=True)
class PlanStatus:
    """Where a plan stands today: due by km and/or by date, whichever comes first."""

    plan: MaintenancePlan
    every_km: int | None
    every_months: int | None
    current_km: int | None
    due_km: int | None
    km_left: int | None
    due_on: dt.date | None
    days_left: int | None
    # When the km run out at the truck's usual pace (None without enough readings).
    estimated_on: dt.date | None
    state: PlanState


def plan_status(
    plan: MaintenancePlan,
    *,
    current_km: int | None,
    pace: float | None,
    today: dt.date | None = None,
) -> PlanStatus:
    """The status of one plan. `current_km` is the truck's last reading, `pace` its km per day."""
    today = today or timezone.localdate()
    kind = plan.type
    every_km = (plan.every_km or kind.every_km) if kind.target == MaintenanceTarget.TRUCK else None
    every_months = plan.every_months or kind.every_months
    due_km = km_left = days_left = None
    due_on = estimated_on = None
    if every_km and plan.last_done_km is not None:
        due_km = plan.last_done_km + every_km
        if current_km is not None:
            km_left = due_km - current_km
            if pace:
                estimated_on = today + dt.timedelta(days=max(0, int(km_left / pace)))
    if every_months and plan.last_done_on is not None:
        due_on = add_months(plan.last_done_on, every_months)
        days_left = (due_on - today).days
    state: PlanState
    if plan.last_done_on is None:
        state = "unknown"  # never done in the app: the office types when it was last done
    elif (km_left is not None and km_left <= 0) or (days_left is not None and days_left <= 0):
        state = "late"
    elif (km_left is not None and km_left <= kind.warn_km) or (days_left is not None and days_left <= kind.warn_days):
        state = "soon"
    else:
        state = "ok"
    return PlanStatus(
        plan=plan,
        every_km=every_km,
        every_months=every_months,
        current_km=current_km,
        due_km=due_km,
        km_left=km_left,
        due_on=due_on,
        days_left=days_left,
        estimated_on=estimated_on,
        state=state,
    )


def plan_statuses(
    organization: Organization, *, truck_id: int | None = None, location_id: int | None = None
) -> list[PlanStatus]:
    """The status of every active plan (of one truck or cold room when asked), with each truck's compteur."""
    plans = list(plans_of(organization, truck_id=truck_id, location_id=location_id))
    trucks = {plan.truck_id for plan in plans if plan.truck_id is not None}
    current: dict[int, int | None] = {}
    pace: dict[int, float | None] = {}
    for truck in trucks:
        last = last_reading(organization, truck_id=truck)
        current[truck] = last.km if last is not None else None
        pace[truck] = km_per_day(organization, truck_id=truck)
    return [
        plan_status(
            plan,
            current_km=current.get(plan.truck_id) if plan.truck_id is not None else None,
            pace=pace.get(plan.truck_id) if plan.truck_id is not None else None,
        )
        for plan in plans
    ]


COLD_ROOM_KIND = "cold_room"  # `inventory.LocationKind.COLD_ROOM`


def cold_rooms_of(organization: Organization) -> list["StockLocation"]:
    """The company's active cold rooms, for their frigo service (P10-T03)."""
    return list(inventory.locations_of(organization, kinds=[COLD_ROOM_KIND]))
