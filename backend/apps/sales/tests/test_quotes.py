import datetime as dt
import threading
import uuid
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import connection
from django.utils import timezone

from apps.catalog import services as catalog
from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales import selectors, services
from apps.sales.models import Quote, QuoteStatus

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year

TODAY = timezone.localdate


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


def quote(organization, actor, customer, lines, **fields):
    values: dict[str, Any] = {"quoted_on": timezone.localdate()}
    values.update(fields)
    return services.create_quote(organization=organization, actor=actor, customer=customer, lines=lines, **values)


def errors_of(refused: pytest.ExceptionInfo[ValidationError]) -> dict[str, list[str]]:
    return refused.value.message_dict


# ---- drafts and prices ----


def test_a_new_quote_is_a_numbered_draft_priced_at_the_price_in_force(organization, actor, customer, crevette, calamar):
    first = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}])
    second = quote(
        organization, actor, customer, [{"product": crevette, "quantity": "5"}, {"product": calamar, "quantity": "3"}]
    )

    assert (first.number, first.status, first.created_by) == (f"DV-{YEAR}-0001", QuoteStatus.DRAFT, actor)
    assert second.number == f"DV-{YEAR}-0002"
    assert [(line.unit_price, line.amount) for line in second.lines.order_by("id")] == [
        (Decimal("42.000"), Decimal("210.000")),
        (Decimal("29.000"), Decimal("87.000")),
    ]
    assert (second.subtotal, second.discount_total, second.total_excl_tax, second.total) == (
        Decimal("297.000"),
        Decimal("0.000"),
        Decimal("297.000"),
        Decimal("297.000"),
    )
    # VAT waits for the finance settings (P2-T05).
    assert second.tax_amount is None
    assert AuditLog.objects.filter(action="quote.created", target_id=str(second.pk)).exists()


def test_numbers_are_per_organization(organization, actor, customer, crevette):
    other = OrganizationFactory.create()
    other_product = ProductFactory.create(organization=other)
    ProductPriceFactory.create(product=other_product)

    quote(organization, actor, customer, [{"product": crevette, "quantity": "1"}])
    elsewhere = quote(
        other, actor, CustomerFactory.create(organization=other), [{"product": other_product, "quantity": "1"}]
    )

    assert elsewhere.number == f"DV-{YEAR}-0001"


def test_a_typed_price_and_a_discount_are_kept_and_rounded_once_per_line(organization, actor, customer, crevette):
    draft = quote(
        organization,
        actor,
        customer,
        [{"product": crevette, "quantity": "2.335", "unit_price": "40.500", "discount_rate": "7.5"}],
    )

    line = draft.lines.get()
    # 2.335 × 40.500 = 94.5675 → 94.568; 7.5 % of it = 7.0926 → 7.093; 94.568 − 7.093 = 87.475
    assert (line.unit_price, line.discount_rate) == (Decimal("40.500"), Decimal("7.50"))
    assert (line.gross_amount, line.discount_amount, line.amount) == (
        Decimal("94.568"),
        Decimal("7.093"),
        Decimal("87.475"),
    )
    assert (draft.subtotal, draft.discount_total, draft.total) == (
        Decimal("94.568"),
        Decimal("7.093"),
        Decimal("87.475"),
    )


def test_the_customers_price_list_wins_over_the_daily_price(organization, actor, customer, crevette, calamar):
    catalog.create_price_list(
        organization=organization,
        actor=actor,
        name="Le Corail",
        customer_id=customer.pk,
        items=[{"product": crevette, "price": Decimal("39.500")}],
    )
    other = CustomerFactory.create(organization=organization)
    lines = [{"product": crevette, "quantity": "2"}, {"product": calamar, "quantity": "1"}]

    own = quote(organization, actor, customer, lines)
    elsewhere = quote(organization, actor, other, lines)

    # The list holds the shrimp only: the squid stays at the daily price.
    assert [line.unit_price for line in own.lines.order_by("id")] == [Decimal("39.500"), Decimal("29.000")]
    assert [line.unit_price for line in elsewhere.lines.order_by("id")] == [Decimal("42.000"), Decimal("29.000")]


