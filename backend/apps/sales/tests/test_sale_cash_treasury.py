"""The money paid at the sale is a treasury movement the day of the sale (P9-T05b, D-239): the Caisse for cash at the
office, the driver's cash for cash a driver took on the road, the main bank account for a transfer or a card."""

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import services
from apps.treasury.models import AccountKind, TreasuryMovement

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(
        organization=organization,
        name="Restaurant Le Corail",
        credit_limit=D("1000.000"),
        payment_terms_days=30,
    )


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


@pytest.fixture
def crevette(organization):
    item = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(product=item, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=300))
    return item


@pytest.fixture
def stocked(organization, counter, crevette):
    batch = BatchFactory.create(
        organization=organization,
        product=crevette,
        unit_cost=D("20.000"),
        received_on=timezone.localdate() - dt.timedelta(days=120),
    )
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("500"),
        to_location=counter,
    )
    return crevette


def make_sale(organization, actor, customer, counter, product, kg, **fields):
    return services.create_sale(
        organization=organization,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": product, "quantity": kg}],
        confirm=True,
        **fields,
    )


def movement_of(sale):
    return TreasuryMovement.objects.get(source="sales.sale", source_id=sale.pk)


def test_cash_paid_at_the_counter_is_in_the_caisse_the_day_of_the_sale(organization, actor, customer, counter, stocked):
    sale = make_sale(
        organization,
        actor,
        customer,
        counter,
        stocked,
        "5",
        payment={"amount_paid": "50.000", "payment_method": "cash"},
    )

    row = movement_of(sale)
    assert row.account.kind == AccountKind.CASH
    assert row.amount == D("50.000")
    assert row.kind == "sale_cash"
    assert row.day == timezone.localtime(sale.sold_at).date()


def test_a_transfer_paid_at_the_sale_goes_to_the_main_bank_account(organization, actor, customer, counter, stocked):
    sale = make_sale(
        organization,
        actor,
        customer,
        counter,
        stocked,
        "5",
        payment={"amount_paid": "210.000", "payment_method": "transfer"},
    )

    assert movement_of(sale).account.kind == AccountKind.BANK


def test_a_sale_with_nothing_paid_moves_no_money(organization, actor, customer, counter, stocked):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")

    assert not TreasuryMovement.objects.filter(source="sales.sale", source_id=sale.pk).exists()
