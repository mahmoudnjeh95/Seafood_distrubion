"""A règlement with several means (cash, cheques, traites...) spread over several invoices (D-196, P9-T01)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import payment_selectors, printing, receivables, services
from apps.treasury import selectors as treasury
from apps.treasury import services as treasury_services
from apps.treasury.models import InstrumentStatus

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
    return CustomerFactory.create(
        organization=organization, name="Restaurant Le Corail", credit_limit=D("10000.000"), payment_terms_days=30
    )


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


@pytest.fixture
def crevette(organization, counter):
    item = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(product=item, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=300))
    batch = BatchFactory.create(
        organization=organization,
        product=item,
        unit_cost=D("20.000"),
        received_on=timezone.localdate() - dt.timedelta(days=120),
    )
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("500"),
        to_location=counter,
    )
    return item


@pytest.fixture
def bank(organization):
    return treasury.banks_of(organization).get(code="BIAT")


def make_sale(organization, actor, customer, counter, product, kg):
    return services.create_sale(
        organization=organization,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": product, "quantity": kg}],
        confirm=True,
    )


def pay(organization, actor, customer, lines, **fields):
    return services.record_customer_payment(
        organization=organization, actor=actor, customer=customer, lines=lines, **fields
    )


def paper(method, amount, number, bank, due_on, **fields):
    return {"method": method, "amount": amount, "number": number, "bank": bank, "due_on": due_on, **fields}


def months(count):
    return timezone.localdate() + dt.timedelta(days=30 * count)


# ---- the owner's example: some cash, three traites and three cheques over several invoices ----


def test_cash_three_traites_and_three_cheques_settle_several_documents(
    organization, actor, customer, counter, crevette, bank
):
    first = make_sale(organization, actor, customer, counter, crevette, "30")  # 1 260.000
    second = make_sale(organization, actor, customer, counter, crevette, "20")  # 840.000
    third = make_sale(organization, actor, customer, counter, crevette, "40")  # 1 680.000
    lines = [
        {"method": "cash", "amount": "500.000"},
        *(paper("bill", "500.000", f"TR-{n}", bank, months(n)) for n in (1, 2, 3)),
        *(paper("cheque", "500.000", f"CH-{n}", bank, months(n)) for n in (1, 2, 3)),
    ]

    payment = pay(
        organization,
        actor,
        customer,
        lines,
        allocations=[{"sale": first, "amount": "1260.000"}, {"sale": third, "amount": "1500.000"}],
    )

    assert (payment.number, payment.amount, payment.method) == ("RG-0001", D("3500.000"), "mixed")
    assert [line.method for line in payment.lines.order_by("id")] == ["cash"] + ["bill"] * 3 + ["cheque"] * 3
    for row in (first, second, third):
        row.refresh_from_db()
    assert (first.amount_due, second.amount_due, third.amount_due) == (D("0.000"), D("840.000"), D("180.000"))
    # 3 500 received, 2 760 allocated: 740 stays the customer's credit; the balance already counts it all.
    balance = receivables.customer_balance(organization, customer.pk)
    assert (balance.balance, balance.credit) == (D("280.000"), D("740.000"))

    effets = list(treasury.instruments_of(organization, customer_id=customer.pk))
    assert len(effets) == 6
    assert {row.status for row in effets} == {InstrumentStatus.PORTFOLIO}
    assert {row.source_number for row in effets} == {"RG-0001"}
    assert {row.drawer for row in effets} == {"Restaurant Le Corail"}
    traites = [row for row in effets if row.kind == "bill"]
    assert [row.due_on for row in traites] == [months(1), months(2), months(3)]
    assert all(row.events.get().to_status == InstrumentStatus.PORTFOLIO for row in effets)

    entry = AuditLog.objects.get(organization=organization, action="customer_payment.recorded")
    after = entry.after or {}
    assert len(after["lines"]) == 7
    assert after["lines"][1] == {
        "method": "bill",
        "amount": "500.000",
        "reference": "",
        "number": "TR-1",
        "bank": "BIAT",
        "due_on": months(1).isoformat(),
    }


def test_an_invoice_is_settled_by_its_amount_spread_over_its_bls(
    organization, actor, customer, counter, crevette, bank
):
    first = make_sale(organization, actor, customer, counter, crevette, "5")
    second = make_sale(organization, actor, customer, counter, crevette, "2")
    invoice = services.create_invoice(sales=[first, second], actor=actor, issue=True)
    owed = sum(
        (row.outstanding for row in receivables.sale_receivables(organization, customer_id=customer.pk)), D("0.000")
    )

    pay(
        organization,
        actor,
        customer,
        [{"method": "cash", "amount": "100.000"}, paper("cheque", str(owed - D("100.000")), "0012345", bank, None)],
        allocations=[{"invoice": invoice, "amount": str(owed)}],
    )

    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.amount_due, second.amount_due) == (D("0.000"), D("0.000"))

    with pytest.raises(ValidationError) as refused:
        pay(
            organization,
            actor,
            customer,
            [{"method": "cash", "amount": "10.000"}],
            allocations=[{"invoice": invoice, "amount": "10.000"}],
        )
    assert "allocations.0.amount" in refused.value.message_dict


def test_an_invoice_cannot_take_more_than_it_owes(organization, actor, customer, counter, crevette):
    sale = make_sale(organization, actor, customer, counter, crevette, "5")
    invoice = services.create_invoice(sale=sale, actor=actor, issue=True)
    with pytest.raises(ValidationError) as refused:
        pay(
            organization,
            actor,
            customer,
            [{"method": "cash", "amount": "9999.000"}],
            allocations=[{"invoice": invoice, "amount": "9999.000"}],
        )
    assert "ne doit plus que" in refused.value.message_dict["allocations.0.amount"][0]


# ---- what a line must give ----


def test_a_cheque_and_a_traite_need_their_number_bank_and_due_day(organization, actor, customer, bank):
    today = timezone.localdate()
    with pytest.raises(ValidationError) as refused:
        pay(
            organization,
            actor,
            customer,
            [
                {"method": "cheque", "amount": "10.000"},
                {"method": "bill", "amount": "10.000", "number": "T1", "bank": bank},
                paper("bill", "10.000", "T2", bank, today - dt.timedelta(days=1)),
                paper("cheque", "10.000", "C3", bank, today + dt.timedelta(days=366)),
                {"method": "mixed", "amount": "10.000"},
                {"method": "cash", "amount": "0"},
            ],
        )
    errors = refused.value.message_dict
    assert {"lines.0.number", "lines.0.bank", "lines.1.due_on", "lines.2.due_on", "lines.3.due_on"} <= set(errors)
    assert {"lines.4.method", "lines.5.amount"} <= set(errors)
    assert "lines.0.due_on" not in errors  # a cheque without a date may be cashed at once


def test_a_cheque_without_a_date_is_due_the_day_it_is_received(organization, actor, customer, bank):
    payment = pay(organization, actor, customer, [paper("cheque", "75.500", "7654321", bank, None)])
    line = payment.lines.get()
    assert (line.instrument.due_on, line.instrument.amount) == (payment.received_on, D("75.500"))
    assert payment.method == "cheque"


def test_the_same_effet_cannot_be_recorded_twice(organization, actor, customer, bank):
    due = months(1)
    with pytest.raises(ValidationError) as refused:
        pay(
            organization,
            actor,
            customer,
            [paper("cheque", "10.000", "111", bank, due), paper("cheque", "10.000", " 111 ", bank, due)],
        )
    assert "lines.1.number" in refused.value.message_dict

    pay(organization, actor, customer, [paper("cheque", "10.000", "111", bank, due)])
    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, [paper("cheque", "10.000", "111", bank, due)])
    assert "RG-0001" in refused.value.message_dict["lines.0.number"][0]
    # Another bank's paper may carry the same number.
    other = treasury.banks_of(organization).get(code="STB")
    pay(organization, actor, customer, [paper("cheque", "10.000", "111", other, due)])


def test_a_bank_taken_off_the_list_is_refused(organization, actor, customer, bank):
    treasury_services.update_bank(bank=bank, actor=actor, code=bank.code, name=bank.name, is_active=False)
    bank.refresh_from_db()
    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, [paper("cheque", "10.000", "1", bank, None)])
    assert "lines.0.bank" in refused.value.message_dict


def test_the_total_must_match_the_lines_and_lines_are_needed(organization, actor, customer):
    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, [{"method": "cash", "amount": "10.000"}], amount="11.000")
    assert "amount" in refused.value.message_dict
    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, [])
    assert "lines" in refused.value.message_dict
    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, [{"method": "cash", "amount": "1.000"}] * 51)
    assert "lines" in refused.value.message_dict


def test_the_single_fields_still_make_one_line(organization, actor, customer):
    payment = services.record_customer_payment(
        organization=organization, actor=actor, customer=customer, amount="40.000", method="transfer", reference="VIR-9"
    )
    line = payment.lines.get()
    assert (line.method, line.amount, line.reference, line.instrument) == ("transfer", D("40.000"), "VIR-9", None)
    assert (payment.method, payment.reference) == ("transfer", "VIR-9")


# ---- voiding ----


def test_voiding_cancels_the_effets_still_in_the_portfolio(organization, actor, customer, bank):
    payment = pay(
        organization,
        actor,
        customer,
        [{"method": "cash", "amount": "10.000"}, paper("bill", "20.000", "T-1", bank, months(1))],
    )
    services.void_customer_payment(payment=payment, actor=actor, reason="Saisi deux fois")
    effet = payment.lines.get(method="bill").instrument
    effet.refresh_from_db()
    assert effet.status == InstrumentStatus.CANCELLED
    assert [row.to_status for row in effet.events.order_by("id")] == ["portfolio", "cancelled"]
    assert "Saisi deux fois" in effet.events.last().note
    # The same paper may be typed again once its règlement is voided.
    pay(organization, actor, customer, [paper("bill", "20.000", "T-1", bank, months(1))])


def test_a_règlement_whose_effet_moved_on_cannot_be_voided(organization, actor, customer, bank):
    payment = pay(organization, actor, customer, [paper("cheque", "20.000", "C-1", bank, None)])
    effet = payment.lines.get().instrument
    # T04 writes this move from the portfolio page; here straight on the row.
    effet.status = InstrumentStatus.DEPOSITED
    effet.save(update_fields=["status"])
    with pytest.raises(ValidationError) as refused:
        services.void_customer_payment(payment=payment, actor=actor, reason="Erreur")
    assert "Remis en banque" in refused.value.messages[0]
    payment.refresh_from_db()
    assert payment.voided_at is None


# ---- reading it back ----


def test_search_finds_a_payment_by_its_effet_number_and_the_receipt_lists_the_lines(
    organization, actor, customer, bank
):
    pay(
        organization,
        actor,
        customer,
        [{"method": "cash", "amount": "10.000"}, paper("bill", "20.000", "TR-778", bank, months(2))],
    )
    pay(organization, actor, customer, [{"method": "cash", "amount": "5.000"}])

    found = list(payment_selectors.customer_payments_of(organization, search="TR-778"))
    assert [row.number for row in found] == ["RG-0001"]
    # The search does not multiply the allocated total.
    assert found[0].allocated_total == D("0.000")  # type: ignore[attr-defined]

    printable = printing.receipt_printable(organization, found[0].pk)
    assert printable.context["method_label"] == "Plusieurs moyens"
    assert [(row["method_label"], row["number"], row["bank"]) for row in printable.context["lines"]] == [
        ("Espèces", "", ""),
        ("Traite", "TR-778", "BIAT"),
    ]
