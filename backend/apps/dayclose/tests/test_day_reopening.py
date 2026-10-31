"""Sending the closing closes a driver's day, and a load validated that date opens it again (D-134): what is
refused meanwhile, what the reopened day adds up to, the cash already handed over, and the record of the send
that was undone. A sale still counts on the day when it was made before the send (D-133)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.dayclose import selectors
from apps.dayclose.models import DayReopening
from apps.fleet import services as fleet
from apps.fleet.models import DriverDay
from apps.inventory import services as inventory
from apps.inventory.models import LossReason, MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners import services as partners
from apps.sales.models import Sale

pytestmark = pytest.mark.django_db

# The date everything happens on; the clock of each test is set by hand (`clock`).
DAY = timezone.localdate() - dt.timedelta(days=2)
DAY_BEFORE = DAY - dt.timedelta(days=1)
NEXT_DAY = DAY + dt.timedelta(days=1)
CLOSED = "Votre journée est clôturée : elle rouvre quand le bureau recharge votre camion."


def at(hour, minute=0, *, day=DAY):
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hour, minute)))


@pytest.fixture
def clock(monkeypatch):
    """Set the server's clock: `clock(at(10))`."""

    def set_to(moment):
        monkeypatch.setattr(timezone, "now", lambda: moment)

    return set_to


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def load(road, kg, *, on=None, back=False, truck=None):
    """Load `kg` of dorade into the truck (or bring them back to the cold room), today or on an earlier day."""
    place = (truck or road["truck"]).location
    places = (place, road["room"]) if back else (road["room"], place)
    return inventory.create_transfer(
        organization=road["organization"],
        actor=road["office_user"],
        from_location=places[0],
        to_location=places[1],
        transferred_on=on or timezone.localdate(),
        lines=[{"product": road["product"], "quantity": Decimal(kg)}],
        validate=True,
    )


@pytest.fixture
def road(clock):
    """A driver whose truck kept 3 kg of dorade from the day before and got 12 kg more at 08:00. Dorade is 28 DT.
    The driver started the day at 08:30 with 50 DT. The clock is left at 08:30."""
    clock(at(7))
    organization = OrganizationFactory.create()
    actor = UserFactory.create()
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    office = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    room = StockLocationFactory.create(organization=organization, name="Chambre froide 1")
    truck = fleet.create_truck(
        organization=organization, actor=actor, name="Camion 1", plate="101 TU 2001", driver=driver.user
    )
    product = ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")
    ProductPriceFactory.create(product=product, price=Decimal("28.000"), valid_from=at(0, day=DAY - dt.timedelta(5)))
    batch = BatchFactory.create(organization=organization, product=product, received_on=DAY_BEFORE)
    inventory.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity="40",
        to_location=room,
        occurred_at=at(7, day=DAY_BEFORE),
    )
    customer = partners.create_customer(
        organization=organization, actor=actor, name="Restaurant Le Port", credit_limit=Decimal("5000.000")
    )
    road = {
        "api": client_for(driver),
        "office": client_for(office),
        "office_user": office.user,
        "organization": organization,
        "driver": driver,
        "product": product,
        "room": room,
        "truck": truck,
        "customer": customer,
    }
    load(road, "3", on=DAY_BEFORE)
    clock(at(8))
    load(road, "12")
    clock(at(8, 30))
    organization, driver = road["organization"], road["driver"]
    fleet.set_day_fund(
        organization=organization,
        actor=driver.user,
        driver=driver.user,
        date=timezone.localdate(),
        opening_cash=Decimal("50"),
    )
    assert road["api"].post(reverse("my-day"), format="json").status_code == 201
    return road


def sell(road, kg, paid="0", *, made_at=None):
    body = {
        "customer": road["customer"].pk,
        "location": road["truck"].location_id,
        "confirm_now": True,
        "amount_paid": paid,
        "payment_method": "cash",
        "lines": [{"product": road["product"].pk, "quantity": kg}],
    }
    if made_at is not None:
        body["sold_at"] = made_at.isoformat()
    return road["api"].post(reverse("sale-list"), body, format="json")


