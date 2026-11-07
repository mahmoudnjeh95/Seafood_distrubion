"""D-289: a price request to several suppliers, their offers side by side, one purchase order per chosen supplier."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import services
from apps.purchasing.models import PriceRequestStatus, PurchaseOrder, SupplierOfferLine

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


@pytest.fixture
def organization(manager):
    return manager.organization


@pytest.fixture
def setup(organization):
    port = SupplierFactory.create(organization=organization, name="Mareyeur du port")
    farm = SupplierFactory.create(organization=organization, name="Ferme aquacole")
    dorade = ProductFactory.create(organization=organization, name="Dorade")
    loup = ProductFactory.create(organization=organization, name="Loup")
    return port, farm, dorade, loup


def ask(organization, manager, setup):
    port, farm, dorade, loup = setup
    return services.create_price_request(
        organization=organization,
        actor=manager.user,
        requested_on=TODAY(),
        lines=[{"product": dorade, "quantity": "100"}, {"product": loup, "quantity": "50"}],
        suppliers=[port, farm],
    )


def test_the_cheapest_offers_become_one_order_per_supplier(organization, manager, setup):
    port, farm, dorade, loup = setup
    request = ask(organization, manager, setup)
    assert request.number.startswith("DD-")
    first, second = request.lines.order_by("id")
    assert request.offers.count() == 2

    services.record_offer(
        request=request, actor=manager.user, supplier=port, prices={first.pk: "21.500", second.pk: "30.000"}
    )
    services.record_offer(
        request=request,
        actor=manager.user,
        supplier=farm,
        prices={first.pk: "22.000", second.pk: "27.000"},
        reference="DEV-77",
        valid_until=TODAY() + dt.timedelta(days=3),
    )
    orders = services.order_from_offers(
        request=request, actor=manager.user, choices={first.pk: port, second.pk: farm}, ordered_on=TODAY()
    )

    assert sorted((order.supplier.name, order.lines.get().unit_cost) for order in orders) == [
        ("Ferme aquacole", D("27.000")),
        ("Mareyeur du port", D("21.500")),
    ]
    farm_order = next(order for order in orders if order.supplier == farm)
    assert farm_order.lines.get().ordered_quantity == D("50.000")
    assert "DEV-77" in farm_order.notes
    request.refresh_from_db()
    assert request.status == PriceRequestStatus.ORDERED
    assert SupplierOfferLine.objects.filter(retained=True).count() == 2
    assert AuditLog.objects.filter(action="price_request.ordered").count() == 1
    with pytest.raises(ValidationError):
        services.record_offer(request=request, actor=manager.user, supplier=port, prices={})


def test_no_order_without_a_price_or_after_the_offer_expired(organization, manager, setup):
    port, farm, dorade, loup = setup
    request = ask(organization, manager, setup)
    first, second = request.lines.order_by("id")
    services.record_offer(
        request=request,
        actor=manager.user,
        supplier=port,
        prices={first.pk: "21.500", second.pk: None},
        received_on=TODAY() - dt.timedelta(days=5),
        valid_until=TODAY() - dt.timedelta(days=1),
    )

    with pytest.raises(ValidationError) as refused:
        services.order_from_offers(
            request=request, actor=manager.user, choices={first.pk: port, second.pk: port}, ordered_on=TODAY()
        )
    errors = refused.value.message_dict
    assert "n'est plus valable" in errors[f"choices.{first.pk}"][0]
    assert "pas donné de prix" in errors[f"choices.{second.pk}"][0]
    assert not PurchaseOrder.objects.exists()


def test_a_request_needs_suppliers_and_lines_and_can_be_cancelled(organization, manager, setup):
    port, farm, dorade, loup = setup
    with pytest.raises(ValidationError) as refused:
        services.create_price_request(
            organization=organization, actor=manager.user, requested_on=TODAY(), lines=[], suppliers=[]
        )
    assert {"suppliers", "lines"} <= set(refused.value.message_dict)

    request = ask(organization, manager, setup)
    services.cancel_price_request(request=request, actor=manager.user)
    request.refresh_from_db()
    assert request.status == PriceRequestStatus.CANCELLED


def test_the_office_compares_and_orders_through_the_api(manager, organization, setup):
    port, farm, dorade, loup = setup
    client = APIClient()
    client.force_authenticate(manager.user)
    created = client.post(
        reverse("price-request-list"),
        {
            "requested_on": TODAY().isoformat(),
            "suppliers": [port.pk],
            "lines": [{"product": dorade.pk, "quantity": "40"}],
        },
        format="json",
    )
    assert created.status_code == 201, created.json()
    body = created.json()
    line = body["lines"][0]["id"]

    # A supplier not asked at first answers anyway: added to the request.
    offered = client.post(
        reverse("price-request-offers", args=[body["id"]]),
        {"supplier": farm.pk, "prices": [{"request_line": line, "unit_cost": "19.900"}], "reference": "F-12"},
        format="json",
    )
    assert offered.status_code == 200, offered.json()
    assert [offer["supplier"]["id"] for offer in offered.json()["offers"]] == [port.pk, farm.pk]

    ordered = client.post(
        reverse("price-request-order", args=[body["id"]]),
        {"choices": [{"request_line": line, "supplier": farm.pk}], "ordered_on": TODAY().isoformat()},
        format="json",
    )
    assert ordered.status_code == 200, ordered.json()
    result = ordered.json()
    assert result["status"] == "ordered"
    farm_offer = next(offer for offer in result["offers"] if offer["supplier"]["id"] == farm.pk)
    assert farm_offer["order"]["number"].startswith("BA-")
    assert client.get(reverse("price-request-list"), {"search": "Dorade"}).json()["count"] == 1
