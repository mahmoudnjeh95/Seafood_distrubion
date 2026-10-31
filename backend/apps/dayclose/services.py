"""Every write on day closings goes through these functions (ARCHITECTURE §3)."""

import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.models import Organization, User
from apps.core.money import Number, checked_amount
from apps.fleet import selectors as fleet
from apps.fleet import services as fleet_services
from apps.sales import services as sales_services

from . import selectors
from .models import DayClosing, DayClosingStatus, DayReopening, SyncProblem

if TYPE_CHECKING:
    from apps.fleet.models import DriverDay
    from apps.inventory.models import Transfer


def _plain(value: Any) -> Any:
    """The summary as plain JSON values: dates and Decimals become strings."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


CHANGED_SINCE_SENT = (
    "Les chiffres ont changé depuis l'envoi : le chauffeur doit renvoyer sa journée avant l'approbation."
)
_COUNT_FIELDS = [
    "office_counted_cash",
    "office_counted_purchase_cash",
    "office_difference",
    "office_purchase_difference",
]


def _text(value: Decimal | None) -> str | None:
    return None if value is None else str(value)


def _counts_checked(office_counted_cash: Decimal | None, office_counted_purchase_cash: Decimal | None) -> None:
    errors: dict[str, str] = {}
    for name, value in (
        ("office_counted_cash", office_counted_cash),
        ("office_counted_purchase_cash", office_counted_purchase_cash),
    ):
        if value is not None and value < 0:
            errors[name] = _("Un montant compté ne peut pas être négatif.")
    if errors:
        raise ValidationError(errors)


def _set_office_count(
    closing: DayClosing, office_counted_cash: Decimal, office_counted_purchase_cash: Decimal | None
) -> None:
    """The cash the office counted, and its gap with what the driver should hold (D-213). A purchase count left
    out is no gap, as a sales count left out is none in the closing's own figures."""
    closing.office_counted_cash = office_counted_cash
    closing.office_counted_purchase_cash = office_counted_purchase_cash
    closing.office_difference = office_counted_cash - closing.expected_cash
    closing.office_purchase_difference = (
        office_counted_purchase_cash - closing.expected_purchase_cash
        if office_counted_purchase_cash is not None
        else Decimal("0.000")
    )


@transaction.atomic
def submit_day_closing(*, driver_day: "DriverDay", actor: User, note: str = "") -> DayClosing:
    """The driver sends the end of their day. The driver does not count the cash: the office counts it when the
    driver is back (D-213), and the driver sees what they should hold (`expected_cash`, `expected_purchase_cash`).
    Allowed once, and again after the office asked for a justification, after a new load reopened the day
    (D-134), or when the day's records no longer say what was sent (D-132). An approved day does not change. The
    figures are kept as they are at this moment (`DayClosing.summary`); nothing recorded later rewrites them."""
    driver_day = fleet.locked_driver_day(driver_day)
    existing = selectors.closing_of(driver_day)
    if (
        existing is not None
        and existing.status == DayClosingStatus.SUBMITTED
        and not selectors.changed_since_sent(existing)
    ):
        raise ValidationError(_("Cette journée est déjà envoyée."))
    if existing is not None and existing.status == DayClosingStatus.APPROVED:
        raise ValidationError(_("Cette journée est approuvée : elle ne change plus."))
    # The BL of the truck still to deliver are not delivered (D-178): nothing was sold, the goods go back with the
    # return to the cold room.
    sales_services.cancel_undelivered(
        organization=driver_day.organization, location_id=driver_day.truck.location_id, actor=actor
    )
    now = timezone.now()
    # Sending ends the day (D-134): nothing made from now on is taken. Sent again while it is still closed (a
    # justification, changed records), the day keeps its end, so the figures are those of the same window: a
    # sale made in it and received since is now in them, and the stock left is what the ledger held when the
    # day ended. A day a new load reopened ends now.
    driver_day = fleet_services.end_driver_day(driver_day=driver_day, ended_at=now)
    summary = selectors.day_summary(driver_day.organization, driver_day)
    expected: Decimal = summary["expected_cash"]
    expected_purchase: Decimal = summary["expected_purchase_cash"]
    fields: dict[str, Any] = {
        "status": DayClosingStatus.SUBMITTED,
        "expected_cash": expected,
        "expected_purchase_cash": expected_purchase,
        "driver_note": note.strip(),
        "summary": _plain(summary),
        "submitted_at": now,
        # The driver's own count is no longer asked: the office counts again (D-213).
        "counted_cash": None,
        "difference": None,
        "counted_purchase_cash": None,
        "purchase_difference": None,
        "office_counted_cash": None,
        "office_counted_purchase_cash": None,
        "office_difference": Decimal("0.000"),
        "office_purchase_difference": Decimal("0.000"),
    }
    if existing is None:
        closing = DayClosing.objects.create(organization=driver_day.organization, driver_day=driver_day, **fields)
        action = "day_closing.submitted"
    else:
        for name, value in fields.items():
            setattr(existing, name, value)
        existing.save()
        closing, action = existing, "day_closing.resubmitted"
    audit.record(
        organization=closing.organization,
        actor=actor,
        action=action,
        target=closing,
        after={"expected": str(expected), "expected_purchase": str(expected_purchase)},
    )
    return closing


