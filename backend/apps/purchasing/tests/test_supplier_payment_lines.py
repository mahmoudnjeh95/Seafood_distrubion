"""A supplier règlement with several means (D-208, P9-T02): our cheques and traites become effets issued, the
allocation by invoice or oldest due first, several plan lines in one règlement, and the older single-field forms."""

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
from apps.purchasing.models import PlanLineStatus, SupplierInvoice, SupplierInvoiceStatus, SupplierPaymentPlanLine
from apps.treasury import selectors as treasury
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


def invoice_of(organization, supplier, amount, due_in=30):
    """A posted opening invoice of `amount` DT, due in `due_in` days."""
    return services.create_opening_invoice(
        organization=organization,
        actor=None,
        supplier=supplier,
        amount=amount,
        invoice_date=TODAY() - dt.timedelta(days=60),
        due_date=TODAY() + dt.timedelta(days=due_in),
    )


def in_days(days):
    return TODAY() + dt.timedelta(days=days)


def test_cash_two_cheques_and_a_traite_pay_two_invoices(organization, actor, supplier, biat):
    first = invoice_of(organization, supplier, "1500")
    second = invoice_of(organization, supplier, "2000")
    stb = treasury.banks_of(organization).get(code="STB")

    payment = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cash", "amount": "500"},
            {"method": "cheque", "amount": "1000", "number": "4401", "bank": biat},
            {"method": "cheque", "amount": "1000", "number": "4402", "bank": biat, "due_on": in_days(15)},
            {"method": "bill", "amount": "800", "number": "TR-77", "bank": stb, "due_on": in_days(60)},
            {"method": "transfer", "amount": "200", "reference": "VIR-123"},
        ],
        allocations=[{"invoice": first, "amount": "1500"}, {"invoice": second, "amount": "1800"}],
    )

    assert (payment.amount, payment.method, payment.reference, payment.cash_on) == (D("3500.000"), "mixed", "", None)
    lines = list(payment.lines.order_by("id"))
    assert [(line.method, line.amount, line.reference) for line in lines] == [
        ("cash", D("500.000"), ""),
        ("cheque", D("1000.000"), ""),
        ("cheque", D("1000.000"), ""),
        ("bill", D("800.000"), ""),
        ("transfer", D("200.000"), "VIR-123"),
    ]
    effets = Instrument.objects.filter(supplier=supplier).order_by("due_on", "id")
    assert [(row.kind, row.number, row.bank.code if row.bank else "", row.due_on, row.status) for row in effets] == [
        ("cheque", "4401", "BIAT", TODAY(), "issued"),
        ("cheque", "4402", "BIAT", in_days(15), "issued"),
        ("bill", "TR-77", "STB", in_days(60), "issued"),
    ]
    assert {row.direction for row in effets} == {"issued"}
    assert {row.source_number for row in effets} == {payment.number}
    assert SupplierInvoice.objects.get(pk=first.pk).status == SupplierInvoiceStatus.PAID
    assert SupplierInvoice.objects.get(pk=second.pk).status == SupplierInvoiceStatus.PARTLY_PAID
    # 200 DT not allocated: an advance.
    assert getattr(selectors.payment_of(organization, payment.pk), "unallocated_amount") == D("200.000")  # noqa: B009
    log = AuditLog.objects.get(action="supplier_payment.recorded")
    assert log.after is not None
    assert [row["method"] for row in log.after["lines"]] == ["cash", "cheque", "cheque", "bill", "transfer"]
    assert log.after["lines"][3] == {
        "method": "bill",
        "amount": "800.000",
        "reference": "",
        "number": "TR-77",
        "bank": "STB",
        "due_on": in_days(60).isoformat(),
    }


