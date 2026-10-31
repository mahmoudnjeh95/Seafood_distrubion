"""Lot results read from real records, closing, reopening (P6-T02, D-061)."""

import threading
from decimal import Decimal
from typing import Any

import pytest
from django.core.exceptions import ValidationError
from django.db import connection

from apps.closing import selectors, services
from apps.closing.models import LotResult, LotResultStatus
from apps.core.models import AuditLog, Role
from apps.core.tests.factories import MembershipFactory
from apps.partners.tests.factories import SupplierFactory
from apps.partnerships import selectors as partnerships
from apps.partnerships.models import CapitalEntryKind, PartnershipStatus
from apps.sales import services as sales

from .conftest import client_for, cost, employee_day, lose, member, partnership, receive, sell

pytestmark = pytest.mark.django_db
D = Decimal


def close(organization, actor, batch) -> LotResult:
    return services.close_lot(organization=organization, actor=actor, batch_id=batch.pk, costs_confirmed=True)


def ledger(organization, batch) -> list[tuple[str, Decimal]]:
    live = partnerships.live_partnership_of_batch(organization, batch_id=batch.pk)
    assert live is not None
    return [(entry.kind, entry.amount) for entry in partnerships.capital_entries_of(live)]


# ---- The live result ----


def test_the_live_result_reads_sales_losses_costs_and_employee_days_of_the_lot(organization, finished_lot):
    result = selectors.live_result(organization, batch_id=finished_lot.pk)

    # 40 × 32.500 + 35 × 30.000 + 20 × 28.750; 95 kg × 20.000; 5 kg × 20.000; 120 + 40 + 50.
    assert result.revenue == D("2925.000")
    assert result.cogs == D("1900.000")
    assert result.spoilage == D("100.000")
    assert [(group.kind, group.total) for group in result.cost_groups] == [
        ("lot", D("160.000")),
        ("employee", D("50.000")),
    ]
    assert result.net_result == D("715.000")
    assert result.partner is not None
    # 715.000 × 40 % = 286.000
    assert result.partner.share == D("286.000")
    assert result.owner_share == D("429.000")
    assert result.partner.payable_to_partner == D("1286.000")
    assert result.snapshot.received_quantity == D("100.000")
    assert result.snapshot.on_hand_quantity == D("0.000")
    employee_line = result.cost_groups[1].lines[0]
    assert (employee_line.source_type, employee_line.detail) == ("employee", "0.50 × 2600.000 / 26")


def test_a_draft_cost_does_not_count_and_holds_the_closing(organization, actor, finished_lot):
    cost(organization, actor, finished_lot, "fuel", "30.000", approve=False)

    result = selectors.live_result(organization, batch_id=finished_lot.pk)
    checks = {check.code: check for check in selectors.closing_checks(organization, result)}

    assert result.costs_total == D("210.000")
    assert (checks["costs_approved"].ok, checks["costs_approved"].count) == (False, 1)
    with pytest.raises(ValidationError, match="attendent une approbation"):
        close(organization, actor, finished_lot)


def test_a_lot_with_stock_left_is_not_closed(organization, actor, cold_room):
    batch = receive(organization, cold_room, "10.000")
    sell(organization, actor, cold_room, batch, "4.000", "30.000")

    with pytest.raises(ValidationError, match=r"Il reste 6.000 kg"):
        close(organization, actor, batch)
    # So far: 4 kg sold at 30.000 for 4 × 20.000; the 6 kg left are stock, not a cost.
    result = selectors.live_result(organization, batch_id=batch.pk)
    assert (result.net_result, result.stock_value) == (D("40.000"), D("120.000"))


def test_closing_needs_the_costs_confirmed(organization, actor, finished_lot):
    with pytest.raises(ValidationError) as refused:
        services.close_lot(organization=organization, actor=actor, batch_id=finished_lot.pk)

    assert "costs_confirmed" in refused.value.message_dict


# ---- Closing and the frozen result ----


