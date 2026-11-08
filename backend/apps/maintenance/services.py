"""Every write of the maintenance module goes through these functions (ARCHITECTURE §3, P10, D-295)."""

import datetime as dt
from decimal import Decimal
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.images import reencoded_photo
from apps.core.models import Organization, User
from apps.core.money import checked_amount
from apps.expenses import selectors as expense_selectors
from apps.expenses import services as expenses
from apps.fleet import selectors as fleet
from apps.notifications import services as notifications

from . import selectors
from .models import (
    PERSON_PAPERS,
    TRUCK_PAPERS,
    MaintenancePlan,
    MaintenanceRecord,
    MaintenanceSettings,
    MaintenanceTarget,
    MaintenanceType,
    MaintenanceWarningSent,
    OdometerReading,
    OdometerSource,
    OdometerWarning,
    Paper,
    PaperKind,
    TruckDayAllowance,
)

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay, Truck
    from apps.hr.models import Employee
    from apps.inventory.models import StockLocation

MAX_KM = 9_999_999  # a truck's compteur shows at most 7 digits


def _checked_km(km: int) -> int:
    if km < 0 or km > MAX_KM:
        raise ValidationError({"km": _("Tapez le nombre de km affiché au compteur.")})
    return km


def _save(reading: OdometerReading, photo: "UploadedFile[bytes] | None") -> OdometerReading:
    """Write the reading, and its photo first when there is one."""
    if photo is not None:
        reading.photo.save("photo.webp", reencoded_photo(photo), save=False)
    try:
        reading.save()
    except BaseException:
        # The file is written before the row: never leave it behind when the row is not written.
        if reading.photo.name:
            reading.photo.storage.delete(reading.photo.name)
        raise
    return reading


def _snapshot(reading: OdometerReading) -> dict[str, object]:
    return {
        "truck": reading.truck.location.name,
        "plate": reading.truck.plate,
        "km": reading.km,
        "driven_km": reading.driven_km,
        "warning": reading.warning,
        "source": reading.source,
        "photo": bool(reading.photo.name),
        "note": reading.note,
    }


@transaction.atomic
def record_driver_reading(
    *,
    driver_day: "DriverDay",
    actor: User,
    km: int,
    photo: "UploadedFile[bytes] | None" = None,
    note: str = "",
) -> OdometerReading:
    """The compteur the driver typed when sending his day (P10-T01). Refused below the truck's last reading (a typo:
    the office corrects a wrong last reading) and on a day already sent. More km since the last reading than the
    settings allow per day is kept, with a warning the office is told about."""
    km = _checked_km(km)
    driver_day = fleet.locked_driver_day(driver_day)
    if driver_day.ended_at is not None:
        raise ValidationError(_("Votre journée est déjà envoyée : le compteur ne se saisit plus."))
    truck = fleet.locked_truck(driver_day.truck)
    organization = driver_day.organization
    last = selectors.last_reading(organization, truck_id=truck.pk)
    driven: int | None = None
    warning = OdometerWarning.NONE
    if last is not None:
        if km < last.km:
            raise ValidationError(
                {"km": _("Le compteur ne peut pas être inférieur au dernier relevé : %(km)s km.") % {"km": last.km}}
            )
        driven = km - last.km
        days = max(1, (timezone.localdate() - timezone.localdate(last.created_at)).days)
        if driven > selectors.settings_of(organization).max_day_km * days:
            warning = OdometerWarning.BIG_JUMP
    reading = _save(
        OdometerReading(
            organization=organization,
            truck=truck,
            driver_day=driver_day,
            km=km,
            source=OdometerSource.DRIVER,
            note=note.strip()[:300],
            warning=warning,
            driven_km=driven,
            recorded_by=actor,
        ),
        photo,
    )
    audit.record(
        organization=organization, actor=actor, action="odometer.recorded", target=reading, after=_snapshot(reading)
    )
    return reading


@transaction.atomic
def correct_reading(
    *,
    organization: Organization,
    truck: "Truck",
    actor: User,
    km: int,
    note: str,
    photo: "UploadedFile[bytes] | None" = None,
) -> OdometerReading:
    """The office sets a truck's compteur (a wrong reading, a new truck, a compteur replaced): a new reading with its
    reason, which may be lower than the last one. It becomes the reference for the next reading."""
    km = _checked_km(km)
    note = note.strip()
    if not note:
        raise ValidationError({"note": _("Indiquez la raison de la correction.")})
    truck = fleet.locked_truck(truck)
    last = selectors.last_reading(organization, truck_id=truck.pk)
    reading = _save(
        OdometerReading(
            organization=organization,
            truck=truck,
            km=km,
            source=OdometerSource.OFFICE,
            note=note[:300],
            recorded_by=actor,
        ),
        photo,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="odometer.corrected",
        target=reading,
        before={"km": last.km if last is not None else None},
        after=_snapshot(reading),
    )
    return reading


