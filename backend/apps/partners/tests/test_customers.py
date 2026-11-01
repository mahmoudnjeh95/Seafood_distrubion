from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.core import services as core_services
from apps.core.models import AuditLog
from apps.core.tests.factories import OrganizationFactory, UserFactory
from apps.partners import selectors, services
from apps.partners.models import Customer

from .factories import CustomerContactFactory, CustomerFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


def new_customer(organization, actor, **fields):
    values: dict[str, Any] = {"name": "Restaurant Le Corail"}
    values.update(fields)
    return services.create_customer(organization=organization, actor=actor, **values)


def test_a_customer_without_reference_gets_the_next_c_number(organization, actor):
    CustomerFactory.create(organization=organization, reference="C-007")
    CustomerFactory.create(organization=organization, reference="RESTO-12")
    CustomerFactory.create(reference="C-050")  # another company

    assert new_customer(organization, actor).reference == "C-008"
    assert new_customer(organization, actor, name="Hôtel Thyna").reference == "C-009"


def test_creating_stores_the_money_the_contacts_and_audits(organization, actor):
    customer = new_customer(
        organization,
        actor,
        kind="hotel",
        tax_id="0000102b/a/m/000",
        credit_limit=Decimal("5000"),
        payment_terms_days=45,
        contacts=[{"name": " Sonia ", "role": "Économat"}],
    )

    customer.refresh_from_db()
    assert (customer.kind, customer.tax_id, customer.payment_terms_days) == ("hotel", "0000102B/A/M/000", 45)
    assert customer.credit_limit == Decimal("5000.000")
    assert customer.contacts.get().name == "Sonia"
    entry = AuditLog.objects.get(action="customer.created")
    assert entry.actor == actor
    assert entry.after is not None
    assert entry.after["credit_limit"] == "5000.000"


def test_default_is_no_credit_and_payment_on_delivery(organization, actor):
    customer = new_customer(organization, actor)

    assert (customer.credit_limit, customer.payment_terms_days, customer.is_walk_in) == (0, 0, False)


def test_errors_come_one_per_field(organization, actor):
    CustomerFactory.create(organization=organization, reference="C-001", tax_id="0000001A/A/M/000")

    with pytest.raises(ValidationError) as caught:
        new_customer(
            organization,
            actor,
            reference="c-001",
            name=" ",
            kind="martian",
            tax_id="0000001A/A/M/000",
            email="not-mail",
            credit_limit=Decimal("-1"),
            payment_terms_days=400,
        )

    assert set(caught.value.message_dict) == {
        "reference",
        "name",
        "kind",
        "tax_id",
        "email",
        "credit_limit",
        "payment_terms_days",
    }


def test_a_credit_limit_has_at_most_three_decimals(organization, actor):
    with pytest.raises(ValidationError) as caught:
        new_customer(organization, actor, credit_limit=Decimal("10.0005"))

    assert list(caught.value.message_dict) == ["credit_limit"]


def test_references_and_tax_ids_may_repeat_in_another_organization(organization, actor):
    CustomerFactory.create(reference="C-001", tax_id="0000001A/A/M/000")

    customer = new_customer(organization, actor, reference="C-001", tax_id="0000001A/A/M/000")

    assert customer.pk is not None


def test_update_audits_only_what_changed_and_the_limit_is_a_decimal(organization, actor):
    customer = new_customer(organization, actor, credit_limit=Decimal("1000"))

    services.update_customer(customer=customer, actor=actor, credit_limit=Decimal("1500.5"))

    customer.refresh_from_db()
    assert customer.credit_limit == Decimal("1500.500")
    entry = AuditLog.objects.get(action="customer.updated")
    assert (entry.before, entry.after) == ({"credit_limit": "1000.000"}, {"credit_limit": "1500.500"})


def test_contacts_are_replaced_only_when_sent(organization, actor):
    customer = new_customer(organization, actor, contacts=[{"name": "Sonia"}, {"name": "Ali"}])

    services.update_customer(customer=customer, actor=actor, city="Sfax")
    assert customer.contacts.count() == 2

    services.update_customer(customer=customer, actor=actor, contacts=[{"name": "Ali"}])
    assert list(customer.contacts.values_list("name", flat=True)) == ["Ali"]


