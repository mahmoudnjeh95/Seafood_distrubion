from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, OrganizationScopedQuerySet
from apps.core.money import MoneyField


class LotResultStatus(models.TextChoices):
    # The lot is closed: this is its result, frozen.
    CLOSED = "closed", _("Clôturé")
    # The owner reopened the lot (reason kept): this copy is history, a new closing makes a new one.
    REOPENED = "reopened", _("Rouvert")


class LotOutcome(models.TextChoices):
    """What a net result is (engine.outcome_of): it decides which of the partner's two rates applies."""

    PROFIT = "profit", _("Bénéfice")
    ZERO = "zero", _("Nul")
    LOSS = "loss", _("Perte")


class LotState(models.TextChoices):
    """Where a lot stands for its result: still open (live result) or closed (frozen result)."""

    OPEN = "open", _("En cours")
    CLOSED = "closed", _("Clôturé")


class SettlementState(models.TextChoices):
    """Where a lot stands with its partner (P6-T03, D-066): no partnership, still open, closed and ready to
    settle, or settled."""

    NONE = "none", _("Sans partenaire")
    NOT_CLOSED = "not_closed", _("Lot non clôturé")
    READY = "ready", _("À régler")
    SETTLED = "settled", _("Réglé")


class LotResultQuerySet(OrganizationScopedQuerySet["LotResult"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("A lot result is frozen: reopen the lot (with a reason) and close it again")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("A lot result is never deleted: reopening keeps it as history")


class LotResult(OrganizationScopedModel):
    """The frozen result of a closed lot (P6-T02, D-061): the whole computation as it was, kept as JSON with
    its main figures as columns for lists and totals.

    Immutable once written (ARCHITECTURE §4.5): only `status` and the reopening fields change, once, when
    the owner reopens the lot with a reason. A cost or a payment arriving later never rewrites it: it goes
    to the partner's next settlement (D-041, P6-T03).
    """

    # By name, not by import (ARCHITECTURE §3).
    batch = models.ForeignKey("inventory.Batch", on_delete=models.PROTECT, related_name="+")
    partnership = models.ForeignKey(
        "partnerships.LotPartnership", null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    status = models.CharField(max_length=20, choices=LotResultStatus.choices, default=LotResultStatus.CLOSED)
    revenue = MoneyField()
    cogs = MoneyField()
    spoilage = MoneyField()
    costs_total = MoneyField()
    net_result = MoneyField()
    owner_share = MoneyField()
    # The partner's side (zero without a partnership): signed share, loss share taken from the capital,
    # the part the capital could not cover (carried, D-031) and the capital to give back.
    partner_share = MoneyField(default=0)
    capital_deducted = MoneyField(default=0)
    uncovered_loss = MoneyField(default=0)
    capital_to_return = MoneyField(default=0)
    # Customers still owed money on the lot's sales when it closed: customer payments are not tracked yet
    # (P2-T06), so this is a warning kept with the result, not a refusal.
    payments_unverified = models.BooleanField(default=False)
    # `engine.to_json` of the result, with the closing checks as they were.
    data = models.JSONField(encoder=DjangoJSONEncoder)
    closed_at = models.DateTimeField()
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reopen_reason = models.CharField(max_length=300, blank=True)

    objects = LotResultQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["-closed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["batch"], condition=models.Q(status="closed"), name="one_closed_result_per_lot"
            ),
        ]

    def __str__(self) -> str:
        return f"{self.batch} · {self.get_status_display()}"


class PartnershipResultQuerySet(OrganizationScopedQuerySet["PartnershipResult"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("A partnership result is frozen: reopen one of its lots (with a reason) and close it again")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("A partnership result is never deleted: reopening keeps it as history")


class PartnershipResult(OrganizationScopedModel):
    """The frozen result of one partnership (P6-T08, D-320, D-324): the partner's rate on the *sum* of the frozen
    nets of the lines it shares, rounded once (D-031). Frozen when the last of those lines closes.

    Each line keeps its own `LotResult` (the engine, unchanged, per product); this is what the partner's ledgers and
    settlement read. Immutable like a `LotResult`: reopening one of its lines marks it `reopened` (history) and the
    next closing of the lines freezes a new one.
    """

    # By name, not by import (ARCHITECTURE §3).
    partnership = models.ForeignKey("partnerships.LotPartnership", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=20, choices=LotResultStatus.choices, default=LotResultStatus.CLOSED)
    # Sum of the frozen nets of its lines, the partner's signed share of it and what the owner keeps (net − share).
    net_result = MoneyField()
    partner_share = MoneyField()
    owner_share = MoneyField()
    capital_deducted = MoneyField(default=0)
    uncovered_loss = MoneyField(default=0)
    capital_to_return = MoneyField(default=0)
    # `engine.partnership_result_to_json`: its lines (each with its `LotResult` id and net) and the steps.
    data = models.JSONField(encoder=DjangoJSONEncoder)
    closed_at = models.DateTimeField()
    closed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reopen_reason = models.CharField(max_length=300, blank=True)

    objects = PartnershipResultQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["-closed_at", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["partnership"],
                condition=models.Q(status="closed"),
                name="one_closed_result_per_partnership",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.partnership_id} · {self.get_status_display()}"

    @property
    def lot_result_ids(self) -> list[int]:
        return [int(line["lot_result_id"]) for line in self.data.get("lines", []) if line.get("lot_result_id")]

    @property
    def batch_ids(self) -> list[int]:
        return [int(line["batch_id"]) for line in self.data.get("lines", [])]


# ---- The monthly closing for the accountant (P6-T06, D-074) ----


class MonthlyClosingStatus(models.TextChoices):
    # The accountant checked the month's figures; the owner has not approved them yet.
    REVIEWED = "reviewed", _("Vérifié")
    # The owner approved: the month is locked and its figures frozen.
    APPROVED = "approved", _("Approuvé")
    # The owner reopened it (reason kept): this copy is history, a new review and approval make a new one.
    REOPENED = "reopened", _("Rouvert")


class MonthState(models.TextChoices):
    """Where a month stands: still open (live figures), reviewed by the accountant, or approved (frozen)."""

    OPEN = "open", _("Ouvert")
    REVIEWED = "reviewed", _("Vérifié")
    APPROVED = "approved", _("Approuvé")


class MonthlyClosingQuerySet(OrganizationScopedQuerySet["MonthlyClosing"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("A monthly closing is frozen: reopen the month (with a reason) and close it again")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("A monthly closing is never deleted: reopening keeps it as history")


class MonthlyClosing(OrganizationScopedModel):
    """The accountant's review and the owner's approval of one month, with the figures as they were.

    One live row per month (reviewed, then approved); a reopened one stays as history. `data` is
    `monthly.to_json` of the report. The review keeps a fingerprint of the figures: if they change before the
    owner approves, the accountant must review again. It does not change the partners' shares, which are
    settled per lot (D-040).
    """

    month = models.DateField()
    status = models.CharField(max_length=20, choices=MonthlyClosingStatus.choices)
    revenue = MoneyField()
    cogs = MoneyField()
    spoilage = MoneyField()
    operating_costs = MoneyField()
    net_result = MoneyField()
    closing_stock_value = MoneyField()
    data = models.JSONField(encoder=DjangoJSONEncoder)
    # What the review looked at: approving figures that moved since is refused.
    fingerprint = models.CharField(max_length=64)
    reviewed_at = models.DateTimeField()
    reviewed_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    review_notes = models.CharField(max_length=300, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reopened_at = models.DateTimeField(null=True, blank=True)
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reopen_reason = models.CharField(max_length=300, blank=True)

    objects = MonthlyClosingQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["-month", "-id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "month"],
                condition=models.Q(status__in=["reviewed", "approved"]),
                name="one_live_closing_per_month",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.month:%Y-%m} · {self.get_status_display()}"