@transaction.atomic
def update_settings(*, organization: Organization, actor: User, max_day_km: int) -> MaintenanceSettings:
    """Change the maintenance settings (Paramètres entretien)."""
    if max_day_km < 1 or max_day_km > 5000:
        raise ValidationError({"max_day_km": _("Entre 1 et 5 000 km par jour.")})
    found, _created = MaintenanceSettings.objects.select_for_update().get_or_create(organization=organization)
    before = {"max_day_km": found.max_day_km}
    found.max_day_km = max_day_km
    found.save(update_fields=["max_day_km", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="maintenance_settings.changed",
        target=found,
        before=before,
        after={"max_day_km": max_day_km},
    )
    return found


# ---- Maintenance types, plans and records (P10-T02, P10-T03) ----

# The types offered the first time (owner can change every value, answer 3). Usual intervals for a light diesel
# delivery truck; each truck's manual decides.
# (target, name, every_km, every_months, warn_km, warn_days)
DEFAULT_TYPES: tuple[tuple[str, str, int | None, int | None, int, int], ...] = (
    (MaintenanceTarget.TRUCK, "Vidange moteur et filtre à huile", 10_000, 6, 1000, 15),
    (MaintenanceTarget.TRUCK, "Filtre à air", 20_000, 12, 1000, 15),
    (MaintenanceTarget.TRUCK, "Filtre à gasoil", 20_000, 12, 1000, 15),
    (MaintenanceTarget.TRUCK, "Freins (plaquettes et liquide)", 20_000, 24, 1000, 15),
    (MaintenanceTarget.TRUCK, "Pneus (contrôle)", None, 1, 1000, 5),
    (MaintenanceTarget.TRUCK, "Courroie de distribution", 100_000, 60, 3000, 30),
    (MaintenanceTarget.TRUCK, "Batterie (contrôle)", None, 12, 1000, 15),
    (MaintenanceTarget.FRIGO, "Entretien du groupe frigo", None, 1, 0, 5),
    (MaintenanceTarget.COLD_ROOM, "Entretien de la chambre froide", None, 1, 0, 5),
)

# The expense category of each target's costs: the trucks' own one, the cold rooms' "Froid et stockage".
COST_CATEGORY = {
    MaintenanceTarget.TRUCK: "vehicles",
    MaintenanceTarget.FRIGO: "vehicles",
    MaintenanceTarget.COLD_ROOM: "cold_storage",
}


def _type_snapshot(kind: MaintenanceType) -> dict[str, object]:
    return {
        "name": kind.name,
        "target": kind.target,
        "every_km": kind.every_km,
        "every_months": kind.every_months,
        "warn_km": kind.warn_km,
        "warn_days": kind.warn_days,
        "is_active": kind.is_active,
    }


def _checked_type(
    organization: Organization,
    *,
    name: str,
    target: str,
    every_km: int | None,
    every_months: int | None,
    exclude_id: int | None = None,
) -> str:
    errors: dict[str, str] = {}
    name = " ".join(name.split())[:100]
    if not name:
        errors["name"] = _("Indiquez le nom de l'entretien.")
    elif (
        MaintenanceType.objects.for_organization(organization)
        .filter(target=target, name__iexact=name)
        .exclude(pk=exclude_id or 0)
        .exists()
    ):
        errors["name"] = _("Cet entretien existe déjà.")
    if target not in MaintenanceTarget.values:
        errors["target"] = _("Choix inconnu.")
    if target != MaintenanceTarget.TRUCK and every_km:
        errors["every_km"] = _("Un groupe frigo ou une chambre froide se suit en mois, pas en km.")
    if not every_km and not every_months:
        errors["every_months"] = _("Indiquez un intervalle en km ou en mois.")
    if every_months is not None and every_months > 120:
        errors["every_months"] = _("Au plus 120 mois.")
    if errors:
        raise ValidationError(errors)
    return name


@transaction.atomic
def add_default_types(*, organization: Organization, actor: User) -> int:
    """Add the suggested types the organization does not have yet (by name). Returns how many were added."""
    have = {(t.target, t.name.lower()) for t in MaintenanceType.objects.for_organization(organization)}
    added = 0
    for position, (target, name, every_km, every_months, warn_km, warn_days) in enumerate(DEFAULT_TYPES):
        if (target, name.lower()) in have:
            continue
        kind = MaintenanceType.objects.create(
            organization=organization,
            target=target,
            name=name,
            every_km=every_km,
            every_months=every_months,
            warn_km=warn_km,
            warn_days=warn_days,
            position=(position + 1) * 10,
        )
        audit.record(
            organization=organization,
            actor=actor,
            action="maintenance_type.created",
            target=kind,
            after=_type_snapshot(kind),
        )
        added += 1
    return added


@transaction.atomic
def create_type(
    *,
    organization: Organization,
    actor: User,
    name: str,
    target: str = MaintenanceTarget.TRUCK,
    every_km: int | None = None,
    every_months: int | None = None,
    warn_km: int = 1000,
    warn_days: int = 15,
) -> MaintenanceType:
    """A new kind of maintenance with its interval (km and/or months) and warning thresholds."""
    name = _checked_type(organization, name=name, target=target, every_km=every_km, every_months=every_months)
    kind = MaintenanceType.objects.create(
        organization=organization,
        name=name,
        target=target,
        every_km=every_km or None,
        every_months=every_months or None,
        warn_km=warn_km,
        warn_days=warn_days,
        position=1000,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="maintenance_type.created",
        target=kind,
        after=_type_snapshot(kind),
    )
    return kind


@transaction.atomic
def update_type(*, kind: MaintenanceType, actor: User, **changes: object) -> MaintenanceType:
    """Change a type's name, interval, thresholds or archive it (`is_active`). Its target never changes."""
    kind = MaintenanceType.objects.select_for_update().get(pk=kind.pk)
    before = _type_snapshot(kind)
    for field in ("name", "every_km", "every_months", "warn_km", "warn_days", "is_active"):
        if field in changes:
            setattr(kind, field, changes[field])
    kind.every_km = kind.every_km or None
    kind.every_months = kind.every_months or None
    kind.name = _checked_type(
        kind.organization,
        name=kind.name,
        target=kind.target,
        every_km=kind.every_km,
        every_months=kind.every_months,
        exclude_id=kind.pk,
    )
    kind.save()
    audit.record(
        organization=kind.organization,
        actor=actor,
        action="maintenance_type.changed",
        target=kind,
        before=before,
        after=_type_snapshot(kind),
    )
    return kind


def _plan_snapshot(plan: MaintenancePlan) -> dict[str, object]:
    return {
        "type": plan.type.name,
        "truck": plan.truck.location.name if plan.truck is not None else None,
        "location": plan.location.name if plan.location is not None else None,
        "every_km": plan.every_km,
        "every_months": plan.every_months,
        "last_done_on": plan.last_done_on.isoformat() if plan.last_done_on else None,
        "last_done_km": plan.last_done_km,
        "is_active": plan.is_active,
    }


def _checked_last_done(last_done_on: dt.date | None, last_done_km: int | None) -> None:
    if last_done_on is not None and last_done_on > timezone.localdate():
        raise ValidationError({"last_done_on": _("La date ne peut pas être dans le futur.")})
    if last_done_km is not None:
        _checked_km(last_done_km)


@transaction.atomic
def create_plan(
    *,
    organization: Organization,
    actor: User,
    kind: MaintenanceType,
    truck: "Truck | None" = None,
    location: "StockLocation | None" = None,
    every_km: int | None = None,
    every_months: int | None = None,
    last_done_on: dt.date | None = None,
    last_done_km: int | None = None,
) -> MaintenancePlan:
    """Follow a maintenance type on a truck (truck or frigo types) or a cold room. When it was last done may be typed
    once here, for a job done before the app; then each "Entretien effectué" moves it. Made again after it was
    stopped, the same plan starts again."""
    if kind.organization_id != organization.pk or not kind.is_active:
        raise ValidationError({"type": _("Entretien inconnu.")})
    on_room = kind.target == MaintenanceTarget.COLD_ROOM
    if on_room and (location is None or location.kind != selectors.COLD_ROOM_KIND):
        raise ValidationError({"location": _("Choisissez une chambre froide.")})
    if not on_room and truck is None:
        raise ValidationError({"truck": _("Choisissez un camion.")})
    for subject in (truck, location):
        if subject is not None and subject.organization_id != organization.pk:
            raise ValidationError({"truck": _("Camion inconnu.")})
    _checked_last_done(last_done_on, last_done_km)
    plan, created = MaintenancePlan.objects.select_for_update().get_or_create(
        organization=organization,
        type=kind,
        truck=None if on_room else truck,
        location=location if on_room else None,
        defaults={"is_active": True},
    )
    if not created and plan.is_active:
        raise ValidationError({"type": _("Cet entretien est déjà suivi ici.")})
    plan.is_active = True
    plan.every_km = (every_km or None) if not on_room and kind.target == MaintenanceTarget.TRUCK else None
    plan.every_months = every_months or None
    if last_done_on is not None:
        plan.last_done_on = last_done_on
    if last_done_km is not None:
        plan.last_done_km = last_done_km
    plan.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="maintenance_plan.created",
        target=plan,
        after=_plan_snapshot(plan),
    )
    return plan


