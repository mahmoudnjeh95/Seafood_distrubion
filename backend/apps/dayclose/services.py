"""Every write on day closings goes through these functions (ARCHITECTURE §3)."""

import json
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from django.core.exceptions import PermissionDenied, ValidationError
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.boxes import selectors as boxes
from apps.catalog import selectors as catalog
from apps.core import audit
from apps.core.models import Organization, User
from apps.expenses import services as expenses_services
from apps.fleet import selectors as fleet
from apps.fleet import services as fleet_services
from apps.inventory import selectors as inventory
from apps.inventory import services as inventory_services
from apps.purchasing import services as purchasing_services
from apps.sales import services as sales_services

from . import selectors
from .models import DayClosing, DayClosingRevision, DayClosingStatus, DayReopening, SyncProblem

if TYPE_CHECKING:
    from apps.expenses.models import Expense
    from apps.fleet.models import DriverDay
    from apps.inventory.models import Transfer
    from apps.purchasing.models import FieldPurchase


def _plain(value: Any) -> Any:
    """The summary as plain JSON values: dates and Decimals become strings."""
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


# The office corrects a day whose records moved since the send (D-220); the driver never sends it again.
CHANGED_SINCE_SENT = (
    "Les chiffres ont changé depuis l'envoi : corrigez d'abord la journée (Corriger). Le chauffeur ne la renvoie plus."
)
DRIVER_CANNOT_RESEND = (
    "Les chiffres ont changé depuis l'envoi : le bureau corrige la journée. Vous ne pouvez plus l'envoyer."
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


def _refuse_recount(
    closing: DayClosing, office_counted_cash: Decimal | None, office_counted_purchase_cash: Decimal | None
) -> None:
    """A count already saved changes only by a correction, with its reason (D-220). A count left out (None) keeps
    what was saved."""
    errors: dict[str, str] = {}
    message = _("Le comptage est déjà saisi : pour le changer, corrigez la journée avec une raison.")
    if closing.office_counted_cash is not None and office_counted_cash not in (None, closing.office_counted_cash):
        errors["office_counted_cash"] = message
    purchase_moved = office_counted_purchase_cash not in (None, closing.office_counted_purchase_cash)
    if closing.office_counted_purchase_cash is not None and purchase_moved:
        errors["office_counted_purchase_cash"] = message
    if errors:
        raise ValidationError(errors)


def _figures_of(summary: dict[str, Any], closing: DayClosing) -> dict[str, str | None]:
    """The figures a correction shows before and after: the day's figures as kept, and the office's counts."""
    figures: dict[str, str | None] = {name: str(summary[name]) for name in selectors.DAY_FIGURES if name in summary}
    figures.update(
        office_counted_cash=_text(closing.office_counted_cash),
        office_counted_purchase_cash=_text(closing.office_counted_purchase_cash),
        office_difference=str(closing.office_difference),
        office_purchase_difference=str(closing.office_purchase_difference),
    )
    return figures


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
    # The driver never changes a sent day (D-220): when its records moved since the send, the office corrects it.
    if (
        existing is not None
        and existing.status in (DayClosingStatus.SUBMITTED, DayClosingStatus.JUSTIFICATION)
        and selectors.changed_since_sent(existing)
    ):
        raise PermissionDenied(DRIVER_CANNOT_RESEND)
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
    _refuse_recount(closing, office_counted_cash, office_counted_purchase_cash)
    # A purchase count left out keeps the one saved (D-220).
    purchase = (
        office_counted_purchase_cash
        if office_counted_purchase_cash is not None
        else closing.office_counted_purchase_cash
    )
    _set_office_count(closing, office_counted_cash, purchase)
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
    # A count sent with the approval must match the saved one (D-220); a figure left out keeps what was saved.
    _refuse_recount(closing, office_counted_cash, office_counted_purchase_cash)
    cash = office_counted_cash if office_counted_cash is not None else closing.office_counted_cash
    purchase = (
        office_counted_purchase_cash
        if office_counted_purchase_cash is not None
        else closing.office_counted_purchase_cash
    )
    if cash is not None:
        _set_office_count(closing, cash, purchase)
    if closing.office_counted_cash is None:
        raise ValidationError({"office_counted_cash": _("Comptez l'argent du chauffeur avant d'approuver.")})
    if closing.expected_purchase_cash > 0 and closing.office_counted_purchase_cash is None:
        raise ValidationError(
            {"office_counted_purchase_cash": _("Comptez l'argent des achats qui reste avant d'approuver.")}
        )
    # The office checks the day as it stands: what it still has to settle is refused (D-239).
    blockers = selectors.review_blockers(closing.organization, closing.driver_day)
    if blockers:
        raise ValidationError({"review": "; ".join(blockers)})
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
def correct_day_closing(
    *,
    closing: DayClosing,
    actor: User,
    reason: str,
    office_counted_cash: Decimal | None = None,
    office_counted_purchase_cash: Decimal | None = None,
) -> DayClosing:
    """The office corrects a driver's day (D-220): the driver never changes a sent day, so the office takes the day's
    records as they are now (the figures sent move to them) and, when given, its counts. Each correction is a
    `DayClosingRevision` with who, when, why, and the figures before and after. The status stays: an approval
    stands, and a day still to check stays to check. Refused for a day a new load reopened: its send is in the
    history (D-134)."""
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": _("Dites pourquoi vous corrigez la journée.")})
    _counts_checked(office_counted_cash, office_counted_purchase_cash)
    closing = DayClosing.objects.select_for_update().get(pk=closing.pk)
    if closing.status == DayClosingStatus.REOPENED:
        raise ValidationError(_("Une nouvelle charge a rouvert cette journée : corrigez-la après son prochain envoi."))
    cash = office_counted_cash if office_counted_cash is not None else closing.office_counted_cash
    purchase = (
        office_counted_purchase_cash
        if office_counted_purchase_cash is not None
        else closing.office_counted_purchase_cash
    )
    if cash is None and purchase is not None:
        raise ValidationError({"office_counted_cash": _("Comptez d'abord l'argent du chauffeur.")})
    before = _figures_of(closing.summary, closing)
    live = selectors.day_summary(closing.organization, closing.driver_day)
    # A change of a product's kilos alone moves no day figure, but it is a change to correct too (D-239).
    moved = selectors.changed_since_sent(closing)
    closing.summary = _plain(live)
    closing.expected_cash = live["expected_cash"]
    closing.expected_purchase_cash = live["expected_purchase_cash"]
    if cash is not None:
        _set_office_count(closing, cash, purchase)
    after = _figures_of(closing.summary, closing)
    if after == before and not moved:
        raise ValidationError(_("Rien n'a changé : il n'y a rien à corriger."))
    closing.save(update_fields=["summary", "expected_cash", "expected_purchase_cash", *_COUNT_FIELDS, "updated_at"])
    last = closing.revisions.aggregate(last=Max("number"))["last"] or 0
    DayClosingRevision.objects.create(
        organization=closing.organization,
        closing=closing,
        number=last + 1,
        actor=actor,
        reason=reason[:300],
        before=before,
        after=after,
    )
    audit.record(
        organization=closing.organization,
        actor=actor,
        action="day_closing.corrected",
        target=closing,
        before=before,
        after=after,
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


def _refresh_after_review(*, driver_day: "DriverDay", actor: User, reason: str) -> None:
    """An office decision that moves the figures the driver sent (an expense refused, a purchase refused...) is kept
    as a correction of the sent day, with its reason, so the day can be approved as it stands (D-220, D-239). Nothing
    happens for a day not sent yet, a reopened one, or one whose figures did not move."""
    closing = selectors.closing_of(driver_day)
    if closing is None or closing.status not in (DayClosingStatus.SUBMITTED, DayClosingStatus.JUSTIFICATION):
        return
    if selectors.changed_since_sent(closing):
        correct_day_closing(closing=closing, actor=actor, reason=reason)


@transaction.atomic
def decide_driver_expense(
    *, driver_day: "DriverDay", expense: "Expense", actor: User, approve: bool, reason: str = ""
) -> "Expense":
    """The office approves or refuses one expense the driver typed on the day (D-239). An approved one counts as the
    expense it is; a refused one needs its reason and never counts (D-205)."""
    if approve:
        decided = expenses_services.approve_expense(expense=expense, actor=actor)
    else:
        decided = expenses_services.reject_expense(expense=expense, actor=actor, reason=reason)
    _refresh_after_review(
        driver_day=driver_day,
        actor=actor,
        reason=_("Dépense « %(category)s » %(verdict)s par le bureau")
        % {"category": expense.category.name, "verdict": "approuvée" if approve else "refusée"},
    )
    return decided


@transaction.atomic
def validate_driver_purchase(*, driver_day: "DriverDay", purchase: "FieldPurchase", actor: User) -> "FieldPurchase":
    """The office validates a purchase the driver made on the day, from the day's check (D-239): its kilos enter the
    truck's stock. Refused when the purchase is not complete (supplier, products or place still to set)."""
    validated = purchasing_services.validate_field_purchase(purchase=purchase, actor=actor)
    _refresh_after_review(
        driver_day=driver_day,
        actor=actor,
        reason=_("Achat %(number)s validé par le bureau") % {"number": validated.number},
    )
    return validated


@transaction.atomic
def return_truck_to_stock(*, driver_day: "DriverDay", actor: User, to_location_id: int | None = None) -> "Transfer":
    """The office gives back what the truck still holds, kilos and boxes, to the cold room it chooses (D-258; the only
    active one when there is one, D-239): one validated transfer from the truck, so the stock and the boxes move with
    the ledger. Only on the truck's latest day: the stock it holds is then this day's to give back. The driver need not
    have sent the day."""
    driver_day = fleet.locked_driver_day(driver_day)
    organization = driver_day.organization
    if not selectors.owns_truck(organization, driver_day):
        raise ValidationError(_("Le camion a déjà un jour plus récent : son stock appartient à ce jour-là."))
    rooms = inventory.active_cold_rooms(organization)
    if not rooms:
        raise ValidationError(_("Aucune chambre froide active pour recevoir le stock."))
    if to_location_id is None:
        if len(rooms) > 1:
            raise ValidationError({"to_location_id": _("Choisissez la chambre froide qui reçoit le stock.")})
        destination = rooms[0]
    else:
        chosen = [room for room in rooms if room.pk == to_location_id]
        if not chosen:
            raise ValidationError({"to_location_id": _("Choisissez une chambre froide active.")})
        destination = chosen[0]
    today = timezone.localdate()
    truck_location = driver_day.truck.location
    lines: list[inventory_services.TransferLineFields] = [
        {"product": catalog.product_of(organization, row["product_id"]), "quantity": row["quantity"]}
        for row in inventory.location_stock(organization, location_id=truck_location.pk)
    ]
    counts = {
        row.box_type: row.expected for row in boxes.truck_day(organization, truck_location, today) if row.expected > 0
    }
    if not lines and not counts:
        raise ValidationError(_("Le camion est vide : rien à remettre en stock."))
    transfer = inventory_services.create_transfer(
        organization=organization,
        actor=actor,
        from_location=truck_location,
        to_location=destination,
        transferred_on=today,
        lines=lines,
        boxes=counts or None,
        notes=_("Remis en stock par le bureau (journée du %(day)s)") % {"day": driver_day.date.isoformat()},
        validate=True,
    )
    _refresh_after_review(driver_day=driver_day, actor=actor, reason=_("Camion remis en stock"))
    return transfer


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
        counted: Decimal | None
        difference: Decimal | None
        counted_purchase: Decimal | None
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
