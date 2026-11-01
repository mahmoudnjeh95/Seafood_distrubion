"""The bank details of the Agence bancaire and the Caisse liquide (P9-T09a, D-236): the SWIFT code and address of a
bank; the RIB and IBAN of a bank account, each kept once in the organization; the type of a Caisse."""

import pytest
from django.core.exceptions import ValidationError

from apps.core.tests.factories import MembershipFactory
from apps.treasury import services
from apps.treasury.models import AccountKind, CashType, TreasuryAccount

pytestmark = pytest.mark.django_db

RIB = "22222222222222222222"


@pytest.fixture
def organization():
    return MembershipFactory.create().organization


@pytest.fixture
def bank(organization):
    return services.create_bank(organization=organization, actor=None, code="TESTBK", name="Banque de test")


def bank_account(organization, bank, name, **extra):
    return services.create_account(
        organization=organization, actor=None, kind=AccountKind.BANK, name=name, bank=bank, **extra
    )


def test_a_bank_keeps_its_swift_code_and_address(organization):
    bank = services.create_bank(
        organization=organization,
        actor=None,
        code="BIATX",
        name="BIAT",
        swift="biattntt",
        address="  Avenue Majida Boulila,   Sfax ",
    )
    assert bank.swift == "BIATTNTT"
    assert bank.address == "Avenue Majida Boulila, Sfax"


def test_a_swift_code_is_eight_or_eleven_characters(organization):
    with pytest.raises(ValidationError) as excinfo:
        services.create_bank(organization=organization, actor=None, code="BADSW", name="Test", swift="ABC")
    assert "swift" in excinfo.value.message_dict


def test_updating_a_bank_sets_its_swift_code_and_address(organization, bank):
    updated = services.update_bank(
        bank=bank, actor=None, code=bank.code, name=bank.name, is_active=True, swift="ATBKTNTT", address="Sfax"
    )
    assert (updated.swift, updated.address) == ("ATBKTNTT", "Sfax")


def test_a_rib_belongs_to_one_account_only(organization, bank):
    bank_account(organization, bank, "Compte 1", rib=RIB)
    with pytest.raises(ValidationError) as excinfo:
        bank_account(organization, bank, "Compte 2", rib=RIB)
    assert "rib" in excinfo.value.message_dict


def test_an_account_keeps_its_own_rib_when_it_is_saved_again(organization, bank):
    account = bank_account(organization, bank, "Compte 1", rib=RIB)
    saved = services.update_account(
        account=account,
        actor=None,
        name="Compte 1",
        bank=bank,
        rib=RIB,
        opening_balance="0",
        opening_on=None,
        is_active=True,
        is_default=False,
    )
    assert saved.rib == RIB


def test_an_iban_is_checked_and_kept_without_spaces(organization, bank):
    account = bank_account(organization, bank, "Compte IBAN", iban="TN11 TNTN 1111 111")
    assert account.iban == "TN11TNTN1111111"


def test_a_malformed_iban_is_refused(organization, bank):
    with pytest.raises(ValidationError) as excinfo:
        bank_account(organization, bank, "Compte mal saisi", iban="TN1")
    assert "iban" in excinfo.value.message_dict


def test_an_iban_belongs_to_one_account_only(organization, bank):
    bank_account(organization, bank, "Compte A", iban="TN11 TNTN 1111 111")
    with pytest.raises(ValidationError) as excinfo:
        bank_account(organization, bank, "Compte B", iban="TN11TNTN1111111")
    assert "iban" in excinfo.value.message_dict


def test_a_caisse_is_principale_unless_told_otherwise(organization):
    caisse = services.create_account(organization=organization, actor=None, kind=AccountKind.CASH, name="Caisse port")
    assert caisse.cash_type == CashType.PRINCIPAL
    secondary = services.create_account(
        organization=organization,
        actor=None,
        kind=AccountKind.CASH,
        name="Caisse secondaire",
        cash_type=CashType.SECONDARY,
    )
    assert secondary.cash_type == CashType.SECONDARY


def test_a_caisse_type_is_one_of_the_two(organization):
    with pytest.raises(ValidationError) as excinfo:
        services.create_account(
            organization=organization, actor=None, kind=AccountKind.CASH, name="Caisse douteuse", cash_type="autre"
        )
    assert "cash_type" in excinfo.value.message_dict


def test_a_bank_account_has_no_caisse_type(organization, bank):
    account = bank_account(organization, bank, "Compte sans type", cash_type=CashType.SECONDARY)
    assert account.cash_type == ""
    assert TreasuryAccount.objects.get(pk=account.pk).cash_type == ""
