import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners import services as partners
from apps.partners.tests.factories import CustomerFactory
from apps.sales import payment_selectors, receivables, services
from apps.sales.models import CreditNoteKind, CreditPolicy, CreditStatus, SaleStatus

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
        organization=organization,
        name="Restaurant Le Corail",
        credit_limit=D("1000.000"),
        payment_terms_days=30,
    )


@pytest.fixture
def counter(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


@pytest.fixture
def crevette(organization):
    item = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(product=item, price=D("42.000"), valid_from=timezone.now() - dt.timedelta(days=300))
    return item


@pytest.fixture
def stocked(organization, counter, crevette):
    # Received long ago: some tests sell on past days, and stock cannot leave before it arrived (D-106).
    batch = BatchFactory.create(
        organization=organization,
        product=crevette,
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
    return crevette


def make_sale(organization, actor, customer, counter, product, kg, **fields):
    return services.create_sale(
        organization=organization,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": product, "quantity": kg}],
        confirm=True,
        **fields,
    )


def pay(organization, actor, customer, amount, **fields):
    return services.record_customer_payment(
        organization=organization, actor=actor, customer=customer, amount=amount, method="cash", **fields
    )


def set_policy(organization, actor, policy):
    services.save_finance_settings(organization=organization, actor=actor, credit_policy=policy)


# ---- acceptance: the customer pays 100.000, the balance shows the rest ----


def test_a_partial_payment_leaves_the_rest_on_the_balance(organization, actor, customer, counter, stocked):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")  # 210.000
    assert sale.amount_due == D("210.000")

    payment = pay(organization, actor, customer, "100.000", reference="CH-001")

    sale.refresh_from_db()
    assert payment.number == "RG-0001"
    assert sale.amount_due == D("110.000")
    balance = receivables.customer_balance(organization, customer.pk)
    assert (balance.balance, balance.open_total, balance.credit) == (D("110.000"), D("110.000"), D("0.000"))
    assert [row.sale_id for row in balance.open_sales] == [sale.pk]
    assert payment.allocations.get().amount == D("100.000")
    assert AuditLog.objects.filter(organization=organization, action="customer_payment.recorded").count() == 1


def test_the_whole_amount_closes_the_sale_and_the_surplus_stays_as_credit(
    organization, actor, customer, counter, stocked
):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")

    payment = pay(organization, actor, customer, "250.000")

    sale.refresh_from_db()
    assert sale.amount_due == D("0.000")
    balance = receivables.customer_balance(organization, customer.pk)
    assert (balance.balance, balance.open_total, balance.credit) == (D("-40.000"), D("0.000"), D("40.000"))
    assert payment.allocations.get().amount == D("210.000")


def test_a_payment_settles_the_oldest_sale_first_and_manual_allocation_is_checked(
    organization, actor, customer, counter, stocked
):
    first = make_sale(organization, actor, customer, counter, stocked, "5")  # 210.000
    second = make_sale(organization, actor, customer, counter, stocked, "2")  # 84.000

    pay(organization, actor, customer, "230.000")
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.amount_due, second.amount_due) == (D("0.000"), D("64.000"))

    with pytest.raises(ValidationError) as refused:
        pay(organization, actor, customer, "100.000", allocations=[{"sale": second, "amount": "70.000"}])
    assert "allocations.0.amount" in refused.value.message_dict

    pay(organization, actor, customer, "100.000", allocations=[{"sale": second, "amount": "64.000"}])
    second.refresh_from_db()
    assert second.amount_due == D("0.000")
    # 36.000 left over, kept as credit.
    assert receivables.customer_balance(organization, customer.pk).credit == D("36.000")


def test_unallocated_credit_can_be_allocated_later(organization, actor, customer, counter, stocked):
    payment = pay(organization, actor, customer, "100.000")  # nothing owed yet: all credit
    assert payment.allocations.count() == 0
    sale = make_sale(organization, actor, customer, counter, stocked, "5")
    # The balance already counts the credit.
    assert receivables.customer_balance(organization, customer.pk).balance == D("110.000")

    services.allocate_customer_payment(payment=payment, actor=actor)

    sale.refresh_from_db()
    assert sale.amount_due == D("110.000")
    with pytest.raises(ValidationError):
        services.allocate_customer_payment(payment=payment, actor=actor)


def test_a_voided_payment_stops_counting(organization, actor, customer, counter, stocked):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")
    payment = pay(organization, actor, customer, "100.000")

    with pytest.raises(ValidationError):
        services.void_customer_payment(payment=payment, actor=actor, reason=" ")
    services.void_customer_payment(payment=payment, actor=actor, reason="Saisi deux fois")

    sale.refresh_from_db()
    payment.refresh_from_db()
    assert sale.amount_due == D("210.000")
    assert payment.voided_at is not None
    assert payment.void_reason == "Saisi deux fois"
    assert receivables.customer_balance(organization, customer.pk).balance == D("210.000")
    with pytest.raises(ValidationError):
        services.void_customer_payment(payment=payment, actor=actor, reason="encore")


def test_payment_input_is_checked(organization, actor, customer):
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    with pytest.raises(ValidationError) as refused:
        services.record_customer_payment(
            organization=organization,
            actor=actor,
            customer=customer,
            amount="0",
            method="gold",
            received_on=tomorrow,
        )
    assert set(refused.value.message_dict) == {"amount", "method", "received_on"}
    with pytest.raises(ValidationError):
        pay(organization, actor, customer, "10.0005")


def test_a_counter_sale_to_the_walk_in_customer_is_settled_by_a_payment(organization, actor, counter, stocked):
    walk_in = partners.ensure_walk_in_customer(organization=organization, actor=actor)
    # The office types no payment at the counter (D-240): the sale is left to the treasurer.
    sale = make_sale(organization, actor, walk_in, counter, stocked, "1")
    assert (sale.amount_paid, sale.amount_due) == (D("0.000"), D("42.000"))

    pay(organization, actor, walk_in, "42.000")

    sale.refresh_from_db()
    assert sale.amount_due == D("0.000")


# ---- balance, ageing, history ----


def test_ageing_buckets_follow_the_age_of_each_sale(organization, actor, customer, counter, stocked):
    now = timezone.now()
    for days, kg in ((10, "1"), (45, "2"), (90, "3")):
        make_sale(organization, actor, customer, counter, stocked, kg, sold_at=now - dt.timedelta(days=days))

    balance = receivables.customer_balance(organization, customer.pk)

    assert balance.buckets == {"d0_30": D("42.000"), "d31_60": D("84.000"), "d60_plus": D("126.000")}
    assert balance.balance == D("252.000")
    # Terms are 30 days from the sale: the two older sales are past due.
    assert balance.overdue == D("210.000")
    assert [row.number for row in balance.open_sales] == [f"BL-{now.year}-000{n}" for n in (3, 2, 1)]


def test_history_runs_to_the_balance(organization, actor, customer, counter, stocked):
    make_sale(
        organization,
        actor,
        customer,
        counter,
        stocked,
        "5",
        payment={"amount_paid": "50.000", "payment_method": "cash"},
    )
    pay(organization, actor, customer, "60.000")
    cancelled = make_sale(organization, actor, customer, counter, stocked, "1")
    services.cancel_sale(sale=cancelled, actor=actor, reason="Erreur")

    history = receivables.customer_history(organization, customer.pk)

    assert [entry.kind for entry in history] == ["sale", "on_spot", "payment"]
    assert history[-1].balance == receivables.customer_balance(organization, customer.pk).balance == D("100.000")


def test_money_paid_on_a_cancelled_sale_becomes_credit(organization, actor, customer, counter, stocked):
    sale = make_sale(
        organization,
        actor,
        customer,
        counter,
        stocked,
        "5",
        payment={"amount_paid": "50.000", "payment_method": "cash"},
    )
    services.cancel_sale(sale=sale, actor=actor, reason="Erreur")

    balance = receivables.customer_balance(organization, customer.pk)

    assert (balance.balance, balance.credit, balance.open_total) == (D("-50.000"), D("50.000"), D("0.000"))


# ---- credit limit ----


def test_a_sale_above_the_limit_is_blocked_for_everyone(organization, actor, customer, counter, stocked):
    # The default policy blocks. Limit 1000: 24 kg = 1008.000.
    with pytest.raises(ValidationError) as refused:
        make_sale(organization, actor, customer, counter, stocked, "24")
    assert "credit_limit" in refused.value.message_dict
    assert not customer.sales.exists()

    # What is already owed counts: 20 kg = 840, then 5 kg more makes 1050.
    make_sale(organization, actor, customer, counter, stocked, "20")
    with pytest.raises(ValidationError):
        make_sale(organization, actor, customer, counter, stocked, "5")
    # Paying on the spot, or paying earlier, makes room.
    make_sale(
        organization, actor, customer, counter, stocked, "5", payment={"paid_in_full": True, "payment_method": "cash"}
    )
    pay(organization, actor, customer, "100.000")
    assert make_sale(organization, actor, customer, counter, stocked, "2").status == SaleStatus.CONFIRMED


def test_a_customer_without_credit_pays_at_once(organization, actor, counter, stocked):
    cash_only = CustomerFactory.create(organization=organization, credit_limit=D("0.000"))
    with pytest.raises(ValidationError) as refused:
        make_sale(organization, actor, cash_only, counter, stocked, "1")
    assert "credit_limit" in refused.value.message_dict
    paid = make_sale(
        organization, actor, cash_only, counter, stocked, "1", payment={"paid_in_full": True, "payment_method": "cash"}
    )
    assert paid.status == SaleStatus.CONFIRMED


def test_approval_policy_keeps_a_pending_draft_until_the_owner_approves(
    organization, actor, customer, counter, stocked
):
    set_policy(organization, actor, CreditPolicy.APPROVAL)
    driver = UserFactory.create()

    sale = make_sale(organization, driver, customer, counter, stocked, "24")

    assert sale.status == SaleStatus.DRAFT
    assert (sale.credit_status, sale.credit_over_by) == (CreditStatus.PENDING, D("8.000"))
    assert AuditLog.objects.filter(action="sale.credit_approval_requested").count() == 1
    # Confirming again without approval stays pending.
    assert services.confirm_sale(sale=sale, actor=driver).status == SaleStatus.DRAFT

    approved = services.confirm_sale(sale=sale, actor=actor, approve_credit=True)

    assert approved.status == SaleStatus.CONFIRMED
    assert (approved.credit_status, approved.credit_decided_by) == (CreditStatus.APPROVED, actor)
    assert approved.amount_due == D("1008.000")
    assert AuditLog.objects.filter(action="sale.credit_limit_exceeded").count() == 1


def test_editing_a_pending_draft_asks_again(organization, actor, customer, counter, stocked):
    set_policy(organization, actor, CreditPolicy.APPROVAL)
    sale = make_sale(organization, actor, customer, counter, stocked, "24")

    updated = services.update_sale(
        sale=sale,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": stocked, "quantity": "2"}],
    )

    assert (updated.credit_status, updated.credit_over_by) == ("", D("0.000"))
    assert services.confirm_sale(sale=updated, actor=actor).status == SaleStatus.CONFIRMED


def test_warn_policy_lets_the_sale_through_and_logs_it(organization, actor, customer, counter, stocked):
    set_policy(organization, actor, CreditPolicy.WARN)

    sale = make_sale(organization, actor, customer, counter, stocked, "24")

    assert sale.status == SaleStatus.CONFIRMED
    assert (sale.credit_status, sale.credit_over_by) == (CreditStatus.WARNED, D("8.000"))
    assert AuditLog.objects.filter(action="sale.credit_limit_exceeded").count() == 1


def test_an_unknown_policy_is_refused(organization, actor):
    with pytest.raises(ValidationError) as refused:
        set_policy(organization, actor, "whatever")
    assert "credit_policy" in refused.value.message_dict


# ---- invoices, credit notes, withholding ----


def issued_invoice(sale, actor, **choices):
    return services.create_invoice(sale=sale, actor=actor, issue=True, **choices)


def test_an_issued_invoice_adds_vat_and_stamp_to_what_is_owed(organization, actor, customer, counter, stocked):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")  # 210.000
    invoice = issued_invoice(sale, actor)  # + 19 % = 39.900 + stamp 1.000
    sale.refresh_from_db()

    assert invoice.total_incl_tax == D("250.900")
    assert sale.amount_due == D("250.900")

    pay(organization, actor, customer, "100.000")
    sale.refresh_from_db()
    assert sale.amount_due == D("150.900")
    row = receivables.sale_receivables(organization, customer_id=customer.pk)[0]
    assert (row.invoice_number, row.due_on) == (invoice.number, invoice.due_on)


def test_a_full_credit_note_clears_the_receivable_and_a_payment_becomes_credit(
    organization, actor, customer, counter, stocked
):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")
    invoice = issued_invoice(sale, actor)
    pay(organization, actor, customer, "100.000")

    services.create_credit_note(invoice=invoice, actor=actor, kind=CreditNoteKind.FULL, reason="Retour")

    sale.refresh_from_db()
    assert sale.amount_due == D("0.000")
    balance = receivables.customer_balance(organization, customer.pk)
    assert (balance.balance, balance.credit) == (D("-100.000"), D("100.000"))


def test_a_withholding_certificate_replaces_the_planned_withholding(organization, actor, customer, counter, stocked):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")
    invoice = issued_invoice(sale, actor, withholding_applied=True, withholding_rate="1.5")
    # (210.000 + 39.900) × 1.5 % = 3.749 withheld; 250.900 − 3.749 = 247.151 to pay.
    sale.refresh_from_db()
    assert (invoice.withholding_amount, sale.amount_due) == (D("3.749"), D("247.151"))

    certificate = services.record_withholding_certificate(
        invoice=invoice, actor=actor, number="RS-2026-77", issued_on=timezone.localdate(), amount="5.000"
    )

    sale.refresh_from_db()
    assert sale.amount_due == D("245.900")
    with pytest.raises(ValidationError):
        services.record_withholding_certificate(
            invoice=invoice, actor=actor, number="RS-2", issued_on=timezone.localdate(), amount="1.000"
        )

    services.void_withholding_certificate(certificate=certificate, actor=actor, reason="Mauvais montant")
    sale.refresh_from_db()
    assert sale.amount_due == D("247.151")


def test_certificate_input_and_file(organization, actor, customer, counter, stocked, settings, tmp_path):
    settings.MEDIA_ROOT = tmp_path
    sale = make_sale(organization, actor, customer, counter, stocked, "5")
    invoice = issued_invoice(sale, actor)
    with pytest.raises(ValidationError) as refused:
        services.record_withholding_certificate(
            invoice=invoice,
            actor=actor,
            number=" ",
            issued_on=timezone.localdate() + dt.timedelta(days=1),
            amount="999.000",
        )
    assert set(refused.value.message_dict) == {"number", "issued_on", "amount"}

    certificate = services.record_withholding_certificate(
        invoice=invoice,
        actor=actor,
        number="RS-1",
        issued_on=timezone.localdate(),
        amount="3.000",
        upload=SimpleUploadedFile("c.pdf", b"%PDF-1.4 test", content_type="application/pdf"),
    )
    assert (certificate.file.name or "").endswith(".pdf")
    with pytest.raises(ValidationError):
        services.add_certificate_file(
            certificate=certificate, actor=actor, upload=SimpleUploadedFile("c.txt", b"not an image")
        )


def test_certificate_totals_and_invoices_awaiting_one(organization, actor, customer, counter, stocked):
    today = timezone.localdate()
    planned = issued_invoice(
        make_sale(organization, actor, customer, counter, stocked, "5"),
        actor,
        withholding_applied=True,
        withholding_rate="1.5",
    )
    other = issued_invoice(
        make_sale(organization, actor, customer, counter, stocked, "2"),
        actor,
        withholding_applied=True,
        withholding_rate="1.5",
    )
    services.record_withholding_certificate(
        invoice=planned, actor=actor, number="RS-1", issued_on=today, amount="3.749"
    )

    certificates = payment_selectors.withholding_certificates_of(organization, date_from=today, date_to=today)
    awaiting = payment_selectors.invoices_awaiting_certificate(organization, date_from=today, date_to=today)

    assert [row.number for row in certificates] == ["RS-1"]
    assert [row.pk for row in awaiting] == [other.pk]
