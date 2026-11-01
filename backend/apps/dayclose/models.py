from typing import Any

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel
from apps.core.money import MoneyField


class DayClosingStatus(models.TextChoices):
    # Sent by the driver, waiting for the office.
    SUBMITTED = "submitted", _("À vérifier")
    # The office asks the driver to explain; the driver sends it again with a note.
    JUSTIFICATION = "justification", _("Justification demandée")
    # Checked and locked: only a new load of that date opens it again (D-134).
    APPROVED = "approved", _("Approuvée")
    # The truck was loaded again after the send: the day runs, the driver sends it again at the end.
    REOPENED = "reopened", _("Rouverte")


class DayClosing(OrganizationScopedModel, TimeStampedModel):
    """The end of a driver's day (P3-T06, D-094): what the driver should hold, and the cash the office counts
    (D-213; only the office counts). The figures are kept as they were when the driver sent them (the last send;
    the sends a new load undid are in `reopenings`)."""

    # By name, not by import (ARCHITECTURE §3).
    driver_day = models.OneToOneField("fleet.DriverDay", on_delete=models.PROTECT, related_name="closing")
    status = models.CharField(max_length=20, choices=DayClosingStatus.choices, default=DayClosingStatus.SUBMITTED)
    # What the records say: opening cash + cash sales - cash expenses. The driver is shown it, never asked to count.
    expected_cash = MoneyField()
    # The driver's own count and its gap (D-094, D-158): kept for the sends made before D-213, empty since.
    counted_cash = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    difference = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    # The purchase money, counted apart from the sales cash (D-158): what should be left of it.
    expected_purchase_cash = MoneyField(default=0)
    counted_purchase_cash = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    purchase_difference = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    # The cash the office counted when the driver handed it over (D-204, D-213); empty until the office counts.
    office_counted_cash = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    office_counted_purchase_cash = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    # Office count - expected, shown without judgement (negative: less cash than expected); 0 until counted.
    office_difference = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    office_purchase_difference = models.DecimalField(max_digits=14, decimal_places=3, default=0)
    driver_note = models.TextField(blank=True)
    # `selectors.day_summary` as it was when sent.
    summary: Any = models.JSONField(encoder=DjangoJSONEncoder)
    submitted_at = models.DateTimeField()
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True)

    class Meta:
        ordering = ["-submitted_at", "-id"]

    def __str__(self) -> str:
        return f"{self.driver_day} · {self.get_status_display()}"


class DayReopening(OrganizationScopedModel, TimeStampedModel):
    """A sent day that a new load opened again (D-134): the send it undid, kept as it was (also an approved
    one, with who approved it), and the load. The cash counted at that send went to the office, so the day's
    next count is only what the driver holds since (`selectors.day_summary`, `handed_over`). Never changed
    once written; `created_at` is when the day was reopened."""

    closing = models.ForeignKey(DayClosing, on_delete=models.PROTECT, related_name="reopenings")
    # The send as it was: its status, its figures and the office's review.
    status = models.CharField(max_length=20, choices=DayClosingStatus.choices)
    expected_cash = MoneyField()
    # The cash the office counted at that send (D-213; the driver's own count for a send made before), and its gap.
    counted_cash = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    difference = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    # The purchase money counted at that send (D-158), handed to the office with the sales cash.
    counted_purchase_cash = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    driver_note = models.TextField(blank=True)
    summary: Any = models.JSONField(encoder=DjangoJSONEncoder)
    submitted_at = models.DateTimeField()
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=300, blank=True)
    # The load that reopened the day, by name, not by import (ARCHITECTURE §3), and who validated it.
    load = models.ForeignKey("inventory.Transfer", on_delete=models.PROTECT, related_name="+")
    reopened_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["created_at", "id"]

    def __str__(self) -> str:
        return f"{self.closing.driver_day} · {self.load.number}"


class DayClosingRevision(OrganizationScopedModel, TimeStampedModel):
    """An office correction of a driver's day (D-220): who made it, when (`created_at`), why, and the figures before
    and after (the sent figures, then the office's counts). The driver never corrects a sent day: only this does.
    Never changed once written; a correction is a new revision, numbered per closing."""

    closing = models.ForeignKey(DayClosing, on_delete=models.PROTECT, related_name="revisions")
    number = models.PositiveIntegerField()
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    reason = models.CharField(max_length=300)
    # Figure name -> value as a string (Decimals stay exact): the day's figures and the office's counts.
    before: Any = models.JSONField(encoder=DjangoJSONEncoder)
    after: Any = models.JSONField(encoder=DjangoJSONEncoder)

    class Meta:
        ordering = ["number"]
        constraints = [
            models.UniqueConstraint(fields=["closing", "number"], name="day_closing_revision_number_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.closing.driver_day} · révision {self.number}"


class SyncProblem(OrganizationScopedModel, TimeStampedModel):
    """Something a driver's phone could not send because the server refused it (P3-T07d, D-099): a sale above the
    credit limit, stock the office moved meanwhile... The phone reports it so the office sees it; it is never
    dropped silently."""

    driver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    # "sale", "expense", "loss" or "payment".
    kind = models.CharField(max_length=20)
    # What the driver would call it: the customer, the category, the product.
    label = models.CharField(max_length=150)
    reason = models.CharField(max_length=500)
    # The `client_uuid` of the refused item: reporting twice makes one problem.
    client_uuid = models.UUIDField()
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-created_at", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "client_uuid"], name="sync_problem_uuid_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.kind} · {self.label}"