@transaction.atomic
def update_plan(*, plan: MaintenancePlan, actor: User, **changes: object) -> MaintenancePlan:
    """Change a plan's own interval, its last done date and km (a mistake when it was made), or stop it
    (`is_active` false)."""
    plan = (
        MaintenancePlan.objects.select_for_update(of=("self",))
        .select_related("type", "truck__location", "location")
        .get(pk=plan.pk)
    )
    before = _plan_snapshot(plan)
    for field in ("every_km", "every_months", "last_done_on", "last_done_km", "is_active"):
        if field in changes:
            setattr(plan, field, changes[field])
    if plan.type.target != MaintenanceTarget.TRUCK:
        plan.every_km = None
    plan.every_km = plan.every_km or None
    plan.every_months = plan.every_months or None
    _checked_last_done(plan.last_done_on, plan.last_done_km)
    plan.save()
    audit.record(
        organization=plan.organization,
        actor=actor,
        action="maintenance_plan.changed",
        target=plan,
        before=before,
        after=_plan_snapshot(plan),
    )
    return plan


@transaction.atomic
def record_maintenance(
    *,
    plan: MaintenancePlan,
    actor: User,
    done_on: dt.date,
    km: int | None = None,
    garage: str = "",
    note: str = "",
    cost: Decimal | str | int = 0,
    payment_method: str = "cash",
) -> MaintenanceRecord:
    """ "Entretien effectué": the job is done, the next one is due from here. A cost makes an approved expense of the
    general overhead (owner answer 6), not a truck cost of the day: it is not charged to the lots. On a truck plan the
    compteur is the one typed, or the truck's last reading."""
    plan = (
        MaintenancePlan.objects.select_for_update(of=("self",))
        .select_related("type", "truck__location", "location")
        .get(pk=plan.pk)
    )
    organization = plan.organization
    if not plan.is_active:
        raise ValidationError(_("Cet entretien n'est plus suivi."))
    if done_on > timezone.localdate():
        raise ValidationError({"done_on": _("La date ne peut pas être dans le futur.")})
    on_truck = plan.type.target == MaintenanceTarget.TRUCK
    if on_truck:
        if km is None and plan.truck_id is not None:
            last = selectors.last_reading(organization, truck_id=plan.truck_id)
            km = last.km if last is not None else None
        if km is not None:
            _checked_km(km)
    else:
        km = None
    try:
        amount = checked_amount(cost)
    except (ValueError, TypeError):
        raise ValidationError({"cost": _("Indiquez un montant en DT, au millime près.")}) from None
    if amount < 0:
        raise ValidationError({"cost": _("Le coût ne peut pas être négatif.")})
    garage = " ".join(garage.split())[:150]
    subject = plan.truck.location.name if plan.truck is not None else (plan.location.name if plan.location else "")
    expense = None
    if amount > 0:
        expenses.ensure_default_categories(organization=organization)
        category = expense_selectors.category_by_code(organization, COST_CATEGORY[MaintenanceTarget(plan.type.target)])
        expense = expenses.create_expense(
            organization=organization,
            actor=actor,
            spent_on=done_on,
            category=category,
            amount=amount,
            payment_method=payment_method,
            description=f"{plan.type.name} · {subject}",
            payee=garage,
            notes=note,
            approve=True,
        )
    record = MaintenanceRecord.objects.create(
        organization=organization,
        plan=plan,
        done_on=done_on,
        km=km,
        garage=garage,
        note=note.strip()[:300],
        cost=amount,
        expense=expense,
        recorded_by=actor,
    )
    # A job typed late (an older date) does not move the plan back.
    if plan.last_done_on is None or done_on >= plan.last_done_on:
        plan.last_done_on = done_on
        if km is not None:
            plan.last_done_km = km
        plan.save(update_fields=["last_done_on", "last_done_km", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="maintenance.recorded",
        target=record,
        after={
            "type": plan.type.name,
            "subject": subject,
            "done_on": done_on.isoformat(),
            "km": km,
            "cost": str(amount),
            "expense": expense.number if expense is not None else None,
        },
    )
    return record


# ---- Papers with expiry dates (P10-T04) ----

MAX_SCAN_BYTES = 8 * 1024 * 1024


def _scan_content(upload: "UploadedFile[bytes]") -> tuple[ContentFile[bytes], str]:
    """A PDF kept as it is, or a photo turned upright, shrunk and saved as WebP; with the file name."""
    head = upload.read(5)
    upload.seek(0)
    if head == b"%PDF-":
        if upload.size is not None and upload.size > MAX_SCAN_BYTES:
            raise ValidationError({"scan": _("Le fichier dépasse 8 Mo.")})
        return ContentFile(upload.read()), "scan.pdf"
    return reencoded_photo(upload, field="scan"), "scan.webp"


@transaction.atomic
def record_paper(
    *,
    organization: Organization,
    actor: User,
    kind: str,
    expires_on: dt.date,
    truck: "Truck | None" = None,
    employee: "Employee | None" = None,
    number: str = "",
    issuer: str = "",
    issued_on: dt.date | None = None,
    cost: Decimal | str | int = 0,
    payment_method: str = "cash",
    note: str = "",
    scan: "UploadedFile[bytes] | None" = None,
) -> Paper:
    """A paper of a truck or a person, typed when it is issued or renewed (P10-T04). The one valid the longest is the
    current one. A cost makes an approved expense of the general overhead (owner answer 6)."""
    errors: dict[str, str] = {}
    if kind in TRUCK_PAPERS:
        if truck is None or truck.organization_id != organization.pk:
            errors["truck"] = _("Choisissez un camion.")
    elif kind in PERSON_PAPERS:
        if employee is None or employee.organization_id != organization.pk:
            errors["employee"] = _("Choisissez une personne.")
    else:
        errors["kind"] = _("Papier inconnu.")
    if issued_on is not None and issued_on > expires_on:
        errors["expires_on"] = _("La fin de validité est avant la date de délivrance.")
    try:
        amount = checked_amount(cost)
        if amount < 0:
            errors["cost"] = _("Le coût ne peut pas être négatif.")
    except (ValueError, TypeError):
        errors["cost"] = _("Indiquez un montant en DT, au millime près.")
        amount = Decimal(0)
    if errors:
        raise ValidationError(errors)
    on_truck = kind in TRUCK_PAPERS
    subject = truck.location.name if on_truck and truck is not None else (employee.name if employee else "")
    label = str(PaperKind(kind).label)
    expense = None
    if amount > 0:
        expenses.ensure_default_categories(organization=organization)
        category = expense_selectors.category_by_code(organization, "vehicles" if on_truck else "personnel")
        expense = expenses.create_expense(
            organization=organization,
            actor=actor,
            spent_on=min(issued_on or timezone.localdate(), timezone.localdate()),
            category=category,
            amount=amount,
            payment_method=payment_method,
            description=f"{label} · {subject}",
            payee=" ".join(issuer.split())[:150],
            notes=note,
            approve=True,
        )
    paper = Paper(
        organization=organization,
        kind=kind,
        truck=truck if on_truck else None,
        employee=None if on_truck else employee,
        number=" ".join(number.split())[:60],
        issuer=" ".join(issuer.split())[:150],
        issued_on=issued_on,
        expires_on=expires_on,
        cost=amount,
        expense=expense,
        note=note.strip()[:300],
        recorded_by=actor,
    )
    if scan is not None:
        content, name = _scan_content(scan)
        paper.scan.save(name, content, save=False)
    try:
        paper.save()
    except BaseException:
        if paper.scan.name:
            paper.scan.storage.delete(paper.scan.name)
        raise
    audit.record(
        organization=organization,
        actor=actor,
        action="paper.recorded",
        target=paper,
        after={
            "kind": kind,
            "subject": subject,
            "number": paper.number,
            "expires_on": expires_on.isoformat(),
            "cost": str(amount),
            "expense": expense.number if expense is not None else None,
        },
    )
    return paper


@transaction.atomic
def allow_truck_day(
    *, organization: Organization, actor: User, truck: "Truck", date: dt.date, reason: str
) -> TruckDayAllowance:
    """The owner lets the truck go out that day although its assurance or visite technique has expired (owner answer
    5b). The reason is kept; the API lets only the owner do it."""
    reason = " ".join(reason.split())[:300]
    if not reason:
        raise ValidationError({"reason": _("Indiquez la raison.")})
    if truck.organization_id != organization.pk:
        raise ValidationError({"truck": _("Camion inconnu.")})
    if date < timezone.localdate():
        raise ValidationError({"date": _("La date est passée.")})
    allowance, created = TruckDayAllowance.objects.get_or_create(
        organization=organization, truck=truck, date=date, defaults={"reason": reason, "allowed_by": actor}
    )
    if not created:
        raise ValidationError({"date": _("Cette journée est déjà autorisée.")})
    audit.record(
        organization=organization,
        actor=actor,
        action="truck_day.allowed",
        target=allowance,
        after={"truck": truck.location.name, "date": date.isoformat(), "reason": reason},
    )
    return allowance


@transaction.atomic
def update_paper_warnings(*, organization: Organization, actor: User, days: list[int]) -> MaintenanceSettings:
    """The days before a paper expires when the office is warned (30, 15 and 7 by default; and on the day)."""
    cleaned = sorted({int(day) for day in days if 0 < int(day) <= 365}, reverse=True)[:5]
    if not cleaned:
        raise ValidationError({"paper_warn_days": _("Indiquez au moins un nombre de jours, entre 1 et 365.")})
    found, _created = MaintenanceSettings.objects.select_for_update().get_or_create(organization=organization)
    before = {"paper_warn_days": found.paper_warn_days}
    found.paper_warn_days = cleaned
    found.save(update_fields=["paper_warn_days", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="maintenance_settings.changed",
        target=found,
        before=before,
        after={"paper_warn_days": cleaned},
    )
    return found


# ---- Warnings everywhere (P10-T05) ----


def _send_once(organization: Organization, key: str, *, kind: str, params: dict[str, object], link: str) -> bool:
    _sent, created = MaintenanceWarningSent.objects.get_or_create(organization=organization, key=key[:120])
    if created:
        notifications.tell_office_of(organization=organization, actor=None, kind=kind, params=params, link=link)
    return created


@transaction.atomic
def send_warnings(*, organization: Organization, today: dt.date | None = None) -> int:
    """The daily check (P10-T05): tell the owner and the managers once when a maintenance turns orange or red, and
    when a paper reaches each warning day, its last day and its expiry. Returns how many notifications were sent."""
    today = today or timezone.localdate()
    thresholds = sorted(set(selectors.settings_of(organization).paper_warn_days or []) | {0})
    sent = 0
    for status in selectors.plan_statuses(organization):
        if status.state not in ("soon", "late"):
            continue
        plan = status.plan
        subject = plan.truck.location.name if plan.truck is not None else (plan.location.name if plan.location else "")
        link = f"/flotte?camion={plan.truck_id}" if plan.truck_id else "/flotte"
        # Once per state and per job: a new "Entretien effectué" starts again.
        key = f"plan:{plan.pk}:{status.state}:{plan.last_done_on}:{plan.last_done_km}"
        kind = "maintenance_late" if status.state == "late" else "maintenance_soon"
        sent += _send_once(organization, key, kind=kind, params={"subject": subject, "type": plan.type.name}, link=link)
    for row in selectors.paper_board(organization, today=today):
        paper, days = row.paper, row.days_left
        if paper is None or days is None:
            continue
        link = f"/flotte?camion={row.truck_id}" if row.truck_id else "/flotte"
        params: dict[str, object] = {
            "subject": row.subject,
            "paper": str(PaperKind(row.kind).label),
            "date": paper.expires_on.isoformat(),
        }
        if days < 0:
            sent += _send_once(
                organization, f"paper:{paper.pk}:expired", kind="paper_expired", params=params, link=link
            )
            continue
        crossed = [limit for limit in thresholds if days <= limit]
        if crossed:
            limit = min(crossed)
            sent += _send_once(
                organization,
                f"paper:{paper.pk}:{limit}",
                kind="paper_expires",
                params={**params, "days": days},
                link=link,
            )
    return sent
