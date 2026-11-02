"""The end of a driver's day (P3-T06, D-094): the summary, the counted cash and the office review."""

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
from apps.dayclose.models import DayClosing, DayClosingRevision, DayClosingStatus
from apps.fleet import services as fleet
from apps.fleet.models import DayFund
from apps.inventory import services as inventory
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners import services as partners
from apps.sales import services as sales
from apps.sales.models import Sale
from apps.sales.receivables import customer_balance

pytestmark = pytest.mark.django_db


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def day():
    """A driver with a loaded truck: 12 kg of dorade at 28 DT, 50 DT in the till, day started."""
    organization = OrganizationFactory.create()
    actor = UserFactory.create()
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    office = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    room = StockLocationFactory.create(organization=organization, name="Chambre froide 1")
    truck = fleet.create_truck(
        organization=organization, actor=actor, name="Camion 1", plate="101 TU 2001", driver=driver.user
    )
    product = ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")
    ProductPriceFactory.create(
        product=product, price=Decimal("28.000"), valid_from=timezone.now() - dt.timedelta(days=3)
    )
    batch = BatchFactory.create(organization=organization, product=product, received_on=timezone.localdate())
    inventory.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity="20",
        to_location=room,
    )
    inventory.create_transfer(
        organization=organization,
        actor=actor,
        from_location=room,
        to_location=truck.location,
        transferred_on=timezone.localdate(),
        lines=[{"product": product, "quantity": Decimal("12")}],
        validate=True,
    )
    customer = partners.create_customer(
        organization=organization, actor=actor, name="Restaurant Le Port", credit_limit=Decimal("500.000")
    )
    api = client_for(driver)
    # The office sets the starting cash, the driver accepts it (D-203).
    fleet.set_day_fund(
        organization=organization,
        actor=driver.user,
        driver=driver.user,
        date=timezone.localdate(),
        opening_cash=Decimal("50"),
    )
    assert api.post(reverse("my-day"), format="json").status_code == 201
    owner = MembershipFactory.create(organization=organization, role=Role.OWNER)
    return {
        "api": api,
        "office": client_for(office),
        "owner": client_for(owner),
        "organization": organization,
        "product": product,
        "room": room,
        "batch": batch,
        "truck": truck,
        "customer": customer,
        "driver": driver.user,
        "actor": actor,
    }


def empty_the_truck(client, closing_id):
    """The office gives back what the truck holds before it approves the day (D-249)."""
    driver_day_id = client.get(reverse("day-closing-detail", args=[closing_id])).json()["driver_day_id"]
    client.post(reverse("day-overview-return-to-stock", args=[driver_day_id]))


def sell(day, kg, paid):
    return day["api"].post(
        reverse("sale-list"),
        {
            "customer": day["customer"].pk,
            "location": day["truck"].location_id,
            "confirm_now": True,
            "amount_paid": paid,
            "payment_method": "cash",
            "lines": [{"product": day["product"].pk, "quantity": kg}],
        },
        format="json",
    )


def test_the_summary_adds_up_the_day(day):
    assert sell(day, "5", "100.000").status_code == 201  # 140 DT, 40 on credit

    summary = day["api"].get(reverse("my-day-summary")).json()["summary"]

    assert (summary["sales_count"], summary["sales_total"], summary["cash_received"], summary["on_credit"]) == (
        1,
        "140.000",
        "100.000",
        "40.000",
    )
    assert summary["expected_cash"] == "150.000"  # 50 at the start + 100 received
    assert summary["products"][0] | {"product_id": 0} == {
        "product_id": 0,
        "product_name": "Dorade royale",
        "opening": "0.000",
        "loaded": "12.000",
        "sold": "5.000",
        "lost": "0.000",
        "returned": "0.000",
        "remaining": "7.000",
        "unexplained": "0.000",
    }


