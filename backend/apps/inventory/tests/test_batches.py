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

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog, NumberSeries, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.inventory import selectors, services
from apps.inventory.models import Batch
from apps.partners.tests.factories import SupplierFactory

from .factories import BatchFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


def new_batch(organization, actor, **fields):
    values: dict[str, Any] = {
        "product": ProductFactory.create(organization=organization),
        "supplier": SupplierFactory.create(organization=organization),
        "received_on": timezone.localdate(),
        "unit_cost": "34.000",
    }
    values.update(fields)
    return services.create_batch(organization=organization, actor=actor, **values)


# ---- services ----


def test_batches_are_numbered_in_order_per_organization(organization, actor):
    numbers = [new_batch(organization, actor).number for _ in range(3)]

    assert numbers == ["L-0001", "L-0002", "L-0003"]
    assert new_batch(OrganizationFactory.create(), actor).number == "L-0001"


def test_the_number_keeps_growing_past_four_digits(organization, actor):
    new_batch(organization, actor)
    NumberSeries.objects.filter(organization=organization, kind="batch").update(last_number=9999)

    assert new_batch(organization, actor).number == "L-10000"


def test_a_batch_keeps_its_cost_dates_and_receipt_and_is_audited(organization, actor):
    received_on = timezone.localdate() - dt.timedelta(days=2)
    batch = new_batch(
        organization,
        actor,
        unit_cost=Decimal("18.5"),
        receipt_reference=" AQM-0784 ",
        received_on=received_on,
        use_by=received_on + dt.timedelta(days=5),
    )

    batch.refresh_from_db()
    assert (batch.unit_cost, batch.receipt_reference) == (Decimal("18.500"), "AQM-0784")
    assert batch.use_by == received_on + dt.timedelta(days=5)
    log = AuditLog.objects.get(action="batch.created")
    assert log.after is not None
    assert log.after["number"] == "L-0001"
    assert log.after["unit_cost"] == "18.500"


def test_the_same_product_from_two_suppliers_makes_two_batches(organization, actor):
    dorade = ProductFactory.create(organization=organization)
    first = new_batch(organization, actor, product=dorade, unit_cost="20.000")
    second = new_batch(organization, actor, product=dorade, unit_cost="18.500")

    assert first.supplier != second.supplier
    assert selectors.batches_of(organization, product_id=dorade.pk).count() == 2


@pytest.mark.parametrize(
    ("fields", "field"),
    [
        ({"unit_cost": "-1"}, "unit_cost"),
        ({"unit_cost": "20.0005"}, "unit_cost"),  # finer than a millime: refused, not rounded
        ({"received_on": timezone.localdate() + dt.timedelta(days=1)}, "received_on"),
        ({"use_by": timezone.localdate() - dt.timedelta(days=1)}, "use_by"),
    ],
)
def test_wrong_values_are_refused_per_field(organization, actor, fields, field):
    with pytest.raises(ValidationError) as caught:
        new_batch(organization, actor, **fields)

    assert list(caught.value.message_dict) == [field]
    assert not Batch.objects.exists()


def test_a_free_delivery_has_a_zero_cost(organization, actor):
    assert new_batch(organization, actor, unit_cost="0").unit_cost == Decimal("0.000")


def test_products_and_suppliers_must_be_active_and_of_the_organization(organization, actor):
    with pytest.raises(ValidationError) as caught:
        new_batch(organization, actor, product=ProductFactory.create(), supplier=SupplierFactory.create())
    assert set(caught.value.message_dict) == {"product", "supplier"}

    with pytest.raises(ValidationError) as caught:
        new_batch(
            organization,
            actor,
            product=ProductFactory.create(organization=organization, is_active=False),
            supplier=SupplierFactory.create(organization=organization, is_active=False),
        )
    assert set(caught.value.message_dict) == {"product", "supplier"}


def test_a_refused_batch_does_not_use_a_number(organization, actor):
    with pytest.raises(ValidationError):
        new_batch(organization, actor, unit_cost="-1")

    assert new_batch(organization, actor).number == "L-0001"


def test_batches_leave_oldest_first_and_are_listed_newest_first(organization, actor):
    product = ProductFactory.create(organization=organization)
    today = timezone.localdate()
    late = new_batch(organization, actor, product=product, received_on=today)
    early = new_batch(organization, actor, product=product, received_on=today - dt.timedelta(days=3))
    same_day = new_batch(organization, actor, product=product, received_on=today)

    assert list(selectors.batches_oldest_first(organization, product_id=product.pk)) == [early, late, same_day]
    assert list(selectors.batches_of(organization)) == [same_day, late, early]


