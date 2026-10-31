"""A driver's sale is dated when it was made, as the phone says, once the server has checked it (D-133)."""

import datetime as dt
from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from django.utils.dateparse import parse_datetime
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.dayclose import selectors, services
from apps.fleet import services as fleet
from apps.inventory import selectors as stock
from apps.inventory import services as inventory
from apps.inventory.models import MovementKind, StockMovement
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners import services as partners
from apps.sales import receivables
from apps.sales.models import Sale, SaleLineBatch

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate()
YESTERDAY = TODAY - dt.timedelta(days=1)


def at(day, hour):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hour, 0)))


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def receive(road, kg, *, on, received_on=None):
    """A new lot of dorade in the cold room, received (and dated) on `on`."""
    batch = BatchFactory.create(
        organization=road["organization"], product=road["product"], received_on=received_on or on
    )
    inventory.post_movement(
        organization=road["organization"],
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=kg,
        to_location=road["room"],
        occurred_at=at(on, 7) if on != TODAY else None,
    )
    return batch


def move(road, kg, *, on, back=False):
    """Load `kg` of dorade into the truck on `on` (or bring them back to the cold room)."""
    places = (road["truck"].location, road["room"]) if back else (road["room"], road["truck"].location)
    inventory.create_transfer(
        organization=road["organization"],
        actor=None,
        from_location=places[0],
        to_location=places[1],
        transferred_on=on,
        lines=[{"product": road["product"], "quantity": Decimal(kg)}],
        validate=True,
    )


@pytest.fixture
def road():
    """A driver and their usual truck, with nothing loaded yet. Dorade cost 28 DT yesterday and 31 DT today."""
    organization = OrganizationFactory.create()
    actor = UserFactory.create()
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    office = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    room = StockLocationFactory.create(organization=organization, name="Chambre froide 1")
    truck = fleet.create_truck(
        organization=organization, actor=actor, name="Camion 1", plate="101 TU 2001", driver=driver.user
    )
    product = ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")
    ProductPriceFactory.create(product=product, price=Decimal("28.000"), valid_from=at(TODAY - dt.timedelta(days=5), 0))
    ProductPriceFactory.create(product=product, price=Decimal("31.000"), valid_from=at(TODAY, 0))
    customer = partners.create_customer(
        organization=organization, actor=actor, name="Restaurant Le Port", credit_limit=Decimal("5000.000")
    )
    return {
        "api": client_for(driver),
        "office": client_for(office),
        "organization": organization,
        "actor": actor,
        "driver": driver,
        "product": product,
        "room": room,
        "truck": truck,
        "customer": customer,
    }


@pytest.fixture
def loaded(road):
    """12 kg loaded yesterday; the driver started yesterday's day and today's with 50 DT."""
    road["batch"] = receive(road, "20", on=YESTERDAY)
    move(road, "12", on=YESTERDAY)
    for day in (YESTERDAY, TODAY):
        road[day] = fleet.open_driver_day(
            organization=road["organization"],
            actor=road["driver"].user,
            truck=road["truck"],
            opening_cash=Decimal("50"),
            date=day,
        )
    return road


def sell(road, kg, *, made_at=None, paid="0", location=None, **fields):
    body = {
        "customer": road["customer"].pk,
        "location": location or road["truck"].location_id,
        "confirm_now": True,
        "amount_paid": paid,
        "payment_method": "cash",
        "lines": [{"product": road["product"].pk, "quantity": kg}],
        **fields,
    }
    if made_at is not None:
        body["sold_at"] = made_at.isoformat()
    return road["api"].post(reverse("sale-list"), body, format="json")


def sold_at(response) -> dt.datetime:
    moment = parse_datetime(response.json()["sold_at"])
    assert moment is not None
    return moment


