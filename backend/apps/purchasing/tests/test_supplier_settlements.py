"""Paid, planned or undefined, per supplier invoice (P3-T16a, D-192): the states, the sum limit, a payment that
settles a plan line, permissions, and a plan that never moves the supplier balance."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory
from apps.inventory.tests.factories import StockLocationFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services
from apps.purchasing.models import PlanLineStatus, SupplierPaymentPlanLine

pytestmark = pytest.mark.django_db

TODAY = timezone.localdate


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization)


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def invoice_of(organization, supplier, amount="1000", due_in=30):
    """A posted opening invoice of `amount` DT."""
    return services.create_opening_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        amount=amount,
        invoice_date=TODAY() - dt.timedelta(days=1),
        due_date=TODAY() + dt.timedelta(days=due_in),
    )


def line(amount, planned_in=5, method="cash", **extra):
    return {"amount": amount, "method": method, "planned_on": TODAY() + dt.timedelta(days=planned_in), **extra}


def line_json(amount):
    return {"amount": amount, "method": "cash", "planned_on": TODAY().isoformat()}


def row_of(organization, invoice):
    return selectors.settlement_of(organization, invoice.pk)


def pay(organization, supplier, invoice, amount, **extra):
    return services.record_payment(
        organization=organization,
        actor=None,
        supplier=supplier,
        paid_on=TODAY(),
        amount=amount,
        method="cash",
        allocations=[{"invoice": invoice, "amount": amount}],
        **extra,
    )


def test_an_invoice_with_no_plan_is_undefined(organization, supplier):
    invoice = invoice_of(organization, supplier)
    row = row_of(organization, invoice)
    assert (row.state, row.paid, row.planned, row.undefined) == ("undefined", 0, 0, Decimal("1000.000"))
    assert row.purchase_type == "opening"


def test_a_partial_plan_stays_undefined_a_full_plan_is_planned(organization, supplier):
    invoice = invoice_of(organization, supplier)
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("400")])
    row = row_of(organization, invoice)
    assert (row.state, row.planned, row.undefined) == ("undefined", Decimal("400.000"), Decimal("600.000"))
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("400"), line("600", method="cheque")])
    row = row_of(organization, invoice)
    assert (row.state, row.planned, row.undefined) == ("planned", Decimal("1000.000"), 0)


def test_a_plan_line_or_a_due_date_in_the_past_is_overdue(organization, supplier):
    late_line = invoice_of(organization, supplier)
    services.set_payment_plan(invoice=late_line, actor=None, lines=[line("1000")])
    SupplierPaymentPlanLine.objects.update(planned_on=TODAY() - dt.timedelta(days=2))
    assert row_of(organization, late_line).state == "overdue"
    late_due = services.create_opening_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        amount="50",
        invoice_date=TODAY() - dt.timedelta(days=10),
        due_date=TODAY() - dt.timedelta(days=3),
    )
    assert row_of(organization, late_due).state == "overdue"


def test_a_fully_paid_invoice_is_settled(organization, supplier):
    invoice = invoice_of(organization, supplier, amount="200")
    pay(organization, supplier, invoice, "200")
    row = row_of(organization, invoice)
    assert (row.state, row.paid, row.undefined) == ("settled", Decimal("200.000"), 0)


def test_lines_cannot_exceed_what_is_left_to_pay(organization, supplier):
    invoice = invoice_of(organization, supplier)
    pay(organization, supplier, invoice, "300")
    with pytest.raises(ValidationError) as caught:
        services.set_payment_plan(invoice=invoice, actor=None, lines=[line("400"), line("301")])
    assert "lines" in caught.value.message_dict
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("400"), line("300")])
    assert row_of(organization, invoice).state == "planned"


def test_replacing_the_plan_cancels_the_old_open_lines(organization, supplier):
    invoice = invoice_of(organization, supplier)
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("400")])
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("250")])
    statuses = sorted(SupplierPaymentPlanLine.objects.values_list("status", "amount"))
    assert statuses == [("cancelled", Decimal("400.000")), ("open", Decimal("250.000"))]
    services.set_payment_plan(invoice=invoice, actor=None, lines=[])
    assert row_of(organization, invoice).planned == 0


def test_a_line_is_checked_field_by_field(organization, supplier):
    invoice = invoice_of(organization, supplier)
    with pytest.raises(ValidationError) as caught:
        services.set_payment_plan(
            invoice=invoice, actor=None, lines=[{"amount": "0", "method": "gold", "planned_on": TODAY()}]
        )
    assert {"lines.0.amount", "lines.0.method"} <= set(caught.value.message_dict)


def test_a_draft_invoice_cannot_be_planned(organization, supplier):
    product = ProductFactory.create(organization=organization)
    room = StockLocationFactory.create(organization=organization)
    receipt = services.create_receipt(
        organization=organization,
        actor=None,
        supplier=supplier,
        location=room,
        received_on=TODAY(),
        lines=[{"product": product, "invoiced_quantity": "1", "accepted_quantity": "1", "unit_cost": "10"}],
    )
    draft = services.create_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        receipts=[receipt],
        invoice_date=TODAY(),
        due_date=TODAY(),
    )
    with pytest.raises(ValidationError) as caught:
        services.set_payment_plan(invoice=draft, actor=None, lines=[line("5")])
    assert "invoice" in caught.value.message_dict


def test_a_payment_naming_a_plan_line_settles_it(organization, supplier):
    invoice = invoice_of(organization, supplier)
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("400"), line("300")])
    first, second = SupplierPaymentPlanLine.objects.order_by("id")
    payment = pay(organization, supplier, invoice, "400", plan_line=first)
    first.refresh_from_db()
    second.refresh_from_db()
    assert (first.status, first.payment_id, second.status) == (PlanLineStatus.PAID, payment.pk, PlanLineStatus.OPEN)
    row = row_of(organization, invoice)
    assert (row.paid, row.planned, row.undefined, row.state) == (
        Decimal("400.000"),
        Decimal("300.000"),
        Decimal("300.000"),
        "undefined",
    )
    # A paid line cannot be paid again nor cancelled.
    with pytest.raises(ValidationError):
        pay(organization, supplier, invoice, "10", plan_line=first)
    with pytest.raises(ValidationError):
        services.cancel_plan_line(line=first, actor=None)


def test_a_payment_must_be_allocated_to_the_line_invoice(organization, supplier):
    invoice = invoice_of(organization, supplier)
    other = invoice_of(organization, supplier, amount="500")
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("400")])
    plan_line = SupplierPaymentPlanLine.objects.get()
    with pytest.raises(ValidationError) as caught:
        pay(organization, supplier, other, "100", plan_line=plan_line)
    assert "plan_line" in caught.value.message_dict


def test_planning_never_moves_the_supplier_balance(organization, supplier):
    invoice = invoice_of(organization, supplier)
    before = selectors.supplier_balance(organization, supplier.pk)
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("1000")])
    services.cancel_plan_line(line=SupplierPaymentPlanLine.objects.get(), actor=None)
    after = selectors.supplier_balance(organization, supplier.pk)
    assert (after.balance, after.paid) == (before.balance, before.paid)
    assert after.balance == Decimal("1000.000")


def test_the_list_filters_and_totals(organization, supplier):
    planned = invoice_of(organization, supplier, amount="1000")
    invoice_of(organization, supplier, amount="500")
    services.set_payment_plan(invoice=planned, actor=None, lines=[line("1000")])
    found = selectors.supplier_settlements(organization, state="planned")
    assert [row.invoice.pk for row in found.rows] == [planned.pk]
    assert (found.summary.planned, found.summary.undefined, found.summary.counts["undefined"]) == (
        Decimal("1000.000"),
        Decimal("500.000"),
        1,
    )
    assert selectors.supplier_settlements(organization, purchase_type="port").rows == []


def test_undefined_for_over_a_day_is_counted_for_the_dashboard(organization, supplier):
    invoice = invoice_of(organization, supplier)
    now = timezone.now()
    assert selectors.undefined_settlements_late(organization, now=now) == 0
    assert selectors.undefined_settlements_late(organization, now=now + dt.timedelta(hours=25)) == 1
    services.set_payment_plan(invoice=invoice, actor=None, lines=[line("1000")])
    assert selectors.undefined_settlements_late(organization, now=now + dt.timedelta(hours=25)) == 0


def test_the_api_plans_lists_cancels_and_pays(organization, supplier):
    invoice = invoice_of(organization, supplier)
    manager = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    body = {"lines": [{"amount": "600.000", "method": "cheque", "planned_on": TODAY().isoformat(), "reference": "C1"}]}
    planned = manager.put(reverse("supplier-invoice-plan", args=[invoice.pk]), body, format="json")
    assert planned.status_code == 200, planned.json()
    assert (planned.json()["state"], planned.json()["undefined"]) == ("undefined", "400.000")
    line_id = planned.json()["plan_lines"][0]["id"]

    listed = manager.get(reverse("supplier-settlements"), {"state": "undefined", "type": "opening"}).json()
    assert [row["invoice_id"] for row in listed["rows"]] == [invoice.pk]
    assert listed["summary"]["planned"] == "600.000"

    paid = manager.post(
        reverse("supplier-payment-list"),
        {
            "supplier": supplier.pk,
            "paid_on": TODAY().isoformat(),
            "amount": "600",
            "method": "cheque",
            "allocations": [{"invoice": invoice.pk, "amount": "600"}],
            "plan_line": line_id,
        },
        format="json",
    )
    assert paid.status_code == 201, paid.json()
    assert SupplierPaymentPlanLine.objects.get(pk=line_id).status == PlanLineStatus.PAID

    other = invoice_of(organization, supplier, amount="100")
    manager.put(reverse("supplier-invoice-plan", args=[other.pk]), {"lines": [line_json("100")]}, format="json")
    cancelled = manager.delete(reverse("supplier-plan-line", args=[SupplierPaymentPlanLine.objects.latest("id").pk]))
    assert cancelled.status_code == 200, cancelled.json()
    assert cancelled.json()["planned"] == "0.000"

    too_much = manager.put(
        reverse("supplier-invoice-plan", args=[other.pk]), {"lines": [line_json("101")]}, format="json"
    )
    assert too_much.status_code == 400


def test_permissions(organization, supplier):
    invoice = invoice_of(organization, supplier)
    body = {"lines": [line_json("10")]}
    url = reverse("supplier-invoice-plan", args=[invoice.pk])
    accountant = client_for(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT))
    assert accountant.get(reverse("supplier-settlements")).status_code == 200
    assert accountant.put(url, body, format="json").status_code == 403
    driver = client_for(MembershipFactory.create(organization=organization, role=Role.DRIVER))
    assert driver.get(reverse("supplier-settlements")).status_code == 403
    assert driver.put(url, body, format="json").status_code == 403
    owner = client_for(MembershipFactory.create(organization=organization, role=Role.OWNER))
    assert owner.put(url, body, format="json").status_code == 200
    # Another organization's invoice is not found.
    stranger = client_for(MembershipFactory.create(organization=OrganizationFactory.create(), role=Role.OWNER))
    assert stranger.put(url, body, format="json").status_code == 404
