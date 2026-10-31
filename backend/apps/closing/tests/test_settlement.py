"""Settling a lot with its partner, late costs and the three balances (P6-T03, D-066)."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.closing import selectors, services
from apps.core.models import AuditLog, Role
from apps.partners.tests.factories import SupplierFactory
from apps.partnerships import selectors as partnerships
from apps.partnerships.models import (
    CapitalEntry,
    PartnershipStatus,
    ProfitShareEntry,
    ProfitShareKind,
)
from apps.purchasing import selectors as purchasing

from .conftest import client_for, cost, member, partnership, receive, sell

pytestmark = pytest.mark.django_db
D = Decimal


def close(organization, actor, batch):
    return services.close_lot(organization=organization, actor=actor, batch_id=batch.pk, costs_confirmed=True)


def settle(organization, actor, batch, *payments, notes=""):
    return services.settle_lot(
        organization=organization,
        actor=actor,
        batch_id=batch.pk,
        payments=[{"amount": amount, "method": method} for amount, method in payments],
        notes=notes,
    )


def balances(organization, partner):
    return partnerships.partner_balances(organization, partner_id=partner.pk)


def sold_lot(organization, actor, cold_room, partner, *, capital, price, kg="100.000", profit="40", loss="25"):
    """100 kg bought at 20.000 (2 000.000), all sold at `price`: net = kg × price - 2 000.000."""
    batch = receive(organization, cold_room, kg, name=f"Produit {price}")
    partnership(organization, actor, batch, partner, capital=capital, profit=profit, loss=loss)
    sell(organization, actor, cold_room, batch, kg, price)
    return batch


# ---- A profit ----


def test_a_profit_lot_pays_the_capital_back_plus_the_share_and_keeps_three_balances_apart(
    organization, actor, finished_lot, partner
):
    close(organization, actor, finished_lot)
    result = selectors.closed_result_of(organization, batch_id=finished_lot.pk)
    assert result is not None
    preview = selectors.settlement_preview(organization, result)
    # Capital 1 000.000 back + 40 % of 715.000.
    assert (preview.capital_to_return, preview.lot_share, preview.total) == (D("1000.000"), D("286.000"), D("1286.000"))
    assert balances(organization, partner).capital == D("1000.000")
    trade_before = purchasing.supplier_balance(organization, partner.pk).balance

    settlement = settle(organization, actor, finished_lot, ("1000.000", "cash"), ("286.000", "transfer"))

    assert (settlement.capital_returned, settlement.lot_share, settlement.share_paid) == (
        D("1000.000"),
        D("286.000"),
        D("286.000"),
    )
    assert (settlement.amount_paid, settlement.carried_in, settlement.carried_out) == (
        D("1286.000"),
        D("0.000"),
        D("0.000"),
    )
    assert sorted(p.method for p in settlement.payments.all()) == ["cash", "transfer"]
    live = partnerships.live_partnership_of_batch(organization, batch_id=finished_lot.pk)
    assert live is not None
    assert live.status == PartnershipStatus.SETTLED
    # Capital: contribution, then returned. Profit share: the share, then paid. Trade payable untouched.
    assert [(e.kind, e.amount) for e in partnerships.capital_entries_of(live)] == [
        ("contribution", D("1000.000")),
        ("return", D("-1000.000")),
    ]
    assert [(e.kind, e.amount) for e in partnerships.profit_share_entries_of(live)] == [
        ("share", D("286.000")),
        ("payment", D("-286.000")),
    ]
    after = balances(organization, partner)
    assert (after.capital, after.profit_share, after.trade_payable) == (D("0.000"), D("0.000"), trade_before)
    assert AuditLog.objects.filter(action="partnership.settled").exists()


def test_payments_must_add_up_and_nothing_is_posted_when_they_do_not(organization, actor, finished_lot, partner):
    close(organization, actor, finished_lot)

    with pytest.raises(ValidationError) as short:
        settle(organization, actor, finished_lot, ("1000.000", "cash"))
    assert "1 286,000" in short.value.message_dict["payments"][0]
    with pytest.raises(ValidationError):
        settle(organization, actor, finished_lot, ("1286.0005", "cash"))
    with pytest.raises(ValidationError):
        settle(organization, actor, finished_lot, ("1286.000", "gold"))

    live = partnerships.live_partnership_of_batch(organization, batch_id=finished_lot.pk)
    assert live is not None
    assert live.status == PartnershipStatus.CLOSED
    assert partnerships.capital_balance(live) == D("1000.000")
    assert not ProfitShareEntry.objects.exists()


def test_a_lot_is_settled_once_and_a_settled_lot_cannot_be_reopened(organization, actor, finished_lot):
    result = close(organization, actor, finished_lot)
    settle(organization, actor, finished_lot, ("1286.000", "cash"))

    with pytest.raises(ValidationError, match="déjà réglé"):
        settle(organization, actor, finished_lot, ("1286.000", "cash"))
    with pytest.raises(ValidationError, match="réglé"):
        services.reopen_lot(result=result, actor=actor, reason="Erreur")
    assert CapitalEntry.objects.filter(kind="return").count() == 1


def test_an_open_lot_or_a_lot_without_partner_is_not_settled(organization, actor, cold_room, partner):
    open_lot = receive(organization, cold_room, "10.000")
    partnership(organization, actor, open_lot, partner)
    with pytest.raises(ValidationError):
        settle(organization, actor, open_lot)

    plain = receive(organization, cold_room, "10.000", name="Seiche")
    sell(organization, actor, cold_room, plain, "10.000", "30.000")
    close(organization, actor, plain)
    with pytest.raises(ValidationError):
        settle(organization, actor, plain)


# ---- A loss ----


def test_a_loss_inside_the_capital_pays_back_what_is_left(organization, actor, cold_room, partner):
    # 2 000.000 bought, sold 1 000.000: net -1 000.000, 25 % = 250.000 off a 1 000.000 capital.
    batch = sold_lot(organization, actor, cold_room, partner, capital="1000.000", price="10.000")
    result = close(organization, actor, batch)
    assert (result.net_result, result.capital_deducted, result.uncovered_loss) == (
        D("-1000.000"),
        D("250.000"),
        D("0.000"),
    )

    settlement = settle(organization, actor, batch, ("750.000", "cheque"))

    assert (settlement.capital_returned, settlement.share_paid, settlement.amount_paid) == (
        D("750.000"),
        D("0.000"),
        D("750.000"),
    )
    live = partnerships.live_partnership_of_batch(organization, batch_id=batch.pk)
    assert live is not None
    assert partnerships.capital_balance(live) == D("0.000")
    assert not ProfitShareEntry.objects.exists()


def test_a_loss_beyond_the_capital_is_carried_and_recovered_from_the_next_profit_share(
    organization, actor, cold_room, partner
):
    # Net -1 000.000, loss share 250.000, capital only 100.000: 150.000 is owed by the partner (D-031).
    losing = sold_lot(organization, actor, cold_room, partner, capital="100.000", price="10.000")
    close(organization, actor, losing)
    first = settle(organization, actor, losing)

    # Nothing is paid, nothing is taken from anywhere else: the 150.000 stays on the profit-share balance.
    assert (first.capital_returned, first.amount_paid, first.carried_out) == (D("0.000"), D("0.000"), D("-150.000"))
    assert balances(organization, partner).profit_share == D("-150.000")
    entries = ProfitShareEntry.objects.all()
    assert [(e.kind, e.amount) for e in entries] == [(ProfitShareKind.UNCOVERED_LOSS, D("-150.000"))]

    # The next lot: net 2 500.000 - 2 000.000 = 500.000, share 40 % = 200.000, capital 300.000.
    winning = sold_lot(organization, actor, cold_room, partner, capital="300.000", price="25.000")
    result = close(organization, actor, winning)
    assert result.partner_share == D("200.000")
    preview = selectors.settlement_preview(organization, result)
    assert (preview.carried_in, preview.share_paid, preview.total) == (D("-150.000"), D("50.000"), D("350.000"))

    second = settle(organization, actor, winning, ("350.000", "cash"))

    # 300.000 capital + (200.000 share - 150.000 owed) = 350.000; nothing left owed.
    assert (second.carried_in, second.share_paid, second.carried_out) == (D("-150.000"), D("50.000"), D("0.000"))
    after = balances(organization, partner)
    assert (after.capital, after.profit_share) == (D("0.000"), D("0.000"))


def test_what_the_partner_still_owes_is_never_taken_from_their_capital(organization, actor, cold_room, partner):
    losing = sold_lot(organization, actor, cold_room, partner, capital="100.000", price="10.000")
    close(organization, actor, losing)
    settle(organization, actor, losing)
    # A second lot with a tiny profit: the share (40 % of 10.000 = 4.000) cannot cover the 150.000 owed.
    small = sold_lot(organization, actor, cold_room, partner, capital="500.000", price="20.100", kg="100.000")
    result = close(organization, actor, small)
    assert result.partner_share == D("4.000")

    settlement = settle(organization, actor, small, ("500.000", "cash"))

    assert (settlement.capital_returned, settlement.share_paid, settlement.carried_out) == (
        D("500.000"),
        D("0.000"),
        D("-146.000"),
    )
    assert balances(organization, partner).profit_share == D("-146.000")


# ---- A cost after the closing ----


def test_a_late_cost_goes_to_the_next_settlement_without_reopening_the_lot(organization, actor, finished_lot, partner):
    frozen = close(organization, actor, finished_lot)
    cost(organization, actor, finished_lot, "cold_storage", "100.000")

    drift = selectors.late_drift(organization, frozen)
    assert drift is not None
    # Net 715.000 -> 615.000: the share goes from 286.000 to 246.000.
    assert (drift.drift, drift.booked, drift.pending_basis, drift.pending_share) == (
        D("-100.000"),
        D("0.000"),
        D("-100.000"),
        D("-40.000"),
    )

    assert services.book_late_adjustments(organization=organization, actor=actor, batch_id=finished_lot.pk) is True
    # Booked once: the second call has nothing left to book.
    assert services.book_late_adjustments(organization=organization, actor=actor, batch_id=finished_lot.pk) is False
    frozen.refresh_from_db()
    assert (frozen.status, frozen.net_result, frozen.partner_share) == ("closed", D("715.000"), D("286.000"))
    assert balances(organization, partner).profit_share == D("-40.000")

    settlement = settle(organization, actor, finished_lot, ("1246.000", "cash"))

    assert (settlement.lot_share, settlement.carried_in, settlement.share_paid) == (
        D("286.000"),
        D("-40.000"),
        D("246.000"),
    )
    assert balances(organization, partner).profit_share == D("0.000")


def test_settling_carries_the_late_cost_without_booking_it_first(organization, actor, finished_lot, partner):
    close(organization, actor, finished_lot)
    cost(organization, actor, finished_lot, "cold_storage", "100.000")

    settlement = settle(organization, actor, finished_lot, ("1246.000", "cash"))

    assert settlement.share_paid == D("246.000")
    assert [e.kind for e in ProfitShareEntry.objects.order_by("id")] == [
        ProfitShareKind.LATE_ADJUSTMENT,
        ProfitShareKind.SHARE,
        ProfitShareKind.PAYMENT,
    ]


def test_a_cost_after_the_settlement_is_recovered_by_the_partners_next_settlement(
    organization, actor, cold_room, finished_lot, partner
):
    close(organization, actor, finished_lot)
    settle(organization, actor, finished_lot, ("1286.000", "cash"))
    cost(organization, actor, finished_lot, "cold_storage", "100.000")
    assert services.book_late_adjustments(organization=organization, actor=actor, batch_id=finished_lot.pk) is True
    assert balances(organization, partner).profit_share == D("-40.000")

    # Net 500.000, share 200.000, capital 300.000: pays 300.000 + 200.000 - 40.000.
    nextlot = sold_lot(organization, actor, cold_room, partner, capital="300.000", price="25.000")
    close(organization, actor, nextlot)
    settlement = settle(organization, actor, nextlot, ("460.000", "cash"))

    assert (settlement.carried_in, settlement.share_paid, settlement.carried_out) == (
        D("-40.000"),
        D("160.000"),
        D("0.000"),
    )


def test_late_adjustments_add_up_to_the_exact_difference_of_shares(organization, actor, finished_lot):
    frozen = close(organization, actor, finished_lot)
    for amount in ("33.333", "0.007", "12.501"):
        cost(organization, actor, finished_lot, "fuel", amount)
        services.book_late_adjustments(organization=organization, actor=actor, batch_id=finished_lot.pk)

    live = partnerships.live_partnership_of_batch(organization, batch_id=finished_lot.pk)
    assert live is not None
    booked = sum(e.amount for e in partnerships.profit_share_entries_of(live))
    # live net = 715.000 - 45.841 = 669.159; 40 % = 267.6636 -> 267.664; 286.000 - 267.664 = 18.336.
    assert selectors.live_result(organization, batch_id=finished_lot.pk).net_result == D("669.159")
    assert booked == D("-18.336")
    drift = selectors.late_drift(organization, frozen)
    assert drift is not None
    assert (drift.pending_basis, drift.pending_share) == (D("0.000"), D("0.000"))


# ---- Receivables behind one function ----


def test_customers_owing_is_read_through_one_function(organization, actor, cold_room):
    batch = receive(organization, cold_room, "10.000")
    sell(organization, actor, cold_room, batch, "4.000", "30.000", paid=True)
    sell(organization, actor, cold_room, batch, "6.000", "30.000", paid=False)

    snapshot = selectors.lot_snapshot(organization, batch_id=batch.pk)
    owing = selectors.customers_owing(organization, snapshot)

    assert sorted(owing.values()) == [D("180.000")]


# ---- API and permissions ----


def test_the_settlement_api_shows_the_preview_then_settles_for_the_owner_only(
    organization, actor, api, finished_lot, partner
):
    close(organization, actor, finished_lot)
    url = f"/api/v1/lots/{finished_lot.pk}/settlement"
    shown = api.get(url).json()
    assert (shown["state"], shown["partner_name"]) == ("ready", partner.name)
    assert shown["preview"]["total"] == "1286.000"
    assert (shown["balances"]["capital"], shown["balances"]["profit_share"]) == ("1000.000", "0.000")

    body = {"payments": [{"amount": "1286.000", "method": "transfer", "reference": "VIR-12"}]}
    for role in (Role.MANAGER, Role.DRIVER, Role.ACCOUNTANT):
        assert (
            client_for(member(organization, role))
            .post(f"/api/v1/lots/{finished_lot.pk}/settle", body, format="json")
            .status_code
            == 403
        )
    assert client_for(member(organization, Role.DRIVER)).get(url).status_code == 403
    assert client_for(member(organization, Role.ACCOUNTANT)).get(url).status_code == 200

    done = api.post(f"/api/v1/lots/{finished_lot.pk}/settle", body, format="json")
    assert done.status_code == 200
    data = done.json()
    assert (data["state"], data["settlement"]["amount_paid"]) == ("settled", "1286.000")
    assert data["settlement"]["payments"][0]["reference"] == "VIR-12"
    assert [entry["kind"] for entry in data["entries"]] == ["share", "payment"]
    wrong = api.post(f"/api/v1/lots/{finished_lot.pk}/settle", body, format="json")
    assert wrong.status_code == 400


def test_the_partner_balances_api_gives_three_separate_numbers(organization, actor, api, finished_lot, partner):
    close(organization, actor, finished_lot)
    other = SupplierFactory.create(organization=organization)

    data = api.get(f"/api/v1/partners/{partner.pk}/balances").json()

    assert (data["trade_payable"], data["capital"], data["profit_share"], data["lots"]) == (
        "0.000",
        "1000.000",
        "0.000",
        1,
    )
    assert api.get(f"/api/v1/partners/{other.pk}/balances").json()["capital"] == "0.000"
    assert (
        client_for(member(organization, Role.MANAGER)).get(f"/api/v1/partners/{partner.pk}/balances").status_code == 403
    )


def test_another_organizations_lot_is_not_found(api, finished_lot):
    from apps.core.tests.factories import MembershipFactory

    stranger = client_for(MembershipFactory.create(role=Role.OWNER))

    assert stranger.get(f"/api/v1/lots/{finished_lot.pk}/settlement").status_code == 404
    assert stranger.post(f"/api/v1/lots/{finished_lot.pk}/settle", {}, format="json").status_code == 404
    assert api.get("/api/v1/lots/999999/settlement").status_code == 404