def test_the_search_matches_number_receipt_product_and_supplier(organization, actor):
    product = ProductFactory.create(organization=organization, name="Dorade royale", reference="DO-003")
    supplier = SupplierFactory.create(organization=organization, name="Aqua Monastir")
    batch = new_batch(organization, actor, product=product, supplier=supplier, receipt_reference="AQM-0784")
    new_batch(organization, actor)

    for search in ("L-0001", "aqm-07", "dorade", "DO-003", "monastir"):
        assert list(selectors.batches_of(organization, search=search)) == [batch]


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_receipts_at_the_same_moment_never_share_a_number():
    organization = OrganizationFactory.create()
    product = ProductFactory.create(organization=organization)
    supplier = SupplierFactory.create(organization=organization)
    numbers: list[str] = []
    errors: list[Exception] = []
    start = threading.Barrier(4)

    def receive() -> None:
        try:
            start.wait()
            batch = services.create_batch(
                organization=organization,
                actor=None,
                product=product,
                supplier=supplier,
                received_on=timezone.localdate(),
                unit_cost="10.000",
            )
            numbers.append(batch.number)
        except Exception as error:  # noqa: BLE001 - every failure is reported by the assertion below
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=receive) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert errors == []
    assert sorted(numbers) == ["L-0001", "L-0002", "L-0003", "L-0004"]


# ---- API ----


def client_for(role, organization=None):
    membership = MembershipFactory.create(role=role, organization=organization or OrganizationFactory.create())
    client = APIClient()
    client.force_authenticate(membership.user)
    return client, membership


def test_the_office_lists_batches_newest_first_with_product_and_supplier():
    client, owner = client_for(Role.OWNER)
    old = BatchFactory.create(organization=owner.organization, received_on=timezone.localdate() - dt.timedelta(days=1))
    new = BatchFactory.create(organization=owner.organization, unit_cost=Decimal("18.500"))

    answer = client.get(reverse("batch-list"))

    assert answer.status_code == 200
    body = answer.json()
    assert body["count"] == 2
    assert [row["id"] for row in body["results"]] == [new.pk, old.pk]
    row = body["results"][0]
    assert row["unit_cost"] == "18.500"  # amounts travel as strings
    assert row["product"] == {
        "id": new.product.pk,
        "reference": new.product.reference,
        "name": new.product.name,
        "is_active": True,
    }
    assert row["supplier"]["reference"] == new.supplier.reference


def test_a_lot_says_when_its_product_is_archived():
    # The lot pickers leave out the lots of an archived product (D-145).
    client, owner = client_for(Role.OWNER)
    product = ProductFactory.create(organization=owner.organization, is_active=False)
    BatchFactory.create(organization=owner.organization, product=product)

    row = client.get(reverse("batch-list")).json()["results"][0]

    assert row["product"]["is_active"] is False


def test_the_list_filters_by_product_supplier_and_search_and_is_paginated():
    client, owner = client_for(Role.MANAGER)
    batch = BatchFactory.create(organization=owner.organization, receipt_reference="MPS-5521")
    BatchFactory.create_batch(3, organization=owner.organization)

    def ids(**params: object) -> list[int]:
        return [row["id"] for row in client.get(reverse("batch-list"), params).json()["results"]]

    assert ids(product=batch.product.pk) == [batch.pk]
    assert ids(supplier=batch.supplier.pk) == [batch.pk]
    assert ids(search="mps-55") == [batch.pk]
    page = client.get(reverse("batch-list"), {"limit": 2, "offset": 0}).json()
    assert (page["count"], len(page["results"]), page["next"] is not None) == (4, 2, True)
    assert client.get(reverse("batch-list"), {"product": "x"}).status_code == 400


def test_one_batch_is_read_by_id_and_other_organizations_stay_invisible():
    client, owner = client_for(Role.ACCOUNTANT)
    batch = BatchFactory.create(organization=owner.organization)
    other = BatchFactory.create()

    assert client.get(reverse("batch-detail", args=[batch.pk])).json()["number"] == batch.number
    assert client.get(reverse("batch-detail", args=[other.pk])).status_code == 404
    assert client.get(reverse("batch-list")).json()["count"] == 1


def test_drivers_and_strangers_cannot_read_batches():
    client, _ = client_for(Role.DRIVER)

    assert client.get(reverse("batch-list")).status_code == 403
    assert APIClient().get(reverse("batch-list")).status_code == 401


def test_batches_are_not_created_or_changed_through_the_api():
    client, owner = client_for(Role.OWNER)
    batch = BatchFactory.create(organization=owner.organization)

    assert client.post(reverse("batch-list"), {}).status_code == 405
    assert client.patch(reverse("batch-detail", args=[batch.pk]), {}, format="json").status_code == 405