def test_a_sale_made_yesterday_and_sent_today_is_yesterdays_sale_everywhere(loaded):
    """Made without connection yesterday at 15:00, sent from the phone's queue today: yesterday's date and
    price, yesterday's day, and the truck starts today with what was really left."""
    made_at = at(YESTERDAY, 15)

    response = sell(loaded, "3", made_at=made_at, paid="50.000")

    assert response.status_code == 201
    body = response.json()
    assert sold_at(response) == made_at
    assert (body["lines"][0]["unit_price"], body["total"]) == ("28.000", "84.000")  # yesterday's price, not 31
    sale = Sale.objects.get(pk=body["id"])
    assert timezone.localtime(sale.confirmed_at).date() == TODAY  # when it reached the server stays known

    # The ledger: the kilos left the truck yesterday (when it happened), posted today (when it was recorded).
    movement = StockMovement.objects.get(kind=MovementKind.SALE)
    assert movement.occurred_at == made_at
    assert timezone.localtime(movement.created_at).date() == TODAY

    # The day it belongs to: yesterday's figures take it, today's do not, and today opens with 9 kg, not 12.
    organization = loaded["organization"]
    yesterday = selectors.day_summary(organization, loaded[YESTERDAY])
    assert (yesterday["sales_count"], yesterday["sales_total"], yesterday["cash_received"]) == (
        1,
        Decimal("84.000"),
        Decimal("50.000"),
    )
    assert yesterday["expected_cash"] == Decimal("100.000")
    assert (yesterday["products"][0]["loaded"], yesterday["products"][0]["sold"]) == (Decimal("12"), Decimal("3"))
    today = loaded["api"].get(reverse("my-day-summary")).json()["summary"]
    assert (today["sales_count"], today["expected_cash"]) == (0, "50.000")
    assert today["products"][0] | {"product_id": 0} == {
        "product_id": 0,
        "product_name": "Dorade royale",
        "opening": "9.000",
        "loaded": "0.000",
        "sold": "0.000",
        "lost": "0.000",
        "returned": "0.000",
        "remaining": "9.000",
        "unexplained": "0.000",
    }

    # Lists and what the customer owes follow the same date.
    listed = lambda day: loaded["office"].get(reverse("sale-list"), {"date_from": day, "date_to": day}).json()  # noqa: E731
    assert [row["id"] for row in listed(YESTERDAY)["results"]] == [sale.pk]
    assert listed(TODAY)["results"] == []
    (owed,) = receivables.sale_receivables(organization, customer_id=loaded["customer"].pk)
    assert (owed.document_date, owed.outstanding) == (YESTERDAY, Decimal("34.000"))


def test_an_online_sale_without_a_time_is_dated_now_as_before(loaded):
    before = timezone.now()

    response = sell(loaded, "2", paid="62.000")

    assert response.status_code == 201
    body = response.json()
    assert before <= sold_at(response) <= timezone.now()
    assert body["lines"][0]["unit_price"] == "31.000"  # today's price
    today = loaded["api"].get(reverse("my-day-summary")).json()["summary"]
    assert (today["sales_count"], today["products"][0]["opening"], today["products"][0]["sold"]) == (
        1,
        "12.000",
        "2.000",
    )


@pytest.mark.parametrize("minutes", [-4, 4])
def test_a_phone_a_few_minutes_off_changes_nothing(loaded, minutes):
    """Within 5 minutes of the server's clock, before or after, the server's own time dates the sale."""
    before = timezone.now()

    response = sell(loaded, "1", made_at=before + dt.timedelta(minutes=minutes), paid="31.000")

    assert response.status_code == 201
    assert before <= sold_at(response) <= timezone.now()
    assert response.json()["lines"][0]["unit_price"] == "31.000"


@pytest.mark.parametrize("ahead", [dt.timedelta(minutes=6), dt.timedelta(days=1)])
def test_a_time_in_the_future_is_refused(loaded, ahead):
    response = sell(loaded, "1", made_at=timezone.now() + ahead, paid="31.000")

    assert response.status_code == 400
    assert "dans le futur" in response.json()["sold_at"][0]
    assert not Sale.objects.exists()
    assert not StockMovement.objects.filter(kind=MovementKind.SALE).exists()


