"""Every write on trucks goes through these functions (ARCHITECTURE §3)."""

import datetime as dt
import re
from datetime import date as date_type
from datetime import datetime
from decimal import Decimal
from typing import Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import Membership, Organization, Role, User
from apps.inventory import services as inventory
from apps.inventory.services import LocationKind

from .models import DayFund, DriverDay, LocationPing, Truck, TruckAssignment, TruckCondition


class _Unchanged:
    """Marks an argument that was not given, where None has a meaning (no driver)."""


UNCHANGED = _Unchanged()


def normalized_plate(value: str) -> str:
    """A plate in capitals with single spaces: "123 tu  4567" → "123 TU 4567"."""
    return re.sub(r"\s+", " ", value).strip().upper()


def _snapshot(truck: Truck) -> dict[str, Any]:
    return {
        "name": truck.location.name,
        "plate": truck.plate,
        "driver": truck.driver.username if truck.driver else None,
        "condition": truck.condition,
    }


def _clean_truck(truck: Truck) -> None:
    errors: dict[str, str] = {}
    truck.plate = normalized_plate(truck.plate)
    others = Truck.objects.for_organization(truck.organization).exclude(pk=truck.pk)
    if not truck.plate:
        errors["plate"] = _("L'immatriculation est obligatoire.")
    elif others.filter(plate=truck.plate).exists():
        errors["plate"] = _("Un autre camion a déjà cette immatriculation.")
    if truck.driver is not None:
        is_driver = Membership.objects.filter(
            organization=truck.organization, user=truck.driver, role=Role.DRIVER, is_active=True
        ).exists()
        if not is_driver:
            errors["driver"] = _("Ce compte n'est pas un chauffeur de la société.")
        elif not truck.is_active:
            errors["driver"] = _("Un camion archivé n'a pas de chauffeur.")
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def create_truck(
    *,
    organization: Organization,
    actor: User | None,
    name: str,
    plate: str,
    driver: User | None = None,
    condition: str = TruckCondition.OK,
) -> Truck:
    """A new truck, with the stock location that holds its goods."""
    truck = Truck(organization=organization, plate=plate, driver=driver, condition=condition)
    _clean_truck(truck)
    truck.location = inventory.create_location(
        organization=organization, actor=actor, kind=LocationKind.TRUCK, name=name
    )
    truck.save()
    audit.record(organization=organization, actor=actor, action="truck.created", target=truck, after=_snapshot(truck))
    return truck


@transaction.atomic
def update_truck(
    *,
    truck: Truck,
    actor: User | None,
    name: str | None = None,
    plate: str | None = None,
    driver: User | _Unchanged | None = UNCHANGED,
    condition: str | None = None,
) -> Truck:
    """Rename a truck, change its plate, give it to another driver (`driver=None` takes it back), or put it in
    maintenance or break it down (a driver cannot take it then, D-163)."""
    truck = Truck.objects.select_for_update().select_related("location").get(pk=truck.pk)
    before = _snapshot(truck)
    if plate is not None:
        truck.plate = plate
    if not isinstance(driver, _Unchanged):
        truck.driver = driver
    if condition is not None and condition != truck.condition:
        if condition not in TruckCondition.values:
            raise ValidationError({"condition": _("État du camion inconnu.")})
        truck.condition = condition
        if condition != TruckCondition.OK:
            # Days still to come lose their assignment; a past day keeps its own.
            for assignment in truck.assignments.filter(date__gte=timezone.localdate()):
                _delete_assignment(assignment=assignment, actor=actor)
    _clean_truck(truck)
    if name is not None:
        truck.location = inventory.update_location(location=truck.location, actor=actor, name=name)
    truck.save()
    after = _snapshot(truck)
    changed = [field for field in after if after[field] != before[field]]
    if changed:
        audit.record(
            organization=truck.organization,
            actor=actor,
            action="truck.updated",
            target=truck,
            before={field: before[field] for field in changed},
            after={field: after[field] for field in changed},
        )
    return truck


@transaction.atomic
def set_truck_active(*, truck: Truck, actor: User | None, is_active: bool) -> Truck:
    """Archive a truck (sold, broken down for good) with its location, or bring it back.

    Archiving takes the truck back from its usual driver and from the days still to come.
    """
    truck = Truck.objects.select_for_update().select_related("location").get(pk=truck.pk)
    if truck.is_active == is_active:
        return truck
    before = _snapshot(truck)
    truck.is_active = is_active
    if not is_active:
        truck.driver = None
        # Days still to come lose their assignment; past days keep theirs.
        for assignment in truck.assignments.filter(date__gte=timezone.localdate()):
            _delete_assignment(assignment=assignment, actor=actor)
    truck.save(update_fields=["is_active", "driver", "updated_at"])
    inventory.set_location_active(location=truck.location, actor=actor, is_active=is_active)
    audit.record(
        organization=truck.organization,
        actor=actor,
        action="truck.restored" if is_active else "truck.archived",
        target=truck,
        before={"driver": before["driver"]} if before["driver"] else None,
    )
    return truck