def test_kilos_left_on_the_truck_from_an_earlier_day_are_its_opening_stock(day):
    """Bug of 2026-10-13: a truck sold more than it was loaded that day (Crevette 109 sold, 100 loaded).
    The 2 kg of dorade sold today were on the truck since yesterday: they are the opening stock, so the
    day adds up: opening + loaded - returned - sold - lost = left."""
    yesterday = timezone.localdate() - dt.timedelta(days=1)
    left_over = BatchFactory.create(organization=day["organization"], product=day["product"], received_on=yesterday)
    inventory.post_movement(
        organization=day["organization"],
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=left_over,
        quantity="2",
        to_location=day["room"],
        occurred_at=timezone.make_aware(dt.datetime.combine(yesterday, dt.time(9, 0))),
    )
    inventory.create_transfer(
        organization=day["organization"],
        actor=None,
        from_location=day["room"],
        to_location=day["truck"].location,
        transferred_on=yesterday,
        lines=[{"product": day["product"], "quantity": Decimal("2")}],
        validate=True,
    )
    assert sell(day, "13", "100.000").status_code == 201

    product = day["api"].get(reverse("my-day-summary")).json()["summary"]["products"][0]

    assert (product["opening"], product["loaded"], product["sold"], product["remaining"]) == (
        "2.000",
        "12.000",
        "13.000",
        "1.000",
    )
    assert product["unexplained"] == "0.000"


def test_stock_that_left_the_truck_without_a_record_is_unexplained(day):
    """Kilos that leave the truck by a hand adjustment, with no sale, loss or transfer behind them, show as a gap."""
    sell(day, "3", "84.000")
    inventory.post_movement(
        organization=day["organization"],
        actor=None,
        kind=MovementKind.ADJUSTMENT,
        batch=day["batch"],
        quantity="2",
        from_location=day["truck"].location,
        reason="Test",
    )

    product = day["api"].get(reverse("my-day-summary")).json()["summary"]["products"][0]

    assert (product["loaded"], product["sold"], product["remaining"]) == ("12.000", "3.000", "7.000")
    assert product["unexplained"] == "-2.000"


def test_the_driver_sends_the_day_and_the_office_approves_it_after_a_justification(day):
    sell(day, "5", "100.000")

    sent = day["api"].post(reverse("my-day-closing"), {"note": "Un billet de 10 manque"}, format="json")
    again = day["api"].post(reverse("my-day-closing"), {}, format="json")

    assert sent.status_code == 201
    assert (sent.json()["closing"]["status"], sent.json()["closing"]["expected_cash"]) == ("submitted", "150.000")
    assert again.status_code == 400  # already sent
    closing = day["office"].get(reverse("day-closing-list")).json()[0]
    assert (closing["expected_cash"], closing["office_counted_cash"], closing["office_difference"]) == (
        "150.000",
        None,
        "0.000",
    )
    detail = day["office"].get(reverse("day-closing-detail", args=[closing["id"]])).json()
    assert detail["driver_note"] == "Un billet de 10 manque"
    assert detail["summary"]["sales_total"] == "140.000"

    asked = day["office"].post(
        reverse("day-closing-justification", args=[closing["id"]]), {"reason": "Expliquez la différence"}, format="json"
    )
    assert asked.json()["status"] == "justification"
    resent = day["api"].post(reverse("my-day-closing"), {"note": "Dépense non saisie"}, format="json")
    assert resent.status_code == 201
    url = reverse("day-closing-approve", args=[closing["id"]])
    empty_the_truck(day["office"], closing["id"])
    # The office counts 135 DT: a gap with the 150 DT the driver should hold needs a note (D-204, D-213).
    counted = day["office"].post(
        reverse("day-closing-count", args=[closing["id"]]), {"office_counted_cash": "135.000"}, format="json"
    )
    assert (counted.json()["office_counted_cash"], counted.json()["office_difference"]) == ("135.000", "-15.000")
    no_note = day["office"].post(url, {}, format="json")
    assert no_note.status_code == 400
    assert "écart" in no_note.json()["note"][0]
    approved = day["office"].post(url, {"note": "Billet faux"}, format="json")
    assert approved.json()["status"] == "approved"
    assert (approved.json()["office_counted_cash"], approved.json()["office_difference"]) == ("135.000", "-15.000")
    assert approved.json()["review_note"] == "Billet faux"
    assert day["api"].post(reverse("my-day-closing"), {}, format="json").status_code == 400  # locked
    assert day["office"].post(url).status_code == 400


