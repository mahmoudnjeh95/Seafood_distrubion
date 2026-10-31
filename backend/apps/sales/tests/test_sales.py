import datetime as dt
import threading
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.utils import timezone

from apps.catalog import services as catalog
from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import selectors as inventory
from apps.inventory import services as stock
from apps.inventory.models import LocationKind, MovementKind, StockMovement, StockOnHand
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import selectors, services
from apps.sales.models import PriceSource, QuoteStatus, Sale, SaleLine, SaleStatus

pytestmark = pytest.mark.django_db


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
    """A cold room open to counter sales."""
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


@pytest.fixture
def crevette(organization):
    product = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(
        product=product, price=Decimal("42.000"), valid_from=timezone.now() - dt.timedelta(days=30)
    )
    return product


@pytest.fixture
def calamar(organization):
    product = ProductFactory.create(organization=organization, name="Calamar", reference="CA-005")
    ProductPriceFactory.create(
        product=product, price=Decimal("29.000"), valid_from=timezone.now() - dt.timedelta(days=30)
    )
    return product


def receive(organization, product, location, kg, *, cost="20.000", days_ago=0):
    batch = BatchFactory.create(
        organization=organization,
        product=product,
        unit_cost=Decimal(cost),
        received_on=timezone.localdate() - dt.timedelta(days=days_ago),
    )
    stock.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )
    return batch


def sale(organization, actor, customer, location, lines, **fields):
    return services.create_sale(
        organization=organization, actor=actor, customer=customer, location=location, lines=lines, **fields
    )


def on_hand(organization, location, product):
    return inventory.quantity_on_hand(organization, location_id=location.pk, product_id=product.pk)


def errors_of(refused: pytest.ExceptionInfo[ValidationError]) -> dict[str, list[str]]:
    return refused.value.message_dict


# ---- drafts and prices ----


def test_a_new_sale_is_a_numbered_draft_priced_at_the_customers_price_in_force(
    organization, actor, customer, counter, crevette, calamar
):
    catalog.create_price_list(
        organization=organization,
        actor=actor,
        name="Le Corail",
        customer_id=customer.pk,
        items=[{"product": crevette, "price": Decimal("39.500")}],
    )
    receive(organization, crevette, counter, "10")

    draft = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "2"}, {"product": calamar, "quantity": "1.5", "discount_rate": "10"}],
    )
    second = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])

    assert (draft.number, draft.status, draft.created_by) == ("VE-0001", SaleStatus.DRAFT, actor)
    assert second.number == "VE-0002"
    assert [
        (line.unit_price, line.price_source, line.discount_amount, line.amount) for line in draft.lines.order_by("id")
    ] == [
        (Decimal("39.500"), PriceSource.PRICE_LIST, Decimal("0.000"), Decimal("79.000")),
        # 1.5 × 29.000 = 43.500, 10 % = 4.350
        (Decimal("29.000"), PriceSource.DAILY, Decimal("4.350"), Decimal("39.150")),
    ]
    assert (draft.subtotal, draft.discount_total, draft.total, draft.amount_due) == (
        Decimal("122.500"),
        Decimal("4.350"),
        Decimal("118.150"),
        Decimal("118.150"),
    )
    # VAT waits for the invoices (P2-T05); a draft moves no stock and has no cost yet.
    assert (draft.tax_amount, draft.cost_total) == (None, None)
    assert on_hand(organization, counter, crevette) == Decimal("10.000")
    assert AuditLog.objects.filter(action="sale.created", target_id=str(draft.pk)).exists()


def test_a_sale_of_an_earlier_moment_takes_the_price_then(organization, actor, customer, counter, crevette):
    ProductPriceFactory.create(product=crevette, price=Decimal("45.000"), valid_from=timezone.now())

    earlier = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "1"}],
        sold_at=timezone.now() - dt.timedelta(days=1),
    )
    now = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])

    assert earlier.lines.get().unit_price == Decimal("42.000")
    assert now.lines.get().unit_price == Decimal("45.000")


def test_a_price_under_the_minimum_is_refused_with_or_without_a_discount(
    organization, actor, customer, counter, crevette
):
    crevette.min_price = Decimal("40.000")
    crevette.save()
    receive(organization, crevette, counter, "5")

    with pytest.raises(ValidationError) as typed:
        sale(
            organization,
            actor,
            customer,
            counter,
            [{"product": crevette, "quantity": "1", "unit_price": "38.000"}],
            confirm=True,
        )
    with pytest.raises(ValidationError) as discounted:
        sale(
            organization,
            actor,
            customer,
            counter,
            [{"product": crevette, "quantity": "1", "unit_price": "42.000", "discount_rate": "10.00"}],
            confirm=True,
        )
    at_the_minimum = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "1", "unit_price": "44.445", "discount_rate": "10.00"}],
        confirm=True,
    )

    assert "lines.0.unit_price" in typed.value.message_dict
    assert "lines.0.discount_rate" in discounted.value.message_dict
    assert at_the_minimum.lines.get().amount == Decimal("40.000")