def _person(user: User) -> str:
    return f"{user.first_name} {user.last_name}".strip() or user.username


def _assignment_snapshot(assignment: TruckAssignment) -> dict[str, Any]:
    return {
        "truck": assignment.truck.location.name,
        "driver": assignment.driver.username if assignment.driver else None,
        "date": assignment.date.isoformat(),
    }


def _delete_assignment(*, assignment: TruckAssignment, actor: User | None) -> None:
    """Remove one assignment and keep what it was in the audit entry."""
    audit.record(
        organization=assignment.organization,
        actor=actor,
        action="truck_assignment.removed",
        before=_assignment_snapshot(assignment),
    )
    assignment.delete()


@transaction.atomic
def assign_truck(
    *,
    organization: Organization,
    actor: User | None,
    truck: Truck,
    driver: User | None,
    date: date_type,
    replace: bool = False,
) -> TruckAssignment:
    """Say that `driver` takes `truck` on `date` (D-046). No driver leaves the truck free that day, also for its
    usual driver (D-163); a driver may then take it.

    One driver per truck and one truck per driver each day: a second claim is refused with a clear message.
    With `replace`, the driver's other truck of that day is swapped for this one (a driver changing their
    own mind); the truck must still be free. Asking again for the same pair changes nothing.
    """
    truck = Truck.objects.for_organization(organization).select_for_update().select_related("location").get(pk=truck.pk)
    errors: dict[str, str] = {}
    if not truck.is_active:
        errors["truck"] = _("Ce camion est archivé.")
    elif truck.condition != TruckCondition.OK:
        errors["truck"] = _("%(truck)s est %(condition)s : il ne se prend pas.") % {
            "truck": truck.location.name,
            "condition": str(TruckCondition(truck.condition).label).lower(),
        }
    if (
        driver is not None
        and not Membership.objects.filter(
            organization=organization, user=driver, role=Role.DRIVER, is_active=True
        ).exists()
    ):
        errors["driver"] = _("Ce compte n'est pas un chauffeur de la société.")
    if errors:
        raise ValidationError(errors)

    # Locking the truck above serializes claims on one truck; the unique constraints back up the driver side.
    day = TruckAssignment.objects.for_organization(organization).filter(date=date).select_related("truck__location")
    on_truck = day.filter(truck=truck).select_related("driver").first()
    shown_date = date.strftime("%d/%m/%Y")
    if driver is None:
        return _free_truck(organization, actor, truck=truck, date=date, on_truck=on_truck)
    of_driver = day.filter(driver=driver).first()
    if on_truck is not None and on_truck.driver_id == driver.pk:
        return on_truck
    if on_truck is not None and on_truck.driver is not None:
        raise ValidationError(
            {
                "truck": _("%(truck)s est déjà attribué à %(driver)s le %(date)s.")
                % {"truck": truck.location.name, "driver": _person(on_truck.driver), "date": shown_date}
            }
        )
    if of_driver is not None and not replace:
        raise ValidationError(
            {
                "driver": _("%(driver)s conduit déjà %(truck)s le %(date)s.")
                % {"driver": _person(driver), "truck": of_driver.truck.location.name, "date": shown_date}
            }
        )
    if on_truck is not None:
        # The truck was left free that day: the driver takes it (their other truck of the day, if any, is let go).
        if of_driver is not None:
            _delete_assignment(assignment=of_driver, actor=actor)
        on_truck.driver = driver
        on_truck.save(update_fields=["driver", "updated_at"])
        audit.record(
            organization=organization,
            actor=actor,
            action="truck_assignment.changed",
            target=on_truck,
            before={"driver": None},
            after={"driver": driver.username},
        )
        return on_truck
    if of_driver is not None:
        before = of_driver.truck.location.name
        of_driver.truck = truck
        of_driver.save(update_fields=["truck", "updated_at"])
        audit.record(
            organization=organization,
            actor=actor,
            action="truck_assignment.changed",
            target=of_driver,
            before={"truck": before},
            after={"truck": truck.location.name},
        )
        return of_driver
    assignment = TruckAssignment.objects.create(organization=organization, truck=truck, driver=driver, date=date)
    audit.record(
        organization=organization,
        actor=actor,
        action="truck_assignment.created",
        target=assignment,
        after=_assignment_snapshot(assignment),
    )
    return assignment


