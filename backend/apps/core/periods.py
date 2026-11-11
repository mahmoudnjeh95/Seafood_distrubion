"""The period lock (D-310, P11-T16): a month declared to the tax office takes no new dated entry.

Every service that writes a dated record calls `ensure_open` with the record's date before writing. The lock is read
from the database each time, so an organization object loaded before the lock moved never lets a write through.
"""

import datetime as dt
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.utils.translation import gettext as _

from apps.core.models import Organization

# True while records already in the books write their history (treasury backfills): they are not new entries.
_writing_history: ContextVar[bool] = ContextVar("writing_history", default=False)


@contextmanager
def writing_history() -> Iterator[None]:
    """Let records that already exist write what they should have written (a backfill), even in a locked period."""
    token = _writing_history.set(True)
    try:
        yield
    finally:
        _writing_history.reset(token)


def locked_until(organization: Organization) -> dt.date | None:
    """The last locked day, or None when nothing is locked."""
    return Organization.objects.filter(pk=organization.pk).values_list("books_locked_until", flat=True).first()


def is_locked(organization: Organization, day: dt.date) -> bool:
    until = locked_until(organization)
    return until is not None and day <= until


def ensure_open(organization: Organization, day: dt.date | dt.datetime, *, field: str | None = None) -> None:
    """Refuse a record dated in the locked period, the error on `field` (the date field of the form) or general."""
    if _writing_history.get():
        return
    if isinstance(day, dt.datetime):
        day = day.date()
    until = locked_until(organization)
    if until is not None and day <= until:
        message = _(
            "Les comptes sont verrouillés jusqu'au %(until)s (période déclarée) : datez l'écriture après cette "
            "date, une correction se fait dans le mois ouvert."
        ) % {"until": until.strftime("%d/%m/%Y")}
        raise ValidationError({field: message} if field else message)
