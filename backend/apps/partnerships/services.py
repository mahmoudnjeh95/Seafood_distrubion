"""Every write on partnership lots and the partners' capital goes through these functions (D-060)."""

import datetime as dt
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.core import audit
from apps.core.locks import lock_lot
from apps.core.models import Organization, User
from apps.core.money import Number, checked_amount, display_money
from apps.inventory import selectors as inventory
from apps.sales import selectors as sales
from apps.treasury import services as treasury

from . import selectors
from .models import (
    CapitalEntry,
    CapitalEntryKind,
    LotPartnership,
    PartnerSettlement,
    PartnershipStatus,
    ProfitShareEntry,
    ProfitShareKind,
    SettlementPayment,
    SettlementPaymentMethod,
)

if TYPE_CHECKING:
    from apps.inventory.models import Batch
    from apps.partners.models import Supplier

RATE_STEP = Decimal("0.01")
HUNDRED = Decimal("100")
ZERO = Decimal("0.000")


def _checked_rate(value: Any) -> Decimal | None:
    """A percent from 0 to 100 with at most 2 decimals; None when it is not one."""
    if value in (None, "") or isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        return None
    try:
        rate = Decimal(value)
    except InvalidOperation:
        return None
    if not rate.is_finite() or rate != rate.quantize(RATE_STEP) or not 0 <= rate <= HUNDRED:
        return None
    return rate.quantize(RATE_STEP)


def _snapshot(partnership: LotPartnership) -> dict[str, Any]:
    return {
        "batch": partnership.batch.number,
        "partner": partnership.partner.name,
        "owner_capital": str(partnership.owner_capital),
        "partner_capital": str(partnership.partner_capital),
        "profit_rate": str(partnership.profit_rate),
        "loss_rate": str(partnership.loss_rate),
        "status": partnership.status,
        "terms_pending": partnership.terms_pending,
    }


def has_sold(organization: Organization, *, batch_id: int) -> bool:
    """Whether the lot has a confirmed sale: its terms are then fixed (a cancelled sale gave its kg back)."""
    return batch_id in sales.batch_sales_totals(organization, batch_ids=[batch_id])


def _terms(
    organization: Organization,
    *,
    batch: "Batch",
    partner: "Supplier",
    owner_capital: Number,
    partner_capital: Number,
    profit_rate: Any,
    loss_rate: Any,
    current: LotPartnership | None = None,
) -> dict[str, Any]:
    """The checked terms of a partnership, or every error at once (ValidationError by field)."""
    errors: dict[str, str] = {}
    values: dict[str, Any] = {}
    if batch.organization_id != organization.pk:
        errors["batch"] = _("Lot inconnu.")
    elif current is None and has_sold(organization, batch_id=batch.pk):
        errors["batch"] = _("Ce lot a déjà été vendu en partie : un partenariat se fixe avant la première vente.")
    elif current is None and inventory.quantity_on_hand(organization, batch_id=batch.pk) <= 0:
        errors["batch"] = _("Ce lot n'a plus de stock : un partenariat se fixe sur un lot ouvert.")
    elif current is None and selectors.live_partnership_of_batch(organization, batch_id=batch.pk) is not None:
        errors["batch"] = _("Ce lot a déjà un partenaire : un seul partenaire par lot.")
    if partner.organization_id != organization.pk:
        errors["partner"] = _("Fournisseur inconnu.")
    elif not partner.is_active and (current is None or current.partner_id != partner.pk):
        errors["partner"] = _("Ce fournisseur est archivé.")
    for field, value in (("owner_capital", owner_capital), ("partner_capital", partner_capital)):
        try:
            values[field] = checked_amount(value)
        except (ValueError, TypeError) as error:
            errors[field] = str(error)
    for field, value in (("profit_rate", profit_rate), ("loss_rate", loss_rate)):
        rate = _checked_rate(value)
        if rate is None:
            errors[field] = _("Indiquez un pourcentage de 0 à 100, avec au plus 2 décimales.")
        values[field] = rate
    if errors:
        raise ValidationError(errors)
    return values


