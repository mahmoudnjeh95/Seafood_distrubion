import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.core.models import AuditLog
from apps.expenses import cost_selectors, selectors, services
from apps.expenses.allocation import split_by_weight
from apps.expenses.costing import (
    add_months,
    allocate_room_days,
    days_in_month,
    estimate_day_amount,
    first_of_month,
    month_days,
    room_day_amounts,
    room_month_amounts,
    split_evenly,
)
from apps.expenses.models import ExpenseStatus, LotCostAdjustment
from apps.inventory import selectors as inventory
from apps.inventory import services as inventory_services
from apps.inventory.models import MovementKind
from apps.inventory.tests.factories import BatchFactory, StockLocationFactory

pytestmark = pytest.mark.django_db

D = Decimal


def at(day: dt.date) -> dt.datetime:
    """Midnight: a lot moved on `day` is in the room from the start of that day (charged by the hour, D-142)."""
    return timezone.make_aware(dt.datetime.combine(day, dt.time.min))


def whole_days(days, kg):
    """The lots of `kg` held through every hour of each day, as `inventory.held_slices_by_hour` gives them."""
    return {day: {hour: [(3600, kg)] for hour in range(24)} for day in days}


def put(organization, name, kg, room, day):
    """A lot of `kg` of a new product received into `room` on `day`."""
    product = ProductFactory.create(organization=organization, name=name)
    batch = BatchFactory.create(organization=organization, product=product, received_on=day)
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity=kg,
        to_location=room,
        occurred_at=at(day),
    )
    return batch


def move(organization, batch, kg, source, target, day):
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.TRANSFER,
        batch=batch,
        quantity=kg,
        from_location=source,
        to_location=target,
        occurred_at=at(day),
    )


def months():
    """Three finished months and the current one: (m0, m1, m2, m3)."""
    m3 = first_of_month(timezone.localdate())
    return add_months(m3, -3), add_months(m3, -2), add_months(m3, -1), m3


def bill(organization, actor, month, amount, **fields):
    return services.create_electricity_bill(
        organization=organization, actor=actor, month=month, amount=amount, **fields
    )


def lines_of(organization, batch, kind=None):
    lines = selectors.lot_cost_lines(organization, batch_id=batch.pk)
    return [line for line in lines if kind is None or line.kind == kind]


