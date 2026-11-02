"""The bank's statement imported from Excel (P9-T09d, D-253): the lines are a copy of the bank's file; a line takes a
customer (debit) or a supplier (credit); nothing here moves money."""

import datetime as dt
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from openpyxl import Workbook

from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import CustomerFactory, SupplierFactory
from apps.treasury import services, statements
from apps.treasury.models import AccountKind, BankStatementLine, TreasuryMovement

pytestmark = pytest.mark.django_db

HEADER = ("DATE", "LIBELLE  STE LOGISTICA SHIPPING", "DEBIT", "CREDIT", "SOLDE")


def workbook(rows, header=HEADER):
    book = Workbook()
    sheet = book.active
    sheet.append(list(header))
    for row in rows:
        sheet.append(list(row))
    buffer = BytesIO()
    book.save(buffer)
    return buffer.getvalue()


@pytest.fixture
def organization():
    return MembershipFactory.create().organization


@pytest.fixture
def account(organization):
    return services.create_account(organization=organization, actor=None, kind=AccountKind.BANK, name="UBCI Sfax")


def bring(organization, account, content):
    return statements.import_statement(organization=organization, actor=None, account=account, content=content)


def test_dates_as_excel_dates_or_french_text_and_amounts_with_a_comma_are_read(organization, account):
    content = workbook(
        [
            (dt.date(2024, 1, 3), "remise cheque", Decimal("0.033"), None, None),
            ("04-janv-24", "taxes sur commission", None, "44,000", "10 100,990"),
            ("05/01/2024", "virement emis", 2026.638, 0, None),
        ]
    )

    report = bring(organization, account, content)

    assert (report.created, report.skipped, report.errors) == (3, 0, [])
    lines = list(BankStatementLine.objects.filter(account=account).order_by("day"))
    assert [line.day for line in lines] == [dt.date(2024, 1, 3), dt.date(2024, 1, 4), dt.date(2024, 1, 5)]
    assert lines[0].debit == Decimal("0.033")
    assert (lines[1].credit, lines[1].balance) == (Decimal("44.000"), Decimal("10100.990"))
    assert lines[2].debit == Decimal("2026.638")


def test_sending_the_same_file_twice_adds_nothing(organization, account):
    content = workbook([("03-janv-24", "remise cheque", 100, None, None)])
    bring(organization, account, content)

    again = bring(organization, account, content)

    assert (again.created, again.skipped) == (0, 1)
    assert BankStatementLine.objects.filter(account=account).count() == 1


def test_two_identical_lines_inside_one_new_file_are_both_kept(organization, account):
    row = ("03-janv-24", "frais", None, 5, None)

    report = bring(organization, account, workbook([row, row]))

    assert report.created == 2


def test_one_unreadable_row_saves_nothing_and_is_listed_with_its_row_number(organization, account):
    content = workbook(
        [
            ("03-janv-24", "remise cheque", 100, None, None),
            ("pas une date", "ligne cassée", 5, None, None),
        ]
    )

    report = bring(organization, account, content)

    assert report.created == 0
    assert [error.number for error in report.errors] == [3]
    assert not BankStatementLine.objects.filter(account=account).exists()


def test_a_missing_column_or_a_file_that_is_not_excel_is_refused(organization, account):
    with pytest.raises(ValidationError) as missing:
        bring(
            organization, account, workbook([("03-janv-24", "x", 1, 2)], header=("DATE", "LIBELLE", "DEBIT", "SOLDE"))
        )
    assert "file" in missing.value.message_dict
    with pytest.raises(ValidationError) as not_excel:
        bring(organization, account, b"ceci n'est pas un classeur")
    assert "file" in not_excel.value.message_dict


def test_a_statement_is_imported_on_a_bank_account_only(organization):
    caisse = services.create_account(organization=organization, actor=None, kind=AccountKind.CASH, name="Caisse test")

    with pytest.raises(ValidationError) as refused:
        bring(organization, caisse, workbook([("03-janv-24", "x", 1, None, None)]))

    assert "account" in refused.value.message_dict


def test_the_import_moves_no_money(organization, account):
    bring(organization, account, workbook([("03-janv-24", "remise cheque", 100, None, None)]))

    assert not TreasuryMovement.objects.filter(organization=organization).exists()


def test_a_customer_goes_on_a_debit_line_and_a_supplier_on_a_credit_line(organization, account):
    bring(
        organization,
        account,
        workbook([("03-janv-24", "remise", 100, None, None), ("04-janv-24", "paiement", None, 50, None)]),
    )
    debit, credit = BankStatementLine.objects.filter(account=account).order_by("day")
    customer = CustomerFactory.create(organization=organization)
    supplier = SupplierFactory.create(organization=organization)

    statements.set_line_party(line=debit, actor=None, customer=customer, supplier=None)
    statements.set_line_party(line=credit, actor=None, customer=None, supplier=supplier)

    debit.refresh_from_db()
    credit.refresh_from_db()
    assert (debit.customer, credit.supplier) == (customer, supplier)
    with pytest.raises(ValidationError):
        statements.set_line_party(line=credit, actor=None, customer=customer, supplier=None)
    with pytest.raises(ValidationError):
        statements.set_line_party(line=debit, actor=None, customer=None, supplier=supplier)
    with pytest.raises(ValidationError):
        statements.set_line_party(line=debit, actor=None, customer=customer, supplier=supplier)


def test_a_line_can_be_taken_off(organization, account):
    bring(organization, account, workbook([("03-janv-24", "remise", 100, None, None)]))
    line = BankStatementLine.objects.get(account=account)

    statements.delete_line(line=line, actor=None)

    assert not BankStatementLine.objects.filter(account=account).exists()
