"""D-284: a credit note says, line by line, what becomes of the goods given back, and refunds the customer who
had paid: the debt left is cancelled first, only what was paid in excess goes back, now or later."""

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
from apps.sales import receivables, services
from apps.sales.models import CreditNoteKind, CreditNoteStock, CustomerRefund
from apps.treasury.models import TreasuryMovement

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail", payment_terms_days=30)


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


def product(organization, name, reference, price):
    item = ProductFactory.create(organization=organization, name=name, reference=reference)
    ProductPriceFactory.create(product=item, price=D(price), valid_from=timezone.now() - dt.timedelta(days=30))
    return item


@pytest.fixture
def crevette(organization):
    return product(organization, "Crevette Royale", "CR-001", "42.000")


@pytest.fixture
def dorade(organization):
    return product(organization, "Dorade royale", "DO-003", "24.500")


def held(organization, location, item):
    rows = inventory_selectors.on_hand_of(organization, location_id=location.pk, product_id=item.pk)
    return sum((row.quantity for row in rows), D("0.000"))


@pytest.fixture
def invoice(organization, actor, customer, counter, crevette, dorade):
    """5 kg × 42.000 + 10 kg × 24.500 = 455.000, without VAT, issued."""
    for item in (crevette, dorade):
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
        lines=[{"product": crevette, "quantity": "5"}, {"product": dorade, "quantity": "10"}],
        confirm=True,
    )
    return services.create_invoice(apply_vat=False, sale=sale, actor=actor, issue=True)


def pay(organization, actor, customer, amount):
    return services.record_customer_payment(
        organization=organization, actor=actor, customer=customer, amount=amount, method="cash"
    )


def credit_amount(invoice, actor, amount, *, refund=None):
    """A partial credit note of `amount` DT without VAT on the dorade line (a price correction, no kilos)."""
    line = invoice.lines.order_by("id").last()
    return services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Erreur de prix",
        lines=[{"invoice_line": line, "amount": amount}],
        stock=None,
        refund=refund,
    )


def test_a_paid_invoice_refunds_the_whole_credit_note_and_the_balance_stays_even(
    organization, actor, customer, invoice
):
    pay(organization, actor, customer, invoice.net_to_pay)

    note = credit_amount(invoice, actor, "100")

    refund = CustomerRefund.objects.get(credit_note=note)
    assert refund.amount == note.net_amount == D("100.000")
    # Nothing left the till yet: it waits "À rembourser".
    assert not TreasuryMovement.objects.filter(kind="customer_refund").exists()
    balance = receivables.customer_balance(organization, customer.pk)
    assert (balance.balance, balance.credit) == (D("0.000"), D("0.000"))


def test_a_partly_paid_invoice_cancels_the_debt_first_then_refunds_the_rest(organization, actor, customer, invoice):
    # The client document's case: 100 DT still owed, a credit note of 200 DT.
    pay(organization, actor, customer, invoice.net_to_pay - D("100"))

    note = credit_amount(invoice, actor, "200")

    assert CustomerRefund.objects.get(credit_note=note).amount == D("100.000")
    assert receivables.customer_balance(organization, customer.pk).balance == D("0.000")


def test_an_unpaid_invoice_only_lowers_what_is_owed(organization, actor, customer, invoice):
    note = credit_amount(invoice, actor, "100")

    assert not CustomerRefund.objects.filter(credit_note=note).exists()
    assert receivables.customer_balance(organization, customer.pk).balance == invoice.net_to_pay - D("100")


def test_a_refund_paid_now_leaves_the_caisse_at_once(organization, actor, customer, invoice):
    pay(organization, actor, customer, invoice.net_to_pay)

    note = credit_amount(invoice, actor, "100", refund={"mode": "now", "method": "cash"})

    refund = CustomerRefund.objects.get(credit_note=note)
    assert services.refunded_total(refund) == D("100.000")
    movement = TreasuryMovement.objects.get(kind="customer_refund")
    assert (movement.amount, movement.reference, movement.account.kind) == (D("-100.000"), refund.number, "cash")


def test_a_refund_is_paid_in_parts_and_never_twice(organization, actor, customer, invoice):
    pay(organization, actor, customer, invoice.net_to_pay)
    refund = CustomerRefund.objects.get(credit_note=credit_amount(invoice, actor, "100"))

    services.pay_refund(refund=refund, actor=actor, amount="60", method="cash")
    with pytest.raises(ValidationError) as too_much:
        services.pay_refund(refund=refund, actor=actor, amount="50", method="cash")
    assert "amount" in too_much.value.message_dict
    services.pay_refund(refund=refund, actor=actor, amount="40", method="transfer", reference="VIR-118")

    assert services.refunded_total(refund) == D("100.000")
    assert sum(row.amount for row in TreasuryMovement.objects.filter(kind="customer_refund")) == D("-100.000")
    with pytest.raises(ValidationError):
        services.pay_refund(refund=refund, actor=actor, amount="0.001", method="cash")


def test_each_line_says_what_becomes_of_its_kilos(organization, actor, invoice, counter, crevette, dorade):
    first, second = list(invoice.lines.order_by("id"))
    crevette_before = held(organization, counter, crevette)
    dorade_before = held(organization, counter, dorade)

    note = services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.PARTIAL,
        reason="Retour",
        lines=[
            {"invoice_line": first, "quantity": "2", "stock": CreditNoteStock.RESTOCK},
            {"invoice_line": second, "quantity": "3", "stock": CreditNoteStock.LOSS},
        ],
        stock=None,
    )

    assert note.stock == CreditNoteStock.MIXED
    assert [line.stock for line in note.lines.order_by("id")] == [CreditNoteStock.RESTOCK, CreditNoteStock.LOSS]
    # The good crevettes are back for sale; the spoiled dorades came back and were thrown away on their lot.
    assert held(organization, counter, crevette) == crevette_before + D("2.000")
    assert held(organization, counter, dorade) == dorade_before
    loss = StockMovement.objects.get(kind=MovementKind.LOSS)
    assert (loss.quantity, loss.batch.product_id) == (D("3.000"), dorade.pk)


def test_returned_kilos_without_a_choice_are_refused(actor, invoice):
    line = invoice.lines.order_by("id").first()

    with pytest.raises(ValidationError) as caught:
        services.create_credit_note(
            invoice=invoice,
            actor=actor,
            kind=CreditNoteKind.PARTIAL,
            reason="Retour",
            lines=[{"invoice_line": line, "quantity": "1"}],
            stock=None,
        )

    assert "lines.0.stock" in caught.value.message_dict
    assert not invoice.credit_notes.exists()


def test_a_bl_invoiced_again_after_a_refunded_total_credit_note_owes_its_amount_again(
    organization, actor, customer, invoice
):
    pay(organization, actor, customer, invoice.net_to_pay)
    sale = invoice.sales.get()

    services.create_credit_note(
        invoice=invoice,
        actor=actor,
        kind=CreditNoteKind.FULL,
        reason="Erreur de saisie",
        stock=CreditNoteStock.NONE,
        refund={"mode": "now", "method": "cash"},
    )
    again = services.create_invoice(apply_vat=False, sale=sale, actor=actor, issue=True)

    # The money went back to the customer: the new invoice keeps its own payment follow-up.
    row = receivables.sale_receivables(organization, sale_ids=[sale.pk])[0]
    assert row.outstanding == again.net_to_pay