def test_every_problem_comes_back_at_once_on_its_own_field(organization, actor, customer, crevette):
    unpriced = ProductFactory.create(organization=organization)
    closed_room = StockLocationFactory.create(organization=organization, name="Chambre de stockage")
    customer.is_active = False
    customer.save()

    with pytest.raises(ValidationError) as refused:
        sale(
            organization,
            actor,
            customer,
            closed_room,
            [
                {"product": crevette, "quantity": "1,5"},
                {"product": unpriced, "quantity": "1"},
                {"product": crevette, "quantity": "1", "discount_rate": "120"},
            ],
            sold_at=timezone.now() + dt.timedelta(hours=1),
            payment={"amount_paid": "10"},
        )

    errors = errors_of(refused)
    assert set(errors) == {
        "customer",
        "location",
        "sold_at",
        "lines.0.quantity",
        "lines.1.unit_price",
        "lines.2.product",
        "lines.2.discount_rate",
        # 10 DT paid on lines that price to nothing, and no way of paying given.
        "amount_paid",
        "payment_method",
    }
    assert "ne fait pas de vente au comptoir" in errors["location"][0]
    assert not Sale.objects.exists()


def test_the_payment_on_the_spot_is_checked_against_the_total(organization, actor, customer, counter, crevette):
    lines = [{"product": crevette, "quantity": "5"}]  # 210.000

    with pytest.raises(ValidationError) as too_much:
        sale(
            organization, actor, customer, counter, lines, payment={"amount_paid": "210.001", "payment_method": "cash"}
        )
    with pytest.raises(ValidationError) as unknown:
        sale(organization, actor, customer, counter, lines, payment={"amount_paid": "10", "payment_method": "bitcoin"})
    part = sale(
        organization,
        actor,
        customer,
        counter,
        lines,
        payment={"amount_paid": "100", "payment_method": "cheque", "payment_reference": " CH-0042 "},
    )
    full = sale(organization, actor, customer, counter, lines, payment={"paid_in_full": True, "payment_method": "card"})
    nothing = sale(organization, actor, customer, counter, lines, payment={"payment_method": "cash"})

    assert "dépasse le total" in errors_of(too_much)["amount_paid"][0]
    assert set(errors_of(unknown)) == {"payment_method"}
    assert (part.amount_paid, part.payment_method, part.payment_reference, part.amount_due) == (
        Decimal("100.000"),
        "cheque",
        "CH-0042",
        Decimal("110.000"),
    )
    assert (full.amount_paid, full.amount_due) == (Decimal("210.000"), Decimal("0.000"))
    # Nothing paid: no method kept.
    assert (nothing.amount_paid, nothing.payment_method) == (Decimal("0.000"), "")


def test_the_same_client_uuid_never_makes_two_sales(organization, actor, customer, counter, crevette):
    import uuid

    key = uuid.uuid4()
    first = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}], client_uuid=key)
    again = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}], client_uuid=key)

    assert first == again
    assert Sale.objects.count() == 1


def test_a_draft_changes_until_it_is_confirmed(organization, actor, customer, counter, crevette, calamar):
    receive(organization, crevette, counter, "10")
    draft = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])

    changed = services.update_sale(
        sale=draft,
        actor=actor,
        customer=customer,
        location=counter,
        lines=[{"product": calamar, "quantity": "2"}],
        notes=" livraison ",
    )
    assert [(line.product, line.quantity) for line in changed.lines.all()] == [(calamar, Decimal("2.000"))]
    assert (changed.total, changed.notes) == (Decimal("58.000"), "livraison")

    services.update_sale(
        sale=draft, actor=actor, customer=customer, location=counter, lines=[{"product": crevette, "quantity": "1"}]
    )
    services.confirm_sale(sale=draft, actor=actor)
    with pytest.raises(ValidationError, match="ne se modifie plus"):
        services.update_sale(
            sale=draft, actor=actor, customer=customer, location=counter, lines=[{"product": crevette, "quantity": "2"}]
        )
    with pytest.raises(ValidationError, match="ne se modifie plus"):
        services.confirm_sale(sale=draft, actor=actor)


