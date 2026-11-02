import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory, SupplierFactory
from apps.purchasing import services as purchasing
from apps.sales import services as sales

pytestmark = pytest.mark.django_db

D = Decimal
URL = reverse("document-index")


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
def customer(organization):
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail")


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


@pytest.fixture
def crevette(organization):
    product = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(product=product, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=30))
    return product


def stock_up(organization, product, location, kg):
    batch = BatchFactory.create(organization=organization, product=product, unit_cost=D("20.000"))
    stock.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )


def accepted_quote(organization, customer, counter, crevette, kg="5"):
    quote = sales.create_quote(
        organization=organization,
        actor=None,
        customer=customer,
        quoted_on=timezone.localdate(),
        location=counter,
        lines=[{"product": crevette, "quantity": kg, "unit_price": "42.000", "discount_rate": None}],
        send=True,
    )
    return sales.accept_quote(quote=quote, actor=None)


def rows_of(response):
    assert response.status_code == 200, response.content
    return {row["key"]: row for row in response.json()["results"]}


def test_a_sale_chain_shows_each_document_with_its_parent(api, organization, customer, counter, crevette):
    stock_up(organization, crevette, counter, D("20"))
    quote = accepted_quote(organization, customer, counter, crevette)
    sale = sales.create_sale_from_quote(quote=quote, actor=None, confirm=True)
    invoice = sales.create_invoice(apply_vat=True, sale=sale, actor=None, issue=True)
    note = sales.create_credit_note(invoice=invoice, actor=None, kind="full", reason="Erreur de client")

    rows = rows_of(api.get(URL))

    assert rows[f"DV:{quote.pk}"]["parents"] == []
    assert rows[f"BL:{sale.pk}"]["parents"] == [f"DV:{quote.pk}"]
    assert rows[f"FA:{invoice.pk}"]["parents"] == [f"BL:{sale.pk}"]
    assert rows[f"AV:{note.pk}"]["parents"] == [f"FA:{invoice.pk}"]
    bl = rows[f"BL:{sale.pk}"]
    assert bl["number"].startswith("BL-")
    assert bl["partner_name"] == "Restaurant Le Corail"
    assert bl["amount"] == "210.000"
    assert bl["tone"] == "done"
    assert bl["pdf"] == "delivery_note"
    # The quote did its job: it became a BL, so it can no longer be converted.
    assert rows[f"DV:{quote.pk}"]["tone"] == "done"
    assert rows[f"DV:{quote.pk}"]["actions"] == []
    # Cancelled by the full credit note: a new invoice may be made for the BL.
    assert rows[f"FA:{invoice.pk}"]["tone"] == "cancelled"
    assert rows[f"FA:{invoice.pk}"]["actions"] == []
    assert "to_invoice" in bl["actions"]


def test_actions_follow_the_state_of_each_document(api, organization, customer, counter, crevette):
    stock_up(organization, crevette, counter, D("20"))
    draft_quote = sales.create_quote(
        organization=organization,
        actor=None,
        customer=customer,
        quoted_on=timezone.localdate(),
        lines=[{"product": crevette, "quantity": "2", "unit_price": None, "discount_rate": None}],
    )
    accepted = accepted_quote(organization, customer, counter, crevette)
    draft_sale = sales.create_sale(
        organization=organization,
        actor=None,
        customer=customer,
        location=counter,
        lines=[{"product": crevette, "quantity": "1"}],
    )
    confirmed = sales.create_sale(
        organization=organization,
        actor=None,
        customer=customer,
        location=counter,
        lines=[{"product": crevette, "quantity": "1"}],
        confirm=True,
    )
    draft_invoice = sales.create_invoice(apply_vat=True, sale=confirmed, actor=None)

    rows = rows_of(api.get(URL))

    assert rows[f"DV:{draft_quote.pk}"]["actions"] == ["edit", "send"]
    assert rows[f"DV:{accepted.pk}"]["actions"] == ["to_sale"]
    assert rows[f"BL:{draft_sale.pk}"]["actions"] == ["edit", "confirm", "cancel"]
    assert rows[f"BL:{draft_sale.pk}"]["pdf"] == ""
    # Already on a draft invoice: not invoiced twice, but it can still be cancelled.
    assert rows[f"BL:{confirmed.pk}"]["actions"] == ["cancel"]
    draft = rows[f"FA:{draft_invoice.pk}"]
    assert (draft["number"], draft["actions"], draft["pdf"]) == ("", ["edit", "issue", "delete"], "")


def test_a_quote_keeps_its_bl_action_until_it_is_delivered_in_full(api, organization, customer, counter, crevette):
    stock_up(organization, crevette, counter, D("20"))
    quote = accepted_quote(organization, customer, counter, crevette)
    line = quote.lines.get()

    first = sales.create_sale_from_quote(
        quote=quote, actor=None, confirm=True, lines=[{"quote_line": line.pk, "quantity": "2"}]
    )
    rows = rows_of(api.get(URL))
    assert (rows[f"DV:{quote.pk}"]["actions"], rows[f"DV:{quote.pk}"]["tone"]) == (["to_sale"], "waiting")

    second = sales.create_sale_from_quote(quote=quote, actor=None, confirm=True)
    rows = rows_of(api.get(URL))
    assert (rows[f"DV:{quote.pk}"]["actions"], rows[f"DV:{quote.pk}"]["tone"]) == ([], "done")
    assert rows[f"BL:{first.pk}"]["parents"] == rows[f"BL:{second.pk}"]["parents"] == [f"DV:{quote.pk}"]
    assert (rows[f"BL:{first.pk}"]["amount"], rows[f"BL:{second.pk}"]["amount"]) == ("84.000", "126.000")