def test_every_line_problem_is_reported_on_its_line(organization, actor, supplier, biat):
    services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[{"method": "cheque", "amount": "100", "number": "9001", "bank": biat}],
    )
    other = OrganizationFactory.create()
    elsewhere = treasury.banks_of(other).get(code="BIAT")
    with pytest.raises(ValidationError) as refused:
        services.record_payment(
            organization=organization,
            actor=actor,
            supplier=supplier,
            paid_on=TODAY(),
            lines=[
                {"method": "mixed", "amount": "10"},
                {"method": "cash", "amount": "0"},
                {"method": "cheque", "amount": "10", "number": "", "bank": None},
                {"method": "bill", "amount": "10", "number": "T1", "bank": elsewhere},
                {"method": "bill", "amount": "10", "number": "T2", "bank": biat, "due_on": in_days(400)},
                # Our cheque 9001 is already given, to whoever it went.
                {"method": "cheque", "amount": "10", "number": "9001", "bank": biat},
                {"method": "cheque", "amount": "10", "number": "9002", "bank": biat},
                {"method": "cheque", "amount": "10", "number": "9002", "bank": biat},
            ],
        )
    assert refused.value.message_dict.keys() == {
        "lines.0.method",
        "lines.1.amount",
        "lines.2.number",
        "lines.2.bank",
        "lines.3.bank",
        "lines.3.due_on",
        "lines.4.due_on",
        "lines.5.number",
        "lines.7.number",
    }
    with pytest.raises(ValidationError) as empty:
        services.record_payment(organization=organization, actor=actor, supplier=supplier, paid_on=TODAY(), lines=[])
    assert "lines" in empty.value.message_dict
    with pytest.raises(ValidationError) as mismatch:
        services.record_payment(
            organization=organization,
            actor=actor,
            supplier=supplier,
            paid_on=TODAY(),
            amount="99",
            lines=[{"method": "cash", "amount": "100"}],
        )
    assert mismatch.value.message_dict.keys() == {"amount"}


def test_without_allocations_the_invoice_due_first_is_paid_first(organization, actor, supplier):
    later = invoice_of(organization, supplier, "300", due_in=40)
    sooner = invoice_of(organization, supplier, "500", due_in=10)

    payment = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[{"method": "cash", "amount": "650"}],
        allocations=None,
    )

    assert [(row.invoice_id, row.amount) for row in payment.allocations.order_by("id")] == [
        (sooner.pk, D("500.000")),
        (later.pk, D("150.000")),
    ]


def test_one_reglement_pays_several_plan_lines(organization, actor, supplier, biat):
    first = invoice_of(organization, supplier, "1000")
    second = invoice_of(organization, supplier, "600")

    def plan(amount: str) -> services.PlanLineFields:
        return {"method": "cheque", "planned_on": TODAY(), "amount": amount}

    services.set_payment_plan(invoice=first, actor=None, lines=[plan("400"), plan("600")])
    services.set_payment_plan(invoice=second, actor=None, lines=[plan("600")])
    ours = list(SupplierPaymentPlanLine.objects.order_by("id"))

    payment = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cheque", "amount": "400", "number": "1", "bank": biat},
            {"method": "cheque", "amount": "600", "number": "2", "bank": biat},
        ],
        allocations=[{"invoice": first, "amount": "1000"}],
        plan_lines=ours[:2],
    )

    states = [(row.status, row.payment_id) for row in SupplierPaymentPlanLine.objects.order_by("id")]
    assert states == [(PlanLineStatus.PAID, payment.pk), (PlanLineStatus.PAID, payment.pk), (PlanLineStatus.OPEN, None)]
    with pytest.raises(ValidationError) as refused:
        services.record_payment(
            organization=organization,
            actor=actor,
            supplier=supplier,
            paid_on=TODAY(),
            lines=[{"method": "cash", "amount": "100"}],
            allocations=[{"invoice": second, "amount": "100"}],
            plan_lines=[ours[0], ours[2], ours[2]],
        )
    assert refused.value.message_dict.keys() == {"plan_lines.0", "plan_lines.2"}