@pytest.fixture
def room_two(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide -20")


# ---- pure functions ----


def test_the_bill_is_shared_between_rooms_by_weight_and_adds_up_to_the_millime():
    weights = {1: D("1.000"), 2: D("1.000"), 3: D("1.000")}
    parts = room_month_amounts(D("100.000"), weights)
    assert sum(parts.values()) == D("100.000")
    assert sorted(parts.values()) == [D("33.333"), D("33.333"), D("33.334")]

    heavy = room_month_amounts(D("1000.000"), {1: D("1.000"), 2: D("2.500")})
    assert heavy == {1: D("285.714"), 2: D("714.286")}


@pytest.mark.parametrize("amount", ["0.001", "1.000", "100.000", "1234.567", "99999.999"])
@pytest.mark.parametrize("month", [dt.date(2026, 2, 1), dt.date(2026, 9, 1), dt.date(2026, 10, 1)])
def test_a_rooms_month_is_spread_over_the_days_exactly(amount, month):
    days = room_day_amounts(D(amount), month)
    assert len(days) == days_in_month(month)
    assert sum(days.values()) == D(amount)
    assert max(days.values()) - min(days.values()) <= D("0.001")
    assert split_evenly(D(amount), 7)
    assert sum(split_evenly(D(amount), 7)) == D(amount)


def test_a_days_cost_is_shared_over_the_lots_by_kg_and_every_day_adds_up():
    month = dt.date(2026, 9, 1)
    days = room_day_amounts(D("100.000"), month)
    held = whole_days(month_days(month), {1: D("30.500"), 2: D("12.250"), 3: D("7.001")})
    charges = allocate_room_days(days, held)
    assert sum(charge.amount for charge in charges.values()) == D("100.000")
    assert charges[1].kg_days == D("30.500") * 30
    # Empty hours: that time is charged to nobody. One hour of stock takes that hour's part of the day.
    sparse = allocate_room_days(days, {dt.date(2026, 9, 1): {5: [(3600, {1: D("5.000")})]}})
    assert sparse[1].amount == split_evenly(days[dt.date(2026, 9, 1)], 24)[5]
    assert split_by_weight(D("10.000"), {}) == {}


def test_a_lot_pays_the_hours_it_stayed_not_a_whole_day():
    # In the room alone from 00:28 to 21:38: 21 h 10 min of a 24 DT day, not the whole day.
    day = dt.date(2026, 9, 1)
    held = {day: {hour: [(3600, {1: D("10.000")})] for hour in range(1, 21)}}
    held[day][0] = [(32 * 60, {1: D("10.000")})]
    held[day][21] = [(38 * 60, {1: D("10.000")})]
    charge = allocate_room_days({day: D("24.000")}, held)[1]
    assert charge.amount == D("21.166")  # 0.533 (32 min of hour 0) + 20 hours + 0.633 (38 min of hour 21)
    assert charge.kg_days == D("8.819")  # 10 kg x 21 h 10 min / 24 h, kept to 3 decimals (quantity)


def test_two_lots_share_the_time_they_overlap_by_kg():
    day = dt.date(2026, 9, 1)
    # Hour 9: lot 1 (30 kg) for the whole hour; lot 2 (10 kg) only for the first 30 minutes, so it gets a
    # quarter of that half hour's share and nothing of the rest.
    held = {day: {9: [(1800, {1: D("30.000"), 2: D("10.000")}), (1800, {1: D("30.000")})]}}
    charges = allocate_room_days({day: D("24.000")}, held)
    hour = split_evenly(D("24.000"), 24)[9]
    assert charges[1].amount + charges[2].amount == hour
    assert charges[2].amount == split_by_weight(hour / 2, {1: D("30.000"), 2: D("10.000")})[2]


def test_the_estimate_is_the_previous_months_daily_rate():
    assert estimate_day_amount(D("310.000"), dt.date(2026, 8, 1)) == D("10.000")
    assert estimate_day_amount(D("100.000"), dt.date(2026, 9, 1)) == D("3.333")


# ---- the ledger by date ----


def test_kilos_in_a_room_are_replayed_from_the_ledger_day_by_day(organization, cold_room, room_two):
    today = timezone.localdate()
    lot = put(organization, "Dorade", "100", cold_room, today - dt.timedelta(days=10))
    move(organization, lot, "40", cold_room, room_two, today - dt.timedelta(days=6))
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.SALE,
        batch=lot,
        quantity="10",
        from_location=room_two,
        occurred_at=at(today - dt.timedelta(days=3)),
    )

    def kg(room, ago):
        return inventory.kg_by_batch_on_day(organization, location_id=room.pk, day=today - dt.timedelta(days=ago))

    assert kg(cold_room, 11) == {}
    assert kg(cold_room, 10) == {lot.pk: D("100.000")}
    assert kg(cold_room, 6) == {lot.pk: D("60.000")}
    assert kg(room_two, 7) == {}
    assert kg(room_two, 6) == {lot.pk: D("40.000")}
    assert kg(room_two, 3) == {lot.pk: D("30.000")}
    everywhere = inventory.kg_by_batch_by_day(organization, date_from=today - dt.timedelta(days=11), date_to=today)[
        inventory.EVERYWHERE
    ]
    assert everywhere[today - dt.timedelta(days=11)] == {}
    assert everywhere[today - dt.timedelta(days=6)] == {lot.pk: D("100.000")}
    assert everywhere[today] == {lot.pk: D("90.000")}


# ---- bill, estimate, correction ----


def test_the_ledger_gives_the_hours_a_lot_was_in_a_room(organization, cold_room):
    day = dt.date(2026, 9, 1)
    product = ProductFactory.create(organization=organization, name="Dorade")
    batch = BatchFactory.create(organization=organization, product=product, received_on=day)

    def moment(hour, minute):
        return timezone.make_aware(dt.datetime.combine(day, dt.time(hour, minute)))

    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity="10",
        to_location=cold_room,
        occurred_at=moment(0, 28),
    )
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.SALE,
        batch=batch,
        quantity="10",
        from_location=cold_room,
        occurred_at=moment(21, 38),
    )
    held = inventory.held_slices_by_hour(organization, date_from=day, date_to=day, location_ids=[cold_room.pk])
    hours = held[cold_room.pk][day]
    assert sorted(hours) == list(range(22))
    assert hours[0] == [(32 * 60, {batch.pk: D("10.000")})]
    assert hours[21] == [(38 * 60, {batch.pk: D("10.000")})]
    assert hours[5] == [(3600, {batch.pk: D("10.000")})]


