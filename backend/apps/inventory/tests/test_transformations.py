"""Transformations (D-304): kilos of a lot become a new lot of another product; the fee and the weight lost go into
the new lot's cost, and each lot's result counts only its own kilos."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.closing import selectors as closing
from apps.core.tests.factories import OrganizationFactory
from apps.inventory import selectors, services
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def room(organization):
    return StockLocationFactory.create(organization=organization)


@pytest.fixture
def whole(organization, room):
    product = ProductFactory.create(organization=organization, name="Loup entier")
    batch = BatchFactory.create(
        organization=organization,
        product=product,
        unit_cost=D("20.000"),
        received_on=timezone.localdate() - dt.timedelta(days=2),
        catch_area="37.2.2",
        number="SRC-1",
    )
    services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=D("50"),
        to_location=room,
    )
    return batch


def transform(organization, room, whole, **fields):
    fillet = ProductFactory.create(organization=organization, name="Filet de loup")
    values = {
        "source_quantity": "10",
        "output_quantity": "6",
        "fee": "12.000",
        "done_on": timezone.localdate(),
        **fields,
    }
    return services.create_transformation(
        organization=organization,
        actor=None,
        location=room,
        source_batch=whole,
        output_product=fillet,
        **values,
    )


def test_the_new_lot_carries_the_cost_the_fee_and_the_weight_lost(organization, room, whole):
    made = transform(organization, room, whole)

    output = made.output_batch
    # (10 kg × 20.000 + 12.000) / 6 kg = 35.333
    assert output.unit_cost == D("35.333")
    assert (output.supplier_id, output.received_on, output.catch_area) == (
        whole.supplier_id,
        whole.received_on,
        "37.2.2",
    )
    assert made.number.startswith("TF-")
    assert made.weight_lost == D("4.000")
    assert selectors.quantity_on_hand(organization, batch_id=whole.pk) == D("40.000")
    assert selectors.quantity_on_hand(organization, batch_id=output.pk) == D("6.000")
    source_result = closing.live_result(organization, batch_id=whole.pk)
    output_result = closing.live_result(organization, batch_id=output.pk)
    assert source_result.purchase_cost == D("800.000")
    assert output_result.purchase_cost == D("211.998")


def test_refusals(organization, room, whole):
    with pytest.raises(ValidationError) as refused:
        transform(organization, room, whole, output_quantity="11")
    assert "output_quantity" in refused.value.message_dict
    with pytest.raises(ValidationError) as refused:
        transform(organization, room, whole, fee="-1")
    assert "fee" in refused.value.message_dict
    with pytest.raises(ValidationError):
        transform(organization, room, whole, source_quantity="60", output_quantity="50")
    assert selectors.quantity_on_hand(organization, batch_id=whole.pk) == D("50.000")


def test_an_expired_lot_is_not_transformed(organization, room, whole):
    whole.use_by = timezone.localdate() - dt.timedelta(days=1)
    whole.save(update_fields=["use_by"])

    with pytest.raises(ValidationError) as refused:
        transform(organization, room, whole)
    assert "source_batch" in refused.value.message_dict