# ---- confirmation: FIFO, cost of goods ----


def test_confirming_takes_the_oldest_batch_first_and_keeps_each_batchs_cost(
    organization, actor, customer, counter, crevette
):
    old = receive(organization, crevette, counter, "3", cost="20.000", days_ago=2)
    new = receive(organization, crevette, counter, "10", cost="22.000")
    draft = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "5"}],
        payment={"amount_paid": "50", "payment_method": "cash"},
    )

    confirmed = services.confirm_sale(sale=draft, actor=actor)

    line = confirmed.lines.get()
    assert [
        (row.batch, row.quantity, row.unit_cost, row.cost_amount, row.revenue_amount)
        for row in line.batches.order_by("id")
    ] == [
        (old, Decimal("3.000"), Decimal("20.000"), Decimal("60.000"), Decimal("126.000")),
        (new, Decimal("2.000"), Decimal("22.000"), Decimal("44.000"), Decimal("84.000")),
    ]
    assert line.cost_amount == Decimal("104.000")
    assert (confirmed.status, confirmed.confirmed_by, confirmed.cost_total, confirmed.amount_due) == (
        SaleStatus.CONFIRMED,
        actor,
        Decimal("104.000"),
        Decimal("160.000"),
    )
    assert on_hand(organization, counter, crevette) == Decimal("8.000")
    movements = StockMovement.objects.filter(kind=MovementKind.SALE).order_by("id")
    assert [(m.batch, m.quantity, m.from_location, m.source, m.occurred_at) for m in movements] == [
        (old, Decimal("3.000"), counter, line, confirmed.sold_at),
        (new, Decimal("2.000"), counter, line, confirmed.sold_at),
    ]
    assert AuditLog.objects.filter(action="sale.confirmed", target_id=str(confirmed.pk)).exists()


def test_a_lines_revenue_shared_over_its_batches_always_adds_up(organization, actor, customer, counter, crevette):
    receive(organization, crevette, counter, "1", days_ago=2)
    receive(organization, crevette, counter, "1", days_ago=1)
    receive(organization, crevette, counter, "1.5")

    confirmed = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "3.5", "unit_price": "7.777"}],
        confirm=True,
    )

    line = confirmed.lines.get()
    parts = [row.revenue_amount for row in line.batches.order_by("id")]
    # 3.5 × 7.777 = 27.2195 → 27.220; 1/3.5 of it = 7.7771 → 7.777 (twice); the last batch takes the rest.
    assert line.amount == Decimal("27.220")
    assert parts == [Decimal("7.777"), Decimal("7.777"), Decimal("11.666")]
    assert sum(parts) == line.amount


def test_a_lot_picked_by_hand_overrides_fifo(organization, actor, customer, counter, crevette):
    old = receive(organization, crevette, counter, "3", cost="20.000", days_ago=2)
    new = receive(organization, crevette, counter, "10", cost="22.000")

    confirmed = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "2", "picks": [{"batch": new, "quantity": "2"}]}],
        confirm=True,
    )

    line = confirmed.lines.get()
    assert [(pick.batch, pick.quantity) for pick in line.picks.all()] == [(new, Decimal("2.000"))]
    assert [(row.batch, row.quantity) for row in line.batches.order_by("id")] == [(new, Decimal("2.000"))]
    assert on_hand(organization, counter, crevette) == Decimal("11.000")
    old_on_hand = StockOnHand.objects.get(location=counter, batch=old)
    assert old_on_hand.quantity == Decimal("3.000")


def test_a_short_lot_picked_by_hand_falls_back_to_the_other_lots_oldest_first(
    organization, actor, customer, counter, crevette
):
    short = receive(organization, crevette, counter, "2", cost="20.000", days_ago=2)
    other = receive(organization, crevette, counter, "10", cost="22.000")

    confirmed = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "5", "picks": [{"batch": short, "quantity": "5"}]}],
        confirm=True,
    )

    line = confirmed.lines.get()
    assert [(row.batch, row.quantity) for row in line.batches.order_by("id")] == [
        (short, Decimal("2.000")),
        (other, Decimal("3.000")),
    ]
    assert on_hand(organization, counter, crevette) == Decimal("7.000")


