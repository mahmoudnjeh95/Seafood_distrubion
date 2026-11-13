"""Closing and reopening a lot: its result frozen, or unfrozen with a reason (P6-T02, D-061); a partnership's
result frozen when the last line it shares closes (D-325)."""

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.locks import lock_lot
from apps.core.models import Organization, User
from apps.core.money import display_money
from apps.partnerships import selectors as partnerships
from apps.partnerships import services as partnership_services

from . import engine, selectors
from .models import LotResult, LotResultStatus, PartnershipResult

if TYPE_CHECKING:
    from apps.partnerships.models import PartnerSettlement


def _refusals(checks: list[selectors.ClosingCheck]) -> list[str]:
    messages = []
    for check in checks:
        if check.ok or not check.blocking:
            continue
        if check.code == "stock_empty":
            messages.append(
                _("Il reste %(quantity)s kg de ce lot en stock : vendez-les ou enregistrez une perte.")
                % {"quantity": check.quantity}
            )
        elif check.code == "costs_approved":
            messages.append(
                _("%(count)s coût(s) du lot attendent une approbation : approuvez-les ou refusez-les d'abord.")
                % {"count": check.count}
            )
        elif check.code == "customers_paid":
            owed = display_money(check.amount or 0)
            messages.append(_("Des clients doivent encore %(amount)s DT sur ce lot.") % {"amount": owed})
    return messages


def _summary(result: LotResult) -> dict[str, Any]:
    return {
        "batch": result.batch.number,
        "status": result.status,
        "net_result": str(result.net_result),
        "partner_share": str(result.partner_share),
        "owner_share": str(result.owner_share),
        "capital_deducted": str(result.capital_deducted),
        "uncovered_loss": str(result.uncovered_loss),
    }


def _lock_lines(organization: Organization, batch_id: int) -> list[Any]:
    """Lock this line and every line of the partnerships that share it, in id order (no deadlock with a settlement
    or another closing), and give those partnerships: closing the last of its lines freezes a partnership."""
    shared = partnerships.live_partnerships_of_line(organization, batch_id=batch_id)
    ids = {batch_id}
    for partnership in shared:
        ids.update(partnerships.line_ids_of(partnership))
    for lot_id in sorted(ids):
        lock_lot(lot_id)
    return shared


def _partnership_summary(result: PartnershipResult) -> dict[str, Any]:
    return {
        "partnership": result.partnership_id,
        "lines": result.batch_ids,
        "status": result.status,
        "net_result": str(result.net_result),
        "partner_share": str(result.partner_share),
        "owner_share": str(result.owner_share),
        "capital_deducted": str(result.capital_deducted),
        "uncovered_loss": str(result.uncovered_loss),
    }


def _freeze_partnership(
    organization: Organization, actor: User | None, partnership: Any, lines: tuple[engine.SharedLine, ...]
) -> PartnershipResult:
    """Freeze a partnership's result from its lines' frozen nets (D-325) and post its consequences: the loss share
    taken from the capital, the partnership closed."""
    computed = engine.partnership_result(selectors.terms_of(partnership), lines)
    partner = computed.partner
    result = PartnershipResult.objects.create(
        organization=organization,
        partnership=partnership,
        net_result=computed.net_result,
        partner_share=partner.share,
        owner_share=computed.owner_share,
        capital_deducted=partner.capital_deducted,
        uncovered_loss=partner.uncovered_loss,
        capital_to_return=partner.capital_to_return,
        data=engine.partnership_result_to_json(computed),
        closed_at=timezone.now(),
        closed_by=actor,
    )
    partnership_services.record_lot_closed(
        partnership=partnership,
        actor=actor,
        partnership_result_id=result.pk,
        lot_result_id=lines[0].lot_result_id if len(lines) == 1 else None,
        capital_deducted=partner.capital_deducted,
        on=timezone.localdate(),
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="partnership.result_closed",
        target=result,
        after=_partnership_summary(result),
    )
    return result


