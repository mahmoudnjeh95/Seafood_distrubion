"""What a driver does is told to the office, what the office does for a driver is told to them (D-175)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.fleet import services as fleet
from apps.inventory import services as inventory
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.notifications import rules
from apps.notifications.models import Notification
from apps.partners import services as partners

pytestmark = pytest.mark.django_db


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def day():
    """A driver whose day runs on a truck with 20 kg of dorade in the cold room; an owner, a manager and an
    accountant in the office."""
    organization = OrganizationFactory.create()
    owner = MembershipFactory.create(organization=organization, role=Role.OWNER)
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    accountant = MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT)
    driver = MembershipFactory.create(
        organization=organization, role=Role.DRIVER, user=UserFactory.create(first_name="Sami", last_name="B.")
    )
    room = StockLocationFactory.create(organization=organization, name="Chambre froide 1")
    truck = fleet.create_truck(
        organization=organization, actor=owner.user, name="Camion 1", plate="101 TU 2001", driver=driver.user
    )
    product = ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")
    ProductPriceFactory.create(
        product=product, price=Decimal("28.000"), valid_from=timezone.now() - dt.timedelta(days=3)
    )
    batch = BatchFactory.create(organization=organization, product=product, received_on=timezone.localdate())
    inventory.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity="20", to_location=room
    )
    customer = partners.create_customer(
        organization=organization, actor=owner.user, name="Restaurant Le Port", credit_limit=Decimal("500.000")
    )
    api = client_for(driver)
    fleet.set_day_fund(
        organization=organization,
        actor=driver.user,
        driver=driver.user,
        date=timezone.localdate(),
        opening_cash=Decimal("50"),
    )
    assert api.post(reverse("my-day"), format="json").status_code == 201
    return {
        "organization": organization,
        "driver": driver,
        "api": api,
        "owner": client_for(owner),
        "owner_user": owner.user,
        "manager": client_for(manager),
        "accountant": client_for(accountant),
        "room": room,
        "truck": truck,
        "product": product,
        "customer": customer,
    }


def load(day, kg="12"):
    return inventory.create_transfer(
        organization=day["organization"],
        actor=day["owner_user"],
        from_location=day["room"],
        to_location=day["truck"].location,
        transferred_on=timezone.localdate(),
        lines=[{"product": day["product"], "quantity": Decimal(kg)}],
        validate=True,
    )


def told(client):
    answer = client.get(reverse("my-notifications"))
    assert answer.status_code == 200
    return answer.json()


def kinds(client):
    return [row["kind"] for row in told(client)["results"]]


def test_the_office_is_told_the_driver_started_the_day(day):
    shown = told(day["owner"])

    assert shown["unread"] == 1
    assert shown["results"][0]["kind"] == "day_started"
    assert shown["results"][0]["params"] == {"driver": "Sami B.", "truck": "Camion 1"}
    assert shown["results"][0]["link"] == "/journees"
    assert shown["results"][0]["read"] is False
    assert kinds(day["manager"]) == ["day_started"]
    # The accountant only reads the books; the driver is not told what they did themselves.
    assert told(day["accountant"]) == {"unread": 0, "results": []}
    assert kinds(day["api"]) == []


def test_a_load_tells_the_driver_and_a_sale_from_the_truck_tells_the_office(day):
    transfer = load(day)

    driver_side = told(day["api"])
    assert driver_side["unread"] == 1
    assert driver_side["results"][0]["kind"] == "load_validated"
    assert driver_side["results"][0]["params"] == {"number": transfer.number, "truck": "Camion 1"}
    assert driver_side["results"][0]["link"] == "/stock"
    # The owner validated the load: they are not told of it.
    assert "load_validated" not in kinds(day["owner"])

    sold = day["api"].post(
        reverse("sale-list"),
        {
            "customer": day["customer"].pk,
            "location": day["truck"].location_id,
            "confirm_now": True,
            "amount_paid": "56.000",
            "payment_method": "cash",
            "lines": [{"product": day["product"].pk, "quantity": "2"}],
        },
        format="json",
    )

    assert sold.status_code == 201
    sale = told(day["owner"])["results"][0]
    assert sale["kind"] == "sale_confirmed"
    assert sale["params"]["customer"] == "Restaurant Le Port"
    assert sale["params"]["total"] == "56.000"
    assert sale["link"] == f"/ventes/{sold.json()['id']}"


def test_the_day_sent_and_its_review_go_both_ways(day):
    load(day)
    assert day["api"].post(reverse("my-day-closing"), {"counted_cash": "40.000"}, format="json").status_code == 201

    sent = told(day["manager"])["results"][0]
    assert (sent["kind"], sent["params"]["difference"]) == ("day_sent", "-10.000")

    closing = day["owner"].get(reverse("day-closing-list")).json()[0]
    asked = day["owner"].post(
        reverse("day-closing-justification", args=[closing["id"]]), {"reason": "Expliquez les 10 DT"}, format="json"
    )
    assert asked.status_code == 200

    asked_row = told(day["api"])["results"][0]
    assert asked_row["kind"] == "day_justification"
    assert asked_row["params"]["reason"] == "Expliquez les 10 DT"
    assert asked_row["link"] == "/cloture"


def test_each_reader_marks_their_own_notifications_read(day):
    load(day)
    first = told(day["owner"])["results"][0]

    read = day["owner"].post(reverse("my-notifications-read"), {"ids": [first["id"]]}, format="json")

    assert read.json() == {"unread": 0}
    assert told(day["owner"])["results"][0]["read"] is True
    # The manager has not read it yet.
    assert told(day["manager"])["unread"] == 1
    assert day["manager"].post(reverse("my-notifications-read"), {"all": True}, format="json").json() == {"unread": 0}
    # The driver cannot mark the office's notifications: they are not theirs to see.
    assert day["api"].post(reverse("my-notifications-read"), {"ids": [first["id"]]}, format="json").json() == {
        "unread": 1
    }
    assert day["api"].post(reverse("my-notifications-read"), {}, format="json").status_code == 400


def test_another_company_is_told_nothing(day):
    other = client_for(MembershipFactory.create(role=Role.OWNER))

    assert told(other) == {"unread": 0, "results": []}


def test_a_broken_notification_never_refuses_the_action(day, monkeypatch):
    def broken(entry):
        raise RuntimeError("boom")

    monkeypatch.setitem(rules.RULES, "transfer.validated", broken)

    transfer = load(day)

    assert transfer.status == "validated"
    assert not Notification.objects.filter(kind="load_validated").exists()


def test_a_bl_delivered_in_part_from_the_phone_tells_the_office_and_its_change_tells_the_driver(day):
    """The BL of a load (D-178): the office changing it tells the driver, a part delivery tells the office."""
    inventory.create_transfer(
        organization=day["organization"],
        actor=day["owner_user"],
        from_location=day["room"],
        to_location=day["truck"].location,
        transferred_on=timezone.localdate(),
        lines=[],
        deliveries=[{"customer": day["customer"], "lines": [{"product": day["product"], "quantity": "6"}]}],
        validate=True,
    )
    (bl,) = day["api"].get(reverse("my-deliveries")).json()
    changed = day["owner"].put(
        reverse("sale-detail", args=[bl["id"]]),
        {
            "customer": day["customer"].pk,
            "location": day["truck"].location_id,
            "lines": [{"product": day["product"].pk, "quantity": "5", "unit_price": "28.000"}],
        },
        format="json",
    )
    assert changed.status_code == 200
    assert "bl_changed" in kinds(day["api"])
    line = changed.json()["lines"][0]

    delivered = day["api"].post(
        reverse("my-delivery-deliver", args=[bl["id"]]),
        {"lines": [{"line": line["id"], "quantity": "4"}], "note": "Le client a pris 4 kg"},
        format="json",
    )

    assert delivered.status_code == 200
    body = delivered.json()
    assert (body["status"], body["delivery_status"], body["version"], body["total"]) == (
        "confirmed",
        "partial",
        3,
        "112.000",
    )
    office = told(day["owner"])["results"][0]
    assert office["kind"] == "delivery_partial"
    assert office["params"]["note"] == "Le client a pris 4 kg"
    assert day["api"].get(reverse("my-deliveries")).json() == []
