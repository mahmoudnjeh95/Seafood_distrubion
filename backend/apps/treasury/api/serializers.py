"""Banks and effets (D-197); our accounts, their movements, transfers and arrêtés de caisse (D-219)."""

from typing import Any

from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.core.models import User
from apps.treasury.models import (
    AccountKind,
    AccountTransfer,
    Bank,
    CashCount,
    CashType,
    Deposit,
    Instrument,
    InstrumentDirection,
    InstrumentKind,
    InstrumentStatus,
    MovementKind,
    TransferKind,
    TreasuryAccount,
)


def _person(user: User | None) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or str(user.username)


class BankSerializer(serializers.ModelSerializer[Bank]):
    class Meta:
        model = Bank
        fields: tuple[str, ...] = ("id", "code", "name", "swift", "address", "is_active")
        read_only_fields: tuple[str, ...] = fields


class BankWriteSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(allow_blank=True, max_length=40)
    name = serializers.CharField(allow_blank=True, max_length=200)
    # The SWIFT code (8 or 11 characters) and the branch address; both may be left blank.
    swift = serializers.CharField(required=False, allow_blank=True, default="", max_length=20)
    address = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)
    # Only on a change: off takes the bank off the lists.
    is_active = serializers.BooleanField(required=False, default=True)


class BankFilterSerializer(serializers.Serializer[Any]):
    # Off: the banks taken off the lists too (Paramètres › Banques).
    active_only = serializers.BooleanField(required=False, default=True)


class PartyRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class DepositRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    deposited_on = serializers.DateField(read_only=True)


class InstrumentSerializer(serializers.ModelSerializer[Instrument]):
    direction = serializers.ChoiceField(choices=InstrumentDirection.choices, read_only=True)
    kind = serializers.ChoiceField(choices=InstrumentKind.choices, read_only=True)
    status = serializers.ChoiceField(choices=InstrumentStatus.choices, read_only=True)
    bank = BankSerializer(read_only=True, allow_null=True)
    customer = PartyRefSerializer(read_only=True, allow_null=True)
    supplier = PartyRefSerializer(read_only=True, allow_null=True)
    # The last bordereau that took it to the bank.
    deposit = DepositRefSerializer(read_only=True, allow_null=True)

    class Meta:
        model = Instrument
        fields: tuple[str, ...] = (
            "id",
            "direction",
            "kind",
            "number",
            "bank",
            "drawer",
            "amount",
            "issued_on",
            "due_on",
            "status",
            "customer",
            "supplier",
            "source_number",
            "notes",
            "deposit",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields


class PartyDocumentRowSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(source="party_id", read_only=True)
    deliveries = serializers.IntegerField(read_only=True)
    invoices = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class PartyDocumentsSerializer(serializers.Serializer[Any]):
    """Per customer: its BL, invoices and net to pay. Per supplier: its BR, invoices and invoiced total (D-211)."""

    customers = PartyDocumentRowSerializer(many=True, read_only=True)
    suppliers = PartyDocumentRowSerializer(many=True, read_only=True)


class InstrumentFilterSerializer(serializers.Serializer[Any]):
    direction = serializers.ChoiceField(choices=InstrumentDirection.choices, required=False)
    kind = serializers.ChoiceField(choices=InstrumentKind.choices, required=False)
    # One or more statuses, comma separated ("portfolio,deposited").
    status = serializers.CharField(required=False, default="", allow_blank=True, max_length=200)
    customer = serializers.IntegerField(required=False, min_value=1)
    supplier = serializers.IntegerField(required=False, min_value=1)
    due_from = serializers.DateField(required=False)
    due_to = serializers.DateField(required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)
    bank = serializers.IntegerField(required=False, min_value=1)
    deposit = serializers.IntegerField(required=False, min_value=1)

    def validate_status(self, value: str) -> list[str]:
        statuses = [item.strip() for item in value.split(",") if item.strip()]
        unknown = [item for item in statuses if item not in InstrumentStatus.values]
        if unknown:
            raise serializers.ValidationError(_("Statut inconnu : %(statuses)s.") % {"statuses": ", ".join(unknown)})
        return statuses


class StatusTotalSerializer(serializers.Serializer[Any]):
    count = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class InstrumentTotalsSerializer(serializers.Serializer[Any]):
    """The count and amount of the filtered effets, by status, and those late (échéance passed, not done)."""

    count = serializers.IntegerField(read_only=True)
    total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    by_status = serializers.DictField(child=StatusTotalSerializer(), read_only=True)
    overdue_count = serializers.IntegerField(read_only=True)
    overdue_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class InstrumentBatchSerializer(serializers.Serializer[Any]):
    """Several effets moved at once, on one day."""

    instruments = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True, max_length=200)
    day = serializers.DateField(required=False, allow_null=True, default=None)
    note = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class DepositWriteSerializer(serializers.Serializer[Any]):
    instruments = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True, max_length=200)
    # Our bank account (D-219), which gives the bank; or only the bank (its account, else the main one).
    account = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    bank = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    deposited_on = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class AccountRefSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    kind = serializers.ChoiceField(choices=AccountKind.choices, read_only=True)
    name = serializers.CharField(read_only=True)


