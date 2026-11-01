"""Our accounts and their movements (P9-T05a, D-219): the règlements and the effets move money in the Caisse, the bank
accounts and the drivers' cash; versements, retraits and virements; the arrêté de caisse; the backfill."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.urls import reverse
from django.utils import timezone
from rest_framework.test import APIClient

from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import CustomerFactory, SupplierFactory
from apps.purchasing import services as purchasing
from apps.sales import services as sales
from apps.treasury import selectors, services
from apps.treasury.models import AccountKind, Instrument, TreasuryAccount, TreasuryMovement

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
def customer(organization):
    return CustomerFactory.create(organization=organization, name="Restaurant La Sirène")


@pytest.fixture
def supplier(organization):
    return SupplierFactory.create(organization=organization, name="Mareyeur Port de Sfax")


def caisse(organization):
    return services.default_account(organization, AccountKind.CASH)


def main_bank(organization):
    return services.default_account(organization, AccountKind.BANK)


def balance(organization, account):
    return getattr(selectors.account_of(organization, account.pk), "balance")  # noqa: B009


def biat_account(organization, actor):
    return services.create_account(
        organization=organization,
        actor=actor,
        kind=AccountKind.BANK,
        name="BIAT Sakiet Ezzit",
        bank=selectors.banks_of(organization).get(code="BIAT"),
        rib="08 006 0123456789012 34",
        opening_balance="1000",
    )


def test_every_organization_starts_with_a_caisse_and_a_bank_account(organization):
    accounts = [
        (row.kind, row.name, row.is_default, balance(organization, row)) for row in selectors.accounts_of(organization)
    ]
    assert accounts == [
        ("cash", "Caisse", True, D("0.000")),
        ("bank", "Banque principale", True, D("0.000")),
    ]


def test_a_customer_payment_puts_its_cash_and_transfer_in_the_accounts_and_a_void_takes_it_back(
    organization, manager, customer
):
    actor = manager.user
    biat = biat_account(organization, actor)
    payment = sales.record_customer_payment(
        organization=organization,
        actor=actor,
        customer=customer,
        lines=[
            {"method": "cash", "amount": "300"},
            {"method": "transfer", "amount": "700", "reference": "VIR-12", "account": biat},
            {
                "method": "cheque",
                "amount": "500",
                "number": "9001",
                "bank": selectors.banks_of(organization).get(code="STB"),
            },
        ],
        allocations=[],
    )

    assert balance(organization, caisse(organization)) == D("300.000")
    assert balance(organization, biat) == D("1700.000")
    # The cheque waits in the portfolio: no money yet.
    assert balance(organization, main_bank(organization)) == D("0.000")

    sales.void_customer_payment(payment=payment, actor=actor, reason="Erreur de saisie")

    assert balance(organization, caisse(organization)) == D("0.000")
    assert balance(organization, biat) == D("1000.000")
    statement = selectors.account_statement(biat)
    assert [(row.movement.amount, row.balance) for row in statement.rows] == [
        (D("700.000"), D("1700.000")),
        (D("-700.000"), D("1000.000")),
    ]
    assert statement.rows[1].movement.label.startswith("Annulation · ")
    assert (statement.opening, statement.total_in, statement.total_out, statement.closing) == (
        D("1000.000"),
        D("700.000"),
        D("700.000"),
        D("1000.000"),
    )


def test_cash_goes_to_a_caisse_and_the_rest_to_a_bank_account(organization, manager, customer):
    with pytest.raises(ValidationError) as refused:
        sales.record_customer_payment(
            organization=organization,
            actor=manager.user,
            customer=customer,
            lines=[{"method": "cash", "amount": "50", "account": main_bank(organization)}],
        )
    assert "lines.0.account" in refused.value.message_dict


def test_the_cash_a_driver_takes_goes_to_the_driver_s_cash(organization, customer):
    driver = MembershipFactory.create(organization=organization, role=Role.DRIVER).user
    sales.record_customer_payment(
        organization=organization,
        actor=driver,
        customer=customer,
        amount="120.000",
        method="cash",
        made_at=timezone.now(),
    )

    account = TreasuryAccount.objects.get(organization=organization, driver=driver)
    assert account.kind == AccountKind.DRIVER
    assert balance(organization, account) == D("120.000")
    assert balance(organization, caisse(organization)) == D("0.000")


def test_a_supplier_payment_takes_its_cash_out_and_our_cheque_when_the_bank_debits_it(organization, manager, supplier):
    actor = manager.user
    biat = biat_account(organization, actor)
    payment = purchasing.record_payment(
        organization=organization,
        actor=actor,
        supplier=supplier,
        paid_on=TODAY(),
        lines=[
            {"method": "cash", "amount": "200"},
            {
                "method": "cheque",
                "amount": "450",
                "number": "C-77",
                "bank": selectors.banks_of(organization).get(code="BIAT"),
                "account": biat,
            },
        ],
    )
    assert balance(organization, caisse(organization)) == D("-200.000")
    assert balance(organization, biat) == D("1000.000")

    cheque = Instrument.objects.get(number="C-77")
    assert cheque.account == biat
    services.debit_instruments(organization=organization, actor=actor, instrument_ids=[cheque.pk], debited_on=TODAY())
    assert balance(organization, biat) == D("550.000")

    with pytest.raises(ValidationError):
        purchasing.void_payment(payment=payment, actor=actor, reason="erreur")


def test_effets_move_money_when_the_bank_pays_or_takes_back(organization, manager, customer):
    actor = manager.user
    biat = biat_account(organization, actor)
    stb = selectors.banks_of(organization).get(code="STB")
    sales.record_customer_payment(
        organization=organization,
        actor=actor,
        customer=customer,
        lines=[
            {"method": "cheque", "amount": "400", "number": "1", "bank": stb},
            {"method": "cheque", "amount": "250", "number": "2", "bank": stb},
        ],
        allocations=[],
    )
    first, second = Instrument.objects.order_by("number")
    deposit = services.deposit_instruments(
        organization=organization, actor=actor, instrument_ids=[first.pk], bank=None, deposited_on=TODAY(), account=biat
    )
    assert (deposit.account, deposit.bank.code) == (biat, "BIAT")

    services.cash_instruments(organization=organization, actor=actor, instrument_ids=[first.pk], cashed_on=TODAY())
    assert balance(organization, biat) == D("1400.000")
    # Cashed at the drawer's bank counter: notes, in the Caisse.
    services.cash_instruments(organization=organization, actor=actor, instrument_ids=[second.pk], cashed_on=TODAY())
    assert balance(organization, caisse(organization)) == D("250.000")

    sales.record_unpaid_effet(
        organization=organization,
        actor=actor,
        instrument_id=first.pk,
        unpaid_on=TODAY(),
        reason="Sans provision",
        bank_charges="0",
    )
    assert balance(organization, biat) == D("1000.000")
    assert selectors.account_statement(biat).rows[-1].movement.kind == "effet_unpaid"


def test_versement_retrait_and_their_void(organization, manager):
    actor = manager.user
    biat = biat_account(organization, actor)
    with pytest.raises(ValidationError) as refused:
        services.transfer_between(
            organization=organization,
            actor=actor,
            from_account=biat,
            to_account=biat,
            amount="0",
            transferred_on=TODAY() + dt.timedelta(days=1),
        )
    assert set(refused.value.message_dict) == {"to_account", "amount", "transferred_on"}

    versement = services.transfer_between(
        organization=organization,
        actor=actor,
        from_account=caisse(organization),
        to_account=biat,
        amount="600",
        transferred_on=TODAY(),
        reference="BV-551",
    )
    retrait = services.transfer_between(
        organization=organization,
        actor=actor,
        from_account=biat,
        to_account=caisse(organization),
        amount="100",
        transferred_on=TODAY(),
    )

    assert (versement.number, versement.kind, retrait.kind) == (
        f"MT-{TODAY().year}-0001",
        "cash_deposit",
        "withdrawal",
    )
    assert balance(organization, caisse(organization)) == D("-500.000")
    assert balance(organization, biat) == D("1500.000")

    services.void_transfer(transfer=versement, actor=actor, reason="Doublon")
    assert balance(organization, caisse(organization)) == D("100.000")
    assert balance(organization, biat) == D("900.000")
    with pytest.raises(ValidationError):
        services.void_transfer(transfer=versement, actor=actor, reason="encore")
    assert AuditLog.objects.filter(action="treasury.transfer_voided").count() == 1


def test_the_cash_count_writes_the_gap_with_its_reason(organization, manager, customer):
    actor = manager.user
    sales.record_customer_payment(
        organization=organization,
        actor=actor,
        customer=customer,
        amount="500.000",
        method="cash",
        received_on=TODAY(),
    )
    with pytest.raises(ValidationError) as refused:
        services.count_cash(
            organization=organization, actor=actor, account=caisse(organization), counted_on=TODAY(), counted="480"
        )
    assert "reason" in refused.value.message_dict

    count = services.count_cash(
        organization=organization,
        actor=actor,
        account=caisse(organization),
        counted_on=TODAY(),
        counted="480",
        reason="Monnaie rendue en trop",
    )

    assert (count.expected, count.counted, count.gap) == (D("500.000"), D("480.000"), D("-20.000"))
    assert balance(organization, caisse(organization)) == D("480.000")
    # Counted again, it matches: no reason needed, no movement.
    again = services.count_cash(
        organization=organization, actor=actor, account=caisse(organization), counted_on=TODAY(), counted="480"
    )
    assert again.gap == D("0.000")
    assert TreasuryMovement.objects.filter(kind="count_gap").count() == 1
    with pytest.raises(ValidationError):
        services.count_cash(
            organization=organization, actor=actor, account=main_bank(organization), counted_on=TODAY(), counted="1"
        )


def test_the_opening_day_leaves_older_movements_out_of_the_balance(organization, manager, customer):
    actor = manager.user
    sales.record_customer_payment(
        organization=organization,
        actor=actor,
        customer=customer,
        amount="90.000",
        method="cash",
        received_on=TODAY() - dt.timedelta(days=3),
    )
    account = caisse(organization)
    services.update_account(
        account=account,
        actor=actor,
        name="Caisse magasin",
        bank=None,
        rib="",
        opening_balance="1500.250",
        opening_on=TODAY() - dt.timedelta(days=1),
        is_active=True,
        is_default=True,
    )
    assert balance(organization, account) == D("1500.250")
    with pytest.raises(ValidationError):
        services.update_account(
            account=account,
            actor=actor,
            name="Caisse magasin",
            bank=None,
            rib="",
            opening_balance="0",
            opening_on=None,
            is_active=False,
            is_default=True,
        )


def test_the_backfill_writes_the_history_once(organization, manager, customer, supplier):
    actor = manager.user
    payment = sales.record_customer_payment(
        organization=organization, actor=actor, customer=customer, amount="80.000", method="cash", allocations=[]
    )
    sales.void_customer_payment(payment=payment, actor=actor, reason="erreur")
    sales.record_customer_payment(
        organization=organization, actor=actor, customer=customer, amount="300.000", method="transfer", allocations=[]
    )
    purchasing.record_payment(
        organization=organization, actor=actor, supplier=supplier, paid_on=TODAY(), amount="40.000", method="cash"
    )
    # As before the accounts existed.
    TreasuryMovement.objects.all().delete()

    call_command("backfill_treasury")
    call_command("backfill_treasury")

    assert TreasuryMovement.objects.count() == 4
    assert balance(organization, caisse(organization)) == D("-40.000")
    assert balance(organization, main_bank(organization)) == D("300.000")


def test_the_api_lists_accounts_statements_and_writes_for_the_office(organization, manager, customer):
    api = APIClient()
    api.force_authenticate(manager.user)
    created = api.post(
        reverse("treasury-account-list"),
        {"kind": "bank", "name": "STB Sfax", "rib": "123", "opening_balance": "-250.000"},
        format="json",
    )
    assert created.status_code == 400
    assert "rib" in created.json()
    created = api.post(
        reverse("treasury-account-list"),
        {"kind": "bank", "name": "STB Sfax", "rib": "10 000 0000000000000 00", "opening_balance": "-250.000"},
        format="json",
    )
    assert created.status_code == 201, created.json()
    assert (created.json()["rib"], created.json()["balance"]) == ("10000000000000000000", "-250.000")

    sales.record_customer_payment(
        organization=organization, actor=manager.user, customer=customer, amount="75.500", method="cash"
    )
    accounts = api.get(reverse("treasury-account-list")).json()
    assert [row["balance"] for row in accounts] == ["75.500", "0.000", "-250.000"]
    statement = api.get(reverse("treasury-account-movements", args=[accounts[0]["id"]])).json()
    assert [(row["amount"], row["balance"], row["kind"]) for row in statement["rows"]] == [
        ("75.500", "75.500", "customer_payment")
    ]
    assert statement["rows"][0]["description"].endswith("Restaurant La Sirène")
    export = api.get(reverse("treasury-account-movements-export", args=[accounts[0]["id"]]))
    assert export.status_code == 200
    assert export["Content-Type"].startswith("application/vnd.openxmlformats")

    moved = api.post(
        reverse("treasury-transfer-list"),
        {
            "from_account": accounts[0]["id"],
            "to_account": created.json()["id"],
            "amount": "50",
            "transferred_on": TODAY().isoformat(),
        },
        format="json",
    )
    assert moved.status_code == 201, moved.json()
    assert moved.json()["kind"] == "cash_deposit"
    counted = api.post(
        reverse("treasury-cash-count-list"),
        {"account": accounts[0]["id"], "counted_on": TODAY().isoformat(), "counted": "25.500"},
        format="json",
    )
    assert counted.status_code == 201, counted.json()

    accountant = APIClient()
    accountant.force_authenticate(MembershipFactory.create(organization=organization, role=Role.ACCOUNTANT).user)
    assert accountant.get(reverse("treasury-account-list")).status_code == 200
    assert accountant.post(reverse("treasury-account-list"), {"name": "X"}, format="json").status_code == 403
