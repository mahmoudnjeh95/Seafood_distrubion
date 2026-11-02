import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import services
from apps.treasury import selectors as treasury

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def api(manager):
    return client_for(manager)


@pytest.fixture
def setup(organization, manager):
    customer = CustomerFactory.create(organization=organization, name="Restaurant Le Corail", credit_limit="1000")
    counter = StockLocationFactory.create(organization=organization, counter_sales=True)
    crevette = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(
        product=crevette, price=Decimal("42.000"), valid_from=timezone.now() - dt.timedelta(days=30)
    )
    batch = BatchFactory.create(organization=organization, product=crevette, unit_cost=Decimal("20.000"))
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=Decimal("500"),
        to_location=counter,
    )
    sale = services.create_sale(
        organization=organization,
        actor=manager.user,
        customer=customer,
        location=counter,
        lines=[{"product": crevette, "quantity": "5"}],
        confirm=True,
    )
    return customer, sale


def test_permissions(organization, setup):
    customer, _sale = setup
    driver = client_for(MembershipFactory.create(organization=organization, role=Role.DRIVER))
    accountant = client_for(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT))
    body = {"customer": customer.pk, "amount": "10.000", "method": "cash"}
    assert driver.get(reverse("customer-payment-list")).status_code == 403
    assert driver.get(reverse("customer-balance", args=[customer.pk])).status_code == 403
    assert accountant.get(reverse("customer-payment-list")).status_code == 200
    assert accountant.get(reverse("receivables-ageing")).status_code == 200
    assert accountant.get(reverse("withholding-summary")).status_code == 200
    assert accountant.post(reverse("customer-payment-list"), body, format="json").status_code == 403


def test_customer_pays_100_and_the_balance_shows_the_rest(api, setup):
    customer, sale = setup
    created = api.post(
        reverse("customer-payment-list"),
        {
            "customer": customer.pk,
            "lines": [
                {
                    "method": "cheque",
                    "amount": "100.000",
                    "number": "CH-1",
                    "bank": treasury.banks_of(customer.organization).get(code="BIAT").pk,
                }
            ],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    payment = created.json()
    assert payment["number"] == "RG-0001"
    assert (payment["allocated_total"], payment["unallocated"]) == ("100.000", "0.000")
    assert payment["allocations"][0]["sale"]["number"] == sale.number
    assert payment["method"] == "cheque"
    [line] = payment["lines"]
    assert (line["amount"], line["instrument"]["number"], line["instrument"]["bank_code"]) == (
        "100.000",
        "CH-1",
        "BIAT",
    )
    assert line["instrument"]["status"] == "portfolio"

    balance = api.get(reverse("customer-balance", args=[customer.pk])).json()
    assert balance["balance"] == "110.000"
    assert balance["ageing"] == {"d0_30": "110.000", "d31_60": "0.000", "d60_plus": "0.000"}
    assert balance["available_credit"] == "890.000"
    assert [row["kind"] for row in balance["history"]] == ["payment", "sale"]

    ageing = api.get(reverse("receivables-ageing")).json()
    assert ageing["total_balance"] == "110.000"
    assert ageing["rows"][0]["customer"]["id"] == customer.pk

    voided = api.post(reverse("customer-payment-void", args=[payment["id"]]), {"reason": "Erreur"}, format="json")
    assert voided.status_code == 200
    assert voided.json()["is_voided"] is True
    assert api.get(reverse("customer-balance", args=[customer.pk])).json()["balance"] == "210.000"
    # Its cheque leaves the portfolio with it.
    assert voided.json()["lines"][0]["instrument"]["status"] == "cancelled"


def test_bad_allocation_is_reported_on_its_row(api, setup):
    customer, sale = setup
    response = api.post(
        reverse("customer-payment-list"),
        {
            "customer": customer.pk,
            "amount": "300.000",
            "method": "cash",
            "allocations": [{"sale": sale.pk, "amount": "250.000"}],
        },
        format="json",
    )
    assert response.status_code == 400
    assert "allocations.0.amount" in response.json()


def test_credit_limit_through_the_api_and_driver_cannot_approve(organization, api, setup):
    customer, sale = setup
    owner = client_for(MembershipFactory.create(organization=organization, role=Role.OWNER))
    assert owner.get(reverse("finance-settings")).json()["in_force"]["credit_policy"] == "block"
    body = {
        "vat_rate": "19",
        "fiscal_stamp": "1.000",
        "prices_include_vat": False,
        "withholding_rate": "0",
        "credit_policy": "approval",
    }
    assert owner.post(reverse("finance-settings"), body, format="json").status_code == 200

    big = {
        "customer": customer.pk,
        "location": sale.location_id,
        "lines": [{"product": sale.lines.first().product_id, "quantity": "30"}],
        "confirm_now": True,
    }
    pending = api.post(reverse("sale-list"), big, format="json")
    assert pending.status_code == 201, pending.json()
    assert (pending.json()["status"], pending.json()["credit_status"]) == ("draft", "pending")

    driver = client_for(MembershipFactory.create(organization=organization, role=Role.DRIVER))
    url = reverse("sale-confirm", args=[pending.json()["id"]])
    assert driver.post(url, {"approve_credit": True}, format="json").status_code in (403, 404)

    approved = api.post(url, {"approve_credit": True}, format="json")
    assert approved.status_code == 200, approved.json()
    assert (approved.json()["status"], approved.json()["credit_status"]) == ("confirmed", "approved")


def test_withholding_certificate_and_summary(api, setup, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    _customer, sale = setup
    invoice = services.create_invoice(
        apply_vat=True,
        sale=sale, actor=None, issue=True, withholding_applied=True, withholding_rate="1.5"
    )
    today = timezone.localdate().isoformat()
    summary = api.get(reverse("withholding-summary")).json()
    assert [row["id"] for row in summary["awaiting"]] == [invoice.pk]

    created = api.post(
        reverse("invoice-withholding-certificate", args=[invoice.pk]),
        {"number": "RS-9", "issued_on": today, "amount": "3.749"},
        format="json",
    )
    assert created.status_code == 201, created.json()
    summary = api.get(reverse("withholding-summary")).json()
    assert (summary["count"], summary["total"], summary["awaiting"]) == (1, "3.749", [])
    assert summary["by_month"][0]["amount"] == "3.749"
    detail = api.get(reverse("invoice-detail", args=[invoice.pk])).json()
    assert detail["certificate"]["number"] == "RS-9"
    assert detail["remaining_to_pay"] == "247.151"

    voided = api.post(
        reverse("withholding-certificate-void", args=[created.json()["id"]]), {"reason": "Erreur"}, format="json"
    )
    assert voided.status_code == 200
    assert api.get(reverse("withholding-summary")).json()["count"] == 0
