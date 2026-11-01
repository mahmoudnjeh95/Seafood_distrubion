import datetime as dt
import threading
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.inventory import selectors, services
from apps.inventory.models import (
    LocationKind,
    MovementKind,
    StockMovement,
    Transfer,
    TransferKind,
    TransferStatus,
)

from .factories import BatchFactory, StockLocationFactory

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


def receive(organization, product, location, kg, *, days_ago=0):
    batch = BatchFactory.create(
        organization=organization, product=product, received_on=timezone.localdate() - dt.timedelta(days=days_ago)
    )
    services.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )
    return batch


def transfer(organization, actor, source, target, lines, **fields):
    values: dict[str, Any] = {"transferred_on": timezone.localdate()}
    values.update(fields)
    return services.create_transfer(
        organization=organization, actor=actor, from_location=source, to_location=target, lines=lines, **values
    )


def on_hand(organization, location, product=None):
    return selectors.quantity_on_hand(
        organization, location_id=location.pk, product_id=product.pk if product is not None else None
    )


# ---- services ----


def test_a_draft_moves_nothing_until_it_is_validated(organization, actor, cold_room, truck, dorade):
    receive(organization, dorade, cold_room, "30")

    draft = transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "12"}])

    assert (draft.number, draft.kind, draft.status) == ("TR-0001", TransferKind.LOAD, TransferStatus.DRAFT)
    assert on_hand(organization, truck) == 0
    validated = services.validate_transfer(transfer=draft, actor=actor)
    assert (validated.status, validated.validated_by) == (TransferStatus.VALIDATED, actor)
    assert validated.validated_at is not None
    assert on_hand(organization, cold_room) == Decimal("18.000")
    assert on_hand(organization, truck) == Decimal("12.000")
    assert list(AuditLog.objects.filter(target_id=str(draft.pk)).values_list("action", flat=True).order_by("id")) == [
        "transfer.created",
        "transfer.validated",
    ]


def test_the_kind_comes_from_the_two_places(organization, actor, cold_room, truck, dorade):
    other_room = StockLocationFactory.create(organization=organization, name="Chambre froide 2")
    other_truck = StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK)
    line = [{"product": dorade, "quantity": "1"}]

    assert transfer(organization, actor, truck, cold_room, line).kind == TransferKind.RETURN
    assert transfer(organization, actor, cold_room, other_room, line).kind == TransferKind.INTERNAL
    assert transfer(organization, actor, truck, other_truck, line).kind == TransferKind.INTERNAL


def test_a_load_carries_the_price_in_force_or_the_one_typed(organization, actor, cold_room, truck, dorade):
    loup = ProductFactory.create(organization=organization, name="Loup")
    ProductPriceFactory.create(product=loup, price=Decimal("35.000"), valid_from=timezone.now() - dt.timedelta(days=2))
    # A price planned for later is not the price of the day.
    ProductPriceFactory.create(product=loup, price=Decimal("99.000"), valid_from=timezone.now() + dt.timedelta(days=2))

    load = transfer(
        organization,
        actor,
        cold_room,
        truck,
        [{"product": dorade, "quantity": "10", "unit_price": "30.500"}, {"product": loup, "quantity": "4"}],
    )

    prices = {line.product_id: line.unit_price for line in load.lines.all()}
    assert prices == {dorade.pk: Decimal("30.500"), loup.pk: Decimal("35.000")}
    # Returns and moves between cold rooms carry no price.
    back = transfer(organization, actor, truck, cold_room, [{"product": dorade, "quantity": "1", "unit_price": "30"}])
    assert back.lines.get().unit_price is None


def test_a_load_without_any_price_asks_for_one(organization, actor, cold_room, truck):
    unpriced = ProductFactory.create(organization=organization)

    with pytest.raises(ValidationError) as refused:
        transfer(organization, actor, cold_room, truck, [{"product": unpriced, "quantity": "2"}])

    assert list(refused.value.message_dict) == ["lines.0.unit_price"]


