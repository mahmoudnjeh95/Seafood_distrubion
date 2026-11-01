"""A truck load split by client leaves a BL for each of them (D-160), validated at the load and delivered by the
driver, in full, in part or not at all (D-178)."""

import datetime as dt
from decimal import Decimal
from uuid import uuid4

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.boxes import selectors as box_selectors
from apps.boxes import services as box_services
from apps.boxes.models import BoxHolder, BoxMovementKind
from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import selectors as inventory
from apps.inventory import services as inventory_services
from apps.inventory.models import LocationKind, MovementKind, StockOnHand
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import printing, selectors, services
from apps.sales.models import DeliveryStatus, Sale, SaleRevisionKind, SaleStatus

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def cold_room(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1")


@pytest.fixture
def truck(organization):
    return StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK, name="Camion 1")


@pytest.fixture
def dorade(organization):
    product = ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")
    ProductPriceFactory.create(
        product=product, price=Decimal("28.000"), valid_from=timezone.now() - dt.timedelta(days=3)
    )
    return product


@pytest.fixture
def restaurant(organization):
    return CustomerFactory.create(
        organization=organization, name="Le Corail", address="Avenue Hédi Chaker", city="Sfax"
    )


@pytest.fixture
def hotel(organization):
    return CustomerFactory.create(organization=organization, name="Hôtel Thyna", address="Route Gabès", city="Sfax")


@pytest.fixture
def stocked(organization, cold_room, dorade):
    """50 kg of dorade in the cold room and 20 boxes of each size at the company."""
    batch = BatchFactory.create(organization=organization, product=dorade, received_on=timezone.localdate())
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=Decimal("50"),
        to_location=cold_room,
    )
    box_services.post_box_counts(
        organization=organization,
        actor=None,
        kind=BoxMovementKind.OPENING,
        counts={"small": 20, "big": 20},
        to_holder=box_services.holder_for(organization=organization, location=cold_room),
    )
    return batch


def load(organization, actor, cold_room, truck, deliveries, *, lines=(), boxes=None, validate=True):
    return inventory_services.create_transfer(
        organization=organization,
        actor=actor,
        from_location=cold_room,
        to_location=truck,
        transferred_on=timezone.localdate(),
        lines=list(lines),
        boxes=boxes,
        deliveries=deliveries,
        validate=validate,
    )


def part(customer, dorade, kg, *, address="", boxes=None):
    return {
        "customer": customer,
        "delivery_address": address,
        "lines": [{"product": dorade, "quantity": kg}],
        "boxes": boxes or {},
    }


def test_a_validated_load_leaves_a_draft_bl_for_each_client(
    organization, actor, cold_room, truck, dorade, restaurant, hotel, stocked
):
    transfer = load(
        organization,
        actor,
        cold_room,
        truck,
        [
            part(restaurant, dorade, "12.500", boxes={"small": 2, "big": 1}),
            part(hotel, dorade, "20", address="Zone industrielle Thyna", boxes={"big": 3}),
        ],
    )

    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("32.500")
    sales_by_customer = {
        sale.customer_id: sale for sale in Sale.objects.filter(transfer=transfer).select_related("customer")
    }
    corail = sales_by_customer[restaurant.pk]
    thyna = sales_by_customer[hotel.pk]
    assert (corail.customer, corail.status, corail.location) == (restaurant, SaleStatus.DRAFT, truck)
    assert corail.delivery_address == "Avenue Hédi Chaker, Sfax"  # the client's own, copied
    assert thyna.delivery_address == "Zone industrielle Thyna"  # typed for this BL only
    restaurant.refresh_from_db()
    assert restaurant.address == "Avenue Hédi Chaker"
    (line,) = corail.lines.all()
    assert (line.quantity, line.unit_price) == (Decimal("12.500"), Decimal("28.000"))  # the load's price of the day
    assert {box.box_type: box.count for box in corail.box_lines.all()} == {"small": 2, "big": 1}
    assert {box.box_type: box.count for box in thyna.box_lines.all()} == {"big": 3}
    # Nothing is sold yet: the truck still holds the kilos and the boxes.
    assert corail.confirmed_at is None
    assert corail.total == Decimal("350.000")


