import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.core.models import AuditLog
from apps.expenses import cost_selectors, selectors, services
from apps.expenses.costing import (
    add_months,
    allocate_general_days,
    days_in_month,
    first_of_month,
    general_day_amounts,
    month_days,
    spread_over_months,
)
from apps.expenses.models import ExpenseStatus

from .conftest import category
from .test_cold_room_cost import put, whole_days

pytestmark = pytest.mark.django_db

D = Decimal


def general_lines(organization, batch):
    return [line for line in selectors.lot_cost_lines(organization, batch_id=batch.pk) if line.kind == "general"]


def current_month():
    return first_of_month(timezone.localdate())


def days_so_far():
    return (timezone.localdate() - current_month()).days + 1


def today_so_far():
    """The part of today that has passed, in days: 0 at midnight, 1 at the end of the day."""
    now = timezone.localtime()
    midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
    return D(str((now - midnight).total_seconds() / 86400))


def elapsed_days():
    """Days of this month up to now, the last one part-way through: a lot in stock from midnight is charged
    by the hour, so today counts only the hours that have come (D-142)."""
    return D((timezone.localdate() - current_month()).days) + today_so_far()


def assert_charged(amount, per_day, before, after):
    """`amount` is `per_day` for each day passed, read between `before` and `after` (the clock moves during the
    call). The margin is a millime per hour passed: each hour's share is rounded to the millime per lot."""
    margin = D("0.001") * (after * 24 + 1)
    assert per_day * before - margin <= amount <= per_day * after + margin


# ---- pure functions ----


def test_a_month_is_spread_over_its_calendar_days_to_the_millime():
    september = general_day_amounts(D("260.000"), dt.date(2026, 9, 1))
    assert len(september) == 30
    assert sum(september.values()) == D("260.000")  # a lot in stock all month carries the bill once
    assert set(september.values()) <= {D("8.666"), D("8.667")}
    february = general_day_amounts(D("280.000"), dt.date(2026, 2, 1))
    assert set(february.values()) == {D("10.000")}


def test_a_bill_over_several_months_is_spread_exactly():
    parts = spread_over_months(D("1000.000"), 12)
    assert sum(parts) == D("1000.000")
    assert sorted(set(parts)) == [D("83.333"), D("83.334")]
    assert spread_over_months(D("90.000"), 1) == [D("90.000")]


def test_each_days_general_cost_is_shared_over_the_lots_in_stock_that_day():
    month = dt.date(2026, 9, 1)
    days = month_days(month)
    held = whole_days(days[:10], {1: D("75.000"), 2: D("25.000")})
    charged = sum(general_day_amounts(D("260.000"), month)[day] for day in days[:10])
    charges = allocate_general_days(D("260.000"), month, days, held)
    assert charges[1].amount + charges[2].amount == charged  # the 10 days' shares
    assert abs(charges[1].amount - charged * D("0.75")) <= D("0.050")  # hour by hour, to the millime
    assert charges[2].kg_days == D("250.000")
    assert allocate_general_days(D("260.000"), month, days, {}) == {}


# ---- templates ----


def test_a_template_generates_the_months_expense_once(organization, actor):
    rent = category(organization, "rent")
    cost = services.create_recurring_cost(
        organization=organization,
        actor=actor,
        name="Loyer",
        category=rent,
        monthly_amount="1300.000",
        start_month=add_months(current_month(), -2),
    )
    created = services.generate_recurring_costs(organization=organization, actor=actor, month=current_month())
    assert len(created) == 1
    expense = created[0].expense
    assert (expense.status, expense.amount, expense.spent_on, expense.description) == (
        ExpenseStatus.DRAFT,
        D("1300.000"),
        current_month(),
        "Loyer",
    )
    assert services.generate_recurring_costs(organization=organization, actor=actor, month=current_month()) == []

    stopped = services.update_recurring_cost(
        cost=cost,
        actor=actor,
        name="Loyer",
        category=rent,
        monthly_amount="1400",
        start_month=cost.start_month,
        is_active=False,
    )
    assert (
        services.generate_recurring_costs(organization=organization, actor=actor, month=add_months(current_month(), -1))
        == []
    )
    assert stopped.monthly_amount == D("1400.000")
    with pytest.raises(ValidationError):
        services.generate_recurring_costs(organization=organization, actor=actor, month=add_months(current_month(), 1))


