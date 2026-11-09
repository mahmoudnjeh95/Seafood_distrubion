"""The access matrix: custom roles and each person's own levels (D-306)."""

from collections.abc import Mapping
from typing import Any

import pytest
from django.core.cache import cache
from django.core.exceptions import ValidationError
from rest_framework.test import APIClient

from apps.core import access, services
from apps.core.models import CustomRole, Membership, Role

from .factories import MembershipFactory, OrganizationFactory, UserFactory
from .test_api_security import ROUTES

pytestmark = pytest.mark.django_db


@pytest.fixture(autouse=True)
def _reset_throttles():
    cache.clear()


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def owner(organization):
    return MembershipFactory.create(organization=organization, role=Role.OWNER)


def _client(membership: Membership) -> APIClient:
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def _custom(organization: Any, levels: Mapping[str, str], name: str = "Commercial") -> Membership:
    role = services.create_custom_role(organization=organization, actor=None, name=name, access_levels=levels)
    return MembershipFactory.create(organization=organization, role=Role.CUSTOM, custom_role=role)


def _forbidden(client: APIClient, method: str, path: str, data: Any = None) -> bool:
    answer = getattr(client, method)(path, data or {}, format="json")
    assert answer.status_code < 500, (method, path, answer.status_code)
    return bool(answer.status_code == 403)


# ---- Every route belongs somewhere ----

# Routes in no section: no login needed, one's own profile, the driver's phone, and the owner's users, roles and
# import (their permission classes decide, and a custom role never gets in).
_OUTSIDE = (
    "health",
    "instance",
    "auth/",
    "me",
    "users/",
    "site/",
    "schema",
    "my-",
    "members",
    "roles",
    "access-sections",
    "imports",
    "documents/",
    "whatsapp/",
)


def test_every_office_route_has_a_section():
    missing = []
    for route, _path, _view in ROUTES:
        bare = route.removeprefix(access.API_PREFIX).rstrip("/")
        if bare.startswith(_OUTSIDE):
            continue
        if access.route_section(bare) is None:
            missing.append(bare)
    assert missing == []


def test_the_documents_follow_the_section_of_their_kind():
    assert access.route_section("documents/<str:kind>/<int:object_id>/pdf", {"kind": "invoice"}) == (
        "invoices",
        False,
    )
    assert access.route_section("documents/<str:kind>/<int:object_id>/pdf", {"kind": "partner_statement"}) == (
        "partnerships",
        False,
    )


def test_the_built_in_matrices_name_every_section_with_a_level_it_offers():
    for role, levels in access.BUILTIN.items():
        assert set(levels) == set(access.SECTION_BY_KEY), role
        for key, level in levels.items():
            if role != Role.OWNER:
                assert level in access.SECTION_BY_KEY[key].levels or level == access.Level.NONE, (role, key)


# ---- A custom role ----


def test_a_custom_role_reads_and_writes_only_its_sections(organization, owner):
    seller = _client(_custom(organization, {"sales": "write", "quotes": "read"}))
    assert not _forbidden(seller, "get", "/api/v1/sales")
    assert not _forbidden(seller, "post", "/api/v1/sales")
    assert not _forbidden(seller, "get", "/api/v1/quotes")
    assert _forbidden(seller, "post", "/api/v1/quotes")
    assert _forbidden(seller, "get", "/api/v1/treasury/accounts")
    assert _forbidden(seller, "get", "/api/v1/employees")
    assert _forbidden(seller, "get", "/api/v1/reports/sales")


def test_the_lists_the_forms_pick_from_stay_readable_but_not_writable(organization, owner):
    seller = _client(_custom(organization, {"sales": "write"}))
    for path in ("/api/v1/products", "/api/v1/customers", "/api/v1/locations", "/api/v1/trucks"):
        assert not _forbidden(seller, "get", path), path
    assert _forbidden(seller, "post", "/api/v1/products")
    assert _forbidden(seller, "post", "/api/v1/customers")


def test_a_custom_role_never_reaches_the_owners_screens(organization, owner):
    everything = {section.key: section.levels[-1] for section in access.SECTIONS}
    boss = _client(_custom(organization, everything, name="Presque tout"))
    for path in ("/api/v1/members", "/api/v1/roles", "/api/v1/access-sections", "/api/v1/imports/products/template"):
        assert _forbidden(boss, "get", path), path
    # Nor the driver's phone.
    assert _forbidden(boss, "get", "/api/v1/my-day")


def test_the_owners_own_writes_need_full(organization, owner):
    reviewer = _client(_custom(organization, {"closing": "write"}))
    assert not _forbidden(reviewer, "get", "/api/v1/months")
    assert not _forbidden(reviewer, "post", "/api/v1/months/2026-01/review", {"notes": ""})
    assert _forbidden(reviewer, "post", "/api/v1/months/2026-01/approve")
    closer = _client(_custom(organization, {"closing": "full"}, name="Clôture"))
    assert not _forbidden(closer, "post", "/api/v1/months/2026-01/approve")


def test_a_truck_out_with_an_expired_paper_needs_full_in_the_fleet(organization, owner):
    fleet = _client(_custom(organization, {"fleet": "write"}))
    assert _forbidden(fleet, "post", "/api/v1/trucks/999999/day-allowances")
    chief = _client(_custom(organization, {"fleet": "full"}, name="Chef de parc"))
    assert not _forbidden(chief, "post", "/api/v1/trucks/999999/day-allowances")


