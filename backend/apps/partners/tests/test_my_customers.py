from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.partners import services
from apps.partners.models import Customer

pytestmark = pytest.mark.django_db


def test_a_driver_finds_customers_by_name_and_only_a_driver_does():
    driver = MembershipFactory.create(role=Role.DRIVER)
    services.ensure_walk_in_customer(organization=driver.organization)
    services.create_customer(organization=driver.organization, actor=driver.user, name="Restaurant Le Port")
    services.create_customer(organization=driver.organization, actor=driver.user, name="Hôtel Marina")
    client = APIClient()
    client.force_authenticate(driver.user)

    found = client.get(reverse("my-customers"), {"search": "port"}).json()
    everyone = client.get(reverse("my-customers")).json()

    assert [c["name"] for c in found] == ["Restaurant Le Port"]
    assert [c["is_walk_in"] for c in everyone] == [False, False, True]  # the walk-in customer is last
    manager = APIClient()
    manager.force_authenticate(MembershipFactory.create(role=Role.MANAGER).user)
    assert manager.get(reverse("my-customers")).status_code == 403


def test_a_driver_adds_a_customer_on_the_phone_with_no_credit_and_no_duplicate_name():
    driver = MembershipFactory.create(role=Role.DRIVER)
    services.create_customer(organization=driver.organization, actor=driver.user, name="Restaurant Le Port")
    client = APIClient()
    client.force_authenticate(driver.user)

    created = client.post(
        reverse("my-customers"),
        {"name": "  Poissonnerie Ben Ali ", "phone": "98 000 000", "city": "Sfax"},
        format="json",
    )
    again = client.post(reverse("my-customers"), {"name": "restaurant le port"}, format="json")
    blank = client.post(reverse("my-customers"), {"name": "   "}, format="json")

    assert created.status_code == 201
    assert (created.json()["name"], created.json()["city"]) == ("Poissonnerie Ben Ali", "Sfax")
    # A driver never sees what a customer owes (D-207).
    assert "owes" not in created.json()
    customer = Customer.objects.get(pk=created.json()["id"])
    assert (customer.phone, customer.credit_limit) == ("98 000 000", Decimal("0"))
    assert again.status_code == 400
    assert "déjà ce nom" in again.json()["name"]
    assert blank.status_code == 400
    names = [c["name"] for c in client.get(reverse("my-customers")).json()]
    assert "Poissonnerie Ben Ali" in names