def test_every_problem_is_reported_at_once_and_nothing_is_written(organization, actor, cold_room, truck, dorade):
    elsewhere = ProductFactory.create()
    archived = ProductFactory.create(organization=organization, is_active=False)

    with pytest.raises(ValidationError) as refused:
        transfer(
            organization,
            actor,
            cold_room,
            truck,
            [
                {"product": dorade, "quantity": "2,5", "unit_price": "0"},
                {"product": dorade, "quantity": "1"},
                {"product": elsewhere, "quantity": "1"},
                {"product": archived, "quantity": "-1"},
            ],
        )

    assert set(refused.value.message_dict) == {
        "lines.0.quantity",
        "lines.0.unit_price",
        "lines.1.product",
        "lines.2.product",
        "lines.3.product",
        "lines.3.quantity",
    }
    assert not Transfer.objects.exists()


def test_the_two_places_must_differ_be_active_and_ours(organization, actor, cold_room, dorade):
    archived = StockLocationFactory.create(organization=organization, is_active=False)
    foreign = StockLocationFactory.create()
    line = [{"product": dorade, "quantity": "1"}]

    for source, target, field in (
        (cold_room, cold_room, "to_location"),
        (cold_room, archived, "to_location"),
        (foreign, cold_room, "from_location"),
    ):
        with pytest.raises(ValidationError) as refused:
            transfer(organization, actor, source, target, line)
        assert list(refused.value.message_dict) == [field]
    with pytest.raises(ValidationError) as empty:
        transfer(organization, actor, cold_room, StockLocationFactory.create(organization=organization), [])
    assert list(empty.value.message_dict) == ["lines"]


def test_kg_leave_the_oldest_batch_first_and_the_line_keeps_its_batches(organization, actor, cold_room, truck, dorade):
    recent = receive(organization, dorade, cold_room, "20", days_ago=1)
    old = receive(organization, dorade, cold_room, "5", days_ago=3)

    load = transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "8"}], validate=True)

    line = load.lines.get()
    moved = selectors.movements_from_sources([line])[line.pk]
    assert [(movement.batch, movement.quantity) for movement in moved] == [
        (old, Decimal("5.000")),
        (recent, Decimal("3.000")),
    ]
    assert {movement.kind for movement in moved} == {MovementKind.TRANSFER}


def test_more_than_the_source_holds_is_refused_on_the_line_and_nothing_moves(
    organization, actor, cold_room, truck, dorade
):
    loup = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=loup, valid_from=timezone.now() - dt.timedelta(days=1))
    receive(organization, dorade, cold_room, "10")
    receive(organization, loup, cold_room, "3")
    draft = transfer(
        organization,
        actor,
        cold_room,
        truck,
        [{"product": dorade, "quantity": "6"}, {"product": loup, "quantity": "4"}],
    )

    with pytest.raises(ValidationError) as refused:
        services.validate_transfer(transfer=draft, actor=actor)

    assert list(refused.value.message_dict) == ["lines.1.quantity"]
    assert "Stock insuffisant" in refused.value.message_dict["lines.1.quantity"][0]
    assert on_hand(organization, truck) == 0
    assert on_hand(organization, cold_room) == Decimal("13.000")
    assert not StockMovement.objects.filter(kind=MovementKind.TRANSFER).exists()
    draft.refresh_from_db()
    assert draft.status == TransferStatus.DRAFT


def test_create_and_validate_at_once_leaves_nothing_when_refused(organization, actor, cold_room, truck, dorade):
    receive(organization, dorade, cold_room, "2")

    with pytest.raises(ValidationError):
        transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "3"}], validate=True)

    assert not Transfer.objects.exists()


def test_a_day_still_to_come_is_validated_that_day(organization, actor, cold_room, truck, dorade):
    receive(organization, dorade, cold_room, "10")
    tomorrow = timezone.localdate() + dt.timedelta(days=1)
    draft = transfer(
        organization, actor, cold_room, truck, [{"product": dorade, "quantity": "2"}], transferred_on=tomorrow
    )

    with pytest.raises(ValidationError) as refused:
        services.validate_transfer(transfer=draft, actor=actor)

    assert list(refused.value.message_dict) == ["transferred_on"]


