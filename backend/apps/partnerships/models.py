from typing import Any

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, OrganizationScopedQuerySet, TimeStampedModel
from apps.core.money import MoneyField

# ---- Partnership lots (P6-T01, D-060) ----


class PartnershipStatus(models.TextChoices):
    # The lot is still being sold: its result is live ("so far").
    OPEN = "open", _("En cours")
    # The lot is closed and its result frozen (P6-T02): capital back ± share is known.
    CLOSED = "closed", _("Clôturé")
    # The partner got their capital back ± share (P6-T03).
    SETTLED = "settled", _("Réglé")
    # Removed before the lot's first sale: the capital went back, nothing was shared.
    CANCELLED = "cancelled", _("Annulé")


class LotPartnership(OrganizationScopedModel, TimeStampedModel):
    """A lot bought together by the owner and one partner supplier (client meeting §5, D-040, D-060).

    Each side puts money in. When the lot closes, the partner gets their profit % of the net profit, or
    carries their loss % of the loss, deducted from their capital (Q3, D-031). One live partnership per
    lot; a supplier can be a partner in several lots at once, each with its own capital and rates (Q22).
    The terms change only before the lot's first sale; then they are what the result uses.
    """

    # By name, not by import (ARCHITECTURE §3): read through `inventory.selectors` and `partners.selectors`.
    batch = models.ForeignKey("inventory.Batch", on_delete=models.PROTECT, related_name="+")
    partner = models.ForeignKey("partners.Supplier", on_delete=models.PROTECT, related_name="+")
    # What each side put into the lot. The partner's is also the first entry of their capital ledger.
    owner_capital = MoneyField()
    partner_capital = MoneyField()
    # Percent with 2 decimals: the partner's share of a profit, and of a loss (two rates, D-031).
    profit_rate = models.DecimalField(max_digits=5, decimal_places=2)
    loss_rate = models.DecimalField(max_digits=5, decimal_places=2)
    status = models.CharField(max_length=20, choices=PartnershipStatus.choices, default=PartnershipStatus.OPEN)
    # The partner was named at the goods receipt, before anyone agreed on capital and rates (D-100): the amounts
    # and rates above are placeholders (zero) until the owner fills them in. The lot cannot close meanwhile.
    terms_pending = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancelled_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    cancel_reason = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch"],
                condition=~models.Q(status="cancelled"),
                name="one_live_partnership_per_lot",
            ),
            models.CheckConstraint(
                condition=models.Q(owner_capital__gte=0) & models.Q(partner_capital__gte=0),
                name="partnership_capital_not_negative",
            ),
            models.CheckConstraint(
                condition=models.Q(profit_rate__gte=0)
                & models.Q(profit_rate__lte=100)
                & models.Q(loss_rate__gte=0)
                & models.Q(loss_rate__lte=100),
                name="partnership_rates_are_percents",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.batch} · {self.partner}"


# ---- The partner's capital, a ledger per partner and lot ----


class SettlementPaymentMethod(models.TextChoices):
    CASH = "cash", _("Espèces")
    CHEQUE = "cheque", _("Chèque")
    TRANSFER = "transfer", _("Virement")
    BILL = "bill", _("Traite")
    OTHER = "other", _("Autre")


class CapitalEntryKind(models.TextChoices):
    # Money the partner put into the lot (+).
    CONTRIBUTION = "contribution", _("Apport")
    # The amount put in was corrected before the first sale (+ or −).
    CORRECTION = "correction", _("Correction de l'apport")
    # Their loss share taken from their capital when the lot closed at a loss (−, D-031).
    LOSS_DEDUCTION = "loss_deduction", _("Part de perte déduite")
    # A reopened lot gives the deducted loss share back (+): the next closing deducts it again.
    LOSS_REVERSAL = "loss_reversal", _("Annulation de la déduction")
    # Capital paid back to the partner (−): at settlement (P6-T03) or when a partnership is cancelled.
    RETURN = "return", _("Remboursement")
    # Part of the capital paid to the partner before the settlement (−), with the means of payment (owner
    # request 2026-11-02). The settlement pays what is left.
    ADVANCE = "advance", _("Avance sur capital")


