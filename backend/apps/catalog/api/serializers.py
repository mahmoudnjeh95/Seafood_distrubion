from decimal import Decimal
from typing import Any

from django.db.models import QuerySet
from django.urls import reverse
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.catalog.models import Category, Illustration, PriceList, PriceListItem, Product, ProductPrice
from apps.core.models import Organization


def temperature_field() -> serializers.DecimalField:
    """A storage temperature in °C, one decimal; empty means no limit on that side."""
    return serializers.DecimalField(
        max_digits=4,
        decimal_places=1,
        min_value=Decimal("-60"),
        max_value=Decimal("60"),
        required=False,
        allow_null=True,
        default=None,
    )


class CategorySerializer(serializers.ModelSerializer[Category]):
    class Meta:
        model = Category
        fields = ("id", "name")
        read_only_fields = ("id",)


class CategoryRefSerializer(serializers.ModelSerializer[Category]):
    class Meta:
        model = Category
        fields = ("id", "name")
        read_only_fields = fields


class ProductSerializer(serializers.ModelSerializer[Product]):
    """A product as the screens show it, with the sale price in force now."""

    category = CategoryRefSerializer(read_only=True)
    base_unit = serializers.CharField(source="base_unit.symbol", read_only=True)
    photo_url = serializers.SerializerMethodField()
    # Null only for a product created outside the API without a price.
    current_price = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, allow_null=True)
    current_price_from = serializers.DateTimeField(read_only=True, allow_null=True)
    min_price = serializers.DecimalField(max_digits=14, decimal_places=3, read_only=True, allow_null=True)
    # The product's own VAT rate in percent (0 = exempt); null = the finance settings' rate (D-056).
    vat_rate = serializers.DecimalField(max_digits=5, decimal_places=2, read_only=True, allow_null=True)

    class Meta:
        model = Product
        fields = (
            "id",
            "reference",
            "name",
            "name_ar",
            "category",
            "base_unit",
            "min_stock",
            "storage_temp_min",
            "storage_temp_max",
            "illustration",
            "photo_url",
            "is_active",
            "current_price",
            "current_price_from",
            "min_price",
            "vat_rate",
            "updated_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_photo_url(self, product: Product) -> str | None:
        if not product.photo.name:
            return None
        # The file name changes with every upload, so the address can be cached for good.
        version = product.photo.name.rsplit("/", 1)[-1].split(".", 1)[0]
        return f"{reverse('product-photo', args=[product.pk])}?v={version}"


@extend_schema_field(OpenApiTypes.INT)
class OrganizationCategoryField(serializers.PrimaryKeyRelatedField[Category]):
    """A category id, looked up only in the organization of the logged-in user."""

    def get_queryset(self) -> QuerySet[Category]:
        organization: Organization = self.context["organization"]
        return Category.objects.for_organization(organization)


class ProductUpdateSerializer(serializers.Serializer[Any]):
    # Empty on creation: the server gives the next product number (D-223). Left out of a change: kept as it is.
    reference = serializers.CharField(max_length=30, required=False, allow_blank=True, default="")
    name = serializers.CharField(max_length=150)
    name_ar = serializers.CharField(max_length=150, required=False, allow_blank=True, default="")
    category = OrganizationCategoryField()
    min_stock = serializers.DecimalField(
        max_digits=12, decimal_places=3, min_value=Decimal("0"), required=False, default=Decimal("0")
    )
    storage_temp_min = temperature_field()
    storage_temp_max = temperature_field()
    illustration = serializers.ChoiceField(choices=Illustration.choices, required=False, default=Illustration.FISH)
    # Percent; 0 = exempt; null = the finance settings' rate (D-056). Left out of a change: kept as it is.
    vat_rate = serializers.DecimalField(
        max_digits=5,
        decimal_places=2,
        min_value=Decimal("0"),
        max_value=Decimal("100"),
        required=False,
        allow_null=True,
        default=None,
    )


class ProductCreateSerializer(ProductUpdateSerializer):
    sale_price = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class ProductFilterSerializer(serializers.Serializer[Any]):
    search = serializers.CharField(required=False, allow_blank=True, default="", max_length=100)
    category = serializers.IntegerField(required=False, min_value=1)
    status = serializers.ChoiceField(
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")], required=False, default="active"
    )


class ProductPriceSerializer(serializers.ModelSerializer[ProductPrice]):
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = ProductPrice
        fields = ("id", "price", "valid_from", "created_at", "created_by")
        read_only_fields = fields

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_created_by(self, product_price: ProductPrice) -> str | None:
        return str(product_price.created_by) if product_price.created_by else None


class SetPriceSerializer(serializers.Serializer[Any]):
    price = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))
    # Empty means "from now". A later moment plans a price; the past is refused.
    valid_from = serializers.DateTimeField(required=False, allow_null=True, default=None)


