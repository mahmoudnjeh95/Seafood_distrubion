"""Treasury: banks, cheques and traites (effets) and their life (D-197, P9-T01); our accounts (Caisse, bank
accounts, each driver's cash) and their movements (D-219, P9-T05).

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
    # The SWIFT code (8 or 11 characters) and the branch's address, as the bank's documents show them.
    swift = models.CharField(max_length=11, blank=True)
    address = models.CharField(max_length=255, blank=True)
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


class Deposit(OrganizationScopedModel, TimeStampedModel):
    """A remise en banque (bordereau, D-216): received effets handed to one of our banks on one day, to be cashed.

    Numbered "RB-2026-0001" per organization and year. Never edited: an effet taken back from the bank
    ("Retirer") stays listed on its bordereau with its own history.
    """

    number = models.CharField(max_length=20)
    # The bank we hand the effets to (T05 replaces it with our bank account).
    bank = models.ForeignKey(Bank, on_delete=models.PROTECT, related_name="deposits")
    # Our bank account the effets were handed to (D-219); empty for a bordereau written before.
    account = models.ForeignKey(
        "TreasuryAccount", null=True, blank=True, on_delete=models.PROTECT, related_name="deposits"
    )
    deposited_on = models.DateField()
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["-deposited_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="treasury_deposit_number_unique"),
        ]

    def __str__(self) -> str:
        return self.number


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
    # The last remise en banque that took it (D-216); kept when it comes back to the portfolio.
    deposit = models.ForeignKey(Deposit, null=True, blank=True, on_delete=models.PROTECT, related_name="instruments")
    # An issued effet: our bank account it will be debited from (D-219); empty: the account of its bank.
    account = models.ForeignKey(
        "TreasuryAccount", null=True, blank=True, on_delete=models.PROTECT, related_name="issued_instruments"
    )
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


class AccountKind(models.TextChoices):
    CASH = "cash", _("Caisse")
    BANK = "bank", _("Compte bancaire")
    # The cash a driver holds on the road, one per driver, made when first needed.
    DRIVER = "driver", _("Caisse chauffeur")


class CashType(models.TextChoices):
    # The main cash box, and the others (a secondary Caisse, e.g. at the port).
    PRINCIPAL = "principal", _("Principale")
    SECONDARY = "secondary", _("Secondaire")


class TreasuryAccount(OrganizationScopedModel, TimeStampedModel):
    """Where our money is: a Caisse, a bank account, a driver's cash (D-219).

    Its balance is `opening_balance` plus its movements from `opening_on` on (all of them when it is empty): the
    movements dated before the day the office counted the opening are kept, never counted twice.
    """

    kind = models.CharField(max_length=10, choices=AccountKind.choices)
    name = models.CharField(max_length=100)
    # A bank account: its bank and its RIB (20 digits).
    bank = models.ForeignKey(Bank, null=True, blank=True, on_delete=models.PROTECT, related_name="accounts")
    rib = models.CharField(max_length=20, blank=True)
    # A bank account's IBAN, as the bank writes it (spaces are dropped when saved).
    iban = models.CharField(max_length=40, blank=True)
    # A Caisse: the main one or a secondary one.
    cash_type = models.CharField(max_length=10, choices=CashType.choices, blank=True)
    # A driver's cash: whose.
    driver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    # May be below zero (an overdraft).
    opening_balance = MoneyField(default=0)
    opening_on = models.DateField(null=True, blank=True)
    # The account of its kind money goes to when nobody chose one (the Caisse, the main bank account).
    is_default = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "kind", "name", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["organization", "kind"],
                condition=models.Q(is_default=True),
                name="treasury_account_one_default_per_kind",
            ),
            models.UniqueConstraint(
                fields=["organization", "driver"],
                condition=models.Q(driver__isnull=False),
                name="treasury_account_one_per_driver",
            ),
            models.CheckConstraint(
                condition=models.Q(kind="driver", driver__isnull=False)
                | (~models.Q(kind="driver") & models.Q(driver__isnull=True)),
                name="treasury_account_driver_matches_kind",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class MovementKind(models.TextChoices):
    CUSTOMER_PAYMENT = "customer_payment", _("Règlement client")
    SUPPLIER_PAYMENT = "supplier_payment", _("Règlement fournisseur")
    EFFET_CASHED = "effet_cashed", _("Effet encaissé")
    EFFET_UNPAID = "effet_unpaid", _("Effet impayé")
    EFFET_DEBITED = "effet_debited", _("Effet débité")
    TRANSFER = "transfer", _("Mouvement entre comptes")
    COUNT_GAP = "count_gap", _("Écart de caisse")
    # Written by the sales, the expenses, the payroll, the partners and the driver's day (P9-T05b).
    SALE_CASH = "sale_cash", _("Vente au comptant")
    DRIVER_HANDOVER = "driver_handover", _("Remise du chauffeur")
    DRIVER_FUND = "driver_fund", _("Fonds remis au chauffeur")
    EXPENSE = "expense", _("Dépense")
    SALARY = "salary", _("Salaire")
    PARTNER_SETTLEMENT = "partner_settlement", _("Règlement associé")
    FIELD_PURCHASE = "field_purchase", _("Achat au port")


class TreasuryMovement(OrganizationScopedModel):
    """Money in (+) or out (−) of one account on one day. Append-only: a mistake is undone by a new movement of
    the opposite sign (`role` "void"), never edited nor deleted.

    `source` and `source_id` name the record that wrote it ("sales.payment_line", 42), by name, not by foreign key
    (ARCHITECTURE §3); with `role` they are unique, so writing a record's movements again (the backfill) never
    counts them twice.
    """

    account = models.ForeignKey(TreasuryAccount, on_delete=models.PROTECT, related_name="movements")
    day = models.DateField()
    amount = MoneyField()
    kind = models.CharField(max_length=30, choices=MovementKind.choices)
    # What the list says: "RG-0042 · Restaurant La Sirène".
    label = models.CharField(max_length=255)
    # The document's number (RG-0042, RB-2026-0003...).
    reference = models.CharField(max_length=50, blank=True)
    source = models.CharField(max_length=40, blank=True)
    source_id = models.PositiveBigIntegerField(null=True, blank=True)
    role = models.CharField(max_length=20, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["day", "id"]
        constraints = [
            models.CheckConstraint(condition=~models.Q(amount=0), name="treasury_movement_amount_not_zero"),
            models.UniqueConstraint(
                fields=["organization", "source", "source_id", "role"],
                condition=~models.Q(source=""),
                name="treasury_movement_source_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["organization", "account", "day"], name="treasury_movement_day_idx"),
            models.Index(fields=["organization", "source", "source_id"], name="treasury_movement_source_idx"),
        ]

    def __str__(self) -> str:
        return f"{self.account} · {self.day} · {self.amount}"


class TransferKind(models.TextChoices):
    # Cash (a Caisse or a driver's) to a bank account.
    CASH_DEPOSIT = "cash_deposit", _("Versement espèces")
    # A bank account to a Caisse.
    WITHDRAWAL = "withdrawal", _("Retrait")
    # Any other pair: bank to bank, Caisse to Caisse, Caisse to a driver.
    TRANSFER = "transfer", _("Virement entre comptes")


class AccountTransfer(OrganizationScopedModel, TimeStampedModel):
    """Money moved from one of our accounts to another, "MT-2026-0001": two movements. Its kind follows from the
    two accounts. Never edited: annulé (reason) writes the two opposite movements."""

    number = models.CharField(max_length=20)
    kind = models.CharField(max_length=20, choices=TransferKind.choices)
    from_account = models.ForeignKey(TreasuryAccount, on_delete=models.PROTECT, related_name="transfers_out")
    to_account = models.ForeignKey(TreasuryAccount, on_delete=models.PROTECT, related_name="transfers_in")
    amount = MoneyField()
    transferred_on = models.DateField()
    # The bank's slip number.
    reference = models.CharField(max_length=50, blank=True)
    notes = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    void_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        ordering = ["-transferred_on", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "number"], name="treasury_transfer_number_unique"),
            models.CheckConstraint(condition=models.Q(amount__gt=0), name="treasury_transfer_amount_positive"),
            models.CheckConstraint(
                condition=~models.Q(from_account=models.F("to_account")), name="treasury_transfer_two_accounts"
            ),
        ]

    def __str__(self) -> str:
        return self.number


class CashCount(OrganizationScopedModel):
    """An arrêté de caisse: the cash counted in a Caisse (or a driver's cash) at the end of a day, against what the
    movements say. A gap is written as a movement "Écart de caisse" with its reason, so the balance is what was
    counted. Never changed."""

    account = models.ForeignKey(TreasuryAccount, on_delete=models.PROTECT, related_name="counts")
    counted_on = models.DateField()
    expected = MoneyField()
    counted = MoneyField()
    # Counted − expected: below zero, cash is missing.
    gap = MoneyField()
    reason = models.CharField(max_length=255, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-counted_on", "-id"]

    def __str__(self) -> str:
        return f"{self.account} · {self.counted_on}"
