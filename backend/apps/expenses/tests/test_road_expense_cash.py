"""'La caisse' on a driver's road expense pays out of the day's cash, so a day started with 0 DT, or not started, is
refused; 'Ma poche' and 'Carte' stay open (D-220)."""

from decimal import Decimal
from uuid import uuid4

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.core.models import Role
from apps.expenses.models import Expense
from apps.fleet import services as fleet_services

from .conftest import client_for, member

pytestmark = pytest.mark.django_db


def driver_on(organization, actor, truck, *, opening_cash=None):
    """A driver on the truck today; with `opening_cash`, the office sets that cash and the driver starts the day
    (D-203)."""
    driver = member(organization, Role.DRIVER)
    today = timezone.localdate()
    fleet_services.assign_truck(organization=organization, actor=actor, truck=truck, driver=driver.user, date=today)
    if opening_cash is not None:
        fleet_services.set_day_fund(
            organization=organization,
            actor=actor,
            driver=driver.user,
            date=today,
            opening_cash=Decimal(opening_cash),
        )
        fleet_services.accept_day_fund(organization=organization, actor=driver.user, truck=truck, date=today)
    return driver


def spend(driver, fuel, paid_with):
    return client_for(driver).post(
        reverse("my-expenses"),
        {"category": fuel.pk, "amount": "12.000", "paid_with": paid_with, "client_uuid": str(uuid4())},
        format="multipart",
    )


def test_la_caisse_is_refused_on_a_day_started_with_0_dt_and_the_other_ways_stay(organization, actor, truck, fuel):
    driver = driver_on(organization, actor, truck, opening_cash="0")

    refused = spend(driver, fuel, "cash")

    assert refused.status_code == 400
    assert "0 DT" in refused.json()["paid_with"][0]
    assert Expense.objects.filter(organization=organization).count() == 0
    assert spend(driver, fuel, "pocket").status_code == 201
    assert spend(driver, fuel, "card").status_code == 201


def test_la_caisse_is_allowed_on_a_day_with_starting_cash(organization, actor, truck, fuel):
    driver = driver_on(organization, actor, truck, opening_cash="50")

    assert spend(driver, fuel, "cash").status_code == 201


def test_la_caisse_is_refused_before_the_day_starts(organization, actor, truck, fuel):
    driver = driver_on(organization, actor, truck)

    refused = spend(driver, fuel, "cash")

    assert refused.status_code == 400
    assert "pas commencée" in refused.json()["paid_with"][0]
    assert spend(driver, fuel, "pocket").status_code == 201
