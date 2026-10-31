"""Voiding a supplier règlement (D-211, P9-T03b), and the list filters, totals and Excel file of the règlements."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory, OrganizationFactory, UserFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services
from apps.purchasing.models import PlanLineStatus, SupplierInvoice, SupplierPaymentPlanLine
from apps.treasury import selectors as treasury
from apps.treasury import services as treasury_services
from apps.treasury.models import Instrument, InstrumentStatus

pytestmark = pytest.mark.django_db

D = Decimal
TODAY = timezone.localdate


@pytest.fixture
def organization():
    return OrganizationFactory.create()


@pytest.fixture
def actor():
    return UserFactory.create()


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")


@pytest.fixture
def biat(organization):
    return treasury.banks_of(organization).get(code="BIAT")


def client_for(membership):
    client = APIClient()
    client.force_authenticate(membership.user)
    return client


def invoice_of(organization, supplier, amount):
    return services.create_opening_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        amount=amount,
        invoice_date=TODAY() - dt.timedelta(days=10),
        due_date=TODAY() + dt.timedelta(days=20),
    )


def status_of(invoice):
    return SupplierInvoice.objects.get(pk=invoice.pk).status


def test_a_voided_reglement_stops_counting_everywhere(organization, actor, supplier, biat):
    invoice = invoice_of(organization, supplier, "1000")
    services.set_payment_plan(
        invoice=invoice, actor=None, lines=[{"method": "cheque", "planned_on": TODAY(), "amount": "600"}]
    )
    plan_line = SupplierPaymentPlanLine.objects.get()
    payment = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cash", "amount": "400"},
            {"method": "cheque", "amount": "700", "number": "88", "bank": biat, "due_on": TODAY()},
        ],
        allocations=[{"invoice": invoice, "amount": "1000"}],
        plan_lines=[plan_line],
    )
    assert status_of(invoice) == "paid"
    assert selectors.supplier_balance(organization, supplier.pk).balance == D("-100.000")

    with pytest.raises(ValidationError) as no_reason:
        services.void_payment(payment=payment, actor=actor, reason="  ")
    assert "reason" in no_reason.value.message_dict
    services.void_payment(payment=payment, actor=actor, reason="Saisi deux fois")

    payment.refresh_from_db()
    assert (payment.void_reason, payment.voided_by) == ("Saisi deux fois", actor)
    assert status_of(invoice) == "posted"
    balance = selectors.supplier_balance(organization, supplier.pk)
    assert (balance.balance, balance.paid, balance.unallocated) == (D("1000.000"), D("0.000"), D("0.000"))
    assert getattr(selectors.invoice_of(organization, invoice.pk), "outstanding") == D("1000.000")  # noqa: B009
    assert list(selectors.invoice_of(organization, invoice.pk).allocations.all()) == []
    plan_line.refresh_from_db()
    assert (plan_line.status, plan_line.payment) == (PlanLineStatus.OPEN, None)
    assert Instrument.objects.get(number="88").status == InstrumentStatus.CANCELLED
    assert selectors.supplier_debts(organization).cheques == []
    assert selectors.payments_by_day(organization, date_from=TODAY(), date_to=TODAY()) == {}
    assert getattr(selectors.payment_of(organization, payment.pk), "unallocated_amount") == 0  # noqa: B009
    assert AuditLog.objects.filter(action="supplier_payment.voided").count() == 1
    with pytest.raises(ValidationError):
        services.void_payment(payment=payment, actor=actor, reason="encore")
    with pytest.raises(ValidationError):
        services.allocate_payment(payment=payment, actor=actor, allocations=[{"invoice": invoice, "amount": "1"}])
    # The cheque number is free again.
    services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[{"method": "cheque", "amount": "10", "number": "88", "bank": biat}],
    )


def test_a_debited_effet_keeps_its_reglement(organization, actor, supplier, biat):
    payment = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[{"method": "cheque", "amount": "50", "number": "7", "bank": biat}],
    )
    effet = Instrument.objects.get()
    treasury_services._move(effet, to_status=InstrumentStatus.DEBITED, happened_on=TODAY(), actor=actor)

    with pytest.raises(ValidationError):
        services.void_payment(payment=payment, actor=actor, reason="erreur")
    payment.refresh_from_db()
    assert payment.voided_at is None


def test_the_list_filters_adds_up_and_exports(organization, actor, supplier, biat):
    other = SupplierFactory.create(organization=organization, name="Pêcheur Hamdi")
    invoice = invoice_of(organization, supplier, "300")
    mixed = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cash", "amount": "100"},
            {"method": "bill", "amount": "400", "number": "T1", "bank": biat, "due_on": TODAY()},
        ],
        allocations=[{"invoice": invoice, "amount": "300"}],
    )
    old = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=other,
        paid_on=TODAY() - dt.timedelta(days=40),
        amount="80",
        method="cash",
    )
    voided = services.record_payment(
        organization=organization, actor=actor, supplier=other, paid_on=TODAY(), amount="999", method="transfer"
    )
    services.void_payment(payment=voided, actor=actor, reason="erreur")
    accountant = client_for(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT))
    url = reverse("supplier-payment-list")

    def numbers(**params):
        return [row["number"] for row in accountant.get(url, params).json()["results"]]

    assert numbers(method="cash") == [mixed.number, old.number]
    assert numbers(method="mixed") == [mixed.number]
    assert numbers(method="bill") == [mixed.number]
    assert numbers(state="voided") == [voided.number]
    assert numbers(state="unallocated") == [mixed.number, old.number]
    assert numbers(date_from=(TODAY() - dt.timedelta(days=7)).isoformat()) == [voided.number, mixed.number]
    assert numbers(supplier=other.pk, state="active") == [old.number]
    listed = accountant.get(url, {"state": "voided"}).json()["results"][0]
    assert (listed["is_voided"], listed["void_reason"], listed["unallocated_amount"]) == (True, "erreur", "0.000")

    totals = accountant.get(reverse("supplier-payment-totals")).json()
    assert totals == {
        "count": 2,
        "voided": 1,
        "total": "580.000",
        "allocated": "300.000",
        "unallocated": "280.000",
        "by_method": {"bill": "400.000", "cash": "180.000"},
    }

    exported = accountant.get(reverse("supplier-payment-export"), {"method": "cash"})
    assert exported.status_code == 200
    assert exported["Content-Type"].startswith("application/vnd.openxmlformats")

    detail = accountant.get(reverse("supplier-payment-detail", args=[mixed.pk])).json()
    events = detail["lines"][1]["instrument"]["events"]
    assert [(row["from_status"], row["to_status"]) for row in events] == [("", "issued")]

    refused = accountant.post(reverse("supplier-payment-void", args=[mixed.pk]), {"reason": "x"}, format="json")
    assert refused.status_code == 403
    manager = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    done = manager.post(reverse("supplier-payment-void", args=[mixed.pk]), {"reason": "doublon"}, format="json")
    assert done.status_code == 200, done.json()
    assert done.json()["is_voided"] is True
    assert done.json()["lines"][1]["instrument"]["status"] == "cancelled"
