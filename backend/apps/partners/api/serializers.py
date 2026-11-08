from decimal import Decimal
from typing import Any

from rest_framework import serializers

from apps.partners.models import (
    Customer,
    CustomerContact,
    CustomerKind,
    CustomerType,
    IdentificationType,
    Supplier,
    SupplierContact,
)


class SupplierContactSerializer(serializers.ModelSerializer[SupplierContact]):
    class Meta:
        model = SupplierContact
        fields = ("name", "role", "phone", "email")
        extra_kwargs = {
            "role": {"required": False, "default": ""},
            "phone": {"required": False, "default": ""},
            "email": {"required": False, "default": ""},
        }


class SupplierSerializer(serializers.ModelSerializer[Supplier]):
    contacts = SupplierContactSerializer(many=True, read_only=True)

    class Meta:
        model = Supplier
        fields = (
            "id",
            "reference",
            "name",
            "tax_id",
            "phone",
            "email",
            "address",
            "city",
            "notes",
            "contacts",
            "is_active",
            "updated_at",
        )
        read_only_fields = fields


class SupplierWriteSerializer(serializers.Serializer[Any]):
    # Empty on creation: the server gives the next F-NNN.
    reference = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=150)
    # Tunisian "matricule fiscal": 1234567A/A/M/000 or 1234567A. Written back in that shape.
    tax_id = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    address = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    # The whole list: on a change it replaces the contacts; left out, they are kept.
    contacts = SupplierContactSerializer(many=True, required=False)


class SupplierFilterSerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    status = serializers.ChoiceField(
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")], required=False, default="active"
    )


class CustomerContactSerializer(serializers.ModelSerializer[CustomerContact]):
    class Meta:
        model = CustomerContact
        fields = ("name", "role", "phone", "email")
        extra_kwargs = {
            "role": {"required": False, "default": ""},
            "phone": {"required": False, "default": ""},
            "email": {"required": False, "default": ""},
        }


class CustomerSerializer(serializers.ModelSerializer[Customer]):
    contacts = CustomerContactSerializer(many=True, read_only=True)

    class Meta:
        model = Customer
        fields = (
            "id",
            "reference",
            "name",
            "kind",
            "id_type",
            "tax_id",
            "phone",
            "email",
            "address",
            "city",
            "notes",
            "latitude",
            "longitude",
            "credit_limit",
            "payment_terms_days",
            "withholding_subject",
            "contacts",
            "is_walk_in",
            "is_active",
            "updated_at",
        )
        read_only_fields = fields


class CustomerWriteSerializer(serializers.Serializer[Any]):
    # Empty on creation: the server gives the next C-NNN.
    reference = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=150)
    # The code of one of the organization's customer types (Paramètres › Types de clients, D-283).
    kind = serializers.CharField(max_length=20, required=False, default=CustomerKind.RESTAURANT)
    id_type = serializers.ChoiceField(
        choices=IdentificationType.choices, required=False, default=IdentificationType.TAX_ID
    )
    # The identification number for `id_type`; a matricule fiscal by default.
    tax_id = serializers.CharField(max_length=20, required=False, allow_blank=True, default="")
    phone = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    email = serializers.EmailField(required=False, allow_blank=True, default="")
    address = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
    city = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")
    notes = serializers.CharField(required=False, allow_blank=True, default="", max_length=2000)
    # DT with 3 decimals, as a string; 0 = no credit.
    credit_limit = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=0, required=False, default=Decimal("0"), coerce_to_string=True
    )
    payment_terms_days = serializers.IntegerField(min_value=0, max_value=365, required=False, default=0)
    # Withholds the retenue à la source on invoices of 1 000 DT and more (D-292).
    withholding_subject = serializers.BooleanField(required=False, default=True)
    contacts = CustomerContactSerializer(many=True, required=False)


class CustomerFilterSerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    status = serializers.ChoiceField(
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")], required=False, default="active"
    )
    kind = serializers.CharField(max_length=20, required=False)


class MyCustomerWriteSerializer(serializers.Serializer[Any]):
    """What a driver types to add a customer: a name, and a phone and a city when they know them."""

    name = serializers.CharField(max_length=150)
    phone = serializers.CharField(required=False, allow_blank=True, default="", max_length=30)
    city = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)


class CustomerChoiceSerializer(serializers.Serializer[Any]):
    """The little a driver needs to pick a customer."""

    id = serializers.IntegerField(read_only=True)
    name = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    is_walk_in = serializers.BooleanField(read_only=True)
    # Loaded for today on the driver's truck (a BL made from the load, D-174): the list then holds only these
    # clients and the walk-in customer.
    on_load = serializers.BooleanField(read_only=True, default=False)


class CustomerLocationSerializer(serializers.Serializer[Any]):
    # Both empty forget the place.
    latitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-90, max_value=90, allow_null=True)
    longitude = serializers.DecimalField(max_digits=9, decimal_places=6, min_value=-180, max_value=180, allow_null=True)


class CustomerTypeSerializer(serializers.ModelSerializer[CustomerType]):
    """One customer type (D-283), with how many customers have it: a type in use cannot be deleted."""

    customer_count = serializers.IntegerField(read_only=True)

    class Meta:
        model = CustomerType
        fields = ("id", "code", "label", "is_active", "customer_count")
        read_only_fields = fields


class CustomerTypeWriteSerializer(serializers.Serializer[Any]):
    # "label" is also a DRF field attribute; the API keeps the business word.
    label = serializers.CharField(max_length=60, required=False)  # type: ignore[assignment]
    is_active = serializers.BooleanField(required=False)