def test_several_lots_picked_by_hand_then_the_rest_oldest_first(organization, actor, customer, counter, crevette):
    old = receive(organization, crevette, counter, "3", cost="20.000", days_ago=2)
    middle = receive(organization, crevette, counter, "4", cost="21.000", days_ago=1)
    new = receive(organization, crevette, counter, "10", cost="22.000")

    confirmed = sale(
        organization,
        actor,
        customer,
        counter,
        [
            {
                "product": crevette,
                "quantity": "5",
                "picks": [{"batch": new, "quantity": "2"}, {"batch": middle, "quantity": "1"}],
            }
        ],
        confirm=True,
    )

    line = confirmed.lines.get()
    assert [(row.batch, row.quantity) for row in line.batches.order_by("id")] == [
        (new, Decimal("2.000")),
        (middle, Decimal("1.000")),
        (old, Decimal("2.000")),
    ]
    assert on_hand(organization, counter, crevette) == Decimal("12.000")
    assert StockOnHand.objects.get(location=counter, batch=old).quantity == Decimal("1.000")


def test_lots_picked_by_hand_asking_more_than_the_line_are_refused(organization, actor, customer, counter, crevette):
    first = receive(organization, crevette, counter, "10")
    second = receive(organization, crevette, counter, "10")
    picks = [{"batch": first, "quantity": "3"}, {"batch": second, "quantity": "3"}]

    with pytest.raises(ValidationError) as refused:
        sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "5", "picks": picks}])

    assert "lines.0.picks" in errors_of(refused)


def test_a_lot_picked_twice_on_one_line_is_refused(organization, actor, customer, counter, crevette):
    lot = receive(organization, crevette, counter, "10")
    picks = [{"batch": lot, "quantity": "1"}, {"batch": lot, "quantity": "1"}]

    with pytest.raises(ValidationError) as refused:
        sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "2", "picks": picks}])

    assert "lines.0.picks" in errors_of(refused)


def test_a_lot_picked_by_hand_still_refuses_a_sale_short_of_stock_everywhere(
    organization, actor, customer, counter, crevette
):
    short = receive(organization, crevette, counter, "2")
    lines = [{"product": crevette, "quantity": "5", "picks": [{"batch": short, "quantity": "5"}]}]
    draft = sale(organization, actor, customer, counter, lines)

    with pytest.raises(ValidationError) as refused:
        services.confirm_sale(sale=draft, actor=actor)

    assert "lines.0.quantity" in errors_of(refused)
    assert on_hand(organization, counter, crevette) == Decimal("2.000")


def test_a_batch_not_of_the_lines_product_is_refused(organization, actor, customer, counter, crevette, calamar):
    other_product_batch = receive(organization, calamar, counter, "5")
    draft_lines = [
        {"product": crevette, "quantity": "1", "picks": [{"batch": other_product_batch, "quantity": "1"}]},
    ]

    with pytest.raises(ValidationError) as refused:
        sale(organization, actor, customer, counter, draft_lines)

    assert "lines.0.picks" in errors_of(refused)


def test_a_sale_short_of_stock_is_refused_as_a_whole_on_each_line(
    organization, actor, customer, counter, crevette, calamar
):
    receive(organization, crevette, counter, "10")
    receive(organization, calamar, counter, "1")
    draft = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "4"}, {"product": calamar, "quantity": "2"}],
    )

    with pytest.raises(ValidationError) as refused:
        services.confirm_sale(sale=draft, actor=actor)
    with pytest.raises(ValidationError):
        sale(organization, actor, customer, counter, [{"product": calamar, "quantity": "2"}], confirm=True)

    assert set(errors_of(refused)) == {"lines.1.quantity"}
    assert "Stock insuffisant : 1.000 kg" in errors_of(refused)["lines.1.quantity"][0]
    # Nothing moved, the draft stays a draft, and "save and confirm" left no draft behind.
    assert on_hand(organization, counter, crevette) == Decimal("10.000")
    assert not StockMovement.objects.filter(kind=MovementKind.SALE).exists()
    draft.refresh_from_db()
    assert draft.status == SaleStatus.DRAFT
    assert Sale.objects.count() == 1


def test_a_truck_sells_but_a_storage_room_does_not(organization, actor, customer, crevette):
    truck = StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK, name="Camion 1")
    storage = StockLocationFactory.create(organization=organization, name="Chambre froide 2")
    receive(organization, crevette, truck, "5")

    confirmed = sale(organization, actor, customer, truck, [{"product": crevette, "quantity": "5"}], confirm=True)
    with pytest.raises(ValidationError) as refused:
        sale(organization, actor, customer, storage, [{"product": crevette, "quantity": "1"}])

    assert confirmed.status == SaleStatus.CONFIRMED
    assert set(errors_of(refused)) == {"location"}


