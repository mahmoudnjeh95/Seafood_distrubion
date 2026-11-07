"""D-287: "Refacturer" a fully credited invoice: a new draft for the same BL, with what was typed on the original,
pointing back to the credit note."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import services
from apps.sales.models import CreditNoteKind, CreditNoteStock, InvoiceStatus

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


@pytest.fixture
def actor(manager):
    return manager.user


@pytest.fixture
def invoice(organization, actor):
    """5 kg × 42.000 = 210.000, without VAT, with 3.000 DT of fees typed, issued."""
    customer = CustomerFactory.create(organization=organization)
    counter = StockLocationFactory.create(organization=organization, counter_sales=True)
    item = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=item, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=30))
    batch = BatchFactory.create(organization=organization, product=item, unit_cost=D("20.000"))
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("30"),
        to_location=counter,
    )
    sale = services.create_sale(
        organization=organization,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": item, "quantity": "5"}],
        confirm=True,
    )
    return services.create_invoice(apply_vat=False, fees="3.000", sale=sale, actor=actor, issue=True)


def credit(invoice, actor, kind=CreditNoteKind.FULL, stock=CreditNoteStock.NONE):
    return services.create_credit_note(invoice=invoice, actor=actor, kind=kind, reason="Erreur de client", stock=stock)


def test_a_full_credit_note_is_billed_again_as_a_draft_with_the_original_choices(invoice, actor):
    note = credit(invoice, actor)
    assert services.rebillable(note)

    again = services.rebill_credit_note(note=note, actor=actor)

    assert again.status == InvoiceStatus.DRAFT
    assert again.rebilled_from == note
    assert list(again.sales.all()) == list(invoice.sales.all())
    assert (again.apply_vat, again.fees, again.total_excl_tax) == (False, D("3.000"), D("210.000"))
    assert AuditLog.objects.filter(action="invoice.rebilled").count() == 1
    assert not services.rebillable(note)  # the BL is on a live invoice again
    with pytest.raises(ValidationError):
        services.rebill_credit_note(note=note, actor=actor)


def test_goods_taken_back_or_a_partial_credit_note_are_not_billed_again(invoice, actor):
    line = invoice.lines.get()
    partial = services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Prix",
        lines=[{"invoice_line": line, "amount": "10.000"}],
    )
    assert not services.rebillable(partial)
    with pytest.raises(ValidationError):
        services.rebill_credit_note(note=partial, actor=actor)

    restocked = credit(invoice, actor, stock=CreditNoteStock.RESTOCK)
    assert not services.rebillable(restocked)
    with pytest.raises(ValidationError):
        services.rebill_credit_note(note=restocked, actor=actor)


def test_the_office_rebills_through_the_api(manager, invoice, actor):
    note = credit(invoice, actor)
    client = APIClient()
    client.force_authenticate(manager.user)

    listed = client.get(reverse("credit-note-detail", args=[note.pk])).json()
    assert listed["rebillable"] is True

    created = client.post(reverse("credit-note-rebill", args=[note.pk]))
    assert created.status_code == 201, created.json()
    body = created.json()
    assert body["status"] == "draft"
    assert body["rebilled_from"]["credit_note_number"] == note.number
    assert body["rebilled_from"]["invoice_number"] == invoice.number

    again = client.get(reverse("credit-note-detail", args=[note.pk])).json()
    assert again["rebillable"] is False
    assert [row["id"] for row in again["rebills"]] == [body["id"]]
