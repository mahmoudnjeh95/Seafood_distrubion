"""The numbers given out in an organization: prefixes set on Paramètres, counters that never restart (D-223)."""

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core import numbering, selectors, services
from apps.core.models import Role

from .factories import MembershipFactory, OrganizationFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def owner(organization):
    return MembershipFactory.create(organization=organization, role=Role.OWNER)


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def test_each_kind_numbers_in_order_with_its_default_prefix(organization):
    assert numbering.next_number(organization, "delivery_note", year=2026) == "BL-2026-0001"
    assert numbering.next_number(organization, "delivery_note", year=2026) == "BL-2026-0002"
    assert numbering.next_number(organization, "delivery_note", year=2027) == "BL-2027-0001"
    assert numbering.next_number(organization, "batch") == "L-0001"
    assert numbering.next_number(organization, "customer") == "C-001"


def test_a_yearly_kind_is_numbered_for_today_unless_told_otherwise(organization):
    this_year = timezone.localdate().year

    assert numbering.next_number(organization, "invoice") == f"FA-{this_year}-0001"


def test_counters_are_per_organization(organization):
    numbering.next_number(organization, "receipt")

    assert numbering.next_number(OrganizationFactory.create(), "receipt") == "BR-0001"


def test_a_new_prefix_goes_on_from_the_counter(organization, owner):
    numbering.next_number(organization, "invoice", year=2026)
    numbering.next_number(organization, "invoice", year=2026)

    services.set_number_prefixes(organization=organization, actor=owner.user, prefixes=[("invoice", "fact")])

    assert numbering.next_number(organization, "invoice", year=2026) == "FACT-2026-0003"
    assert numbering.prefixes_of(organization)["invoice"] == "FACT"
    assert numbering.prefixes_of(organization)["receipt"] == "BR"


def test_the_next_preview_does_not_take_a_number(organization):
    numbering.next_number(organization, "receipt")

    lines = {line.kind: line for line in selectors.number_lines(organization)}

    assert lines["receipt"].next_number == "BR-0002"
    assert numbering.next_number(organization, "receipt") == "BR-0002"


@pytest.mark.parametrize("prefix", ["", "B-L", "BL 1", "TOOLONG7"])
def test_a_prefix_is_one_to_six_capitals_or_digits(organization, owner, prefix):
    with pytest.raises(ValidationError) as error:
        services.set_number_prefixes(organization=organization, actor=owner.user, prefixes=[("sale", prefix)])

    assert "prefixes.0.prefix" in error.value.message_dict


def test_two_kinds_never_share_a_prefix(organization, owner):
    with pytest.raises(ValidationError) as error:
        services.set_number_prefixes(organization=organization, actor=owner.user, prefixes=[("receipt", "BL")])

    assert "prefixes.0.prefix" in error.value.message_dict


def test_an_unknown_kind_is_refused(organization, owner):
    with pytest.raises(ValidationError) as error:
        services.set_number_prefixes(organization=organization, actor=owner.user, prefixes=[("unknown", "XX")])

    assert "prefixes.0.kind" in error.value.message_dict


def test_only_owners_and_managers_change_the_prefixes(organization, owner):
    url = reverse("numbering")
    body = {"prefixes": [{"kind": "sale", "prefix": "VTE"}]}

    assert client_for(owner).put(url, body, format="json").status_code == 200
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    assert client_for(manager).put(url, body, format="json").status_code == 200
    accountant = MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT)
    assert client_for(accountant).put(url, body, format="json").status_code == 403
    assert client_for(accountant).get(url).status_code == 200
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    assert client_for(driver).get(url).status_code == 403
