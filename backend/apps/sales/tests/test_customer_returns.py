import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as stock
from apps.inventory.models import MovementKind, StockMovement
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import selectors, services
from apps.sales.models import CreditNoteKind, CreditNoteLineBatch, CreditNoteStock

pytestmark = pytest.mark.django_db

D = Decimal
YEAR = timezone.localdate().year


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(
        organization=organization,
        name="Restaurant Le Corail",
        address="Avenue Hédi Chaker",
        city="Sfax",
        tax_id="0000101A/A/M/000",
        payment_terms_days=30,
    )


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


def product(organization, name, reference, price, vat_rate=None):
    item = ProductFactory.create(organization=organization, name=name, reference=reference, vat_rate=vat_rate)
    ProductPriceFactory.create(product=item, price=D(price), valid_from=timezone.now() - dt.timedelta(days=30))
    return item


@pytest.fixture
def crevette(organization):
    return product(organization, "Crevette Royale", "CR-001", "42.000")


@pytest.fixture
def dorade(organization):
    return product(organization, "Dorade royale", "DO-003", "24.500")


def receive(organization, item, location, kg, *, cost="20.000"):
    batch = BatchFactory.create(organization=organization, product=item, unit_cost=D(cost))
    stock.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )
    return batch


def confirmed_sale(organization, actor, customer, location, lines):
    for line in lines:
        receive(organization, line["product"], location, D(line["quantity"]) + 10)
    return services.create_sale(
        organization=organization, actor=actor, customer=customer, location=location, lines=lines, confirm=True
    )


@pytest.fixture
def sale(organization, actor, customer, counter, crevette, dorade):
    """The sample invoice's first two lines: 5 kg × 42.000 + 10 kg × 24.500 = 455.000 without VAT."""
    return confirmed_sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "5"}, {"product": dorade, "quantity": "10"}],
    )


def held(organization, location, item):
    rows = inventory_selectors.on_hand_of(organization, location_id=location.pk, product_id=item.pk)
    return sum((row.quantity for row in rows), D("0.000"))


def issued(sale, actor):
    return services.create_invoice(apply_vat=True, sale=sale, actor=actor, issue=True)


def test_a_returned_kilo_goes_back_to_its_batch_and_lowers_the_lots_result(
    sale, actor, organization, counter, crevette
):
    invoice = issued(sale, actor)
    line = invoice.lines.order_by("id").first()
    batch = sale.lines.get(product=crevette).batches.get().batch
    before = held(organization, counter, crevette)

    note = services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Retour client",
        lines=[{"invoice_line": line, "quantity": "2"}],
        stock=CreditNoteStock.RESTOCK,
    )

    assert held(organization, counter, crevette) == before + D("2.000")
    movement = StockMovement.objects.get(kind=MovementKind.CUSTOMER_RETURN, batch=batch)
    assert (movement.quantity, movement.unit_cost, movement.to_location_id) == (D("2.000"), D("20.000"), counter.pk)
    row = CreditNoteLineBatch.objects.get(line__credit_note=note)
    assert (row.quantity, row.revenue_amount, row.cost_amount) == (D("2.000"), D("84.000"), D("40.000"))
    totals = selectors.batch_sales_totals(organization, batch_ids=[batch.pk])[batch.pk]
    assert (totals.quantity, totals.revenue, totals.cost) == (D("3.000"), D("126.000"), D("60.000"))
    assert note.stock == CreditNoteStock.RESTOCK


