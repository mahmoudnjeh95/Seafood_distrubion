"""Papers of the trucks and the people, their warnings, and the truck block with the owner's day (P10-T04, D-295)."""

import datetime as dt
import io

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.expenses.models import Expense
from apps.fleet import services as fleet
from apps.hr import services as hr

pytestmark = pytest.mark.django_db


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def shop():
    organization = OrganizationFactory.create()
    truck = fleet.create_truck(
        organization=organization, actor=UserFactory.create(), name="Camion 1", plate="101 TU 2001"
    )
    owner = MembershipFactory.create(organization=organization, role=Role.OWNER)
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    clients = {}
    for name, member in (("owner", owner), ("manager", manager), ("driver", driver)):
        clients[name] = APIClient()
        clients[name].force_authenticate(member.user)
    employee = hr.create_employee(organization=organization, actor=owner.user, name="Ali Ben Salah")
    return {"organization": organization, "truck": truck, "driver_member": driver, "employee": employee, **clients}


def day(offset: int) -> str:
    return (timezone.localdate() + dt.timedelta(days=offset)).isoformat()


def scan() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (400, 300), (250, 250, 250)).save(buffer, format="JPEG")
    return SimpleUploadedFile("assurance.jpg", buffer.getvalue(), content_type="image/jpeg")


def test_the_board_shows_each_paper_and_its_state(shop, media):
    manager, truck = shop["manager"], shop["truck"]
    body = {
        "kind": "insurance",
        "truck": truck.pk,
        "expires_on": day(10),
        "number": "A-123",
        "cost": "420",
        "scan": scan(),
    }
    made = manager.post(reverse("paper-list"), body, format="multipart")
    assert made.status_code == 201
    assert made.json()["scan_url"] is not None
    assert manager.get(made.json()["scan_url"]).status_code == 200
    manager.post(
        reverse("paper-list"),
        {"kind": "licence", "employee": shop["employee"].pk, "expires_on": day(400)},
        format="json",
    )

    board = manager.get(reverse("paper-board")).json()

    states = {(row["subject"], row["kind"]): row["state"] for row in board}
    assert states[("Camion 1", "insurance")] == "soon"  # within 30 days
    assert states[("Camion 1", "technical_visit")] == "missing"
    assert states[("Ali Ben Salah", "licence")] == "ok"
    assert states[("Ali Ben Salah", "health_card")] == "missing"
    expense = Expense.objects.get()
    assert (expense.category.code, expense.truck_id) == ("vehicles", None)  # general overhead


def test_a_renewal_becomes_the_current_paper(shop):
    manager, truck = shop["manager"], shop["truck"]
    manager.post(reverse("paper-list"), {"kind": "vignette", "truck": truck.pk, "expires_on": day(-5)}, format="json")
    assert next(r for r in manager.get(reverse("paper-board")).json() if r["kind"] == "vignette")["state"] == "expired"
    manager.post(reverse("paper-list"), {"kind": "vignette", "truck": truck.pk, "expires_on": day(360)}, format="json")

    row = next(r for r in manager.get(reverse("paper-board")).json() if r["kind"] == "vignette")

    assert (row["state"], row["days_left"]) == ("ok", 360)
    assert len(manager.get(reverse("paper-list"), {"truck": truck.pk}).json()) == 2


def test_a_paper_goes_on_the_right_subject(shop):
    manager = shop["manager"]
    wrong = manager.post(
        reverse("paper-list"), {"kind": "licence", "truck": shop["truck"].pk, "expires_on": day(30)}, format="json"
    )
    assert "employee" in wrong.json()
    backwards = manager.post(
        reverse("paper-list"),
        {"kind": "insurance", "truck": shop["truck"].pk, "issued_on": day(0), "expires_on": day(-1)},
        format="json",
    )
    assert "expires_on" in backwards.json()


def test_an_expired_assurance_blocks_the_truck_until_the_owner_allows_the_day(shop):
    manager, owner, truck, driver = shop["manager"], shop["owner"], shop["truck"], shop["driver_member"]
    manager.post(reverse("paper-list"), {"kind": "insurance", "truck": truck.pk, "expires_on": day(-1)}, format="json")
    body = {"truck": truck.pk, "driver": driver.user_id, "date": day(0)}

    refused = manager.post(reverse("truck-assignment-list"), body, format="json")

    assert refused.status_code == 400
    assert "Assurance" in refused.json()["truck"][0]
    allow = {"date": day(0), "reason": "Assurance payée, attestation demain"}
    url = reverse("truck-day-allowances", args=[truck.pk])
    assert manager.post(url, allow, format="json").status_code == 403  # the owner only
    assert owner.post(url, {"date": day(0), "reason": " "}, format="json").status_code == 400
    assert owner.post(url, allow, format="json").status_code == 201
    assert owner.post(url, allow, format="json").status_code == 400  # once per day
    assert manager.post(reverse("truck-assignment-list"), body, format="json").status_code == 201
    assert [row["reason"] for row in manager.get(url).json()] == [allow["reason"]]


def test_a_truck_without_papers_typed_is_not_blocked(shop):
    body = {"truck": shop["truck"].pk, "driver": shop["driver_member"].user_id, "date": day(0)}
    assert shop["manager"].post(reverse("truck-assignment-list"), body, format="json").status_code == 201


def test_the_warning_days_are_a_setting(shop):
    manager = shop["manager"]
    assert manager.get(reverse("maintenance-settings")).json()["paper_warn_days"] == [30, 15, 7]
    saved = manager.patch(reverse("maintenance-settings"), {"paper_warn_days": [7, 60, 7]}, format="json")
    assert saved.json()["paper_warn_days"] == [60, 7]
    manager.post(
        reverse("paper-list"), {"kind": "extinguisher", "truck": shop["truck"].pk, "expires_on": day(45)}, format="json"
    )
    row = next(r for r in manager.get(reverse("paper-board")).json() if r["kind"] == "extinguisher")
    assert row["state"] == "soon"


def test_a_driver_sees_no_papers_board(shop):
    assert shop["driver"].get(reverse("paper-board")).status_code == 403


@pytest.mark.django_db(transaction=True)
def test_assigning_a_truck_runs_in_its_own_transaction():
    # Without a test transaction around it, as the real server runs: the paper check must not break the truck lock.
    organization = OrganizationFactory.create()
    actor = UserFactory.create()
    truck = fleet.create_truck(organization=organization, actor=actor, name="Camion 9", plate="109 TU 2009")
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)

    assignment = fleet.assign_truck(
        organization=organization, actor=actor, truck=truck, driver=driver.user, date=timezone.localdate()
    )

    assert assignment.truck_id == truck.pk
