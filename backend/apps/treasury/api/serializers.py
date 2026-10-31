"""Banks and effets (D-197)."""

from typing import Any

from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.treasury.models import Bank, Deposit, Instrument, InstrumentDirection, InstrumentKind, InstrumentStatus


class BankSerializer(serializers.ModelSerializer[Bank]):
    class Meta:
        model = Bank
        fields: tuple[str, ...] = ("id", "code", "name", "is_active")
        read_only_fields: tuple[str, ...] = fields


class BankWriteSerializer(serializers.Serializer[Any]):
    code = serializers.CharField(allow_blank=True, max_length=40)
    name = serializers.CharField(allow_blank=True, max_length=200)
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
    bank = serializers.IntegerField(required=False, allow_null=True, min_value=1, default=None)
    deposited_on = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=255)


class DepositSerializer(serializers.ModelSerializer[Deposit]):
    bank = BankSerializer(read_only=True)
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
        user = deposit.created_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or str(user.username)