def approve(road, day):
    closing = services.submit_day_closing(driver_day=road[day], actor=road["driver"].user)
    return services.approve_day_closing(closing=closing, actor=road["actor"], office_counted_cash=Decimal("50.000"))


def test_a_sale_of_a_day_the_office_approved_is_refused_in_plain_words(loaded):
    approve(loaded, YESTERDAY)

    late = sell(loaded, "3", made_at=at(YESTERDAY, 15), paid="84.000")

    assert late.status_code == 403
    assert late.json()["detail"] == (
        f"Votre journée du {YESTERDAY:%d/%m/%Y} est approuvée par le bureau : elle est fermée, plus rien ne s'y ajoute."
    )
    assert not Sale.objects.exists()
    # Today is another day: it is not approved, the driver still sells.
    assert sell(loaded, "1", paid="31.000").status_code == 201


def test_a_late_sale_enters_a_day_sent_but_not_approved_and_an_earlier_day_than_an_approved_one(loaded):
    """Only the sale's own day counts: sent to the office but not approved, it still takes the sale; and
    today being approved does not close yesterday."""
    services.submit_day_closing(driver_day=loaded[YESTERDAY], actor=loaded["driver"].user)
    approve(loaded, TODAY)

    late = sell(loaded, "3", made_at=at(YESTERDAY, 15), paid="84.000")

    assert late.status_code == 201
    assert sell(loaded, "1", paid="31.000").status_code == 403  # today is approved


def test_a_sale_already_recorded_is_answered_before_any_check_of_its_time(loaded):
    """D-129 kept: the phone lost the answer and sends the sale again after the office approved its day."""
    client_uuid = str(uuid4())
    made_at = at(YESTERDAY, 15)
    first = sell(loaded, "3", made_at=made_at, paid="84.000", client_uuid=client_uuid)
    assert first.status_code == 201
    approve(loaded, YESTERDAY)

    retry = sell(loaded, "3", made_at=made_at, paid="84.000", client_uuid=client_uuid)
    with_a_wrong_clock = sell(
        loaded, "3", made_at=timezone.now() + dt.timedelta(days=2), paid="84.000", client_uuid=client_uuid
    )

    assert (retry.status_code, retry.json()["id"]) == (201, first.json()["id"])
    assert (with_a_wrong_clock.status_code, with_a_wrong_clock.json()["id"]) == (201, first.json()["id"])
    assert Sale.objects.count() == 1


def test_the_truck_is_the_one_the_driver_had_that_day(loaded):
    """The truck is chosen per day (D-042): yesterday the driver was on Camion 2, so a sale of yesterday from
    Camion 1 is refused, and one from Camion 2 is taken although Camion 1 is today's truck."""
    organization = loaded["organization"]
    other = fleet.create_truck(organization=organization, actor=loaded["actor"], name="Camion 2", plate="102 TU 2002")
    fleet.assign_truck(
        organization=organization, actor=loaded["actor"], truck=other, driver=loaded["driver"].user, date=YESTERDAY
    )
    inventory.create_transfer(
        organization=organization,
        actor=None,
        from_location=loaded["room"],
        to_location=other.location,
        transferred_on=YESTERDAY,
        lines=[{"product": loaded["product"], "quantity": Decimal("4")}],
        validate=True,
    )

    wrong = sell(loaded, "1", made_at=at(YESTERDAY, 15), paid="28.000")
    right = sell(loaded, "1", made_at=at(YESTERDAY, 15), paid="28.000", location=other.location_id)

    assert wrong.status_code == 403
    assert wrong.json()["detail"] == (
        f"Ce camion n'était pas le vôtre le {YESTERDAY:%d/%m/%Y} : la vente n'est pas enregistrée."
    )
    assert right.status_code == 201
    assert right.json()["location"]["name"] == "Camion 2"
    # Today the truck is Camion 1 again: Camion 2 is refused for a sale made now.
    assert sell(loaded, "1", paid="31.000", location=other.location_id).status_code == 403