def test_a_counter_sale_without_customer_is_the_walk_in_customer_who_pays_everything(
    organization, actor, counter, crevette
):
    receive(organization, crevette, counter, "10")
    lines = [{"product": crevette, "quantity": "1"}]

    with pytest.raises(ValidationError) as unpaid:
        sale(organization, actor, None, counter, lines, confirm=True)
    paid = sale(
        organization,
        actor,
        None,
        counter,
        lines,
        payment={"paid_in_full": True, "payment_method": "cash"},
        confirm=True,
    )

    assert "paie toute la vente" in errors_of(unpaid)["amount_paid"][0]
    assert paid.customer.is_walk_in
    assert (paid.status, paid.amount_paid, paid.amount_due) == (SaleStatus.CONFIRMED, Decimal("42.000"), Decimal("0"))
    assert on_hand(organization, counter, crevette) == Decimal("9.000")


# ---- cancellation ----


def test_cancelling_a_confirmed_sale_brings_the_kilos_back_to_the_same_batches(
    organization, actor, customer, counter, crevette
):
    old = receive(organization, crevette, counter, "3", cost="20.000", days_ago=2)
    new = receive(organization, crevette, counter, "10", cost="22.000")
    confirmed = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "5"}], confirm=True)

    with pytest.raises(ValidationError) as no_reason:
        services.cancel_sale(sale=confirmed, actor=actor)
    cancelled = services.cancel_sale(sale=confirmed, actor=actor, reason="Client absent à la livraison")

    assert set(errors_of(no_reason)) == {"reason"}
    assert (cancelled.status, cancelled.cancelled_by, cancelled.cancel_reason) == (
        SaleStatus.CANCELLED,
        actor,
        "Client absent à la livraison",
    )
    returns = StockMovement.objects.filter(kind=MovementKind.CUSTOMER_RETURN).order_by("id")
    assert [(m.batch, m.quantity, m.unit_cost, m.to_location) for m in returns] == [
        (old, Decimal("3.000"), Decimal("20.000"), counter),
        (new, Decimal("2.000"), Decimal("22.000"), counter),
    ]
    assert inventory.quantity_on_hand(organization, location_id=counter.pk, product_id=crevette.pk) == Decimal("13.000")
    # The sale and its lots stay; they just no longer count.
    assert cancelled.lines.get().batches.count() == 2
    assert selectors.batch_sales_totals(organization) == {}
    assert StockMovement.objects.filter(kind=MovementKind.SALE).count() == 2
    with pytest.raises(ValidationError, match="déjà annulée"):
        services.cancel_sale(sale=cancelled, actor=actor, reason="encore")


def test_cancelling_a_draft_moves_nothing(organization, actor, customer, counter, crevette):
    draft = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])

    cancelled = services.cancel_sale(sale=draft, actor=actor)

    assert cancelled.status == SaleStatus.CANCELLED
    assert not StockMovement.objects.exists()
    assert AuditLog.objects.filter(action="sale.cancelled", target_id=str(draft.pk)).exists()
    with pytest.raises(ValidationError):
        services.confirm_sale(sale=cancelled, actor=actor)


# ---- lots ----


def test_a_lot_knows_what_it_sold_for_how_much_and_at_what_cost(organization, actor, customer, counter, crevette):
    old = receive(organization, crevette, counter, "3", cost="20.000", days_ago=2)
    new = receive(organization, crevette, counter, "10", cost="22.000")
    other = CustomerFactory.create(organization=organization, name="Hôtel Thyna")
    first = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "2"}], confirm=True)
    second = sale(
        organization,
        actor,
        other,
        counter,
        [{"product": crevette, "quantity": "4", "unit_price": "40.000"}],
        confirm=True,
    )
    sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])  # a draft: not sold

    totals = selectors.batch_sales_totals(organization)
    rows = selectors.batch_sales(organization, batch_id=old.pk)

    assert {batch_id: (t.quantity, t.revenue, t.cost, t.margin) for batch_id, t in totals.items()} == {
        # 2 kg at 42 to Le Corail, then 1 kg at 40 to Thyna
        old.pk: (Decimal("3.000"), Decimal("124.000"), Decimal("60.000"), Decimal("64.000")),
        new.pk: (Decimal("3.000"), Decimal("120.000"), Decimal("66.000"), Decimal("54.000")),
    }
    assert [(row.line.sale, row.quantity, row.revenue_amount) for row in rows] == [
        (first, Decimal("2.000"), Decimal("84.000")),
        (second, Decimal("1.000"), Decimal("40.000")),
    ]
    assert selectors.batch_sales_totals(organization, batch_ids=[new.pk]).keys() == {new.pk}