def test_a_transfer_typed_later_keeps_its_day_in_the_ledger(organization, actor, cold_room, truck, dorade):
    receive(organization, dorade, cold_room, "10", days_ago=3)
    yesterday = timezone.localdate() - dt.timedelta(days=1)

    load = transfer(
        organization,
        actor,
        cold_room,
        truck,
        [{"product": dorade, "quantity": "2"}],
        transferred_on=yesterday,
        validate=True,
    )

    movement = StockMovement.objects.get(kind=MovementKind.TRANSFER)
    assert timezone.localtime(movement.occurred_at).date() == yesterday
    assert movement.source == load.lines.get()


def test_a_draft_is_changed_then_frozen_once_validated(organization, actor, cold_room, truck, dorade):
    receive(organization, dorade, cold_room, "10")
    room_2 = StockLocationFactory.create(organization=organization)
    draft = transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "2"}])

    changed = services.update_transfer(
        transfer=draft,
        actor=actor,
        from_location=cold_room,
        to_location=room_2,
        transferred_on=timezone.localdate(),
        lines=[{"product": dorade, "quantity": "4"}],
        notes="Dégivrage du camion",
        validate=True,
    )

    assert (changed.kind, changed.status, changed.notes) == (
        TransferKind.INTERNAL,
        TransferStatus.VALIDATED,
        "Dégivrage du camion",
    )
    assert changed.lines.get().quantity == Decimal("4.000")
    assert on_hand(organization, room_2) == Decimal("4.000")
    for action in (
        lambda: services.validate_transfer(transfer=changed, actor=actor),
        lambda: services.cancel_transfer(transfer=changed, actor=actor),
        lambda: services.update_transfer(
            transfer=changed,
            actor=actor,
            from_location=cold_room,
            to_location=truck,
            transferred_on=timezone.localdate(),
            lines=[{"product": dorade, "quantity": "1"}],
        ),
    ):
        with pytest.raises(ValidationError, match="déjà validé"):
            action()
    assert on_hand(organization, room_2) == Decimal("4.000")


def test_a_cancelled_draft_never_moves_stock(organization, actor, cold_room, truck, dorade):
    receive(organization, dorade, cold_room, "10")
    draft = transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "2"}])

    cancelled = services.cancel_transfer(transfer=draft, actor=actor)

    assert cancelled.status == TransferStatus.CANCELLED
    with pytest.raises(ValidationError, match="annulé"):
        services.validate_transfer(transfer=cancelled, actor=actor)
    assert on_hand(organization, truck) == 0


def test_the_same_client_uuid_creates_one_transfer(organization, actor, cold_room, truck, dorade):
    import uuid

    key = uuid.uuid4()
    first = transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "2"}], client_uuid=key)
    again = transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "2"}], client_uuid=key)

    assert again == first
    assert Transfer.objects.count() == 1


def test_numbers_are_per_organization(actor, dorade, organization, cold_room, truck):
    assert transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "1"}]).number == "TR-0001"
    assert transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "1"}]).number == "TR-0002"
    other = OrganizationFactory.create()
    product = ProductFactory.create(organization=other)
    ProductPriceFactory.create(product=product, valid_from=timezone.now() - dt.timedelta(days=1))
    first_elsewhere = transfer(
        other,
        actor,
        StockLocationFactory.create(organization=other),
        StockLocationFactory.create(organization=other, kind=LocationKind.TRUCK),
        [{"product": product, "quantity": "1"}],
    )
    assert first_elsewhere.number == "TR-0001"