def _post_entry(
    partnership: LotPartnership,
    *,
    actor: User | None,
    kind: str,
    amount: Decimal,
    note: str = "",
    lot_result_id: int | None = None,
    on: dt.date | None = None,
) -> CapitalEntry:
    return CapitalEntry.objects.create(
        organization=partnership.organization,
        partnership=partnership,
        kind=kind,
        amount=amount,
        entry_date=on or timezone.localdate(),
        note=note[:300],
        lot_result_id=lot_result_id,
        created_by=actor,
    )


@transaction.atomic
def designate_partner(
    *, organization: Organization, actor: User | None, batch: "Batch", partner: "Supplier"
) -> LotPartnership:
    """Name the partner of a lot at its goods receipt, before capital and rates are known (D-100).

    The supplier of the receipt may be the partner too. Capital and rates are zero and `terms_pending`
    is set: the owner fills them in later (`update_partnership`), even after sales, because the shares
    are only computed when the lot closes, which a pending partnership blocks.
    """
    return create_partnership(
        organization=organization,
        actor=actor,
        batch=batch,
        partner=partner,
        owner_capital=ZERO,
        partner_capital=ZERO,
        profit_rate=ZERO,
        loss_rate=ZERO,
        terms_pending=True,
    )


@transaction.atomic
def create_partnership(
    *,
    organization: Organization,
    actor: User | None,
    batch: "Batch",
    partner: "Supplier",
    owner_capital: Number,
    partner_capital: Number,
    profit_rate: Any,
    loss_rate: Any,
    notes: str = "",
    terms_pending: bool = False,
) -> LotPartnership:
    """Put a lot in partnership with one supplier: at receipt time or on an open lot before its first sale.

    The partner's capital becomes the first entry of their capital ledger in this lot. Refused (by field):
    a lot already sold in part, without stock, or that already has a partner; an unknown or archived
    supplier; an amount below zero or finer than a millime; a rate outside 0-100 or finer than 0.01 %.
    """
    lock_lot(batch.pk)
    values = _terms(
        organization,
        batch=batch,
        partner=partner,
        owner_capital=owner_capital,
        partner_capital=partner_capital,
        profit_rate=profit_rate,
        loss_rate=loss_rate,
    )
    partnership = LotPartnership.objects.create(
        organization=organization,
        batch=batch,
        partner=partner,
        notes=notes.strip(),
        created_by=actor,
        terms_pending=terms_pending,
        **values,
    )
    if partnership.partner_capital > 0:
        _post_entry(partnership, actor=actor, kind=CapitalEntryKind.CONTRIBUTION, amount=partnership.partner_capital)
    audit.record(
        organization=organization,
        actor=actor,
        action="partnership.created",
        target=partnership,
        after=_snapshot(partnership),
    )
    return partnership


def _locked(partnership: LotPartnership) -> LotPartnership:
    lock_lot(partnership.batch_id)
    return (
        LotPartnership.objects.select_for_update(of=("self",))
        .select_related("organization", "batch", "partner")
        .get(pk=partnership.pk)
    )


@transaction.atomic
def update_partnership(
    *,
    partnership: LotPartnership,
    actor: User | None,
    partner: "Supplier | None" = None,
    owner_capital: Number | None = None,
    partner_capital: Number | None = None,
    profit_rate: Any = None,
    loss_rate: Any = None,
    notes: str | None = None,
) -> LotPartnership:
    """Change the terms of an open partnership, until its lot is closed (D-163). A changed partner capital
    posts a correction (the difference) on the capital ledger; the ledger itself is never rewritten."""
    partnership = _locked(partnership)
    organization = partnership.organization
    if partnership.status != PartnershipStatus.OPEN:
        raise ValidationError(_("Ce partenariat n'est plus en cours : ses conditions ne changent plus."))
    before = _snapshot(partnership)
    old_capital = partnership.partner_capital
    values = _terms(
        organization,
        batch=partnership.batch,
        partner=partner or partnership.partner,
        owner_capital=partnership.owner_capital if owner_capital is None else owner_capital,
        partner_capital=partnership.partner_capital if partner_capital is None else partner_capital,
        profit_rate=partnership.profit_rate if profit_rate is None else profit_rate,
        loss_rate=partnership.loss_rate if loss_rate is None else loss_rate,
        current=partnership,
    )
    for field, value in values.items():
        setattr(partnership, field, value)
    if partnership.terms_pending and profit_rate is not None and loss_rate is not None:
        partnership.terms_pending = False
    if partner is not None:
        partnership.partner = partner
    if notes is not None:
        partnership.notes = notes.strip()
    partnership.save()
    difference = partnership.partner_capital - old_capital
    if difference:
        _post_entry(
            partnership,
            actor=actor,
            kind=CapitalEntryKind.CORRECTION if old_capital else CapitalEntryKind.CONTRIBUTION,
            amount=difference,
        )
    audit.record(
        organization=organization,
        actor=actor,
        action="partnership.updated",
        target=partnership,
        before=before,
        after=_snapshot(partnership),
    )
    return partnership


