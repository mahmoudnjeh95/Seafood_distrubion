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

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year


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
def sale(organization, manager):
    customer = CustomerFactory.create(organization=organization, name="Restaurant Le Corail")
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
        quantity=Decimal("50"),
        to_location=counter,
    )
    return services.create_sale(
        organization=organization,
        actor=manager.user,
        customer=customer,
        location=counter,
        lines=[{"product": crevette, "quantity": "5"}],
        confirm=True,
    )


def test_drivers_get_403_and_the_accountant_only_reads(organization, sale):
    driver = client_for(MembershipFactory.create(organization=organization, role=Role.DRIVER))
    accountant = client_for(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT))

    assert driver.get(reverse("invoice-list")).status_code == 403
    assert driver.get(reverse("finance-settings")).status_code == 403
    assert accountant.get(reverse("invoice-list")).status_code == 200
    assert accountant.get(reverse("finance-settings")).status_code == 200
    assert accountant.post(reverse("invoice-list"), {"sale": sale.pk}, format="json").status_code == 403


def test_only_the_owner_changes_the_finance_settings(organization, api):
    body = {"vat_rate": "19", "fiscal_stamp": "1.000", "prices_include_vat": True, "withholding_rate": "1.5"}

    refused = api.post(reverse("finance-settings"), body, format="json")
    assert refused.status_code == 403
    assert api.get(reverse("finance-settings")).json()["may_edit"] is False

    owner = client_for(MembershipFactory.create(organization=organization, role=Role.OWNER))
    response = owner.post(reverse("finance-settings"), {**body, "legal_name": "Frutti Del Mare"}, format="json")
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["may_edit"] is True
    assert data["in_force"]["prices_include_vat"] is True
    assert data["in_force"]["withholding_rate"] == "1.50"
    assert data["in_force"]["legal_name"] == "Frutti Del Mare"

    wrong = owner.post(reverse("finance-settings"), {**body, "vat_rate": "abc"}, format="json")
    assert wrong.status_code == 400
    assert "vat_rate" in wrong.json()


def test_invoice_a_sale_type_values_issue_and_credit(api, sale):
    created = api.post(reverse("invoice-list"), {"sale": sale.pk, "apply_vat": True}, format="json")
    assert created.status_code == 201, created.json()
    invoice = created.json()
    assert invoice["status"] == "draft"
    assert invoice["number"] == ""
    assert invoice["vat_total"] == "39.900"
    assert invoice["settings_vat_rate"] == "19.00"
    assert invoice["lines"][0]["default_vat_rate"] == "19.00"
    assert invoice["bill_to"]["name"] == "Restaurant Le Corail"

    url = reverse("invoice-detail", args=[invoice["id"]])
    body = {
        "apply_vat": True,
        "lines": [{"vat_rate": "7"}],
        "vat_amounts": [{"rate": "7.00", "amount": "14.000"}],
        "fiscal_stamp": "",
        "withholding_rate": "",
        "notes": "",
        "issue_now": True,
    }
    issued = api.put(url, body, format="json")
    assert issued.status_code == 200, issued.json()
    data = issued.json()
    assert data["status"] == "issued"
    assert data["number"] == f"FA-{YEAR}-0001"
    assert data["lines"][0]["vat_rate_overridden"] is True
    assert data["vat_lines"] == [
        {
            "rate": "7.00",
            "base": "210.000",
            "computed_amount": "14.700",
            "amount": "14.000",
            "amount_overridden": True,
        }
    ]
    assert data["total_incl_tax"] == "225.000"

    # The sale shows its invoice and VAT.
    sale_data = api.get(reverse("sale-detail", args=[sale.pk])).json()
    assert sale_data["invoice"] == {"id": invoice["id"], "number": f"FA-{YEAR}-0001", "status": "issued"}
    assert sale_data["tax_amount"] == "14.000"

    assert api.put(url, body, format="json").status_code == 400
    assert api.delete(url).status_code == 400

    line_id = data["lines"][0]["id"]
    credit_url = reverse("invoice-credit-notes", args=[invoice["id"]])
    wrong = api.post(
        credit_url,
        {"kind": "partial", "reason": "Retour", "lines": [{"invoice_line": line_id, "quantity": "9"}]},
        format="json",
    )
    assert wrong.status_code == 400
    assert "lines.0.quantity" in wrong.json()
    note = api.post(
        credit_url,
        {"kind": "partial", "reason": "Retour", "lines": [{"invoice_line": line_id, "quantity": "1"}]},
        format="json",
    )
    assert note.status_code == 201, note.json()
    assert note.json()["number"] == f"AV-{YEAR}-0001"
    assert note.json()["total_excl_tax"] == "42.000"
    assert note.json()["vat_total"] == "2.800"

    again = api.get(url).json()
    assert again["lines"][0]["credited_quantity"] == "1.000"
    assert again["credited_total"] == "44.800"
    assert again["remaining_to_pay"] == "180.200"
    assert api.get(reverse("credit-note-list")).json()["count"] == 1
    assert note.json()["stock"] == "none"
    restocked = api.post(
        credit_url,
        {
            "kind": "partial",
            "reason": "Retour en stock",
            "stock": "restock",
            "lines": [{"invoice_line": line_id, "quantity": "1"}],
        },
        format="json",
    )
    assert restocked.status_code == 201, restocked.json()
    assert restocked.json()["stock"] == "restock"
    bad = api.post(credit_url, {"kind": "full", "reason": "x", "stock": "burn"}, format="json")
    assert bad.status_code == 400
    listed = api.get(reverse("invoice-list"), {"status": "issued", "search": "Corail"}).json()
    assert listed["count"] == 1


