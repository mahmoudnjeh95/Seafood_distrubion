import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory, ProductPriceFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import CustomerFactory
from apps.sales.models import Quote, QuoteStatus

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def api(manager):
    return client_for(manager)


@pytest.fixture
def customer(organization):
    return CustomerFactory.create(organization=organization, name="Restaurant Le Corail", city="Sfax")


@pytest.fixture
def crevette(organization):
    product = ProductFactory.create(organization=organization, name="Crevette Royale", reference="CR-001")
    ProductPriceFactory.create(
        product=product, price=Decimal("42.000"), valid_from=timezone.now() - dt.timedelta(days=30)
    )
    return product


def payload(customer, lines, **fields):
    body = {"customer": customer.pk, "quoted_on": timezone.localdate().isoformat(), "lines": lines}
    body.update(fields)
    return body


def create(api, customer, lines, **fields):
    return api.post(reverse("quote-list"), payload(customer, lines, **fields), format="json")


def test_creating_a_quote_answers_it_with_amounts_as_strings(api, customer, crevette, organization):
    room = StockLocationFactory.create(organization=organization, name="Chambre froide 1")

    response = create(
        api,
        customer,
        [{"product": crevette.pk, "quantity": "5", "discount_rate": "10"}],
        location=room.pk,
        notes="Merci",
    )

    assert response.status_code == 201
    body = response.json()
    assert (body["number"], body["status"], body["notes"]) == (f"DV-{YEAR}-0001", "draft", "Merci")
    assert body["customer"]["name"] == "Restaurant Le Corail"
    assert body["location"] == {"id": room.pk, "name": "Chambre froide 1"}
    assert body["valid_until"] == (timezone.localdate() + dt.timedelta(days=3)).isoformat()
    assert body["lines"] == [
        {
            "id": body["lines"][0]["id"],
            "product": {"id": crevette.pk, "reference": "CR-001", "name": "Crevette Royale"},
            "quantity": "5.000",
            "unit_price": "42.000",
            "discount_rate": "10.00",
            "gross_amount": "210.000",
            "discount_amount": "21.000",
            "amount": "189.000",
            "requested_batch": None,
            "delivered_quantity": "0.000",
            "remaining_quantity": "5.000",
        }
    ]
    assert (body["subtotal"], body["discount_total"], body["total_excl_tax"], body["tax_amount"], body["total"]) == (
        "210.000",
        "21.000",
        "189.000",
        None,
        "189.000",
    )
    assert body["line_count"] == 1


def test_line_errors_come_back_on_their_own_keys(api, customer, crevette):
    response = create(
        api,
        customer,
        [
            {"product": crevette.pk, "quantity": "abc"},
            {"product": 999999, "quantity": "1"},
            {"product": crevette.pk, "quantity": "1", "unit_price": "0"},
        ],
    )

    assert response.status_code == 400
    assert set(response.json()) == {"lines.1.product"}
    # Known products are then checked by the service.
    response = create(
        api, customer, [{"product": crevette.pk, "quantity": "abc"}, {"product": crevette.pk, "quantity": "1"}]
    )
    assert set(response.json()) == {"lines.0.quantity", "lines.1.product"}


def test_the_whole_life_of_a_quote_through_the_api(api, customer, crevette):
    quote_id = create(api, customer, [{"product": crevette.pk, "quantity": "5"}]).json()["id"]

    changed = api.put(
        reverse("quote-detail", args=[quote_id]),
        payload(customer, [{"product": crevette.pk, "quantity": "6", "unit_price": "40"}]),
        format="json",
    )
    assert changed.status_code == 200
    assert changed.json()["total"] == "240.000"

    sent = api.post(reverse("quote-send", args=[quote_id]))
    assert (sent.status_code, sent.json()["status"]) == (200, "sent")
    assert sent.json()["sent_by"] != ""

    frozen = api.put(
        reverse("quote-detail", args=[quote_id]),
        payload(customer, [{"product": crevette.pk, "quantity": "1"}]),
        format="json",
    )
    assert frozen.status_code == 400

    accepted = api.post(reverse("quote-accept", args=[quote_id]))
    assert (accepted.status_code, accepted.json()["status"]) == (200, "accepted")
    assert api.post(reverse("quote-refuse", args=[quote_id]), {}, format="json").status_code == 400