def close(road, counted=None):
    """The driver sends the day; the office then counts `counted` when given (D-213)."""
    sent = road["api"].post(reverse("my-day-closing"), {}, format="json")
    if counted is not None and sent.status_code == 201:
        assert count(road, counted).status_code == 200
    return sent


def count(road, counted):
    return road["office"].post(
        reverse("day-closing-count", args=[office_row(road)["id"]]),
        {"office_counted_cash": counted},
        format="json",
    )


def driver_day(road):
    return DriverDay.objects.select_related("truck__location", "driver").get(
        organization=road["organization"], date=DAY
    )


def stock_line(road):
    """The dorade line of the driver's day, computed now from the records."""
    (line,) = selectors.day_summary(road["organization"], driver_day(road))["products"]
    return {name: str(value) for name, value in line.items() if name not in ("product_id", "product_name")}


def my_day(road):
    return road["api"].get(reverse("my-day-summary")).json()


def office_row(road):
    (row,) = road["office"].get(reverse("day-closing-list")).json()
    return row


def office_detail(road):
    return road["office"].get(reverse("day-closing-detail", args=[office_row(road)["id"]])).json()


def morning_sent(road, clock, counted="150.000"):
    """5 kg sold at 10:00 (140 DT, 100 in cash), the closing sent at 12:00: 150 DT expected."""
    clock(at(10))
    assert sell(road, "5", "100.000").status_code == 201
    clock(at(12))
    assert close(road, counted).status_code == 201


# ---- A sent day is closed ----


def test_a_sale_made_after_the_day_was_sent_is_refused_and_one_made_before_is_taken(road, clock):
    morning_sent(road, clock)

    clock(at(12, 5))
    now = sell(road, "1", "28.000")
    clock(at(13))
    kept_on_the_phone = sell(road, "1", "28.000", made_at=at(12, 30))  # made after the send, received later

    for refused in (now, kept_on_the_phone):
        assert refused.status_code == 403
        assert refused.json()["detail"] == CLOSED
    assert Sale.objects.count() == 1
    # A sale made before the send is still the day's (sent, not approved).
    assert sell(road, "1", "28.000", made_at=at(11)).status_code == 201


def test_the_driver_cannot_start_another_day_on_the_same_date(road, clock):
    morning_sent(road, clock)
    first = road["api"].get(reverse("my-day")).json()

    clock(at(12, 10))
    again = road["api"].post(reverse("my-day"), {"opening_cash": "20"}, format="json").json()

    assert (again["id"], again["opening_cash"]) == (first["id"], "50.000")
    assert again["ended_at"] is not None  # still closed
    assert "number" not in again
    assert DriverDay.objects.count() == 1
    assert sell(road, "1", "28.000").status_code == 403


# ---- A load that date opens it again ----


def test_a_load_validated_that_date_opens_the_sent_day_again(road, clock):
    """The count of the first send (150 DT) went to the office: the driver now holds only what comes in after."""
    morning_sent(road, clock)

    clock(at(13))
    load(road, "4")

    assert road["api"].get(reverse("my-day")).json()["ended_at"] is None
    assert my_day(road)["closing"]["status"] == "reopened"
    clock(at(14))
    assert sell(road, "2", "56.000").status_code == 201
    summary = my_day(road)["summary"]
    assert (summary["sales_count"], summary["sales_total"]) == (2, "196.000")
    assert (summary["handed_over"], summary["expected_cash"]) == ("150.000", "56.000")  # 50 + 156 - 150

    clock(at(18))
    resent = close(road, "56.000")

    assert resent.status_code == 201
    closing = resent.json()["closing"]
    assert (closing["status"], closing["expected_cash"]) == ("submitted", "56.000")
    assert timezone.localtime(driver_day(road).ended_at) == at(18)
    assert sell(road, "1", "28.000").status_code == 403  # closed again


