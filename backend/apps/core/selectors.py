"""Reusable read queries on core models."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum

from django.db.models import QuerySet
from django.utils import timezone

from . import numbering
from .models import Job, JobRun, Membership, Organization, Role, User

type MembershipQuerySet = QuerySet[Membership]


def active_membership(user: User) -> Membership | None:
    """The user's membership in an active organization. One organization exists today (ARCHITECTURE §4.6)."""
    return (
        Membership.objects.filter(user=user, is_active=True, organization__is_active=True)
        .select_related("organization", "user")
        .order_by("id")
        .first()
    )


def members_of(organization: Organization) -> MembershipQuerySet:
    """Every membership of one organization, active or not, with its user."""
    return Membership.objects.filter(organization=organization).select_related("user").order_by("user__username")


def active_owner_count(organization: Organization) -> int:
    """How many active owners the organization has (Paramètres > Users guards against losing the last one)."""
    return Membership.objects.filter(organization=organization, role=Role.OWNER, is_active=True).count()


# ---- Monitoring of scheduled jobs (P4-T04, D-140) ----

# The nightly stock check runs every day just after 03:00 UTC; two hours of slack before it reads as late.
STOCK_CHECK_MAX_AGE = timedelta(hours=26)


class JobState(StrEnum):
    OK = "ok"
    FAILED = "failed"  # the last run found a problem or crashed
    LATE = "late"  # no run for longer than the job's maximum age: the scheduler is down
    NEVER = "never"  # the job has never run on this database


@dataclass(frozen=True)
class JobHealth:
    state: JobState
    ran_at: datetime | None

    @property
    def ok(self) -> bool:
        return self.state is JobState.OK


def job_health(job: Job, *, max_age: timedelta, now: datetime | None = None) -> JobHealth:
    """How the last run of a scheduled job went. Anything but a recent passed run is a failure."""
    run = JobRun.objects.filter(job=job).first()
    if run is None:
        return JobHealth(JobState.NEVER, None)
    if not run.ok:
        return JobHealth(JobState.FAILED, run.ran_at)
    if (now or timezone.now()) - run.ran_at > max_age:
        return JobHealth(JobState.LATE, run.ran_at)
    return JobHealth(JobState.OK, run.ran_at)


@dataclass(frozen=True)
class NumberLine:
    """One kind of number on the Paramètres page: its prefix in force, the default, and the next number."""

    kind: str
    title: str
    group: str
    prefix: str
    default_prefix: str
    yearly: bool
    next_number: str


def number_lines(organization: Organization) -> list[NumberLine]:
    prefixes = numbering.prefixes_of(organization)
    return [
        NumberLine(
            kind=item.key,
            title=str(item.label),
            group=str(item.group),
            prefix=prefixes[item.key],
            default_prefix=item.prefix,
            yearly=item.yearly,
            next_number=numbering.next_preview(organization, item.key, prefixes),
        )
        for item in numbering.NUMBER_KINDS
    ]