@transaction.atomic
def close_lot(
    *, organization: Organization, actor: User | None, batch_id: int, costs_confirmed: bool = False
) -> LotResult:
    """Close a lot line: check it is finished, then freeze its result (Q19, D-040).

    Refused: a line already closed; stock still on hand (sell it or record it as a loss); costs typed on
    the line still waiting for approval; `costs_confirmed` not given (only the person closing knows every
    cost is in); customers still owing money on its sales (customer payments, P2-T06, D-062); a partnership
    sharing it whose terms are not filled in yet.
    Each partnership sharing this line whose every line is now closed gets its result frozen (D-325), and a
    partner's loss share is taken from their capital in the same transaction. Two closings at once: the second
    waits, then is refused.
    """
    shared = _lock_lines(organization, batch_id)
    if selectors.closed_result_of(organization, batch_id=batch_id) is not None:
        raise ValidationError(_("Ce lot est déjà clôturé."))
    if any(partnership.terms_pending for partnership in shared):
        raise ValidationError(
            _("Le partenariat de ce lot n'a pas encore de capital ni de pourcentages : complétez-le d'abord.")
        )
    computed = selectors.live_result(organization, batch_id=batch_id)
    checks = selectors.closing_checks(organization, computed)
    refusals = _refusals(checks)
    if refusals:
        raise ValidationError(refusals)
    if not costs_confirmed:
        raise ValidationError({"costs_confirmed": _("Confirmez que tous les coûts du lot sont saisis.")})

    partner = computed.partner
    data = {**engine.to_json(computed), "checks": selectors.checks_to_json(checks)}
    partnership = partnerships.partnership_of(organization, partner.partnership_id) if partner is not None else None
    result = LotResult.objects.create(
        organization=organization,
        batch_id=batch_id,
        partnership=partnership,
        revenue=computed.revenue,
        cogs=computed.cogs,
        spoilage=computed.spoilage,
        costs_total=computed.costs_total,
        net_result=computed.net_result,
        owner_share=computed.owner_share,
        partner_share=partner.share if partner is not None else engine.ZERO,
        capital_deducted=partner.capital_deducted if partner is not None else engine.ZERO,
        uncovered_loss=partner.uncovered_loss if partner is not None else engine.ZERO,
        capital_to_return=partner.capital_to_return if partner is not None else engine.ZERO,
        payments_unverified=any(check.code == "customers_paid" and not check.ok for check in checks),
        data=data,
        closed_at=timezone.now(),
        closed_by=actor,
    )
    audit.record(organization=organization, actor=actor, action="lot.closed", target=result, after=_summary(result))
    for shared_partnership in shared:
        if shared_partnership.status != "open":
            continue
        lines = selectors.shared_lines(organization, shared_partnership)
        if lines is not None:
            _freeze_partnership(organization, actor, shared_partnership, lines)
    return result


@transaction.atomic
def reopen_lot(*, result: LotResult, actor: User | None, reason: str) -> LotResult:
    """Reopen a closed lot line, with a reason (audited). Its frozen result stays as history (status
    `reopened`), and so do the results of the partnerships that share it: the partner's deducted loss share
    comes back to their capital, and the next closing of the lines freezes new ones. A line whose partnership
    is already settled is not reopened: a correction then goes to the partner's next settlement (D-041, P6-T03)."""
    _lock_lines(result.organization, result.batch_id)
    result = LotResult.objects.select_for_update(of=("self",)).select_related("batch").get(pk=result.pk)
    if result.status != LotResultStatus.CLOSED:
        raise ValidationError(_("Ce lot n'est pas clôturé."))
    if not reason.strip():
        raise ValidationError({"reason": _("Indiquez pourquoi le lot est rouvert.")})
    reason = reason.strip()
    before = _summary(result)
    now = timezone.now()
    for frozen in selectors.closed_partnership_results_of_line(result.organization, batch_id=result.batch_id):
        frozen = PartnershipResult.objects.select_for_update(of=("self",)).get(pk=frozen.pk)
        partnership = partnerships.partnership_of(result.organization, frozen.partnership_id)
        partnership_services.record_lot_reopened(
            partnership=partnership,
            actor=actor,
            partnership_result_id=frozen.pk,
            lot_result_id=result.pk if frozen.lot_result_ids == [result.pk] else None,
            capital_deducted=frozen.capital_deducted,
            reason=reason,
        )
        partnership_before = _partnership_summary(frozen)
        frozen.status = LotResultStatus.REOPENED
        frozen.reopened_at = now
        frozen.reopened_by = actor
        frozen.reopen_reason = reason[:300]
        frozen.save(update_fields=["status", "reopened_at", "reopened_by", "reopen_reason"])
        audit.record(
            organization=result.organization,
            actor=actor,
            action="partnership.result_reopened",
            target=frozen,
            before=partnership_before,
            after={**_partnership_summary(frozen), "reason": frozen.reopen_reason},
        )
    result.status = LotResultStatus.REOPENED
    result.reopened_at = now
    result.reopened_by = actor
    result.reopen_reason = reason[:300]
    result.save(update_fields=["status", "reopened_at", "reopened_by", "reopen_reason"])
    audit.record(
        organization=result.organization,
        actor=actor,
        action="lot.reopened",
        target=result,
        before=before,
        after={**_summary(result), "reason": result.reopen_reason},
    )
    return result


