"""The Excel file of a list keeps the list's filters and sort and holds every row (D-276)."""

from io import BytesIO

import pytest
from django.urls import reverse
from openpyxl import load_workbook
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import services

pytestmark = pytest.mark.django_db


def _first_column(response) -> list[str]:
    sheet = load_workbook(BytesIO(response.content)).active
    assert sheet is not None
    return [row[2] for row in sheet.iter_rows(min_row=2, values_only=True)]


def test_the_payment_file_follows_the_sort_of_the_list():
    manager = MembershipFactory.create(role=Role.MANAGER)
    organization = manager.organization
    for name in ("Alpha", "Zeta", "Mimosa"):
        customer = CustomerFactory.create(organization=organization, name=name)
        services.record_customer_payment(
            organization=organization,
            actor=manager.user,
            customer=customer,
            lines=[{"method": "cash", "amount": "10"}],
            allocations=[],
        )
    api = APIClient()
    api.force_authenticate(manager.user)
    url = reverse("customer-payment-export")
    names = _first_column(api.get(url, {"ordering": "-customer"}))
    assert names[:3] == ["Zeta", "Mimosa", "Alpha"]
    assert _first_column(api.get(url, {"ordering": "customer"}))[:3] == ["Alpha", "Mimosa", "Zeta"]


@pytest.mark.parametrize("name", ["sale-export", "invoice-export", "supplier-invoice-export", "expense-export"])
def test_each_list_has_an_excel_file(name):
    manager = MembershipFactory.create(role=Role.MANAGER)
    api = APIClient()
    api.force_authenticate(manager.user)
    response = api.get(reverse(name), {"ordering": "-number"})
    assert response.status_code == 200
    assert response["Content-Disposition"].endswith('.xlsx"')