def test_a_reopened_day_balances_its_stock_over_the_whole_date(road, clock):
    morning_sent(road, clock)
    clock(at(13))
    load(road, "4")
    clock(at(14))
    assert sell(road, "2", "56.000").status_code == 201
    inventory.record_loss(
        organization=road["organization"],
        actor=road["driver"].user,
        location=road["truck"].location,
        product=road["product"],
        quantity="1",
        reason=LossReason.values[0],
        lost_on=DAY,
    )
    clock(at(16))
    load(road, "2", back=True)

    line = stock_line(road)

    assert line == {
        "opening": "3.000",
        "loaded": "16.000",
        "sold": "7.000",
        "lost": "1.000",
        "returned": "2.000",
        "remaining": "9.000",
        "unexplained": "0.000",
    }
    # Sent again, the day keeps these figures, also once the truck moves on the next morning.
    clock(at(18))
    sent = close(road, "56.000").json()["summary"]["products"][0]
    assert (sent["loaded"], sent["sold"], sent["remaining"], sent["unexplained"]) == (
        "16.000",
        "7.000",
        "9.000",
        "0.000",
    )
    clock(at(9, day=NEXT_DAY))
    load(road, "5")
    assert stock_line(road) == line


def test_the_office_cannot_check_a_reopened_day_until_it_is_sent_again(road, clock):
    clock(at(12))
    assert close(road, "50.000").status_code == 201
    clock(at(13))
    load(road, "4")
    row = office_row(road)

    approved = road["office"].post(reverse("day-closing-approve", args=[row["id"]]))
    asked = road["office"].post(
        reverse("day-closing-justification", args=[row["id"]]), {"reason": "Pourquoi ?"}, format="json"
    )

    assert row["status"] == "reopened"
    assert (approved.status_code, asked.status_code) == (400, 400)
    assert len(road["office"].get(reverse("day-closing-list"), {"status": "reopened"}).json()) == 1
    assert road["office"].get(reverse("day-closing-list"), {"status": "submitted"}).json() == []
    clock(at(18))
    assert close(road, "0.000").status_code == 201  # the 50 DT of the first send are with the office
    assert road["office"].post(reverse("day-closing-approve", args=[row["id"]])).json()["status"] == "approved"


def test_an_approved_day_is_reopened_by_a_load_and_its_approval_stays_on_record(road, clock):
    morning_sent(road, clock, counted="140.000")
    row = office_row(road)
    clock(at(12, 30))
    approved = road["office"].post(
        reverse("day-closing-approve", args=[row["id"]]), {"note": "Il manque 10 DT"}, format="json"
    )
    assert approved.json()["status"] == "approved"

    clock(at(13))
    transfer = load(road, "4")

    detail = office_detail(road)
    assert (detail["status"], detail["reviewed_at"], detail["reviewed_by_name"]) == ("reopened", None, "")
    (undone,) = detail["reopenings"]
    office = road["office_user"]
    assert undone == {
        "status": "approved",
        "expected_cash": "150.000",
        "counted_cash": "140.000",
        "difference": "-10.000",
        "counted_purchase_cash": None,
        "driver_note": "",
        "submitted_at": timezone.localtime(at(12)).isoformat(),
        "reviewed_by_name": f"{office.first_name} {office.last_name}".strip() or office.username,
        "reviewed_at": timezone.localtime(at(12, 30)).isoformat(),
        "reopened_at": timezone.localtime(at(13)).isoformat(),
        "load_number": transfer.number,
    }
    # The figures of the undone send are kept as they were.
    kept = DayReopening.objects.get()
    assert (kept.summary["sales_count"], kept.summary["expected_cash"]) == (1, "150.000")
    log = AuditLog.objects.get(action="day_closing.reopened")
    assert (log.actor, log.before, log.after) == (
        office,
        {
            "status": "approved",
            "expected": "150.000",
            "counted": "140.000",
            "difference": "-10.000",
            "reviewed_by": office.username,
        },
        {"load": transfer.number},
    )
    # The day sells again; the 10 DT that were missing at the first count are still missing at the next one.
    clock(at(14))
    assert sell(road, "1", "28.000").status_code == 201
    summary = my_day(road)["summary"]
    assert (summary["handed_over"], summary["expected_cash"]) == ("140.000", "38.000")  # 50 + 128 - 140


def test_a_day_the_office_asked_about_is_reopened_and_keeps_the_question(road, clock):
    morning_sent(road, clock, counted="140.000")
    road["office"].post(
        reverse("day-closing-justification", args=[office_row(road)["id"]]),
        {"reason": "Il manque 10 DT"},
        format="json",
    )

    clock(at(13))
    load(road, "4")

    closing = my_day(road)["closing"]
    assert (closing["status"], closing["review_note"]) == ("reopened", "Il manque 10 DT")
    assert office_detail(road)["reopenings"][0]["status"] == "justification"