# ---- Late costs and settlement with the partner (P6-T03, D-066) ----


def _book_late_adjustment(organization: Organization, actor: User | None, result: PartnershipResult) -> bool:
    """Carry what changed on a closed partnership's lines after its closing to the partner's profit-share balance.
    Returns whether an entry was posted."""
    drift = selectors.late_drift(organization, result)
    if drift is None or drift.pending_basis == 0:
        return False
    partnership = partnerships.partnership_of(organization, result.partnership_id)
    line_ids = result.lot_result_ids
    partnership_services.record_late_adjustment(
        partnership=partnership,
        actor=actor,
        partnership_result_id=result.pk,
        lot_result_id=line_ids[0] if len(line_ids) == 1 else None,
        amount=drift.pending_share,
        basis=drift.pending_basis,
        note=_("Écart de %(amount)s DT sur le résultat du lot après sa clôture")
        % {"amount": display_money(drift.pending_basis)},
    )
    return True


@transaction.atomic
def book_late_adjustments(*, organization: Organization, actor: User | None, batch_id: int) -> bool:
    """Book the line's late costs (and sales) on the next settlement of each partnership that shares it, without
    reopening anything (D-041): the partner's share of the change of their partnership's net goes on their
    profit-share balance, once. Returns whether there was anything to book."""
    _lock_lines(organization, batch_id)
    frozen = selectors.closed_partnership_results_of_line(organization, batch_id=batch_id)
    if not frozen:
        raise ValidationError(_("Ce lot n'est pas un lot de partenariat clôturé."))
    booked = [_book_late_adjustment(organization, actor, result) for result in frozen]
    return any(booked)


def _partnership_to_settle(organization: Organization, *, batch_id: int | None, partnership_id: int | None) -> Any:
    if partnership_id is not None:
        try:
            return partnerships.partnership_of(organization, partnership_id)
        except ObjectDoesNotExist:
            raise ValidationError(_("Ce lot n'est pas un lot de partenariat clôturé.")) from None
    shared = partnerships.live_partnerships_of_line(organization, batch_id=batch_id or 0)
    if len(shared) != 1:
        raise ValidationError(_("Ce lot n'est pas un lot de partenariat clôturé."))
    return shared[0]


@transaction.atomic
def settle_lot(
    *,
    organization: Organization,
    actor: User | None,
    payments: list[dict[str, Any]],
    partnership_id: int | None = None,
    batch_id: int | None = None,
    notes: str = "",
) -> "PartnerSettlement":
    """Settle a closed partnership with its partner (owner only): capital back ± share on the sum of its lines,
    minus what the partner owes from earlier partnerships, paid by the given payments (which must add up to it).
    Given by `partnership_id`, or by `batch_id` for a line shared by one partnership only.

    Before settling, the late costs of every closed partnership of this partner are carried to their balance (the
    "next settlement" of D-041), under their lines' locks taken in line order. A partnership reopened since, or
    never closed, is refused; so is one settled twice.
    """
    partnership = _partnership_to_settle(organization, batch_id=batch_id, partnership_id=partnership_id)
    result = selectors.closed_partnership_result_of(organization, partnership_id=partnership.pk)
    if result is None:
        raise ValidationError(_("Ce lot n'est pas un lot de partenariat clôturé."))
    others = selectors.partner_closed_results(organization, partner_id=partnership.partner_id)
    for lot_id in sorted({*result.batch_ids, *(line for other in others for line in other.batch_ids)}):
        lock_lot(lot_id)
    result = selectors.closed_partnership_result_of(organization, partnership_id=partnership.pk)
    if result is None:
        raise ValidationError(_("Ce lot n'est pas un lot de partenariat clôturé."))
    for other in others:
        _book_late_adjustment(organization, actor, other)
    line_ids = result.lot_result_ids
    return partnership_services.settle_partnership(
        partnership=partnership,
        actor=actor,
        partnership_result_id=result.pk,
        lot_result_id=line_ids[0] if len(line_ids) == 1 else None,
        lot_share=result.partner_share,
        uncovered_loss=result.uncovered_loss,
        payments=payments,
        notes=notes,
    )
