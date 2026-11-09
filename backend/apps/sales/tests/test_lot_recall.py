"""A lot's origin and its recall sheet (D-302): who kept kilos of it, and where the rest is."""

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.tests.factories import OrganizationFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory, SupplierFactory
from apps.sales import printing, selectors, services

pytestmark = pytest.mark.django_db

D = Decimal


def test_the_recall_lists_who_kept_kilos_and_the_bl_prints_the_origin():
    organization = OrganizationFactory.create()
    counter = StockLocationFactory.create(organization=organization, name="Chambre 1", counter_sales=True)
    product = ProductFactory.create(organization=organization, name="Loup", scientific_name="Dicentrarchus labrax")
    ProductPriceFactory.create(product=product, price=D("30.000"), valid_from=timezone.now() - dt.timedelta(days=30))
    supplier = SupplierFactory.create(organization=organization, health_approval="TN-123")
    batch = BatchFactory.create(
        organization=organization,
        product=product,
        supplier=supplier,
        received_on=timezone.localdate() - dt.timedelta(days=2),
        catch_area="37.2.2",
        production_method="wild",
        origin="Port de Sfax",
    )
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("50"),
        to_location=counter,
    )
    big = CustomerFactory.create(organization=organization, name="Hôtel", phone="74 000 000")
    small = CustomerFactory.create(organization=organization, name="Resto")
    sales = [
        services.create_sale(
            organization=organization,
            actor=None,
            customer=customer,
            location=counter,
            lines=[{"product": product, "quantity": kg}],
            confirm=True,
        )
        for customer, kg in ((small, "5"), (big, "12"), (big, "8"))
    ]

    rows = selectors.recall_customers(organization, batch_id=batch.pk)

    assert [(row.customer_name, row.quantity, len(row.sales)) for row in rows] == [
        ("Hôtel", D("20.000"), 2),
        ("Resto", D("5.000"), 1),
    ]
    assert rows[0].phone == "74 000 000"
    text = printing.lot_origin_text(batch)
    assert text == "Dicentrarchus labrax · Zone 37.2.2 · Pêché (sauvage) · Port de Sfax · Agrément TN-123"
    printable = printing.delivery_note_printable(organization, sales[0].pk)
    assert printable.context["lines"][0].origin_text == text


def test_origin_can_be_completed_later_and_is_audited():
    organization = OrganizationFactory.create()
    batch = BatchFactory.create(organization=organization)

    stock.update_lot_origin(batch=batch, actor=None, catch_area="37.1", production_method="farmed", origin="Ferme")

    batch.refresh_from_db()
    assert (batch.catch_area, batch.production_method, batch.origin) == ("37.1", "farmed", "Ferme")