def test_before_any_bill_there_is_no_estimate_to_copy(organization, cold_room):
    lot = put(organization, "Dorade", "100", cold_room, timezone.localdate() - dt.timedelta(days=5))
    assert lines_of(organization, lot, "cold_room") == []


def test_the_estimate_is_flagged_then_the_real_bill_adds_a_dated_correction(organization, actor, cold_room, room_two):
    m0, m1, m2, m3 = months()
    services.set_cold_room_weight(organization=organization, actor=actor, location=room_two, weight="2")
    services.set_cold_room_weight(organization=organization, actor=actor, location=cold_room, weight="1")

    first = bill(organization, actor, m0, "300.000", approve=True)
    rates = {rate.location_id: rate.month_amount for rate in first.rates.all()}
    assert rates == {cold_room.pk: D("100.000"), room_two.pk: D("200.000")}
    assert first.finalized_at is not None
    assert first.estimate_source_month is None

    lot = put(organization, "Dorade", "100", cold_room, m1)
    estimate = estimate_day_amount(D("100.000"), m0)
    estimated = lines_of(organization, lot, "cold_room")
    assert [line.month for line in estimated] == [m1, m2, m3]
    assert all(line.estimated for line in estimated)
    today_days = (timezone.localdate() - m3).days + 1
    # The lot came in at midnight: whole months, and today only up to now (hours to come are not charged).
    assert [line.amount for line in estimated[:2]] == [estimate * days_in_month(m1), estimate * days_in_month(m2)]
    assert 0 <= estimated[2].amount <= estimate * today_days
    assert estimated[0].location_name == "Chambre froide 1"
    assert estimated[0].quantity == D("100.000") * days_in_month(m1)
    assert selectors.lot_cost_total(selectors.lot_cost_lines(organization, batch_id=lot.pk)) == sum(
        (line.amount for line in estimated), D("0")
    )

    # The real bill of month 1 arrives: 400 DT, room 1 takes a third of it.
    second = bill(organization, actor, m1, "400.000", approve=True)
    assert second.estimate_source_month == m0
    real_room_one = {rate.location_id: rate.month_amount for rate in second.rates.all()}[cold_room.pk]
    assert real_room_one == D("133.333")
    adjustment = lines_of(organization, lot, "cold_room_adjustment")
    assert len(adjustment) == 1
    assert adjustment[0].spent_on == timezone.localdate()
    assert adjustment[0].month == m1
    estimate_m1 = lines_of(organization, lot, "cold_room")[0]
    assert estimate_m1.month == m1
    assert estimate_m1.amount == estimate * days_in_month(m1)
    # Estimate line + correction line = the real cost of the month, to the millime.
    assert estimate_m1.amount + adjustment[0].amount == real_room_one
    assert adjustment[0].expense_number == second.expense.number
    assert LotCostAdjustment.objects.filter(batch=lot).count() == 1

    # The month after keeps being estimated, now from month 1's daily rate.
    later = lines_of(organization, lot, "cold_room")
    assert later[1].amount == estimate_day_amount(real_room_one, m1) * days_in_month(m2)
    assert AuditLog.objects.filter(action="electricity_bill.finalized").count() == 2


def test_a_closed_lot_is_not_reopened_the_difference_is_a_separate_later_line(organization, actor, cold_room, room_two):
    m0, m1, m2, _m3 = months()
    bill(organization, actor, m0, "300.000", approve=True)
    # A lot that lived in room 1 for the whole of month 1, sold out the day after.
    lot = put(organization, "Crevette", "50", cold_room, m1)
    inventory_services.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.SALE,
        batch=lot,
        quantity="50",
        from_location=cold_room,
        occurred_at=at(m2),
    )
    before = lines_of(organization, lot, "cold_room")
    assert [line.month for line in before] == [m1]

    bill(organization, actor, m1, "600.000", approve=True)

    after = lines_of(organization, lot, "cold_room")
    assert [(line.month, line.amount) for line in after] == [(line.month, line.amount) for line in before]
    correction = lines_of(organization, lot, "cold_room_adjustment")[0]
    assert correction.spent_on == timezone.localdate()  # dated at bill entry, not in month 1
    assert before[0].amount + correction.amount == D("300.000")  # half of 600


