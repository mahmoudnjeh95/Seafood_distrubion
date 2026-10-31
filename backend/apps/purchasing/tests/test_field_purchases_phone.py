"""Buying at the port from the phone (P3-T12b, D-158): the "can buy" switch, the driver's purchases, their changes,
and the purchase money counted apart at the end of the day."""

import datetime as dt
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.fleet import services as fleet
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import services
from apps.purchasing.models import FieldPurchase

pytestmark = pytest.mark.django_db


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def setup():
    """A driver allowed to buy, on a truck, day started with 50 DT of sales cash and 1 000 DT for purchases."""
    organization = OrganizationFactory.create()
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER, can_buy=True)
    owner = MembershipFactory.create(organization=organization, role=Role.OWNER)
    truck = fleet.create_truck(
        organization=organization, actor=UserFactory.create(), name="Camion 1", plate="101 TU 2001", driver=driver.user
    )
    api = client_for(driver)
    fleet.set_day_fund(
        organization=organization,
        actor=owner.user,
        driver=driver.user,
        date=timezone.localdate(),
        opening_cash=Decimal("50"),
        purchase_float=Decimal("1000"),
    )
    opened = api.post(reverse("my-day"), format="json")
    assert opened.status_code == 201, opened.json()
    return {
        "organization": organization,
        "driver": driver,
        "api": api,
        "owner": client_for(owner),
        "truck": truck,
        "supplier": SupplierFactory.create(organization=organization, name="Pêcheur Hamdi"),
        "product": ProductFactory.create(organization=organization, name="Poulpe"),
        "room": StockLocationFactory.create(organization=organization, name="Chambre froide 1"),
    }


def purchase_payload(setup, **changes: Any) -> dict[str, Any]:
    """30 kg of poulpe at 25 DT = 750 DT, 600 DT given in cash."""
    values: dict[str, Any] = {
        "supplier": setup["supplier"].pk,
        "terms": "cash",
        "lines": [{"product": setup["product"].pk, "declared_quantity": "30", "unit_cost": "25.000"}],
        "payments": [{"method": "cash", "amount": "600"}],
        "client_uuid": str(uuid4()),
    }
    values.update(changes)
    return values


def send(setup, **changes: Any):
    return setup["api"].post(reverse("my-field-purchases"), purchase_payload(setup, **changes), format="json")


# ---- The switch ----


def test_only_a_driver_allowed_to_buy_sends_a_purchase(setup):
    other = MembershipFactory.create(organization=setup["organization"], role=Role.DRIVER)
    refused = client_for(other).post(reverse("my-field-purchases"), purchase_payload(setup), format="json")
    assert refused.status_code == 403
    assert client_for(other).get(reverse("my-suppliers")).status_code == 403
    # A driver may still read their own (empty) list.
    assert client_for(other).get(reverse("my-field-purchases")).json() == []
    # The office has no use of the phone's endpoints.
    assert setup["owner"].get(reverse("my-field-purchases")).status_code == 403


def test_the_owner_switches_buying_on_and_the_session_says_so(setup):
    other = MembershipFactory.create(organization=setup["organization"], role=Role.DRIVER)
    assert client_for(other).get(reverse("me")).json()["can_buy"] is False

    switched = setup["owner"].patch(reverse("member-can-buy", args=[other.pk]), {"can_buy": True}, format="json")

    assert switched.status_code == 200
    assert switched.json()["can_buy"] is True
    assert client_for(other).get(reverse("me")).json()["can_buy"] is True
    assert AuditLog.objects.filter(action="membership.can_buy_set").count() == 1
    manager = MembershipFactory.create(organization=setup["organization"], role=Role.MANAGER)
    assert (
        client_for(manager).patch(reverse("member-can-buy", args=[other.pk]), {"can_buy": False}, format="json")
    ).status_code == 403


# ---- Sent from the phone ----


def test_a_purchase_sent_from_the_phone_waits_for_the_office(setup):
    made_at = timezone.now() - dt.timedelta(hours=1)
    sent = send(setup, made_at=made_at.isoformat(), notes="Payé 600, le reste vendredi.")

    assert sent.status_code == 201, sent.json()
    body = sent.json()
    assert body["status"] == "submitted"
    assert body["total"] == "750.000"
    assert body["rest"] == "150.000"
    assert "partner" not in body["lines"][0]
    purchase = FieldPurchase.objects.get()
    assert purchase.buyer == setup["driver"].user
    assert purchase.made_at == made_at
    assert purchase.bought_on == timezone.localtime(made_at).date()
    listed = setup["api"].get(reverse("my-field-purchases")).json()
    assert [row["number"] for row in listed] == [purchase.number]