def test_closing_freezes_the_result_and_closes_the_partnership(organization, actor, finished_lot):
    result = close(organization, actor, finished_lot)

    assert result.status == LotResultStatus.CLOSED
    assert (result.net_result, result.partner_share, result.owner_share) == (D("715.000"), D("286.000"), D("429.000"))
    assert result.capital_to_return == D("1000.000")
    assert result.data["net_result"] == "715.000"
    assert [check["code"] for check in result.data["checks"]] == ["stock_empty", "costs_approved", "customers_paid"]
    assert result.payments_unverified is False
    assert result.partnership_id is not None
    live = partnerships.partnership_of(organization, result.partnership_id)
    assert live.status == PartnershipStatus.CLOSED
    # A profit takes nothing from the capital.
    assert ledger(organization, finished_lot) == [(CapitalEntryKind.CONTRIBUTION, D("1000.000"))]
    assert AuditLog.objects.filter(action="lot.closed", target_id=str(result.pk)).exists()
    with pytest.raises(ValidationError, match="déjà clôturé"):
        close(organization, actor, finished_lot)


def test_a_cost_approved_after_the_closing_leaves_the_frozen_result_alone(organization, actor, finished_lot):
    frozen = close(organization, actor, finished_lot)
    cost(organization, actor, finished_lot, "fuel", "15.000")

    frozen.refresh_from_db()
    assert frozen.net_result == D("715.000")
    assert selectors.live_result(organization, batch_id=finished_lot.pk).net_result == D("700.000")


def test_a_frozen_result_cannot_be_rewritten_or_deleted(organization, actor, finished_lot):
    close(organization, actor, finished_lot)
    results = LotResult.objects.filter(batch=finished_lot)

    with pytest.raises(TypeError):
        results.update(net_result=0)
    with pytest.raises(TypeError):
        results.delete()


def test_a_loss_lot_takes_the_loss_share_from_the_capital_and_reopening_gives_it_back(
    organization, actor, cold_room, partner
):
    batch = receive(organization, cold_room, "50.000")
    partnership(organization, actor, batch, partner, capital="100.000", profit="40", loss="25")
    # 50 kg bought 1 000.000, sold 600.000, 50.000 of transport: a loss of 450.000.
    sell(organization, actor, cold_room, batch, "50.000", "12.000")
    cost(organization, actor, batch, "transport", "50.000")

    result = close(organization, actor, batch)

    # 450.000 × 25 % = 112.500: 100.000 from the capital, 12.500 owed by the partner (D-031).
    assert (result.net_result, result.partner_share) == (D("-450.000"), D("-112.500"))
    assert (result.capital_deducted, result.uncovered_loss, result.capital_to_return) == (
        D("100.000"),
        D("12.500"),
        D("0.000"),
    )
    assert result.owner_share == D("-337.500")
    assert ledger(organization, batch) == [
        (CapitalEntryKind.CONTRIBUTION, D("100.000")),
        (CapitalEntryKind.LOSS_DEDUCTION, D("-100.000")),
    ]

    with pytest.raises(ValidationError):
        services.reopen_lot(result=result, actor=actor, reason=" ")
    services.reopen_lot(result=result, actor=actor, reason="Facture de transport en double")

    result.refresh_from_db()
    assert (result.status, result.reopen_reason) == (LotResultStatus.REOPENED, "Facture de transport en double")
    live = partnerships.live_partnership_of_batch(organization, batch_id=batch.pk)
    assert live is not None
    assert live.status == PartnershipStatus.OPEN
    assert partnerships.capital_balance(live) == D("100.000")
    assert AuditLog.objects.filter(action="lot.reopened").exists()

    # Closed again: a new frozen result, the deduction posted again, the first result kept as history.
    again = close(organization, actor, batch)
    assert again.pk != result.pk
    assert [row.status for row in selectors.results_of(organization, batch_id=batch.pk)] == [
        LotResultStatus.CLOSED,
        LotResultStatus.REOPENED,
    ]
    assert partnerships.capital_balance(live) == D("0.000")


