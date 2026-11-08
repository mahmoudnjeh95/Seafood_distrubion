"""The compteur the driver types when sending the day, and the office's corrections (P10-T01, D-295)."""

import datetime as dt
import io
from decimal import Decimal

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse
from django.utils import timezone
from PIL import Image
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.fleet import services as fleet
from apps.maintenance.models import OdometerReading
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def media(settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    return tmp_path


@pytest.fixture
def road():
    organization = OrganizationFactory.create()
    truck = fleet.create_truck(
        organization=organization, actor=UserFactory.create(), name="Camion 1", plate="101 TU 2001"
    )
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    client = APIClient()
    client.force_authenticate(driver.user)
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    office = APIClient()
    office.force_authenticate(manager.user)
    return {"organization": organization, "truck": truck, "driver": driver, "client": client, "office": office}


def open_day(road):
    return fleet.open_driver_day(
        organization=road["organization"],
        actor=road["driver"].user,
        truck=road["truck"],
        opening_cash=Decimal(0),
        date=timezone.localdate(),
    )


def photo() -> SimpleUploadedFile:
    buffer = io.BytesIO()
    Image.new("RGB", (800, 600), (20, 20, 20)).save(buffer, format="JPEG")
    return SimpleUploadedFile("compteur.jpg", buffer.getvalue(), content_type="image/jpeg")


def test_the_compteur_waits_for_the_day(road):
    assert road["client"].get(reverse("my-odometer")).status_code == 404
    assert road["client"].post(reverse("my-odometer"), {"km": 1000}).status_code == 404


def test_a_driver_types_the_compteur_with_a_photo(road, media):
    open_day(road)
    client = road["client"]
    assert client.get(reverse("my-odometer")).json() == {"last_km": None, "last_at": None, "today_km": None}

    saved = client.post(reverse("my-odometer"), {"km": 120500, "photo": photo()}, format="multipart")

    assert saved.status_code == 201
    body = saved.json()
    assert (body["km"], body["source"], body["warning"], body["driven_km"]) == (120500, "driver", "", None)
    assert body["photo_url"] is not None
    assert client.get(reverse("my-odometer")).json()["today_km"] == 120500
    assert road["office"].get(body["photo_url"]).status_code == 200
    assert client.get(body["photo_url"]).status_code == 403  # the photos are for the office


def test_a_reading_below_the_last_is_refused_until_the_office_corrects_it(road):
    open_day(road)
    client, office, truck = road["client"], road["office"], road["truck"]
    assert client.post(reverse("my-odometer"), {"km": 125000}).status_code == 201

    refused = client.post(reverse("my-odometer"), {"km": 124000})

    assert refused.status_code == 400
    assert "125000" in refused.json()["km"][0]
    url = reverse("truck-odometer", args=[truck.pk])
    assert office.post(url, {"km": 123900}).status_code == 400  # a correction needs its reason
    assert client.post(url, {"km": 123900, "note": "faute"}).status_code == 403  # a driver never corrects
    corrected = office.post(url, {"km": 123900, "note": "Faute de frappe du chauffeur"})
    assert corrected.status_code == 201
    assert corrected.json()["source"] == "office"
    assert client.post(reverse("my-odometer"), {"km": 124000}).json()["driven_km"] == 100
    readings = office.get(url).json()
    assert [r["km"] for r in readings] == [124000, 123900, 125000]
    assert OdometerReading.objects.count() == 3  # nothing was changed or removed


def test_a_big_jump_is_kept_with_a_warning_and_the_office_is_told(road):
    open_day(road)
    client = road["client"]
    client.post(reverse("my-odometer"), {"km": 100000})
    # The last reading two days ago: up to 2 × 600 km is normal.
    OdometerReading.objects.update(created_at=timezone.now() - dt.timedelta(days=2))
    assert client.post(reverse("my-odometer"), {"km": 101200}).json()["warning"] == ""
    assert not Notification.objects.filter(kind="odometer_jump").exists()

    jumped = client.post(reverse("my-odometer"), {"km": 110000})

    assert jumped.status_code == 201
    assert (jumped.json()["warning"], jumped.json()["driven_km"]) == ("big_jump", 8800)
    notice = Notification.objects.get(kind="odometer_jump")
    assert (notice.params["truck"], notice.params["driven"]) == ("Camion 1", 8800)
    fleet_rows = road["office"].get(reverse("fleet-odometer")).json()
    assert [(r["name"], r["last"]["km"], r["warnings"]) for r in fleet_rows] == [("Camion 1", 110000, 1)]


def test_the_limit_is_a_setting(road):
    office = road["office"]
    assert office.get(reverse("maintenance-settings")).json() == {"max_day_km": 600}
    assert road["client"].patch(reverse("maintenance-settings"), {"max_day_km": 50}, format="json").status_code == 403
    assert office.patch(reverse("maintenance-settings"), {"max_day_km": 0}, format="json").status_code == 400
    assert office.patch(reverse("maintenance-settings"), {"max_day_km": 50}, format="json").json() == {"max_day_km": 50}
    open_day(road)
    road["client"].post(reverse("my-odometer"), {"km": 1000})

    assert road["client"].post(reverse("my-odometer"), {"km": 1060}).json()["warning"] == "big_jump"


def test_no_reading_on_a_day_already_sent(road):
    day = open_day(road)
    fleet.end_driver_day(driver_day=day, ended_at=timezone.now())

    refused = road["client"].post(reverse("my-odometer"), {"km": 1000})

    assert refused.status_code == 400
    assert "envoyée" in str(refused.json())


def test_another_organization_sees_nothing(road):
    stranger = APIClient()
    stranger.force_authenticate(MembershipFactory.create(role=Role.OWNER).user)

    assert stranger.get(reverse("truck-odometer", args=[road["truck"].pk])).status_code == 404
    assert stranger.get(reverse("fleet-odometer")).json() == []


def test_settings_without_a_value_are_refused(road):
    assert road["office"].patch(reverse("maintenance-settings"), {}, format="json").status_code == 400