def test_a_retry_with_the_same_uuid_makes_one_purchase(setup):
    payload = purchase_payload(setup)
    first = setup["api"].post(reverse("my-field-purchases"), payload, format="json")
    again = setup["api"].post(reverse("my-field-purchases"), payload, format="json")
    assert first.status_code == again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert FieldPurchase.objects.count() == 1


def test_a_new_supplier_and_product_by_name(setup):
    sent = send(
        setup,
        supplier=None,
        proposed_supplier="Hédi, barque bleue",
        proposed_supplier_phone="98 123 456",
        lines=[{"proposed_product": "Pageot", "declared_quantity": "6.5", "unit_cost": "16"}],
        payments=[{"method": "cash", "amount": "104"}],
    )
    assert sent.status_code == 201, sent.json()
    assert sent.json()["supplier"] is None
    assert sent.json()["lines"][0]["proposed_product"] == "Pageot"


def test_suppliers_and_last_costs_for_the_phone(setup):
    names = [row["name"] for row in setup["api"].get(reverse("my-suppliers")).json()]
    assert names == ["Pêcheur Hamdi"]
    costs = setup["api"].get(reverse("my-purchase-costs"), {"supplier": setup["supplier"].pk})
    assert costs.status_code == 200


# ---- Changed by the driver ----


def test_the_driver_changes_a_purchase_and_the_office_values_stay(setup):
    sent = send(setup).json()
    purchase = FieldPurchase.objects.get()
    # The office counted 29 kg and chose the place, with a note.
    line = purchase.lines.get()
    services.update_field_purchase(
        purchase=purchase,
        actor=None,
        revision=1,
        fields={
            "supplier": purchase.supplier,
            "bought_on": purchase.bought_on,
            "terms": "cash",
            "location": setup["room"],
            "lines": [
                {
                    "product": line.product,
                    "declared_quantity": line.declared_quantity,
                    "received_quantity": "29",
                    "unit_cost": line.unit_cost,
                }
            ],
            "payments": [{"method": "cash", "amount": "600"}],
        },
        office_note="29 kg au froid.",
    )

    changed = setup["api"].put(
        reverse("my-field-purchase", args=[sent["id"]]),
        {**purchase_payload(setup, payments=[{"method": "cash", "amount": "700"}]), "revision": 2},
        format="json",
    )

    assert changed.status_code == 200, changed.json()
    body = changed.json()
    assert body["revision"] == 3
    assert body["lines"][0]["received_quantity"] == "29.000"
    assert body["office_note"] == "29 kg au froid."
    assert body["paid"] == "700.000"
    purchase.refresh_from_db()
    assert purchase.location == setup["room"]


def test_the_driver_cannot_save_over_a_newer_revision_nor_change_a_decided_one(setup):
    sent = send(setup).json()
    stale = setup["api"].put(
        reverse("my-field-purchase", args=[sent["id"]]), {**purchase_payload(setup), "revision": 7}, format="json"
    )
    assert stale.status_code == 400
    assert "revision" in stale.json()

    purchase = FieldPurchase.objects.get()
    services.refuse_field_purchase(purchase=purchase, actor=None, revision=1, note="Doublon.")
    decided = setup["api"].put(
        reverse("my-field-purchase", args=[sent["id"]]), {**purchase_payload(setup), "revision": 2}, format="json"
    )
    assert decided.status_code == 400


def test_a_driver_only_changes_their_own_purchase(setup):
    sent = send(setup).json()
    other = MembershipFactory.create(organization=setup["organization"], role=Role.DRIVER, can_buy=True)
    response = client_for(other).put(
        reverse("my-field-purchase", args=[sent["id"]]), {**purchase_payload(setup), "revision": 1}, format="json"
    )
    assert response.status_code == 404


# ---- The purchase money at the end of the day ----


def summary(setup) -> dict[str, Any]:
    response = setup["api"].get(reverse("my-day-summary"))
    assert response.status_code == 200, response.json()
    figures: dict[str, Any] = response.json()["summary"]
    return figures


def test_cash_given_at_the_port_comes_out_of_the_purchase_money(setup):
    send(setup)  # 600 DT cash
    send(setup, payments=[{"method": "cheque", "amount": "750", "reference": "CH-1"}])

    figures = summary(setup)

    assert figures["purchase_float"] == "1000.000"
    assert figures["purchases_count"] == 2
    assert figures["purchases_total"] == "1500.000"
    assert figures["purchases_cash"] == "600.000"
    assert figures["purchases_other"] == "750.000"
    assert figures["purchases_from_sales"] == "0.000"
    assert figures["expected_purchase_cash"] == "400.000"
    # The sales cash is untouched.
    assert figures["expected_cash"] == "50.000"