def test_approving_the_day_resets_the_cash_the_office_set_for_that_driver_to_zero(day):
    sell(day, "5", "100.000")
    DayFund.objects.filter(driver=day["driver"]).update(purchase_float=Decimal("30.000"))
    today = timezone.localdate().isoformat()

    sent = day["api"].post(reverse("my-day-closing"), {}, format="json")

    assert (sent.status_code, sent.json()["closing"]["expected_cash"]) == (201, "150.000")
    assert (day["api"].get(reverse("my-day-fund")).json()["opening_cash"]) == "50.000"  # sending keeps the cash
    closing = day["office"].get(reverse("day-closing-list")).json()[0]
    counted = day["office"].post(
        reverse("day-closing-count", args=[closing["id"]]),
        {"office_counted_cash": "150.000", "office_counted_purchase_cash": "0.000"},
        format="json",
    )
    assert counted.status_code == 200
    approved = day["office"].post(reverse("day-closing-approve", args=[closing["id"]]), {}, format="json")
    assert approved.json()["status"] == "approved"
    fund = day["api"].get(reverse("my-day-fund")).json()
    assert (fund["opening_cash"], fund["purchase_float"]) == ("0.000", "0.000")
    rows = day["office"].get(reverse("day-fund-list"), {"date": today}).json()
    mine = next(row for row in rows if row["driver"]["id"] == day["driver"].pk)
    assert (mine["fund"]["opening_cash"], mine["fund"]["purchase_float"]) == ("0.000", "0.000")
    load_again(day, "1")  # a new load reopens the approved day; the amounts do not come back (D-259)
    assert day["api"].get(reverse("my-day-fund")).json()["opening_cash"] == "0.000"


def load_again(day, kg):
    return inventory.create_transfer(
        organization=day["organization"],
        actor=None,
        from_location=day["room"],
        to_location=day["truck"].location,
        transferred_on=timezone.localdate(),
        lines=[{"product": day["product"], "quantity": Decimal(kg)}],
        validate=True,
    )


def test_a_day_loaded_again_after_sending_is_sent_again_before_the_office_approves_it(day):
    """Seen on staging (D-132): the driver sent the day, was loaded again and went back out. The load opens the
    day again (D-134); the office waits for it sent again, with the cash the office counted at the first send
    already handed over."""
    sell(day, "1", "28.000")
    sent = day["api"].post(reverse("my-day-closing"), {}, format="json").json()
    assert (sent["closing"]["status"], sent["closing"]["changed_since_sent"]) == ("submitted", False)
    closing_id = sent["closing"]["id"]
    counted = day["office"].post(
        reverse("day-closing-count", args=[closing_id]), {"office_counted_cash": "78.000"}, format="json"
    )
    assert counted.status_code == 200, counted.json()
    assert sell(day, "2", "56.000").status_code == 403  # sent: closed until the truck is loaded again

    load_again(day, "3")

    assert sell(day, "2", "56.000").status_code == 201
    now = day["api"].get(reverse("my-day-summary")).json()
    assert (now["closing"]["status"], now["summary"]["sales_count"]) == ("reopened", 2)
    assert (now["summary"]["handed_over"], now["summary"]["expected_cash"]) == ("78.000", "56.000")
    assert day["office"].post(reverse("day-closing-approve", args=[closing_id])).status_code == 400
    resent = day["api"].post(reverse("my-day-closing"), {}, format="json")
    assert resent.status_code == 201
    detail = day["office"].get(reverse("day-closing-detail", args=[closing_id])).json()
    assert (detail["expected_cash"], detail["office_counted_cash"], detail["summary"]["sales_count"]) == (
        "56.000",
        None,
        2,
    )
    assert [undone["counted_cash"] for undone in detail["reopenings"]] == ["78.000"]
    assert day["office"].post(reverse("day-closing-approve", args=[closing_id])).status_code == 400
    counted_again = day["office"].post(
        reverse("day-closing-count", args=[closing_id]), {"office_counted_cash": "56.000"}, format="json"
    )
    assert counted_again.status_code == 200, counted_again.json()
    empty_the_truck(day["office"], closing_id)
    approved = day["office"].post(reverse("day-closing-approve", args=[closing_id]), {}, format="json")
    assert approved.json()["status"] == "approved"


def test_a_reopened_day_does_not_wait_for_the_office(day):
    """Its send is undone and its cash difference is that of the first count: neither is the office's to chase
    until the driver sends the day again."""
    from apps.dayclose import selectors

    sell(day, "5", "100.000")  # expected cash: 150
    day["api"].post(reverse("my-day-closing"), {}, format="json")
    organization = day["organization"]
    assert selectors.waiting_for_office(organization) == 1

    load_again(day, "3")

    assert selectors.waiting_for_office(organization) == 0
    assert selectors.unexplained_cash_differences(organization) == []
    dashboard = day["owner"].get(reverse("dashboard")).json()
    assert (dashboard["days_waiting"], dashboard["cash_difference_count"]) == (0, 0)