def test_two_lots_in_a_room_share_each_day_by_kg_and_the_shares_add_up(organization, actor, cold_room, room_two):
    _m0, m1, _m2, _m3 = months()
    big = put(organization, "Dorade", "300", cold_room, m1)
    small = put(organization, "Loup", "100", cold_room, m1)

    bill(organization, actor, m1, "1000.000", approve=True)
    rate = {
        r.location_id: r for r in cost_selectors.bill_of(organization, selectors_bill(organization, m1)).rates.all()
    }
    room_total = rate[cold_room.pk].month_amount

    total = sum(
        (line.amount for lot in (big, small) for line in lines_of(organization, lot, "cold_room_adjustment")), D("0")
    )
    assert total == room_total  # all days of the month are held: nothing is left unallocated
    big_amount = lines_of(organization, big, "cold_room_adjustment")[0].amount
    small_amount = lines_of(organization, small, "cold_room_adjustment")[0].amount
    assert abs(big_amount - room_total * D("0.75")) <= D("0.001") * days_in_month(m1)
    assert abs(small_amount - room_total * D("0.25")) <= D("0.001") * days_in_month(m1)


def selectors_bill(organization, month):
    return cost_selectors.bills_of(organization).get(month=month).pk


def test_a_lot_that_moves_rooms_is_charged_by_room_and_day(organization, actor, cold_room, room_two):
    _m0, m1, _m2, _m3 = months()
    services.set_cold_room_weight(organization=organization, actor=actor, location=room_two, weight="3")
    lot = put(organization, "Dorade", "100", cold_room, m1)
    switch = m1 + dt.timedelta(days=9)  # days 1-9 in room 1, from day 10 in room 2
    move(organization, lot, "100", cold_room, room_two, switch)

    bill(organization, actor, m1, "400.000", approve=True)  # room 1: 100, room 2: 300

    corrections = {line.location_name: line.amount for line in lines_of(organization, lot, "cold_room_adjustment")}
    room_one_days = room_day_amounts(D("100.000"), m1)
    room_two_days = room_day_amounts(D("300.000"), m1)
    assert corrections["Chambre froide 1"] == sum(
        (room_one_days[day] for day in month_days(m1) if day < switch), D("0")
    )
    assert corrections["Chambre froide -20"] == sum(
        (room_two_days[day] for day in month_days(m1) if day >= switch), D("0")
    )
    # The move is at midnight: each room is charged for the hours the lot was in it.
    assert sum(corrections.values()) == sum(
        (room_one_days[day] if day < switch else room_two_days[day] for day in month_days(m1)), D("0")
    )


def test_a_bill_needs_a_finished_month_is_unique_and_a_refused_one_can_be_retyped(organization, actor, cold_room):
    _m0, m1, _m2, m3 = months()
    with pytest.raises(ValidationError) as error:
        bill(organization, actor, m3, "10")
    assert "month" in error.value.message_dict
    with pytest.raises(ValidationError):
        bill(organization, actor, m1 + dt.timedelta(days=1), "10")

    typed = bill(organization, actor, m1, "10")
    assert (typed.expense.status, typed.expense.category.code) == (ExpenseStatus.DRAFT, "cold_storage")
    with pytest.raises(ValidationError):
        bill(organization, actor, m1, "10")
    services.reject_expense(expense=typed.expense, actor=actor, reason="Erreur")
    again = bill(organization, actor, m1, "12.500", approve=True)
    assert again.expense.amount == D("12.500")


def test_a_draft_bill_counts_for_nothing_and_is_edited_then_approved(organization, actor, cold_room):
    m0, m1, *_ = months()
    lot = put(organization, "Dorade", "100", cold_room, m1)
    draft = bill(organization, actor, m0, "100")
    assert draft.finalized_at is None
    assert lines_of(organization, lot, "cold_room") == []  # no finalized bill: no estimate basis

    edited = services.update_electricity_bill(bill=draft, actor=actor, amount="310.000")
    assert edited.expense.amount == D("310.000")
    approved = services.approve_expense(expense=edited.expense, actor=actor)  # the generic path works too
    assert approved.status == ExpenseStatus.APPROVED
    assert cost_selectors.bill_of(organization, draft.pk).finalized_at is not None
    assert len(lines_of(organization, lot, "cold_room")) >= 1
    with pytest.raises(ValidationError):
        services.update_expense(
            expense=approved,
            actor=actor,
            spent_on=approved.spent_on,
            category=approved.category,
            amount="1",
        )


