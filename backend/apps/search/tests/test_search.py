import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.inventory.tests.factories import BatchFactory
from apps.partners.tests.factories import CustomerFactory, SupplierFactory

pytestmark = pytest.mark.django_db

URL = reverse("search")


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def kinds_and_labels(answer):
    return [(hit["kind"], hit["title"]) for hit in answer.json()]


def test_one_box_finds_customers_suppliers_products_and_lots():
    manager = MembershipFactory.create(role=Role.MANAGER)
    organization = manager.organization
    CustomerFactory.create(organization=organization, reference="C-001", name="Golfe Restaurant")
    SupplierFactory.create(organization=organization, reference="F-001", name="Pêcherie du Golfe")
    product = ProductFactory.create(organization=organization, name="Dorade du golfe")
    BatchFactory.create(organization=organization, number="L-0042-1", product=product)
    CustomerFactory.create(organization=organization, name="Autre client")

    found = kinds_and_labels(client_for(manager).get(URL, {"q": "golfe"}))

    assert ("customer", "C-001 · Golfe Restaurant") in found
    assert ("supplier", "F-001 · Pêcherie du Golfe") in found
    assert ("product", f"{product.reference} · Dorade du golfe") in found
    assert ("lot", "L-0042-1 · Dorade du golfe") in found
    assert all("Autre" not in label for _, label in found)
    # Grouped in a fixed order: the box reads customers first, then suppliers, products, lots.
    order = [kind for kind, _ in found]
    assert order == sorted(order, key=["customer", "supplier", "product", "lot", "sale", "invoice"].index)


def test_a_short_query_finds_nothing_and_each_kind_stops_at_five():
    manager = MembershipFactory.create(role=Role.MANAGER)
    for number in range(7):
        CustomerFactory.create(organization=manager.organization, name=f"Marée {number}")
    client = client_for(manager)

    assert client.get(URL, {"q": "m"}).json() == []
    assert len(client.get(URL, {"q": "marée"}).json()) == 5


def test_only_the_sections_the_person_may_read_are_searched():
    # The owner took the customers away from this manager (D-306): their names never show in the box.
    manager = MembershipFactory.create(role=Role.MANAGER, access_overrides={"customers": "none"})
    CustomerFactory.create(organization=manager.organization, name="Golfe Restaurant")
    SupplierFactory.create(organization=manager.organization, name="Pêcherie du Golfe")

    kinds = {kind for kind, _ in kinds_and_labels(client_for(manager).get(URL, {"q": "golfe"}))}

    assert kinds == {"supplier"}


def test_another_company_is_never_found_and_drivers_have_no_box():
    manager = MembershipFactory.create(role=Role.MANAGER)
    CustomerFactory.create(name="Golfe Restaurant")  # another organization

    assert client_for(manager).get(URL, {"q": "golfe"}).json() == []
    driver = MembershipFactory.create(role=Role.DRIVER, organization=manager.organization)
    assert client_for(driver).get(URL, {"q": "golfe"}).status_code == 403
