"""Banks and effets (D-197)."""

from typing import Any

from django.utils.translation import gettext as _
from rest_framework import serializers

from apps.treasury.models import Bank, Instrument, InstrumentDirection, InstrumentKind, InstrumentStatus


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


class InstrumentSerializer(serializers.ModelSerializer[Instrument]):
    direction = serializers.ChoiceField(choices=InstrumentDirection.choices, read_only=True)
    kind = serializers.ChoiceField(choices=InstrumentKind.choices, read_only=True)
    status = serializers.ChoiceField(choices=InstrumentStatus.choices, read_only=True)
    bank = BankSerializer(read_only=True, allow_null=True)
    customer = PartyRefSerializer(read_only=True, allow_null=True)
    supplier = PartyRefSerializer(read_only=True, allow_null=True)

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

    def validate_status(self, value: str) -> list[str]:
        statuses = [item.strip() for item in value.split(",") if item.strip()]
        unknown = [item for item in statuses if item not in InstrumentStatus.values]
        if unknown:
            raise serializers.ValidationError(_("Statut inconnu : %(statuses)s.") % {"statuses": ", ".join(unknown)})
        return statuses
