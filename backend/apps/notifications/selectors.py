"""Reusable read queries of notifications (D-175)."""

import datetime as dt

from django.db.models import Exists, OuterRef, Q, QuerySet
from django.utils import timezone

from apps.core.models import Membership, Organization, Role

from .models import Audience, Notification, NotificationRead

# The office readers: the accountant only reads the books, nothing here is for them.
OFFICE_READERS = frozenset({Role.OWNER, Role.MANAGER})
# Older notifications are no longer shown, read or not.
KEPT_DAYS = 14
SHOWN = 40


def visible_to(membership: Membership) -> QuerySet[Notification]:
    """What one member is told: the office's notifications for an owner or a manager, a driver's own for a driver,
    of the last `KEPT_DAYS` days. Never their own actions."""
    since = timezone.now() - dt.timedelta(days=KEPT_DAYS)
    rows = Notification.objects.for_organization(membership.organization).filter(created_at__gte=since)
    # A custom role (D-306) works in the office: it is told what the office is told.
    if membership.role in OFFICE_READERS or membership.role == Role.CUSTOM:
        # The whole office's, or one addressed to this person (a payment order sent to them, D-255).
        rows = rows.filter(Q(recipient__isnull=True) | Q(recipient_id=membership.user_id), audience=Audience.OFFICE)
    elif membership.role == Role.DRIVER:
        rows = rows.filter(audience=Audience.DRIVER, recipient_id=membership.user_id)
    else:
        return rows.none()
    return rows.exclude(actor_id=membership.user_id).annotate(
        read=Exists(NotificationRead.objects.filter(notification_id=OuterRef("pk"), user_id=membership.user_id))
    )


def unread_of(membership: Membership) -> QuerySet[Notification]:
    """What one member is shown and has not read yet."""
    return visible_to(membership).exclude(reads__user_id=membership.user_id)


def latest_for(membership: Membership) -> list[Notification]:
    """The newest notifications of one member, newest first, each with `read` for them."""
    return list(visible_to(membership).select_related("actor").order_by("-id")[:SHOWN])


def unread_count(membership: Membership) -> int:
    return unread_of(membership).count()


def office_recipients(organization: Organization) -> QuerySet[Membership]:
    """The people a payment order can be sent to: the active owners and managers, by name."""
    return (
        Membership.objects.filter(organization=organization, is_active=True, role__in=OFFICE_READERS)
        .select_related("user")
        .order_by("user__first_name", "user__username")
    )