def test_only_the_right_people_use_the_screens(day):
    assert day["office"].get(reverse("my-day-summary")).status_code == 403
    assert day["api"].get(reverse("day-closing-list")).status_code == 403
    assert client_for(MembershipFactory.create(role=Role.DRIVER)).get(reverse("my-day-summary")).status_code == 404


def test_an_approved_day_is_closed_to_sales_expenses_and_losses(day):
    sell(day, "1", "28.000")
    day["api"].post(reverse("my-day-closing"), {}, format="json")
    closing = day["office"].get(reverse("day-closing-list")).json()[0]

    day["office"].post(reverse("day-closing-approve", args=[closing["id"]]))

    assert sell(day, "1", "28.000").status_code == 403
    expense = day["api"].post(reverse("my-expenses"), {"category": 1, "amount": "5"}, format="multipart")
    loss = day["api"].post(
        reverse("my-losses"),
        {"product": day["product"].pk, "quantity": "1", "reason": "spoiled"},
        format="multipart",
    )
    assert (expense.status_code, loss.status_code) == (403, 403)
    assert day["api"].post(reverse("my-return")).status_code == 403


def test_a_sale_sent_again_after_the_day_is_approved_is_answered_not_refused(day):
    """The phone sent a sale, lost the answer, and the office approved the day meanwhile: the retry gets the
    recorded sale back (201, once), it is not refused as a new sale on a closed day."""
    from apps.sales.models import Sale

    client_uuid = str(uuid4())
    body = {
        "customer": day["customer"].pk,
        "location": day["truck"].location_id,
        "confirm_now": True,
        "client_uuid": client_uuid,
        "amount_paid": "28.000",
        "payment_method": "cash",
        "lines": [{"product": day["product"].pk, "quantity": "1"}],
    }
    first = day["api"].post(reverse("sale-list"), body, format="json")
    assert first.status_code == 201
    day["api"].post(reverse("my-day-closing"), {}, format="json")
    closing = day["office"].get(reverse("day-closing-list")).json()[0]
    day["office"].post(reverse("day-closing-approve", args=[closing["id"]]))

    retry = day["api"].post(reverse("sale-list"), body, format="json")

    assert (retry.status_code, retry.json()["id"]) == (201, first.json()["id"])
    assert Sale.objects.filter(client_uuid=client_uuid).count() == 1
    assert sell(day, "1", "28.000").status_code == 403  # a new sale on the approved day is still refused


def test_customers_sold_to_lately_come_first(day):
    other = partners.create_customer(organization=day["customer"].organization, actor=None, name="Aaa Hôtel")

    names = [c["name"] for c in day["api"].get(reverse("my-customers")).json()]
    assert names == ["Aaa Hôtel", "Restaurant Le Port"]  # alphabetical before any sale

    sell(day, "1", "28.000")
    names = [c["name"] for c in day["api"].get(reverse("my-customers")).json()]
    assert names == ["Restaurant Le Port", "Aaa Hôtel"]
    assert other.pk


def test_a_refused_send_is_reported_once_and_the_office_marks_it_dealt_with(day):
    body = {
        "kind": "sale",
        "what": "Restaurant Le Port",
        "reason": "Limite de crédit dépassée",
        "client_uuid": str(uuid4()),
    }

    first = day["api"].post(reverse("my-sync-problems"), body, format="json")
    again = day["api"].post(reverse("my-sync-problems"), body, format="json")

    assert first.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    listed = day["office"].get(reverse("sync-problem-list")).json()
    assert [(p["kind"], p["label"], p["reason"]) for p in listed] == [
        ("sale", "Restaurant Le Port", "Limite de crédit dépassée")
    ]
    assert day["office"].post(reverse("sync-problem-resolve", args=[first.json()["id"]])).json()["resolved_at"]
    assert day["office"].get(reverse("sync-problem-list")).json() == []
    assert day["api"].get(reverse("sync-problem-list")).status_code == 403
    assert day["office"].post(reverse("my-sync-problems"), body, format="json").status_code == 403


def test_a_cash_difference_nobody_explained_is_an_alert(day):
    from apps.dayclose import selectors

    sell(day, "5", "100.000")  # expected cash: 50 + 100 = 150
    sent = day["api"].post(reverse("my-day-closing"), {}, format="json")
    day["office"].post(
        reverse("day-closing-count", args=[sent.json()["closing"]["id"]]),
        {"office_counted_cash": "140.000"},
        format="json",
    )
    organization = day["truck"].organization

    rows = selectors.unexplained_cash_differences(organization)
    assert [(row.difference, row.day) for row in rows] == [(Decimal("-10.000"), timezone.localdate())]
    dashboard = day["owner"].get(reverse("dashboard")).json()
    assert dashboard["cash_difference_count"] == 1
    assert dashboard["cash_differences"][0]["difference"] == "-10.000"