def big_lines(setup) -> list[dict[str, Any]]:
    """50 kg of poulpe at 25 DT = 1 250 DT: room for more cash than the purchase money."""
    return [{"product": setup["product"].pk, "declared_quantity": "50", "unit_cost": "25.000"}]


def test_cash_beyond_the_purchase_money_comes_from_the_sales_cash(setup):
    send(setup, lines=big_lines(setup), payments=[{"method": "cash", "amount": "1030"}])

    figures = summary(setup)

    assert figures["purchases_from_sales"] == "30.000"
    assert figures["expected_purchase_cash"] == "0.000"
    assert figures["expected_cash"] == "20.000"


def test_cash_the_driver_paid_out_of_pocket_is_owed_back_not_a_gap(setup):
    send(
        setup, lines=big_lines(setup), payments=[{"method": "cash", "amount": "1100"}]
    )  # 100 beyond the float, 50 in hand

    figures = summary(setup)

    # The 100 DT beyond the purchase money: 50 from the sales cash, 50 out of pocket, never both (D-182).
    assert figures["purchases_from_sales"] == "50.000"
    assert figures["owed_to_driver"] == "50.000"
    assert figures["expected_cash"] == "0.000"


def test_a_refused_purchase_gives_its_money_back(setup):
    send(setup)
    services.refuse_field_purchase(purchase=FieldPurchase.objects.get(), actor=None, revision=1, note="Doublon.")
    assert summary(setup)["expected_purchase_cash"] == "1000.000"


def test_the_closing_counts_the_purchase_money_apart(setup):
    send(setup)
    closed = setup["api"].post(
        reverse("my-day-closing"), {"counted_cash": "50", "counted_purchase_cash": "390"}, format="json"
    )
    assert closed.status_code == 201, closed.json()
    closing = closed.json()["closing"]
    assert closing["expected_purchase_cash"] == "400.000"
    assert closing["counted_purchase_cash"] == "390.000"
    assert closing["purchase_difference"] == "-10.000"
    assert closing["difference"] == "0.000"
    # Bought after the day was sent: refused, as an expense would be.
    late = send(setup)
    assert late.status_code == 403


def test_the_purchase_money_can_be_typed_again_while_the_day_runs(setup):
    changed = setup["api"].put(reverse("my-purchase-float"), {"purchase_float": "1500"}, format="json")
    assert changed.status_code == 200
    assert changed.json()["purchase_float"] == "1500.000"
    assert summary(setup)["expected_purchase_cash"] == "1500.000"
    setup["api"].post(reverse("my-day-closing"), {"counted_cash": "50", "counted_purchase_cash": "1500"}, format="json")
    after = setup["api"].put(reverse("my-purchase-float"), {"purchase_float": "2000"}, format="json")
    assert after.status_code == 400


def test_a_closing_without_purchases_needs_no_second_count(setup):
    closed = setup["api"].post(reverse("my-day-closing"), {"counted_cash": "50"}, format="json")
    assert closed.status_code == 201
    # The 1 000 DT given for purchases and not counted back: a gap the office sees.
    assert closed.json()["closing"]["purchase_difference"] == "-1000.000"
    assert Decimal(closed.json()["closing"]["difference"]) == 0


def test_a_purchase_sent_from_the_phone_goes_to_the_drivers_truck(setup):
    """D-212: the goods are on the driver's truck, not in a cold room, unless the office chooses another place."""
    assert send(setup).status_code == 201
    purchase = FieldPurchase.objects.get()
    assert purchase.location == setup["truck"].location


def test_the_office_sees_the_purchase_on_the_drivers_day_until_it_is_checked(setup):
    """D-212: the purchase is on the day in "Journées des chauffeurs", to check, with its total and cash."""
    sent = send(setup)
    assert sent.status_code == 201
    rows = setup["owner"].get(reverse("day-overview-list")).json()
    assert rows[0]["purchases_count"] == 1
    assert rows[0]["purchases_total"] == "750.000"
    detail = setup["owner"].get(reverse("day-overview-detail", args=[rows[0]["id"]])).json()
    assert detail["purchases"] == [
        {
            "id": sent.json()["id"],
            "number": sent.json()["number"],
            "supplier_name": "Pêcheur Hamdi",
            "status": "submitted",
            "total": "750.000",
            "cash": "600.000",
            "made_at": detail["purchases"][0]["made_at"],
        }
    ]
