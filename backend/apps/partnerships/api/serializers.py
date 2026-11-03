from typing import Any

from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.partnerships import selectors
from apps.partnerships.models import (
    CapitalEntry,
    CapitalEntryKind,
    LotPartnership,
    PartnershipStatus,
    SettlementPaymentMethod,
)


def person_name(user: Any) -> str:
    if user is None:
        return ""
    return f"{user.first_name} {user.last_name}".strip() or user.username


class PartnershipBatchSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    product_id = serializers.IntegerField(read_only=True)
    product_name = serializers.CharField(read_only=True, source="product.name")
    received_on = serializers.DateField(read_only=True)
    unit_cost = serializers.DecimalField(read_only=True, max_digits=14, decimal_places=3)


class PartnershipPartnerSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    reference = serializers.CharField(read_only=True)
    name = serializers.CharField(read_only=True)


class CapitalEntrySerializer(serializers.ModelSerializer[CapitalEntry]):
    kind = serializers.ChoiceField(choices=CapitalEntryKind.choices, read_only=True)
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = CapitalEntry
        # `amount` is signed: + money put in, − money taken out (a loss share, a return, an advance).
        fields = (
            "id",
            "kind",
            "amount",
            "entry_date",
            "note",
            "method",
            "reference",
            "lot_result_id",
            "created_at",
            "created_by_name",
        )
        read_only_fields = fields

    def get_created_by_name(self, entry: CapitalEntry) -> str:
        return person_name(entry.created_by)


class LotPartnershipSerializer(serializers.ModelSerializer[LotPartnership]):
    batch = PartnershipBatchSerializer(read_only=True)
    partner = PartnershipPartnerSerializer(read_only=True)
    status = serializers.ChoiceField(choices=PartnershipStatus.choices, read_only=True)
    # The partner's capital in this lot now (the sum of their ledger).
    capital = serializers.SerializerMethodField()
    created_by_name = serializers.SerializerMethodField()

    class Meta:
        model = LotPartnership
        fields: tuple[str, ...] = (
            "id",
            "batch",
            "partner",
            "owner_capital",
            "partner_capital",
            "profit_rate",
            "loss_rate",
            "status",
            "terms_pending",
            "notes",
            "capital",
            "created_at",
            "created_by_name",
            "cancelled_at",
            "cancel_reason",
        )
        read_only_fields: tuple[str, ...] = fields

    @extend_schema_field(serializers.DecimalField(max_digits=14, decimal_places=3))
    def get_capital(self, partnership: LotPartnership) -> str:
        return str(selectors.capital_balance(partnership))

    def get_created_by_name(self, partnership: LotPartnership) -> str:
        return person_name(partnership.created_by)


class LotPartnershipDetailSerializer(LotPartnershipSerializer):
    capital_entries = serializers.SerializerMethodField()
    # Whether the lot has a confirmed sale: its terms are then fixed.
    has_sold = serializers.SerializerMethodField()

    class Meta(LotPartnershipSerializer.Meta):
        fields = (*LotPartnershipSerializer.Meta.fields, "capital_entries", "has_sold")
        read_only_fields = fields

    @extend_schema_field(CapitalEntrySerializer(many=True))
    def get_capital_entries(self, partnership: LotPartnership) -> list[dict[str, Any]]:
        return list(CapitalEntrySerializer(selectors.capital_entries_of(partnership), many=True).data)

    def get_has_sold(self, partnership: LotPartnership) -> bool:
        return bool(self.context.get("has_sold", False))


class LotPartnershipFilterSerializer(serializers.Serializer[Any]):
    # Empty: every partnership but the cancelled ones.
    status = serializers.ChoiceField(choices=PartnershipStatus.choices, required=False)
    partner = serializers.IntegerField(min_value=1, required=False)
    batch = serializers.IntegerField(min_value=1, required=False)
    search = serializers.CharField(required=False, allow_blank=True, default="")


class LotPartnershipWriteSerializer(serializers.Serializer[Any]):
    batch = serializers.IntegerField(min_value=1)
    partner = serializers.IntegerField(min_value=1)
    # Amounts in DT and rates in percent, as strings ("5000.000", "40"), checked by the service.
    owner_capital = serializers.CharField(allow_blank=True)
    partner_capital = serializers.CharField(allow_blank=True)
    profit_rate = serializers.CharField(allow_blank=True)
    loss_rate = serializers.CharField(allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class LotPartnershipUpdateSerializer(serializers.Serializer[Any]):
    partner = serializers.IntegerField(min_value=1, required=False)
    owner_capital = serializers.CharField(required=False, allow_blank=True)
    partner_capital = serializers.CharField(required=False, allow_blank=True)
    profit_rate = serializers.CharField(required=False, allow_blank=True)
    loss_rate = serializers.CharField(required=False, allow_blank=True)
    notes = serializers.CharField(required=False, allow_blank=True)


class LotPartnershipCancelSerializer(serializers.Serializer[Any]):
    reason = serializers.CharField(max_length=300, allow_blank=True)


class LotPartnershipAdvanceSerializer(serializers.Serializer[Any]):
    # The amount in DT as a string ("500.000"), checked by the service.
    amount = serializers.CharField(allow_blank=True)
    method = serializers.ChoiceField(choices=SettlementPaymentMethod.choices)
    reference = serializers.CharField(max_length=50, required=False, allow_blank=True, default="")
    paid_on = serializers.DateField(required=False)
    note = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
