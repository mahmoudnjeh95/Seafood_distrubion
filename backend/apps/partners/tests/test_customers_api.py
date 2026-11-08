import pytest
from django.urls import reverse
from rest_framework.test import APIClient

from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory

from .factories import CustomerContactFactory, CustomerFactory

pytestmark = pytest.mark.django_db


@pytest.fixture
def manager():
    return MembershipFactory.create(role=Role.MANAGER)


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def api(manager):
    return client_for(manager)


def create(api, **fields):
    payload = {"name": "Restaurant Le Corail"}
    payload.update(fields)
    return api.post(reverse("customer-list"), payload, format="json")


def test_creating_a_customer_answers_it_with_money_as_strings(api):
    response = create(
        api,
        kind="hotel",
        credit_limit="5000",
        payment_terms_days=45,
        tax_id="0000102b/a/m/000",
        contacts=[{"name": "Sonia", "phone": "+216 98 000 001"}],
    )

    assert response.status_code == 201
    body = response.json()
    assert body["reference"] == "C-001"
    assert (body["kind"], body["credit_limit"], body["payment_terms_days"]) == ("hotel", "5000.000", 45)
    assert body["tax_id"] == "0000102B/A/M/000"
    assert body["contacts"] == [{"name": "Sonia", "role": "", "phone": "+216 98 000 001", "email": ""}]
    assert (body["is_active"], body["is_walk_in"]) == (True, False)


def test_a_customer_withholds_by_default_and_the_flag_can_be_turned_off(api):
    """D-292: "Soumis à la retenue à la source" starts on, as before; the office turns it off for a customer
    who does not withhold."""
    created = create(api)
    assert created.json()["withholding_subject"] is True

    url = reverse("customer-detail", args=[created.json()["id"]])
    changed = api.patch(url, {"withholding_subject": False}, format="json")
    assert changed.status_code == 200, changed.json()
    assert changed.json()["withholding_subject"] is False


def test_a_negative_limit_or_unknown_kind_is_a_400_on_its_field(api):
    assert list(create(api, credit_limit="-5").json()) == ["credit_limit"]
    assert list(create(api, kind="martian").json()) == ["kind"]
    assert list(create(api, tax_id="12AB").json()) == ["tax_id"]


@pytest.mark.parametrize(
    ("role", "read_status", "write_status"),
    [
        (Role.OWNER, 200, 201),
        (Role.MANAGER, 200, 201),
        (Role.ACCOUNTANT, 200, 403),
        (Role.DRIVER, 403, 403),
    ],
)
def test_drivers_never_see_customers_and_accountants_only_read(role, read_status, write_status):
    client = client_for(MembershipFactory.create(role=role))

    assert client.get(reverse("customer-list")).status_code == read_status
    assert create(client).status_code == write_status


def test_a_driver_cannot_read_one_customer_or_archive_it():
    customer = CustomerFactory.create()
    client = client_for(MembershipFactory.create(role=Role.DRIVER, organization=customer.organization))

    assert client.get(reverse("customer-detail", args=[customer.pk])).status_code == 403
    assert client.post(reverse("customer-archive", args=[customer.pk])).status_code == 403


def test_anonymous_visitors_get_401():
    assert APIClient().get(reverse("customer-list")).status_code == 401


def test_another_organization_customers_are_invisible(api):
    other = CustomerFactory.create()

    assert api.get(reverse("customer-list")).json() == []
    assert api.get(reverse("customer-detail", args=[other.pk])).status_code == 404
    assert api.patch(reverse("customer-detail", args=[other.pk]), {"name": "X"}, format="json").status_code == 404
    assert api.post(reverse("customer-archive", args=[other.pk])).status_code == 404


def test_the_list_filters_by_search_status_and_kind(api, manager):
    corail = CustomerFactory.create(organization=manager.organization, name="Restaurant Le Corail")
    CustomerContactFactory.create(customer=corail, name="Sonia")
    CustomerFactory.create(organization=manager.organization, name="Hôtel Thyna", kind="hotel", is_active=False)

    def names(**params):
        return [row["name"] for row in api.get(reverse("customer-list"), params).json()]

    assert names() == ["Restaurant Le Corail"]
    assert names(status="all") == ["Hôtel Thyna", "Restaurant Le Corail"]
    assert names(status="archived") == ["Hôtel Thyna"]
    assert names(status="all", kind="hotel") == ["Hôtel Thyna"]
    assert names(search="sonia") == ["Restaurant Le Corail"]
    assert api.get(reverse("customer-list"), {"kind": "gone"}).status_code == 400


def test_a_partial_update_keeps_the_other_fields_and_the_contacts(api):
    customer_id = create(api, city="Sfax", credit_limit="1000", contacts=[{"name": "Sonia"}]).json()["id"]

    response = api.patch(reverse("customer-detail", args=[customer_id]), {"credit_limit": "2500.500"}, format="json")

    assert response.status_code == 200
    body = response.json()
    assert (body["name"], body["city"], body["credit_limit"]) == ("Restaurant Le Corail", "Sfax", "2500.500")
    assert [contact["name"] for contact in body["contacts"]] == ["Sonia"]


def test_archiving_and_restoring(api):
    customer_id = create(api).json()["id"]

    archived = api.post(reverse("customer-archive", args=[customer_id]))
    assert archived.json()["is_active"] is False
    assert api.get(reverse("customer-list")).json() == []

    restored = api.post(reverse("customer-restore", args=[customer_id]))
    assert restored.json()["is_active"] is True


def test_the_walk_in_customer_cannot_be_archived_over_the_api(api, manager):
    walk_in = CustomerFactory.create(organization=manager.organization, is_walk_in=True)

    response = api.post(reverse("customer-archive", args=[walk_in.pk]))

    assert response.status_code == 400