def recurring(organization, actor, rent, **fields):
    values = {"name": "Loyer", "category": rent, "monthly_amount": "1300.000", "start_month": current_month()}
    return services.create_recurring_cost(organization=organization, actor=actor, **{**values, **fields})


def test_a_template_with_an_archived_category_is_skipped_and_reported_not_a_failure(organization, actor):
    own = services.create_category(organization=organization, actor=actor, name="Gardiennage")
    recurring(organization, actor, own, name="Gardien")
    recurring(organization, actor, category(organization, "rent"))
    services.update_category(category=own, actor=actor, is_active=False)

    created = services.generate_recurring_costs(organization=organization, actor=actor, month=current_month())

    assert [period.expense.description for period in created] == ["Loyer"]
    skipped = AuditLog.objects.get(action="recurring_cost.skipped")
    assert skipped.after is not None
    assert skipped.after["archived_category"] == ["Gardien"]


def test_a_refused_month_of_a_template_is_generated_again(organization, actor):
    recurring(organization, actor, category(organization, "rent"))
    [first] = services.generate_recurring_costs(organization=organization, actor=actor, month=current_month())
    services.reject_expense(expense=first.expense, actor=actor, reason="Erreur de saisie")

    [second] = services.generate_recurring_costs(organization=organization, actor=actor, month=current_month())

    assert second.expense_id != first.expense_id
    assert second.expense.status == ExpenseStatus.DRAFT
    first.expense.refresh_from_db()
    assert first.expense.status == ExpenseStatus.REJECTED  # the refusal stays as a trace
    assert services.generate_recurring_costs(organization=organization, actor=actor, month=current_month()) == []


def test_generating_locks_the_organization_so_two_runs_cannot_both_create_a_month(organization, actor):
    recurring(organization, actor, category(organization, "rent"))

    with CaptureQueriesContext(connection) as queries:
        services.generate_recurring_costs(organization=organization, actor=actor, month=current_month())

    assert any("FOR UPDATE" in query["sql"] and "core_organization" in query["sql"] for query in queries)


def test_a_template_respects_its_first_and_last_month(organization, actor):
    rent = category(organization, "rent")
    services.create_recurring_cost(
        organization=organization,
        actor=actor,
        name="Assurance",
        category=rent,
        monthly_amount="50",
        start_month=add_months(current_month(), -1),
        end_month=add_months(current_month(), -1),
    )
    assert (
        services.generate_recurring_costs(organization=organization, actor=actor, month=add_months(current_month(), -2))
        == []
    )
    assert services.generate_recurring_costs(organization=organization, actor=actor, month=current_month()) == []
    assert (
        len(
            services.generate_recurring_costs(
                organization=organization, actor=actor, month=add_months(current_month(), -1), approve=True
            )
        )
        == 1
    )


def test_template_validation(organization, actor):
    day_labour = category(organization, "day_labour")
    rent = category(organization, "rent")
    with pytest.raises(ValidationError):
        services.create_recurring_cost(
            organization=organization,
            actor=actor,
            name="X",
            category=day_labour,
            monthly_amount="5",
            start_month=current_month(),
        )
    with pytest.raises(ValidationError):
        services.create_recurring_cost(
            organization=organization,
            actor=actor,
            name="X",
            category=rent,
            monthly_amount="0",
            start_month=current_month(),
        )
    with pytest.raises(ValidationError):
        services.create_recurring_cost(
            organization=organization,
            actor=actor,
            name="X",
            category=rent,
            monthly_amount="5",
            start_month=current_month() + dt.timedelta(days=1),
        )


# ---- cost on lots ----


def test_rent_is_spread_over_the_days_of_the_month_by_kg(organization, actor, cold_room):
    rent = category(organization, "rent")
    services.create_recurring_cost(
        organization=organization,
        actor=actor,
        name="Loyer",
        category=rent,
        monthly_amount="260.000",
        start_month=current_month(),
    )
    big = put(organization, "Dorade", "300", cold_room, current_month() - dt.timedelta(days=40))
    small = put(organization, "Loup", "100", cold_room, current_month() - dt.timedelta(days=40))

    [period] = services.generate_recurring_costs(organization=organization, actor=actor, month=current_month())
    assert general_lines(organization, big) == []  # a draft counts for nothing
    services.approve_expense(expense=period.expense, actor=actor)

    before = elapsed_days()
    [line_big] = general_lines(organization, big)
    [line_small] = general_lines(organization, small)
    after = elapsed_days()
    per_day = D("260.000") / days_in_month(current_month())
    assert_charged(line_big.amount + line_small.amount, per_day, before, after)
    assert_charged(line_big.amount, per_day * D("0.75"), before, after)
    assert (line_big.month, line_big.expense_number, line_big.category_code) == (
        current_month(),
        period.expense.number,
        "rent",
    )
    assert_charged(line_big.quantity, D("300.000"), before, after)
    # It joins the other costs of the lot and its total.
    assert selectors.lot_cost_total(selectors.lot_cost_lines(organization, batch_id=big.pk)) == line_big.amount