def test_the_monthly_closing_sees_cash_differences_and_days_never_sent(day):
    from apps.dayclose import selectors
    from apps.fleet.models import DriverDay

    organization = day["truck"].organization
    today = timezone.localdate()
    sell(day, "5", "100.000")  # expected cash: 50 + 100 = 150
    sent = day["api"].post(reverse("my-day-closing"), {}, format="json")
    closing_id = sent.json()["closing"]["id"]
    day["office"].post(
        reverse("day-closing-count", args=[closing_id]), {"office_counted_cash": "140.000"}, format="json"
    )

    found = selectors.period_days(organization, date_from=today, date_to=today)
    assert (found.difference_count, found.difference_amount) == (1, Decimal("-10.000"))

    empty_the_truck(day["office"], closing_id)
    approved = day["office"].post(
        reverse("day-closing-approve", args=[closing_id]), {"note": "Billet faux"}, format="json"
    )
    assert approved.status_code == 200, approved.json()
    assert selectors.period_days(organization, date_from=today, date_to=today).difference_count == 0

    # A past day whose closing was never sent: its figures were never counted.
    yesterday = today - dt.timedelta(days=1)
    DriverDay.objects.filter(pk=selectors.closings_of(organization).get().driver_day_id).update(
        date=yesterday, ended_at=None
    )
    found = selectors.period_days(organization, date_from=yesterday, date_to=yesterday)
    assert found.unsent_count == 1


def test_an_explained_or_exact_day_is_not_an_alert(day):
    from apps.dayclose import selectors

    sell(day, "5", "100.000")
    sent = day["api"].post(reverse("my-day-closing"), {"note": "Un billet de 10 manque"}, format="json")
    day["office"].post(
        reverse("day-closing-count", args=[sent.json()["closing"]["id"]]),
        {"office_counted_cash": "140.000"},
        format="json",
    )
    assert selectors.unexplained_cash_differences(day["truck"].organization) == []


def test_a_payment_collected_by_the_driver_counts_in_the_day_cash_and_is_recorded_once(day):
    sell(day, "5", "100.000")  # 140 DT, 40 left on credit
    listed = day["api"].get(reverse("my-customers")).json()
    assert all("owes" not in c for c in listed)  # the driver never sees the balance (D-207)
    assert customer_balance(day["customer"].organization, day["customer"].pk).balance == Decimal("40.000")
    body = {"customer": day["customer"].pk, "amount": "30.000", "method": "cash", "client_uuid": str(uuid4())}

    first = day["api"].post(reverse("my-payments"), body, format="json")
    again = day["api"].post(reverse("my-payments"), body, format="json")

    assert first.status_code == 201
    assert again.json()["id"] == first.json()["id"]
    assert [p["amount"] for p in day["api"].get(reverse("my-payments")).json()] == ["30.000"]
    assert customer_balance(day["customer"].organization, day["customer"].pk).balance == Decimal("10.000")
    summary = day["api"].get(reverse("my-day-summary")).json()["summary"]
    assert (summary["payments_cash"], summary["expected_cash"]) == ("30.000", "180.000")  # 50 + 100 + 30
    assert (
        day["api"].post(reverse("my-payments"), {**body, "amount": "0", "client_uuid": None}, format="json").status_code
        == 400
    )
    assert day["office"].post(reverse("my-payments"), body, format="json").status_code == 403


def test_an_approved_day_refuses_new_customer_payments(day):
    day["api"].post(reverse("my-day-closing"), {}, format="json")
    closing = day["office"].get(reverse("day-closing-list")).json()[0]
    day["office"].post(reverse("day-closing-approve", args=[closing["id"]]))

    body = {"customer": day["customer"].pk, "amount": "5.000", "method": "cash"}

    assert day["api"].post(reverse("my-payments"), body, format="json").status_code == 403


# ---- A sent day is closed, and the history (D-134) ----


