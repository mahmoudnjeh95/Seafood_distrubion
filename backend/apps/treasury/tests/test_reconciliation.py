"""Bank reconciliation (D-265, provisional): the system suggests the movements of our ledger that look like a line of
the bank's statement (same amount, within three days); the office confirms or matches by hand; no balance changes."""

import datetime as dt
from decimal import Decimal
from io import BytesIO

import pytest
from django.core.exceptions import ValidationError
from openpyxl import Workbook

from apps.core.tests.factories import MembershipFactory
from apps.treasury import selectors, services, statements
from apps.treasury.models import AccountKind, BankStatementLine, TreasuryMovement

pytestmark = pytest.mark.django_db

D = Decimal
DAY = dt.date(2026, 11, 2)


@pytest.fixture
def organization():
    return MembershipFactory.create().organization


@pytest.fixture
def account(organization):
    return services.create_account(organization=organization, actor=None, kind=AccountKind.BANK, name="UBCI Sfax")


def move(organization, account, amount, day=DAY, source_id=1):
    return services.post_movement(
        organization=organization,
        account=account,
        day=day,
        amount=D(amount),
        kind="customer_payment",
        label="RG-1",
        source="test.source",
        source_id=source_id,
    )


def line(organization, account, debit=None, credit=None, day=DAY):
    book = Workbook()
    sheet = book.active
    sheet.append(["DATE", "LIBELLE", "DEBIT", "CREDIT"])
    sheet.append([day, "ligne", debit, credit])
    buffer = BytesIO()
    book.save(buffer)
    statements.import_statement(organization=organization, actor=None, account=account, content=buffer.getvalue())
    return BankStatementLine.objects.filter(account=account).latest("id")


def test_a_movement_with_the_same_amount_close_in_date_is_suggested(organization, account):
    near = move(organization, account, "100.000", DAY + dt.timedelta(days=2), source_id=1)
    move(organization, account, "100.000", DAY + dt.timedelta(days=9), source_id=2)
    move(organization, account, "90.000", DAY, source_id=3)
    bank_line = line(organization, account, debit=100)

    assert [(row.pk, suggested) for row, suggested in selectors.match_candidates(bank_line)] == [(near.pk, True)]


def test_a_credit_of_the_bank_is_money_out_of_our_account(organization, account):
    out = move(organization, account, "-44.000")
    move(organization, account, "44.000", source_id=2)
    bank_line = line(organization, account, credit=44)

    assert [row.pk for row, _ in selectors.match_candidates(bank_line)] == [out.pk]


def test_by_hand_every_unmatched_movement_within_a_month_is_offered_suggestions_first(organization, account):
    other = move(organization, account, "55.000", DAY + dt.timedelta(days=20), source_id=1)
    exact = move(organization, account, "100.000", source_id=2)
    bank_line = line(organization, account, debit=100)

    rows = selectors.match_candidates(bank_line, by_hand=True)

    assert [(row.pk, flag) for row, flag in rows] == [(exact.pk, True), (other.pk, False)]


def test_matching_links_the_two_and_changes_no_balance(organization, account):
    movement = move(organization, account, "100.000")
    bank_line = line(organization, account, debit=100)
    before = list(TreasuryMovement.objects.values_list("pk", "amount"))

    matched = statements.match_line(line=bank_line, movement=movement, actor=None)

    assert matched.movement == movement
    assert list(TreasuryMovement.objects.values_list("pk", "amount")) == before
    assert selectors.match_candidates(line(organization, account, debit=100), by_hand=True) == []


def test_a_matched_movement_or_line_cannot_be_matched_again(organization, account):
    movement = move(organization, account, "100.000")
    first = line(organization, account, debit=100)
    second = line(organization, account, debit=100)
    statements.match_line(line=first, movement=movement, actor=None)

    with pytest.raises(ValidationError):
        statements.match_line(line=second, movement=movement, actor=None)
    with pytest.raises(ValidationError):
        statements.match_line(line=first, movement=move(organization, account, "5.000", source_id=9), actor=None)


def test_a_movement_of_another_account_is_refused(organization, account):
    elsewhere = services.create_account(organization=organization, actor=None, kind=AccountKind.BANK, name="BIAT")
    movement = move(organization, elsewhere, "100.000")

    with pytest.raises(ValidationError) as refused:
        statements.match_line(line=line(organization, account, debit=100), movement=movement, actor=None)

    assert "movement" in refused.value.message_dict


def test_a_wrong_match_can_be_undone(organization, account):
    movement = move(organization, account, "100.000")
    bank_line = line(organization, account, debit=100)
    statements.match_line(line=bank_line, movement=movement, actor=None)

    statements.unmatch_line(line=bank_line, actor=None)

    bank_line.refresh_from_db()
    assert bank_line.movement is None
    assert [row.pk for row, _ in selectors.match_candidates(bank_line)] == [movement.pk]
    with pytest.raises(ValidationError):
        statements.unmatch_line(line=bank_line, actor=None)


def test_the_lines_can_be_kept_matched_or_unmatched(organization, account):
    movement = move(organization, account, "100.000")
    done = statements.match_line(line=line(organization, account, debit=100), movement=movement, actor=None)
    open_line = line(organization, account, credit=30)

    def ids(state):
        return [row.pk for row in selectors.statement_lines_of(organization, account, state=state)]

    assert ids("all") == [done.pk, open_line.pk]
    assert ids("matched") == [done.pk]
    assert ids("unmatched") == [open_line.pk]


def test_the_summary_shows_both_sides_of_what_is_left_to_match(organization, account):
    movement = move(organization, account, "100.000", source_id=1)
    statements.match_line(line=line(organization, account, debit=100), movement=movement, actor=None)
    line(organization, account, debit=40)
    line(organization, account, credit=25)
    ours_in = move(organization, account, "70.000", source_id=2)
    ours_out = move(organization, account, "-15.000", source_id=3)

    summary = selectors.reconciliation_summary(organization, account)

    assert (summary.lines, summary.matched, summary.unmatched) == (3, 1, 2)
    assert (summary.unmatched_in, summary.unmatched_out) == (D("40.000"), D("25.000"))
    assert [row.pk for row in summary.movements] == [ours_in.pk, ours_out.pk]
    assert summary.movements_total == D("55.000")


def test_the_summary_keeps_to_the_period(organization, account):
    line(organization, account, debit=40, day=DAY - dt.timedelta(days=40))
    move(organization, account, "70.000", DAY - dt.timedelta(days=40), source_id=2)
    inside = move(organization, account, "5.000", DAY, source_id=3)

    summary = selectors.reconciliation_summary(organization, account, date_from=DAY - dt.timedelta(days=5))

    assert (summary.lines, summary.unmatched) == (0, 0)
    assert [row.pk for row in summary.movements] == [inside.pk]