def _reviewable(closing: DayClosing) -> DayClosing:
    closing = DayClosing.objects.select_for_update().get(pk=closing.pk)
    if closing.status != DayClosingStatus.SUBMITTED:
        raise ValidationError(_("Seule une journée envoyée par le chauffeur peut être vérifiée."))
    return closing


@transaction.atomic
def record_office_count(
    *,
    closing: DayClosing,
    actor: User,
    office_counted_cash: Decimal,
    office_counted_purchase_cash: Decimal | None = None,
) -> DayClosing:
    """The office counts the cash the driver hands over (D-213): the sales cash, and the purchase money when there is
    some. Saved before the approval, so the gap shows while the day is checked. Refused while the day's records
    changed since the send: the driver sends it again first (D-132)."""
    _counts_checked(office_counted_cash, office_counted_purchase_cash)
    closing = _reviewable(closing)
    if selectors.changed_since_sent(closing):
        raise ValidationError(CHANGED_SINCE_SENT)
    _set_office_count(closing, office_counted_cash, office_counted_purchase_cash)
    closing.save(update_fields=[*_COUNT_FIELDS, "updated_at"])
    audit.record(
        organization=closing.organization,
        actor=actor,
        action="day_closing.counted",
        target=closing,
        after={
            "office_counted_cash": _text(office_counted_cash),
            "office_counted_purchase_cash": _text(office_counted_purchase_cash),
            "office_difference": str(closing.office_difference),
            "office_purchase_difference": str(closing.office_purchase_difference),
        },
    )
    return closing


@transaction.atomic
def approve_day_closing(
    *,
    closing: DayClosing,
    actor: User,
    office_counted_cash: Decimal | None = None,
    office_counted_purchase_cash: Decimal | None = None,
    note: str = "",
) -> DayClosing:
    """The office checked the day: it is locked. Refused while the day's records no longer say what the driver
    sent (D-132): the driver sends it again first. The office has counted the cash (`record_office_count`, or the
    counts sent with the approval); a gap with what the driver should hold needs a note, kept as the review note."""
    _counts_checked(office_counted_cash, office_counted_purchase_cash)
    closing = _reviewable(closing)
    if selectors.changed_since_sent(closing):
        raise ValidationError(CHANGED_SINCE_SENT)
    if office_counted_cash is not None:
        _set_office_count(closing, office_counted_cash, office_counted_purchase_cash)
    if closing.office_counted_cash is None:
        raise ValidationError({"office_counted_cash": _("Comptez l'argent du chauffeur avant d'approuver.")})
    if closing.expected_purchase_cash > 0 and closing.office_counted_purchase_cash is None:
        raise ValidationError(
            {"office_counted_purchase_cash": _("Comptez l'argent des achats qui reste avant d'approuver.")}
        )
    gap = closing.office_difference != 0 or closing.office_purchase_difference != 0
    if gap and not note.strip():
        raise ValidationError(
            {"note": _("Le bureau n'a pas compté la même somme que le chauffeur doit avoir : expliquez l'écart.")}
        )
    closing.status = DayClosingStatus.APPROVED
    closing.reviewed_by = actor
    closing.reviewed_at = timezone.now()
    closing.review_note = note.strip()[:300]
    closing.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", *_COUNT_FIELDS, "updated_at"])
    audit.record(
        organization=closing.organization,
        actor=actor,
        action="day_closing.approved",
        target=closing,
        after={
            "office_counted_cash": _text(closing.office_counted_cash),
            "office_counted_purchase_cash": _text(closing.office_counted_purchase_cash),
            "office_difference": str(closing.office_difference),
            "office_purchase_difference": str(closing.office_purchase_difference),
        },
    )
    return closing


