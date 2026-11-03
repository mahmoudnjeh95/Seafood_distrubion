from typing import Any

from rest_framework import serializers

from apps.sales.models import CustomerPayment, SalePaymentMethod


class RoadPaymentWriteSerializer(serializers.Serializer[Any]):
    customer = serializers.IntegerField(min_value=1)
    # In DT as a string ("120.500"), checked by the service.
    amount = serializers.CharField(allow_blank=True)
    method = serializers.ChoiceField(choices=SalePaymentMethod.choices, default=SalePaymentMethod.CASH)
    # Sent by the app that may retry: the same value never records two payments.
    client_uuid = serializers.UUIDField(required=False, allow_null=True, default=None)
    # When the driver's phone says it happened (D-133); the server checks it.
    made_at = serializers.DateTimeField(required=False, allow_null=True, default=None)
    # The driver confirmed on the phone a cash amount at or above the cash limit (D-280).
    confirm_cash_limit = serializers.BooleanField(required=False, default=False)


class CashLimitSerializer(serializers.Serializer[Any]):
    cash_limit = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True)


class RoadPaymentSerializer(serializers.ModelSerializer[CustomerPayment]):
    customer_name = serializers.CharField(source="customer.name", read_only=True)

    class Meta:
        model = CustomerPayment
        fields = ("id", "number", "customer_name", "amount", "method")
        read_only_fields = fields


class ReceiptHeaderSerializer(serializers.Serializer[Any]):
    """The seller printed at the top of the driver's receipts (D-281), from the finance settings in force."""

    name = serializers.CharField(read_only=True)
    address = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    tax_id = serializers.CharField(read_only=True)
