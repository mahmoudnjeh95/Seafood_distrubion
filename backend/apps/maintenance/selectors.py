"""Reads of the maintenance module (P10, D-295)."""

import calendar
import datetime as dt
from dataclasses import dataclass
from typing import TYPE_CHECKING, Literal

from django.db.models import Count, Max, Min, Q, QuerySet
from django.utils import timezone

from apps.core.models import Organization
from apps.fleet import selectors as fleet
from apps.hr import selectors as hr
from apps.inventory import selectors as inventory

from .models import (
    BLOCKING_PAPERS,
    PERSON_PAPERS,
    TRUCK_PAPERS,
    MaintenancePlan,
    MaintenanceRecord,
    MaintenanceSettings,
    MaintenanceTarget,
    MaintenanceType,
    OdometerReading,
    Paper,
    PaperKind,
    TruckDayAllowance,
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


# ---- Papers with expiry dates (P10-T04) ----

type PaperState = Literal["ok", "soon", "expired", "missing"]


def papers_of(
    organization: Organization, *, truck_id: int | None = None, employee_id: int | None = None
) -> QuerySet[Paper]:
    """Every paper typed, of one truck or person when asked, the one valid the longest first."""
    papers = Paper.objects.for_organization(organization).select_related("truck__location", "employee", "recorded_by")
    if truck_id is not None:
        papers = papers.filter(truck_id=truck_id)
    if employee_id is not None:
        papers = papers.filter(employee_id=employee_id)
    return papers.order_by("-expires_on", "-id")


def paper_of(organization: Organization, paper_id: int) -> Paper:
    """One paper. Raises Paper.DoesNotExist outside the organization."""
    return Paper.objects.for_organization(organization).get(pk=paper_id)


@dataclass(frozen=True)
class PaperStatus:
    """A paper a truck or a person must hold, and where it stands: the current one (valid the longest), if any."""

    kind: str
    truck_id: int | None
    employee_id: int | None
    subject: str
    paper: Paper | None
    days_left: int | None
    state: PaperState


def _state(days_left: int | None, warn: int) -> PaperState:
    if days_left is None:
        return "missing"
    if days_left < 0:
        return "expired"
    return "soon" if days_left <= warn else "ok"


def paper_board(organization: Organization, *, today: dt.date | None = None) -> list[PaperStatus]:
    """Each active truck's and each active employee's papers (owner answer 5), the current one of each kind."""
    today = today or timezone.localdate()
    warn = max(settings_of(organization).paper_warn_days or [0])
    current: dict[tuple[str, int | None, int | None], Paper] = {}
    for typed in Paper.objects.for_organization(organization).order_by("expires_on", "id"):
        current[(typed.kind, typed.truck_id, typed.employee_id)] = typed  # the one valid the longest stays
    rows: list[PaperStatus] = []
    for truck in fleet.trucks_of(organization):
        for kind in TRUCK_PAPERS:
            paper = current.get((kind, truck.pk, None))
            days = (paper.expires_on - today).days if paper is not None else None
            rows.append(PaperStatus(kind, truck.pk, None, truck.location.name, paper, days, _state(days, warn)))
    for employee in hr.employees_of(organization):
        for kind in PERSON_PAPERS:
            paper = current.get((kind, None, employee.pk))
            days = (paper.expires_on - today).days if paper is not None else None
            rows.append(PaperStatus(kind, None, employee.pk, employee.name, paper, days, _state(days, warn)))
    return rows


def expired_blocking_papers(organization: Organization, *, truck_id: int, on: dt.date) -> list[str]:
    """The names of the truck's assurance and visite technique that are expired on that day, unless the owner allowed
    the day (owner answer 5b). A paper never typed blocks nothing: the office types them first."""
    if TruckDayAllowance.objects.for_organization(organization).filter(truck_id=truck_id, date=on).exists():
        return []
    expired = []
    for kind in BLOCKING_PAPERS:
        latest = (
            Paper.objects.for_organization(organization)
            .filter(truck_id=truck_id, kind=kind)
            .order_by("-expires_on", "-id")
            .first()
        )
        if latest is not None and latest.expires_on < on:
            expired.append(str(PaperKind(kind).label))
    return expired


def allowances_of(organization: Organization, *, truck_id: int) -> QuerySet[TruckDayAllowance]:
    """The days the owner let the truck go out with an expired paper, the latest first."""
    return (
        TruckDayAllowance.objects.for_organization(organization)
        .filter(truck_id=truck_id)
        .select_related("allowed_by")
        .order_by("-date", "-id")
    )


# ---- Warnings everywhere (P10-T05) ----

type AlertState = Literal["ok", "soon", "late"]
RANK: dict[str, int] = {"ok": 0, "unknown": 0, "missing": 0, "soon": 1, "late": 2, "expired": 2}


@dataclass(frozen=True)
class Alert:
    """One thing to do soon or late: a maintenance or a paper, on a truck, a cold room or a person."""

    what: Literal["plan", "paper"]
    state: AlertState
    subject: str
    truck_id: int | None
    location_id: int | None
    employee_id: int | None
    # The maintenance type's name, or the paper kind's label.
    label: str
    # The day it falls due (a plan by date or at the truck's pace, a paper's end of validity), if known.
    due_on: dt.date | None
    km_left: int | None
    days_left: int | None
    object_id: int


def alerts_of(organization: Organization, *, today: dt.date | None = None) -> list[Alert]:
    """Every maintenance and paper that is soon or late, the latest first."""
    today = today or timezone.localdate()
    alerts: list[Alert] = []
    for status in plan_statuses(organization):
        if status.state not in ("soon", "late"):
            continue
        plan = status.plan
        subject = plan.truck.location.name if plan.truck is not None else (plan.location.name if plan.location else "")
        candidates = [day for day in (status.due_on, status.estimated_on) if day is not None]
        alerts.append(
            Alert(
                what="plan",
                state="late" if status.state == "late" else "soon",
                subject=subject,
                truck_id=plan.truck_id,
                location_id=plan.location_id,
                employee_id=None,
                label=plan.type.name,
                due_on=min(candidates) if candidates else None,
                km_left=status.km_left,
                days_left=status.days_left,
                object_id=plan.pk,
            )
        )
    for row in paper_board(organization, today=today):
        if row.state not in ("soon", "expired") or row.paper is None:
            continue
        alerts.append(
            Alert(
                what="paper",
                state="late" if row.state == "expired" else "soon",
                subject=row.subject,
                truck_id=row.truck_id,
                location_id=None,
                employee_id=row.employee_id,
                label=str(PaperKind(row.kind).label),
                due_on=row.paper.expires_on,
                km_left=None,
                days_left=row.days_left,
                object_id=row.paper.pk,
            )
        )
    alerts.sort(key=lambda alert: (-RANK[alert.state], alert.due_on or dt.date.max, alert.subject))
    return alerts


def truck_alert_states(organization: Organization) -> dict[int, AlertState]:
    """The worst state of each truck that has something soon or late: the badge on its icon (owner answer 1)."""
    worst: dict[int, AlertState] = {}
    for alert in alerts_of(organization):
        if alert.truck_id is not None and RANK[alert.state] > RANK[worst.get(alert.truck_id, "ok")]:
            worst[alert.truck_id] = alert.state
    return worst


def driver_alerts(organization: Organization, *, user_id: int, truck_id: int | None) -> list[Alert]:
    """What the driver sees on the phone: his truck's maintenance and papers, and his own papers."""
    employee = hr.employees_of(organization).filter(user_id=user_id).first()
    return [
        alert
        for alert in alerts_of(organization)
        if (truck_id is not None and alert.truck_id == truck_id)
        or (employee is not None and alert.employee_id == employee.pk)
    ]