def test_errors_come_back_on_their_field(api, sale):
    response = api.post(
        reverse("invoice-list"),
        {"sale": sale.pk, "lines": [{"vat_rate": "200"}], "fiscal_stamp": "x"},
        format="json",
    )

    assert response.status_code == 400
    assert set(response.json()) >= {"lines.0.vat_rate", "fiscal_stamp"}


def test_an_unknown_sale_or_another_organizations_invoice(api, sale):
    assert api.post(reverse("invoice-list"), {"sale": 999999}, format="json").status_code == 400
    other = client_for(MembershipFactory.create(role=Role.MANAGER))
    created = api.post(reverse("invoice-list"), {"sale": sale.pk}, format="json").json()
    assert other.get(reverse("invoice-detail", args=[created["id"]])).status_code == 404


def test_a_draft_can_be_issued_or_deleted(api, sale):
    created = api.post(reverse("invoice-list"), {"sale": sale.pk, "apply_vat": False}, format="json").json()
    assert created["vat_lines"] == []
    assert created["total_incl_tax"] == "211.000"

    url = reverse("invoice-detail", args=[created["id"]])
    assert api.delete(url).status_code == 204
    assert api.get(url).status_code == 404

    again = api.post(reverse("invoice-list"), {"sale": sale.pk}, format="json").json()
    issued = api.post(reverse("invoice-issue", args=[again["id"]]))
    assert issued.status_code == 200
    assert issued.json()["number"] == f"FA-{YEAR}-0001"


def test_product_vat_rate_is_set_and_kept(api, organization):
    product = ProductFactory.create(organization=organization)
    url = reverse("product-detail", args=[product.pk])

    response = api.patch(url, {"vat_rate": "0"}, format="json")
    assert response.status_code == 200, response.json()
    assert response.json()["vat_rate"] == "0.00"
    # A change that leaves the rate out keeps it.
    assert api.patch(url, {"name": "Sardine"}, format="json").json()["vat_rate"] == "0.00"
    assert api.patch(url, {"vat_rate": None}, format="json").json()["vat_rate"] is None