def _free_truck(
    organization: Organization,
    actor: User | None,
    *,
    truck: Truck,
    date: date_type,
    on_truck: TruckAssignment | None,
) -> TruckAssignment:
    """Leave a truck without any driver on a date, whoever its usual driver is."""
    if on_truck is None:
        assignment = TruckAssignment.objects.create(organization=organization, truck=truck, driver=None, date=date)
        audit.record(
            organization=organization,
            actor=actor,
            action="truck_assignment.created",
            target=assignment,
            after=_assignment_snapshot(assignment),
        )
        return assignment
    if on_truck.driver_id is not None:
        before = on_truck.driver.username if on_truck.driver else None
        on_truck.driver = None
        on_truck.save(update_fields=["driver", "updated_at"])
        audit.record(
            organization=organization,
            actor=actor,
            action="truck_assignment.changed",
            target=on_truck,
            before={"driver": before},
            after={"driver": None},
        )
    return on_truck


@transaction.atomic
def unassign_truck(*, assignment: TruckAssignment, actor: User | None) -> None:
    """Take a day's assignment back; the truck falls back to its usual driver for that day."""
    assignment = TruckAssignment.objects.select_related("truck__location", "driver", "organization").get(
        pk=assignment.pk
    )
    _delete_assignment(assignment=assignment, actor=actor)


@transaction.atomic
def open_driver_day(
    *,
    organization: Organization,
    actor: User,
    truck: Truck,
    opening_cash: Decimal,
    date: date_type,
    purchase_float: Decimal = Decimal("0.000"),
) -> DriverDay:
    """Open the driver's day on their truck with the cash they start with, and the money given for purchases at
    the port (D-158). One day per driver and date: asking again changes nothing, also once its closing is sent
    (only a new load opens a sent day again, D-134)."""
    if opening_cash < 0:
        raise ValidationError({"opening_cash": _("Le fonds de caisse ne peut pas être négatif.")})
    if purchase_float < 0:
        raise ValidationError({"purchase_float": _("L'argent pour les achats ne peut pas être négatif.")})
    existing = DriverDay.objects.for_organization(organization).filter(driver=actor, date=date).first()
    if existing is not None:
        return existing
    if truck.condition != TruckCondition.OK:
        raise ValidationError({"truck": _("Ce camion n'est pas disponible : demandez au bureau.")})
    day = DriverDay.objects.create(
        organization=organization,
        truck=truck,
        driver=actor,
        date=date,
        opening_cash=opening_cash,
        purchase_float=purchase_float,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="driver_day.opened",
        target=day,
        after={
            "truck": truck.location.name,
            "date": str(date),
            "opening_cash": str(opening_cash),
            "purchase_float": str(purchase_float),
        },
    )
    return day


