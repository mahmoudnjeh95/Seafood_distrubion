import datetime as dt

import pytest
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.inventory.tests.factories import BatchFactory

from .factories import EmployeeFactory

pytestmark = pytest.mark.django_db

YEAR = timezone.localdate().year

MONTH = timezone.localdate().replace(day=1).isoformat()


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


@pytest.fixture
def owner():
    return MembershipFactory.create(role=Role.OWNER)


@pytest.fixture
def api(owner):
    return client_for(owner)


def create_employee(api, **fields):
    payload = {
        "name": "Sami B.",
        "position": "Chauffeur-vendeur",
        "monthly_salary": "1250",
        "employee_cnss_rate": "0",
    }
    payload.update(fields)
    return api.post(reverse("employee-list"), payload, format="json")


def test_the_owner_creates_an_employee_with_money_as_strings_and_the_default_rate(api):
    response = create_employee(api, cnss_number="12345678-90", hire_date="2024-03-01")

    assert response.status_code == 201
    body = response.json()
    assert body["reference"] == "E-001"
    assert (body["monthly_salary"], body["cnss_rate"], body["unpaid"]) == ("1250.000", "17.07", "0.000")
    assert body["employee_cnss_rate"] == "0.00"
    assert body["user"] is None


def test_a_typed_zero_rate_stays_zero_and_only_an_omitted_rate_gets_the_default(api):
    free = create_employee(api, cnss_rate="0")

    assert free.status_code == 201
    assert free.json()["cnss_rate"] == "0.00"


def test_an_employee_is_linked_to_a_login_of_the_organization(api, owner):
    driver = MembershipFactory.create(role=Role.DRIVER, organization=owner.organization)
    stranger = MembershipFactory.create(role=Role.DRIVER)

    linked = create_employee(api, user=driver.user.pk)
    refused = create_employee(api, user=stranger.user.pk)

    assert linked.json()["user"] == {"id": driver.user.pk, "username": driver.user.username}
    assert refused.status_code == 400
    assert list(refused.json()) == ["user"]


def test_invalid_salary_or_rate_is_a_400_on_its_field(api):
    assert list(create_employee(api, monthly_salary="-5").json()) == ["monthly_salary"]
    assert list(create_employee(api, monthly_salary="10.0001").json()) == ["monthly_salary"]
    assert list(create_employee(api, cnss_rate="101").json()) == ["cnss_rate"]


@pytest.mark.parametrize(
    ("role", "read_status", "write_status"),
    [
        (Role.OWNER, 200, 201),
        (Role.ACCOUNTANT, 200, 403),
        (Role.MANAGER, 403, 403),
        (Role.DRIVER, 403, 403),
    ],
)
def test_only_the_owner_writes_and_the_accountant_reads_pay(role, read_status, write_status):
    client = client_for(MembershipFactory.create(role=role))

    assert client.get(reverse("employee-list")).status_code == read_status
    assert create_employee(client).status_code == write_status
    assert client.get(reverse("salary-record-list")).status_code == read_status
    assert client.get(reverse("salary-payment-list")).status_code == read_status
    assert client.get(reverse("payroll-summary"), {"month": MONTH}).status_code == read_status
    assert client.get(reverse("lot-work-day-list")).status_code == read_status


def test_a_linked_driver_sees_nothing_of_pay():
    employee = EmployeeFactory.create()
    driver = MembershipFactory.create(role=Role.DRIVER, organization=employee.organization)
    client = client_for(driver)

    assert client.get(reverse("employee-detail", args=[employee.pk])).status_code == 403
    assert client.post(reverse("salary-record-generate"), {"month": MONTH}, format="json").status_code == 403


def test_employees_of_another_organization_are_not_found(api):
    foreign = EmployeeFactory.create()

    assert api.get(reverse("employee-detail", args=[foreign.pk])).status_code == 404
    assert api.post(reverse("employee-archive", args=[foreign.pk])).status_code == 404
    assert api.get(reverse("employee-list")).json() == []


def test_archiving_hides_an_employee_from_the_default_list(api):
    employee_id = create_employee(api).json()["id"]

    api.post(reverse("employee-archive", args=[employee_id]))

    assert api.get(reverse("employee-list")).json() == []
    assert len(api.get(reverse("employee-list"), {"status": "all"}).json()) == 1


