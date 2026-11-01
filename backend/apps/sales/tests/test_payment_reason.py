"""The optional Motif and "Payé par" of a customer règlement (D-225): saved, shown, and length-checked."""

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import CustomerFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def api(manager):
    client = APIClient()
    client.force_authenticate(manager.user)
    return client


@pytest.fixture
def customer(manager):
    return CustomerFactory.create(organization=manager.organization, name="Restaurant Le Corail")


def test_motif_and_paid_by_are_saved_and_listed(api, customer):
    created = api.post(
        reverse("customer-payment-list"),
        {
            "customer": customer.pk,
            "amount": "50.000",
            "method": "cash",
            "reason": "  Acompte de mai ",
            "paid_by": "Fils du patron",
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert (created.json()["reason"], created.json()["paid_by"]) == ("Acompte de mai", "Fils du patron")

    listed = api.get(reverse("customer-payment-list")).json()["results"]
    assert (listed[0]["reason"], listed[0]["paid_by"]) == ("Acompte de mai", "Fils du patron")
    detail = api.get(reverse("customer-payment-detail", args=[created.json()["id"]])).json()
    assert detail["reason"] == "Acompte de mai"


def test_both_are_optional(api, customer):
    created = api.post(
        reverse("customer-payment-list"),
        {"customer": customer.pk, "amount": "10.000", "method": "cash"},
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert (created.json()["reason"], created.json()["paid_by"]) == ("", "")


def test_too_long_motif_or_payer_is_refused(api, customer):
    base = {"customer": customer.pk, "amount": "10.000", "method": "cash"}
    long_reason = api.post(reverse("customer-payment-list"), {**base, "reason": "m" * 201}, format="json")
    assert long_reason.status_code == 400
    assert "reason" in long_reason.json()
    long_payer = api.post(reverse("customer-payment-list"), {**base, "paid_by": "p" * 121}, format="json")
    assert long_payer.status_code == 400
    assert "paid_by" in long_payer.json()