def test_the_owners_checks_inside_the_views_follow_full(organization, owner):
    clerk = _custom(organization, {"expenses": "write"})
    assert not access.can(clerk, "expenses", access.Level.FULL)
    assert _forbidden(_client(clerk), "post", "/api/v1/expense-categories", {"name": "Glace"})
    head = _custom(organization, {"expenses": "full"}, name="Chef comptable")
    assert not _forbidden(_client(head), "post", "/api/v1/expense-categories", {"name": "Glace"})


def test_the_session_tells_the_role_name_and_the_levels(organization, owner):
    seller = _custom(organization, {"sales": "write"})
    session = _client(seller).get("/api/v1/me").json()
    assert session["role"] == "custom"
    assert session["role_label"] == "Commercial"
    assert session["access"]["sales"] == "write"
    assert session["access"]["treasury"] == "none"
    owner_session = _client(owner).get("/api/v1/me").json()
    assert set(owner_session["access"].values()) == {"full"}


# ---- A person's own levels over a built-in role ----


def test_a_manager_given_payroll_in_reading_reads_it_and_nothing_more(organization, owner):
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    client = _client(manager)
    assert _forbidden(client, "get", "/api/v1/employees")
    services.set_member_access(organization=organization, membership=manager, actor=None, overrides={"payroll": "read"})
    manager.refresh_from_db()
    client = _client(manager)
    assert not _forbidden(client, "get", "/api/v1/employees")
    assert _forbidden(client, "post", "/api/v1/employees", {"name": "X"})
    # The other sections keep the manager's rules.
    assert not _forbidden(client, "post", "/api/v1/customers", {})


def test_a_manager_can_lose_a_section(organization, owner):
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    services.set_member_access(
        organization=organization, membership=manager, actor=None, overrides={"treasury": "none"}
    )
    client = _client(manager)
    assert _forbidden(client, "get", "/api/v1/treasury/accounts")
    assert not _forbidden(client, "get", "/api/v1/sales")


def test_a_level_equal_to_the_role_is_not_kept(organization, owner):
    manager = MembershipFactory.create(organization=organization, role=Role.MANAGER)
    saved = services.set_member_access(
        organization=organization, membership=manager, actor=None, overrides={"sales": "write", "payroll": "read"}
    )
    assert saved.access_overrides == {"payroll": "read"}


def test_the_owner_and_drivers_take_no_levels_of_their_own(organization, owner):
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER)
    for membership in (owner, driver):
        with pytest.raises(ValidationError):
            services.set_member_access(
                organization=organization, membership=membership, actor=None, overrides={"sales": "read"}
            )


def test_a_level_a_section_does_not_offer_is_refused(organization, owner):
    with pytest.raises(ValidationError):
        services.create_custom_role(organization=organization, actor=None, name="X", access_levels={"payroll": "write"})
    with pytest.raises(ValidationError):
        services.create_custom_role(organization=organization, actor=None, name="Y", access_levels={"nowhere": "read"})


# ---- Roles: names, deletion, assignment ----


def test_role_names_are_unique_and_differ_from_the_built_in_ones(organization, owner):
    services.create_custom_role(organization=organization, actor=None, name="Commercial", access_levels={})
    for name in ("commercial", "Gestionnaire", "  "):
        with pytest.raises(ValidationError):
            services.create_custom_role(organization=organization, actor=None, name=name, access_levels={})


def test_a_role_someone_has_cannot_be_deleted(organization, owner):
    member = _custom(organization, {"sales": "read"})
    role = member.custom_role
    assert role is not None
    with pytest.raises(ValidationError):
        services.delete_custom_role(organization=organization, role=role, actor=None)
    services.set_member_role(organization=organization, membership=member, actor=None, role=Role.MANAGER)
    member.refresh_from_db()
    assert member.custom_role is None
    services.delete_custom_role(organization=organization, role=role, actor=None)
    assert not CustomRole.objects.filter(pk=role.pk).exists()


def test_the_owner_makes_a_role_and_gives_it_through_the_api(organization, owner):
    client = _client(owner)
    made = client.post("/api/v1/roles", {"name": "Magasinier", "access": {"stock": "write"}}, format="json")
    assert made.status_code == 201, made.json()
    person = MembershipFactory.create(organization=organization, role=Role.MANAGER, user=UserFactory.create())
    answer = client.patch(
        f"/api/v1/members/{person.pk}/role", {"role": "custom", "custom_role": made.json()["id"]}, format="json"
    )
    assert answer.status_code == 200, answer.json()
    assert answer.json()["custom_role"]["name"] == "Magasinier"
    assert not _forbidden(_client(person), "get", "/api/v1/stock/overview")
    assert _forbidden(_client(person), "get", "/api/v1/sales")
    # A custom role needs its role; another company's role is unknown.
    other = services.create_custom_role(
        organization=OrganizationFactory.create(), actor=None, name="Ailleurs", access_levels={}
    )
    for body in ({"role": "custom"}, {"role": "custom", "custom_role": other.pk}):
        assert client.patch(f"/api/v1/members/{person.pk}/role", body, format="json").status_code == 400
    sections = client.get("/api/v1/access-sections").json()
    assert {row["key"] for row in sections} == set(access.SECTION_BY_KEY)


def test_a_role_change_reaches_its_people_at_once(organization, owner):
    member = _custom(organization, {"sales": "read"})
    role = member.custom_role
    assert role is not None
    assert _forbidden(_client(member), "post", "/api/v1/sales")
    services.update_custom_role(
        organization=organization, role=role, actor=None, name=role.name, access_levels={"sales": "write"}
    )
    assert not _forbidden(_client(member), "post", "/api/v1/sales")