def test_a_refused_update_changes_nothing(organization, actor):
    customer = new_customer(organization, actor, contacts=[{"name": "Sonia"}])

    with pytest.raises(ValidationError):
        services.update_customer(customer=customer, actor=actor, name="Autre", contacts=[{"name": ""}])

    customer.refresh_from_db()
    assert customer.name == "Restaurant Le Corail"
    assert customer.contacts.count() == 1


def test_archiving_and_restoring_are_audited_once(organization, actor):
    customer = new_customer(organization, actor)

    services.set_customer_active(customer=customer, actor=actor, is_active=False)
    services.set_customer_active(customer=customer, actor=actor, is_active=False)
    services.set_customer_active(customer=customer, actor=actor, is_active=True)

    actions = AuditLog.objects.filter(target_id=str(customer.pk)).order_by("id").values_list("action", flat=True)
    assert list(actions) == ["customer.created", "customer.archived", "customer.restored"]


# ---- walk-in customer ----


def test_the_walk_in_customer_is_created_once_and_pays_at_once(organization, actor):
    first = services.ensure_walk_in_customer(organization=organization, actor=actor)
    again = services.ensure_walk_in_customer(organization=organization)

    assert first.pk == again.pk
    assert (first.is_walk_in, first.kind, first.credit_limit, first.name) == (
        True,
        "individual",
        Decimal("0"),
        "Client de passage",
    )
    assert Customer.objects.filter(organization=organization, is_walk_in=True).count() == 1


def test_the_walk_in_customer_cannot_be_archived_or_given_credit(organization, actor):
    walk_in = services.ensure_walk_in_customer(organization=organization, actor=actor)

    with pytest.raises(ValidationError):
        services.set_customer_active(customer=walk_in, actor=actor, is_active=False)
    with pytest.raises(ValidationError) as caught:
        services.update_customer(customer=walk_in, actor=actor, credit_limit=Decimal("100"))

    assert list(caught.value.message_dict) == ["credit_limit"]
    walk_in.refresh_from_db()
    assert walk_in.is_active is True


def test_the_database_allows_one_walk_in_customer_per_organization(organization):
    CustomerFactory.create(organization=organization, is_walk_in=True)

    with pytest.raises(IntegrityError), transaction.atomic():
        CustomerFactory.create(organization=organization, is_walk_in=True)


# ---- reading ----


def test_search_finds_a_customer_once_by_name_city_or_contact(organization):
    corail = CustomerFactory.create(organization=organization, name="Restaurant Le Corail", city="Sfax")
    CustomerContactFactory.create(customer=corail, name="Karim Ben Ali")
    CustomerContactFactory.create(customer=corail, name="Karima")
    CustomerFactory.create(organization=organization, name="Hôtel Thyna", city="Thyna")

    assert list(selectors.customers_of(organization, search="karim")) == [corail]
    assert list(selectors.customers_of(organization, search="SFAX")) == [corail]
    assert selectors.customers_of(organization).count() == 2


def test_status_and_kind_filters_and_the_walk_in_customer_comes_last(organization):
    walk_in = CustomerFactory.create(organization=organization, name="Abdou", is_walk_in=True, kind="individual")
    hotel = CustomerFactory.create(organization=organization, name="Hôtel Thyna", kind="hotel")
    archived = CustomerFactory.create(organization=organization, name="Zeta", is_active=False)

    assert list(selectors.customers_of(organization)) == [hotel, walk_in]
    assert list(selectors.customers_of(organization, status="archived")) == [archived]
    assert list(selectors.customers_of(organization, kind="hotel")) == [hotel]


def test_a_new_prefix_for_customers_goes_on_from_the_counter(organization, actor):
    new_customer(organization, actor)  # C-001

    core_services.set_number_prefixes(organization=organization, actor=actor, prefixes=[("customer", "CL")])

    assert new_customer(organization, actor, name="Hôtel Thyna").reference == "CL-002"
