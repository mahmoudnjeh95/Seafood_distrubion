"""Cold-chain readings (D-300): a range per place, readings outside it flagged and told to the office."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.inventory import selectors, services
from apps.inventory.models import LocationKind
from apps.inventory.tests.factories import StockLocationFactory
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db


def test_a_reading_outside_the_range_is_flagged_and_the_office_told():
    organization = OrganizationFactory.create()
    room = StockLocationFactory.create(organization=organization, kind=LocationKind.COLD_ROOM, name="Négative")
    services.set_temperature_range(location=room, actor=None, temp_min="", temp_max="-18")

    fine = services.record_temperature(location=room, actor=None, celsius="-20,5")
    warm = services.record_temperature(location=room, actor=None, celsius="-12")

    assert (fine.celsius, fine.out_of_range) == (Decimal("-20.5"), False)
    assert warm.out_of_range is True
    assert list(Notification.objects.filter(organization=organization).values_list("kind", flat=True)) == [
        "temperature_alert"
    ]
    place = next(row for row in selectors.cold_chain_overview(organization) if row.location.pk == room.pk)
    assert place.last == warm
    assert (place.readings_today, place.alerts_7_days) == (2, 1)


def test_bad_values_are_refused():
    organization = OrganizationFactory.create()
    room = StockLocationFactory.create(organization=organization, kind=LocationKind.COLD_ROOM)

    with pytest.raises(ValidationError) as refused:
        services.record_temperature(location=room, actor=None, celsius="froid")
    assert "celsius" in refused.value.message_dict
    with pytest.raises(ValidationError) as refused:
        services.set_temperature_range(location=room, actor=None, temp_min="4", temp_max="0")
    assert "temp_max" in refused.value.message_dict


def test_the_api_lists_and_records():
    membership = MembershipFactory.create(role="manager", organization=OrganizationFactory.create())
    room = StockLocationFactory.create(organization=membership.organization, kind=LocationKind.COLD_ROOM)
    client = APIClient()
    client.force_authenticate(membership.user)

    made = client.post(reverse("temperature-list"), {"location": room.pk, "celsius": "3.5"}, format="json")
    listed = client.get(reverse("temperature-list"))
    overview = client.get(reverse("cold-chain"))

    assert made.status_code == 201
    assert listed.json()["count"] == 1
    assert overview.json()[0]["last"]["celsius"] == "3.5"