def test_spoiled_returned_goods_come_back_then_are_written_off_on_the_same_lot(
    sale, actor, organization, counter, crevette
):
    invoice = issued(sale, actor)
    line = invoice.lines.order_by("id").first()
    batch = sale.lines.get(product=crevette).batches.get().batch
    before = held(organization, counter, crevette)

    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Produit avarié",
        lines=[{"invoice_line": line, "quantity": "1.500"}],
        stock=CreditNoteStock.LOSS,
    )

    assert held(organization, counter, crevette) == before
    kinds = list(StockMovement.objects.filter(batch=batch).order_by("id").values_list("kind", "quantity"))
    assert kinds[-2:] == [(MovementKind.CUSTOMER_RETURN, D("1.500")), (MovementKind.LOSS, D("1.500"))]
    totals = selectors.batch_sales_totals(organization, batch_ids=[batch.pk])[batch.pk]
    assert (totals.quantity, totals.revenue, totals.cost) == (D("3.500"), D("147.000"), D("70.000"))


def test_without_a_stock_choice_nothing_moves_but_the_revenue_still_drops(sale, actor, organization, crevette):
    invoice = issued(sale, actor)
    line = invoice.lines.order_by("id").first()
    batch = sale.lines.get(product=crevette).batches.get().batch
    movements = StockMovement.objects.count()

    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Écart de poids",
        lines=[{"invoice_line": line, "quantity": "1"}],
    )

    assert StockMovement.objects.count() == movements
    totals = selectors.batch_sales_totals(organization, batch_ids=[batch.pk])[batch.pk]
    assert (totals.quantity, totals.revenue, totals.cost) == (D("5.000"), D("168.000"), D("100.000"))


def test_a_price_correction_lowers_revenue_only(sale, actor, organization, crevette):
    invoice = issued(sale, actor)
    line = invoice.lines.order_by("id").first()
    batch = sale.lines.get(product=crevette).batches.get().batch

    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Geste commercial",
        lines=[{"invoice_line": line, "amount": "10.000"}],
        stock=CreditNoteStock.RESTOCK,
    )

    totals = selectors.batch_sales_totals(organization, batch_ids=[batch.pk])[batch.pk]
    assert (totals.quantity, totals.revenue, totals.cost) == (D("5.000"), D("200.000"), D("100.000"))
    assert not StockMovement.objects.filter(kind=MovementKind.CUSTOMER_RETURN).exists()


def test_a_full_credit_note_can_put_everything_back_and_the_sale_then_cancels_without_a_second_return(
    sale, actor, organization, counter, crevette, dorade
):
    invoice = issued(sale, actor)
    before = (held(organization, counter, crevette), held(organization, counter, dorade))

    services.create_credit_note(
        invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Erreur", stock=CreditNoteStock.RESTOCK
    )

    assert held(organization, counter, crevette) == before[0] + D("5.000")
    assert held(organization, counter, dorade) == before[1] + D("10.000")
    services.cancel_sale(sale=sale, actor=actor, reason="Erreur")
    assert held(organization, counter, crevette) == before[0] + D("5.000")
    assert held(organization, counter, dorade) == before[1] + D("10.000")


def test_the_kilos_taken_back_never_exceed_what_the_batches_gave(sale, actor, crevette):
    invoice = issued(sale, actor)
    line = invoice.lines.order_by("id").first()
    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Premier retour",
        lines=[{"invoice_line": line, "quantity": "3"}],
        stock=CreditNoteStock.RESTOCK,
    )
    # 2 kg are left on the line; a weight-dispute note without stock uses 1 kg of the invoice line only.
    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Litige",
        lines=[{"invoice_line": line, "quantity": "1"}],
    )

    with pytest.raises(ValidationError) as refused:
        services.create_credit_note(
            invoice=invoice,
            actor=actor,
            kind=CreditNoteKind.PARTIAL,
            reason="Trop",
            lines=[{"invoice_line": line, "quantity": "2"}],
            stock=CreditNoteStock.RESTOCK,
        )
    assert "lines.0.quantity" in refused.value.message_dict


def test_an_unknown_stock_choice_is_refused_and_nothing_is_written(sale, actor):
    invoice = issued(sale, actor)

    with pytest.raises(ValidationError) as refused:
        services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="x", stock="burn")

    assert "stock" in refused.value.message_dict
    assert not invoice.credit_notes.exists()
