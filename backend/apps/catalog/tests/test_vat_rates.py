"""Paramètres › TVA (D-283): the VAT rates the product form offers."""

from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.catalog.models import VatRate
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory

from .factories import ProductFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def api(manager):
    client = APIClient()
    client.force_authenticate(manager.user)
    return client


def test_a_new_company_has_the_tunisian_rates(api):
    assert [row["rate"] for row in api.get(reverse("vat-rate-list")).json()] == ["0.00", "7.00", "13.00", "19.00"]


def test_a_product_takes_only_an_active_rate_and_keeps_a_deactivated_one(api, manager):
    product = ProductFactory.create(organization=manager.organization)
    assert api.patch(reverse("product-detail", args=[product.pk]), {"vat_rate": "7"}, format="json").status_code == 200
    seven = VatRate.objects.get(organization=manager.organization, rate=Decimal("7"))

    api.patch(reverse("vat-rate-detail", args=[seven.pk]), {"is_active": False}, format="json")

    # Its product keeps it; the rate is no longer offered to another product.
    assert api.patch(reverse("product-detail", args=[product.pk]), {"name": "Loup"}, format="json").status_code == 200
    other = ProductFactory.create(organization=manager.organization)
    refused = api.patch(reverse("product-detail", args=[other.pk]), {"vat_rate": "7"}, format="json")
    assert refused.status_code == 400
    assert "vat_rate" in refused.json()
    assert api.patch(reverse("product-detail", args=[other.pk]), {"vat_rate": "5"}, format="json").status_code == 400


def test_a_rate_is_deleted_only_while_unused(api, manager):
    created = api.post(reverse("vat-rate-list"), {"rate": "12", "label": "Test"}, format="json")
    assert created.status_code == 201
    nineteen = VatRate.objects.get(organization=manager.organization, rate=Decimal("19"))
    ProductFactory.create(organization=manager.organization, vat_rate=Decimal("19"))

    assert api.delete(reverse("vat-rate-detail", args=[nineteen.pk])).status_code == 400
    assert api.delete(reverse("vat-rate-detail", args=[created.json()["id"]])).status_code == 204
    assert api.post(reverse("vat-rate-list"), {"rate": "19"}, format="json").status_code == 400


def test_drivers_do_not_read_the_rates(manager):
    driver = MembershipFactory.create(organization=manager.organization, role=Role.DRIVER)
    client = APIClient()
    client.force_authenticate(driver.user)

    assert client.get(reverse("vat-rate-list")).status_code == 403
