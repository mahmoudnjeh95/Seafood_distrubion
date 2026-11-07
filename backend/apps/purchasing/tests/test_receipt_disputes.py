"""A goods receipt contested with its supplier ("bon de réception contesté", D-285)."""

import datetime as dt

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services
from apps.purchasing.models import ReceiptDisputeStatus

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization)


@pytest.fixture
def receipt(organization, supplier):
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)
    return services.create_receipt(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=TODAY(),
        lines=[{"product": product, "invoiced_quantity": "62", "accepted_quantity": "60", "unit_cost": "20.250"}],
    )


def invoice(organization, actor, supplier, receipts):
    return services.create_invoice(
        organization=organization,
        actor=actor,
        supplier=supplier,
        receipts=receipts,
        invoice_date=TODAY(),
        due_date=TODAY() + dt.timedelta(days=30),
    )


def test_a_contested_receipt_goes_on_no_invoice_until_the_dispute_is_lifted(organization, actor, supplier, receipt):
    services.dispute_receipt(receipt=receipt, actor=actor, reason="Motif de contestation : 2 caisses abîmées")
    receipt.refresh_from_db()
    assert receipt.dispute_status == ReceiptDisputeStatus.OPEN
    assert receipt.disputed_by == actor
    assert AuditLog.objects.filter(action="receipt.disputed").count() == 1

    with pytest.raises(ValidationError) as refused:
        invoice(organization, actor, supplier, [receipt])
    assert "contestée" in str(refused.value.message_dict["receipts"])

    services.resolve_receipt_dispute(receipt=receipt, actor=actor, resolution="Avoir fournisseur accepté")
    receipt.refresh_from_db()
    assert receipt.dispute_status == ReceiptDisputeStatus.RESOLVED
    assert receipt.dispute_resolution == "Avoir fournisseur accepté"
    assert invoice(organization, actor, supplier, [receipt]).total > 0


def test_a_dispute_needs_a_reason_and_its_lifting_a_resolution(actor, receipt):
    with pytest.raises(ValidationError) as no_reason:
        services.dispute_receipt(receipt=receipt, actor=actor, reason="  ")
    assert "reason" in no_reason.value.message_dict

    with pytest.raises(ValidationError):
        services.resolve_receipt_dispute(receipt=receipt, actor=actor, resolution="Réglé")  # nothing contested

    services.dispute_receipt(receipt=receipt, actor=actor, reason="Poids")
    with pytest.raises(ValidationError):
        services.dispute_receipt(receipt=receipt, actor=actor, reason="Encore")  # already open
    with pytest.raises(ValidationError) as no_resolution:
        services.resolve_receipt_dispute(receipt=receipt, actor=actor, resolution="")
    assert "resolution" in no_resolution.value.message_dict


def test_an_invoiced_receipt_cannot_be_contested_and_a_lifted_one_can_be_again(organization, actor, supplier, receipt):
    draft = invoice(organization, actor, supplier, [receipt])
    with pytest.raises(ValidationError) as refused:
        services.dispute_receipt(receipt=receipt, actor=actor, reason="Poids")
    assert draft.number in str(refused.value)

    services.delete_invoice(invoice=draft, actor=actor)
    services.dispute_receipt(receipt=receipt, actor=actor, reason="Poids")
    services.resolve_receipt_dispute(receipt=receipt, actor=actor, resolution="Pesée refaite")
    services.dispute_receipt(receipt=receipt, actor=actor, reason="Qualité")
    receipt.refresh_from_db()
    assert (receipt.dispute_status, receipt.dispute_reason, receipt.dispute_resolution) == (
        ReceiptDisputeStatus.OPEN,
        "Qualité",
        "",
    )


def test_the_list_filters_the_contested_receipts(organization, actor, receipt):
    assert list(selectors.receipts_of(organization, disputed=True)) == []
    services.dispute_receipt(receipt=receipt, actor=actor, reason="Poids")
    assert [row.pk for row in selectors.receipts_of(organization, disputed=True)] == [receipt.pk]


def test_the_owner_contests_and_lifts_through_the_api_and_the_accountant_cannot():
    membership = MembershipFactory.create(role=Role.OWNER, organization=OrganizationFactory.create())
    organization = membership.organization
    client = APIClient()
    client.force_authenticate(membership.user)
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)
    supplier = SupplierFactory.create(organization=organization)
    created = services.create_receipt(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=TODAY(),
        lines=[{"product": product, "invoiced_quantity": "10", "accepted_quantity": "10", "unit_cost": "5"}],
    )

    accountant = MembershipFactory.create(role=Role.ACCOUNTANT, organization=organization)
    other = APIClient()
    other.force_authenticate(accountant.user)
    url = reverse("receipt-dispute", args=[created.pk])
    assert other.post(url, {"reason": "Poids"}, format="json").status_code == 403

    assert client.post(url, {"reason": ""}, format="json").status_code == 400
    body = client.post(url, {"reason": "Poids"}, format="json").json()
    assert (body["dispute_status"], body["dispute_reason"]) == ("open", "Poids")
    listed = client.get(reverse("receipt-list"), {"disputed": "true"}).json()["results"]
    assert [row["id"] for row in listed] == [created.pk]

    lifted = client.post(
        reverse("receipt-resolve-dispute", args=[created.pk]), {"resolution": "Réglé"}, format="json"
    ).json()
    assert lifted["dispute_status"] == "resolved"
