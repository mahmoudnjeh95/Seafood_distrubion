import datetime as dt
from decimal import Decimal
from typing import Any, cast

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.inventory import selectors as inventory
from apps.inventory import services as stock
from apps.inventory.models import Batch, LocationKind, MovementKind, StockMovement
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import services
from apps.purchasing.models import GoodsReceipt, GoodsReceiptRevision
from apps.purchasing.services import ReceiptRevisionFields

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")


@pytest.fixture
def cold_room(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1")


@pytest.fixture
def truck(organization):
    return StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK, name="Camion 1")


@pytest.fixture
def dorade(organization):
    return ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")


def receive(organization, actor, supplier, location, product, *, accepted="60", invoiced="62", cost="20.250"):
    return services.create_receipt(
        organization=organization,
        actor=actor,
        supplier=supplier,
        location=location,
        received_on=timezone.localdate(),
        supplier_reference="MPS-5544",
        lines=[
            {
                "product": product,
                "ordered_quantity": None,
                "invoiced_quantity": invoiced,
                "accepted_quantity": accepted,
                "unit_cost": cost,
            }
        ],
    )


def current_lines(receipt):
    return [
        {
            "id": line.pk,
            "invoiced_quantity": str(line.invoiced_quantity),
            "accepted_quantity": str(line.accepted_quantity),
            "unit_cost": str(line.unit_cost),
            "use_by": line.batch.use_by,
        }
        for line in receipt.lines.select_related("batch").order_by("id")
    ]


def revise(receipt, *, revision=None, reason="Pesée corrigée au quai", lines=None, **header):
    receipt.refresh_from_db()
    fields: dict[str, Any] = {
        "supplier_reference": receipt.supplier_reference,
        "notes": receipt.notes,
        "with_vat": receipt.with_vat,
        "lines": current_lines(receipt) if lines is None else lines,
    }
    fields.update(header)
    return services.revise_receipt(
        receipt=receipt,
        actor=None,
        revision=receipt.revision if revision is None else revision,
        reason=reason,
        fields=cast(ReceiptRevisionFields, fields),
    )


def on_hand(organization, receipt):
    return inventory.quantity_on_hand(organization, batch_id=receipt.lines.get().batch_id)


# ---- services ----