class CapitalEntryQuerySet(OrganizationScopedQuerySet["CapitalEntry"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("Capital entries are append-only: post a correcting entry instead")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("Capital entries are append-only: they are never deleted")


class CapitalEntry(OrganizationScopedModel):
    """One change of a partner's capital in one lot (D-060). Signed: + puts money in, − takes it out.

    The capital is a balance of its own: never mixed with what the company owes the supplier for goods
    (D-043) nor with their profit share (D-031). Append-only, like the stock ledger.
    """

    partnership = models.ForeignKey(LotPartnership, on_delete=models.PROTECT, related_name="capital_entries")
    kind = models.CharField(max_length=20, choices=CapitalEntryKind.choices)
    amount = MoneyField()
    entry_date = models.DateField()
    note = models.CharField(max_length=300, blank=True)
    # The means and reference of an advance (blank for every other kind).
    method = models.CharField(max_length=20, choices=SettlementPaymentMethod.choices, blank=True)
    reference = models.CharField(max_length=50, blank=True)
    # The frozen lot result that caused it (a loss deduction or its reversal), by id: `closing` reads us.
    lot_result_id = models.PositiveBigIntegerField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    objects = CapitalEntryQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["entry_date", "id"]
        verbose_name_plural = "capital entries"

    def __str__(self) -> str:
        return f"{self.partnership} · {self.kind} · {self.amount}"


# ---- The partner's profit share, a second ledger per partner and lot (P6-T03, D-066) ----


class ProfitShareKind(models.TextChoices):
    # The partner's part of the lot's profit, posted when the lot is settled (+: the company owes it).
    SHARE = "share", _("Part de bénéfice")
    # The part of their loss share their capital could not cover (−: the partner owes it, D-031).
    UNCOVERED_LOSS = "uncovered_loss", _("Perte au-delà de l'apport")
    # A cost or a sale recorded after the lot closed changed the net result: the difference in their share
    # (±), carried to the partner's next settlement, never by reopening the lot (D-041).
    LATE_ADJUSTMENT = "late_adjustment", _("Régularisation après clôture")
    # What was paid out of the profit share at a settlement (−).
    PAYMENT = "payment", _("Paiement")


class ProfitShareEntryQuerySet(OrganizationScopedQuerySet["ProfitShareEntry"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("Profit share entries are append-only: post a correcting entry instead")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("Profit share entries are append-only: they are never deleted")


class ProfitShareEntry(OrganizationScopedModel):
    """One change of the partner's profit-share balance, signed: + the company owes the partner, − the
    partner owes the company. A balance of its own, separate from their capital (CapitalEntry) and from
    what is owed for goods (D-043): the three are never mixed (D-031, D-040). Append-only."""

    partnership = models.ForeignKey(LotPartnership, on_delete=models.PROTECT, related_name="profit_share_entries")
    kind = models.CharField(max_length=20, choices=ProfitShareKind.choices)
    amount = MoneyField()
    # A late adjustment: the change of the lot's net result it covers (a cost of 100 is -100). The sum
    # over the lot's adjustments is what is already booked; the rest of the drift is still to book.
    basis = MoneyField(default=0)
    entry_date = models.DateField()
    note = models.CharField(max_length=300, blank=True)
    lot_result_id = models.PositiveBigIntegerField(null=True, blank=True)
    settlement = models.ForeignKey(
        "partnerships.PartnerSettlement", null=True, blank=True, on_delete=models.PROTECT, related_name="entries"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    objects = ProfitShareEntryQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["entry_date", "id"]
        verbose_name_plural = "profit share entries"

    def __str__(self) -> str:
        return f"{self.partnership} · {self.kind} · {self.amount}"


class PartnerSettlement(OrganizationScopedModel, TimeStampedModel):
    """The settlement of one partnership lot with its partner (P6-T03, D-066): the capital back, ± the
    profit share, minus what the partner still owed from earlier lots, paid out. One per partnership; a
    recorded settlement is never edited (a later correction is a late adjustment on the next one)."""

    partnership = models.OneToOneField(LotPartnership, on_delete=models.PROTECT, related_name="settlement")
    lot_result_id = models.PositiveBigIntegerField()
    settled_on = models.DateField()
    # Capital returned to the partner (what was left of it after a loss share).
    capital_returned = MoneyField()
    # The lot's share, signed, as frozen at the closing; and the part of a loss their capital did not cover.
    lot_share = MoneyField()
    uncovered_loss = MoneyField(default=0)
    # The partner's profit-share balance (all their lots) just before this lot's own entries, signed: a
    # negative one is what they owe from an earlier lot or a late cost, recovered from this share.
    carried_in = MoneyField(default=0)
    # Paid out of the profit share, and in total with the capital (= the sum of the payments).
    share_paid = MoneyField(default=0)
    amount_paid = MoneyField(default=0)
    # What the partner still owes after this settlement (0 or negative), carried to their next one.
    carried_out = MoneyField(default=0)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-settled_on", "-id"]

    def __str__(self) -> str:
        return f"{self.partnership} · {self.settled_on}"


class SettlementPayment(OrganizationScopedModel):
    """Money paid to the partner at a settlement: one line per way of paying (cash, cheque...)."""

    settlement = models.ForeignKey(PartnerSettlement, on_delete=models.PROTECT, related_name="payments")
    paid_on = models.DateField()
    amount = MoneyField()
    method = models.CharField(max_length=20, choices=SettlementPaymentMethod.choices)
    reference = models.CharField(max_length=50, blank=True)

    class Meta:
        ordering = ["paid_on", "id"]
        constraints = [models.CheckConstraint(condition=models.Q(amount__gt=0), name="settlement_payment_positive")]

    def __str__(self) -> str:
        return f"{self.settlement} · {self.method} · {self.amount}"
