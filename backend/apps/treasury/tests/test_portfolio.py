"""The portfolio (P9-T04a, D-216): remise en banque with its bordereau, encaissé, retiré, débité, the totals."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.documents import services as documents
from apps.partners.tests.factories import CustomerFactory, SupplierFactory
from apps.treasury import selectors, services
from apps.treasury.models import Instrument, InstrumentStatus

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


def received(organization, actor, number, amount="100.000", kind="cheque", due_in=0, customer=None):
    return services.register_instrument(
        organization=organization,
        actor=actor,
        direction="received",
        kind=kind,
        number=number,
        bank=selectors.banks_of(organization).get(code="STB"),
        amount=amount,
        issued_on=TODAY() - dt.timedelta(days=10),
        due_on=TODAY() + dt.timedelta(days=due_in),
        customer=customer or CustomerFactory.create(organization=organization, name="Hôtel Les Pins"),
        source_number="RG-0001",
    )


def test_a_remise_en_banque_makes_a_bordereau_then_the_bank_cashes(organization, manager):
    actor = manager.user
    first = received(organization, actor, "1001", "250.500")
    second = received(organization, actor, "T-7", "749.500", kind="bill")
    biat = selectors.banks_of(organization).get(code="BIAT")

    deposit = services.deposit_instruments(
        organization=organization,
        actor=actor,
        instrument_ids=[first.pk, second.pk],
        bank=biat,
        deposited_on=TODAY(),
        notes="Agence Sakiet Ezzit",
    )

    assert deposit.number == f"RB-{TODAY().year}-0001"
    first.refresh_from_db()
    assert (first.status, first.deposit) == (InstrumentStatus.DEPOSITED, deposit)
    listed = selectors.deposit_of(organization, deposit.pk)
    assert (getattr(listed, "effets_count"), getattr(listed, "effets_total")) == (2, D("1000.000"))  # noqa: B009
    html = documents.render_html(documents.printable(organization, "bank_deposit", deposit.pk))
    assert f"Bordereau de remise N° {deposit.number}" in html
    assert "1 chèque et 1 traite" in html
    assert "749,500" in html
    assert "Agence Sakiet Ezzit" in html

    # Already at the bank: not twice.
    with pytest.raises(ValidationError):
        services.deposit_instruments(
            organization=organization, actor=actor, instrument_ids=[first.pk], bank=biat, deposited_on=TODAY()
        )
    services.withdraw_instruments(
        organization=organization, actor=actor, instrument_ids=[second.pk], withdrawn_on=TODAY(), note="Erreur"
    )
    services.cash_instruments(organization=organization, actor=actor, instrument_ids=[first.pk], cashed_on=TODAY())
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, second.status) == (InstrumentStatus.CASHED, InstrumentStatus.PORTFOLIO)
    assert [event.to_status for event in second.events.order_by("id")] == ["portfolio", "deposited", "portfolio"]
    assert AuditLog.objects.filter(action__startswith="treasury.").count() == 3
    # A cashed effet cannot be cashed again; a cheque in portfolio can be cashed at the bank's counter.
    with pytest.raises(ValidationError):
        services.cash_instruments(organization=organization, actor=actor, instrument_ids=[first.pk], cashed_on=TODAY())
    services.cash_instruments(organization=organization, actor=actor, instrument_ids=[second.pk], cashed_on=TODAY())


def test_every_batch_problem_is_refused(organization, manager):
    actor = manager.user
    effet = received(organization, actor, "1")
    other = MembershipFactory.create(role=Role.MANAGER).organization
    elsewhere = received(other, actor, "2", customer=CustomerFactory.create(organization=other))
    with pytest.raises(ValidationError) as empty:
        services.cash_instruments(organization=organization, actor=actor, instrument_ids=[], cashed_on=None)
    assert set(empty.value.message_dict) == {"instruments", "day"}
    with pytest.raises(ValidationError) as future:
        services.cash_instruments(
            organization=organization, actor=actor, instrument_ids=[effet.pk], cashed_on=TODAY() + dt.timedelta(days=1)
        )
    assert set(future.value.message_dict) == {"day"}
    with pytest.raises(ValidationError) as foreign:
        services.cash_instruments(
            organization=organization, actor=actor, instrument_ids=[effet.pk, elsewhere.pk], cashed_on=TODAY()
        )
    assert "instruments" in foreign.value.message_dict
    with pytest.raises(ValidationError) as no_bank:
        services.deposit_instruments(
            organization=organization, actor=actor, instrument_ids=[effet.pk], bank=None, deposited_on=TODAY()
        )
    assert set(no_bank.value.message_dict) == {"bank"}
    # Ours are debited, never deposited.
    with pytest.raises(ValidationError):
        services.debit_instruments(
            organization=organization, actor=actor, instrument_ids=[effet.pk], debited_on=TODAY()
        )


def test_the_api_lists_moves_and_adds_up_the_portfolio(organization, manager):
    actor = manager.user
    late = received(organization, actor, "L1", "300", due_in=-5)
    soon = received(organization, actor, "S1", "200", due_in=5)
    ours = services.register_instrument(
        organization=organization,
        actor=actor,
        direction="issued",
        kind="cheque",
        number="9001",
        bank=selectors.banks_of(organization).get(code="BIAT"),
        amount="80",
        issued_on=TODAY(),
        due_on=TODAY(),
        supplier=SupplierFactory.create(organization=organization),
    )
    api = APIClient()
    api.force_authenticate(actor)

    totals = api.get(reverse("treasury-instrument-totals"), {"direction": "received"}).json()
    assert totals["count"] == 2
    assert totals["by_status"] == {"portfolio": {"count": 2, "total": "500.000"}}
    assert (totals["overdue_count"], totals["overdue_total"]) == (1, "300.000")

    biat = selectors.banks_of(organization).get(code="BIAT")
    created = api.post(
        reverse("treasury-deposit-list"),
        {"instruments": [late.pk, soon.pk], "bank": biat.pk, "deposited_on": TODAY().isoformat()},
        format="json",
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    assert (body["effets_count"], body["effets_total"], body["bank"]["code"]) == (2, "500.000", "BIAT")
    assert [row["number"] for row in body["instruments"]] == ["L1", "S1"]
    listed = api.get(reverse("treasury-instrument-list"), {"deposit": body["id"]}).json()["results"]
    assert {row["deposit"]["number"] for row in listed} == {body["number"]}

    cashed = api.post(
        reverse("treasury-instrument-cash"), {"instruments": [late.pk], "day": TODAY().isoformat()}, format="json"
    )
    assert cashed.status_code == 200, cashed.json()
    assert cashed.json()[0]["status"] == "cashed"
    debited = api.post(
        reverse("treasury-instrument-debit"), {"instruments": [ours.pk], "day": TODAY().isoformat()}, format="json"
    )
    assert debited.json()[0]["status"] == "debited"
    assert Instrument.objects.get(pk=soon.pk).status == InstrumentStatus.DEPOSITED
    assert api.get(reverse("treasury-deposit-list")).json()["count"] == 1

    accountant = APIClient()
    accountant.force_authenticate(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT).user)
    assert accountant.get(reverse("treasury-deposit-detail", args=[body["id"]])).status_code == 200
    refused = accountant.post(
        reverse("treasury-instrument-withdraw"), {"instruments": [soon.pk], "day": TODAY().isoformat()}, format="json"
    )
    assert refused.status_code == 403