def test_a_change_updates_the_receipt_and_its_lot_and_keeps_a_revision(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    line = receipt.lines.get()

    revise(
        receipt,
        supplier_reference="MPS-9001",
        notes="Caisse abîmée, 2 kg rendus",
        with_vat=True,
        lines=[
            {
                "id": line.pk,
                "invoiced_quantity": "62",
                "accepted_quantity": "58",
                "unit_cost": "21.000",
                "use_by": dt.date(2026, 12, 1),
            }
        ],
    )

    receipt.refresh_from_db()
    batch = Batch.objects.get(pk=line.batch_id)
    assert (receipt.revision, receipt.supplier_reference, receipt.with_vat) == (1, "MPS-9001", True)
    assert (batch.unit_cost, batch.use_by, batch.bought_with_vat, batch.receipt_reference) == (
        Decimal("21.000"),
        dt.date(2026, 12, 1),
        True,
        "MPS-9001",
    )
    assert on_hand(organization, receipt) == Decimal("58.000")

    # The receipt's own movement is kept as it was; the change is a correction on top of it.
    receipt_movement = StockMovement.objects.get(kind=MovementKind.RECEIPT, batch_id=line.batch_id)
    correction = StockMovement.objects.get(kind=MovementKind.ADJUSTMENT, batch_id=line.batch_id)
    assert (receipt_movement.quantity, correction.quantity, correction.from_location) == (
        Decimal("60.000"),
        Decimal("2.000"),
        cold_room,
    )

    (revision,) = GoodsReceiptRevision.objects.filter(receipt=receipt)
    assert (revision.number, revision.reason, revision.created_by) == (1, "Pesée corrigée au quai", None)
    assert revision.before["lines"][0]["accepted_quantity"] == "60.000"
    assert revision.after["lines"][0]["accepted_quantity"] == "58.000"
    assert revision.after["with_vat"] is True
    assert AuditLog.objects.filter(action="receipt.edited", target_id=str(receipt.pk)).count() == 1


def test_the_revision_must_be_the_current_one_and_nothing_is_written(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    revise(receipt, supplier_reference="MPS-1")

    with pytest.raises(ValidationError) as caught:
        revise(receipt, revision=0, supplier_reference="MPS-2")

    assert list(caught.value.message_dict) == ["revision"]
    receipt.refresh_from_db()
    assert (receipt.revision, receipt.supplier_reference) == (1, "MPS-1")


def test_a_reason_is_required_and_a_change_must_change_something(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)

    with pytest.raises(ValidationError) as no_reason:
        revise(receipt, reason="  ", supplier_reference="MPS-1")
    assert list(no_reason.value.message_dict) == ["reason"]

    with pytest.raises(ValidationError) as nothing:
        revise(receipt)
    assert list(nothing.value.message_dict) == ["lines"]
    receipt.refresh_from_db()
    assert receipt.revision == 0
    assert not GoodsReceiptRevision.objects.exists()


def test_every_line_of_the_receipt_is_sent_and_no_other(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)

    with pytest.raises(ValidationError) as caught:
        revise(receipt, supplier_reference="MPS-1", lines=[])

    assert list(caught.value.message_dict) == ["lines"]


def test_line_errors_come_back_on_their_own_keys_and_nothing_is_written(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    line = receipt.lines.get()
    bad = [
        {
            "id": line.pk,
            "invoiced_quantity": "62",
            "accepted_quantity": "abc",
            "unit_cost": "x",
            "use_by": dt.date(2026, 1, 1),
        }
    ]

    with pytest.raises(ValidationError) as caught:
        revise(receipt, lines=bad)

    assert set(caught.value.message_dict) == {
        "lines.0.accepted_quantity",
        "lines.0.unit_cost",
        "lines.0.use_by",
    }
    assert on_hand(organization, receipt) == Decimal("60.000")


def test_a_receipt_on_a_draft_invoice_is_not_changed_until_the_draft_is_deleted(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    invoice = services.create_invoice(
        organization=organization,
        actor=actor,
        supplier=supplier,
        receipts=[receipt],
        invoice_date=timezone.localdate(),
        due_date=timezone.localdate() + dt.timedelta(days=30),
    )

    with pytest.raises(ValidationError) as caught:
        revise(receipt, supplier_reference="MPS-1")

    assert invoice.number in str(caught.value.messages[0])
    assert "brouillon" in str(caught.value.messages[0])
    receipt.refresh_from_db()
    assert receipt.revision == 0


def test_a_receipt_on_a_posted_invoice_is_never_changed(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    services.create_invoice(
        organization=organization,
        actor=actor,
        supplier=supplier,
        receipts=[receipt],
        invoice_date=timezone.localdate(),
        due_date=timezone.localdate() + dt.timedelta(days=30),
        post=True,
    )

    with pytest.raises(ValidationError) as caught:
        revise(receipt, supplier_reference="MPS-1", lines=current_lines(receipt))

    assert "validée" in str(caught.value.messages[0])
    assert on_hand(organization, receipt) == Decimal("60.000")


def test_a_lower_accepted_weight_cannot_take_the_lot_below_what_already_left(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    line = receipt.lines.get()
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.SALE,
        batch=line.batch,
        quantity="50",
        from_location=cold_room,
    )
    too_low = [{**current_lines(receipt)[0], "accepted_quantity": "40"}]

    with pytest.raises(ValidationError) as caught:
        revise(receipt, lines=too_low)

    assert list(caught.value.message_dict) == ["lines.0.accepted_quantity"]
    assert "50.000 kg" in caught.value.message_dict["lines.0.accepted_quantity"][0]
    assert on_hand(organization, receipt) == Decimal("10.000")

    revise(receipt, lines=[{**current_lines(receipt)[0], "accepted_quantity": "50"}])
    assert on_hand(organization, receipt) == Decimal("0.000")


def test_a_higher_accepted_weight_adds_stock_where_the_receipt_landed(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)

    revise(receipt, lines=[{**current_lines(receipt)[0], "accepted_quantity": "65"}])

    assert on_hand(organization, receipt) == Decimal("65.000")
    correction = StockMovement.objects.get(kind=MovementKind.ADJUSTMENT)
    assert (correction.quantity, correction.to_location, correction.from_location) == (
        Decimal("5.000"),
        cold_room,
        None,
    )


def test_the_cost_cannot_change_once_something_valued_has_left_the_lot(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.SALE,
        batch=receipt.lines.get().batch,
        quantity="10",
        from_location=cold_room,
    )

    with pytest.raises(ValidationError) as caught:
        revise(receipt, lines=[{**current_lines(receipt)[0], "unit_cost": "21.000"}])

    assert list(caught.value.message_dict) == ["lines.0.unit_cost"]
    receipt.refresh_from_db()
    assert receipt.revision == 0


def test_the_vat_flag_cannot_change_once_something_valued_has_left_the_lot(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.SALE,
        batch=receipt.lines.get().batch,
        quantity="10",
        from_location=cold_room,
    )

    with pytest.raises(ValidationError) as caught:
        revise(receipt, with_vat=True)

    assert list(caught.value.message_dict) == ["with_vat"]


def test_price_and_vat_change_while_the_lot_has_only_been_moved(
    organization, actor, supplier, cold_room, truck, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.TRANSFER,
        batch=receipt.lines.get().batch,
        quantity="10",
        from_location=cold_room,
        to_location=truck,
    )

    revise(receipt, with_vat=True, lines=[{**current_lines(receipt)[0], "unit_cost": "21.000"}])

    batch = receipt.lines.get().batch
    batch.refresh_from_db()
    assert (batch.unit_cost, batch.bought_with_vat) == (Decimal("21.000"), True)


def test_a_weight_correction_does_not_lock_the_price_for_the_next_change(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    revise(receipt, lines=[{**current_lines(receipt)[0], "accepted_quantity": "58"}])

    revise(receipt, lines=[{**current_lines(receipt)[0], "unit_cost": "21.000"}])

    receipt.refresh_from_db()
    assert (receipt.revision, receipt.lines.get().unit_cost) == (2, Decimal("21.000"))


# ---- API ----


def client_for(role, organization):
    membership = MembershipFactory.create(role=role, organization=organization)
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def api_body(receipt, **overrides):
    lines = [{**row, "use_by": row["use_by"].isoformat() if row["use_by"] else None} for row in current_lines(receipt)]
    body: dict[str, Any] = {
        "revision": receipt.revision,
        "reason": "Pesée corrigée au quai",
        "supplier_reference": receipt.supplier_reference,
        "notes": receipt.notes,
        "with_vat": receipt.with_vat,
        "lines": lines,
    }
    body.update(overrides)
    return body


@pytest.mark.parametrize(
    ("role", "status"), [(Role.OWNER, 200), (Role.MANAGER, 200), (Role.DRIVER, 403), (Role.ACCOUNTANT, 403)]
)
def test_only_the_owner_and_the_manager_change_a_receipt(
    role, status, organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    client = client_for(role, organization)

    response = client.post(
        reverse("receipt-revise", args=[receipt.pk]),
        api_body(receipt, supplier_reference="MPS-7"),
        format="json",
    )

    assert response.status_code == status
    receipt.refresh_from_db()
    assert receipt.revision == (1 if status == 200 else 0)


def test_the_detail_shows_each_change_and_whether_it_can_still_change(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    client = client_for(Role.OWNER, organization)
    client.post(
        reverse("receipt-revise", args=[receipt.pk]),
        api_body(receipt, lines=[{**current_lines(receipt)[0], "accepted_quantity": "58"}]),
        format="json",
    )

    body = client.get(reverse("receipt-detail", args=[receipt.pk])).json()

    assert (body["revision"], body["editable"]) == (1, True)
    (change,) = body["revisions"]
    assert change["reason"] == "Pesée corrigée au quai"
    assert {"field": "accepted_quantity", "line": 0, "before": "60.000", "after": "58.000"}.items() <= change[
        "changes"
    ][0].items()


def test_a_stale_revision_from_the_api_is_refused(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    client = client_for(Role.OWNER, organization)
    stale = api_body(receipt, supplier_reference="MPS-1")
    client.post(reverse("receipt-revise", args=[receipt.pk]), stale, format="json")

    response = client.post(reverse("receipt-revise", args=[receipt.pk]), stale | {"revision": 0}, format="json")

    assert response.status_code == 400
    assert "revision" in response.json()


def test_another_organization_cannot_see_or_change_the_receipt(organization, actor, supplier, cold_room, dorade):
    receipt = receive(organization, actor, supplier, cold_room, dorade)
    client = client_for(Role.OWNER, OrganizationFactory.create())

    response = client.post(
        reverse("receipt-revise", args=[receipt.pk]), api_body(receipt, supplier_reference="MPS-1"), format="json"
    )

    assert response.status_code == 404
    assert GoodsReceipt.objects.get(pk=receipt.pk).revision == 0