def test_the_truck_day_shows_loaded_minus_returned_per_product(organization, actor, cold_room, truck, dorade):
    loup = ProductFactory.create(organization=organization, name="Loup de mer")
    ProductPriceFactory.create(product=loup, price=Decimal("35.000"), valid_from=timezone.now() - dt.timedelta(days=1))
    receive(organization, dorade, cold_room, "40")
    receive(organization, loup, cold_room, "10")
    morning = [{"product": dorade, "quantity": "15", "unit_price": "30"}, {"product": loup, "quantity": "6"}]
    transfer(organization, actor, cold_room, truck, morning, validate=True)
    transfer(
        organization, actor, cold_room, truck, [{"product": dorade, "quantity": "5", "unit_price": "29"}], validate=True
    )
    transfer(organization, actor, truck, cold_room, [{"product": dorade, "quantity": "4.5"}], validate=True)
    # Drafts and other days do not count.
    transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "1"}])

    day = selectors.truck_day(organization, location_id=truck.pk, day=timezone.localdate())

    assert [(line.product_name, line.loaded, line.returned, line.sold_or_lost) for line in day] == [
        ("Dorade royale", Decimal("20.000"), Decimal("4.500"), Decimal("15.500")),
        ("Loup de mer", Decimal("6.000"), Decimal("0.000"), Decimal("6.000")),
    ]
    # The day's price is the last load's; the amount is sold or lost × that price.
    assert (day[0].unit_price, day[0].amount) == (Decimal("29.000"), Decimal("449.500"))
    assert (day[1].unit_price, day[1].amount) == (Decimal("35.000"), Decimal("210.000"))
    assert (
        selectors.truck_day(organization, location_id=truck.pk, day=timezone.localdate() - dt.timedelta(days=1)) == []
    )


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
def test_two_loads_validated_at_once_never_take_the_same_kilos():
    organization = OrganizationFactory.create()
    cold_room = StockLocationFactory.create(organization=organization)
    products = [ProductFactory.create(organization=organization) for _ in range(2)]
    for product in products:
        ProductPriceFactory.create(product=product, valid_from=timezone.now() - dt.timedelta(days=1))
        receive(organization, product, cold_room, "10")
    # Lines in opposite product orders: posting in product order keeps the two from deadlocking.
    drafts = iter(
        [
            transfer(
                organization,
                None,
                cold_room,
                StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK),
                [{"product": product, "quantity": "6"} for product in ordered],
            )
            for ordered in (products, products[::-1])
        ]
    )

    def validate() -> None:
        services.validate_transfer(transfer=next(drafts), actor=None)

    errors = run_at_once(2, validate)

    assert len(errors) == 1
    assert isinstance(errors[0], ValidationError)
    for product in products:
        assert on_hand(organization, cold_room, product) == Decimal("4.000")
    assert Transfer.objects.filter(status=TransferStatus.VALIDATED).count() == 1


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_one_draft_validated_twice_at_once_moves_once():
    organization = OrganizationFactory.create()
    cold_room = StockLocationFactory.create(organization=organization)
    truck = StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK)
    product = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=product, valid_from=timezone.now() - dt.timedelta(days=1))
    receive(organization, product, cold_room, "20")
    draft = transfer(organization, None, cold_room, truck, [{"product": product, "quantity": "5"}])

    errors = run_at_once(2, lambda: services.validate_transfer(transfer=draft, actor=None))

    assert len(errors) == 1
    assert "déjà validé" in str(errors[0])
    assert on_hand(organization, truck) == Decimal("5.000")


# ---- API ----


def client_for(role, organization=None):
    membership = MembershipFactory.create(role=role, organization=organization or OrganizationFactory.create())
    client = APIClient()
    client.force_authenticate(membership.user)
    return client, membership


def payload(source, target, product, **fields) -> dict[str, Any]:
    body: dict[str, Any] = {
        "from_location": source.pk,
        "to_location": target.pk,
        "transferred_on": timezone.localdate().isoformat(),
        "lines": [{"product": product.pk, "quantity": "12"}],
    }
    body.update(fields)
    return body