def test_only_the_hours_a_lot_is_in_stock_are_charged(organization, actor, cold_room):
    rent = category(organization, "rent")
    services.create_recurring_cost(
        organization=organization,
        actor=actor,
        name="Loyer",
        category=rent,
        monthly_amount="260.000",
        start_month=current_month(),
    )
    [period] = services.generate_recurring_costs(
        organization=organization, actor=actor, month=current_month(), approve=True
    )
    assert period.expense.status == ExpenseStatus.APPROVED
    lot = put(organization, "Dorade", "10", cold_room, timezone.localdate())  # arrived at midnight today
    before = today_so_far()
    [line] = general_lines(organization, lot)
    after = today_so_far()
    assert_charged(line.amount, D("260.000") / days_in_month(current_month()), before, after)  # today's hours so far


def test_a_bill_over_several_months_is_spread_over_them(organization, actor, cold_room):
    insurance = category(organization, "administration")
    start = add_months(current_month(), -1)
    period = services.create_general_cost(
        organization=organization,
        actor=actor,
        spent_on=start,
        category=insurance,
        amount="780.000",
        first_month=start,
        months=3,
        description="Assurance trimestrielle",
        approve=True,
    )
    lot = put(organization, "Dorade", "100", cold_room, start - dt.timedelta(days=5))
    before = elapsed_days()
    lines = general_lines(organization, lot)
    after = elapsed_days()
    assert [line.month for line in lines] == [start, current_month()]  # next month has not come yet
    assert lines[0].amount == D("260.000")  # the whole third of the bill, every day of that month in stock
    assert_charged(lines[1].amount, D("260.000") / days_in_month(current_month()), before, after)
    assert lines[0].description == "Assurance trimestrielle"
    assert cost_selectors.general_periods_of(organization, month=add_months(start, 2)).count() == 1
    assert cost_selectors.general_periods_of(organization, month=add_months(start, 3)).count() == 0
    assert period.months == 3


def test_a_general_cost_draft_is_deleted_through_its_own_record(organization, actor):
    draft = services.create_general_cost(
        organization=organization,
        actor=actor,
        spent_on=timezone.localdate(),
        category=category(organization, "rent"),
        amount="100",
        first_month=current_month(),
    )
    with pytest.raises(ValidationError):
        services.delete_expense(expense=draft.expense, actor=actor)
    services.delete_general_cost(period=draft, actor=actor)
    assert not cost_selectors.general_periods_of(organization).exists()
    with pytest.raises(ValidationError):
        services.create_general_cost(
            organization=organization,
            actor=actor,
            spent_on=timezone.localdate(),
            category=category(organization, "rent"),
            amount="100",
            first_month=current_month(),
            months=61,
        )


def test_changing_a_template_updates_its_months_not_yet_approved(organization, actor):
    rent = category(organization, "rent")
    cost = recurring(organization, actor, rent)
    last_month = add_months(current_month(), -1)
    services.update_recurring_cost(
        cost=cost, actor=actor, name="Loyer", category=rent, monthly_amount="1300", start_month=last_month
    )
    [approved] = services.generate_recurring_costs(
        organization=organization, actor=actor, month=last_month, approve=True
    )
    [draft] = services.generate_recurring_costs(organization=organization, actor=actor, month=current_month())

    services.update_recurring_cost(
        cost=cost,
        actor=actor,
        name="Loyer dépôt",
        category=rent,
        monthly_amount="1450",
        start_month=last_month,
        payee="M. Ben Ali",
    )

    draft.expense.refresh_from_db()
    approved.expense.refresh_from_db()
    assert (draft.expense.amount, draft.expense.description, draft.expense.payee) == (
        D("1450.000"),
        "Loyer dépôt",
        "M. Ben Ali",
    )
    assert draft.expense.status == ExpenseStatus.DRAFT
    # An approved month never changes: a correction is a new expense.
    assert (approved.expense.amount, approved.expense.description) == (D("1300.000"), "Loyer")
