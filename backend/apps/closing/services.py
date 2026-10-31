"""Closing and reopening a lot: its result frozen, or unfrozen with a reason (P6-T02, D-061)."""

from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
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
from .models import LotResult, LotResultStatus

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


@transaction.atomic
def close_lot(
    *, organization: Organization, actor: User | None, batch_id: int, costs_confirmed: bool = False
) -> LotResult:
    """Close a lot: check it is finished, then freeze its result (Q19, D-040).

    Refused: a lot already closed; stock still on hand (sell it or record it as a loss); costs typed on
    the lot still waiting for approval; `costs_confirmed` not given (only the person closing knows every
    cost is in); customers still owing money on its sales (customer payments, P2-T06, D-062).
    A partner's loss share is taken from their capital in the same transaction. Two
    closings of the same lot at once: the second waits, then is refused.
    """
    lock_lot(batch_id)
    if selectors.closed_result_of(organization, batch_id=batch_id) is not None:
        raise ValidationError(_("Ce lot est déjà clôturé."))
    pending = partnerships.live_partnership_of_batch(organization, batch_id=batch_id)
    if pending is not None and pending.terms_pending:
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
    if partnership is not None and partner is not None:
        partnership_services.record_lot_closed(
            partnership=partnership,
            actor=actor,
            lot_result_id=result.pk,
            capital_deducted=partner.capital_deducted,
            on=timezone.localdate(),
        )
    audit.record(organization=organization, actor=actor, action="lot.closed", target=result, after=_summary(result))
    return result


@transaction.atomic
def reopen_lot(*, result: LotResult, actor: User | None, reason: str) -> LotResult:
    """Reopen a closed lot, with a reason (audited). Its frozen result stays as history (status
    `reopened`), the partner's deducted loss share comes back to their capital, and the next closing
    freezes a new result. A lot already settled with its partner is not reopened: a correction then
    goes to the partner's next settlement (D-041, P6-T03)."""
    lock_lot(result.batch_id)
    result = LotResult.objects.select_for_update(of=("self",)).select_related("batch").get(pk=result.pk)
    if result.status != LotResultStatus.CLOSED:
        raise ValidationError(_("Ce lot n'est pas clôturé."))
    if not reason.strip():
        raise ValidationError({"reason": _("Indiquez pourquoi le lot est rouvert.")})
    before = _summary(result)
    if result.partnership_id is not None:
        partnership = partnerships.partnership_of(result.organization, result.partnership_id)
        partnership_services.record_lot_reopened(
            partnership=partnership,
            actor=actor,
            lot_result_id=result.pk,
            capital_deducted=result.capital_deducted,
            reason=reason.strip(),
        )
    result.status = LotResultStatus.REOPENED
    result.reopened_at = timezone.now()
    result.reopened_by = actor
    result.reopen_reason = reason.strip()[:300]
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


def _book_late_adjustment(organization: Organization, actor: User | None, result: LotResult) -> bool:
    """Carry what changed on a closed lot after its closing to the partner's profit-share balance. A lot
    without a partner has nothing to carry: its drift is only shown. Returns whether an entry was posted."""
    drift = selectors.late_drift(organization, result)
    if drift is None or drift.pending_basis == 0:
        return False
    partnership = partnerships.partnership_of(organization, result.partnership_id or 0)
    partnership_services.record_late_adjustment(
        partnership=partnership,
        actor=actor,
        lot_result_id=result.pk,
        amount=drift.pending_share,
        basis=drift.pending_basis,
        note=_("Écart de %(amount)s DT sur le résultat du lot après sa clôture")
        % {"amount": display_money(drift.pending_basis)},
    )
    return True


@transaction.atomic
def book_late_adjustments(*, organization: Organization, actor: User | None, batch_id: int) -> bool:
    """Book the lot's late costs (and sales) on the partner's next settlement, without reopening the lot
    (D-041): the partner's share of the change goes on their profit-share balance, once. Returns whether
    there was anything to book."""
    lock_lot(batch_id)
    result = selectors.closed_result_of(organization, batch_id=batch_id)
    if result is None or result.partnership_id is None:
        raise ValidationError(_("Ce lot n'est pas un lot de partenariat clôturé."))
    return _book_late_adjustment(organization, actor, result)


@transaction.atomic
def settle_lot(
    *,
    organization: Organization,
    actor: User | None,
    batch_id: int,
    payments: list[dict[str, Any]],
    notes: str = "",
) -> "PartnerSettlement":
    """Settle a closed partnership lot with its partner (owner only): capital back ± share, minus what the
    partner owes from earlier lots, paid by the given payments (which must add up to it).

    Before settling, the late costs of every closed lot of this partner are carried to their balance (the
    "next settlement" of D-041), in lot order under each lot's lock. A lot reopened since, or never closed,
    is refused; so is a lot settled twice.
    """
    result = selectors.closed_result_of(organization, batch_id=batch_id)
    if result is None or result.partnership_id is None:
        raise ValidationError(_("Ce lot n'est pas un lot de partenariat clôturé."))
    partnership = partnerships.partnership_of(organization, result.partnership_id)
    others = selectors.partner_closed_results(organization, partner_id=partnership.partner_id)
    for lot_id in sorted({batch_id, *(other.batch_id for other in others)}):
        lock_lot(lot_id)
    result = selectors.closed_result_of(organization, batch_id=batch_id) or result
    for other in others:
        _book_late_adjustment(organization, actor, other)
    return partnership_services.settle_partnership(
        partnership=partnership,
        actor=actor,
        lot_result_id=result.pk,
        lot_share=result.partner_share,
        uncovered_loss=result.uncovered_loss,
        payments=payments,
        notes=notes,
    )
