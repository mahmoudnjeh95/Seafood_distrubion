"""Clearing what we owe a supplier to zero (D-252): the supplier takes less than its balance, the rest is a gain on
them. The amount is typed again, the invoices it settles read as paid, and the balance and statement count it."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services, statements
from apps.purchasing.models import SupplierBalanceWriteOff, SupplierInvoice, SupplierInvoiceStatus

pytestmark = pytest.mark.django_db

D = Decimal


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


def owe(organization, supplier, room, product, amount: str, received_on: dt.date):
    """A delivery of 1 kg at `amount` DT, invoiced at once and owed."""
    return services.receive_and_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=received_on,
        lines=[{"product": product, "invoiced_quantity": "1", "accepted_quantity": "1", "unit_cost": amount}],
        terms="days",
        due_days=30,
    )


def test_the_rest_is_given_up_and_the_invoice_reads_paid(organization, actor, supplier, room, product):
    owe(organization, supplier, room, product, "100.000", timezone.localdate() - dt.timedelta(days=5))
    invoice = SupplierInvoice.objects.get(supplier=supplier)

    write_off = services.write_off_supplier_balance(
        supplier=supplier, actor=actor, expected="100.000", reason="Le fournisseur accepte 0"
    )

    assert (write_off.amount, write_off.reason) == (D("100.000"), "Le fournisseur accepte 0")
    assert write_off.created_by == actor
    current = selectors.supplier_balance(organization, supplier.pk)
    assert (current.balance, current.written_off, current.outstanding) == (D("0.000"), D("100.000"), D("0.000"))
    invoice.refresh_from_db()
    assert invoice.status == SupplierInvoiceStatus.PAID
    assert AuditLog.objects.filter(organization=organization, action="supplier.balance_written_off").count() == 1


def test_the_statement_shows_the_write_off_and_closes_on_zero(organization, actor, supplier, room, product):
    owe(organization, supplier, room, product, "100.000", timezone.localdate() - dt.timedelta(days=5))
    services.write_off_supplier_balance(supplier=supplier, actor=actor, expected="100.000", reason="Reste")

    statement = statements.supplier_statement(organization, supplier.pk, date_from=None, date_to=timezone.localdate())
    assert statement.closing_balance == D("0.000")
    assert statement.entries[-1].kind == "written_off"
    assert statement.entries[-1].amount == D("-100.000")


def test_the_amount_must_be_the_balance_shown_now(organization, actor, supplier, room, product):
    owe(organization, supplier, room, product, "100.000", timezone.localdate() - dt.timedelta(days=5))

    with pytest.raises(ValidationError) as refused:
        services.write_off_supplier_balance(supplier=supplier, actor=actor, expected="90.000", reason="Erreur")
    assert set(refused.value.message_dict) == {"expected_amount"}
    assert not SupplierBalanceWriteOff.objects.exists()


def test_a_supplier_we_owe_nothing_is_refused(organization, actor, supplier, room, product):
    with pytest.raises(ValidationError):
        services.write_off_supplier_balance(supplier=supplier, actor=actor, expected="0.000", reason="Rien")
    assert not SupplierBalanceWriteOff.objects.exists()