class DepositSerializer(serializers.ModelSerializer[Deposit]):
    bank = BankSerializer(read_only=True)
    account = AccountRefSerializer(read_only=True, allow_null=True)
    effets_count = serializers.IntegerField(read_only=True)
    effets_total = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, allow_null=True)
    instruments = InstrumentSerializer(many=True, read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = Deposit
        fields: tuple[str, ...] = (
            "id",
            "number",
            "bank",
            "account",
            "deposited_on",
            "notes",
            "effets_count",
            "effets_total",
            "instruments",
            "created_by",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_created_by(self, deposit: Deposit) -> str:
        return _person(deposit.created_by)


class TreasuryAccountSerializer(serializers.ModelSerializer[TreasuryAccount]):
    kind = serializers.ChoiceField(choices=AccountKind.choices, read_only=True)
    bank = BankSerializer(read_only=True, allow_null=True)
    # A driver's cash: the driver's name.
    driver = serializers.SerializerMethodField()
    # At the end of today (or of the day asked).
    balance = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)

    class Meta:
        model = TreasuryAccount
        fields: tuple[str, ...] = (
            "id",
            "kind",
            "name",
            "bank",
            "rib",
            "iban",
            "cash_type",
            "driver",
            "opening_balance",
            "opening_on",
            "is_default",
            "is_active",
            "balance",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_driver(self, account: TreasuryAccount) -> str:
        return _person(account.driver)


class TreasuryAccountWriteSerializer(serializers.Serializer[Any]):
    # Only on a new account: a Caisse or a bank account (a driver's cash is made by itself).
    kind = serializers.ChoiceField(choices=AccountKind.choices, required=False, default=AccountKind.CASH)
    name = serializers.CharField(allow_blank=True, max_length=200)
    bank = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    rib = serializers.CharField(required=False, allow_blank=True, default="", max_length=40)
    # A bank account's IBAN (spaces allowed), and a Caisse's type (principale or secondaire): checked by the service.
    iban = serializers.CharField(required=False, allow_blank=True, default="", max_length=60)
    cash_type = serializers.ChoiceField(choices=CashType.choices, required=False, allow_blank=True, default="")
    # A string ("1250.000", "-300.000" for an overdraft), checked by the service.
    opening_balance = serializers.CharField(required=False, allow_blank=True, default="0", max_length=30)
    opening_on = serializers.DateField(required=False, allow_null=True, default=None)
    # Only on a change.
    is_active = serializers.BooleanField(required=False, default=True)
    is_default = serializers.BooleanField(required=False, default=False)


class AccountFilterSerializer(serializers.Serializer[Any]):
    active_only = serializers.BooleanField(required=False, default=False)
    # The balances at the end of this day (today when left out).
    on = serializers.DateField(required=False)


class MovementRowSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(source="movement.id", read_only=True)
    day = serializers.DateField(source="movement.day", read_only=True)
    # + in, − out.
    amount = serializers.DecimalField(source="movement.amount", max_digits=14, decimal_places=3, read_only=True)
    kind = serializers.ChoiceField(source="movement.kind", choices=MovementKind.choices, read_only=True)
    # What the list says ("RG-0042 · Restaurant La Sirène"); the movement's label.
    description = serializers.CharField(source="movement.label", read_only=True)
    reference = serializers.CharField(source="movement.reference", read_only=True)
    created_by = serializers.SerializerMethodField()
    # The account's balance just after it.
    balance = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)

    def get_created_by(self, row: Any) -> str:
        return _person(row.movement.created_by)


class AccountStatementSerializer(serializers.Serializer[Any]):
    account = TreasuryAccountSerializer(read_only=True)
    date_from = serializers.DateField(read_only=True, allow_null=True)
    date_to = serializers.DateField(read_only=True, allow_null=True)
    opening = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    total_in = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    total_out = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    closing = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    rows = MovementRowSerializer(many=True, read_only=True)


class StatementFilterSerializer(serializers.Serializer[Any]):
    date_from = serializers.DateField(required=False)
    date_to = serializers.DateField(required=False)
    kind = serializers.ChoiceField(choices=MovementKind.choices, required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


class AccountTransferSerializer(serializers.ModelSerializer[AccountTransfer]):
    kind = serializers.ChoiceField(choices=TransferKind.choices, read_only=True)
    from_account = AccountRefSerializer(read_only=True)
    to_account = AccountRefSerializer(read_only=True)
    created_by = serializers.SerializerMethodField()
    voided_by = serializers.SerializerMethodField()
    is_voided = serializers.SerializerMethodField()

    class Meta:
        model = AccountTransfer
        fields: tuple[str, ...] = (
            "id",
            "number",
            "kind",
            "from_account",
            "to_account",
            "amount",
            "transferred_on",
            "reference",
            "notes",
            "created_by",
            "created_at",
            "is_voided",
            "voided_at",
            "voided_by",
            "void_reason",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_created_by(self, transfer: AccountTransfer) -> str:
        return _person(transfer.created_by)

    def get_voided_by(self, transfer: AccountTransfer) -> str:
        return _person(transfer.voided_by)

    def get_is_voided(self, transfer: AccountTransfer) -> bool:
        return transfer.voided_at is not None


class AccountTransferWriteSerializer(serializers.Serializer[Any]):
    from_account = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    to_account = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    # A string ("1500.000"), checked by the service.
    amount = serializers.CharField(allow_blank=True, max_length=30)
    transferred_on = serializers.DateField(required=False, allow_null=True, default=None)
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class TransferFilterSerializer(serializers.Serializer[Any]):
    account = serializers.IntegerField(required=False, min_value=1)


class VoidTransferSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(allow_blank=True, max_length=255)


class CashCountSerializer(serializers.ModelSerializer[CashCount]):
    account = AccountRefSerializer(read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = CashCount
        fields: tuple[str, ...] = (
            "id",
            "account",
            "counted_on",
            "expected",
            "counted",
            "gap",
            "reason",
            "created_by",
            "created_at",
        )
        read_only_fields: tuple[str, ...] = fields

    def get_created_by(self, count: CashCount) -> str:
        return _person(count.created_by)


class CashCountWriteSerializer(serializers.Serializer[Any]):
    account = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    counted_on = serializers.DateField(required=False, allow_null=True, default=None)
    # A string ("845.500"), checked by the service.
    counted = serializers.CharField(allow_blank=True, max_length=30)
    # Needed when the count differs from what the movements say.
    reason = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class MovementOfFilterSerializer(serializers.Serializer[Any]):
    # Where the money was written from: "sales.payment_line", "sales.sale", "expenses.expense"...
    from_source = serializers.CharField(max_length=40)
    # The records' ids, comma separated (at most 200).
    source_ids = serializers.CharField(max_length=2000)


class MovementOfSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    source_id = serializers.IntegerField(read_only=True)
    day = serializers.DateField(read_only=True)
    amount = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)
    kind = serializers.ChoiceField(choices=MovementKind.choices, read_only=True)
    account = AccountRefSerializer(read_only=True)
