"""One of our cheques or traites the bank refused (rejeté, P9-T04c, D-218): the supplier is owed it again, the
invoices its règlement settled owe again beyond its advance."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import SupplierFactory
from apps.purchasing import selectors, services, statements
from apps.purchasing.models import SupplierInvoice
from apps.treasury import selectors as treasury
from apps.treasury.models import Instrument, InstrumentStatus

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
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")


def invoice_of(organization, supplier, amount, days_ago):
    return services.create_opening_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        amount=amount,
        invoice_date=TODAY() - dt.timedelta(days=days_ago),
        due_date=TODAY() + dt.timedelta(days=20),
    )


def test_a_rejected_effet_makes_the_supplier_and_the_invoices_owed_again(organization, manager, supplier):
    actor = manager.user
    first = invoice_of(organization, supplier, "600", 20)
    second = invoice_of(organization, supplier, "400", 10)
    biat = treasury.banks_of(organization).get(code="BIAT")
    payment = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cash", "amount": "700"},
            {"method": "cheque", "amount": "500", "number": "4401", "bank": biat},
        ],
        allocations=[{"invoice": first, "amount": "600"}, {"invoice": second, "amount": "400"}],
    )
    assert selectors.supplier_balance(organization, supplier.pk).balance == D("-200.000")
    effet = Instrument.objects.get(number="4401")

    with pytest.raises(ValidationError) as refused:
        services.reject_issued_effet(
            organization=organization, actor=actor, instrument_id=effet.pk, rejected_on=TODAY(), reason=""
        )
    assert "reason" in refused.value.message_dict
    rejected = services.reject_issued_effet(
        organization=organization, actor=actor, instrument_id=effet.pk, rejected_on=TODAY(), reason="Sans provision"
    )

    effet.refresh_from_db()
    assert effet.status == InstrumentStatus.REJECTED
    balance = selectors.supplier_balance(organization, supplier.pk)
    # The 200 of advance went first; 300 is taken back from the newest allocation (the second invoice).
    assert (balance.balance, balance.paid, balance.unallocated) == (D("300.000"), D("700.000"), D("0.000"))
    assert [(row.invoice_id, row.amount) for row in rejected.releases.all()] == [(second.pk, D("300.000"))]
    assert SupplierInvoice.objects.get(pk=second.pk).status == "partly_paid"
    assert SupplierInvoice.objects.get(pk=first.pk).status == "paid"
    assert getattr(selectors.invoice_of(organization, second.pk), "outstanding") == D("300.000")  # noqa: B009
    listed = selectors.payment_of(organization, payment.pk)
    assert (getattr(listed, "allocated_amount"), getattr(listed, "unallocated_amount")) == (  # noqa: B009
        D("700.000"),
        D("0.000"),
    )
    assert selectors.supplier_debts(organization).cheques == []
    statement = statements.supplier_statement(organization, supplier.pk, date_from=None, date_to=TODAY())
    assert statement.entries[-1].kind == "rejected"
    assert statement.closing_balance == D("300.000")
    assert AuditLog.objects.filter(action="supplier_payment.rejected").count() == 1

    with pytest.raises(ValidationError):
        services.reject_issued_effet(
            organization=organization, actor=actor, instrument_id=effet.pk, rejected_on=TODAY(), reason="encore"
        )
    with pytest.raises(ValidationError):
        services.void_payment(payment=payment, actor=actor, reason="erreur")

    # A new règlement pays what is owed again.
    services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[{"method": "transfer", "amount": "300", "reference": "VIR-9"}],
        allocations=[{"invoice": second, "amount": "300"}],
    )
    assert selectors.supplier_balance(organization, supplier.pk).balance == D("0.000")
    assert SupplierInvoice.objects.get(pk=second.pk).status == "paid"


def test_the_api_rejects_one_of_our_effets(organization, manager, supplier):
    services.record_payment(
        organization=organization,
        actor=manager.user,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {
                "method": "bill",
                "amount": "250",
                "number": "TR-3",
                "bank": treasury.banks_of(organization).get(code="STB"),
                "due_on": TODAY(),
            }
        ],
    )
    effet = Instrument.objects.get(number="TR-3")
    api = APIClient()
    api.force_authenticate(manager.user)

    answer = api.post(
        reverse("supplier-effet-reject", args=[effet.pk]),
        {"rejected_on": TODAY().isoformat(), "reason": "Compte bloqué"},
        format="json",
    )

    assert answer.status_code == 200, answer.json()
    line = answer.json()["lines"][0]
    assert (line["instrument"]["status"], line["rejected"]["reason"]) == ("rejected", "Compte bloqué")
    assert answer.json()["unallocated_amount"] == "0.000"
    assert selectors.supplier_balance(organization, supplier.pk).balance == D("0.000")
    accountant = APIClient()
    accountant.force_authenticate(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT).user)
    assert (
        accountant.post(reverse("supplier-effet-reject", args=[effet.pk]), {"reason": "x"}, format="json").status_code
        == 403
    )