def test_each_reopening_adds_the_cash_counted_to_what_was_handed_over(road, clock):
    morning_sent(road, clock)
    clock(at(13))
    load(road, "4")
    clock(at(14))
    assert sell(road, "2", "56.000").status_code == 201
    clock(at(15))
    assert close(road, "56.000").status_code == 201

    clock(at(16))
    load(road, "1")

    summary = my_day(road)["summary"]
    assert (summary["handed_over"], summary["expected_cash"]) == ("206.000", "0.000")
    clock(at(17))
    assert sell(road, "1", "28.000").status_code == 201
    assert my_day(road)["summary"]["expected_cash"] == "28.000"
    assert [row["counted_cash"] for row in office_detail(road)["reopenings"]] == ["150.000", "56.000"]


def test_only_a_load_of_that_date_into_the_drivers_truck_reopens_the_day(road, clock):
    morning_sent(road, clock)
    other_truck = fleet.create_truck(
        organization=road["organization"], actor=None, name="Camion 2", plate="102 TU 2002"
    )

    clock(at(13))
    load(road, "2", on=DAY_BEFORE)  # typed late for the day before
    load(road, "2", back=True)  # the office unloads the truck
    load(road, "2", truck=other_truck)
    clock(at(9, day=NEXT_DAY))
    load(road, "2")  # the next morning's load is the next day's

    assert driver_day(road).ended_at is not None
    assert office_row(road)["status"] == "submitted"
    assert not DayReopening.objects.exists()


def test_a_load_does_not_reopen_the_day_of_a_driver_who_no_longer_has_the_truck(road, clock):
    morning_sent(road, clock)
    other = MembershipFactory.create(organization=road["organization"], role=Role.DRIVER)
    fleet.assign_truck(organization=road["organization"], actor=None, truck=road["truck"], driver=other.user, date=DAY)

    clock(at(13))
    load(road, "4")

    assert driver_day(road).ended_at is not None
    assert office_row(road)["status"] == "submitted"


def test_a_load_on_a_day_that_runs_changes_nothing(road, clock):
    clock(at(9))
    load(road, "4")

    assert my_day(road)["closing"] is None
    assert my_day(road)["summary"]["handed_over"] == "0.000"
    assert not DayReopening.objects.exists()


def test_what_the_office_moves_after_the_send_stays_out_of_the_sent_day(road, clock):
    """The truck is unloaded in the evening, after the driver sent the day: the day's figures stop at the send."""
    morning_sent(road, clock)

    clock(at(16))
    load(road, "10", back=True)

    line = stock_line(road)
    assert (line["returned"], line["remaining"], line["unexplained"]) == ("0.000", "10.000", "0.000")
    assert office_detail(road)["changes_since_sent"] == []


# ---- A sale made before the send and received after it (D-133), and the day sent again (D-132) ----