def test_a_quote_dated_earlier_takes_the_price_in_force_that_day(organization, actor, customer):
    loup = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=loup, price=Decimal("25.000"), valid_from=timezone.now() - dt.timedelta(days=10))
    ProductPriceFactory.create(product=loup, price=Decimal("27.000"), valid_from=timezone.now() - dt.timedelta(hours=1))
    # A price planned for later is never used.
    ProductPriceFactory.create(product=loup, price=Decimal("99.000"), valid_from=timezone.now() + dt.timedelta(days=1))

    today = quote(organization, actor, customer, [{"product": loup, "quantity": "1"}])
    last_week = quote(
        organization, actor, customer, [{"product": loup, "quantity": "1"}], quoted_on=TODAY() - dt.timedelta(days=5)
    )

    assert today.lines.get().unit_price == Decimal("27.000")
    assert last_week.lines.get().unit_price == Decimal("25.000")


def test_the_line_keeps_its_price_when_the_catalogue_price_changes(organization, actor, customer, crevette):
    draft = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}])
    services.send_quote(quote=draft, actor=actor)

    ProductPriceFactory.create(product=crevette, price=Decimal("45.000"))

    line = selectors.quote_of(organization, draft.pk).lines.get()
    assert (line.unit_price, line.amount) == (Decimal("42.000"), Decimal("210.000"))


def test_validity_defaults_to_three_days_and_cannot_precede_the_quote(organization, actor, customer, crevette):
    line = [{"product": crevette, "quantity": "1"}]

    assert quote(organization, actor, customer, line).valid_until == TODAY() + dt.timedelta(days=3)
    with pytest.raises(ValidationError) as refused:
        quote(organization, actor, customer, line, valid_until=TODAY() - dt.timedelta(days=1))
    assert "valid_until" in errors_of(refused)


def test_every_problem_comes_back_at_once_on_its_own_field(organization, actor, customer, crevette):
    unpriced = ProductFactory.create(organization=organization)
    archived = ProductFactory.create(organization=organization, is_active=False)
    customer.is_active = False
    customer.save()
    other_room = StockLocationFactory.create(organization=OrganizationFactory.create())

    with pytest.raises(ValidationError) as refused:
        quote(
            organization,
            actor,
            customer,
            [
                {"product": crevette, "quantity": "0"},
                {"product": unpriced, "quantity": "1"},
                {"product": crevette, "quantity": "1", "discount_rate": "101"},
                {"product": archived, "quantity": "1"},
                {"product": ProductFactory.create(organization=organization), "quantity": "1", "unit_price": "-2"},
                {
                    "product": ProductFactory.create(organization=organization),
                    "quantity": "1.2345",
                    "unit_price": "10",
                    "discount_rate": "2.555",
                },
            ],
            location=other_room,
            quoted_on=TODAY() + dt.timedelta(days=1),
        )

    errors = errors_of(refused)
    assert set(errors) == {
        "customer",
        "location",
        "quoted_on",
        "lines.0.quantity",
        "lines.1.unit_price",
        "lines.2.product",
        "lines.2.discount_rate",
        "lines.3.product",
        "lines.4.unit_price",
        "lines.5.quantity",
        "lines.5.discount_rate",
    }
    assert errors["lines.2.product"] == ["Ce produit est déjà sur une autre ligne."]
    assert not Quote.objects.exists()


def test_a_quote_needs_a_line(organization, actor, customer):
    with pytest.raises(ValidationError) as refused:
        quote(organization, actor, customer, [])
    assert errors_of(refused) == {"lines": ["Ajoutez au moins un produit."]}