@transaction.atomic
def cancel_partnership(*, partnership: LotPartnership, actor: User | None, reason: str) -> LotPartnership:
    """Remove a partnership set by mistake, before the lot's first sale. The capital still in goes back
    to the partner (a `return` entry); the partnership stays, cancelled, with who, when and why."""
    partnership = _locked(partnership)
    organization = partnership.organization
    if not reason.strip():
        raise ValidationError({"reason": _("Indiquez pourquoi le partenariat est annulé.")})
    if partnership.status != PartnershipStatus.OPEN:
        raise ValidationError(_("Seul un partenariat en cours peut être annulé."))
    if has_sold(organization, batch_id=partnership.batch_id):
        raise ValidationError(_("Ce lot a déjà été vendu en partie : le partenariat ne peut plus être annulé."))
    before = _snapshot(partnership)
    balance = selectors.capital_balance(partnership)
    if balance:
        _post_entry(
            partnership,
            actor=actor,
            kind=CapitalEntryKind.RETURN,
            amount=-balance,
            note=_("Partenariat annulé : %(reason)s") % {"reason": reason.strip()},
        )
    partnership.status = PartnershipStatus.CANCELLED
    partnership.cancelled_at = timezone.now()
    partnership.cancelled_by = actor
    partnership.cancel_reason = reason.strip()[:300]
    partnership.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="partnership.cancelled",
        target=partnership,
        before=before,
        after={**_snapshot(partnership), "reason": partnership.cancel_reason},
    )
    return partnership


# ---- Called by `closing` when a lot closes or reopens (P6-T02, D-061) ----


def record_lot_closed(
    *, partnership: LotPartnership, actor: User | None, lot_result_id: int, capital_deducted: Decimal, on: dt.date
) -> LotPartnership:
    """The lot's result is frozen: the partnership is closed, and a loss share taken from the capital is
    posted on the ledger (D-031). Runs inside the closing's transaction, which holds the lot's lock."""
    partnership = _locked(partnership)
    if partnership.status != PartnershipStatus.OPEN:
        raise ValidationError(_("Ce partenariat n'est pas en cours."))
    if capital_deducted > 0:
        _post_entry(
            partnership,
            actor=actor,
            kind=CapitalEntryKind.LOSS_DEDUCTION,
            amount=-capital_deducted,
            lot_result_id=lot_result_id,
            on=on,
        )
    partnership.status = PartnershipStatus.CLOSED
    partnership.save(update_fields=["status", "updated_at"])
    return partnership


def record_lot_reopened(
    *, partnership: LotPartnership, actor: User | None, lot_result_id: int, capital_deducted: Decimal, reason: str
) -> LotPartnership:
    """A closed lot is reopened: the partnership is open again and a deducted loss share comes back to the
    capital (a reversal entry, never an edit). The next closing computes and deducts it again."""
    partnership = _locked(partnership)
    if partnership.status != PartnershipStatus.CLOSED:
        raise ValidationError(_("Ce partenariat n'est pas clôturé : il a peut-être déjà été réglé."))
    if capital_deducted > 0:
        _post_entry(
            partnership,
            actor=actor,
            kind=CapitalEntryKind.LOSS_REVERSAL,
            amount=capital_deducted,
            note=reason,
            lot_result_id=lot_result_id,
        )
    partnership.status = PartnershipStatus.OPEN
    partnership.save(update_fields=["status", "updated_at"])
    return partnership