def test_a_sent_day_is_closed_to_sales_expenses_losses_returns_and_payments(day):
    sell(day, "5", "100.000")
    day["api"].post(reverse("my-day-closing"), {}, format="json")

    sale = sell(day, "1", "28.000")
    expense = day["api"].post(reverse("my-expenses"), {"category": 1, "amount": "5"}, format="multipart")
    loss = day["api"].post(
        reverse("my-losses"),
        {"product": day["product"].pk, "quantity": "1", "reason": "spoiled"},
        format="multipart",
    )
    back = day["api"].post(reverse("my-return"))
    payment = day["api"].post(
        reverse("my-payments"), {"customer": day["customer"].pk, "amount": "5.000", "method": "cash"}, format="json"
    )

    for refused in (sale, expense, loss, back, payment):
        assert refused.status_code == 403
        assert refused.json()["detail"] == (
            "Votre journée est clôturée : elle rouvre quand le bureau recharge votre camion."
        )
    assert day["api"].get(reverse("my-day")).json()["ended_at"] is not None
    # Starting the day again changes nothing: it is the same day, still closed.
    again = day["api"].post(reverse("my-day"), {"opening_cash": "20"}, format="json").json()
    assert (again["opening_cash"], again["ended_at"] is None) == ("50.000", False)


def test_the_driver_sees_the_history_and_sends_a_justification_from_it(day):
    sell(day, "5", "100.000")
    day["api"].post(reverse("my-day-closing"), {}, format="json")
    first = day["api"].get(reverse("my-day-list")).json()[0]
    closing_id = day["office"].get(reverse("day-closing-list")).json()[0]["id"]
    day["office"].post(
        reverse("day-closing-justification", args=[closing_id]), {"reason": "Il manque 10 DT"}, format="json"
    )

    (row,) = day["api"].get(reverse("my-day-list")).json()
    assert (row["closing"]["status"], row["closing"]["expected_cash"]) == ("justification", "150.000")
    assert (row["truck_name"], row["ended_at"] is None) == ("Camion 1", False)
    detail = day["api"].get(reverse("my-day-detail", args=[first["id"]])).json()
    assert (detail["summary"]["sales_total"], detail["summary"]["products"][0]["remaining"]) == ("140.000", "7.000")

    resent = day["api"].post(
        reverse("my-past-day-closing", args=[first["id"]]),
        {"note": "Pourboire"},
        format="json",
    )
    assert resent.status_code == 201
    summary = resent.json()["summary"]
    assert (summary["sales_total"], summary["products"][0]["remaining"]) == ("140.000", "7.000")
    assert resent.json()["closing"]["status"] == "submitted"
    assert sell(day, "1", "28.000").status_code == 403  # sent again: still closed


def test_a_driver_only_sees_their_own_days(day):
    other = client_for(MembershipFactory.create(role=Role.DRIVER))
    first = day["api"].get(reverse("my-day-list")).json()[0]

    assert other.get(reverse("my-day-list")).json() == []
    assert other.get(reverse("my-day-detail", args=[first["id"]])).status_code == 404
    assert other.post(reverse("my-past-day-closing", args=[first["id"]]), {}, format="json").status_code == 404


def test_the_office_history_filters_by_driver_and_dates(day):
    day["api"].post(reverse("my-day-closing"), {}, format="json")
    today = timezone.localdate()

    def rows(**params):
        return day["office"].get(reverse("day-closing-list"), params).json()

    assert len(rows(search="Camion 1")) == 1
    assert rows(search="personne") == []
    assert len(rows(date_from=today.isoformat(), date_to=today.isoformat())) == 1
    assert rows(date_from=(today + dt.timedelta(days=1)).isoformat()) == []


def phone_moment(minutes_ago):
    """A time the driver's phone says, a few minutes before now: outside the clock margin (D-133)."""
    return (timezone.now() - dt.timedelta(minutes=minutes_ago)).isoformat()


def test_an_expense_entered_late_is_dated_when_it_was_spent(day):
    from apps.expenses.models import Expense, ExpenseCategory

    fuel = ExpenseCategory.objects.for_organization(day["organization"]).get(code="fuel")
    spent = day["api"].post(
        reverse("my-expenses"),
        {"category": fuel.pk, "amount": "5", "made_at": phone_moment(10)},
        format="multipart",
    )

    assert spent.status_code == 201
    assert Expense.objects.get(pk=spent.json()["id"]).spent_on == timezone.localdate()
    assert (
        day["api"]
        .post(
            reverse("my-expenses"),
            {"category": fuel.pk, "amount": "5", "made_at": (timezone.now() + dt.timedelta(hours=2)).isoformat()},
            format="multipart",
        )
        .json()["made_at"][0]
        .startswith("Cette saisie est datée dans le futur")
    )


