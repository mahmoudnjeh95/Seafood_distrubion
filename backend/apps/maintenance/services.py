"""Every write of the maintenance module goes through these functions (ARCHITECTURE §3, P10, D-295)."""

from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import UploadedFile
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.images import reencoded_photo
from apps.core.models import Organization, User
from apps.fleet import selectors as fleet

from . import selectors
from .models import MaintenanceSettings, OdometerReading, OdometerSource, OdometerWarning

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay, Truck

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