def test_customers_still_owing_block_the_closing_until_they_pay(organization, actor, cold_room):
    batch = receive(organization, cold_room, "10.000")
    sale = sell(organization, actor, cold_room, batch, "10.000", "30.000", paid=False)

    with pytest.raises(ValidationError) as refused:
        close(organization, actor, batch)
    assert "300,000" in refused.value.messages[0]
    owed = next(
        check
        for check in selectors.closing_checks(organization, selectors.live_result(organization, batch_id=batch.pk))
        if check.code == "customers_paid"
    )
    assert (owed.ok, owed.blocking, owed.amount) == (False, True, D("300.000"))

    sales.record_customer_payment(
        organization=organization, actor=actor, customer=sale.customer, amount="300.000", method="cash"
    )
    result = close(organization, actor, batch)

    assert result.payments_unverified is False


def test_a_lot_fully_spoiled_closes_at_a_loss_without_a_sale(organization, actor, cold_room):
    batch = receive(organization, cold_room, "8.000", cost="12.500")
    lose(organization, actor, cold_room, batch, "8.000")

    result = close(organization, actor, batch)

    assert (result.revenue, result.spoilage, result.net_result) == (D("0.000"), D("100.000"), D("-100.000"))
    assert result.partnership_id is None


def test_a_supplier_partner_in_several_lots_has_each_lot_settled_on_its_own(organization, actor, cold_room, partner):
    other = SupplierFactory.create(organization=organization, name="Surgelés du Sahel")
    profit_lot = receive(organization, cold_room, "10.000", name="Crevette")
    loss_lot = receive(organization, cold_room, "10.000", name="Poulpe")
    third_lot = receive(organization, cold_room, "10.000", name="Seiche")
    partnership(organization, actor, profit_lot, partner, capital="500.000", profit="40", loss="25")
    partnership(organization, actor, loss_lot, partner, capital="300.000", profit="40", loss="25")
    partnership(organization, actor, third_lot, other, capital="200.000", profit="30", loss="20")
    sell(organization, actor, cold_room, profit_lot, "10.000", "35.000")  # +150.000
    sell(organization, actor, cold_room, loss_lot, "10.000", "12.000")  # −80.000
    sell(organization, actor, cold_room, third_lot, "10.000", "25.000")  # +50.000

    first, second, third = (close(organization, actor, lot) for lot in (profit_lot, loss_lot, third_lot))

    # 150 × 40 % = 60.000; 80 × 25 % = 20.000 from the capital; 50 × 30 % = 15.000.
    assert (first.partner_share, first.capital_to_return) == (D("60.000"), D("500.000"))
    assert (second.partner_share, second.capital_to_return) == (D("-20.000"), D("280.000"))
    assert (third.partner_share, third.capital_to_return) == (D("15.000"), D("200.000"))
    capital = partnerships.capital_by_partner(organization)
    assert (capital[partner.pk].lots, capital[partner.pk].capital) == (2, D("780.000"))
    assert (capital[other.pk].lots, capital[other.pk].capital) == (1, D("200.000"))


# ---- Concurrency ----