def test_a_payment_collected_late_is_dated_when_it_was_received(day):
    from apps.sales.models import CustomerPayment

    sell(day, "5", "100.000")
    body = {"customer": day["customer"].pk, "amount": "30.000", "method": "cash", "made_at": phone_moment(10)}

    paid = day["api"].post(reverse("my-payments"), body, format="json")

    assert paid.status_code == 201
    assert CustomerPayment.objects.get(pk=paid.json()["id"]).received_on == timezone.localdate()
    summary = day["api"].get(reverse("my-day-summary")).json()["summary"]
    assert summary["payments_cash"] == "30.000"


def test_a_loss_reported_late_leaves_the_stock_at_the_moment_it_was_made(day):
    from apps.inventory.models import StockMovement

    moment = phone_moment(10)
    lost = day["api"].post(
        reverse("my-losses"),
        {"product": day["product"].pk, "quantity": "1", "reason": "spoiled", "made_at": moment},
        format="multipart",
    )

    assert lost.status_code == 201
    loss_movement = StockMovement.objects.filter(kind=MovementKind.LOSS).get()
    assert loss_movement.occurred_at == parse_datetime(moment)


def test_the_office_follows_a_running_day_and_filters_it(day):
    sell(day, "5", "100.000")

    rows = day["office"].get(reverse("day-overview-list")).json()
    other_driver = day["office"].get(reverse("day-overview-list"), {"driver_id": 0}).json()
    detail = day["office"].get(reverse("day-overview-detail", args=[rows[0]["id"]])).json()
    drivers = day["office"].get(reverse("day-overview-drivers")).json()

    assert len(rows) == 1
    assert (rows[0]["phase"], rows[0]["sales_count"], rows[0]["sales_total"]) == ("running", 1, "140.000")
    assert (rows[0]["deliveries_done"], rows[0]["deliveries_todo"]) == (0, 0)
    assert other_driver == []
    assert len(detail["sales"]) == 1
    assert detail["expenses"] == []
    assert len(drivers) == 1
    assert day["api"].get(reverse("day-overview-list")).status_code == 403


def load_bl(day, kg):
    """A load of `kg` of dorade for the day's customer, validated by the office: its BL waits for the driver."""
    transfer = inventory.create_transfer(
        organization=day["organization"],
        actor=day["actor"],
        from_location=day["room"],
        to_location=day["truck"].location,
        transferred_on=timezone.localdate(),
        lines=[],
        deliveries=[
            {
                "customer": day["customer"],
                "delivery_address": "",
                "lines": [{"product": day["product"], "quantity": kg}],
                "boxes": {},
            }
        ],
        validate=True,
    )
    return Sale.objects.get(transfer=transfer)


def overview(day):
    (row,) = day["office"].get(reverse("day-overview-list")).json()
    return row


def test_a_load_bl_the_driver_delivers_counts_in_their_day(day):
    bl = load_bl(day, "5")
    # Validated before midnight for the next morning: the delivery, not the load, dates the sale.
    Sale.objects.filter(pk=bl.pk).update(sold_at=timezone.now() - dt.timedelta(days=1))

    delivered = sales.deliver_sale(
        sale=bl,
        actor=day["driver"],
        lines=[{"line": bl.lines.get().pk, "quantity": "4"}],
        payment={"amount_paid": "60.000", "payment_method": "cash"},
    )

    assert delivered.sold_at == delivered.delivered_at
    summary = day["api"].get(reverse("my-day-summary")).json()["summary"]
    assert (summary["sales_count"], summary["sales_total"], summary["cash_received"]) == (1, "112.000", "60.000")
    assert (summary["on_credit"], summary["expected_cash"]) == ("52.000", "110.000")  # 50 at the start + 60
    (product,) = summary["products"]
    assert (product["loaded"], product["sold"], product["remaining"]) == ("17.000", "4.000", "13.000")
    assert product["unexplained"] == "0.000"
    row = overview(day)
    assert (row["sales_total"], row["deliveries_done"], row["deliveries_todo"]) == ("112.000", 1, 0)


def test_a_load_bl_the_office_marks_delivered_counts_in_the_truck_drivers_day(day):
    bl = load_bl(day, "5")

    sales.confirm_sale(sale=bl, actor=day["actor"])

    row = overview(day)
    assert (row["sales_count"], row["sales_total"], row["on_credit"]) == (1, "140.000", "140.000")


def send(day):
    return day["api"].post(reverse("my-day-closing"), {"note": ""}, format="json")


