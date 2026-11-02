"""Clearing a customer's balance to zero (D-252): the customer paid less than they owed, the rest is given up as a
loss on them. The amount is typed again, the sales it settles read as settled, and the balance counts it."""

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
from apps.sales import receivables, services
from apps.sales.models import CustomerBalanceWriteOff, CustomerWriteOffAllocation

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
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail", credit_limit=D("1000.000"))


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


def make_sale(organization, actor, customer, counter, product, kg):
    return services.create_sale(
        organization=organization,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": product, "quantity": kg}],
        confirm=True,
    )


def pay(organization, actor, customer, amount):
    return services.record_customer_payment(
        organization=organization, actor=actor, customer=customer, amount=amount, method="cash"
    )


def balance(organization, customer):
    return receivables.customer_balance(organization, customer.pk)


# ---- the case of use: 210 DT owed, 200 DT paid, the 10 DT left are given up ----


def test_the_rest_is_given_up_and_the_balance_reads_zero(organization, actor, customer, counter, stocked):
    sale = make_sale(organization, actor, customer, counter, stocked, "5")  # 210.000
    pay(organization, actor, customer, "200.000")
    assert balance(organization, customer).balance == D("10.000")

    write_off = services.write_off_customer_balance(
        customer=customer, actor=actor, expected="10.000", reason="Le client a payé 200 sur 210"
    )

    assert (write_off.amount, write_off.reason) == (D("10.000"), "Le client a payé 200 sur 210")
    assert write_off.created_by == actor
    current = balance(organization, customer)
    assert (current.balance, current.open_total, current.credit) == (D("0.000"), D("0.000"), D("0.000"))
    assert current.open_sales == []
    allocation = CustomerWriteOffAllocation.objects.get()
    assert (allocation.sale_id, allocation.amount) == (sale.pk, D("10.000"))
    assert AuditLog.objects.filter(organization=organization, action="customer.balance_written_off").count() == 1


def test_the_history_shows_the_loss_and_ends_on_zero(organization, actor, customer, counter, stocked):
    make_sale(organization, actor, customer, counter, stocked, "5")
    pay(organization, actor, customer, "200.000")
    services.write_off_customer_balance(customer=customer, actor=actor, expected="10.000", reason="Reste perdu")

    history = receivables.customer_history(organization, customer.pk)
    loss = history[-1]
    assert (loss.kind, loss.amount, loss.note, loss.balance) == ("writeoff", D("-10.000"), "Reste perdu", D("0.000"))


def test_a_sale_made_after_the_write_off_owes_again(organization, actor, customer, counter, stocked):
    make_sale(organization, actor, customer, counter, stocked, "5")
    pay(organization, actor, customer, "200.000")
    services.write_off_customer_balance(customer=customer, actor=actor, expected="10.000", reason="Reste perdu")

    make_sale(organization, actor, customer, counter, stocked, "1")  # 42.000

    current = balance(organization, customer)
    assert (current.balance, current.open_total) == (D("42.000"), D("42.000"))


def test_the_amount_must_be_the_balance_shown_now(organization, actor, customer, counter, stocked):
    make_sale(organization, actor, customer, counter, stocked, "5")
    pay(organization, actor, customer, "200.000")

    with pytest.raises(ValidationError) as refused:
        services.write_off_customer_balance(customer=customer, actor=actor, expected="80.000", reason="Erreur")
    assert set(refused.value.message_dict) == {"expected_amount"}
    assert not CustomerBalanceWriteOff.objects.exists()
    assert balance(organization, customer).balance == D("10.000")


def test_a_reason_is_required(organization, actor, customer, counter, stocked):
    make_sale(organization, actor, customer, counter, stocked, "5")
    pay(organization, actor, customer, "200.000")

    with pytest.raises(ValidationError) as refused:
        services.write_off_customer_balance(customer=customer, actor=actor, expected="10.000", reason="  ")
    assert set(refused.value.message_dict) == {"reason"}
    assert not CustomerBalanceWriteOff.objects.exists()


def test_a_customer_who_owes_nothing_or_holds_credit_is_refused(organization, actor, customer, counter, stocked):
    make_sale(organization, actor, customer, counter, stocked, "5")
    pay(organization, actor, customer, "250.000")  # 40 DT of credit held

    with pytest.raises(ValidationError):
        services.write_off_customer_balance(customer=customer, actor=actor, expected="0.000", reason="Crédit")
    assert not CustomerBalanceWriteOff.objects.exists()
    assert balance(organization, customer).balance == D("-40.000")


def test_the_oldest_sales_are_settled_first(organization, actor, customer, counter, stocked):
    first = make_sale(organization, actor, customer, counter, stocked, "5")  # 210.000
    second = make_sale(organization, actor, customer, counter, stocked, "2")  # 84.000
    pay(organization, actor, customer, "280.000")  # settles the first, 70 of the second left

    services.write_off_customer_balance(customer=customer, actor=actor, expected="14.000", reason="Reste")

    rows = {row.sale_id: row for row in receivables.sale_receivables(organization, customer_id=customer.pk)}
    assert (rows[first.pk].outstanding, rows[first.pk].written_off) == (D("0.000"), D("0.000"))
    assert (rows[second.pk].outstanding, rows[second.pk].written_off) == (D("0.000"), D("14.000"))
    assert balance(organization, customer).balance == D("0.000")
