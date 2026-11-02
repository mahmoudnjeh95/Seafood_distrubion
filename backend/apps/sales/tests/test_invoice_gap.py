"""D-256: a BL paid before its invoice. The invoice is worked out in advance without saving (VAT only on goods
bought with VAT, one stamp), the BL's open row carries the estimate, and an invoice reads paid / partly paid."""

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
from apps.sales.models import Invoice, Sale

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


@pytest.fixture
def api(manager):
    client = APIClient()
    client.force_authenticate(manager.user)
    return client


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail", credit_limit=D("5000.000"))


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, counter_sales=True)


def sell(organization, manager, customer, counter, *, with_vat, kg="5"):
    """A confirmed BL of `kg` kilos at 42.000 DT, from a lot bought with or without VAT."""
    product = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=product, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=30))
    batch = BatchFactory.create(
        organization=organization, product=product, unit_cost=D("20.000"), bought_with_vat=with_vat
    )
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("50"),
        to_location=counter,
    )
    return services.create_sale(
        organization=organization,
        actor=manager.user,
        customer=customer,
        location=counter,
        lines=[{"product": product, "quantity": kg}],
        confirm=True,
    )


def pay(organization, manager, customer, amount):
    return services.record_customer_payment(
        organization=organization, actor=manager.user, customer=customer, amount=amount, method="cash"
    )


def test_goods_without_vat_have_only_the_stamp_to_come(organization, manager, customer, counter):
    bl = sell(organization, manager, customer, counter, with_vat=False)  # 210.000

    estimate = services.estimate_invoice(organization=organization, sales=[bl])

    assert (estimate.total_excl_tax, estimate.vat_total, estimate.fiscal_stamp) == (
        D("210.000"),
        D("0.000"),
        D("1.000"),
    )
    assert estimate.vat_by_rate == []
    assert estimate.extra == D("1.000")
    assert estimate.extra_by_sale == {bl.pk: D("1.000")}
    assert not Invoice.objects.exists()


def test_goods_bought_with_vat_get_their_vat_and_the_stamp(organization, manager, customer, counter):
    bl = sell(organization, manager, customer, counter, with_vat=True)

    estimate = services.estimate_invoice(organization=organization, sales=[bl])

    assert estimate.vat_by_rate == [(D("19.00"), D("39.900"))]
    assert estimate.extra == D("40.900")
    assert estimate.net_to_pay == D("250.900")


def test_several_bl_pay_one_stamp_shared_between_them(organization, manager, customer, counter):
    first = sell(organization, manager, customer, counter, with_vat=False, kg="5")  # 210.000
    second = sell(organization, manager, customer, counter, with_vat=False, kg="10")  # 420.000

    estimate = services.estimate_invoice(organization=organization, sales=[first, second])

    assert estimate.fiscal_stamp == D("1.000")
    assert estimate.extra == D("1.000")
    assert sum(estimate.extra_by_sale.values()) == D("1.000")


def test_an_invoiced_bl_is_left_out_of_the_estimate(organization, manager, customer, counter):
    bl = sell(organization, manager, customer, counter, with_vat=False)
    services.create_invoice(sale=bl, actor=manager.user)

    estimate = services.estimate_invoice(organization=organization, sales=[bl])

    assert estimate.extra_by_sale == {}
    assert (estimate.net_to_pay, estimate.fiscal_stamp, estimate.extra) == (D("0.000"), D("0.000"), D("0.000"))


def test_the_open_row_of_a_bl_carries_the_estimate_and_an_invoiced_one_does_not(
    organization, manager, customer, counter, api
):
    bl = sell(organization, manager, customer, counter, with_vat=True)

    rows = api.get(reverse("customer-balance", args=[customer.pk])).json()["open_sales"]
    assert [(row["number"], row["estimated_extra"]) for row in rows] == [(bl.number, "40.900")]

    services.create_invoice(sale=bl, apply_vat=True, actor=manager.user, issue=True)
    rows = api.get(reverse("customer-balance", args=[customer.pk])).json()["open_sales"]
    assert [row["estimated_extra"] for row in rows] == ["0.000"]


def test_the_estimate_endpoint_answers_for_one_or_several_bl(organization, manager, customer, counter, api):
    bl = sell(organization, manager, customer, counter, with_vat=True)

    answer = api.get(reverse("invoice-estimate"), {"sales": str(bl.pk)})

    assert answer.status_code == 200
    body = answer.json()
    assert (body["vat_total"], body["fiscal_stamp"], body["extra"]) == ("39.900", "1.000", "40.900")
    assert body["vat_by_rate"] == [["19.00", "39.900"]]
    assert body["extra_by_sale"] == {str(bl.pk): "40.900"}
    assert api.get(reverse("invoice-estimate"), {"sales": "x"}).status_code == 400


def test_a_bl_paid_at_its_goods_then_invoiced_reads_partly_paid_with_the_gap(
    organization, manager, customer, counter, api
):
    bl = sell(organization, manager, customer, counter, with_vat=True)  # goods 210.000
    pay(organization, manager, customer, "210.000")

    invoice = services.create_invoice(sale=bl, apply_vat=True, actor=manager.user, issue=True)

    body = api.get(reverse("invoice-detail", args=[invoice.pk])).json()
    assert body["remaining_to_pay"] == "40.900"
    assert body["paid_total"] == "210.000"
    assert body["payment_state"] == "partial"
    assert body["extra_over_goods"] == "40.900"
    listed = api.get(reverse("invoice-list"), {"payment_state": "partial"}).json()["results"]
    assert [row["id"] for row in listed] == [invoice.pk]
    assert api.get(reverse("invoice-list"), {"payment_state": "paid"}).json()["results"] == []


def test_collecting_the_gap_makes_the_invoice_paid(organization, manager, customer, counter, api):
    bl = sell(organization, manager, customer, counter, with_vat=False)
    pay(organization, manager, customer, "210.000")
    invoice = services.create_invoice(sale=bl, actor=manager.user, issue=True)
    assert api.get(reverse("invoice-detail", args=[invoice.pk])).json()["remaining_to_pay"] == "1.000"

    pay(organization, manager, customer, "1.000")

    body = api.get(reverse("invoice-detail", args=[invoice.pk])).json()
    assert (body["payment_state"], body["remaining_to_pay"], body["paid_total"]) == ("paid", "0.000", "211.000")
    assert Sale.objects.get(pk=bl.pk).amount_due == D("0.000")


def test_an_unpaid_invoice_and_a_draft_read_unpaid_and_none(organization, manager, customer, counter, api):
    bl = sell(organization, manager, customer, counter, with_vat=False)
    draft = services.create_invoice(sale=bl, actor=manager.user)
    assert api.get(reverse("invoice-detail", args=[draft.pk])).json()["payment_state"] == "none"

    services.issue_invoice(invoice=draft, actor=manager.user)

    body = api.get(reverse("invoice-detail", args=[draft.pk])).json()
    assert (body["payment_state"], body["paid_total"]) == ("unpaid", "0.000")