def closing_of(day) -> DayClosing:
    return DayClosing.objects.get(organization=day["organization"])


def moved(closing: DayClosing) -> None:
    """The records now differ from what was sent (a sale received after the send, D-132): the sent expected cash is
    set aside, so the comparison with the records finds a change."""
    DayClosing.objects.filter(pk=closing.pk).update(summary={**closing.summary, "expected_cash": "1.000"})


def test_the_driver_does_not_send_a_sent_day_again_once_its_records_moved(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    moved(closing_of(day))

    again = send(day)

    assert again.status_code == 403
    assert "bureau corrige" in again.json()["detail"]


def test_the_driver_cannot_send_again_after_a_justification_once_the_records_moved(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    asked = day["office"].post(
        reverse("day-closing-justification", args=[closing.pk]), {"reason": "Expliquez la vente"}, format="json"
    )
    assert asked.status_code == 200
    moved(closing)

    assert send(day).status_code == 403


def test_the_driver_sends_again_after_a_justification_when_nothing_moved(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    day["office"].post(
        reverse("day-closing-justification", args=[closing.pk]), {"reason": "Expliquez la vente"}, format="json"
    )

    assert send(day).status_code == 201
    closing.refresh_from_db()
    assert closing.status == DayClosingStatus.SUBMITTED


def test_the_office_corrects_a_moved_day_and_the_correction_is_a_revision(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    moved(closing)

    response = day["office"].post(
        reverse("day-closing-correct", args=[closing.pk]), {"reason": "Vente oubliée"}, format="json"
    )

    assert response.status_code == 200
    body = response.json()
    assert body["changed_since_sent"] is False
    assert [(r["number"], r["reason"]) for r in body["revisions"]] == [(1, "Vente oubliée")]
    assert body["revisions"][0]["actor_name"] != ""
    revision = DayClosingRevision.objects.get(closing=closing)
    assert (revision.before["expected_cash"], revision.after["expected_cash"]) == ("1.000", "150.000")


def test_a_correction_needs_a_reason_and_a_change(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    url = reverse("day-closing-correct", args=[closing.pk])

    assert day["office"].post(url, {"reason": " "}, format="json").status_code == 400
    # Nothing moved and no count given: there is nothing to correct.
    assert day["office"].post(url, {"reason": "Pour rien"}, format="json").status_code == 400
    assert DayClosingRevision.objects.count() == 0


def test_a_saved_count_changes_only_by_a_correction(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    counted = day["office"].post(
        reverse("day-closing-count", args=[closing.pk]), {"office_counted_cash": "150.000"}, format="json"
    )
    assert counted.status_code == 200

    recount = day["office"].post(
        reverse("day-closing-count", args=[closing.pk]), {"office_counted_cash": "140.000"}, format="json"
    )
    corrected = day["office"].post(
        reverse("day-closing-correct", args=[closing.pk]),
        {"reason": "Compté deux fois", "office_counted_cash": "140.000"},
        format="json",
    )

    assert recount.status_code == 400
    assert corrected.status_code == 200
    body = corrected.json()
    assert (body["office_counted_cash"], body["office_difference"]) == ("140.000", "-10.000")
    revision = DayClosingRevision.objects.get(closing=closing)
    assert (revision.before["office_counted_cash"], revision.after["office_counted_cash"]) == ("150.000", "140.000")


def test_the_office_cannot_approve_a_moved_day_before_correcting_it(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    moved(closing)

    approved = day["office"].post(
        reverse("day-closing-approve", args=[closing.pk]), {"office_counted_cash": "150.000"}, format="json"
    )

    assert approved.status_code == 400
    closing.refresh_from_db()
    assert closing.status == DayClosingStatus.SUBMITTED


def test_only_the_office_corrects_a_day(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    moved(closing)

    response = day["api"].post(
        reverse("day-closing-correct", args=[closing.pk]), {"reason": "Je corrige"}, format="json"
    )

    assert response.status_code == 403


def test_a_day_a_new_load_reopened_is_not_corrected_on_its_old_send(day):
    assert sell(day, "5", "100.000").status_code == 201
    assert send(day).status_code == 201
    closing = closing_of(day)
    DayClosing.objects.filter(pk=closing.pk).update(status=DayClosingStatus.REOPENED)

    response = day["office"].post(
        reverse("day-closing-correct", args=[closing.pk]), {"reason": "Trop tard"}, format="json"
    )

    assert response.status_code == 400