def test_the_single_fields_make_one_line_with_an_effet_to_complete(organization, actor, supplier):
    invoice = invoice_of(organization, supplier, "800")

    payment = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        amount="800",
        method="bill",
        reference="TR-9",
        allocations=[{"invoice": invoice, "amount": "800"}],
    )

    assert (payment.method, payment.reference, payment.cash_on) == ("bill", "TR-9", None)
    line = payment.lines.get()
    assert (line.method, line.amount, line.reference) == ("bill", D("800.000"), "")
    assert line.instrument is not None
    assert (line.instrument.number, line.instrument.bank, line.instrument.due_on) == ("TR-9", None, TODAY())
    # No number given: the effet keeps the règlement's until the office completes it.
    cheque = services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        amount="50",
        method="cheque",
        cash_on=in_days(20),
    )
    effet = cheque.lines.get().instrument
    assert effet is not None
    assert (effet.number, effet.due_on, cheque.cash_on) == (cheque.number, in_days(20), in_days(20))
    with pytest.raises(ValidationError) as refused:
        services.record_payment(
            organization=organization,
            actor=actor,
            supplier=supplier,
            paid_on=TODAY(),
            amount="0",
            method="mixed",
            cash_on=TODAY() - dt.timedelta(days=1),
        )
    assert refused.value.message_dict.keys() == {"amount", "method", "cash_on"}


def test_the_cheques_to_come_list_reads_each_effet(organization, actor, supplier, biat):
    services.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cash", "amount": "100"},
            {"method": "cheque", "amount": "200", "number": "71", "bank": biat, "due_on": in_days(9)},
            {"method": "bill", "amount": "300", "number": "T-3", "bank": biat, "due_on": in_days(3)},
        ],
    )

    debts = selectors.supplier_debts(organization)

    assert [(row.method, row.reference, row.amount, row.cash_on) for row in debts.cheques] == [
        ("bill", "T-3", D("300.000"), in_days(3)),
        ("cheque", "71", D("200.000"), in_days(9)),
    ]
    assert debts.cheques_total == D("500.000")


def test_the_api_takes_lines_and_shows_each_effet(organization, supplier, biat):
    invoice = invoice_of(organization, supplier, "900")
    manager = client_for(MembershipFactory.create(organization=organization, role=Role.MANAGER))
    url = reverse("supplier-payment-list")

    created = manager.post(
        url,
        {
            "supplier": supplier.pk,
            "paid_on": TODAY().isoformat(),
            "amount": "900.000",
            "lines": [
                {"method": "cash", "amount": "300"},
                {
                    "method": "bill",
                    "amount": "600",
                    "number": "TR-5",
                    "bank": biat.pk,
                    "due_on": in_days(30).isoformat(),
                },
            ],
            "auto_allocate": True,
        },
        format="json",
    )

    assert created.status_code == 201, created.json()
    body = created.json()
    assert (body["method"], body["amount"], body["unallocated_amount"]) == ("mixed", "900.000", "0.000")
    assert [(row["method"], row["amount"]) for row in body["lines"]] == [("cash", "300.000"), ("bill", "600.000")]
    assert body["lines"][0]["instrument"] is None
    effet = body["lines"][1]["instrument"]
    assert (effet["number"], effet["bank_code"], effet["due_on"], effet["status"]) == (
        "TR-5",
        "BIAT",
        in_days(30).isoformat(),
        "issued",
    )
    assert body["allocations"][0]["invoice"]["id"] == invoice.pk
    assert [row["number"] for row in manager.get(url, {"search": "TR-5"}).json()["results"]] == [body["number"]]

    unknown_bank = manager.post(
        url,
        {
            "supplier": supplier.pk,
            "paid_on": TODAY().isoformat(),
            "lines": [{"method": "cheque", "amount": "10", "number": "1", "bank": 999999}],
        },
        format="json",
    )
    assert unknown_bank.status_code == 400
    assert "lines.0.bank" in unknown_bank.json()
    issued = treasury.instruments_of(organization, direction="issued", statuses=[InstrumentStatus.ISSUED])
    assert [row.number for row in issued] == ["TR-5"]
