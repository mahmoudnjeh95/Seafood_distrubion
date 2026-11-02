"""The office reviews a driver's day before it approves it (D-239): the expenses are approved or refused, and what the
truck still holds, kilos and boxes, goes back to the cold room, whether or not the driver sent the day."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse

from apps.expenses import services as expenses
from apps.expenses.models import ExpenseCategory
from apps.inventory import selectors as inventory_selectors

from .test_dayclose import day, sell  # noqa: F401 - the day fixture, a driver with a loaded truck

pytestmark = pytest.mark.django_db


def closing_of_day(day):
    """The closing the driver sent, as the office's list shows it."""
    return day["office"].get(reverse("day-closing-list")).json()[0]


def closing_detail(day, closing_id):
    return day["office"].get(reverse("day-closing-detail", args=[closing_id])).json()


def day_detail(day, driver_day_id):
    return day["office"].get(reverse("day-overview-detail", args=[driver_day_id])).json()


def test_a_day_waits_for_the_truck_to_be_emptied_before_the_approval(day):
    sell(day, "5", "100.000")
    assert day["api"].post(reverse("my-day-closing"), {}, format="json").status_code == 201
    closing = closing_of_day(day)
    assert len(closing_detail(day, closing["id"])["review_blockers"]) == 1

    refused = day["office"].post(
        reverse("day-closing-approve", args=[closing["id"]]), {"office_counted_cash": "150.000"}, format="json"
    )
    assert refused.status_code == 400
    assert "review" in refused.json()

    returned = day["office"].post(reverse("day-overview-return-to-stock", args=[closing["driver_day_id"]]))

    assert returned.status_code == 200
    assert returned.json()["stock"] == []
    # 20 kg received, 12 loaded on the truck, 5 sold: the 7 kg left come back, the cold room holds 15 kg.
    room = inventory_selectors.location_stock(day["organization"], location_id=day["room"].pk)
    assert [row["quantity"] for row in room] == [Decimal("15.000")]
    # The sent day keeps its figures: the leftover left the truck after the send.
    assert closing_detail(day, closing["id"])["changed_since_sent"] is False
    assert closing_detail(day, closing["id"])["review_blockers"] == []

    approved = day["office"].post(
        reverse("day-closing-approve", args=[closing["id"]]), {"office_counted_cash": "150.000"}, format="json"
    )
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"


def test_a_refused_expense_is_taken_off_the_sent_day_as_a_correction(day):
    expenses.ensure_default_categories(organization=day["organization"])
    fuel = ExpenseCategory.objects.get(organization=day["organization"], code="fuel")
    spent = day["api"].post(
        reverse("my-expenses"),
        {"category": fuel.pk, "amount": "12.000", "paid_with": "cash", "client_uuid": str(uuid4())},
        format="multipart",
    )
    assert spent.status_code == 201
    assert day["api"].post(reverse("my-day-closing"), {}, format="json").status_code == 201
    closing = closing_of_day(day)
    expense_id = day_detail(day, closing["driver_day_id"])["expenses"][0]["id"]

    refused = day["office"].post(
        reverse("day-overview-expense-decide", args=[closing["driver_day_id"], expense_id]),
        {"decision": "reject", "reason": "Pas de ticket"},
        format="json",
    )

    assert refused.status_code == 200
    assert refused.json()["expenses"][0]["status"] == "rejected"
    assert refused.json()["expenses"][0]["rejection_reason"] == "Pas de ticket"
    corrected = closing_detail(day, closing["id"])
    assert corrected["summary"]["expenses_total"] == "0.000"
    assert len(corrected["revisions"]) == 1
    assert corrected["changed_since_sent"] is False