# ---- from a quote ----


@pytest.fixture
def accepted(organization, actor, customer, counter, crevette, calamar):
    quote = services.create_quote(
        organization=organization,
        actor=actor,
        customer=customer,
        quoted_on=timezone.localdate(),
        location=counter,
        lines=[{"product": crevette, "quantity": "5"}, {"product": calamar, "quantity": "2", "discount_rate": "5"}],
        send=True,
    )
    return services.accept_quote(quote=quote, actor=actor)


def test_an_accepted_quote_becomes_a_sale_at_its_own_prices(
    organization, actor, customer, counter, crevette, calamar, accepted
):
    receive(organization, crevette, counter, "10")
    receive(organization, calamar, counter, "10")
    # The price moved since the quote: the quote's price holds.
    ProductPriceFactory.create(product=crevette, price=Decimal("48.000"), valid_from=timezone.now())

    converted = services.create_sale_from_quote(
        quote=accepted, actor=actor, payment={"amount_paid": "100", "payment_method": "cash"}, confirm=True
    )

    assert (converted.customer, converted.location, converted.quote, converted.status) == (
        customer,
        counter,
        accepted,
        SaleStatus.CONFIRMED,
    )
    assert [
        (line.product, line.quantity, line.unit_price, line.discount_rate, line.price_source)
        for line in converted.lines.order_by("id")
    ] == [
        (crevette, Decimal("5.000"), Decimal("42.000"), Decimal("0.00"), PriceSource.QUOTE),
        (calamar, Decimal("2.000"), Decimal("29.000"), Decimal("5.00"), PriceSource.QUOTE),
    ]
    assert converted.total == accepted.total
    accepted.refresh_from_db()
    assert accepted.status == QuoteStatus.ACCEPTED
    assert selectors.live_sale_of(accepted) == converted
    assert selectors.live_sale_of(selectors.quote_of(organization, accepted.pk)) == converted
    assert AuditLog.objects.filter(action="quote.converted", target_id=str(accepted.pk)).exists()

    with pytest.raises(ValidationError, match=f"déjà livré en entier \\(BL-{timezone.localdate().year}-0001\\)"):
        services.create_sale_from_quote(quote=accepted, actor=actor)
    services.cancel_sale(sale=converted, actor=actor, reason="Erreur de saisie")
    again = services.create_sale_from_quote(quote=accepted, actor=actor)
    assert (again.number, again.quote, again.status) == ("VE-0002", accepted, SaleStatus.DRAFT)


def test_a_quote_is_delivered_in_several_bl(organization, actor, counter, crevette, calamar, accepted):
    """D-115: 5 kg crevette + 2 kg calamar quoted; a first BL takes 3 kg crevette, a second the rest."""
    receive(organization, crevette, counter, "10")
    receive(organization, calamar, counter, "10")
    shrimp_line, squid_line = accepted.lines.order_by("id")

    first = services.create_sale_from_quote(
        quote=accepted,
        actor=actor,
        confirm=True,
        lines=[{"quote_line": shrimp_line.pk, "quantity": "3"}, {"quote_line": squid_line.pk, "quantity": "0"}],
    )

    assert [(line.product, line.quantity, line.unit_price) for line in first.lines.all()] == [
        (crevette, Decimal("3.000"), Decimal("42.000"))
    ]
    quote = selectors.quote_of(organization, accepted.pk)
    delivery = selectors.quote_delivery(quote)
    assert (delivery[shrimp_line.pk].delivered, delivery[shrimp_line.pk].remaining) == (
        Decimal("3.000"),
        Decimal("2.000"),
    )
    assert delivery[squid_line.pk].remaining == Decimal("2.000")
    assert selectors.quote_remaining(quote) == Decimal("4.000")

    # More than what is left on a line is refused, under that line.
    with pytest.raises(ValidationError) as too_much:
        services.create_sale_from_quote(
            quote=accepted, actor=actor, lines=[{"quote_line": shrimp_line.pk, "quantity": "2.5"}]
        )
    assert "Il reste 2.000 kg" in errors_of(too_much)["lines.0.quantity"][0]
    with pytest.raises(ValidationError, match="au moins un poids"):
        services.create_sale_from_quote(
            quote=accepted, actor=actor, lines=[{"quote_line": shrimp_line.pk, "quantity": "0"}]
        )
    with pytest.raises(ValidationError) as unknown:
        services.create_sale_from_quote(quote=accepted, actor=actor, lines=[{"quote_line": 0, "quantity": "1"}])
    assert set(errors_of(unknown)) == {"lines.0.quote_line"}

    # Without lines, the next BL takes everything left: a draft's kilos are spoken for too.
    second = services.create_sale_from_quote(quote=accepted, actor=actor)
    assert second.status == SaleStatus.DRAFT
    assert [(line.product, line.quantity, line.discount_rate) for line in second.lines.order_by("id")] == [
        (crevette, Decimal("2.000"), Decimal("0.00")),
        (calamar, Decimal("2.000"), Decimal("5.00")),
    ]
    quote = selectors.quote_of(organization, accepted.pk)
    assert selectors.quote_remaining(quote) == Decimal("0.000")
    assert selectors.live_sales_of(quote) == [first, second]
    assert selectors.live_sale_of(quote) == second
    with pytest.raises(ValidationError, match="déjà livré en entier"):
        services.create_sale_from_quote(quote=accepted, actor=actor)

    # Cancelling a BL frees its kilos for another one.
    services.cancel_sale(sale=first, actor=actor, reason="Client absent")
    assert selectors.quote_remaining(selectors.quote_of(organization, accepted.pk)) == Decimal("3.000")


