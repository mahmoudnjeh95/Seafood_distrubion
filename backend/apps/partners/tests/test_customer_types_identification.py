"""Paramètres › Types de clients and the customer's identification type and number (D-283)."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.models import CustomerType

from .factories import CustomerFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def api(manager):
    client = APIClient()
    client.force_authenticate(manager.user)
    return client


def test_a_new_company_starts_with_the_seven_types(api):
    labels = [row["label"] for row in api.get(reverse("customer-type-list")).json()]

    assert labels == ["Restaurant", "Hôtel", "Poissonnerie", "Supermarché", "Grossiste", "Traiteur", "Particulier"]


def test_an_added_type_is_offered_and_a_deactivated_one_stays_on_its_customers(api, manager):
    created = api.post(reverse("customer-type-list"), {"label": "Cantine scolaire"}, format="json")
    assert created.status_code == 201
    code = created.json()["code"]
    customer = api.post(reverse("customer-list"), {"name": "Lycée", "kind": code}, format="json").json()
    assert customer["kind"] == code
    assert [row["name"] for row in api.get(reverse("customer-list"), {"kind": code}).json()] == ["Lycée"]

    api.patch(reverse("customer-type-detail", args=[created.json()["id"]]), {"is_active": False}, format="json")

    # The customer keeps it and can still be saved with it...
    kept = api.patch(reverse("customer-detail", args=[customer["id"]]), {"phone": "71 000 000"}, format="json")
    assert (kept.status_code, kept.json()["kind"]) == (200, code)
    # ...but no other customer gets it any more.
    refused = api.post(reverse("customer-list"), {"name": "Collège", "kind": code}, format="json")
    assert refused.status_code == 400
    assert "kind" in refused.json()


def test_a_type_in_use_is_not_deleted(api, manager):
    hotel = CustomerType.objects.get(organization=manager.organization, code="hotel")
    CustomerFactory.create(organization=manager.organization, kind="hotel")

    assert api.delete(reverse("customer-type-detail", args=[hotel.pk])).status_code == 400
    unused = CustomerType.objects.get(organization=manager.organization, code="caterer")
    assert api.delete(reverse("customer-type-detail", args=[unused.pk])).status_code == 204


def test_a_cin_keeps_its_leading_zeros_and_is_checked(api):
    created = api.post(
        reverse("customer-list"), {"name": "Ali", "id_type": "cin", "tax_id": "0123 4567"}, format="json"
    )
    assert created.status_code == 201
    assert (created.json()["id_type"], created.json()["tax_id"]) == ("cin", "01234567")

    wrong = api.post(reverse("customer-list"), {"name": "Sami", "id_type": "cin", "tax_id": "1234"}, format="json")
    assert wrong.status_code == 400
    assert "tax_id" in wrong.json()


def test_an_existing_tax_id_stays_a_tax_id(api):
    created = api.post(reverse("customer-list"), {"name": "Corail", "tax_id": "1234567a/a/m/000"}, format="json")

    assert (created.json()["id_type"], created.json()["tax_id"]) == ("tax_id", "1234567A/A/M/000")