def test_a_draft_changes_as_a_whole_and_keeps_its_number(organization, actor, customer, crevette, calamar):
    room = StockLocationFactory.create(organization=organization)
    draft = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}])
    hotel = CustomerFactory.create(organization=organization)

    changed = services.update_quote(
        quote=draft,
        actor=actor,
        customer=hotel,
        location=room,
        quoted_on=TODAY(),
        valid_until=TODAY() + dt.timedelta(days=7),
        lines=[{"product": calamar, "quantity": "10", "discount_rate": "10"}],
        notes="  Livraison mardi ",
    )

    assert (changed.number, changed.customer, changed.location, changed.notes) == (
        f"DV-{YEAR}-0001",
        hotel,
        room,
        "Livraison mardi",
    )
    assert [(line.product_id, line.amount) for line in changed.lines.all()] == [(calamar.pk, Decimal("261.000"))]
    assert changed.total == Decimal("261.000")
    entry = AuditLog.objects.get(action="quote.updated")
    assert entry.before is not None
    assert entry.before["lines"][0]["product"] == "CR-001"


# ---- answers ----


def test_a_quote_is_sent_then_accepted_and_no_longer_changes(organization, actor, customer, crevette):
    draft = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}])

    sent = services.send_quote(quote=draft, actor=actor)
    assert (sent.status, sent.sent_by) == (QuoteStatus.SENT, actor)
    with pytest.raises(ValidationError, match="envoyé : il ne se modifie plus"):
        services.update_quote(
            quote=sent,
            actor=actor,
            customer=customer,
            quoted_on=TODAY(),
            lines=[{"product": crevette, "quantity": "1"}],
        )

    accepted = services.accept_quote(quote=sent, actor=actor)
    assert (accepted.status, accepted.answered_by) == (QuoteStatus.ACCEPTED, actor)
    assert accepted.answered_at is not None
    with pytest.raises(ValidationError, match="déjà accepté"):
        services.refuse_quote(quote=accepted, actor=actor)
    assert list(AuditLog.objects.filter(target_id=str(draft.pk)).order_by("id").values_list("action", flat=True)) == [
        "quote.created",
        "quote.sent",
        "quote.accepted",
    ]


def test_a_draft_must_be_sent_before_an_answer(organization, actor, customer, crevette):
    draft = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}])

    with pytest.raises(ValidationError, match="Envoyez d'abord"):
        services.accept_quote(quote=draft, actor=actor)


def test_create_and_send_in_one_go(organization, actor, customer, crevette):
    sent = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}], send=True)

    assert sent.status == QuoteStatus.SENT


def test_a_refusal_keeps_its_reason(organization, actor, customer, crevette):
    sent = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}], send=True)

    refused = services.refuse_quote(quote=sent, actor=actor, reason="  Trop cher ")

    assert (refused.status, refused.refusal_reason) == (QuoteStatus.REFUSED, "Trop cher")


# ---- validity ----


def test_a_sent_quote_past_its_validity_shows_expired_and_cannot_be_accepted(organization, actor, customer, crevette):
    old = quote(
        organization,
        actor,
        customer,
        [{"product": crevette, "quantity": "5"}],
        quoted_on=TODAY() - dt.timedelta(days=5),
        valid_until=TODAY() - dt.timedelta(days=1),
    )
    # Sent while still valid.
    Quote.objects.filter(pk=old.pk).update(status=QuoteStatus.SENT)
    still_valid = quote(organization, actor, customer, [{"product": crevette, "quantity": "1"}], send=True)

    shown = {q.number: q.current_status for q in selectors.quotes_of(organization)}  # type: ignore[attr-defined]
    assert shown == {old.number: QuoteStatus.EXPIRED, still_valid.number: QuoteStatus.SENT}
    assert [q.number for q in selectors.quotes_of(organization, status=QuoteStatus.EXPIRED)] == [old.number]
    with pytest.raises(ValidationError) as refused:
        services.accept_quote(quote=old, actor=actor)
    assert "valid_until" in errors_of(refused)
    # The customer's no is still worth recording.
    assert services.refuse_quote(quote=old, actor=actor).status == QuoteStatus.REFUSED


def test_the_last_valid_day_is_included(organization, actor, customer, crevette):
    sent = quote(
        organization, actor, customer, [{"product": crevette, "quantity": "5"}], valid_until=TODAY(), send=True
    )

    assert services.accept_quote(quote=sent, actor=actor).status == QuoteStatus.ACCEPTED