def test_a_linked_draft_is_not_edited_or_deleted_through_the_plain_expense(organization, actor, cold_room):
    m0, *_ = months()
    draft = bill(organization, actor, m0, "100")
    with pytest.raises(ValidationError):
        services.update_expense(
            expense=draft.expense,
            actor=actor,
            spent_on=draft.expense.spent_on,
            category=draft.expense.category,
            amount="5",
        )
    with pytest.raises(ValidationError):
        services.delete_expense(expense=draft.expense, actor=actor)
    services.delete_electricity_bill(bill=draft, actor=actor)
    assert not cost_selectors.bills_of(organization).exists()


def test_an_approved_bill_needs_a_cold_room(organization, actor):
    m0, *_ = months()
    with pytest.raises(ValidationError):
        bill(organization, actor, m0, "100", approve=True)


def test_the_month_view_is_estimated_until_the_bill_is_approved(organization, actor, cold_room, room_two):
    m0, m1, *_ = months()
    services.set_cold_room_weight(organization=organization, actor=actor, location=room_two, weight="3")
    view = cost_selectors.cold_room_month(organization, month=m0)
    assert view.estimated
    assert view.bill is None
    assert view.total is None
    assert [(row.location_name, row.weight) for row in view.rooms] == [
        ("Chambre froide -20", D("3.000")),
        ("Chambre froide 1", D("1.000")),
    ]

    bill(organization, actor, m0, "400.000", approve=True)
    real = cost_selectors.cold_room_month(organization, month=m0)
    assert not real.estimated
    assert real.total == D("400.000")
    assert {row.location_name: row.month_amount for row in real.rooms} == {
        "Chambre froide -20": D("300.000"),
        "Chambre froide 1": D("100.000"),
    }
    guess = cost_selectors.cold_room_month(organization, month=m1)
    assert guess.estimated
    assert guess.estimate_source_month == m0
    assert {row.location_name: row.day_amount for row in guess.rooms}["Chambre froide 1"] == estimate_day_amount(
        D("100.000"), m0
    )


def test_a_weight_change_does_not_touch_a_bill_already_approved(organization, actor, cold_room, room_two):
    m0, m1, *_ = months()
    first = bill(organization, actor, m0, "400.000", approve=True)
    services.set_cold_room_weight(organization=organization, actor=actor, location=room_two, weight="9")
    assert {rate.location_id: rate.month_amount for rate in first.rates.all()}[cold_room.pk] == D("200.000")
    second = bill(organization, actor, m1, "400.000", approve=True)
    assert {rate.location_id: rate.month_amount for rate in second.rates.all()}[cold_room.pk] == D("40.000")
    with pytest.raises(ValidationError):
        services.set_cold_room_weight(organization=organization, actor=actor, location=room_two, weight="0")
    with pytest.raises(ValidationError):
        services.set_cold_room_weight(organization=organization, actor=actor, location=room_two, weight="1.2345")


def test_creating_a_bill_locks_the_organization_so_two_at_once_get_the_clean_message(organization, actor):
    _m0, _m1, last_month, _current = months()
    with CaptureQueriesContext(connection) as queries:
        bill(organization, actor, last_month, "300.000")

    assert any("FOR UPDATE" in query["sql"] and "core_organization" in query["sql"] for query in queries)
    with pytest.raises(ValidationError) as error:
        bill(organization, actor, last_month, "310.000")
    assert "month" in error.value.message_dict


def test_the_shares_of_the_cold_rooms_are_set_together_and_must_make_100_percent(organization):
    rooms = [StockLocationFactory.create(organization=organization, kind="cold_room") for _ in range(3)]
    shares = {rooms[0].pk: D("20"), rooms[1].pk: D("40"), rooms[2].pk: D("40")}

    services.set_cold_room_shares(organization=organization, actor=None, shares=shares)

    assert cost_selectors.room_weights(organization) == {room.pk: shares[room.pk] for room in rooms}
    with pytest.raises(ValidationError):  # 99 %
        services.set_cold_room_shares(organization=organization, actor=None, shares={**shares, rooms[2].pk: D("39")})
    with pytest.raises(ValidationError):  # a room is missing
        services.set_cold_room_shares(
            organization=organization, actor=None, shares={rooms[0].pk: D("50"), rooms[1].pk: D("50")}
        )