# ---- Late costs and settlement with the partner (P6-T03, D-066), called by `closing` ----


def _post_share_entry(
    partnership: LotPartnership,
    *,
    actor: User | None,
    kind: str,
    amount: Decimal,
    basis: Decimal = ZERO,
    note: str = "",
    lot_result_id: int | None = None,
    settlement: PartnerSettlement | None = None,
    on: dt.date | None = None,
) -> ProfitShareEntry:
    return ProfitShareEntry.objects.create(
        organization=partnership.organization,
        partnership=partnership,
        kind=kind,
        amount=amount,
        basis=basis,
        entry_date=on or timezone.localdate(),
        note=note[:300],
        lot_result_id=lot_result_id,
        settlement=settlement,
        created_by=actor,
    )


@transaction.atomic
def record_late_adjustment(
    *,
    partnership: LotPartnership,
    actor: User | None,
    lot_result_id: int,
    amount: Decimal,
    basis: Decimal,
    note: str = "",
) -> ProfitShareEntry:
    """A cost or a sale recorded after the lot closed changed its net result by `basis`: the difference in
    the partner's share (`amount`, signed) goes on their profit-share balance, so their next settlement
    pays or recovers it. The lot is never reopened (D-041) and its frozen result is not touched."""
    partnership = _locked(partnership)
    if partnership.status not in (PartnershipStatus.CLOSED, PartnershipStatus.SETTLED):
        raise ValidationError(_("Ce partenariat n'est pas clôturé."))
    entry = _post_share_entry(
        partnership,
        actor=actor,
        kind=ProfitShareKind.LATE_ADJUSTMENT,
        amount=amount,
        basis=basis,
        note=note,
        lot_result_id=lot_result_id,
    )
    audit.record(
        organization=partnership.organization,
        actor=actor,
        action="partnership.late_adjustment",
        target=partnership,
        after={"batch": partnership.batch.number, "amount": str(amount), "basis": str(basis), "note": note},
    )
    return entry


def _checked_payments(payments: list[dict[str, Any]], on: dt.date) -> list[dict[str, Any]]:
    checked: list[dict[str, Any]] = []
    errors: list[str] = []
    for payment in payments:
        try:
            amount = checked_amount(payment.get("amount", ""))
        except (ValueError, TypeError) as error:
            errors.append(str(error))
            continue
        method = payment.get("method", "")
        if amount <= 0:
            errors.append(_("Un paiement doit être supérieur à zéro."))
        elif method not in SettlementPaymentMethod.values:
            errors.append(_("Mode de paiement inconnu."))
        else:
            checked.append(
                {
                    "amount": amount,
                    "method": method,
                    "paid_on": payment.get("paid_on") or on,
                    "reference": str(payment.get("reference", ""))[:50],
                }
            )
    if errors:
        raise ValidationError({"payments": errors})
    return checked


