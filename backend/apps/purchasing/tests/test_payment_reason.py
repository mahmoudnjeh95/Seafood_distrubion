"""The optional Motif of a supplier règlement (D-225): saved with it, shown in its list and detail, length-checked."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.partners.tests.factories import SupplierFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER, organization=OrganizationFactory.create())


@pytest.fixture
def api(manager):
    client = APIClient()
    client.force_authenticate(manager.user)
    return client


@pytest.fixture
def supplier(manager):
    return SupplierFactory.create(organization=manager.organization, name="Mareyeur Port de Sfax")


def test_motif_is_saved_and_shown(api, supplier):
    created = api.post(
        reverse("supplier-payment-list"),
        {
            "supplier": supplier.pk,
            "paid_on": timezone.localdate().isoformat(),
            "amount": "120.000",
            "method": "cash",
            "reason": " Avance sur la commande ",
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert created.json()["reason"] == "Avance sur la commande"
    listed = api.get(reverse("supplier-payment-list")).json()["results"]
    assert listed[0]["reason"] == "Avance sur la commande"


def test_motif_is_optional_and_limited(api, supplier):
    base = {
        "supplier": supplier.pk,
        "paid_on": timezone.localdate().isoformat(),
        "amount": "120.000",
        "method": "cash",
    }
    assert api.post(reverse("supplier-payment-list"), base, format="json").json()["reason"] == ""
    too_long = api.post(reverse("supplier-payment-list"), {**base, "reason": "x" * 201}, format="json")
    assert too_long.status_code == 400
    assert "reason" in too_long.json()
