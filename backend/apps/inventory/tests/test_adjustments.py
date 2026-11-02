import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.inventory import selectors, services
from apps.inventory.models import LocationKind, MovementKind, StockMovement

from .factories import BatchFactory, StockLocationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def cold_room(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1")


@pytest.fixture
def truck(organization):
    return StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK, name="Camion 1")


@pytest.fixture
def dorade(organization):
    return ProductFactory.create(organization=organization, name="Dorade royale")


def receive(organization, product, location, kg, cost, *, days_ago=0):
    batch = BatchFactory.create(
        organization=organization,
        product=product,
        unit_cost=cost,
        received_on=timezone.localdate() - dt.timedelta(days=days_ago),
    )
    services.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )
    return batch


def adjust(organization, batch, location, *, add, quantity, reason="Erreur de pesée"):
    return services.adjust_stock(
        organization=organization,
        actor=None,
        location=location,
        batch=batch,
        add=add,
        quantity=quantity,
        reason=reason,
    )


def average(organization, product):
    return selectors.average_purchase_cost(organization, product_id=product.pk)


def test_adding_kilos_keeps_the_lot_cost_and_the_average_is_worked_out_again(organization, cold_room, dorade):
    old = receive(organization, dorade, cold_room, "10", "20.000", days_ago=3)
    receive(organization, dorade, cold_room, "30", "28.000", days_ago=1)
    assert average(organization, dorade) == Decimal("26.000")

    movement = adjust(organization, old, cold_room, add=True, quantity="10")

    # (20 x 20 + 30 x 28) / 50
    assert (movement.kind, movement.to_location, movement.from_location) == (MovementKind.ADJUSTMENT, cold_room, None)
    assert (movement.unit_cost, movement.reason) == (Decimal("20.000"), "Erreur de pesée")
    assert average(organization, dorade) == Decimal("24.800")


def test_removing_kilos_moves_the_average_towards_what_is_left(organization, cold_room, dorade):
    old = receive(organization, dorade, cold_room, "10", "20.000", days_ago=3)
    new = receive(organization, dorade, cold_room, "30", "28.000", days_ago=1)

    adjust(organization, new, cold_room, add=False, quantity="30", reason="Lot mal pesé")

    assert selectors.quantity_on_hand(organization, product_id=dorade.pk) == Decimal("10.000")
    assert average(organization, dorade) == Decimal("20.000")
    assert selectors.quantity_on_hand(organization, location_id=cold_room.pk, batch_id=old.pk) == Decimal("10.000")


def test_an_adjustment_needs_a_reason_and_never_takes_more_than_the_place_holds(organization, cold_room, dorade):
    batch = receive(organization, dorade, cold_room, "10", "20.000")

    with pytest.raises(ValidationError) as no_reason:
        adjust(organization, batch, cold_room, add=True, quantity="1", reason="  ")
    assert list(no_reason.value.message_dict) == ["reason"]

    with pytest.raises(ValidationError) as too_much:
        adjust(organization, batch, cold_room, add=False, quantity="10.001")
    assert list(too_much.value.message_dict) == ["quantity"]

    assert selectors.quantity_on_hand(organization, product_id=dorade.pk) == Decimal("10.000")
    assert StockMovement.objects.filter(kind=MovementKind.ADJUSTMENT).count() == 0


def test_an_archived_place_is_refused_on_the_location_field(organization, cold_room, dorade):
    batch = receive(organization, dorade, cold_room, "10", "20.000")
    cold_room.is_active = False
    cold_room.save(update_fields=["is_active"])

    with pytest.raises(ValidationError) as caught:
        adjust(organization, batch, cold_room, add=True, quantity="1")

    assert list(caught.value.message_dict) == ["location"]


def client_for(role, organization):
    membership = MembershipFactory.create(role=role, organization=organization)
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def test_the_office_adjusts_from_the_product_page_and_gets_the_new_average(organization, cold_room, dorade):
    client = client_for(Role.OWNER, organization)
    old = receive(organization, dorade, cold_room, "10", "20.000", days_ago=3)
    receive(organization, dorade, cold_room, "30", "28.000", days_ago=1)

    response = client.post(
        reverse("stock-adjustment"),
        {
            "location": cold_room.pk,
            "batch": old.pk,
            "direction": "add",
            "quantity": "10",
            "reason": "Trouvé en chambre",
        },
        format="json",
    )

    assert response.status_code == 201
    assert (response.json()["quantity"], response.json()["average_cost"]) == ("50.000", "24.800")


def test_the_api_refuses_unknown_places_and_lots_and_drivers_cannot_adjust(organization, cold_room, dorade):
    batch = receive(organization, dorade, cold_room, "10", "20.000")
    owner = client_for(Role.OWNER, organization)

    response = owner.post(
        reverse("stock-adjustment"),
        {"location": 999999, "batch": 999999, "direction": "remove", "quantity": "1", "reason": "Test"},
        format="json",
    )
    assert response.status_code == 400
    assert set(response.json()) == {"location", "batch"}

    driver = client_for(Role.DRIVER, organization)
    body = {"location": cold_room.pk, "batch": batch.pk, "direction": "add", "quantity": "1", "reason": "Test"}
    assert driver.post(reverse("stock-adjustment"), body, format="json").status_code == 403
