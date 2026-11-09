"""The assistant reads through the API as the user, with the same rights as the screens (P12-T01)."""

import pytest
from rest_framework.test import APIClient

from apps.assistant.api_caller import call_api
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.partners import services as partners

pytestmark = pytest.mark.django_db


@pytest.fixture
def company():
    organization = OrganizationFactory.create()
    owner = MembershipFactory.create(organization=organization, role=Role.OWNER)
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    return owner, driver


def test_owner_reads_customers(company):
    owner, _ = company
    answer = call_api(user=owner.user, method="GET", path="customers")
    assert answer.status == 200


def test_driver_gets_the_same_refusal_as_the_screen(company):
    _, driver = company
    answer = call_api(user=driver.user, method="GET", path="suppliers")
    client = APIClient()
    client.force_authenticate(driver.user)
    assert answer.status == client.get("/api/v1/suppliers").status_code == 403


def test_unknown_path_is_not_found(company):
    owner, _ = company
    assert call_api(user=owner.user, method="GET", path="no-such-thing").status == 404


@pytest.mark.parametrize("path", ["../admin", "/customers", "customers?x=1", "https://evil", "a//b"])
def test_odd_paths_refused(company, path):
    owner, _ = company
    with pytest.raises(ValueError, match="Chemin refusé"):
        call_api(user=owner.user, method="GET", path=path)


def test_writes_refused_in_this_version(company):
    owner, _ = company
    with pytest.raises(ValueError, match="Méthode refusée"):
        call_api(user=owner.user, method="POST", path="customers", body={"name": "X"})


def test_query_reaches_the_view(company):
    owner, _ = company
    partners.create_customer(organization=owner.organization, actor=owner.user, name="Mohamed Ben Ali")
    partners.create_customer(organization=owner.organization, actor=owner.user, name="Sami Trabelsi")
    answer = call_api(user=owner.user, method="GET", path="customers", query={"search": "Mohamed"})
    rows = answer.data["results"] if isinstance(answer.data, dict) else answer.data
    assert [row["name"] for row in rows] == ["Mohamed Ben Ali"]