@extend_schema_field(OpenApiTypes.BINARY)
class UploadedFileField(serializers.FileField):
    """A file sent in a multipart form: a Blob in the generated client, not a URL."""


class PhotoUploadSerializer(serializers.Serializer[Any]):
    photo = UploadedFileField()


class PriceBoardPriceSerializer(serializers.Serializer[Any]):
    """A price that started today: who set it and when."""

    price = serializers.DecimalField(max_digits=14, decimal_places=3)
    valid_from = serializers.DateTimeField()
    created_by = serializers.CharField(allow_null=True)


class PriceBoardRowSerializer(serializers.Serializer[Any]):
    product = ProductSerializer()
    price = serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True)
    price_from = serializers.DateTimeField(allow_null=True)
    min_price = serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True)
    stock = serializers.DecimalField(max_digits=12, decimal_places=3)
    last_cost = serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True)
    average_cost = serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True)
    margin = serializers.DecimalField(max_digits=14, decimal_places=3, allow_null=True)
    margin_percent = serializers.DecimalField(max_digits=6, decimal_places=1, allow_null=True)
    below_minimum = serializers.BooleanField()
    todays_prices = PriceBoardPriceSerializer(many=True)


class PriceBoardSerializer(serializers.Serializer[Any]):
    rows = PriceBoardRowSerializer(many=True)
    # Product ids whose price now is below their minimum price (a warning, never a block).
    below_minimum = serializers.ListField(child=serializers.IntegerField())


class PriceChangeSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    price = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"), required=False)
    # Left out keeps the minimum price; null removes it.
    min_price = serializers.DecimalField(
        max_digits=14, decimal_places=3, min_value=Decimal("0.001"), required=False, allow_null=True
    )


class SetPricesSerializer(serializers.Serializer[Any]):
    items = PriceChangeSerializer(many=True, allow_empty=False, max_length=500)  # type: ignore[call-arg]


class PriceListItemSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    price = serializers.DecimalField(max_digits=14, decimal_places=3, min_value=Decimal("0.001"))


class PriceListItemOutSerializer(serializers.ModelSerializer[PriceListItem]):
    class Meta:
        model = PriceListItem
        fields = ("product", "price")
        read_only_fields = fields


class PriceListSerializer(serializers.ModelSerializer[PriceList]):
    customer = serializers.IntegerField(source="customer_id", read_only=True, allow_null=True)
    items = PriceListItemOutSerializer(many=True, read_only=True)

    class Meta:
        model = PriceList
        fields = ("id", "name", "customer", "is_active", "items", "updated_at")
        read_only_fields = fields


class PriceListWriteSerializer(serializers.Serializer[Any]):
    name = serializers.CharField(max_length=100)
    customer = serializers.IntegerField(min_value=1, required=False, allow_null=True, default=None)
    is_active = serializers.BooleanField(required=False, default=True)
    items = PriceListItemSerializer(many=True, required=False, default=list, max_length=500)  # type: ignore[call-arg]


class PriceListFilterSerializer(serializers.Serializer[Any]):
    customer = serializers.IntegerField(required=False, min_value=1)
    status = serializers.ChoiceField(
        choices=[("active", "active"), ("archived", "archived"), ("all", "all")], required=False, default="active"
    )