def run_at_once(count: int, action) -> list[Exception]:
    errors: list[Exception] = []
    start = threading.Barrier(count)

    def run() -> None:
        try:
            start.wait()
            action()
        except Exception as error:  # noqa: BLE001 - every failure is reported to the test
            errors.append(error)
        finally:
            connection.close()

    threads = [threading.Thread(target=run) for _ in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    return errors


@pytest.mark.django_db(transaction=True, serialized_rollback=True)
def test_two_closings_of_the_same_lot_at_once_freeze_it_once():
    owner = MembershipFactory.create(role=Role.OWNER)
    organization, actor = owner.organization, owner.user
    from apps.inventory.tests.factories import StockLocationFactory

    cold_room = StockLocationFactory.create(organization=organization, counter_sales=True)
    partner = SupplierFactory.create(organization=organization)
    batch = receive(organization, cold_room, "10.000")
    partnership(organization, actor, batch, partner, capital="100.000", loss="50")
    sell(organization, actor, cold_room, batch, "10.000", "10.000")  # a loss of 100.000

    errors = run_at_once(3, lambda: close(organization, actor, batch))

    assert len(errors) == 2
    assert all(isinstance(error, ValidationError) for error in errors)
    assert LotResult.objects.filter(batch=batch).count() == 1
    # The loss share (50.000) is taken from the capital once.
    assert ledger(organization, batch) == [
        (CapitalEntryKind.CONTRIBUTION, D("100.000")),
        (CapitalEntryKind.LOSS_DEDUCTION, D("-50.000")),
    ]


# ---- API ----


def url(batch, action: str = "result") -> str:
    return f"/api/v1/lots/{batch.pk}/{action}"


def test_the_api_shows_the_live_result_then_the_frozen_one(api, organization, actor, finished_lot):
    answer = api.get(url(finished_lot))

    assert answer.status_code == 200
    data: dict[str, Any] = answer.json()
    assert (data["state"], data["can_close"], data["closing"]) == ("open", True, None)
    assert data["result"]["net_result"] == "715.000"
    assert data["result"]["partner"]["share"] == "286.000"
    assert [step["code"] for step in data["result"]["steps"]][:4] == ["revenue", "cogs", "spoilage", "cost"]
    assert len(data["result"]["sales"]) == 3

    refused = api.post(url(finished_lot, "close"), {}, format="json")
    assert refused.status_code == 400
    assert "costs_confirmed" in refused.json()

    closed = api.post(url(finished_lot, "close"), {"costs_confirmed": True}, format="json")
    assert closed.status_code == 200
    assert closed.json()["state"] == "closed"
    cost(organization, actor, finished_lot, "fuel", "15.000")
    later = api.get(url(finished_lot)).json()
    assert (later["result"]["net_result"], later["live_net_result"]) == ("715.000", "700.000")

    reopened = api.post(url(finished_lot, "reopen"), {"reason": "Erreur de prix"}, format="json")
    assert reopened.status_code == 200
    assert reopened.json()["state"] == "open"
    assert reopened.json()["history"][0]["reopen_reason"] == "Erreur de prix"


def test_lot_figures_list_only_the_closed_lots_among_the_ones_asked_for(api, organization, actor, finished_lot):
    asked = f"/api/v1/lot-figures?batch_ids={finished_lot.pk},999999"
    assert api.get(asked).json() == []

    close(organization, actor, finished_lot)
    rows = api.get(asked).json()

    assert [(row["batch_id"], row["outcome"], row["net_result"]) for row in rows] == [
        (finished_lot.pk, "profit", "715.000")
    ]
    assert rows[0]["partner_share"] == "286.000"
    assert api.get("/api/v1/lot-figures?batch_ids=abc").status_code == 400


@pytest.mark.parametrize(
    ("role", "read", "write"),
    [(Role.ACCOUNTANT, 200, 403), (Role.MANAGER, 403, 403), (Role.DRIVER, 403, 403)],
)
def test_only_the_owner_closes_and_the_accountant_reads(organization, finished_lot, role, read, write):
    client = client_for(member(organization, role))

    assert client.get(url(finished_lot)).status_code == read
    assert client.post(url(finished_lot, "close"), {"costs_confirmed": True}, format="json").status_code == write


def test_a_lot_of_another_organization_is_not_found(finished_lot):
    stranger = client_for(MembershipFactory.create(role=Role.OWNER))

    assert stranger.get(url(finished_lot)).status_code == 404
    assert stranger.post(url(finished_lot, "close"), {"costs_confirmed": True}, format="json").status_code == 404


def test_employee_days_on_a_lot_appear_with_their_cost(organization, actor, cold_room):
    batch = receive(organization, cold_room, "5.000")
    employee_day(organization, actor, batch, "1", salary="1300.000")

    result = selectors.live_result(organization, batch_id=batch.pk)

    assert [(group.kind, group.total) for group in result.cost_groups] == [("employee", D("50.000"))]
