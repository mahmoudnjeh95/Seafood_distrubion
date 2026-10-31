"""A customer effet the bank refused (impayé, P9-T04b, D-217): the customer owes again, the sales it settled owe
again beyond the règlement's credit, the bank's charges become an expense, the office is told."""

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
from apps.expenses.models import Expense
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.notifications.models import Notification
from apps.partners.tests.factories import CustomerFactory
from apps.sales import receivables, services
from apps.sales.models import Sale
from apps.treasury import selectors as treasury
from apps.treasury import services as treasury_services
from apps.treasury.models import Instrument, InstrumentStatus

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail", credit_limit=D("10000.000"))


@pytest.fixture
def sale_of(organization, manager, customer):
    counter = StockLocationFactory.create(organization=organization, counter_sales=True)
    product = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=product, price=D("10.000"), valid_from=timezone.now() - dt.timedelta(days=30))
    batch = BatchFactory.create(organization=organization, product=product, unit_cost=D("5.000"))
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("1000"),
        to_location=counter,
    )

    def make(kg):
        return services.create_sale(
            organization=organization,
            actor=manager.user,
            customer=customer,
            location=counter,
            lines=[{"product": product, "quantity": kg}],
            confirm=True,
        )

    return make


def deposited(organization, actor, number):
    effet = Instrument.objects.get(number=number)
    treasury_services.deposit_instruments(
        organization=organization,
        actor=actor,
        instrument_ids=[effet.pk],
        bank=treasury.banks_of(organization).get(code="BIAT"),
        deposited_on=TODAY(),
    )
    return effet


def balance_of(organization, customer):
    return receivables.customer_balance(organization, customer.pk)


def test_an_impaye_makes_the_sales_owe_again_and_charges_the_bank_fees(organization, manager, customer, sale_of):
    actor = manager.user
    first = sale_of("60")  # 600 DT
    second = sale_of("40")  # 400 DT
    stb = treasury.banks_of(organization).get(code="STB")
    payment = services.record_customer_payment(
        organization=organization,
        actor=actor,
        customer=customer,
        lines=[
            {"method": "cash", "amount": "700"},
            {"method": "cheque", "amount": "500", "number": "CH-1", "bank": stb, "due_on": TODAY()},
        ],
    )
    # 1 200 received: both sales paid, 200 left as credit.
    assert balance_of(organization, customer).balance == D("-200.000")
    effet = deposited(organization, actor, "CH-1")

    with pytest.raises(ValidationError) as refused:
        services.record_unpaid_effet(
            organization=organization, actor=actor, instrument_id=effet.pk, unpaid_on=TODAY(), reason=" "
        )
    assert "reason" in refused.value.message_dict
    unpaid = services.record_unpaid_effet(
        organization=organization,
        actor=actor,
        instrument_id=effet.pk,
        unpaid_on=TODAY(),
        reason="Sans provision",
        bank_charges="12.500",
    )

    effet.refresh_from_db()
    assert effet.status == InstrumentStatus.UNPAID
    balance = balance_of(organization, customer)
    # The 200 of credit went first; 300 is taken back from the newest sale.
    assert (balance.balance, balance.credit) == (D("300.000"), D("0.000"))
    assert [(release.sale_id, release.amount) for release in unpaid.releases.all()] == [(second.pk, D("300.000"))]
    assert Sale.objects.get(pk=second.pk).amount_due == D("300.000")
    assert Sale.objects.get(pk=first.pk).amount_due == D("0.000")
    expense = Expense.objects.get(number=unpaid.expense_number)
    assert (expense.amount, expense.category.code, expense.status) == (D("12.500"), "financial", "approved")
    notification = Notification.objects.get(kind="effet_unpaid")
    assert notification.params["number"] == "CH-1"
    assert notification.link == f"/reglements/{payment.pk}"
    assert AuditLog.objects.filter(action="customer_payment.unpaid").count() == 1
    history = receivables.customer_history(organization, customer.pk)
    assert history[-1].kind == "unpaid"
    assert history[-1].balance == D("300.000")

    # Not twice; and the règlement can no longer be voided.
    with pytest.raises(ValidationError):
        services.record_unpaid_effet(
            organization=organization, actor=actor, instrument_id=effet.pk, unpaid_on=TODAY(), reason="encore"
        )
    with pytest.raises(ValidationError):
        services.void_customer_payment(payment=payment, actor=actor, reason="erreur")
    # Nothing left to allocate from this règlement.
    with pytest.raises(ValidationError):
        services.allocate_customer_payment(payment=payment, actor=actor)

    # The paper goes back to the customer, who pays with a new règlement.
    treasury_services.return_instruments(
        organization=organization, actor=actor, instrument_ids=[effet.pk], returned_on=TODAY()
    )
    effet.refresh_from_db()
    assert effet.status == InstrumentStatus.RETURNED
    services.record_customer_payment(
        organization=organization, actor=actor, customer=customer, amount="300", method="cash"
    )
    assert balance_of(organization, customer).balance == D("0.000")
    assert Sale.objects.get(pk=second.pk).amount_due == D("0.000")


def test_the_api_records_an_impaye_and_shows_it_on_the_reglement(organization, manager, customer, sale_of):
    actor = manager.user
    sale_of("30")  # 300 DT
    payment = services.record_customer_payment(
        organization=organization,
        actor=actor,
        customer=customer,
        lines=[
            {
                "method": "bill",
                "amount": "300",
                "number": "TR-8",
                "bank": treasury.banks_of(organization).get(code="BNA"),
                "due_on": TODAY(),
            }
        ],
    )
    effet = deposited(organization, actor, "TR-8")
    api = APIClient()
    api.force_authenticate(actor)

    answer = api.post(
        reverse("customer-effet-unpaid", args=[effet.pk]),
        {"unpaid_on": TODAY().isoformat(), "reason": "Signature non conforme", "bank_charges": ""},
        format="json",
    )

    assert answer.status_code == 200, answer.json()
    line = answer.json()["lines"][0]
    assert line["instrument"]["status"] == "unpaid"
    assert line["unpaid"]["reason"] == "Signature non conforme"
    assert line["unpaid"]["expense_number"] == ""
    assert answer.json()["unallocated"] == "0.000"
    assert balance_of(organization, customer).balance == D("300.000")
    listed = api.get(reverse("customer-payment-list"), {"state": "unallocated"}).json()["results"]
    assert payment.number not in [row["number"] for row in listed]

    accountant = APIClient()
    accountant.force_authenticate(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT).user)
    assert (
        accountant.post(reverse("customer-effet-unpaid", args=[effet.pk]), {"reason": "x"}, format="json").status_code
        == 403
    )
    returned = api.post(
        reverse("treasury-instrument-return"), {"instruments": [effet.pk], "day": TODAY().isoformat()}, format="json"
    )
    assert returned.json()[0]["status"] == "returned"