def test_only_an_accepted_quote_still_valid_becomes_a_sale(organization, actor, customer, counter, crevette, accepted):
    sent = services.create_quote(
        organization=organization,
        actor=actor,
        customer=customer,
        quoted_on=timezone.localdate(),
        lines=[{"product": crevette, "quantity": "1"}],
        send=True,
    )
    with pytest.raises(ValidationError, match="Seul un devis accepté"):
        services.create_sale_from_quote(quote=sent, actor=actor, location=counter)

    services.accept_quote(quote=sent, actor=actor)
    with pytest.raises(ValidationError) as no_place:
        services.create_sale_from_quote(quote=sent, actor=actor)
    assert set(errors_of(no_place)) == {"location"}

    accepted.quoted_on = accepted.valid_until = timezone.localdate() - dt.timedelta(days=1)
    accepted.save()
    with pytest.raises(ValidationError) as expired:
        services.create_sale_from_quote(quote=accepted, actor=actor)
    assert "n'est plus valable" in errors_of(expired)["valid_until"][0]


# ---- concurrency ----


def run_at_once(count: int, action) -> list[Exception]:
    errors: list[Exception] = []
    start = threading.Barrier(count)

    def run() -> None:
        try:
            start.wait()
            action()
        except Exception as error:  # noqa: BLE001 - every failure is reported to the test
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_sales_of_the_last_kilo_at_once_sell_it_once():
    organization = OrganizationFactory.create()
    counter = StockLocationFactory.create(organization=organization, counter_sales=True)
    product = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=product, valid_from=timezone.now() - dt.timedelta(days=1))
    receive(organization, product, counter, "1")
    customers = iter([CustomerFactory.create(organization=organization) for _ in range(2)])

    def sell() -> Any:
        return services.create_sale(
            organization=organization,
            actor=None,
            customer=next(customers),
            location=counter,
            lines=[{"product": product, "quantity": "1"}],
            confirm=True,
        )

    errors = run_at_once(2, sell)

    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    assert "lines.0.quantity" in errors[0].message_dict
    assert on_hand(organization, counter, product) == Decimal("0.000")
    assert Sale.objects.filter(status=SaleStatus.CONFIRMED).count() == 1
    assert SaleLine.objects.count() == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_one_draft_confirmed_twice_at_once_moves_once():
    organization = OrganizationFactory.create()
    counter = StockLocationFactory.create(organization=organization, counter_sales=True)
    product = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=product, valid_from=timezone.now() - dt.timedelta(days=1))
    receive(organization, product, counter, "10")
    draft = services.create_sale(
        organization=organization,
        actor=None,
        customer=CustomerFactory.create(organization=organization),
        location=counter,
        lines=[{"product": product, "quantity": "4"}],
    )

    errors = run_at_once(2, lambda: services.confirm_sale(sale=draft, actor=None))

    assert len(errors) == 1
    assert "ne se modifie plus" in str(errors[0])
    assert on_hand(organization, counter, product) == Decimal("6.000")


# ---- the price floor and the owner's reason (D-163, D-193) ----


