"""Maintenance types, plans per truck or cold room, and "Entretien effectué" (P10-T02, P10-T03, D-295)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.expenses.models import Expense, ExpenseStatus
from apps.fleet import services as fleet
from apps.inventory import services as inventory
from apps.maintenance import selectors, services
from apps.maintenance.models import MaintenancePlan, MaintenanceType, OdometerReading, OdometerSource

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    organization = OrganizationFactory.create()
    actor = UserFactory.create()
    truck = fleet.create_truck(organization=organization, actor=actor, name="Camion 1", plate="101 TU 2001")
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    office = APIClient()
    office.force_authenticate(manager.user)
    return {"organization": organization, "truck": truck, "user": manager.user, "office": office}


def reading(shop, km: int, days_ago: int = 0) -> None:
    row = OdometerReading.objects.create(
        organization=shop["organization"],
        truck=shop["truck"],
        km=km,
        source=OdometerSource.OFFICE,
        recorded_by=shop["user"],
    )
    OdometerReading.objects.filter(pk=row.pk).update(created_at=timezone.now() - dt.timedelta(days=days_ago))


def test_add_months_keeps_the_last_day_of_a_short_month():
    assert selectors.add_months(dt.date(2026, 1, 31), 1) == dt.date(2026, 2, 28)
    assert selectors.add_months(dt.date(2026, 11, 15), 3) == dt.date(2027, 2, 15)


def test_the_suggested_types_are_added_once_and_stay_settings(shop):
    office = shop["office"]
    assert office.post(reverse("maintenance-type-defaults")).json()["added"] == len(services.DEFAULT_TYPES)
    assert office.post(reverse("maintenance-type-defaults")).json()["added"] == 0
    oil = MaintenanceType.objects.get(name__startswith="Vidange")
    changed = office.patch(reverse("maintenance-type-detail", args=[oil.pk]), {"every_km": 15000}, format="json")
    assert changed.json()["every_km"] == 15000
    refused = office.post(
        reverse("maintenance-type-list"), {"name": "Groupe", "target": "frigo", "every_km": 5000}, format="json"
    )
    assert refused.status_code == 400  # a frigo unit is followed in months
    nothing = office.post(reverse("maintenance-type-list"), {"name": "Lavage"}, format="json")
    assert "every_months" in nothing.json()
    frigo = office.get(reverse("maintenance-type-list"), {"target": "frigo"}).json()
    assert [t["name"] for t in frigo] == ["Entretien du groupe frigo"]


def test_a_plan_is_due_by_km_or_months_whichever_comes_first(shop):
    organization, truck = shop["organization"], shop["truck"]
    oil = services.create_type(
        organization=organization, actor=shop["user"], name="Vidange", every_km=10000, every_months=6, warn_km=1000
    )
    today = timezone.localdate()
    plan = services.create_plan(
        organization=organization,
        actor=shop["user"],
        kind=oil,
        truck=truck,
        last_done_on=today - dt.timedelta(days=30),
        last_done_km=100000,
    )
    reading(shop, 104000, days_ago=20)
    reading(shop, 108000)
    [status] = selectors.plan_statuses(organization, truck_id=truck.pk)
    assert (status.due_km, status.km_left, status.state) == (110000, 2000, "ok")
    assert status.estimated_on == today + dt.timedelta(days=10)  # 200 km a day
    reading(shop, 109500)
    assert selectors.plan_statuses(organization, truck_id=truck.pk)[0].state == "soon"
    reading(shop, 110200)
    assert selectors.plan_statuses(organization, truck_id=truck.pk)[0].state == "late"
    # By the months: six months since, whatever the km.
    services.update_plan(
        plan=plan, actor=shop["user"], last_done_on=today - dt.timedelta(days=200), last_done_km=110000
    )
    assert selectors.plan_statuses(organization, truck_id=truck.pk)[0].state == "late"


def test_a_plan_never_done_asks_when_it_was_last_done(shop):
    oil = services.create_type(organization=shop["organization"], actor=shop["user"], name="Vidange", every_km=10000)
    services.create_plan(organization=shop["organization"], actor=shop["user"], kind=oil, truck=shop["truck"])

    rows = shop["office"].get(reverse("maintenance-plan-list"), {"truck": shop["truck"].pk}).json()

    assert [(r["type"]["name"], r["state"], r["truck"]["name"]) for r in rows] == [("Vidange", "unknown", "Camion 1")]
    again = shop["office"].post(
        reverse("maintenance-plan-list"), {"type": oil.pk, "truck": shop["truck"].pk}, format="json"
    )
    assert again.status_code == 400  # already followed


def test_a_job_done_moves_the_plan_and_its_cost_is_general_overhead(shop):
    office = shop["office"]
    oil = services.create_type(organization=shop["organization"], actor=shop["user"], name="Vidange", every_km=10000)
    made = office.post(reverse("maintenance-plan-list"), {"type": oil.pk, "truck": shop["truck"].pk}, format="json")
    plan_id = made.json()["id"]
    reading(shop, 50000)

    done = office.post(
        reverse("maintenance-record-list", args=[plan_id]),
        {"done_on": timezone.localdate().isoformat(), "garage": "Garage Ezzit", "cost": "185.500"},
        format="json",
    )

    assert done.status_code == 201
    assert (done.json()["km"], done.json()["cost"]) == (50000, "185.500")  # the truck's last compteur
    expense = Expense.objects.get()
    assert (expense.status, expense.amount, expense.truck_id, expense.batch_id) == (
        ExpenseStatus.APPROVED,
        Decimal("185.500"),
        None,  # not a truck cost of the day: not charged to the lots (owner answer 6)
        None,
    )
    assert expense.category.code == "vehicles"
    plan = MaintenancePlan.objects.get(pk=plan_id)
    assert (plan.last_done_km, plan.last_done_on) == (50000, timezone.localdate())
    free = office.post(
        reverse("maintenance-record-list", args=[plan_id]),
        {"done_on": (timezone.localdate() - dt.timedelta(days=90)).isoformat(), "km": 40000},
        format="json",
    )
    assert free.json()["expense_id"] is None
    assert MaintenancePlan.objects.get(pk=plan_id).last_done_km == 50000  # an older job does not move it back
    assert len(office.get(reverse("maintenance-record-list", args=[plan_id])).json()) == 2


def test_a_cold_room_has_its_monthly_service(shop):
    organization = shop["organization"]
    room = inventory.create_location(organization=organization, actor=shop["user"], kind="cold_room", name="Chambre 1")
    services.add_default_types(organization=organization, actor=shop["user"])
    service = MaintenanceType.objects.get(target="cold_room")
    office = shop["office"]
    assert (
        office.post(
            reverse("maintenance-plan-list"), {"type": service.pk, "truck": shop["truck"].pk}, format="json"
        ).status_code
        == 400
    )

    made = office.post(
        reverse("maintenance-plan-list"),
        {
            "type": service.pk,
            "location": room.pk,
            "last_done_on": (timezone.localdate() - dt.timedelta(days=40)).isoformat(),
        },
        format="json",
    )

    assert made.status_code == 201
    assert (made.json()["location"]["name"], made.json()["every_months"], made.json()["state"]) == (
        "Chambre 1",
        1,
        "late",
    )
    done = office.post(
        reverse("maintenance-record-list", args=[made.json()["id"]]),
        {"done_on": timezone.localdate().isoformat(), "cost": "60", "km": 123},
        format="json",
    )
    assert done.json()["km"] is None  # no compteur on a cold room
    assert Expense.objects.get().category.code == "cold_storage"
    assert office.get(reverse("maintenance-plan-list"), {"location": room.pk}).json()[0]["state"] == "ok"


def test_a_driver_and_an_accountant_cannot_change_plans(shop):
    oil = services.create_type(organization=shop["organization"], actor=shop["user"], name="Vidange", every_km=10000)
    for role in (Role.DRIVER, Role.ACCOUNTANT):
        client = APIClient()
        client.force_authenticate(MembershipFactory.create(organization=shop["organization"], role=role).user)
        body = {"type": oil.pk, "truck": shop["truck"].pk}
        assert client.post(reverse("maintenance-plan-list"), body, format="json").status_code == 403