def test_the_owner_loads_a_truck_and_reads_the_batches_back():
    client, owner = client_for(Role.OWNER)
    organization = owner.organization
    room = StockLocationFactory.create(organization=organization, name="Chambre froide 1")
    truck = StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK, name="Camion 1")
    product = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(
        product=product, price=Decimal("28.000"), valid_from=timezone.now() - dt.timedelta(days=1)
    )
    batch = receive(organization, product, room, "30")

    created = client.post(reverse("transfer-list"), payload(room, truck, product), format="json")

    assert created.status_code == 201
    body = created.json()
    assert (body["number"], body["kind"], body["status"], body["total_quantity"], body["total_amount"]) == (
        "TR-0001",
        "load",
        "draft",
        "12.000",
        "336.000",
    )
    assert body["lines"][0]["unit_price"] == "28.000"
    assert body["lines"][0]["batches"] == []
    validated = client.post(reverse("transfer-validate", args=[body["id"]]))
    assert validated.status_code == 200
    assert validated.json()["status"] == "validated"
    assert validated.json()["validated_by"]
    assert validated.json()["lines"][0]["batches"] == [
        {"batch_id": batch.pk, "batch_number": batch.number, "quantity": "12.000"}
    ]
    assert client.get(reverse("transfer-detail", args=[body["id"]])).json() == validated.json()
    listed = client.get(reverse("transfer-list"), {"kind": "load", "location": truck.pk}).json()
    assert (listed["count"], listed["results"][0]["number"]) == (1, "TR-0001")
    stock = client.get(reverse("location-stock", args=[truck.pk])).json()
    assert stock == [
        {
            "product_id": product.pk,
            "product_reference": product.reference,
            "product_name": product.name,
            "quantity": "12.000",
        }
    ]
    day = client.get(reverse("transfer-truck-day"), {"location": truck.pk, "date": timezone.localdate().isoformat()})
    assert day.json()["lines"][0]["sold_or_lost"] == "12.000"
    assert day.json()["amount"] == "336.000"


def test_a_draft_is_edited_cancelled_and_errors_come_back_on_the_lines():
    client, manager = client_for(Role.MANAGER)
    organization = manager.organization
    room = StockLocationFactory.create(organization=organization)
    truck = StockLocationFactory.create(organization=organization, kind=LocationKind.TRUCK)
    product = ProductFactory.create(organization=organization)
    receive(organization, product, room, "5")

    no_price = client.post(reverse("transfer-list"), payload(room, truck, product), format="json")
    assert no_price.status_code == 400
    assert list(no_price.json()) == ["lines.0.unit_price"]
    draft = client.post(
        reverse("transfer-list"),
        payload(room, truck, product, lines=[{"product": product.pk, "quantity": "12", "unit_price": "30"}]),
        format="json",
    ).json()

    too_much = client.post(reverse("transfer-validate", args=[draft["id"]]))
    assert too_much.status_code == 400
    assert list(too_much.json()) == ["lines.0.quantity"]
    edited = client.put(
        reverse("transfer-detail", args=[draft["id"]]),
        payload(
            room,
            truck,
            product,
            lines=[{"product": product.pk, "quantity": "5", "unit_price": "31"}],
            validate_now=True,
        ),
        format="json",
    )
    assert edited.status_code == 200
    assert (edited.json()["status"], edited.json()["lines"][0]["unit_price"]) == ("validated", "31.000")
    assert client.post(reverse("transfer-cancel", args=[draft["id"]])).status_code == 400

    unknown = client.post(reverse("transfer-list"), payload(room, truck, ProductFactory.create()), format="json")
    assert list(unknown.json()) == ["lines.0.product"]


@pytest.mark.parametrize(
    ("role", "read_status", "write_status"), [(Role.ACCOUNTANT, 200, 403), (Role.DRIVER, 403, 403)]
)
def test_the_accountant_reads_and_drivers_get_nothing(role, read_status, write_status):
    client, _ = client_for(role)

    assert client.get(reverse("transfer-list")).status_code == read_status
    assert client.post(reverse("transfer-list"), {}, format="json").status_code == write_status