def test_a_sale_made_before_the_closing_and_received_after_it_counts_on_that_day(road, clock):
    """Made at 11:00 without connection, received at 15:00, after the day was sent at 12:00: it is that day's
    sale. The closing keeps what was sent, the office sees what changed and waits for the day sent again."""
    morning_sent(road, clock)
    clock(at(15))

    late = sell(road, "1", "28.000", made_at=at(11))

    assert late.status_code == 201
    assert Sale.objects.get(pk=late.json()["id"]).sold_at == at(11)
    line = stock_line(road)
    assert (line["sold"], line["remaining"], line["unexplained"]) == ("6.000", "9.000", "0.000")
    # The phone shows the day's records again: they are what the driver counts against and sends.
    answer = my_day(road)
    assert (answer["closing"]["changed_since_sent"], answer["summary"]["expected_cash"]) == (True, "178.000")
    # The office still reads the closing as it was sent, and sees figure by figure what moved since.
    detail = office_detail(road)
    assert (detail["expected_cash"], detail["summary"]["sales_count"], detail["changed_since_sent"]) == (
        "150.000",
        1,
        True,
    )
    assert [(c["figure"], c["product_name"], c["sent"], c["live"]) for c in detail["changes_since_sent"]] == [
        ("sales_count", "", "1.000", "2.000"),
        ("sales_total", "", "140.000", "168.000"),
        ("cash_received", "", "100.000", "128.000"),
        ("expected_cash", "", "150.000", "178.000"),
        ("sold", "Dorade royale", "5.000", "6.000"),
        ("remaining", "Dorade royale", "10.000", "9.000"),
    ]
    refused = road["office"].post(reverse("day-closing-approve", args=[detail["id"]]))
    assert refused.status_code == 400

    clock(at(16))
    assert close(road, "178.000").status_code == 201

    detail = office_detail(road)
    assert (detail["status"], detail["office_difference"], detail["changes_since_sent"]) == ("submitted", "0.000", [])
    assert timezone.localtime(driver_day(road).ended_at) == at(12)  # sent again, the day still ends at its first send
    approved = road["office"].post(reverse("day-closing-approve", args=[detail["id"]])).json()
    assert (approved["status"], approved["expected_cash"]) == ("approved", "178.000")
    late_again = sell(road, "1", "28.000", made_at=at(11, 30))  # nothing more on an approved day
    assert late_again.status_code == 403
    assert late_again.json()["detail"] == "Votre journée est approuvée par le bureau : elle est fermée."


def test_nothing_changed_since_the_closing_was_sent_shows_no_difference(road, clock):
    morning_sent(road, clock)
    clock(at(14))

    detail = office_detail(road)

    assert (detail["changes_since_sent"], detail["changed_since_sent"]) == ([], False)
    assert my_day(road)["summary"]["sales_total"] == "140.000"


def test_the_day_sent_again_after_a_justification_takes_the_late_sale(road, clock):
    morning_sent(road, clock)
    day_id = driver_day(road).pk
    clock(at(15))
    assert sell(road, "1", "28.000", made_at=at(11)).status_code == 201
    row = office_row(road)
    road["office"].post(
        reverse("day-closing-justification", args=[row["id"]]), {"reason": "Une vente en plus ?"}, format="json"
    )

    # Asked, the phone shows the day's records, which the new send will keep: the cash to count against is right.
    asked = road["api"].get(reverse("my-day-detail", args=[day_id])).json()
    assert (asked["closing"]["status"], asked["summary"]["expected_cash"]) == ("justification", "178.000")

    clock(at(16))
    resent = road["api"].post(
        reverse("my-past-day-closing", args=[day_id]), {"note": "Vente hors réseau"}, format="json"
    )
    assert resent.status_code == 201
    assert count(road, "178.000").status_code == 200

    summary = resent.json()["summary"]
    assert (summary["sales_count"], summary["expected_cash"]) == (2, "178.000")
    assert (summary["products"][0]["sold"], summary["products"][0]["remaining"]) == ("6.000", "9.000")
    detail = office_detail(road)
    assert (detail["status"], detail["office_difference"], detail["changes_since_sent"]) == ("submitted", "0.000", [])
    assert timezone.localtime(driver_day(road).ended_at) == at(12)


def test_a_sale_made_after_the_closing_of_an_earlier_date_is_refused_with_its_date(road, clock):
    """Yesterday's day was sent at 18:00: a sale the phone says was made at 19:00, received this morning, is
    refused, so the phone reports it."""
    clock(at(18))
    assert close(road, "50.000").status_code == 201
    clock(at(9, day=NEXT_DAY))

    after = sell(road, "1", "28.000", made_at=at(19))
    before = sell(road, "1", "28.000", made_at=at(17))

    assert after.status_code == 403
    assert after.json()["detail"] == (
        f"Votre journée du {DAY:%d/%m/%Y} était déjà clôturée quand cette vente a été faite : "
        "elle n'est pas enregistrée. Prévenez le bureau."
    )
    assert before.status_code == 201  # made before the send: yesterday's sale, the day is not approved
    assert timezone.localtime(Sale.objects.get().sold_at) == at(17)
    assert sell(road, "1", "28.000").status_code == 201  # today no day is started yet: sold as before (D-133)