def test_a_sale_of_a_day_the_driver_never_started_is_taken_and_belongs_to_no_closing(road):
    """Starting the day needs a connection, selling does not: a driver without signal all day never started it.
    The sale is still dated on its day, from the driver's truck of that day; no day closing holds it."""
    receive(road, "20", on=YESTERDAY)
    move(road, "12", on=YESTERDAY)
    today = fleet.open_driver_day(
        organization=road["organization"],
        actor=road["driver"].user,
        truck=road["truck"],
        opening_cash=Decimal("0"),
        date=TODAY,
    )

    response = sell(road, "3", made_at=at(YESTERDAY, 15), paid="84.000")

    assert response.status_code == 201
    assert timezone.localtime(sold_at(response)).date() == YESTERDAY
    summary = selectors.day_summary(road["organization"], today)
    assert (summary["sales_count"], summary["expected_cash"]) == (0, Decimal("0.000"))
    assert summary["products"][0]["opening"] == Decimal("9.000")


def test_kilos_that_were_not_on_the_truck_that_day_are_refused(loaded):
    """The truck was emptied last night and loaded again this morning: the 12 kg it holds now were not there
    yesterday, so a sale dated yesterday cannot take them (yesterday would end below zero)."""
    move(loaded, "12", on=YESTERDAY, back=True)
    move(loaded, "12", on=TODAY)

    late = sell(loaded, "3", made_at=at(YESTERDAY, 15), paid="84.000")

    assert late.status_code == 400
    assert late.json()["lines.0.quantity"] == [
        f"Stock insuffisant à cette date : « Camion 1 » n'a gardé que 0.000 kg de ce produit depuis le "
        f"{YESTERDAY:%d/%m/%Y}."
    ]
    assert not Sale.objects.exists()
    assert sell(loaded, "3", paid="93.000").status_code == 201  # sold now, the same kilos are there


def test_kilos_sold_or_given_back_since_are_no_longer_there_for_a_late_sale(loaded):
    """12 kg yesterday, 8 brought back in the evening: 4 kg have stayed since, whatever was loaded today."""
    move(loaded, "8", on=YESTERDAY, back=True)
    move(loaded, "8", on=TODAY)

    assert sell(loaded, "5", made_at=at(YESTERDAY, 15), paid="0").status_code == 400
    assert sell(loaded, "4", made_at=at(YESTERDAY, 15), paid="0").status_code == 201
    assert (
        stock.location_stock_before(loaded["organization"], location_id=loaded["truck"].location_id, day=TODAY) == []
    )  # yesterday ends at zero, not below


def test_a_late_sale_takes_the_lot_that_was_on_the_truck_that_day(loaded):
    """An older lot loaded today would leave first by FIFO, but it was not on the truck yesterday: the late
    sale takes yesterday's lot, so the profit of each lot stays right."""
    older = receive(loaded, "10", on=TODAY, received_on=YESTERDAY - dt.timedelta(days=3))
    # Bring the cold room's rest of yesterday's lot aside so today's load is the older lot only.
    inventory.post_movement(
        organization=loaded["organization"],
        actor=None,
        kind=MovementKind.ADJUSTMENT,
        batch=loaded["batch"],
        quantity="8",
        from_location=loaded["room"],
        reason="Test",
    )
    move(loaded, "10", on=TODAY)

    late = sell(loaded, "3", made_at=at(YESTERDAY, 15), paid="0")
    now = sell(loaded, "3", paid="0")

    assert (late.status_code, now.status_code) == (201, 201)
    lots = dict(SaleLineBatch.objects.values_list("line__sale_id", "batch_id"))
    assert lots == {late.json()["id"]: loaded["batch"].pk, now.json()["id"]: older.pk}
