"""The owner's estimate of a month's cold-room electricity, typed before the bill arrives (P9-point 11, D-227)."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse

from apps.core.models import AuditLog, Role
from apps.expenses import cost_selectors, selectors, services
from apps.expenses.costing import add_months, days_in_month, estimate_day_amount
from apps.expenses.models import ColdRoomEstimate, ExpenseStatus
from apps.inventory.tests.factories import StockLocationFactory

from .conftest import client_for, member
from .test_cold_room_cost import bill, lines_of, months, put

pytestmark = pytest.mark.django_db

D = Decimal


@pytest.fixture
def room_two(organization):
    return StockLocationFactory.create(organization=organization, name="Chambre froide -20")


def type_estimate(organization, actor, month, amount, reason=""):
    return services.set_cold_room_estimate(
        organization=organization, actor=actor, month=month, amount=amount, reason=reason
    )


def test_a_typed_estimate_replaces_the_copied_rate_and_is_shared_by_weight(organization, actor, cold_room, room_two):
    m0, m1, *_ = months()
    services.set_cold_room_weight(organization=organization, actor=actor, location=room_two, weight="3")
    bill(organization, actor, m0, "300.000", approve=True)
    type_estimate(organization, actor, m1, "400.000")

    view = cost_selectors.cold_room_month(organization, month=m1)
    assert view.estimated
    assert view.estimate_typed
    assert view.typed_amount == D("400.000")
    assert view.estimate_source_month is None
    rows = {row.location_name: row for row in view.rooms}
    # Shared by weight, as a bill is: room 1 a quarter, the -20 room three quarters.
    assert rows["Chambre froide 1"].month_amount == D("100.000")
    assert rows["Chambre froide -20"].month_amount == D("300.000")
    assert rows["Chambre froide 1"].day_amount == estimate_day_amount(D("100.000"), m1)
    assert view.total == D("400.000")
    assert view.estimate_total == D("400.000")
    assert view.difference is None

    # A lot in room 1 for the whole month pays the typed estimate, not the copied rate of month 0.
    lot = put(organization, "Dorade", "100", cold_room, m1)
    estimated = lines_of(organization, lot, "cold_room")
    assert estimated[0].month == m1
    assert estimated[0].amount == estimate_day_amount(D("100.000"), m1) * days_in_month(m1)


def test_the_real_bill_counts_as_an_expense_and_the_difference_with_the_typed_estimate_is_shown(
    organization, actor, cold_room, room_two
):
    _m0, m1, *_ = months()
    type_estimate(organization, actor, m1, "200.000")
    lot = put(organization, "Dorade", "100", cold_room, m1)

    real = bill(organization, actor, m1, "400.000", approve=True)
    assert real.expense.status == ExpenseStatus.APPROVED
    assert real.expense.amount == D("400.000")
    assert real.estimate_source_month is None
    rates = {rate.location_id: rate.estimate_day_amount for rate in real.rates.all()}
    half = estimate_day_amount(D("100.000"), m1)
    assert rates == {cold_room.pk: half, room_two.pk: half}

    view = cost_selectors.cold_room_month(organization, month=m1)
    assert not view.estimated
    assert view.typed_amount == D("200.000")
    assert view.estimate_typed
    assert view.total == D("400.000")
    assert view.estimate_total == estimate_day_amount(D("100.000"), m1) * days_in_month(m1) * 2
    assert view.difference == D("400.000") - view.estimate_total

    # Estimate line + correction line = the room's real part of the bill (200 DT), to the millime.
    estimated = lines_of(organization, lot, "cold_room")
    adjustment = lines_of(organization, lot, "cold_room_adjustment")
    assert len(adjustment) == 1
    assert estimated[0].amount + adjustment[0].amount == D("200.000")
    assert selectors.lot_cost_total(selectors.lot_cost_lines(organization, batch_id=lot.pk)) == D("200.000") + sum(
        (line.amount for line in estimated[1:]), D("0")
    )


def test_a_typed_estimate_is_frozen_once_the_bill_is_approved(organization, actor, cold_room):
    _m0, m1, *_ = months()
    type_estimate(organization, actor, m1, "200.000")
    bill(organization, actor, m1, "400.000", approve=True)

    with pytest.raises(ValidationError):
        type_estimate(organization, actor, m1, "50.000")
    assert ColdRoomEstimate.objects.get(month=m1).amount == D("200.000")


def test_the_estimate_is_typed_for_this_month_or_an_earlier_one_and_changed_in_place(organization, actor, cold_room):
    _m0, m1, _m2, m3 = months()
    with pytest.raises(ValidationError):
        type_estimate(organization, actor, add_months(m3, 1), "10.000")
    with pytest.raises(ValidationError):
        type_estimate(organization, actor, m1.replace(day=2), "10.000")
    for amount in ("0", "-5", "abc", "1.0001"):
        with pytest.raises(ValidationError):
            type_estimate(organization, actor, m1, amount)
    assert not ColdRoomEstimate.objects.filter(month=m1).exists()

    type_estimate(organization, actor, m1, "200")
    type_estimate(organization, actor, m1, "250.500", reason="Facture en retard")
    assert list(ColdRoomEstimate.objects.filter(month=m1).values_list("amount", flat=True)) == [D("250.500")]
    entry = AuditLog.objects.filter(action="cold_room_estimate.set").latest("id")
    assert entry.before == {"amount": "200.000"}
    assert entry.after == {"month": m1.isoformat(), "amount": "250.500", "reason": "Facture en retard"}


def test_the_owner_or_manager_types_the_estimate_and_the_accountant_cannot(organization, manager, cold_room):
    _m0, m1, *_ = months()
    payload = {"month": m1.isoformat(), "amount": "300.000"}

    answer = client_for(manager).put(reverse("cold-room-estimate"), payload, format="json")
    assert answer.status_code == 200
    month = answer.json()
    assert (month["typed_amount"], month["estimate_typed"], month["total"]) == ("300.000", True, "300.000")
    assert month["estimated"] is True

    accountant = client_for(member(organization, Role.ACCOUNTANT))
    assert accountant.put(reverse("cold-room-estimate"), payload, format="json").status_code == 403
    bad = client_for(manager).put(reverse("cold-room-estimate"), {**payload, "amount": "0"}, format="json")
    assert bad.status_code == 400
