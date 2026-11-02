import datetime as dt
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.inventory import selectors as inventory
from apps.inventory.models import Batch, LocationKind, StockMovement
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.partnerships.models import LotPartnership
from apps.purchasing import selectors, services
from apps.purchasing.models import GoodsReceipt, SupplierPayment

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
def dorade(organization):
    return ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")


def line(product, **fields) -> dict[str, Any]:
    values: dict[str, Any] = {
        "product": product,
        "ordered_quantity": "62",
        "invoiced_quantity": "62",
        "accepted_quantity": "60",
        "unit_cost": "20.250",
    }
    values.update(fields)
    return values


def receive(organization, actor, supplier, location, lines, **fields):
    values: dict[str, Any] = {"received_on": timezone.localdate(), "supplier_reference": "MPS-5544"}
    values.update(fields)
    return services.create_receipt(
        organization=organization, actor=actor, supplier=supplier, location=location, lines=lines, **values
    )


# ---- services ----


def test_a_receipt_makes_one_batch_per_line_and_puts_the_accepted_weight_in_stock(
    organization, actor, supplier, cold_room, dorade
):
    rouget = ProductFactory.create(organization=organization)
    use_by = timezone.localdate() + dt.timedelta(days=4)

    receipt = receive(
        organization,
        actor,
        supplier,
        cold_room,
        [
            line(dorade, use_by=use_by),
            line(rouget, ordered_quantity=None, invoiced_quantity="20", accepted_quantity="20"),
        ],
    )

    assert receipt.number == "BR-0001"
    first, _second = receipt.lines.all()
    assert (first.batch.product, first.batch.supplier, first.batch.unit_cost) == (dorade, supplier, Decimal("20.250"))
    assert (first.batch.receipt_reference, first.batch.use_by) == ("MPS-5544", use_by)
    assert inventory.quantity_on_hand(organization, location_id=cold_room.pk, product_id=dorade.pk) == Decimal("60.000")
    assert inventory.quantity_on_hand(organization, location_id=cold_room.pk, product_id=rouget.pk) == Decimal("20.000")
    movement = StockMovement.objects.get(batch=first.batch)
    assert (movement.kind, movement.source, movement.user) == ("receipt", first, actor)
    log = AuditLog.objects.get(action="receipt.created")
    assert log.after is not None
    assert log.after["lines"][0]["accepted_quantity"] == "60.000"


def test_amounts_and_differences(organization, actor, supplier, cold_room, dorade):
    receipt = receive(
        organization,
        actor,
        supplier,
        cold_room,
        [
            line(dorade, unit_cost="20.255"),
            line(dorade, ordered_quantity=None, invoiced_quantity="5", accepted_quantity="5"),
        ],
    )

    first, second = receipt.lines.all()
    # 62 × 20.255 = 1255.810 invoiced; 60 × 20.255 = 1215.300 in stock.
    assert (first.invoiced_amount, first.accepted_amount, first.has_difference) == (
        Decimal("1255.810"),
        Decimal("1215.300"),
        True,
    )
    assert second.has_difference is False
    assert selectors.receipt_totals(selectors.receipt_of(organization, receipt.pk)) == (
        Decimal("1357.060"),
        Decimal("1316.550"),
    )


def test_an_order_different_from_the_accepted_weight_is_a_difference(organization, actor, supplier, cold_room, dorade):
    receive(organization, actor, supplier, cold_room, [line(dorade, ordered_quantity="70", accepted_quantity="62")])
    receive(organization, actor, supplier, cold_room, [line(dorade, ordered_quantity="62", accepted_quantity="62")])

    assert [line.ordered_quantity for line in selectors.difference_lines(organization)] == [Decimal("70.000")]
    assert selectors.receipts_of(organization, with_differences=True).count() == 1


def test_every_problem_is_reported_at_once_on_its_own_field_and_nothing_is_written(
    organization, actor, supplier, cold_room, dorade
):
    archived = ProductFactory.create(organization=organization, is_active=False)

    with pytest.raises(ValidationError) as caught:
        receive(
            organization,
            actor,
            supplier,
            cold_room,
            [
                line(dorade, accepted_quantity="0", unit_cost="-1"),
                line(archived, invoiced_quantity="12.3456", ordered_quantity="abc"),
                line(dorade, use_by=timezone.localdate() - dt.timedelta(days=1)),
            ],
            received_on=timezone.localdate() + dt.timedelta(days=1),
        )

    assert set(caught.value.message_dict) == {
        "received_on",
        "lines.0.accepted_quantity",
        "lines.0.unit_cost",
        "lines.1.product",
        "lines.1.invoiced_quantity",
        "lines.1.ordered_quantity",
        # The use-by date is compared with the (refused) receipt date: tomorrow.
        "lines.2.use_by",
    }
    assert not GoodsReceipt.objects.exists()
    assert not Batch.objects.exists()


