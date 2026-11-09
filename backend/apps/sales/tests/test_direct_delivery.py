"""A direct BL "à livrer" (D-305, bug 11): validated with its number, the stock leaves only at the delivery."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import selectors as stock
from apps.inventory import services as inventory
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import services
from apps.sales.models import DeliveryStatus, SaleStatus

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def setup():
    organization = OrganizationFactory.create()
    room = StockLocationFactory.create(organization=organization, name="Chambre 1", counter_sales=True)
    product = ProductFactory.create(organization=organization, name="Dorade")
    ProductPriceFactory.create(product=product, price=D("25.000"), valid_from=timezone.now() - dt.timedelta(days=5))
    batch = BatchFactory.create(organization=organization, product=product, number="SRC-1")
    inventory.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("30"),
        to_location=room,
    )
    customer = CustomerFactory.create(organization=organization, credit_limit=D("10000"))
    return organization, room, product, customer


def draft(setup, kg="10"):
    organization, room, product, customer = setup
    return services.create_sale(
        organization=organization,
        actor=None,
        customer=customer,
        location=room,
        lines=[{"product": product, "quantity": kg}],
    )


def test_issued_bl_takes_its_number_and_no_stock(setup):
    organization, room, _product, _customer = setup
    sale = services.issue_sale(sale=draft(setup), actor=UserFactory.create())

    assert sale.status == SaleStatus.DRAFT
    assert sale.delivery_status == DeliveryStatus.TO_DELIVER
    assert sale.number.startswith("BL-")
    assert stock.quantity_on_hand(organization, location_id=room.pk) == D("30.000")


def test_part_delivery_takes_only_the_kilos_delivered(setup):
    organization, room, _product, _customer = setup
    sale = services.issue_sale(sale=draft(setup), actor=None)
    line = sale.lines.get()

    done = services.deliver_sale(sale=sale, actor=None, lines=[{"line": line.pk, "quantity": "7"}])

    assert (done.status, done.delivery_status) == (SaleStatus.CONFIRMED, DeliveryStatus.PARTIAL)
    assert done.total == D("175.000")
    assert stock.quantity_on_hand(organization, location_id=room.pk) == D("23.000")


def test_not_delivered_moves_nothing(setup):
    organization, room, _product, _customer = setup
    sale = services.issue_sale(sale=draft(setup), actor=None)

    gone = services.cancel_delivery(sale=sale, actor=None, note="Fermé")

    assert gone.status == SaleStatus.CANCELLED
    assert stock.quantity_on_hand(organization, location_id=room.pk) == D("30.000")


def test_more_than_the_place_holds_is_refused_at_issue(setup):
    with pytest.raises(ValidationError) as refused:
        services.issue_sale(sale=draft(setup, kg="31"), actor=None)
    assert "lines.0.quantity" in refused.value.message_dict
