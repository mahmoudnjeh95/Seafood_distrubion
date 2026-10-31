"""Banks and effets (D-196, P9-T01)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import services as sales
from apps.treasury import selectors, services
from apps.treasury.models import InstrumentStatus

pytestmark = pytest.mark.django_db

D = Decimal


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


# ---- banks ----


def test_a_new_organization_gets_the_tunisian_banks_once():
    organization = OrganizationFactory.create()
    codes = list(selectors.banks_of(organization).values_list("code", flat=True))
    assert len(codes) == len(services.DEFAULT_BANKS)
    assert {"BIAT", "STB", "BNA", "ATTIJARI", "ZITOUNA", "POSTE"} <= set(codes)
    services.ensure_default_banks(organization=organization)
    assert selectors.banks_of(organization).count() == len(codes)


def test_banks_are_added_renamed_and_taken_off_the_list(organization):
    actor = UserFactory.create()
    bank = services.create_bank(organization=organization, actor=actor, code=" tsb ", name="  Tunisian   Saudi Bank ")
    assert (bank.code, bank.name, bank.is_active) == ("TSB", "Tunisian Saudi Bank", True)
    with pytest.raises(ValidationError) as refused:
        services.create_bank(organization=organization, actor=actor, code="biat", name="")
    assert set(refused.value.message_dict) == {"code", "name"}

    services.update_bank(bank=bank, actor=actor, code="TSB", name="TSB Bank", is_active=False)
    assert bank.pk not in selectors.banks_of(organization, active_only=True).values_list("pk", flat=True)
    assert selectors.banks_of(organization).get(pk=bank.pk).name == "TSB Bank"
    assert AuditLog.objects.filter(organization=organization, action__startswith="bank.").count() == 2


def test_banks_api_reads_for_the_office_and_writes_for_owner_or_manager(organization, manager):
    accountant = MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT)
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    url = reverse("treasury-bank-list")

    assert client_for(driver).get(url).status_code == 403
    listed = client_for(accountant).get(url)
    assert listed.status_code == 200
    assert listed.json()[0]["code"] == "AMEN"
    assert client_for(accountant).post(url, {"code": "X", "name": "X"}, format="json").status_code == 403

    created = client_for(manager).post(url, {"code": "NEW", "name": "Nouvelle Banque"}, format="json")
    assert created.status_code == 201
    bank_id = created.json()["id"]
    changed = client_for(manager).put(
        reverse("treasury-bank-detail", args=[bank_id]),
        {"code": "NEW", "name": "Nouvelle Banque", "is_active": False},
        format="json",
    )
    assert changed.json()["is_active"] is False
    assert bank_id not in [row["id"] for row in client_for(manager).get(url).json()]
    assert bank_id in [row["id"] for row in client_for(manager).get(url, {"active_only": "false"}).json()]

    elsewhere = MembershipFactory.create(role=Role.MANAGER)
    assert (
        client_for(elsewhere)
        .put(reverse("treasury-bank-detail", args=[bank_id]), {"code": "A", "name": "A"}, format="json")
        .status_code
        == 404
    )


# ---- effets ----


def test_the_portfolio_lists_effets_soonest_due_first_with_filters(organization, manager):
    customer = CustomerFactory.create(organization=organization, name="Poissonnerie du Port")
    other = CustomerFactory.create(organization=organization, name="Hôtel Les Pins")
    bank = selectors.banks_of(organization).get(code="BIAT")
    today = timezone.localdate()
    for who, number, days in ((customer, "TR-2", 60), (customer, "TR-1", 30), (other, "CH-9", 0)):
        sales.record_customer_payment(
            organization=organization,
            actor=manager.user,
            customer=who,
            lines=[
                {
                    "method": "bill" if number.startswith("TR") else "cheque",
                    "amount": "100.000",
                    "number": number,
                    "bank": bank,
                    "due_on": today + dt.timedelta(days=days),
                }
            ],
        )
    api = client_for(manager)
    url = reverse("treasury-instrument-list")

    rows = api.get(url).json()["results"]
    assert [row["number"] for row in rows] == ["CH-9", "TR-1", "TR-2"]
    assert rows[0]["bank"]["code"] == "BIAT"
    assert rows[0]["customer"]["name"] == "Hôtel Les Pins"
    assert rows[0]["status"] == "portfolio"

    assert [row["number"] for row in api.get(url, {"kind": "bill"}).json()["results"]] == ["TR-1", "TR-2"]
    assert [row["number"] for row in api.get(url, {"customer": other.pk}).json()["results"]] == ["CH-9"]
    due_to = (today + dt.timedelta(days=31)).isoformat()
    assert [row["number"] for row in api.get(url, {"due_to": due_to}).json()["results"]] == ["CH-9", "TR-1"]
    assert [row["number"] for row in api.get(url, {"search": "port"}).json()["results"]] == ["TR-1", "TR-2"]
    assert api.get(url, {"status": "portfolio,cashed"}).json()["count"] == 3
    assert api.get(url, {"status": "lost"}).status_code == 400
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    assert client_for(driver).get(url).status_code == 403


def test_an_effet_moves_only_along_its_life(organization):
    actor = UserFactory.create()
    customer = CustomerFactory.create(organization=organization)
    bank = selectors.banks_of(organization).get(code="STB")
    effet = services.register_instrument(
        organization=organization,
        actor=actor,
        direction="received",
        kind="cheque",
        number="555",
        bank=bank,
        amount="12.500",
        issued_on=timezone.localdate(),
        due_on=None,
        customer=customer,
        source_number="RG-0009",
    )
    assert (effet.status, effet.amount, effet.due_on) == (InstrumentStatus.PORTFOLIO, D("12.500"), timezone.localdate())
    services.cancel_instruments(instrument_ids=[effet.pk], actor=actor, happened_on=timezone.localdate())
    effet.refresh_from_db()
    assert effet.status == InstrumentStatus.CANCELLED
    # A cancelled effet goes nowhere.
    with pytest.raises(ValidationError):
        services.cancel_instruments(instrument_ids=[effet.pk], actor=actor, happened_on=timezone.localdate())
    with pytest.raises(ValidationError) as refused:
        services.register_instrument(
            organization=organization,
            actor=actor,
            direction="received",
            kind="bill",
            number="",
            bank=None,
            amount="0",
            issued_on=timezone.localdate(),
            due_on=None,
            customer=customer,
        )
    assert set(refused.value.message_dict) == {"number", "bank", "due_on", "amount"}
