"""The lot that expires first leaves first, and expired lots are never sold nor loaded (D-296)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import selectors, services
from apps.inventory.models import LocationKind, MovementKind

from .factories import BatchFactory, StockLocationFactory

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def cold_room(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1")


@pytest.fixture
def truck(organization):
    return StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK, name="Camion 1")


@pytest.fixture
def product(organization):
    return ProductFactory.create(organization=organization, name="Loup")


def receive(organization, product, location, kg, *, days_ago=0, use_by_in=None):
    batch = BatchFactory.create(
        organization=organization,
        product=product,
        received_on=TODAY() - dt.timedelta(days=days_ago),
        use_by=None if use_by_in is None else TODAY() + dt.timedelta(days=use_by_in),
    )
    services.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )
    return batch


def take(organization, actor, product, quantity, from_location, **fields):
    return services.post_fifo_movements(
        organization=organization,
        actor=actor,
        product_id=product.pk,
        quantity=quantity,
        from_location=from_location,
        **{"kind": MovementKind.SALE, **fields},
    )


def split(movements):
    return [(movement.batch, movement.quantity) for movement in movements]


def test_the_lot_that_expires_first_leaves_first_even_when_received_later(organization, actor, product, cold_room):
    old_long = receive(organization, product, cold_room, "10", days_ago=3, use_by_in=10)
    recent_short = receive(organization, product, cold_room, "10", days_ago=1, use_by_in=2)
    no_date = receive(organization, product, cold_room, "10", days_ago=5)

    movements = take(organization, actor, product, "25", cold_room)

    assert split(movements) == [
        (recent_short, Decimal("10.000")),
        (old_long, Decimal("10.000")),
        (no_date, Decimal("5.000")),
    ]


def test_same_use_by_falls_back_to_the_oldest_receipt(organization, actor, product, cold_room):
    recent = receive(organization, product, cold_room, "10", days_ago=1, use_by_in=4)
    old = receive(organization, product, cold_room, "10", days_ago=2, use_by_in=4)

    assert split(take(organization, actor, product, "5", cold_room)) == [(old, Decimal("5.000"))]
    assert recent.pk != old.pk


def test_an_expired_lot_is_skipped_by_a_sale_and_the_refusal_says_why(organization, actor, product, cold_room):
    expired = receive(organization, product, cold_room, "10", days_ago=6, use_by_in=-1)
    good = receive(organization, product, cold_room, "4", days_ago=1, use_by_in=3)

    assert split(take(organization, actor, product, "3", cold_room)) == [(good, Decimal("3.000"))]
    with pytest.raises(ValidationError) as refused:
        take(organization, actor, product, "5", cold_room)
    assert "date limite" in refused.value.message_dict["quantity"][0]
    assert selectors.quantity_on_hand(organization, batch_id=expired.pk) == Decimal("10.000")


def test_the_use_by_day_itself_still_sells(organization, actor, product, cold_room):
    today = receive(organization, product, cold_room, "5", days_ago=2, use_by_in=0)

    assert split(take(organization, actor, product, "5", cold_room)) == [(today, Decimal("5.000"))]


def test_picking_an_expired_lot_by_hand_is_refused(organization, actor, product, cold_room):
    expired = receive(organization, product, cold_room, "10", days_ago=6, use_by_in=-1)
    receive(organization, product, cold_room, "10", days_ago=1, use_by_in=3)

    with pytest.raises(ValidationError) as refused:
        take(organization, actor, product, "2", cold_room, picks=[(expired.pk, Decimal("2"))])
    assert expired.number in refused.value.message_dict["quantity"][0]


def test_expired_kilos_still_go_to_a_loss_and_back_from_a_truck(organization, actor, product, cold_room, truck):
    receive(organization, product, truck, "6", days_ago=6, use_by_in=-1)

    back = take(organization, actor, product, "6", truck, kind=MovementKind.TRANSFER, to_location=cold_room)
    lost = take(organization, actor, product, "6", cold_room, kind=MovementKind.LOSS, reason="Date dépassée")

    assert sum(m.quantity for m in back) == sum(m.quantity for m in lost) == Decimal("6.000")


def test_a_truck_load_skips_expired_lots(organization, actor, product, cold_room, truck):
    receive(organization, product, cold_room, "10", days_ago=6, use_by_in=-1)

    with pytest.raises(ValidationError):
        take(
            organization,
            actor,
            product,
            "1",
            cold_room,
            kind=MovementKind.TRANSFER,
            to_location=truck,
            skip_expired=True,
        )


def test_pickers_and_the_driver_stock_leave_expired_lots_out(organization, product, cold_room, truck):
    receive(organization, product, cold_room, "10", days_ago=6, use_by_in=-1)
    good = receive(organization, product, cold_room, "4", days_ago=1, use_by_in=3)
    receive(organization, product, truck, "7", days_ago=6, use_by_in=-2)
    receive(organization, product, truck, "2", days_ago=1)

    assert [row.batch_id for row in selectors.product_batches(organization, product_id=product.pk)] == [good.pk]
    assert [
        row.batch_id
        for row in selectors.location_batches(organization, product_id=product.pk, location_id=cold_room.pk)
    ] == [good.pk]
    sellable = selectors.location_stock(organization, location_id=truck.pk, sellable_on=TODAY())
    assert [row["quantity"] for row in sellable] == [Decimal("2.000")]
