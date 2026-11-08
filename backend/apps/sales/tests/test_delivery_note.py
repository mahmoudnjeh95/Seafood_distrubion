"""D-095: a validated sale is a delivery note numbered BL-<year>-<nnnn>, restarting every year."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory import services as stock
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import printing, services
from apps.sales.models import SaleStatus

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
    return StockLocationFactory.create(organization=organization, name="Chambre froide 1", counter_sales=True)


@pytest.fixture
def crevette(organization):
    product = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(
        product=product, price=Decimal("42.000"), valid_from=timezone.now() - dt.timedelta(days=30)
    )
    return product


def receive(organization, product, location, kg):
    batch = BatchFactory.create(organization=organization, product=product, unit_cost=Decimal("20.000"))
    stock.post_movement(
        organization=organization, actor=None, kind=MovementKind.RECEIPT, batch=batch, quantity=kg, to_location=location
    )


def sale(organization, actor, customer, location, lines):
    return services.create_sale(
        organization=organization, actor=actor, customer=customer, location=location, lines=lines
    )


def test_validating_numbers_the_sale_as_a_delivery_note(organization, actor, customer, counter, crevette):
    receive(organization, crevette, counter, "10")
    first = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])
    second = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])
    year = timezone.localdate().year
    # A draft BL has its provisional reference from its own yearly counter (D-283).
    assert first.number == f"VE-{year}-0001"

    # Validated in the other order: numbers follow validation, not creation.
    assert services.confirm_sale(sale=second, actor=actor).number == f"BL-{year}-0001"
    assert services.confirm_sale(sale=first, actor=actor).number == f"BL-{year}-0002"
    audit = AuditLog.objects.filter(action="sale.confirmed", target_id=str(first.pk)).get()
    assert audit.after is not None
    assert audit.after["draft_number"] == f"VE-{year}-0001"
    first.refresh_from_db()
    assert first.draft_number == f"VE-{year}-0001"


def test_the_numbering_restarts_every_year(organization, actor, customer, counter, crevette, monkeypatch):
    receive(organization, crevette, counter, "10")
    last_year = timezone.localdate().year - 1
    monkeypatch.setattr("apps.sales.services.timezone.localdate", lambda *args: dt.date(last_year, 12, 31))
    old = services.confirm_sale(
        sale=sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}]), actor=actor
    )
    monkeypatch.undo()
    new = services.confirm_sale(
        sale=sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}]), actor=actor
    )
    assert old.number == f"BL-{last_year}-0001"
    assert new.number == f"BL-{timezone.localdate().year}-0001"


def test_a_refused_validation_leaves_no_gap_in_the_numbers(organization, actor, customer, counter, crevette):
    receive(organization, crevette, counter, "2")
    too_much = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "5"}])
    ok = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])

    with pytest.raises(ValidationError):
        services.confirm_sale(sale=too_much, actor=actor)

    too_much.refresh_from_db()
    assert (too_much.number, too_much.status) == (f"VE-{timezone.localdate().year}-0001", SaleStatus.DRAFT)
    assert services.confirm_sale(sale=ok, actor=actor).number == f"BL-{timezone.localdate().year}-0001"


def test_only_a_validated_sale_has_a_delivery_note_pdf(organization, actor, customer, counter, crevette):
    receive(organization, crevette, counter, "10")
    draft = sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "2"}])

    with pytest.raises(ValidationError, match="validez-la"):
        printing.delivery_note_printable(organization, draft.pk)

    confirmed = services.confirm_sale(sale=draft, actor=actor)
    printable = printing.delivery_note_printable(organization, confirmed.pk)
    assert printable.context["number"] == confirmed.number
    assert printable.context["total_kg"] == Decimal("2.000")
    assert printable.filename == f"bl-{confirmed.number.lower()}.pdf"


# ---- D-283: draft prefix, BL to invoice per customer, opening balances apart from the BL ----


def test_a_draft_prefix_gives_drafts_their_own_counter(organization, actor, customer, counter, crevette):
    from apps.core import numbering
    from apps.core import services as core

    receive(organization, crevette, counter, "10")
    year = timezone.localdate().year
    core.set_number_prefixes(
        organization=organization,
        actor=actor,
        prefixes=[("delivery_note", "BL")],
        draft_prefixes={"delivery_note": "BBL"},
    )
    drafts = [sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}]) for _ in range(3)]
    assert [draft.number for draft in drafts] == [f"BBL-{year}-000{n}" for n in (1, 2, 3)]

    validated = services.confirm_sale(sale=drafts[2], actor=actor)

    # The definitive counter never moved for the drafts: BBL-…-0003 becomes BL-…-0001, and keeps its draft reference.
    assert (validated.number, validated.draft_number) == (f"BL-{year}-0001", f"BBL-{year}-0003")
    assert numbering.next_draft_preview(organization, "delivery_note") == f"BBL-{year}-0004"


def test_a_draft_prefix_may_not_repeat_another_prefix(organization, actor):
    from apps.core import services as core

    with pytest.raises(ValidationError) as caught:
        core.set_number_prefixes(
            organization=organization, actor=actor, prefixes=[("invoice", "FA")], draft_prefixes={"invoice": "BL"}
        )
    assert "prefixes.0.draft_prefix" in caught.value.message_dict
    with pytest.raises(ValidationError):
        core.set_number_prefixes(
            organization=organization, actor=actor, prefixes=[("customer", "C")], draft_prefixes={"customer": "BC"}
        )


def test_the_bl_to_invoice_are_counted_per_customer_without_the_opening_balances(
    organization, actor, customer, counter, crevette
):
    from apps.sales import selectors

    receive(organization, crevette, counter, "10")
    for _ in range(2):
        services.confirm_sale(
            sale=sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}]), actor=actor
        )
    sale(organization, actor, customer, counter, [{"product": crevette, "quantity": "1"}])  # a draft: not counted
    opening = services.create_opening_receivable(
        organization=organization, actor=actor, customer=customer, amount="500", owed_on=timezone.localdate()
    )

    assert selectors.uninvoiced_counts(organization) == {customer.pk: 2}
    # The opening balance is not a BL: left out of the BL list, alone in its own list.
    assert opening.pk not in set(selectors.sales_of(organization, opening="exclude").values_list("pk", flat=True))
    assert list(selectors.sales_of(organization, opening="only").values_list("pk", flat=True)) == [opening.pk]
