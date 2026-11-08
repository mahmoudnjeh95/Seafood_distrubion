"""Reusable read queries of suppliers (and of customers, from Phase 2)."""

from typing import Literal

from django.db.models import Count, Prefetch, Q, QuerySet

from apps.core.models import Organization

from .models import Customer, CustomerContact, Supplier, SupplierContact

type SupplierStatus = Literal["active", "archived", "all"]


def suppliers_of(
    organization: Organization, *, search: str = "", status: SupplierStatus = "active"
) -> QuerySet[Supplier]:
    """Suppliers of one organization sorted by name, each with its contacts."""
    suppliers = (
        Supplier.objects.for_organization(organization)
        .prefetch_related(Prefetch("contacts", queryset=SupplierContact.objects.order_by("id")))
        .order_by("name", "id")
    )
    if status == "active":
        suppliers = suppliers.filter(is_active=True)
    elif status == "archived":
        suppliers = suppliers.filter(is_active=False)
    if search := search.strip():
        matching = Supplier.objects.filter(
            Q(name__icontains=search)
            | Q(reference__icontains=search)
            | Q(city__icontains=search)
            | Q(phone__icontains=search)
            | Q(tax_id__icontains=search)
            | Q(contacts__name__icontains=search)
        )
        # A subquery rather than a join: a supplier with two matching contacts is still listed once.
        suppliers = suppliers.filter(pk__in=matching.values("pk"))
    return suppliers


def supplier_of(organization: Organization, supplier_id: int) -> Supplier:
    """One supplier with its contacts. Raises Supplier.DoesNotExist outside the organization."""
    return suppliers_of(organization, status="all").get(pk=supplier_id)


def customers_of(
    organization: Organization, *, search: str = "", status: SupplierStatus = "active", kind: str = ""
) -> QuerySet[Customer]:
    """Customers of one organization sorted by name (the walk-in one last), each with its contacts."""
    customers = (
        Customer.objects.for_organization(organization)
        .prefetch_related(Prefetch("contacts", queryset=CustomerContact.objects.order_by("id")))
        .order_by("is_walk_in", "name", "id")
    )
    if status == "active":
        customers = customers.filter(is_active=True)
    elif status == "archived":
        customers = customers.filter(is_active=False)
    if kind:
        customers = customers.filter(kind=kind)
    if search := search.strip():
        matching = Customer.objects.filter(
            Q(name__icontains=search)
            | Q(reference__icontains=search)
            | Q(city__icontains=search)
            | Q(phone__icontains=search)
            | Q(tax_id__icontains=search)
            | Q(contacts__name__icontains=search)
        )
        # A subquery rather than a join: a customer with two matching contacts is still listed once.
        customers = customers.filter(pk__in=matching.values("pk"))
    return customers


def customer_of(organization: Organization, customer_id: int) -> Customer:
    """One customer with its contacts. Raises Customer.DoesNotExist outside the organization."""
    return customers_of(organization, status="all").get(pk=customer_id)


def customer_places(organization: Organization) -> list[Customer]:
    """The active customers whose place on the map is known (D-172)."""
    return list(
        Customer.objects.for_organization(organization).filter(
            is_active=True, latitude__isnull=False, longitude__isnull=False
        )
    )


def customer_type_counts(organization: Organization) -> dict[str, int]:
    """How many customers, archived included, have each customer type code (D-283)."""
    rows = (
        Customer.objects.for_organization(organization)
        .order_by()
        .values("kind")
        .annotate(count=Count("pk"))
        .values_list("kind", "count")
    )
    return dict(rows)
