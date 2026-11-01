from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.db.models.functions import Lower

from apps.core.models import OrganizationScopedModel, TimeStampedModel


def unique_emails(*addresses: str) -> list[str]:
    """The non-empty addresses, each once (case ignored), in the order given: the party's own first (D-222)."""
    seen: set[str] = set()
    result: list[str] = []
    for address in addresses:
        value = address.strip()
        if value and value.lower() not in seen:
            seen.add(value.lower())
            result.append(value)
    return result


class Supplier(OrganizationScopedModel, TimeStampedModel):
    """Someone the company buys seafood from: a fisherman, a wholesaler at the port, a fish farm, an importer.

    Its agreement (ordinary purchase, consignment, profit sharing, investment) comes in Phase 6; its
    balance comes with purchases and payments. Neither is stored here.
    """

    reference = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    # Tunisian "matricule fiscal", stored as 1234567A/A/M/000 (or 1234567A alone). Empty when unknown.
    tax_id = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    # Archived suppliers keep their history but cannot be bought from.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                "organization", Lower("reference"), name="supplier_reference_unique_per_organization"
            ),
            models.UniqueConstraint(
                fields=["organization", "tax_id"],
                condition=~models.Q(tax_id=""),
                name="supplier_tax_id_unique_per_organization",
            ),
        ]

    def email_addresses(self) -> list[str]:
        """Every address the party has: its own, then each contact's (D-222). The e-mail window offers them all."""
        return unique_emails(self.email, *(contact.email for contact in self.contacts.all()))

    def __str__(self) -> str:
        return f"{self.reference} · {self.name}"


class SupplierContact(OrganizationScopedModel):
    """A person to call at a supplier: the boat owner, the accountant, the person who loads the goods."""

    supplier = models.ForeignKey(Supplier, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=150)
    # What they do there ("Gérant", "Comptable"), free text.
    role = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["supplier", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.supplier.name})"


class CustomerKind(models.TextChoices):
    RESTAURANT = "restaurant", "Restaurant"
    HOTEL = "hotel", "Hôtel"
    FISH_SHOP = "fish_shop", "Poissonnerie"
    SUPERMARKET = "supermarket", "Supermarché"
    WHOLESALER = "wholesaler", "Grossiste"
    CATERER = "caterer", "Traiteur"
    INDIVIDUAL = "individual", "Particulier"


class Customer(OrganizationScopedModel, TimeStampedModel):
    """Someone the company sells to: a restaurant, a hotel, a fish shop, a supermarket, a wholesaler, a person.

    The balance owed comes with sales and payments (P2-T06) and is not stored here. The credit limit
    (Q16) is the ceiling each customer may owe; what happens above it is a company setting (P2-T06).
    """

    reference = models.CharField(max_length=30)
    name = models.CharField(max_length=150)
    kind = models.CharField(max_length=20, choices=CustomerKind.choices, default=CustomerKind.RESTAURANT)
    # Tunisian "matricule fiscal", stored as 1234567A/A/M/000 (or 1234567A alone). Empty when unknown.
    tax_id = models.CharField(max_length=20, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    notes = models.TextField(blank=True)
    # Where the customer is, saved from a stop of a driver's route (D-172); empty when unknown.
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    # What the customer may owe at most, in DT. 0 = no credit: pays at once.
    credit_limit = models.DecimalField(max_digits=12, decimal_places=3, default=0, validators=[MinValueValidator(0)])
    # Days after the invoice date by which the customer pays; 0 = on delivery.
    payment_terms_days = models.PositiveSmallIntegerField(default=0, validators=[MaxValueValidator(365)])
    # The "Client de passage" record counters and anonymous sales use: one per organization, never archived.
    is_walk_in = models.BooleanField(default=False)
    # Archived customers keep their history but cannot be sold to.
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [
            models.UniqueConstraint(
                "organization", Lower("reference"), name="customer_reference_unique_per_organization"
            ),
            models.UniqueConstraint(
                fields=["organization", "tax_id"],
                condition=~models.Q(tax_id=""),
                name="customer_tax_id_unique_per_organization",
            ),
            models.UniqueConstraint(
                fields=["organization"],
                condition=models.Q(is_walk_in=True),
                name="customer_one_walk_in_per_organization",
            ),
            models.CheckConstraint(
                condition=models.Q(latitude__isnull=True, longitude__isnull=True)
                | models.Q(latitude__isnull=False, longitude__isnull=False),
                name="customer_place_has_both_coordinates",
            ),
        ]

    def email_addresses(self) -> list[str]:
        """Every address the customer has: its own, then each contact's (D-222). The e-mail window offers them all."""
        return unique_emails(self.email, *(contact.email for contact in self.contacts.all()))

    def __str__(self) -> str:
        return f"{self.reference} · {self.name}"


class CustomerContact(OrganizationScopedModel):
    """A person to call at a customer: the chef, the purchasing manager, the accountant."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=150)
    role = models.CharField(max_length=100, blank=True)
    phone = models.CharField(max_length=30, blank=True)
    email = models.EmailField(blank=True)

    class Meta:
        ordering = ["customer", "id"]

    def __str__(self) -> str:
        return f"{self.name} ({self.customer.name})"