def test_save_and_send_at_once_and_refuse_with_a_reason(api, customer, crevette):
    quote_id = create(api, customer, [{"product": crevette.pk, "quantity": "5"}], send_now=True).json()["id"]

    refused = api.post(reverse("quote-refuse", args=[quote_id]), {"reason": "Trop cher"}, format="json")

    assert refused.json()["status"] == "refused"
    assert refused.json()["refusal_reason"] == "Trop cher"


def test_the_list_filters_by_current_status_customer_and_search(api, customer, crevette, organization):
    hotel = CustomerFactory.create(organization=organization, name="Hôtel Thyna")
    create(api, customer, [{"product": crevette.pk, "quantity": "5"}])
    sent = create(api, hotel, [{"product": crevette.pk, "quantity": "5"}], send_now=True).json()
    old = create(
        api,
        hotel,
        [{"product": crevette.pk, "quantity": "5"}],
        quoted_on=(timezone.localdate() - dt.timedelta(days=9)).isoformat(),
        valid_until=(timezone.localdate() - dt.timedelta(days=2)).isoformat(),
    ).json()
    Quote.objects.filter(pk=old["id"]).update(status=QuoteStatus.SENT)

    def numbers(**params):
        response = api.get(reverse("quote-list"), params)
        assert response.status_code == 200
        return [row["number"] for row in response.json()["results"]]

    assert numbers() == [f"DV-{YEAR}-0002", f"DV-{YEAR}-0001", f"DV-{YEAR}-0003"]
    assert numbers(status="sent") == [sent["number"]]
    assert numbers(status="expired") == [old["number"]]
    assert numbers(customer=customer.pk) == [f"DV-{YEAR}-0001"]
    assert numbers(search="thyna") == [f"DV-{YEAR}-0002", f"DV-{YEAR}-0003"]
    assert numbers(date_to=(timezone.localdate() - dt.timedelta(days=1)).isoformat()) == [f"DV-{YEAR}-0003"]


@pytest.mark.parametrize(
    ("role", "read", "write"),
    [
        (Role.OWNER, 200, 201),
        (Role.MANAGER, 200, 201),
        (Role.ACCOUNTANT, 200, 403),
        (Role.DRIVER, 403, 403),
    ],
)
def test_quotes_are_office_documents(role, read, write):
    membership = MembershipFactory.create(role=role)
    organization = membership.organization
    customer = CustomerFactory.create(organization=organization)
    product = ProductFactory.create(organization=organization)
    ProductPriceFactory.create(product=product)
    client = client_for(membership)

    assert client.get(reverse("quote-list")).status_code == read
    assert create(client, customer, [{"product": product.pk, "quantity": "1"}]).status_code == write


def test_the_accountant_cannot_answer_a_quote(organization, customer, crevette, api):
    quote_id = create(api, customer, [{"product": crevette.pk, "quantity": "5"}], send_now=True).json()["id"]
    accountant = client_for(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT))

    assert accountant.get(reverse("quote-detail", args=[quote_id])).status_code == 200
    assert accountant.post(reverse("quote-accept", args=[quote_id])).status_code == 403


def test_anonymous_visitors_get_401():
    assert APIClient().get(reverse("quote-list")).status_code == 401


def test_another_organizations_quotes_and_customers_are_not_found(api, customer, crevette):
    other = OrganizationFactory.create()
    stranger = CustomerFactory.create(organization=other)
    foreign = MembershipFactory.create(organization=other, role=Role.OWNER)
    other_product = ProductFactory.create(organization=other)
    ProductPriceFactory.create(product=other_product)
    foreign_id = create(client_for(foreign), stranger, [{"product": other_product.pk, "quantity": "1"}]).json()["id"]

    assert api.get(reverse("quote-detail", args=[foreign_id])).status_code == 404
    assert api.post(reverse("quote-send", args=[foreign_id])).status_code == 404
    assert create(api, stranger, [{"product": crevette.pk, "quantity": "1"}]).json() == {
        "customer": ["Client inconnu."]
    }


def test_a_manager_may_quote_under_the_minimum_with_a_reason(api, customer, crevette):
    crevette.min_price = Decimal("40.000")
    crevette.save()
    lines = [{"product": crevette.pk, "quantity": "5", "unit_price": "42.000", "discount_rate": "10.00"}]

    refused = create(api, customer, lines)
    approved = create(api, customer, lines, below_minimum_reason="Offre de lancement")

    assert refused.status_code == 400
    assert "lines.0.discount_rate" in refused.json()
    assert approved.status_code == 201
