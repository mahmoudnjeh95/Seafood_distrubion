"""D-286: a BL "non facturable" (owed, never invoiced) or "offert" (given away: nothing owed, never invoiced)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import receivables, selectors, services
from apps.sales.models import SaleBilling

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(organization=organization, credit_limit=D("5000.000"))


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, counter_sales=True)


@pytest.fixture
def product(organization, counter):
    """A product at 42.000 DT/kg (minimum 40.000), 50 kg in stock at 20.000 DT/kg."""
    product = ProductFactory.create(organization=organization, min_price=D("40.000"))
    ProductPriceFactory.create(product=product, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=30))
    batch = BatchFactory.create(organization=organization, product=product, unit_cost=D("20.000"))
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("50"),
        to_location=counter,
    )
    return product


def sell(organization, manager, customer, counter, product, **fields):
    return services.create_sale(
        organization=organization,
        actor=manager.user,
        customer=customer,
        location=counter,
        lines=[{"product": product, "quantity": "5"}],
        confirm=True,
        **fields,
    )


def test_a_non_invoiced_bl_is_owed_but_never_offered_for_an_invoice(organization, manager, customer, counter, product):
    bl = sell(organization, manager, customer, counter, product, billing=SaleBilling.NO_INVOICE)

    assert (bl.billing, bl.total, bl.amount_due) == (SaleBilling.NO_INVOICE, D("210.000"), D("210.000"))
    assert receivables.customer_balance(organization, customer.pk).balance == D("210.000")
    assert list(selectors.sales_of(organization, uninvoiced=True)) == []
    assert services.estimated_extras(organization, [bl.pk]) == {}
    with pytest.raises(ValidationError) as refused:
        services.create_invoice(apply_vat=False, sale=bl, actor=manager.user)
    assert "ne se facture pas" in str(refused.value)


def test_a_free_bl_owes_nothing_and_its_lot_carries_the_cost(organization, manager, customer, counter, product):
    # The 100 % discount takes the price under the minimum: allowed for a gift, no reason asked.
    bl = sell(organization, manager, customer, counter, product, billing=SaleBilling.FREE)

    line = bl.lines.get()
    assert (line.unit_price, line.discount_rate, line.amount) == (D("42.000"), D("100.00"), D("0.000"))
    assert (bl.total, bl.amount_due, bl.cost_total) == (D("0.000"), D("0.000"), D("100.000"))
    assert receivables.customer_balance(organization, customer.pk).balance == D("0.000")
    assert list(selectors.sales_of(organization, uninvoiced=True)) == []
    assert [row.pk for row in selectors.sales_of(organization, billing=SaleBilling.FREE)] == [bl.pk]


def test_a_confirmed_bl_switches_between_invoiced_and_not_while_on_no_invoice(
    organization, manager, customer, counter, product
):
    bl = sell(organization, manager, customer, counter, product)
    services.set_sale_billing(sale=bl, actor=manager.user, billing=SaleBilling.NO_INVOICE)
    bl.refresh_from_db()
    assert bl.billing == SaleBilling.NO_INVOICE
    assert AuditLog.objects.filter(action="sale.billing_changed").count() == 1

    services.set_sale_billing(sale=bl, actor=manager.user, billing=SaleBilling.INVOICE)
    services.create_invoice(apply_vat=False, sale=bl, actor=manager.user)
    with pytest.raises(ValidationError):
        services.set_sale_billing(sale=bl, actor=manager.user, billing=SaleBilling.NO_INVOICE)  # on a draft invoice
    with pytest.raises(ValidationError):
        services.set_sale_billing(sale=bl, actor=manager.user, billing=SaleBilling.FREE)  # changes what is owed

    gift = sell(organization, manager, customer, counter, product, billing=SaleBilling.FREE)
    with pytest.raises(ValidationError):
        services.set_sale_billing(sale=gift, actor=manager.user, billing=SaleBilling.INVOICE)


def test_the_walk_in_customer_keeps_the_usual_billing(organization, manager, counter, product):
    with pytest.raises(ValidationError) as refused:
        sell(organization, manager, None, counter, product, billing=SaleBilling.NO_INVOICE)
    assert "billing" in refused.value.message_dict


def test_the_office_chooses_the_billing_and_the_driver_cannot(manager, organization, customer, counter, product):
    client = APIClient()
    client.force_authenticate(manager.user)
    payload = {
        "customer": customer.pk,
        "location": counter.pk,
        "lines": [{"product": product.pk, "quantity": "2"}],
        "billing": "free",
    }
    created = client.post(reverse("sale-list"), payload, format="json")
    assert created.status_code == 201, created.json()
    assert (created.json()["billing"], created.json()["total"]) == ("free", "0.000")

    other = client.post(reverse("sale-list"), {**payload, "billing": "invoice", "confirm_now": True}, format="json")
    switched = client.post(reverse("sale-billing", args=[other.json()["id"]]), {"billing": "no_invoice"}, format="json")
    assert switched.status_code == 200
    assert switched.json()["billing"] == "no_invoice"
    listed = client.get(reverse("sale-list"), {"billing": "no_invoice"}).json()["results"]
    assert [row["id"] for row in listed] == [other.json()["id"]]

    driver = MembershipFactory.create(role=Role.DRIVER, organization=organization)
    phone = APIClient()
    phone.force_authenticate(driver.user)
    refused = phone.post(reverse("sale-billing", args=[other.json()["id"]]), {"billing": "invoice"}, format="json")
    assert refused.status_code == 403