def test_a_receipt_needs_lines_an_active_supplier_and_an_active_location(organization, actor, cold_room, dorade):
    archived_supplier = SupplierFactory.create(organization=organization, is_active=False)
    archived_room = StockLocationFactory.create(organization=organization, is_active=False)

    with pytest.raises(ValidationError) as caught:
        receive(organization, actor, archived_supplier, archived_room, [])

    assert set(caught.value.message_dict) == {"supplier", "location", "lines"}


def test_receipts_are_numbered_per_organization(organization, actor, supplier, cold_room, dorade):
    numbers = [receive(organization, actor, supplier, cold_room, [line(dorade)]).number for _ in range(2)]
    other = OrganizationFactory.create()
    other_receipt = receive(
        other,
        actor,
        SupplierFactory.create(organization=other),
        StockLocationFactory.create(organization=other),
        [line(ProductFactory.create(organization=other))],
    )

    assert numbers == ["BR-0001", "BR-0002"]
    assert other_receipt.number == "BR-0001"


def test_a_receipt_typed_later_keeps_its_day_in_the_ledger(organization, actor, supplier, cold_room, dorade):
    two_days_ago = timezone.localdate() - dt.timedelta(days=2)

    receipt = receive(organization, actor, supplier, cold_room, [line(dorade)], received_on=two_days_ago)

    movement = StockMovement.objects.get(batch=receipt.lines.get().batch)
    assert timezone.localtime(movement.occurred_at).date() == two_days_ago


def test_without_a_supplier_reference_the_batch_carries_the_receipt_number(
    organization, actor, supplier, cold_room, dorade
):
    receipt = receive(organization, actor, supplier, cold_room, [line(dorade)], supplier_reference=" ")

    assert receipt.lines.get().batch.receipt_reference == "BR-0001"


def test_the_last_cost_of_each_product_from_a_supplier(organization, supplier, dorade):
    loup = ProductFactory.create(organization=organization)
    today = timezone.localdate()
    BatchFactory.create(
        organization=organization,
        supplier=supplier,
        product=dorade,
        received_on=today - dt.timedelta(days=3),
        unit_cost=Decimal("19"),
    )
    latest = BatchFactory.create(
        organization=organization,
        supplier=supplier,
        product=dorade,
        received_on=today - dt.timedelta(days=1),
        unit_cost=Decimal("20.5"),
    )
    BatchFactory.create(organization=organization, product=dorade, unit_cost=Decimal("30"))  # another supplier
    BatchFactory.create(organization=organization, supplier=supplier, product=loup, unit_cost=Decimal("21.5"))

    costs = {batch.product_id: batch for batch in inventory.last_batches_from(organization, supplier_id=supplier.pk)}

    assert costs[dorade.pk] == latest
    assert costs[loup.pk].unit_cost == Decimal("21.500")


# ---- API ----


def client_for(role, organization=None):
    membership = MembershipFactory.create(role=role, organization=organization or OrganizationFactory.create())
    client = APIClient()
    client.force_authenticate(membership.user)
    return client, membership


def payload(supplier, location, product, **line_fields) -> dict[str, Any]:
    return {
        "supplier": supplier.pk,
        "location": location.pk,
        "received_on": timezone.localdate().isoformat(),
        "supplier_reference": "MPS-5544",
        "lines": [
            {
                "product": product.pk,
                "ordered_quantity": "62",
                "invoiced_quantity": "62",
                "accepted_quantity": "60",
                "unit_cost": "20.250",
                **line_fields,
            }
        ],
    }


def test_the_owner_records_a_receipt_and_reads_it_back():
    client, owner = client_for(Role.OWNER)
    organization = owner.organization
    supplier = SupplierFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)

    created = client.post(reverse("receipt-list"), payload(supplier, room, product), format="json")

    assert created.status_code == 201
    body = created.json()
    assert (body["number"], body["has_differences"], body["invoiced_total"], body["accepted_total"]) == (
        "BR-0001",
        True,
        "1255.500",
        "1215.000",
    )
    (row,) = body["lines"]
    assert (row["accepted_quantity"], row["unit_cost"], row["batch"]["number"]) == ("60.000", "20.250", "L-0001")
    assert row["product"]["id"] == product.pk
    assert body["created_by"]
    assert client.get(reverse("receipt-detail", args=[body["id"]])).json() == body
    listed = client.get(reverse("receipt-list"), {"differences": "true"}).json()
    assert (listed["count"], listed["results"][0]["id"]) == (1, body["id"])


