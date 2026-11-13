"""The tax the company withholds from a supplier invoice at its validation (D-326)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.core.tests.factories import OrganizationFactory
from apps.documents import services as documents
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services
from apps.purchasing.models import SupplierInvoiceStatus, SupplierPayment
from apps.sales import services as sales_services
from apps.treasury.models import TreasuryMovement

pytestmark = [pytest.mark.django_db, pytest.mark.supplier_withholding]

TODAY = timezone.localdate


@pytest.fixture
def organization():
    organization = OrganizationFactory.create()
    sales_services.ensure_finance_settings(organization=organization)
    return organization


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, tax_id="1234567/A/M/000")


def posted_invoice(organization, supplier, kilos: str, cost: str):
    receipt = services.create_receipt(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=StockLocationFactory.create(organization=organization),
        received_on=TODAY(),
        lines=[
            {
                "product": ProductFactory.create(organization=organization),
                "invoiced_quantity": kilos,
                "accepted_quantity": kilos,
                "unit_cost": cost,
            }
        ],
    )
    return services.create_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        receipts=[receipt],
        invoice_date=TODAY(),
        due_date=TODAY() + dt.timedelta(days=30),
        post=True,
    )


def test_an_invoice_of_1000_dt_and_more_is_withheld_one_percent(organization, supplier):
    invoice = posted_invoice(organization, supplier, "100", "20.000")

    assert (invoice.total, invoice.withholding_rate, invoice.withholding_amount) == (
        Decimal("2000.000"),
        Decimal("1.00"),
        Decimal("20.000"),
    )
    assert invoice.status == SupplierInvoiceStatus.PARTLY_PAID
    payment = SupplierPayment.objects.get(supplier=supplier)
    assert (payment.method, payment.amount, payment.reference) == ("withholding", Decimal("20.000"), invoice.number)
    assert invoice.withholding_payment == payment
    listed = selectors.invoices_of(organization, supplier_id=supplier.pk).get(pk=invoice.pk)
    assert listed.outstanding == Decimal("1980.000")
    assert selectors.supplier_balance(organization, supplier.pk).balance == Decimal("1980.000")
    # No money left an account.
    assert not TreasuryMovement.objects.filter(organization=organization).exists()


def test_nothing_is_withheld_below_1000_dt(organization, supplier):
    invoice = posted_invoice(organization, supplier, "10", "20.000")

    assert (invoice.withholding_amount, invoice.status) == (Decimal("0.000"), SupplierInvoiceStatus.POSTED)
    assert not SupplierPayment.objects.exists()


def test_a_supplier_not_subject_to_it_is_paid_in_full(organization, supplier):
    supplier.subject_to_withholding = False
    supplier.save()

    assert posted_invoice(organization, supplier, "100", "20.000").withholding_amount == Decimal("0.000")


def test_nothing_is_withheld_while_the_rate_is_empty(organization, supplier):
    sales_services.save_finance_settings(organization=organization, actor=None, supplier_withholding_rate="")

    assert posted_invoice(organization, supplier, "100", "20.000").withholding_amount == Decimal("0.000")


def test_the_rest_is_paid_to_the_supplier_and_no_more(organization, supplier):
    invoice = posted_invoice(organization, supplier, "100", "20.000")

    with pytest.raises(ValidationError):
        services.record_payment(
            organization=organization,
            actor=None,
            supplier=supplier,
            paid_on=TODAY(),
            amount="2000.000",
            method="transfer",
            allocations=[{"invoice": invoice, "amount": "2000.000"}],
        )
    services.record_payment(
        organization=organization,
        actor=None,
        supplier=supplier,
        paid_on=TODAY(),
        amount="1980.000",
        method="transfer",
        allocations=[{"invoice": invoice, "amount": "1980.000"}],
    )

    invoice.refresh_from_db()
    assert invoice.status == SupplierInvoiceStatus.PAID


def test_a_withholding_is_not_typed_nor_voided(organization, supplier):
    invoice = posted_invoice(organization, supplier, "100", "20.000")

    with pytest.raises(ValidationError):
        services.record_payment(
            organization=organization, actor=None, supplier=supplier, paid_on=TODAY(), amount="5", method="withholding"
        )
    with pytest.raises(ValidationError, match="retenue"):
        services.void_payment(payment=invoice.withholding_payment, actor=None, reason="erreur")


def test_the_withholding_prints_as_a_certificate(organization, supplier):
    invoice = posted_invoice(organization, supplier, "100", "20.000")

    printable = documents.printable(organization, "supplier_receipt", invoice.withholding_payment.pk)
    html = documents.render_html(printable)

    assert printable.filename.startswith("certificat-retenue-")
    assert "Certificat de retenue à la source" in html
    assert invoice.number in html
    assert "2 000,000" in html.replace("\u202f", " ").replace("\xa0", " ")
    assert "1 980,000" in html.replace("\u202f", " ").replace("\xa0", " ")