@transaction.atomic
def request_justification(*, closing: DayClosing, actor: User, reason: str) -> DayClosing:
    """The office asks the driver to explain; the driver then sends the day again with a note."""
    if not reason.strip():
        raise ValidationError({"reason": _("Dites au chauffeur ce qu'il doit expliquer.")})
    closing = _reviewable(closing)
    closing.status = DayClosingStatus.JUSTIFICATION
    closing.reviewed_by = actor
    closing.reviewed_at = timezone.now()
    closing.review_note = reason.strip()[:300]
    closing.save(update_fields=["status", "reviewed_by", "reviewed_at", "review_note", "updated_at"])
    audit.record(
        organization=closing.organization,
        actor=actor,
        action="day_closing.justification_requested",
        target=closing,
        after={"reason": closing.review_note},
    )
    return closing


@transaction.atomic
def reopen_days_after_load(*, load: "Transfer", actor: User | None) -> list[DayClosing]:
    """A load validated into a truck opens again the day its driver had sent that date (D-134): the driver sells
    what was loaded, then sends the day again. The send it undoes is kept as it was in a `DayReopening`, and the
    cash counted then stays with the office. An approved day opens again too: the one case where an approved
    closing changes, with the approval kept on that record. A load dated another day changes nothing, as does
    one into a truck whose driver's day runs or was never started."""
    if load.transferred_on != timezone.localdate():
        return []
    reopened = []
    days = fleet.closed_days_on_truck(load.organization, location_id=load.to_location_id, on=load.transferred_on)
    for day in days:
        driver_day = fleet.locked_driver_day(day)
        if driver_day.ended_at is None:
            continue
        fleet_services.reopen_driver_day(driver_day=driver_day)
        closing = DayClosing.objects.select_for_update().filter(driver_day=driver_day).first()
        if closing is None:
            continue
        # The cash the office counted at that send went to the office (D-213); a send made before the office counted
        # kept the driver's own count, which went the same way.
        if closing.office_counted_cash is not None:
            counted, difference = closing.office_counted_cash, closing.office_difference
            counted_purchase = closing.office_counted_purchase_cash
        else:
            counted, difference = closing.counted_cash, closing.difference
            counted_purchase = closing.counted_purchase_cash
        undone = DayReopening.objects.create(
            organization=closing.organization,
            closing=closing,
            status=closing.status,
            expected_cash=closing.expected_cash,
            counted_cash=counted,
            difference=difference,
            counted_purchase_cash=counted_purchase,
            driver_note=closing.driver_note,
            summary=closing.summary,
            submitted_at=closing.submitted_at,
            reviewed_by=closing.reviewed_by,
            reviewed_at=closing.reviewed_at,
            review_note=closing.review_note,
            load=load,
            reopened_by=actor,
        )
        closing.status = DayClosingStatus.REOPENED
        # The review was of the send that is undone; the office's question stays for the driver to read.
        closing.reviewed_by = None
        closing.reviewed_at = None
        closing.save(update_fields=["status", "reviewed_by", "reviewed_at", "updated_at"])
        audit.record(
            organization=closing.organization,
            actor=actor,
            action="day_closing.reopened",
            target=closing,
            before={
                "status": undone.status,
                "expected": str(undone.expected_cash),
                "counted": _text(undone.counted_cash),
                "difference": _text(undone.difference),
                "reviewed_by": undone.reviewed_by.username if undone.reviewed_by else None,
            },
            after={"load": load.number},
        )
        reopened.append(closing)
    return reopened


@transaction.atomic
def report_sync_problem(
    *, organization: Organization, actor: User, kind: str, label: str, reason: str, client_uuid: uuid.UUID
) -> SyncProblem:
    """A driver's phone says the server refused one of its sends. Reporting the same item again changes nothing."""
    existing = SyncProblem.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
    if existing is not None:
        return existing
    problem = SyncProblem.objects.create(
        organization=organization,
        driver=actor,
        kind=kind,
        label=label[:150],
        reason=reason[:500],
        client_uuid=client_uuid,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="sync_problem.reported",
        target=problem,
        after={"kind": kind, "label": problem.label, "reason": problem.reason},
    )
    return problem


@transaction.atomic
def resolve_sync_problem(*, problem: SyncProblem, actor: User) -> SyncProblem:
    """The office dealt with it (called the driver, redid the sale by hand...)."""
    problem = SyncProblem.objects.select_for_update().get(pk=problem.pk)
    if problem.resolved_at is None:
        problem.resolved_at = timezone.now()
        problem.resolved_by = actor
        problem.save(update_fields=["resolved_at", "resolved_by", "updated_at"])
        audit.record(organization=problem.organization, actor=actor, action="sync_problem.resolved", target=problem)
    return problem