@pytest.mark.parametrize(("role", "status", "partnerships"), [(Role.OWNER, 201, 1), (Role.MANAGER, 400, 0)])
def test_only_the_owner_names_a_partner_on_a_receipt_line(role, status, partnerships):
    client, member = client_for(role)
    organization = member.organization
    supplier = SupplierFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)

    # The supplier of the receipt is its own partner here; capital and rates come later (D-100).
    response = client.post(
        reverse("receipt-list"), payload(supplier, room, product, partner=supplier.pk), format="json"
    )

    assert response.status_code == status
    assert LotPartnership.objects.count() == partnerships
    if status == 400:
        assert "lines.0.partner" in response.json()


def test_line_errors_come_back_on_their_own_keys():
    client, owner = client_for(Role.MANAGER)
    organization = owner.organization
    supplier = SupplierFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)

    refused = client.post(reverse("receipt-list"), payload(supplier, room, product, unit_cost="20,5"), format="json")
    assert refused.status_code == 400
    assert list(refused.json()) == ["lines.0.unit_cost"]

    elsewhere = ProductFactory.create()
    unknown = client.post(reverse("receipt-list"), payload(supplier, room, elsewhere), format="json")
    assert list(unknown.json()) == ["lines.0.product"]
    assert not GoodsReceipt.objects.exists()


def test_the_differences_report_and_the_last_costs():
    client, owner = client_for(Role.ACCOUNTANT)
    organization = owner.organization
    supplier = SupplierFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization, kind=LocationKind.COLD_ROOM)
    product = ProductFactory.create(organization=organization)
    receive(organization, None, supplier, room, [line(product), line(product, accepted_quantity="62")])

    report = client.get(reverse("receipt-differences"), {"supplier": supplier.pk}).json()
    assert report["count"] == 1
    assert (report["results"][0]["receipt"]["number"], report["results"][0]["accepted_quantity"]) == (
        "BR-0001",
        "60.000",
    )
    tomorrow = (timezone.localdate() + dt.timedelta(days=1)).isoformat()
    assert client.get(reverse("receipt-differences"), {"date_from": tomorrow}).json()["count"] == 0

    costs = client.get(reverse("receipt-last-costs"), {"supplier": supplier.pk}).json()
    assert costs == [
        {
            "product_id": product.pk,
            "unit_cost": "20.250",
            "received_on": timezone.localdate().isoformat(),
            "batch_number": "L-0002",
        }
    ]
    assert client.get(reverse("receipt-last-costs")).status_code == 400


@pytest.mark.parametrize(
    ("role", "read_status", "write_status"), [(Role.ACCOUNTANT, 200, 403), (Role.DRIVER, 403, 403)]
)
def test_the_accountant_reads_and_drivers_get_nothing(role, read_status, write_status):
    client, _ = client_for(role)

    assert client.get(reverse("receipt-list")).status_code == read_status
    assert client.post(reverse("receipt-list"), {}, format="json").status_code == write_status


def test_another_organization_receipts_are_invisible():
    client, _ = client_for(Role.OWNER)
    other = OrganizationFactory.create()
    receipt = receive(
        other,
        None,
        SupplierFactory.create(organization=other),
        StockLocationFactory.create(organization=other),
        [line(ProductFactory.create(organization=other))],
    )

    assert client.get(reverse("receipt-list")).json()["count"] == 0
    assert client.get(reverse("receipt-detail", args=[receipt.pk])).status_code == 404


def test_a_line_amount_too_big_to_store_is_refused_on_its_cost(organization, actor, supplier, cold_room, dorade):
    with pytest.raises(ValidationError) as failure:
        receive(
            organization,
            actor,
            supplier,
            cold_room,
            [
                line(
                    dorade,
                    ordered_quantity=None,
                    invoiced_quantity="900000",
                    accepted_quantity="900000",
                    unit_cost="900000",
                )
            ],
        )
    assert "lines.0.unit_cost" in failure.value.message_dict
    assert not GoodsReceipt.objects.exists()


def test_money_given_at_reception_needs_the_cash_limit_confirmation(db):
    client, owner = client_for(Role.OWNER)
    organization = owner.organization
    supplier = SupplierFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)
    body = {
        **payload(supplier, room, product, unit_cost="100.000"),
        "payments": [{"method": "cash", "amount": "5000.000"}],
    }

    refused = client.post(reverse("receipt-list"), body, format="json")

    assert refused.status_code == 400
    assert "cash_limit" in refused.json()
    assert GoodsReceipt.objects.count() == 0  # the whole receipt rolled back

    confirmed = client.post(reverse("receipt-list"), {**body, "confirm_cash_limit": True}, format="json")

    assert confirmed.status_code == 201
    assert SupplierPayment.objects.get().cash_limit_confirmed is True
