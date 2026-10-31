"""A driver starts the day from the phone: picks a truck, then opens the day with the cash float (P3-T01)."""

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.fleet import services

pytestmark = pytest.mark.django_db


def test_a_driver_picks_a_truck_then_opens_the_day():
    organization = OrganizationFactory.create()
    actor = UserFactory.create()
    one = services.create_truck(organization=organization, actor=actor, name="Camion 1", plate="101 TU 2001")
    two = services.create_truck(organization=organization, actor=actor, name="Camion 2", plate="102 TU 2002")
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    other = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    services.assign_truck(
        organization=organization, actor=actor, truck=two, driver=other.user, date=timezone.localdate()
    )
    client = APIClient()
    client.force_authenticate(driver.user)

    choices = client.get(reverse("my-truck-choices")).json()
    assert [(c["name"], c["taken"]) for c in choices] == [("Camion 1", False), ("Camion 2", True)]
    assert client.get(reverse("my-day")).status_code == 404
    assert client.post(reverse("my-day"), format="json").status_code == 400  # no truck yet

    assert client.post(reverse("truck-assignment-list"), {"truck": one.pk}, format="json").status_code == 201
    # Nothing set by the office yet: the driver cannot start (D-203).
    assert client.get(reverse("my-day-fund")).status_code == 404
    refused = client.post(reverse("my-day"), format="json")
    assert refused.status_code == 400
    assert "bureau" in refused.json()["opening_cash"][0]

    office = APIClient()
    office.force_authenticate(MembershipFactory.create(organization=organization, role=Role.MANAGER).user)
    today = timezone.localdate().isoformat()
    body = {"driver": driver.user_id, "date": today, "opening_cash": "40"}
    assert office.put(reverse("day-fund-list"), body, format="json").status_code == 200
    body["opening_cash"] = "50"
    assert office.put(reverse("day-fund-list"), body, format="json").status_code == 200  # changed before it is accepted
    assert client.get(reverse("my-day-fund")).json()["opening_cash"] == "50.000"
    assert client.put(reverse("day-fund-list"), body, format="json").status_code == 403  # a driver never sets it

    opened = client.post(reverse("my-day"), {"opening_cash": "999"}, format="json")  # a typed amount is ignored
    again = client.post(reverse("my-day"), format="json")

    assert opened.status_code == 201
    assert (opened.json()["truck_name"], opened.json()["opening_cash"]) == ("Camion 1", "50.000")
    assert again.json()["opening_cash"] == "50.000"  # the first opening stands
    assert client.get(reverse("my-day-fund")).json()["accepted_at"] is not None
    rows = office.get(reverse("day-fund-list"), {"date": today}).json()
    mine = next(row for row in rows if row["driver"]["id"] == driver.user_id)
    assert (mine["started"], mine["fund"]["opening_cash"]) == (True, "50.000")
    body["opening_cash"] = "70"
    assert (
        office.put(reverse("day-fund-list"), body, format="json").status_code == 400
    )  # accepted: it no longer changes
    assert client.get(reverse("my-day")).json()["id"] == opened.json()["id"]


def test_only_drivers_use_the_driver_day_screens():
    manager = MembershipFactory.create(role=Role.MANAGER)
    client = APIClient()
    client.force_authenticate(manager.user)

    assert client.get(reverse("my-day")).status_code == 403
    assert client.get(reverse("my-truck-choices")).status_code == 403
