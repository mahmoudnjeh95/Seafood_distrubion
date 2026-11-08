"""Supplier credit notes (avoirs fournisseurs, D-297): returns leave the stock, weight gaps and price cuts lower what
we owe; the credit settles its invoice, then the other open ones, and the rest waits for the next invoice."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.closing import selectors as closing
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import selectors as inventory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services, statements
from apps.purchasing.models import GoodsReceiptLine, SupplierInvoice, SupplierInvoiceStatus

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Pêcheur Sfax")


@pytest.fixture
def room(organization):
    return StockLocationFactory.create(organization=organization)


@pytest.fixture
def product(organization):
    return ProductFactory.create(organization=organization)


def receive(organization, supplier, room, product, *, invoiced="100", accepted="100", cost="10.000", days_ago=5):
    return services.receive_goods(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=TODAY() - dt.timedelta(days=days_ago),
        lines=[{"product": product, "invoiced_quantity": invoiced, "accepted_quantity": accepted, "unit_cost": cost}],
    )


def invoice_of(organization, supplier, receipts):
    day = TODAY() - dt.timedelta(days=4)
    return services.create_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        receipts=receipts,
        invoice_date=day,
        due_date=day + dt.timedelta(days=30),
        post=True,
    )


def credit(organization, actor, supplier, invoice, lines, reason="Marchandise refusée"):
    return services.create_credit_note(
        organization=organization,
        actor=actor,
        supplier=supplier,
        invoice=invoice,
        credited_on=TODAY(),
        reason=reason,
        lines=lines,
    )


def line_of(receipt):
    return GoodsReceiptLine.objects.get(receipt=receipt)


def test_a_return_leaves_the_stock_and_settles_part_of_the_invoice(organization, actor, supplier, room, product):
    receipt = receive(organization, supplier, room, product)
    invoice = invoice_of(organization, supplier, [receipt])

    note = credit(
        organization,
        actor,
        supplier,
        invoice,
        [{"receipt_line": line_of(receipt).pk, "kind": "return", "quantity": "20", "from_location": room.pk}],
    )

    assert note.number.startswith("AVF-")
    assert note.total == D("200.000")
    assert inventory.quantity_on_hand(organization, location_id=room.pk) == D("80.000")
    invoice.refresh_from_db()
    assert invoice.status == SupplierInvoiceStatus.PARTLY_PAID
    balance = selectors.supplier_balance(organization, supplier.pk)
    assert balance.balance == D("800.000")
    assert balance.credited == D("200.000")
    assert balance.credit_unapplied == D("0.000")
    result = closing.live_result(organization, batch_id=line_of(receipt).batch_id)
    assert result.purchase_cost == D("800.000")


def test_a_weight_gap_is_claimed_once(organization, actor, supplier, room, product):
    receipt = receive(organization, supplier, room, product, invoiced="100", accepted="92")
    invoice = invoice_of(organization, supplier, [receipt])
    assert [gap.quantity for gap in selectors.weight_gaps(organization)] == [D("8.000")]

    credit(
        organization,
        actor,
        supplier,
        invoice,
        [{"receipt_line": line_of(receipt).pk, "kind": "weight", "quantity": "8"}],
    )

    assert selectors.weight_gaps(organization) == []
    assert inventory.quantity_on_hand(organization, location_id=room.pk) == D("92.000")
    assert selectors.supplier_balance(organization, supplier.pk).balance == D("920.000")
    with pytest.raises(ValidationError) as refused:
        credit(
            organization,
            actor,
            supplier,
            invoice,
            [{"receipt_line": line_of(receipt).pk, "kind": "weight", "quantity": "1"}],
        )
    assert "lines.0.quantity" in refused.value.message_dict


def test_a_price_cut_is_a_gain_on_the_lot(organization, actor, supplier, room, product):
    receipt = receive(organization, supplier, room, product)
    invoice = invoice_of(organization, supplier, [receipt])
    batch_id = line_of(receipt).batch_id
    before = closing.live_result(organization, batch_id=batch_id)

    credit(
        organization,
        actor,
        supplier,
        invoice,
        [{"receipt_line": line_of(receipt).pk, "kind": "price", "quantity": "100", "unit_amount": "1.500"}],
        reason="Remise accordée",
    )

    after = closing.live_result(organization, batch_id=batch_id)
    assert after.net_result - before.net_result == D("150.000")
    assert selectors.supplier_balance(organization, supplier.pk).balance == D("850.000")


def test_a_credit_above_what_is_owed_waits_for_the_next_invoice(organization, actor, supplier, room, product):
    first = receive(organization, supplier, room, product, invoiced="10", accepted="10", days_ago=6)
    invoice = invoice_of(organization, supplier, [first])
    services.write_off_supplier_balance(
        supplier=supplier,
        actor=actor,
        expected="100.000",
        reason="Arrangement",
        lot_shares=[{"batch": line_of(first).batch_id, "amount": "100.000"}],
    )
    note = credit(
        organization,
        actor,
        supplier,
        invoice,
        [{"receipt_line": line_of(first).pk, "kind": "price", "quantity": "10", "unit_amount": "3"}],
    )
    assert selectors.supplier_balance(organization, supplier.pk).credit_unapplied == D("30.000")

    second = receive(organization, supplier, room, product, invoiced="10", accepted="10", days_ago=2)
    later = invoice_of(organization, supplier, [second])

    later.refresh_from_db()
    assert later.status == SupplierInvoiceStatus.PARTLY_PAID
    assert getattr(selectors.credit_note_of(organization, note.pk), "applied_amount") == D("30.000")  # noqa: B009
    assert selectors.supplier_balance(organization, supplier.pk).balance == D("70.000")


def test_vat_comes_back_at_the_receipts_rate(organization, actor, supplier, room, product):
    receipt = services.receive_goods(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=TODAY() - dt.timedelta(days=5),
        with_vat=True,
        lines=[{"product": product, "invoiced_quantity": "11", "accepted_quantity": "10", "unit_cost": "10"}],
    )
    invoice = invoice_of(organization, supplier, [receipt])
    rate = invoice.vat_total / invoice.total_excl_tax * 100

    note = credit(
        organization,
        actor,
        supplier,
        invoice,
        [{"receipt_line": line_of(receipt).pk, "kind": "weight", "quantity": "1"}],
    )

    assert note.total_excl_tax == D("10.000")
    assert note.vat_total == (D("10.000") * rate / 100).quantize(D("0.001"))
    assert note.total == note.total_excl_tax + note.vat_total


def test_refusals(organization, actor, supplier, room, product):
    receipt = receive(organization, supplier, room, product)
    invoice = invoice_of(organization, supplier, [receipt])
    other = SupplierFactory.create(organization=organization)
    line = line_of(receipt).pk

    with pytest.raises(ValidationError) as refused:
        credit(organization, actor, other, invoice, [{"receipt_line": line, "kind": "weight", "quantity": "1"}])
    assert "invoice" in refused.value.message_dict
    with pytest.raises(ValidationError) as refused:
        credit(organization, actor, supplier, invoice, [{"receipt_line": line, "kind": "return", "quantity": "1"}])
    assert "lines.0.from_location" in refused.value.message_dict
    with pytest.raises(ValidationError) as refused:
        credit(
            organization,
            actor,
            supplier,
            invoice,
            [{"receipt_line": line, "kind": "price", "quantity": "1", "unit_amount": "11"}],
        )
    assert "lines.0.unit_amount" in refused.value.message_dict
    with pytest.raises(ValidationError) as refused:
        credit(organization, actor, supplier, invoice, [], reason=" ")
    assert {"reason"} <= set(refused.value.message_dict)
    with pytest.raises(ValidationError):
        credit(
            organization,
            actor,
            supplier,
            invoice,
            [{"receipt_line": line, "kind": "return", "quantity": "101", "from_location": room.pk}],
        )
    assert not SupplierInvoice.objects.exclude(status=SupplierInvoiceStatus.POSTED).exists()


def test_the_statement_shows_the_credit_note(organization, actor, supplier, room, product):
    receipt = receive(organization, supplier, room, product)
    invoice = invoice_of(organization, supplier, [receipt])
    credit(
        organization,
        actor,
        supplier,
        invoice,
        [{"receipt_line": line_of(receipt).pk, "kind": "price", "quantity": "100", "unit_amount": "1"}],
    )

    statement = statements.supplier_statement(organization, supplier.pk, date_from=None, date_to=TODAY())

    assert [entry.kind for entry in statement.entries] == ["invoice", "credit_note"]
    assert statement.entries[-1].balance == D("900.000")