@transaction.atomic
def settle_partnership(
    *,
    partnership: LotPartnership,
    actor: User | None,
    lot_result_id: int,
    lot_share: Decimal,
    uncovered_loss: Decimal,
    payments: list[dict[str, Any]],
    settled_on: dt.date | None = None,
    notes: str = "",
) -> PartnerSettlement:
    """Settle a closed partnership lot with its partner: pay their capital back and their profit share.

    The three balances stay separate. The capital ledger gets a `return` of what is left of the capital
    (after a loss share was deducted at closing). The profit-share ledger gets the lot's `share` (a
    profit) or its `uncovered_loss` (D-031), then its balance over all the partner's lots decides the
    payout: a positive balance is paid, a negative one (a loss beyond capital, a late cost) is recovered
    from this share and, when the share is not enough, carried to the next settlement; it is never taken
    from the capital. The payments given must add up to exactly what is paid; nothing to pay means none.
    """
    partnership = _locked(partnership)
    organization = partnership.organization
    if partnership.status == PartnershipStatus.SETTLED:
        raise ValidationError(_("Ce lot est déjà réglé avec le partenaire."))
    if partnership.status != PartnershipStatus.CLOSED:
        raise ValidationError(_("Clôturez le lot avant de le régler avec le partenaire."))
    on = settled_on or timezone.localdate()

    capital = selectors.capital_balance(partnership)
    carried_in = selectors.profit_share_balance_of_partner(organization, partner_id=partnership.partner_id)
    lot_entry = lot_share if lot_share > 0 else -uncovered_loss
    balance = carried_in + lot_entry
    share_paid = balance if balance > 0 else ZERO
    total = capital + share_paid

    checked = _checked_payments(payments, on)
    paid = sum((payment["amount"] for payment in checked), ZERO)
    if paid != total:
        raise ValidationError(
            {
                "payments": _("Les paiements (%(paid)s DT) doivent égaler le montant à régler (%(total)s DT).")
                % {"paid": display_money(paid), "total": display_money(total)}
            }
        )

    settlement = PartnerSettlement.objects.create(
        organization=organization,
        partnership=partnership,
        lot_result_id=lot_result_id,
        settled_on=on,
        capital_returned=capital,
        lot_share=lot_share,
        uncovered_loss=uncovered_loss,
        carried_in=carried_in,
        share_paid=share_paid,
        amount_paid=total,
        carried_out=balance - share_paid,
        notes=notes.strip(),
        created_by=actor,
    )
    entries = [
        (ProfitShareKind.SHARE, lot_share) if lot_share > 0 else (ProfitShareKind.UNCOVERED_LOSS, -uncovered_loss),
        (ProfitShareKind.PAYMENT, -share_paid),
    ]
    for kind, amount in entries:
        if amount:
            _post_share_entry(
                partnership,
                actor=actor,
                kind=kind,
                amount=amount,
                lot_result_id=lot_result_id,
                settlement=settlement,
                on=on,
            )
    if capital > 0:
        _post_entry(
            partnership,
            actor=actor,
            kind=CapitalEntryKind.RETURN,
            amount=-capital,
            note=_("Règlement du lot"),
            lot_result_id=lot_result_id,
            on=on,
        )
    for payment in checked:
        row = SettlementPayment.objects.create(organization=organization, settlement=settlement, **payment)
        _post_settlement_money(row, settlement=settlement, actor=actor)
    partnership.status = PartnershipStatus.SETTLED
    partnership.save(update_fields=["status", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="partnership.settled",
        target=partnership,
        after={
            "batch": partnership.batch.number,
            "partner": partnership.partner.name,
            "capital_returned": str(capital),
            "lot_share": str(lot_share),
            "uncovered_loss": str(uncovered_loss),
            "carried_in": str(carried_in),
            "share_paid": str(share_paid),
            "amount_paid": str(total),
            "carried_out": str(settlement.carried_out),
        },
    )
    return settlement


# The money paid to a partner leaves our accounts the day it was paid, by the method it was paid with (P9-T05b, D-240).
SETTLEMENT_PAYMENT_SOURCE = "partnerships.settlement_payment"


def _post_settlement_money(payment: SettlementPayment, *, settlement: PartnerSettlement, actor: User | None) -> None:
    treasury.post_movement(
        organization=payment.organization,
        account=treasury.line_account(payment.organization, payment.method, None),
        day=payment.paid_on,
        amount=-payment.amount,
        kind="partner_settlement",
        label=f"{settlement.partnership.partner.name} · {settlement.partnership.batch.number}",
        reference=payment.reference or settlement.partnership.batch.number,
        source=SETTLEMENT_PAYMENT_SOURCE,
        source_id=payment.pk,
        actor=actor,
    )


def post_treasury_history(*, organization: Organization) -> None:
    """Write the money of the partner settlements paid before the ledger existed. Safe to run again."""
    payments = SettlementPayment.objects.filter(organization=organization).select_related(
        "organization", "settlement__partnership__partner", "settlement__partnership__batch"
    )
    for payment in payments:
        _post_settlement_money(payment, settlement=payment.settlement, actor=None)