def test_another_organization_transfers_are_invisible():
    client, _ = client_for(Role.OWNER)
    other = OrganizationFactory.create()
    product = ProductFactory.create(organization=other)
    ProductPriceFactory.create(product=product, valid_from=timezone.now() - dt.timedelta(days=1))
    foreign = transfer(
        other,
        None,
        StockLocationFactory.create(organization=other),
        StockLocationFactory.create(organization=other, kind=LocationKind.TRUCK),
        [{"product": product, "quantity": "1"}],
    )

    assert client.get(reverse("transfer-list")).json()["count"] == 0
    assert client.get(reverse("transfer-detail", args=[foreign.pk])).status_code == 404
    assert client.post(reverse("transfer-validate", args=[foreign.pk])).status_code == 404
    day = client.get(
        reverse("transfer-truck-day"), {"location": foreign.to_location_id, "date": timezone.localdate().isoformat()}
    )
    assert day.status_code == 404


def test_a_driver_sees_the_load_of_their_own_truck_today(organization, actor, cold_room, dorade):
    from apps.fleet import services as fleet

    client, driver = client_for(Role.DRIVER, organization)
    assert client.get(reverse("my-truck-day")).status_code == 404  # no truck yet
    truck = fleet.create_truck(
        organization=organization, actor=actor, name="Camion 7", plate="107 TU 2007", driver=driver.user
    )
    receive(organization, dorade, cold_room, "20")
    services.create_transfer(
        organization=organization,
        actor=actor,
        from_location=cold_room,
        to_location=truck.location,
        transferred_on=timezone.localdate(),
        lines=[{"product": dorade, "quantity": Decimal("12")}],
        validate=True,
    )

    day = client.get(reverse("my-truck-day")).json()

    assert day["lines"][0]["loaded"] == "12.000"
    assert day["lines"][0]["unit_price"] == "28.000"
    manager, _ = client_for(Role.MANAGER, organization)
    assert manager.get(reverse("my-truck-day")).status_code == 403


def test_a_driver_sees_the_stock_and_price_of_their_truck(organization, actor, cold_room, dorade):
    from apps.fleet import services as fleet

    client, driver = client_for(Role.DRIVER, organization)
    assert client.get(reverse("my-stock")).status_code == 404  # no truck yet
    truck = fleet.create_truck(
        organization=organization, actor=actor, name="Camion 8", plate="108 TU 2008", driver=driver.user
    )
    receive(organization, dorade, cold_room, "20")
    services.create_transfer(
        organization=organization,
        actor=actor,
        from_location=cold_room,
        to_location=truck.location,
        transferred_on=timezone.localdate(),
        lines=[{"product": dorade, "quantity": Decimal("12")}],
        validate=True,
    )

    rows = client.get(reverse("my-stock")).json()

    assert rows == [
        {
            "product_id": dorade.pk,
            "product_name": "Dorade royale",
            "quantity": "12.000",
            "unit_price": "28.000",
            # No photo yet: the driver app shows a plain mark.
            "photo_url": None,
        }
    ]


def test_a_driver_reports_a_loss_with_a_photo_and_returns_the_rest_to_the_cold_room(
    organization, actor, cold_room, dorade, tmp_path, settings
):
    import io

    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    from apps.fleet import services as fleet

    settings.MEDIA_ROOT = tmp_path
    client, driver = client_for(Role.DRIVER, organization)
    truck = fleet.create_truck(
        organization=organization, actor=actor, name="Camion 9", plate="109 TU 2009", driver=driver.user
    )
    receive(organization, dorade, cold_room, "20")
    services.create_transfer(
        organization=organization,
        actor=actor,
        from_location=cold_room,
        to_location=truck.location,
        transferred_on=timezone.localdate(),
        lines=[{"product": dorade, "quantity": Decimal("12")}],
        validate=True,
    )
    buffer = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(buffer, format="JPEG")
    photo = SimpleUploadedFile("loss.jpg", buffer.getvalue(), content_type="image/jpeg")

    lost = client.post(
        reverse("my-losses"),
        {"product": dorade.pk, "quantity": "1", "reason": "spoiled", "photo": photo},
        format="multipart",
    )
    assert lost.status_code == 201
    assert lost.json()["status"] == "approved"
    assert client.get(reverse("my-stock")).json()[0]["quantity"] == "11.000"

    returned = client.post(reverse("my-return"))

    assert returned.status_code == 201
    assert (returned.json()["to_location"], returned.json()["total_quantity"]) == ("Chambre froide 1", "11.000")
    assert client.get(reverse("my-stock")).json() == []
    assert client.post(reverse("my-return")).status_code == 400  # nothing left


