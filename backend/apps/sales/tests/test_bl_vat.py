"""D-224: a BL shows the VAT of the lines sold with VAT from the start, the same as its invoice would; the VAT is a
snapshot kept on the lines; a BL without any line sold with VAT looks as before."""

import datetime as dt
from decimal import Decimal

import pytest
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import printing, services

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
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail")


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


def receive(organization, item, location, kg, *, with_vat):
    batch = BatchFactory.create(
        organization=organization, product=item, unit_cost=D("20.000"), bought_with_vat=with_vat
    )
    stock.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D(kg),
        to_location=location,
    )


def draft(organization, actor, customer, location, lines):
    return services.create_sale(
        organization=organization, actor=actor, customer=customer, location=location, lines=lines
    )


def test_a_product_bought_with_vat_shows_its_vat_on_the_bl_from_the_start(
    organization, actor, customer, counter, crevette
):
    receive(organization, crevette, counter, "20", with_vat=True)

    bl = draft(organization, actor, customer, counter, [{"product": crevette, "quantity": "5"}])

    (line,) = bl.lines.all()
    assert (line.vat_rate, line.amount_excl_tax, line.vat_amount, line.amount_incl_tax) == (
        D("19.00"),
        D("210.000"),
        D("39.900"),
        D("249.900"),
    )
    assert (bl.total, bl.amount_excl_tax, bl.vat_total, bl.total_incl_tax) == (
        D("210.000"),
        D("210.000"),
        D("39.900"),
        D("249.900"),
    )


def test_the_bl_totals_are_the_ones_its_invoice_then_takes(organization, actor, customer, counter, crevette):
    receive(organization, crevette, counter, "20", with_vat=True)
    bl = services.confirm_sale(
        sale=draft(organization, actor, customer, counter, [{"product": crevette, "quantity": "5"}]), actor=actor
    )
    printable = printing.delivery_note_printable(organization, bl.pk)

    invoice = services.create_invoice(apply_vat=True, sale=bl, actor=actor)

    assert printable.context["has_vat"] is True
    assert (printable.context["amount_excl_tax"], printable.context["vat_total"]) == (D("210.000"), D("39.900"))
    assert (invoice.total_excl_tax, invoice.vat_total) == (bl.amount_excl_tax, bl.vat_total)
    assert invoice.total_incl_tax == bl.total_incl_tax + invoice.fiscal_stamp


def test_prices_including_vat_take_the_vat_out_on_the_bl_as_on_the_invoice(
    organization, actor, customer, counter, crevette
):
    receive(organization, crevette, counter, "20", with_vat=True)
    services.save_finance_settings(organization=organization, actor=actor, prices_include_vat=True)

    bl = draft(organization, actor, customer, counter, [{"product": crevette, "quantity": "5"}])

    (line,) = bl.lines.all()
    assert (line.amount_incl_tax, line.amount_excl_tax, line.vat_amount) == (D("210.000"), D("176.471"), D("33.529"))
    assert (bl.total, bl.amount_excl_tax, bl.vat_total, bl.total_incl_tax) == (
        D("210.000"),
        D("176.471"),
        D("33.529"),
        D("210.000"),
    )


def test_only_the_lines_of_products_sold_with_vat_carry_vat(organization, actor, customer, counter, crevette, dorade):
    receive(organization, crevette, counter, "20", with_vat=True)
    receive(organization, dorade, counter, "20", with_vat=False)

    bl = draft(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "5"}, {"product": dorade, "quantity": "10"}],
    )

    with_vat, without = bl.lines.order_by("id")
    assert (with_vat.vat_rate, with_vat.vat_amount) == (D("19.00"), D("39.900"))
    assert (without.vat_rate, without.vat_amount, without.amount_excl_tax, without.amount_incl_tax) == (
        None,
        D("0.000"),
        D("245.000"),
        D("245.000"),
    )
    assert (bl.total, bl.vat_total, bl.total_incl_tax) == (D("455.000"), D("39.900"), D("494.900"))


def test_a_bl_without_any_line_sold_with_vat_has_no_vat(organization, actor, customer, counter, crevette):
    receive(organization, crevette, counter, "20", with_vat=False)
    bl = services.confirm_sale(
        sale=draft(organization, actor, customer, counter, [{"product": crevette, "quantity": "5"}]), actor=actor
    )

    (line,) = bl.lines.all()
    assert (line.vat_rate, line.vat_amount) == (None, D("0.000"))
    assert (bl.vat_total, bl.amount_excl_tax, bl.total_incl_tax) == (D("0.000"), D("210.000"), D("210.000"))
    assert printing.delivery_note_printable(organization, bl.pk).context["has_vat"] is False


def test_a_product_exempt_from_vat_keeps_a_zero_rate_on_its_bl(organization, actor, customer, counter):
    exempt = product(organization, "Sardine", "SA-010", "6.000", vat_rate=D("0.00"))
    receive(organization, exempt, counter, "20", with_vat=True)

    bl = draft(organization, actor, customer, counter, [{"product": exempt, "quantity": "10"}])

    (line,) = bl.lines.all()
    assert (line.vat_rate, line.vat_amount, bl.total_incl_tax) == (D("0.00"), D("0.000"), D("60.000"))


def test_the_vat_of_a_bl_is_a_snapshot_that_later_rate_changes_do_not_move(
    organization, actor, customer, counter, crevette
):
    receive(organization, crevette, counter, "20", with_vat=True)
    bl = services.confirm_sale(
        sale=draft(organization, actor, customer, counter, [{"product": crevette, "quantity": "5"}]), actor=actor
    )

    crevette.vat_rate = D("7.00")
    crevette.save(update_fields=["vat_rate"])
    services.save_finance_settings(
        organization=organization, actor=actor, valid_from=timezone.localdate() + dt.timedelta(days=1), vat_rate="13"
    )

    (line,) = bl.lines.all()
    bl.refresh_from_db()
    assert (line.vat_rate, line.vat_amount) == (D("19.00"), D("39.900"))
    assert (bl.vat_total, bl.total_incl_tax) == (D("39.900"), D("249.900"))


def test_an_opening_balance_has_no_vat(organization, actor, customer):
    owed = services.create_opening_receivable(
        organization=organization,
        actor=actor,
        customer=customer,
        amount="120.000",
        owed_on=timezone.localdate() - dt.timedelta(days=10),
    )

    assert (owed.total, owed.vat_total, owed.total_incl_tax) == (D("120.000"), D("0.000"), D("120.000"))