def test_a_reason_lets_a_discount_go_under_the_minimum_and_is_audited(organization, actor, customer, counter, crevette):
    crevette.min_price = Decimal("40.000")
    crevette.save()
    receive(organization, crevette, counter, "5")

    approved = sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "1", "unit_price": "42.000", "discount_rate": "10.00"}],
        confirm=True,
        below_minimum_reason="Client fidèle, fin de journée",
    )

    line = approved.lines.get()
    assert (line.amount, line.below_minimum) == (Decimal("37.800"), True)
    trail = AuditLog.objects.get(action="sale.price_below_minimum_approved", target_id=str(approved.pk))
    assert trail.actor == actor
    assert trail.after is not None
    assert trail.after["reason"] == "Client fidèle, fin de journée"
    assert trail.after["lines"][0]["minimum"] == "40.000"


def test_a_blank_reason_does_not_let_a_price_go_under_the_minimum(organization, actor, customer, counter, crevette):
    crevette.min_price = Decimal("40.000")
    crevette.save()

    with pytest.raises(ValidationError) as refused:
        sale(
            organization,
            actor,
            customer,
            counter,
            [{"product": crevette, "quantity": "1", "unit_price": "42.000", "discount_rate": "10.00"}],
            below_minimum_reason="   ",
        )

    assert "lines.0.discount_rate" in errors_of(refused)
    assert not AuditLog.objects.filter(action="sale.price_below_minimum_approved").exists()


def test_a_reason_is_not_audited_when_no_line_goes_under_the_minimum(organization, actor, customer, counter, crevette):
    crevette.min_price = Decimal("40.000")
    crevette.save()

    sale(
        organization,
        actor,
        customer,
        counter,
        [{"product": crevette, "quantity": "1"}],
        below_minimum_reason="Par précaution",
    )

    assert not AuditLog.objects.filter(action="sale.price_below_minimum_approved").exists()


def test_a_draft_is_changed_under_the_minimum_only_with_a_reason(organization, actor, customer, counter, crevette):
    crevette.min_price = Decimal("40.000")
    crevette.save()
    draft = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])
    lines: list[services.SaleLineFields] = [
        {"product": crevette, "quantity": "1", "unit_price": "42.000", "discount_rate": "10.00"}
    ]

    with pytest.raises(ValidationError):
        services.update_sale(sale=draft, actor=actor, customer=customer, location=counter, lines=lines)
    services.update_sale(
        sale=draft,
        actor=actor,
        customer=customer,
        location=counter,
        lines=lines,
        below_minimum_reason="Accord du patron",
    )

    assert draft.lines.get().discount_rate == Decimal("10.00")
    assert AuditLog.objects.filter(action="sale.price_below_minimum_approved", target_id=str(draft.pk)).exists()


def test_a_quote_approved_under_the_minimum_is_delivered_by_anyone(organization, actor, customer, counter, crevette):
    crevette.min_price = Decimal("40.000")
    crevette.save()
    receive(organization, crevette, counter, "5")
    quote = services.create_quote(
        organization=organization,
        actor=actor,
        customer=customer,
        quoted_on=timezone.localdate(),
        lines=[{"product": crevette, "quantity": "2", "unit_price": "42.000", "discount_rate": "10.00"}],
        below_minimum_reason="Gros volume",
    )
    services.send_quote(quote=quote, actor=actor)
    services.accept_quote(quote=quote, actor=actor)

    delivered = services.create_sale_from_quote(quote=quote, actor=actor, location=counter, confirm=True)

    assert delivered.lines.get().amount == Decimal("75.600")
    assert AuditLog.objects.filter(action="quote.price_below_minimum_approved", target_id=str(quote.pk)).exists()


def test_the_lot_picked_on_a_quote_goes_on_its_bl(organization, actor, customer, counter, crevette):
    receive(organization, crevette, counter, "10", cost="20.000", days_ago=2)
    new = receive(organization, crevette, counter, "10", cost="22.000")
    quote = services.create_quote(
        organization=organization,
        actor=actor,
        customer=customer,
        quoted_on=timezone.localdate(),
        location=counter,
        lines=[{"product": crevette, "quantity": "4", "batch": new}],
        send=True,
    )
    assert quote.lines.get().requested_batch == new

    converted = services.create_sale_from_quote(
        quote=services.accept_quote(quote=quote, actor=actor),
        actor=actor,
        payment={"amount_paid": "0", "payment_method": "cash"},
        confirm=True,
    )

    line = converted.lines.get()
    assert line.requested_batch == new
    assert [(row.batch, row.quantity) for row in line.batches.order_by("id")] == [(new, Decimal("4.000"))]
