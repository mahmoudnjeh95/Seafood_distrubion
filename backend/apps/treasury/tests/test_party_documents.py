"""What each customer and supplier has on paper, for the lists of the règlement forms (D-211)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing.models import SupplierInvoice, SupplierInvoiceStatus

pytestmark = pytest.mark.django_db

D = Decimal


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def test_a_supplier_is_counted_by_its_invoices_but_not_its_drafts():
    manager = MembershipFactory.create(role=Role.MANAGER)
    organization = manager.organization
    supplier = SupplierFactory.create(organization=organization)
    SupplierFactory.create(organization=organization)  # no document: not listed
    for number, status, total in [
        ("FF-0001", SupplierInvoiceStatus.POSTED, D("1471.500")),
        ("FF-0002", SupplierInvoiceStatus.PAID, D("200.000")),
        ("FF-0003", SupplierInvoiceStatus.DRAFT, D("999.000")),
    ]:
        SupplierInvoice.objects.create(
            organization=organization,
            number=number,
            supplier=supplier,
            invoice_date=dt.date(2026, 10, 1),
            due_date=dt.date(2026, 11, 1),
            status=status,
            total=total,
        )

    body = client_for(manager).get(reverse("treasury-party-documents")).json()

    assert body["customers"] == []
    assert body["suppliers"] == [{"id": supplier.pk, "deliveries": 0, "invoices": 2, "total": "1671.500"}]


def test_drivers_do_not_see_the_party_documents():
    driver = MembershipFactory.create(role=Role.DRIVER)

    assert client_for(driver).get(reverse("treasury-party-documents")).status_code == 403