def test_the_print_pack_lists_each_clients_bl_by_customer_name(
    organization, actor, cold_room, truck, dorade, restaurant, hotel, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "5"), part(hotel, dorade, "6")])

    notes = selectors.load_delivery_notes(organization, transfer.pk)

    assert [customer_id for _sale_id, customer_id in notes] == sorted(
        [restaurant.pk, hotel.pk], key=lambda pk: {restaurant.pk: restaurant.name, hotel.pk: hotel.name}[pk]
    )


def test_the_boxes_of_every_client_go_to_the_truck_with_the_load(
    organization, actor, cold_room, truck, dorade, restaurant, hotel, stocked
):
    load(
        organization,
        actor,
        cold_room,
        truck,
        [part(restaurant, dorade, "5", boxes={"small": 2}), part(hotel, dorade, "5", boxes={"small": 3, "big": 1})],
        boxes={"big": 1},
    )

    on_truck = box_services.holder_for(organization=organization, location=truck)
    assert box_selectors.balance_of(organization, on_truck, "small") == 5
    assert box_selectors.balance_of(organization, on_truck, "big") == 2


def test_confirming_a_client_bl_takes_the_stock_and_the_boxes_off_the_truck(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10", boxes={"small": 4})])
    (sale,) = Sale.objects.filter(transfer=transfer)

    services.confirm_sale(sale=sale, actor=actor)

    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("0.000")
    holder = BoxHolder.objects.get(organization=organization, customer=restaurant)
    assert box_selectors.balance_of(organization, holder, "small") == 4
    sale.refresh_from_db()
    assert sale.number.startswith("BL-")
    assert sale.amount_due == Decimal("280.000")


def test_changing_the_lines_of_a_draft_bl_keeps_its_address_and_boxes(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(
        organization, actor, cold_room, truck, [part(restaurant, dorade, "10", address="Quai 3", boxes={"big": 2})]
    )
    (sale,) = Sale.objects.filter(transfer=transfer)

    services.update_sale(
        sale=sale,
        actor=actor,
        customer=restaurant,
        location=truck,
        lines=[{"product": dorade, "quantity": "8", "unit_price": "28.000"}],
    )
    sale.refresh_from_db()
    assert sale.delivery_address == "Quai 3"
    assert {box.box_type: box.count for box in sale.box_lines.all()} == {"big": 2}

    services.update_sale(
        sale=sale,
        actor=actor,
        customer=restaurant,
        location=truck,
        lines=[{"product": dorade, "quantity": "8", "unit_price": "28.000"}],
        delivery_address="Quai 5",
    )
    sale.refresh_from_db()
    assert sale.delivery_address == "Quai 5"
    restaurant.refresh_from_db()
    assert restaurant.address == "Avenue Hédi Chaker"


def test_the_bl_of_a_load_prints_as_the_real_bl_to_deliver_with_its_address_and_boxes(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(
        organization, actor, cold_room, truck, [part(restaurant, dorade, "10", address="Quai 3", boxes={"big": 2})]
    )
    (sale,) = Sale.objects.filter(transfer=transfer)

    printable = printing.delivery_note_printable(organization, sale.pk)

    assert printable.context["provisional"] is False
    assert printable.context["to_deliver"] is True
    assert printable.context["version"] == 1
    assert printable.context["number"].startswith("BL-")
    assert printable.context["deliver_to"] == "Quai 3"
    assert printable.context["boxes"] == [("Grande caisse", 2)]


def test_an_ordinary_draft_sale_still_has_no_bl(organization, actor, truck, dorade, restaurant):
    sale = services.create_sale(
        organization=organization,
        actor=actor,
        customer=restaurant,
        location=truck,
        lines=[{"product": dorade, "quantity": "1", "unit_price": "28.000"}],
    )

    with pytest.raises(ValidationError):
        printing.delivery_note_printable(organization, sale.pk)


def test_a_client_part_that_asks_for_too_much_is_refused_on_its_own_line(
    organization, actor, cold_room, truck, dorade, restaurant, hotel, stocked
):
    with pytest.raises(ValidationError) as refused:
        load(organization, actor, cold_room, truck, [part(restaurant, dorade, "30"), part(hotel, dorade, "30")])

    assert "deliveries.1.lines.0.quantity" in refused.value.message_dict
    assert not Sale.objects.filter(organization=organization).exists()
    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("0.000")


def test_a_client_appears_once_and_only_a_load_is_split_by_client(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    with pytest.raises(ValidationError) as twice:
        load(organization, actor, cold_room, truck, [part(restaurant, dorade, "5"), part(restaurant, dorade, "5")])
    other_room = StockLocationFactory.create(organization=organization, name="Chambre froide 2")
    with pytest.raises(ValidationError) as not_a_load:
        load(organization, actor, cold_room, other_room, [part(restaurant, dorade, "5")])

    assert "deliveries.1.customer" in twice.value.message_dict
    assert "deliveries" in not_a_load.value.message_dict


def test_the_part_kept_on_the_truck_makes_no_bl(organization, actor, cold_room, truck, dorade, restaurant, stocked):
    transfer = load(
        organization,
        actor,
        cold_room,
        truck,
        [part(restaurant, dorade, "10")],
        lines=[{"product": dorade, "quantity": "15"}],
    )

    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("25.000")
    assert Sale.objects.filter(transfer=transfer).count() == 1


# ---- A load from the cold rooms together (D-174) ----


def _received(organization, product, room, kg):
    batch = BatchFactory.create(organization=organization, product=product, received_on=timezone.localdate())
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=Decimal(kg),
        to_location=room,
    )


def _held(room, product):
    return sum((row.quantity for row in StockOnHand.objects.filter(location=room, product=product)), Decimal("0.000"))


def test_a_load_from_the_cold_rooms_takes_the_kilos_from_each_room_in_turn(
    organization, actor, cold_room, truck, dorade, restaurant
):
    second_room = StockLocationFactory.create(organization=organization, name="Chambre froide 2")
    _received(organization, dorade, cold_room, "30")
    _received(organization, dorade, second_room, "40")

    transfer = inventory_services.create_transfer(
        organization=organization,
        actor=actor,
        from_location=cold_room,
        to_location=truck,
        transferred_on=timezone.localdate(),
        lines=[],
        deliveries=[part(restaurant, dorade, "50")],
        from_cold_rooms=True,
        validate=True,
    )

    assert transfer.from_cold_rooms is True
    assert _held(cold_room, dorade) == Decimal("0.000")
    assert _held(second_room, dorade) == Decimal("20.000")
    assert _held(truck, dorade) == Decimal("50.000")
    assert Sale.objects.filter(transfer=transfer, customer=restaurant).count() == 1


def test_a_load_from_the_cold_rooms_is_refused_when_the_rooms_together_hold_too_little(
    organization, actor, cold_room, truck, dorade, restaurant
):
    second_room = StockLocationFactory.create(organization=organization, name="Chambre froide 2")
    _received(organization, dorade, cold_room, "30")
    _received(organization, dorade, second_room, "40")

    with pytest.raises(ValidationError) as refused:
        inventory_services.create_transfer(
            organization=organization,
            actor=actor,
            from_location=cold_room,
            to_location=truck,
            transferred_on=timezone.localdate(),
            lines=[],
            deliveries=[part(restaurant, dorade, "80")],
            from_cold_rooms=True,
            validate=True,
        )

    assert "deliveries.0.lines.0.quantity" in refused.value.message_dict
    assert _held(cold_room, dorade) == Decimal("30.000")


def test_only_a_load_into_a_truck_leaves_from_the_cold_rooms_together(organization, actor, cold_room, dorade):
    second_room = StockLocationFactory.create(organization=organization, name="Chambre froide 2")
    _received(organization, dorade, cold_room, "30")

    with pytest.raises(ValidationError) as refused:
        inventory_services.create_transfer(
            organization=organization,
            actor=actor,
            from_location=cold_room,
            to_location=second_room,
            transferred_on=timezone.localdate(),
            lines=[{"product": dorade, "quantity": "5"}],
            from_cold_rooms=True,
        )

    assert "from_location" in refused.value.message_dict


def test_the_clients_of_the_days_load_are_the_drivers_customers(
    organization, actor, cold_room, truck, dorade, restaurant, hotel, stocked
):
    load(organization, actor, cold_room, truck, [part(restaurant, dorade, "5"), part(hotel, dorade, "6")])

    found = selectors.load_customer_ids(organization, location_id=truck.pk, day=timezone.localdate())

    assert sorted(found) == sorted([restaurant.pk, hotel.pk])
    assert (
        selectors.load_customer_ids(organization, location_id=truck.pk, day=timezone.localdate() - dt.timedelta(days=1))
        == []
    )


# ---- Delivered by the driver: in full, in part, or not at all (D-178) ----


@pytest.fixture
def loup(organization, cold_room):
    product = ProductFactory.create(organization=organization, name="Loup de mer", reference="LO-004")
    ProductPriceFactory.create(
        product=product, price=Decimal("30.000"), valid_from=timezone.now() - dt.timedelta(days=3)
    )
    batch = BatchFactory.create(organization=organization, product=product, received_on=timezone.localdate())
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=Decimal("20"),
        to_location=cold_room,
    )
    return product


def two_products(customer, dorade, loup, *, boxes=None):
    return {
        "customer": customer,
        "delivery_address": "",
        "lines": [{"product": dorade, "quantity": "10"}, {"product": loup, "quantity": "5"}],
        "boxes": boxes or {},
    }


def test_the_bl_of_a_load_is_validated_with_its_number_and_nothing_is_sold_yet(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10")])
    (sale,) = Sale.objects.filter(transfer=transfer)

    assert sale.number == f"BL-{timezone.localdate().year}-0001"
    assert (sale.status, sale.delivery_status, sale.version) == (SaleStatus.DRAFT, DeliveryStatus.TO_DELIVER, 1)
    assert sale.issued_at is not None
    assert [line.ordered_quantity for line in sale.lines.all()] == [Decimal("10.000")]
    assert [revision.kind for revision in sale.revisions.all()] == [SaleRevisionKind.ISSUED]
    # Nothing is owed nor to invoice before the delivery.
    assert selectors.sales_of(organization, uninvoiced=True).count() == 0


def test_a_bl_delivered_as_written_keeps_its_number_and_version(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10", boxes={"small": 2})])
    (sale,) = Sale.objects.filter(transfer=transfer)
    number = sale.number

    delivered = services.deliver_sale(sale=sale, actor=actor)

    assert (delivered.status, delivered.delivery_status, delivered.version) == (
        SaleStatus.CONFIRMED,
        DeliveryStatus.DELIVERED,
        1,
    )
    assert delivered.number == number
    assert delivered.amount_due == Decimal("280.000")
    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("0.000")


def test_a_part_delivery_sells_only_what_was_delivered_and_the_rest_stays_on_the_truck(
    organization, actor, cold_room, truck, dorade, loup, restaurant, stocked
):
    transfer = load(organization, actor, cold_room, truck, [two_products(restaurant, dorade, loup, boxes={"big": 3})])
    (sale,) = Sale.objects.filter(transfer=transfer)
    dorade_line, loup_line = sale.lines.order_by("id")

    delivered = services.deliver_sale(
        sale=sale,
        actor=actor,
        lines=[{"line": dorade_line.pk, "quantity": "8"}, {"line": loup_line.pk, "quantity": "0"}],
        boxes={"big": 2},
        note="Pas de loup aujourd'hui",
        payment={"amount_paid": "100.000", "payment_method": "cash"},
    )

    assert (delivered.status, delivered.delivery_status, delivered.version) == (
        SaleStatus.CONFIRMED,
        DeliveryStatus.PARTIAL,
        2,
    )
    (line,) = delivered.lines.all()
    assert (line.product, line.ordered_quantity, line.quantity, line.amount) == (
        dorade,
        Decimal("10.000"),
        Decimal("8.000"),
        Decimal("224.000"),
    )
    assert (delivered.total, delivered.amount_paid, delivered.amount_due) == (
        Decimal("224.000"),
        Decimal("100.000"),
        Decimal("124.000"),
    )
    # 2 kg of dorade and the 5 kg of loup are still on the truck, for the road or the return.
    assert inventory.quantity_on_hand(organization, location_id=truck.pk, product_id=dorade.pk) == Decimal("2.000")
    assert inventory.quantity_on_hand(organization, location_id=truck.pk, product_id=loup.pk) == Decimal("5.000")
    holder = BoxHolder.objects.get(organization=organization, customer=restaurant)
    assert box_selectors.balance_of(organization, holder, "big") == 2
    revision = delivered.revisions.order_by("-id").first()
    assert revision is not None
    assert (revision.kind, revision.version, revision.note) == (
        SaleRevisionKind.DELIVERED,
        2,
        "Pas de loup aujourd'hui",
    )
    assert {row["name"]: (row["ordered"], row["delivered"]) for row in revision.lines} == {
        "Dorade royale": ("10.000", "8.000"),
        "Loup de mer": ("5.000", "0.000"),
    }
    printable = printing.delivery_note_printable(organization, delivered.pk)
    assert printable.context["delivered"] is True
    assert [row["name"] for row in printable.context["removed"]] == ["Loup de mer"]


def test_more_than_written_is_the_weight_at_the_client(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(
        organization,
        actor,
        cold_room,
        truck,
        [part(restaurant, dorade, "10")],
        lines=[{"product": dorade, "quantity": "1"}],
    )
    (sale,) = Sale.objects.filter(transfer=transfer)
    (line,) = sale.lines.all()

    delivered = services.deliver_sale(sale=sale, actor=actor, lines=[{"line": line.pk, "quantity": "10.400"}])

    assert (delivered.delivery_status, delivered.version, delivered.total) == (
        DeliveryStatus.DELIVERED,
        2,
        Decimal("291.200"),
    )


def test_a_bl_not_delivered_sells_nothing_and_cannot_be_delivered_again(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10", boxes={"small": 2})])
    (sale,) = Sale.objects.filter(transfer=transfer)

    gone = services.cancel_delivery(sale=sale, actor=actor, note="Restaurant fermé")

    assert (gone.status, gone.delivery_status, gone.delivery_note) == (
        SaleStatus.CANCELLED,
        DeliveryStatus.CANCELLED,
        "Restaurant fermé",
    )
    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("10.000")
    with pytest.raises(ValidationError):
        services.deliver_sale(sale=gone, actor=actor)


def test_all_lines_at_zero_is_not_delivered(organization, actor, cold_room, truck, dorade, restaurant, stocked):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10")])
    (sale,) = Sale.objects.filter(transfer=transfer)
    (line,) = sale.lines.all()

    gone = services.deliver_sale(sale=sale, actor=actor, lines=[{"line": line.pk, "quantity": "0"}])

    assert gone.delivery_status == DeliveryStatus.CANCELLED


def test_a_retry_of_the_phone_records_one_delivery(organization, actor, cold_room, truck, dorade, restaurant, stocked):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10")])
    (sale,) = Sale.objects.filter(transfer=transfer)
    (line,) = sale.lines.all()
    key = uuid4()

    first = services.deliver_sale(sale=sale, actor=actor, lines=[{"line": line.pk, "quantity": "6"}], delivery_uuid=key)
    again = services.deliver_sale(sale=sale, actor=actor, lines=[{"line": line.pk, "quantity": "6"}], delivery_uuid=key)

    assert first.pk == again.pk
    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("4.000")


def test_the_office_changing_the_bl_on_the_road_makes_a_new_version(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10")])
    (sale,) = Sale.objects.filter(transfer=transfer)

    services.update_sale(
        sale=sale,
        actor=actor,
        customer=restaurant,
        location=truck,
        lines=[{"product": dorade, "quantity": "7", "unit_price": "28.000"}],
    )

    sale.refresh_from_db()
    assert (sale.version, sale.delivery_status) == (2, DeliveryStatus.TO_DELIVER)
    assert [line.ordered_quantity for line in sale.lines.all()] == [Decimal("7.000")]
    assert [revision.kind for revision in sale.revisions.order_by("id")] == [
        SaleRevisionKind.ISSUED,
        SaleRevisionKind.EDITED,
    ]


def test_the_office_marking_it_delivered_delivers_it_as_written(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "10")])
    (sale,) = Sale.objects.filter(transfer=transfer)

    confirmed = services.confirm_sale(sale=sale, actor=actor)

    assert (confirmed.delivery_status, confirmed.delivered_by) == (DeliveryStatus.DELIVERED, actor)
    last = confirmed.revisions.order_by("-id").first()
    assert last is not None
    assert last.kind == SaleRevisionKind.DELIVERED


def test_the_bl_still_to_deliver_at_the_end_of_the_day_are_not_delivered(
    organization, actor, cold_room, truck, dorade, restaurant, hotel, stocked
):
    transfer = load(organization, actor, cold_room, truck, [part(restaurant, dorade, "5"), part(hotel, dorade, "6")])
    corail, thyna = Sale.objects.filter(transfer=transfer).order_by("id")
    services.deliver_sale(sale=corail, actor=actor)

    gone = services.cancel_undelivered(organization=organization, location_id=truck.pk, actor=actor)

    assert [sale.pk for sale in gone] == [thyna.pk]
    thyna.refresh_from_db()
    assert thyna.delivery_status == DeliveryStatus.CANCELLED
    assert inventory.quantity_on_hand(organization, location_id=truck.pk) == Decimal("6.000")


def test_a_bl_of_a_product_sold_with_vat_keeps_its_rate_and_takes_the_vat_of_the_kilos_left(
    organization, actor, cold_room, truck, dorade, restaurant, stocked
):
    # The lot is bought with VAT (D-202): the BL carries its VAT from the load on (D-224).
    stocked.bought_with_vat = True
    stocked.save(update_fields=["bought_with_vat"])
    transfer = load(
        organization,
        actor,
        cold_room,
        truck,
        [part(restaurant, dorade, "10")],
        lines=[{"product": dorade, "quantity": "1"}],
    )
    (sale,) = Sale.objects.filter(transfer=transfer)
    (line,) = sale.lines.all()
    assert (line.vat_rate, line.amount, line.vat_amount) == (Decimal("19.00"), Decimal("280.000"), Decimal("53.200"))

    delivered = services.deliver_sale(sale=sale, actor=actor, lines=[{"line": line.pk, "quantity": "8"}])

    (line,) = delivered.lines.all()
    assert (line.vat_rate, line.amount, line.amount_excl_tax, line.vat_amount, line.amount_incl_tax) == (
        Decimal("19.00"),
        Decimal("224.000"),
        Decimal("224.000"),
        Decimal("42.560"),
        Decimal("266.560"),
    )
    assert (delivered.amount_excl_tax, delivered.vat_total, delivered.total_incl_tax) == (
        Decimal("224.000"),
        Decimal("42.560"),
        Decimal("266.560"),
    )
