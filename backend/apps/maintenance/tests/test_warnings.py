"""Warnings: the daily notifications, the alerts behind the truck badges, and the driver's phone (P10-T05, D-295)."""

import datetime as dt

import pytest
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.fleet import services as fleet
from apps.hr import services as hr
from apps.maintenance import services
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


@pytest.fixture
def shop():
    organization = OrganizationFactory.create()
    actor = UserFactory.create()
    one = fleet.create_truck(organization=organization, actor=actor, name="Camion 1", plate="101 TU 2001")
    two = fleet.create_truck(organization=organization, actor=actor, name="Camion 2", plate="102 TU 2002")
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    office = APIClient()
    office.force_authenticate(manager.user)
    phone = APIClient()
    phone.force_authenticate(driver.user)
    return {
        "organization": organization,
        "one": one,
        "two": two,
        "user": manager.user,
        "driver": driver,
        "office": office,
        "phone": phone,
    }


def in_days(count: int) -> dt.date:
    return timezone.localdate() + dt.timedelta(days=count)


def test_each_warning_is_sent_once_per_step(shop):
    organization, user = shop["organization"], shop["user"]
    paper = services.record_paper(
        organization=organization, actor=user, kind="insurance", truck=shop["one"], expires_on=in_days(20)
    )
    kind = services.create_type(organization=organization, actor=user, name="Vidange", every_months=6)
    services.create_plan(
        organization=organization, actor=user, kind=kind, truck=shop["two"], last_done_on=in_days(-200)
    )

    assert services.send_warnings(organization=organization) == 2
    assert services.send_warnings(organization=organization) == 0  # nothing new
    kinds = sorted(Notification.objects.values_list("kind", flat=True))
    assert kinds == ["maintenance_late", "paper_expires"]
    # The next warning day of the same paper (15 days before) is a new step.
    assert services.send_warnings(organization=organization, today=paper.expires_on - dt.timedelta(days=14)) == 1
    assert services.send_warnings(organization=organization, today=paper.expires_on + dt.timedelta(days=1)) == 1
    assert Notification.objects.filter(kind="paper_expired").count() == 1


def test_the_nightly_command_runs_for_every_organization(shop):
    services.record_paper(
        organization=shop["organization"], actor=shop["user"], kind="vignette", truck=shop["one"], expires_on=in_days(3)
    )
    call_command("maintenance_warnings")
    assert Notification.objects.filter(kind="paper_expires").count() == 1


def test_the_alerts_give_each_truck_its_worst_state(shop):
    organization, user = shop["organization"], shop["user"]
    services.record_paper(
        organization=organization, actor=user, kind="insurance", truck=shop["one"], expires_on=in_days(5)
    )
    services.record_paper(
        organization=organization, actor=user, kind="vignette", truck=shop["one"], expires_on=in_days(-2)
    )
    services.record_paper(
        organization=organization, actor=user, kind="insurance", truck=shop["two"], expires_on=in_days(300)
    )

    alerts = shop["office"].get(reverse("fleet-alerts")).json()

    assert [(a["subject"], a["title"], a["state"]) for a in alerts] == [
        ("Camion 1", "Vignette", "late"),
        ("Camion 1", "Assurance", "soon"),
    ]


def test_the_driver_sees_his_truck_and_his_own_papers_only(shop):
    organization, user, driver = shop["organization"], shop["user"], shop["driver"]
    me = hr.create_employee(organization=organization, actor=user, name="Moi", user=driver.user)
    other = hr.create_employee(organization=organization, actor=user, name="Autre")
    for employee in (me, other):
        services.record_paper(
            organization=organization, actor=user, kind="medical", employee=employee, expires_on=in_days(4)
        )
    services.record_paper(
        organization=organization, actor=user, kind="insurance", truck=shop["one"], expires_on=in_days(4)
    )
    services.record_paper(
        organization=organization, actor=user, kind="insurance", truck=shop["two"], expires_on=in_days(4)
    )
    fleet.assign_truck(
        organization=organization, actor=user, truck=shop["one"], driver=driver.user, date=timezone.localdate()
    )

    mine = shop["phone"].get(reverse("my-alerts")).json()

    assert sorted((a["subject"], a["title"]) for a in mine) == [
        ("Camion 1", "Assurance"),
        ("Moi", "Certificat médical"),
    ]
    assert shop["phone"].get(reverse("fleet-alerts")).status_code == 403