def test_payroll_month_flow_generate_adjust_pay(api):
    create_employee(api, name="Rim K.", monthly_salary="1600.000")
    create_employee(api, name="Anis M.", monthly_salary="1250.000")

    generated = api.post(reverse("salary-record-generate"), {"month": MONTH}, format="json").json()
    assert generated["created"] == 2
    assert [record["net"] for record in generated["records"]] == ["1250.000", "1600.000"]
    # Approved by default (D-228): no draft step.
    assert {record["status"] for record in generated["records"]} == {"approved"}
    again = api.post(reverse("salary-record-generate"), {"month": MONTH}, format="json").json()
    assert again["created"] == 0

    record = next(item for item in generated["records"] if item["employee"]["name"] == "Rim K.")
    detail = reverse("salary-record-detail", args=[record["id"]])
    # An approved salary changes by an adjustment only: no patch, no approval, no delete.
    assert api.patch(detail, {"bonus": "100.000"}, format="json").status_code == 400
    assert api.post(reverse("salary-record-approve", args=[record["id"]])).status_code == 400
    assert api.delete(detail).status_code == 400

    adjusted = api.post(
        reverse("salary-record-adjust", args=[record["id"]]),
        {"amount": "-50.000", "reason": "Retard"},
        format="json",
    )
    assert adjusted.status_code == 201
    assert api.get(detail).json()["outstanding"] == "1550.000"

    payment = api.post(
        reverse("salary-payment-list"),
        {
            "employee": record["employee"]["id"],
            "paid_on": timezone.localdate().isoformat(),
            "amount": "1000.000",
            "method": "cash",
            "allocations": [{"salary_record": record["id"], "amount": "1000.000"}],
        },
        format="json",
    )
    assert payment.status_code == 201
    assert payment.json()["number"] == f"PS-{YEAR}-0001"
    assert payment.json()["unallocated"] == "0.000"
    assert api.get(detail).json()["outstanding"] == "550.000"

    summary = api.get(reverse("payroll-summary"), {"month": MONTH}).json()
    assert (summary["records"], summary["drafts"], summary["paid"], summary["outstanding"]) == (
        2,
        0,
        "1000.000",
        "1800.000",
    )
    assert (summary["unpaid_total"], summary["unpaid_records"]) == ("1800.000", 2)
    employee = next(item for item in api.get(reverse("employee-list")).json() if item["id"] == record["employee"]["id"])
    assert employee["unpaid"] == "550.000"

    month = api.post(reverse("salary-record-approve-month"), {"month": MONTH}, format="json").json()
    assert month["approved"] == 0
    actions = set(AuditLog.objects.values_list("action", flat=True))
    assert {"salary.month_generated", "salary.adjusted", "salary_payment.recorded"} <= actions


def test_payment_errors_come_back_on_the_allocation_line(api):
    employee_id = create_employee(api).json()["id"]
    api.post(reverse("salary-record-generate"), {"month": MONTH}, format="json")

    response = api.post(
        reverse("salary-payment-list"),
        {
            "employee": employee_id,
            "paid_on": timezone.localdate().isoformat(),
            "amount": "10.000",
            "method": "cash",
            "allocations": [{"salary_record": 99999, "amount": "10.000"}],
        },
        format="json",
    )

    assert response.status_code == 400
    assert list(response.json()) == ["allocations.0.salary_record"]


def test_days_on_a_lot_use_the_batch_and_the_salary_over_26(api, owner):
    employee_id = create_employee(api, monthly_salary="1300").json()["id"]
    batch = BatchFactory.create(organization=owner.organization)

    created = api.post(
        reverse("lot-work-day-list"),
        {
            "employee": employee_id,
            "work_date": timezone.localdate().isoformat(),
            "batch": batch.pk,
            "days": "0.5",
        },
        format="json",
    )

    assert created.status_code == 201
    body = created.json()
    assert (body["days"], body["cost"], body["batch"]) == ("0.50", "25.000", {"id": batch.pk, "number": batch.number})
    listed = api.get(reverse("lot-work-day-list"), {"batch": batch.pk}).json()
    assert [item["cost"] for item in listed] == ["25.000"]
    assert api.delete(reverse("lot-work-day-detail", args=[body["id"]])).status_code == 204


def test_an_unknown_batch_or_a_day_over_one_is_a_400(api):
    employee_id = create_employee(api).json()["id"]
    foreign_batch = BatchFactory.create()
    today = timezone.localdate().isoformat()

    unknown = api.post(
        reverse("lot-work-day-list"),
        {"employee": employee_id, "work_date": today, "batch": foreign_batch.pk, "days": "1"},
        format="json",
    )
    too_much = api.post(
        reverse("lot-work-day-list"), {"employee": employee_id, "work_date": today, "days": "1.5"}, format="json"
    )
    future = api.post(
        reverse("lot-work-day-list"),
        {"employee": employee_id, "work_date": (timezone.localdate() + dt.timedelta(days=2)).isoformat(), "days": "1"},
        format="json",
    )

    assert list(unknown.json()) == ["batch"]
    assert list(too_much.json()) == ["days"]
    assert list(future.json()) == ["work_date"]
