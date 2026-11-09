import uuid
from typing import Any

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils.translation import gettext_lazy as _

from apps.core.models import OrganizationScopedModel, OrganizationScopedQuerySet, TimeStampedModel
from apps.core.money import MoneyField, QuantityField

KILOGRAM = "kg"


class Unit(TimeStampedModel):
    """A unit of measure. Shared by every organization, like a currency code (D-029).

    Only the kilogram exists: everything is sold by kg (Q10) and quantities are stored in kg. The table
    keeps the door open for box or piece units that other distributors may need (Q17).
    """

    code = models.SlugField(max_length=20, unique=True)
    name = models.CharField(max_length=50)
    symbol = models.CharField(max_length=10)

    class Meta:
        ordering = ["code"]

    def __str__(self) -> str:
        return self.symbol


class Category(OrganizationScopedModel, TimeStampedModel):
    """A family of products: Poissons, Crustacés, Céphalopodes..."""

    name = models.CharField(max_length=100)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"
        constraints = [
            models.UniqueConstraint("organization", Lower("name"), name="category_name_unique_per_organization"),
        ]

    def __str__(self) -> str:
        return self.name


class Illustration(models.TextChoices):
    """The prototype's drawings, shown on a product card until it has a real photo."""

    SHRIMP = "shrimp", _("Crevette")
    PEELED = "peeled", _("Crevette décortiquée")
    FISH = "fish", _("Poisson")
    BASS = "bass", _("Loup")
    SQUID = "squid", _("Calamar")
    OCTOPUS = "octopus", _("Poulpe")
    MUSSEL = "mussel", _("Coquillage")
    MIX = "mix", _("Mélange")


def product_photo_path(product: "Product", filename: str) -> str:
    # A new random name on every upload: the old URL never shows the new photo from a cache.
    return f"products/{product.organization_id}/{uuid.uuid4().hex}.webp"


class Product(OrganizationScopedModel, TimeStampedModel):
    """Something the company buys and sells. Quantities are in `base_unit` (always kg for now, D-029).

    The sale price is not stored here: it changes every day, so it lives in `ProductPrice` (D-020).
    """

    reference = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    name_ar = models.CharField(max_length=150, blank=True)
    # The species' Latin name ("Dicentrarchus labrax"), printed with the lot's origin (D-299).
    scientific_name = models.CharField(max_length=150, blank=True)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    base_unit = models.ForeignKey(Unit, on_delete=models.PROTECT, related_name="+")
    # Below this total quantity the stock screens warn.
    min_stock = QuantityField(default=0)
    # Storage temperature in °C; either end may be open ("≤ -18 °C" for frozen goods).
    storage_temp_min = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    storage_temp_max = models.DecimalField(max_digits=4, decimal_places=1, null=True, blank=True)
    illustration = models.CharField(max_length=20, choices=Illustration.choices, default=Illustration.FISH)
    photo = models.ImageField(upload_to=product_photo_path, blank=True)
    # Archived products keep their history but cannot be bought or sold.
    is_active = models.BooleanField(default=True)
    # Selling below this price only warns (and is logged in the audit), it never blocks (D-049).
    min_price = models.DecimalField(max_digits=14, decimal_places=3, null=True, blank=True)
    # The product's own VAT rate in percent, proposed on invoices instead of the organization's rate (D-056).
    # Empty = the finance settings' rate; 0 = exempt (Tunisian fishing products, to check with the accountant).
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                "organization", Lower("reference"), name="product_reference_unique_per_organization"
            ),
            models.CheckConstraint(condition=models.Q(min_stock__gte=0), name="product_min_stock_not_negative"),
            models.CheckConstraint(
                condition=models.Q(storage_temp_min__isnull=True)
                | models.Q(storage_temp_max__isnull=True)
                | models.Q(storage_temp_min__lte=models.F("storage_temp_max")),
                name="product_storage_temp_range_ordered",
            ),
            models.CheckConstraint(
                condition=models.Q(vat_rate__isnull=True) | models.Q(vat_rate__gte=0, vat_rate__lte=100),
                name="product_vat_rate_percent",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.reference} · {self.name}"


class ProductPriceQuerySet(OrganizationScopedQuerySet["ProductPrice"]):
    def update(self, **kwargs: Any) -> int:
        raise TypeError("Prices are history: set a new price instead of changing one")

    def delete(self) -> tuple[int, dict[str, int]]:
        raise TypeError("Prices are history: they are never deleted")


class ProductPrice(OrganizationScopedModel):
    """The sale price of one base unit from `valid_from` on, VAT as set by the organization (D-018).

    The price in force at a moment is the latest one at or before it. Append-only (D-020).
    """

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="prices")
    price = MoneyField()
    valid_from = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")

    objects = ProductPriceQuerySet.as_manager()  # type: ignore[misc]

    class Meta:
        ordering = ["-valid_from", "-id"]
        constraints = [
            # Its index also serves "the latest price at or before a moment".
            models.UniqueConstraint(fields=["product", "valid_from"], name="one_price_per_product_and_moment"),
            models.CheckConstraint(condition=models.Q(price__gt=0), name="product_price_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.product} · {self.price} dès {self.valid_from:%Y-%m-%d %H:%M}"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise TypeError("Prices are history: set a new price instead of changing one")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise TypeError("Prices are history: they are never deleted")


class PriceList(OrganizationScopedModel, TimeStampedModel):
    """Special sale prices for some products, for everybody or for one customer (D-049).

    A price list is a working document, not history: its items are replaced as a whole and every change is
    audited. Its prices apply to a sale before the product's daily price does.
    """

    name = models.CharField(max_length=100)
    # By name, not by import: an app only uses another app's services and selectors (ARCHITECTURE §3).
    customer = models.ForeignKey("partners.Customer", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint("organization", Lower("name"), name="price_list_name_unique_per_organization"),
            # One list per customer keeps "the customer's price" unambiguous.
            models.UniqueConstraint(
                fields=["organization", "customer"],
                condition=models.Q(customer__isnull=False),
                name="one_price_list_per_customer",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class PriceListItem(OrganizationScopedModel):
    price_list = models.ForeignKey(PriceList, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    price = MoneyField()

    class Meta:
        ordering = ["product__name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["price_list", "product"], name="one_item_per_product_in_price_list"),
            models.CheckConstraint(condition=models.Q(price__gt=0), name="price_list_item_price_positive"),
        ]

    def __str__(self) -> str:
        return f"{self.price_list} · {self.product} · {self.price}"


class VatRate(OrganizationScopedModel, TimeStampedModel):
    """One VAT rate the organization uses (Paramètres › TVA, D-283). The product form offers the active ones. A
    deactivated rate is no longer offered but stays where it is used: products, documents and lines keep the
    percent itself, so changing this list never recomputes a saved document. A rate is deleted only while unused."""

    rate = models.DecimalField(max_digits=5, decimal_places=2)
    label = models.CharField(max_length=60, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["rate", "id"]
        constraints = [
            models.UniqueConstraint(fields=["organization", "rate"], name="vat_rate_unique_per_organization"),
            models.CheckConstraint(condition=models.Q(rate__gte=0, rate__lte=100), name="vat_rate_percent"),
        ]

    def __str__(self) -> str:
        return f"{self.rate} %"
