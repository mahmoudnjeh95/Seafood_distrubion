"""The list of customer règlements: filters by means and state, totals, Excel file, effet history (P9-T03b)."""

import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import services
from apps.treasury import selectors as treasury

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate


def test_the_list_filters_adds_up_exports_and_shows_each_effet_history():
    manager = MembershipFactory.create(role=Role.MANAGER)
    organization = manager.organization
    customer = CustomerFactory.create(organization=organization, name="Hôtel Les Pins")
    biat = treasury.banks_of(organization).get(code="BIAT")

    def pay(lines, **extra):
        return services.record_customer_payment(
            organization=organization, actor=manager.user, customer=customer, lines=lines, allocations=[], **extra
        )

    mixed = pay(
        [
            {"method": "cash", "amount": "100"},
            {"method": "bill", "amount": "300", "number": "T9", "bank": biat, "due_on": TODAY()},
        ]
    )
    cash = pay([{"method": "cash", "amount": "50"}], received_on=TODAY() - dt.timedelta(days=3))
    voided = pay([{"method": "transfer", "amount": "999", "reference": "VIR"}])
    services.void_customer_payment(payment=voided, actor=manager.user, reason="erreur")
    api = APIClient()
    api.force_authenticate(manager.user)
    url = reverse("customer-payment-list")

    def numbers(**params):
        return [row["number"] for row in api.get(url, params).json()["results"]]

    assert numbers(method="cash") == [mixed.number, cash.number]
    assert numbers(method="mixed") == [mixed.number]
    assert numbers(state="voided") == [voided.number]
    assert numbers(state="unallocated") == [mixed.number, cash.number]
    assert numbers(state="active", method="transfer") == []

    assert api.get(reverse("customer-payment-totals")).json() == {
        "count": 2,
        "voided": 1,
        "total": "450.000",
        "allocated": "0.000",
        "unallocated": "450.000",
        "by_method": {"bill": "300.000", "cash": "150.000"},
    }
    exported = api.get(reverse("customer-payment-export"))
    assert exported.status_code == 200
    assert exported["Content-Disposition"] == 'attachment; filename="reglements-clients.xlsx"'

    detail = api.get(reverse("customer-payment-detail", args=[mixed.pk])).json()
    events = detail["lines"][1]["instrument"]["events"]
    assert [(row["from_status"], row["to_status"]) for row in events] == [("", "portfolio")]