def test_my_stock_shows_the_price_a_customer_pays_when_the_driver_asks_for_them(organization, actor, cold_room, dorade):
    from apps.catalog.models import PriceList, PriceListItem
    from apps.fleet import services as fleet
    from apps.partners import services as partners

    client, driver = client_for(Role.DRIVER, organization)
    truck = fleet.create_truck(
        organization=organization, actor=actor, name="Camion 9", plate="109 TU 2009", driver=driver.user
    )
    receive(organization, dorade, cold_room, "20")
    services.create_transfer(
        organization=organization,
        actor=actor,
        from_location=cold_room,
        to_location=truck.location,
        transferred_on=timezone.localdate(),
        lines=[{"product": dorade, "quantity": Decimal("12")}],
        validate=True,
    )
    corail = partners.create_customer(organization=organization, actor=actor, name="Le Corail")
    price_list = PriceList.objects.create(organization=organization, name="Le Corail", customer=corail, is_active=True)
    PriceListItem.objects.create(
        organization=organization, price_list=price_list, product=dorade, price=Decimal("25.000")
    )

    daily = client.get(reverse("my-stock")).json()
    for_corail = client.get(reverse("my-stock"), {"customer": corail.pk}).json()
    unknown = client.get(reverse("my-stock"), {"customer": 999999})

    assert (daily[0]["unit_price"], for_corail[0]["unit_price"]) == ("28.000", "25.000")
    assert unknown.status_code == 400


def test_lots_picked_on_a_load_leave_first_then_the_oldest_first(organization, actor, cold_room, truck, dorade):
    old = receive(organization, dorade, cold_room, "5", days_ago=3)
    recent = receive(organization, dorade, cold_room, "20", days_ago=1)
    receive(organization, dorade, cold_room, "10")

    load = transfer(
        organization,
        actor,
        cold_room,
        truck,
        [{"product": dorade, "quantity": "8", "picks": [{"batch": recent, "quantity": "3"}]}],
        validate=True,
    )

    line = load.lines.get()
    moved = selectors.movements_from_sources([line])[line.pk]
    assert [(movement.batch, movement.quantity) for movement in moved] == [
        (recent, Decimal("3.000")),
        (old, Decimal("5.000")),
    ]


def test_lots_picked_on_a_line_asking_more_than_the_line_are_refused(organization, actor, cold_room, truck, dorade):
    first = receive(organization, dorade, cold_room, "10")
    second = receive(organization, dorade, cold_room, "10")
    picks = [{"batch": first, "quantity": "3"}, {"batch": second, "quantity": "3"}]

    with pytest.raises(ValidationError) as refused:
        transfer(organization, actor, cold_room, truck, [{"product": dorade, "quantity": "5", "picks": picks}])

    assert "lines.0.picks" in refused.value.message_dict
    assert on_hand(organization, cold_room, dorade) == Decimal("20.000")


def test_lots_cannot_be_picked_on_a_load_from_several_cold_rooms(organization, actor, cold_room, truck, dorade):
    lot = receive(organization, dorade, cold_room, "10")

    with pytest.raises(ValidationError) as refused:
        transfer(
            organization,
            actor,
            cold_room,
            truck,
            [{"product": dorade, "quantity": "2", "picks": [{"batch": lot, "quantity": "2"}]}],
            from_cold_rooms=True,
        )

    assert "lines.0.picks" in refused.value.message_dict
