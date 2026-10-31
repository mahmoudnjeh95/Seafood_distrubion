"""Treasury: banks, cheques and traites (effets) and their life (D-197, P9-T01).

An effet is written by the règlement that holds it (a customer payment line, later a supplier payment line) through
`services.register_instrument`; this app never reads the règlement's tables, it keeps the règlement's number.
"""

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, TimeStampedModel
from apps.core.money import MoneyField


class Bank(OrganizationScopedModel, TimeStampedModel):
    """A bank an effet is drawn on, or where we hold an account: the Tunisian banks, editable per organization."""

    # Short name printed on lists ("BIAT", "STB").
    code = models.CharField(max_length=20)
    name = models.CharField(max_length=100)
    # A bank no longer offered in the lists; effets already drawn on it keep it.
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "code", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "code"], name="treasury_bank_code_unique"),
        ]

    def __str__(self) -> str:
        return self.code


class InstrumentDirection(models.TextChoices):
    # Given to us by a customer.
    RECEIVED = "received", _("Reçu")
    # Given by us to a supplier.
    ISSUED = "issued", _("Émis")


class InstrumentKind(models.TextChoices):
    CHEQUE = "cheque", _("Chèque")
    BILL = "bill", _("Traite")


class InstrumentStatus(models.TextChoices):
    # Received effets.
    PORTFOLIO = "portfolio", _("En portefeuille")
    DEPOSITED = "deposited", _("Remis en banque")
    CASHED = "cashed", _("Encaissé")
    UNPAID = "unpaid", _("Impayé")
    RETURNED = "returned", _("Restitué")
    ENDORSED = "endorsed", _("Endossé")
    # Issued effets.
    ISSUED = "issued", _("Émis")
    DEBITED = "debited", _("Débité")
    REJECTED = "rejected", _("Rejeté")
    # Its règlement was voided before the effet moved on (both directions).
    CANCELLED = "cancelled", _("Annulé")


# Where an effet's life starts, by direction.
FIRST_STATUS = {
    InstrumentDirection.RECEIVED: InstrumentStatus.PORTFOLIO,
    InstrumentDirection.ISSUED: InstrumentStatus.ISSUED,
}


class Instrument(OrganizationScopedModel, TimeStampedModel):
    """A cheque or a traite, received from a customer or issued to a supplier, followed until the bank pays it.

    Its amount, number and dates never change once written; only `status` moves, each move kept as an
    `InstrumentEvent`. Who it comes from (or goes to) is the customer or the supplier of the règlement.
    """

    direction = models.CharField(max_length=10, choices=InstrumentDirection.choices)
    kind = models.CharField(max_length=10, choices=InstrumentKind.choices)
    number = models.CharField(max_length=50)
    # Empty only for a cheque taken over from a payment recorded before D-197 ("à compléter").
    bank = models.ForeignKey(Bank, null=True, blank=True, on_delete=models.PROTECT, related_name="instruments")
    # The person or company whose name signs it (tireur); for an issued effet, ours.
    drawer = models.CharField(max_length=150, blank=True)
    amount = MoneyField()
    # The day it was handed over (the règlement's day).
    issued_on = models.DateField()
    # The échéance: the first day it may be cashed.
    due_on = models.DateField()
    status = models.CharField(max_length=20, choices=InstrumentStatus.choices)
    customer = models.ForeignKey(
        "partners.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="instruments"
    )
    supplier = models.ForeignKey(
        "partners.Supplier", null=True, blank=True, on_delete=models.PROTECT, related_name="instruments"
    )
    # The number of the règlement holding it ("RG-0042", "RF-0012").
    source_number = models.CharField(max_length=20, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["due_on", "id"]
        constraints = [
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="treasury_instrument_amount_positive"),
            models.CheckConstraint(
                condition=(
                    models.Q(direction=InstrumentDirection.RECEIVED, supplier__isnull=True)
                    | models.Q(direction=InstrumentDirection.ISSUED, customer__isnull=True)
                ),
                name="treasury_instrument_party_matches_direction",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "status", "due_on"], name="treasury_instrument_due_idx"),
            models.Index(fields=["organization", "kind", "bank", "number"], name="treasury_instrument_number_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.get_kind_display()} {self.number}"


class InstrumentEvent(OrganizationScopedModel):
    """One move of an effet's status (its first one included). Append-only."""

    instrument = models.ForeignKey(Instrument, on_delete=models.PROTECT, related_name="events")
    # Empty for the first event (the effet was written).
    from_status = models.CharField(max_length=20, choices=InstrumentStatus.choices, blank=True)
    to_status = models.CharField(max_length=20, choices=InstrumentStatus.choices)
    # The day it happened (the bank's day for a deposit or a cashing).
    happened_on = models.DateField()
    note = models.CharField(max_length=255, blank=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["instrument", "id"]

    def __str__(self) -> str:
        return f"{self.instrument} · {self.from_status or '-'} → {self.to_status}"
