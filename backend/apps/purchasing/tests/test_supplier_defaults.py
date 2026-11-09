"""A supplier's usual deal and the total typed from the supplier's paper (D-301)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.core.tests.factories import OrganizationFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners import services as partners
from apps.purchasing import selectors, services

pytestmark = pytest.mark.django_db


def test_a_supplier_keeps_its_usual_days_and_vat():
    organization = OrganizationFactory.create()
    supplier = partners.create_supplier(
        organization=organization, actor=None, name="Ferme Mahdia", payment_terms_days=45, buys_with_vat=True
    )
    supplier.refresh_from_db()
    assert (supplier.payment_terms_days, supplier.buys_with_vat) == (45, True)

    partners.update_supplier(supplier=supplier, actor=None, name="Ferme Mahdia", payment_terms_days=None)
    supplier.refresh_from_db()
    assert supplier.payment_terms_days is None


def test_the_paper_total_is_kept_and_checked():
    organization = OrganizationFactory.create()
    supplier = partners.create_supplier(organization=organization, actor=None, name="Port")
    room = StockLocationFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)
    day = timezone.localdate() - dt.timedelta(days=1)
    receipt = services.receive_goods(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=day,
        lines=[{"product": product, "invoiced_quantity": "10", "accepted_quantity": "10", "unit_cost": "12"}],
    )
    invoice = services.create_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        receipts=[receipt],
        invoice_date=day,
        due_date=day,
        paper_total="125.000",
    )
    shown = selectors.invoice_of(organization, invoice.pk)
    assert shown.paper_total == Decimal("125.000")
    assert shown.total == Decimal("120.000")

    with pytest.raises(ValidationError) as refused:
        services.update_invoice(
            invoice=invoice, actor=None, receipts=[receipt], invoice_date=day, due_date=day, paper_total="abc"
        )
    assert "paper_total" in refused.value.message_dict