@transaction.atomic
def set_day_fund(
    *,
    organization: Organization,
    actor: User,
    driver: User,
    date: date_type,
    opening_cash: Decimal,
    purchase_float: Decimal = Decimal("0.000"),
) -> DayFund:
    """The office sets the cash it hands a driver for a day (D-203). It changes freely until the driver accepts it
    (which starts the day). Once started, the accepted cash stays as it is and only the money for purchases changes,
    and only the office changes it (D-248); a day whose closing is sent keeps its figures."""
    errors: dict[str, str] = {}
    if opening_cash < 0:
        errors["opening_cash"] = _("Le fonds de caisse ne peut pas être négatif.")
    if purchase_float < 0:
        errors["purchase_float"] = _("L'argent pour les achats ne peut pas être négatif.")
    if not Membership.objects.filter(organization=organization, user=driver, role=Role.DRIVER, is_active=True).exists():
        errors["driver"] = _("Chauffeur inconnu.")
    if errors:
        raise ValidationError(errors)
    fund, _created = DayFund.objects.select_for_update().get_or_create(
        organization=organization, driver=driver, date=date
    )
    day = DriverDay.objects.select_for_update().filter(organization=organization, driver=driver, date=date).first()
    if day is not None:
        if opening_cash != day.opening_cash:
            raise ValidationError(
                {"opening_cash": _("Le chauffeur a déjà accepté son fonds de caisse : il ne change plus.")}
            )
        if day.ended_at is not None and purchase_float != day.purchase_float:
            raise ValidationError(
                {"purchase_float": _("Sa journée est clôturée : l'argent pour les achats ne change plus.")}
            )
    before = {"opening_cash": str(fund.opening_cash), "purchase_float": str(fund.purchase_float)}
    fund.opening_cash = opening_cash
    fund.purchase_float = purchase_float
    fund.set_by = actor
    fund.save(update_fields=["opening_cash", "purchase_float", "set_by", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="day_fund.set",
        target=fund,
        before=before,
        after={"opening_cash": str(opening_cash), "purchase_float": str(purchase_float), "date": str(date)},
    )
    if day is not None and day.purchase_float != purchase_float:
        # The running day takes the new money at once; the phone shows it and cannot change it (D-248).
        day_before = str(day.purchase_float)
        day.purchase_float = purchase_float
        day.save(update_fields=["purchase_float", "updated_at"])
        audit.record(
            organization=organization,
            actor=actor,
            action="driver_day.purchase_float_set",
            target=day,
            before={"purchase_float": day_before},
            after={"purchase_float": str(purchase_float)},
        )
    return fund


@transaction.atomic
def accept_day_fund(*, organization: Organization, actor: User, truck: Truck, date: date_type) -> DriverDay:
    """The driver accepts the cash the office set for the day and so starts it with those amounts (D-203). Refused
    while the office has set nothing. Asking again returns the day unchanged, as `open_driver_day` does."""
    fund = DayFund.objects.select_for_update().filter(organization=organization, driver=actor, date=date).first()
    existing = DriverDay.objects.for_organization(organization).filter(driver=actor, date=date).first()
    if existing is not None:
        return existing
    if fund is None:
        raise ValidationError(
            {"opening_cash": _("Le bureau n'a pas encore indiqué votre fonds de caisse : appelez le bureau.")}
        )
    day = open_driver_day(
        organization=organization,
        actor=actor,
        truck=truck,
        opening_cash=fund.opening_cash,
        purchase_float=fund.purchase_float,
        date=date,
    )
    fund.accepted_at = timezone.now()
    fund.save(update_fields=["accepted_at", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="day_fund.accepted",
        target=fund,
        after={"opening_cash": str(fund.opening_cash), "purchase_float": str(fund.purchase_float)},
    )
    return day


def end_driver_day(*, driver_day: DriverDay, ended_at: datetime) -> DriverDay:
    """The driver sent the day's closing: the day is over and its records stop here (D-134). Called inside the
    closing's transaction, on a locked row; ending a day already ended (sent again) keeps its end. The office's
    cash for that driver and day is reset to zero (D-242): the day keeps the amounts it started with."""
    if driver_day.ended_at is None:
        driver_day.ended_at = ended_at
        driver_day.save(update_fields=["ended_at", "updated_at"])
        _reset_day_fund(driver_day)
    return driver_day


def _reset_day_fund(driver_day: DriverDay) -> None:
    """Set the driver's "Fonds de caisse" and "Argent pour les achats" of that day back to zero (D-242). The fund
    row stays, with its acceptance, so the office still sees the day was started."""
    fund = (
        DayFund.objects.select_for_update()
        .filter(organization=driver_day.organization, driver=driver_day.driver, date=driver_day.date)
        .first()
    )
    if fund is None or (fund.opening_cash == 0 and fund.purchase_float == 0):
        return
    before = {"opening_cash": str(fund.opening_cash), "purchase_float": str(fund.purchase_float)}
    fund.opening_cash = Decimal("0.000")
    fund.purchase_float = Decimal("0.000")
    fund.save(update_fields=["opening_cash", "purchase_float", "updated_at"])
    audit.record(
        organization=driver_day.organization,
        actor=None,
        action="day_fund.reset",
        target=fund,
        before=before,
        after={"opening_cash": "0.000", "purchase_float": "0.000", "date": str(driver_day.date)},
    )


def reopen_driver_day(*, driver_day: DriverDay) -> DriverDay:
    """A new load opened the sent day again (D-134): it runs until its closing is sent again. Called inside the
    reopening's transaction, on a locked row."""
    if driver_day.ended_at is not None:
        driver_day.ended_at = None
        driver_day.save(update_fields=["ended_at", "updated_at"])
    return driver_day


# A phone's clock may be a little ahead: a point further in the future is refused.
PING_CLOCK_TOLERANCE = dt.timedelta(minutes=5)


@transaction.atomic
def record_location_pings(*, driver_day: DriverDay, points: list[dict[str, Any]]) -> int:
    """Store the GPS points the driver's phone sends (D-164): each is `{client_uuid, recorded_at, latitude,
    longitude, accuracy}`. A point already stored (same `client_uuid`) is skipped, so a resent batch is safe. A
    point dated after the day's sent closing, or in the future, is dropped: the day is followed while it runs.
    Returns how many points were kept from this batch (new or already stored)."""
    driver_day = DriverDay.objects.select_for_update().get(pk=driver_day.pk)
    latest = timezone.now() + PING_CLOCK_TOLERANCE
    kept: list[dict[str, Any]] = [
        point
        for point in points
        if point["recorded_at"] <= latest
        and (driver_day.ended_at is None or point["recorded_at"] <= driver_day.ended_at)
    ]
    LocationPing.objects.bulk_create(
        [
            LocationPing(
                organization=driver_day.organization,
                driver_day=driver_day,
                client_uuid=point["client_uuid"],
                recorded_at=point["recorded_at"],
                latitude=point["latitude"],
                longitude=point["longitude"],
                accuracy=point.get("accuracy"),
            )
            for point in kept
        ],
        ignore_conflicts=True,
    )
    return len(kept)