def test_an_invoice_of_several_bl_names_them_all(api, organization, customer, counter, crevette):
    stock_up(organization, crevette, counter, D("20"))
    first, second = (
        sales.create_sale(
            organization=organization,
            actor=None,
            customer=customer,
            location=counter,
            lines=[{"product": crevette, "quantity": "2"}],
            confirm=True,
        )
        for _ in range(2)
    )
    invoice = sales.create_invoice(apply_vat=True, sales=[first, second], actor=None)

    rows = rows_of(api.get(URL))

    assert rows[f"FA:{invoice.pk}"]["parents"] == [f"BL:{first.pk}", f"BL:{second.pk}"]
    assert "to_invoice" not in rows[f"BL:{second.pk}"]["actions"]


def test_a_purchase_chain_shows_order_receipts_and_invoice(api, organization, supplier, counter, crevette):
    order = purchasing.create_order(
        organization=organization,
        actor=None,
        supplier=supplier,
        ordered_on=timezone.localdate(),
        lines=[{"product": crevette, "ordered_quantity": "100", "unit_cost": "20.000"}],
    )
    first = purchasing.create_receipt(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=counter,
        purchase_order=order,
        received_on=timezone.localdate(),
        lines=[{"product": crevette, "invoiced_quantity": "40", "accepted_quantity": "40", "unit_cost": "20.000"}],
    )
    direct = purchasing.create_receipt(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=counter,
        received_on=timezone.localdate(),
        lines=[{"product": crevette, "invoiced_quantity": "10", "accepted_quantity": "10", "unit_cost": "21.000"}],
    )
    invoice = purchasing.create_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        receipts=[first, direct],
        invoice_date=timezone.localdate(),
        due_date=timezone.localdate() + dt.timedelta(days=30),
    )

    rows = rows_of(api.get(URL))

    ba = rows[f"BA:{order.pk}"]
    assert (ba["amount"], ba["status"], ba["tone"]) == ("2000.000", "partly_received", "waiting")
    assert ba["actions"] == ["receive", "close"]
    assert rows[f"BR:{first.pk}"]["parents"] == [f"BA:{order.pk}"]
    assert rows[f"BR:{first.pk}"]["amount"] == "800.000"
    # Received without an order: a root of its own.
    assert rows[f"BR:{direct.pk}"]["parents"] == []
    assert rows[f"BR:{direct.pk}"]["actions"] == []
    ff = rows[f"FF:{invoice.pk}"]
    assert ff["parents"] == [f"BR:{first.pk}", f"BR:{direct.pk}"]
    assert ff["actions"] == ["edit", "post", "delete"]


def test_filters_by_type_search_period_and_tone(api, organization, customer, supplier, counter, crevette):
    old = accepted_quote(organization, customer, counter, crevette)
    old.quoted_on = timezone.localdate() - dt.timedelta(days=60)
    old.valid_until = old.quoted_on
    old.save(update_fields=["quoted_on", "valid_until"])
    recent = accepted_quote(organization, customer, counter, crevette)
    order = purchasing.create_order(
        organization=organization,
        actor=None,
        supplier=supplier,
        ordered_on=timezone.localdate(),
        lines=[{"product": crevette, "ordered_quantity": "10", "unit_cost": "20.000"}],
    )

    assert set(rows_of(api.get(URL, {"types": "BA"}))) == {f"BA:{order.pk}"}
    assert set(rows_of(api.get(URL, {"search": "mareyeur"}))) == {f"BA:{order.pk}"}
    since = (timezone.localdate() - dt.timedelta(days=30)).isoformat()
    assert set(rows_of(api.get(URL, {"types": "dv", "date_from": since}))) == {f"DV:{recent.pk}"}
    assert set(rows_of(api.get(URL, {"tone": "waiting", "types": "DV,BA"}))) == {
        f"DV:{recent.pk}",
        f"BA:{order.pk}",
        f"DV:{old.pk}",
    }
    assert api.get(URL, {"types": "XX"}).status_code == 400


def test_only_office_roles_read_and_only_owner_or_manager_get_actions(organization, customer, counter, crevette):
    accepted_quote(organization, customer, counter, crevette)
    accountant = MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT)
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)

    rows = rows_of(client_for(accountant).get(URL))
    assert rows
    assert all(row["actions"] == [] for row in rows.values())
    assert client_for(driver).get(URL).status_code == 403
    assert APIClient().get(URL).status_code == 401
    assert client_for(accountant).post(URL, {}).status_code == 403


def test_another_organization_sees_nothing(organization, customer, counter, crevette):
    accepted_quote(organization, customer, counter, crevette)
    stranger = MembershipFactory.create(organization=OrganizationFactory.create(), role=Role.OWNER)

    assert client_for(stranger).get(URL).json()["results"] == []