def test_a_draft_past_its_validity_cannot_be_sent(organization, actor, customer, crevette):
    draft = quote(
        organization,
        actor,
        customer,
        [{"product": crevette, "quantity": "5"}],
        quoted_on=TODAY() - dt.timedelta(days=4),
        valid_until=TODAY() - dt.timedelta(days=1),
    )

    with pytest.raises(ValidationError) as refused:
        services.send_quote(quote=draft, actor=actor)
    assert "valid_until" in errors_of(refused)
    # A draft never shows as expired: its dates can still be changed.
    assert selectors.quotes_of(organization).get().current_status == QuoteStatus.DRAFT  # type: ignore[attr-defined]


def test_the_nightly_job_writes_the_expiry_down(organization, actor, customer, crevette):
    sent = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}], send=True)
    accepted = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}], send=True)
    services.accept_quote(quote=accepted, actor=actor)

    assert services.expire_quotes(organization=organization, today=TODAY()) == 0
    assert services.expire_quotes(organization=organization, today=sent.valid_until + dt.timedelta(days=1)) == 1

    sent.refresh_from_db()
    accepted.refresh_from_db()
    assert (sent.status, accepted.status) == (QuoteStatus.EXPIRED, QuoteStatus.ACCEPTED)
    assert sent.expired_at is not None
    assert AuditLog.objects.filter(action="quote.expired", target_id=str(sent.pk)).exists()


def test_the_expire_command_runs_for_every_organization(organization, actor, customer, crevette, capsys):
    sent = quote(
        organization,
        actor,
        customer,
        [{"product": crevette, "quantity": "5"}],
        quoted_on=TODAY() - dt.timedelta(days=5),
        valid_until=TODAY() - dt.timedelta(days=2),
    )
    Quote.objects.filter(pk=sent.pk).update(status=QuoteStatus.SENT)

    call_command("expire_quotes")

    sent.refresh_from_db()
    assert sent.status == QuoteStatus.EXPIRED
    assert "1 quote(s) expired." in capsys.readouterr().out


def test_a_client_uuid_already_used_returns_the_same_quote(organization, actor, customer, crevette):
    key = uuid.uuid4()
    first = quote(organization, actor, customer, [{"product": crevette, "quantity": "5"}], client_uuid=key)
    again = quote(organization, actor, customer, [{"product": crevette, "quantity": "9"}], client_uuid=key)

    assert again.pk == first.pk
    assert Quote.objects.count() == 1


# ---- numbering under load ----


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_quotes_saved_at_once_never_share_a_number():
    organization = OrganizationFactory.create()
    customer = CustomerFactory.create(organization=organization)
    crevette = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=crevette, valid_from=timezone.now() - dt.timedelta(days=1))
    numbers: list[str] = []
    failures: list[BaseException] = []

    def make() -> None:
        try:
            numbers.append(quote(organization, None, customer, [{"product": crevette, "quantity": "1"}]).number)
        except BaseException as error:  # noqa: BLE001 - reported below
            failures.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=make) for _ in range(4)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert failures == []
    assert sorted(numbers) == [f"DV-{YEAR}-0001", f"DV-{YEAR}-0002", f"DV-{YEAR}-0003", f"DV-{YEAR}-0004"]


def test_a_quote_line_under_the_minimum_is_refused_unless_a_reason_is_given(organization, actor, customer, crevette):
    crevette.min_price = Decimal("40.000")
    crevette.save()
    lines = [{"product": crevette, "quantity": "5", "unit_price": "42.000", "discount_rate": "10.00"}]

    with pytest.raises(ValidationError) as refused:
        quote(organization, actor, customer, lines)
    approved = quote(organization, actor, customer, lines, below_minimum_reason="Offre de lancement")

    assert "lines.0.discount_rate" in errors_of(refused)
    assert approved.total == Decimal("189.000")
    trail = AuditLog.objects.get(action="quote.price_below_minimum_approved", target_id=str(approved.pk))
    assert trail.after is not None
    assert trail.after["reason"] == "Offre de lancement"
