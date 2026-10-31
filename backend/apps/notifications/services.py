"""Every write on notifications goes through these functions (ARCHITECTURE §3, D-175)."""

from collections.abc import Sequence
from typing import Any

from django.db import transaction

from apps.core.models import Membership, Organization, Role, User
from apps.core.selectors import active_membership

from . import selectors
from .models import Audience, Notification, NotificationRead


def _is_driver(user: User | None) -> bool:
    membership = active_membership(user) if user is not None else None
    return membership is not None and membership.role == Role.DRIVER


def tell_office(
    *, organization: Organization, driver: User, kind: str, params: dict[str, Any], link: str = ""
) -> Notification | None:
    """A driver did something the office should see. Nothing when `driver` is not a driver: the office does not
    tell itself what it does."""
    if not _is_driver(driver):
        return None
    return Notification.objects.create(
        organization=organization, audience=Audience.OFFICE, actor=driver, kind=kind, params=params, link=link
    )


def tell_driver(
    *,
    organization: Organization,
    driver: User | None,
    actor: User | None,
    kind: str,
    params: dict[str, Any],
    link: str = "",
) -> Notification | None:
    """The office did something for one driver. Nothing when there is no such driver, or when the driver did it
    themselves (or another driver did)."""
    if driver is None or (actor is not None and actor.pk == driver.pk) or _is_driver(actor) or not _is_driver(driver):
        return None
    return Notification.objects.create(
        organization=organization,
        audience=Audience.DRIVER,
        recipient=driver,
        actor=actor,
        kind=kind,
        params=params,
        link=link,
    )


def tell_office_of(
    *, organization: Organization, actor: User | None, kind: str, params: dict[str, Any], link: str = ""
) -> Notification:
    """Something the whole office must know, whoever recorded it (an impayé, D-217)."""
    return Notification.objects.create(
        organization=organization, audience=Audience.OFFICE, actor=actor, kind=kind, params=params, link=link
    )


def tell_office_from_site(
    *, organization: Organization, kind: str, params: dict[str, Any], link: str = ""
) -> Notification:
    """A visitor of the public site sent a quote request or an order (D-186): nobody of the company did it, so
    there is no actor."""
    return Notification.objects.create(
        organization=organization, audience=Audience.OFFICE, actor=None, kind=kind, params=params, link=link
    )


@transaction.atomic
def mark_read(*, membership: Membership, ids: Sequence[int] | None) -> int:
    """The member has seen these notifications (`None`: all they are shown). Only their own; the others' reads
    stay as they are. Returns how many are left unread."""
    unread = selectors.unread_of(membership)
    if ids is not None:
        unread = unread.filter(pk__in=list(ids))
    NotificationRead.objects.bulk_create(
        [
            NotificationRead(organization=membership.organization, notification_id=pk, user=membership.user)
            for pk in unread.values_list("pk", flat=True)
        ],
        ignore_conflicts=True,
    )
    return selectors.unread_count(membership)
