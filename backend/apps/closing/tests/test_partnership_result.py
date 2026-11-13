"""A partnership's result: its rate on the sum of the lines it shares (D-320 Q31, D-325)."""

from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError

from apps.closing import engine, selectors, services
from apps.closing.models import LotResultStatus, PartnershipResult
from apps.partnerships import selectors as partnerships
from apps.partnerships.models import PartnershipLine, PartnershipStatus

from .conftest import cost, partnership, receive, sell

pytestmark = pytest.mark.django_db
D = Decimal


def terms(profit: str, loss: str, capital: str = "1000.000", partner_id: int = 1) -> engine.PartnershipTerms:
    return engine.PartnershipTerms(
        partnership_id=partner_id,
        partner_id=partner_id,
        partner_name=f"Partenaire {partner_id}",
        owner_capital=D("1000.000"),
        partner_capital=D(capital),
        profit_rate=D(profit),
        loss_rate=D(loss),
    )


def line(batch_id: int, net: str) -> engine.SharedLine:
    return engine.SharedLine(batch_id=batch_id, batch_number=f"L-0042-{batch_id}", product_name="", net_result=D(net))


# ---- The engine ----


def test_golden_shrimp_and_squid_shared_at_fifty_percent_give_the_partner_950():
    # The owner's example (D-320): shrimp +2 400, squid −500, shared at 50 %; the sardine (+300) is not shared.
    result = engine.partnership_result(terms("50", "50"), (line(1, "2400.000"), line(2, "-500.000")))

    assert result.net_result == D("1900.000")
    assert result.outcome == "profit"
    assert result.partner.share == D("950.000")
    assert result.owner_share == D("950.000")
    assert result.partner.payable_to_partner == D("1950.000")
    assert [step.code for step in result.steps][:3] == ["line", "line", "net_result"]


def test_golden_two_partners_on_one_line_each_take_their_rate_and_the_owner_the_rest():
    # Shrimp +1 000 shared by Ali at 40 % and Salah at 30 %: 400 and 300, the owner 300.
    shrimp = (line(1, "1000.000"),)
    ali = engine.partnership_result(terms("40", "40", partner_id=1), shrimp)
    salah = engine.partnership_result(terms("30", "30", partner_id=2), shrimp)

    assert (ali.partner.share, salah.partner.share) == (D("400.000"), D("300.000"))
    assert D("1000.000") - ali.partner.share - salah.partner.share == D("300.000")


def test_a_loss_sum_uses_the_loss_rate_and_is_taken_from_the_capital():
    # +200 and −500: a loss of 300, at the loss rate (25 %), not the profit rate (40 %).
    result = engine.partnership_result(terms("40", "25"), (line(1, "200.000"), line(2, "-500.000")))

    assert result.outcome == "loss"
    assert result.partner.rate == D("25")
    assert result.partner.share == D("-75.000")
    assert (result.partner.capital_deducted, result.partner.capital_to_return) == (D("75.000"), D("925.000"))
    assert result.owner_share == D("-225.000")


def test_the_rate_is_rounded_once_on_the_sum_not_per_line():
    # 0.001 + 0.001 at 50 %: 0.0005 + 0.0005 rounded per line would give 0.002; on the sum 0.001.
    result = engine.partnership_result(terms("50", "50"), (line(1, "0.001"), line(2, "0.001")))

    assert result.partner.share == D("0.001")
    assert result.partner.share + result.owner_share == result.net_result


def test_one_line_gives_that_lines_share_to_the_millime():
    for net in ("715.000", "-450.000", "0.000", "333.333", "-0.001"):
        alone = engine.partner_share(terms("40", "25"), D(net))
        result = engine.partnership_result(terms("40", "25"), (line(1, net),))
        assert result.partner == alone


# ---- Closing the lines of a real lot ----


@pytest.fixture
def shared_lot(organization, actor, cold_room, partner):
    """Shrimp and squid of one purchase shared with the partner at 50 % (capital 1 000.000), sardine the owner's:
    100 kg of each bought at 20.000; shrimp sold at 44.000 (+2 400), squid at 15.000 (−500), sardine at 23.000."""
    shrimp = receive(organization, cold_room, "100.000", name="Crevette")
    squid = receive(organization, cold_room, "100.000", name="Calamar")
    sardine = receive(organization, cold_room, "100.000", name="Sardine")
    shared = partnership(organization, actor, shrimp, partner, profit="50", loss="50")
    # Several lines per partnership come with P6-T08c2's form (PR 2); the result already nets them.
    PartnershipLine.objects.create(organization=organization, partnership=shared, batch=squid)
    sell(organization, actor, cold_room, shrimp, "100.000", "44.000")
    sell(organization, actor, cold_room, squid, "100.000", "15.000")
    sell(organization, actor, cold_room, sardine, "100.000", "23.000")
    return shared, shrimp, squid, sardine


def close(organization, actor, batch):
    return services.close_lot(organization=organization, actor=actor, batch_id=batch.pk, costs_confirmed=True)


def test_the_partnership_closes_when_its_last_line_closes_and_nets_its_lines(organization, actor, shared_lot, partner):
    shared, shrimp, squid, sardine = shared_lot

    first = close(organization, actor, shrimp)
    # A line of a partnership of several lines carries no share of its own.
    assert (first.net_result, first.partner_share, first.partnership_id) == (D("2400.000"), D("0.000"), None)
    assert selectors.closed_partnership_result_of(organization, partnership_id=shared.pk) is None
    assert partnerships.partnership_of(organization, shared.pk).status == PartnershipStatus.OPEN

    close(organization, actor, squid)

    frozen = selectors.closed_partnership_result_of(organization, partnership_id=shared.pk)
    assert frozen is not None
    assert (frozen.net_result, frozen.partner_share, frozen.owner_share) == (
        D("1900.000"),
        D("950.000"),
        D("950.000"),
    )
    assert frozen.batch_ids == [shrimp.pk, squid.pk]
    assert partnerships.partnership_of(organization, shared.pk).status == PartnershipStatus.CLOSED
    # The sardine is still open and never in the partner's numbers.
    assert selectors.closed_result_of(organization, batch_id=sardine.pk) is None
    assert sardine.pk not in frozen.batch_ids

    settlement = services.settle_lot(
        organization=organization,
        actor=actor,
        partnership_id=shared.pk,
        payments=[{"amount": "1950.000", "method": "cash"}],
    )
    assert (settlement.capital_returned, settlement.lot_share, settlement.share_paid) == (
        D("1000.000"),
        D("950.000"),
        D("950.000"),
    )
    assert settlement.partnership_result_id == frozen.pk
    assert settlement.lot_result_id is None


def test_a_line_shared_with_others_is_settled_by_partnership_not_by_line(organization, actor, shared_lot):
    shared, shrimp, squid, _sardine = shared_lot
    close(organization, actor, shrimp)
    close(organization, actor, squid)

    # By the line still works: one partnership shares it.
    frozen = selectors.closed_partnership_result_of(organization, partnership_id=shared.pk)
    assert frozen is not None
    preview = selectors.settlement_preview(organization, frozen)
    assert preview.total == D("1950.000")
    services.settle_lot(
        organization=organization, actor=actor, batch_id=squid.pk, payments=[{"amount": "1950.000", "method": "cash"}]
    )
    assert partnerships.partnership_of(organization, shared.pk).status == PartnershipStatus.SETTLED


def test_reopening_one_line_reopens_its_partnership_and_gives_the_loss_back(organization, actor, cold_room, partner):
    shrimp = receive(organization, cold_room, "100.000", name="Crevette")
    squid = receive(organization, cold_room, "100.000", name="Calamar")
    shared = partnership(organization, actor, shrimp, partner, profit="50", loss="50")
    PartnershipLine.objects.create(organization=organization, partnership=shared, batch=squid)
    sell(organization, actor, cold_room, shrimp, "100.000", "21.000")  # +100
    sell(organization, actor, cold_room, squid, "100.000", "15.000")  # −500
    close(organization, actor, shrimp)
    squid_result = close(organization, actor, squid)

    frozen = selectors.closed_partnership_result_of(organization, partnership_id=shared.pk)
    assert frozen is not None
    # −400 at 50 %: 200 taken from the capital.
    assert (frozen.net_result, frozen.partner_share, frozen.capital_deducted) == (
        D("-400.000"),
        D("-200.000"),
        D("200.000"),
    )
    live = partnerships.partnership_of(organization, shared.pk)
    assert partnerships.capital_balance(live) == D("800.000")

    services.reopen_lot(result=squid_result, actor=actor, reason="Facture oubliée")

    frozen.refresh_from_db()
    assert frozen.status == LotResultStatus.REOPENED
    live = partnerships.partnership_of(organization, shared.pk)
    assert live.status == PartnershipStatus.OPEN
    assert partnerships.capital_balance(live) == D("1000.000")
    # The shrimp stays closed; closing the squid again freezes a new partnership result.
    close(organization, actor, squid)
    assert PartnershipResult.objects.filter(partnership=shared).count() == 2


def test_a_late_cost_on_one_line_moves_the_partnerships_net(organization, actor, shared_lot):
    shared, shrimp, squid, _sardine = shared_lot
    close(organization, actor, shrimp)
    close(organization, actor, squid)
    cost(organization, actor, shrimp, "cold_storage", "100.000")

    frozen = selectors.closed_partnership_result_of(organization, partnership_id=shared.pk)
    assert frozen is not None
    drift = selectors.late_drift(organization, frozen)
    assert drift is not None
    # 1 900 -> 1 800: the share goes from 950 to 900.
    assert (drift.drift, drift.pending_basis, drift.pending_share) == (D("-100.000"), D("-100.000"), D("-50.000"))
    assert services.book_late_adjustments(organization=organization, actor=actor, batch_id=shrimp.pk) is True
    assert services.book_late_adjustments(organization=organization, actor=actor, batch_id=squid.pk) is False


def test_a_line_with_pending_terms_does_not_close(organization, actor, cold_room, partner):
    from apps.partnerships import services as partnership_services

    shrimp = receive(organization, cold_room, "10.000", name="Crevette")
    partnership_services.designate_partner(organization=organization, actor=actor, batch=shrimp, partner=partner)
    sell(organization, actor, cold_room, shrimp, "10.000", "30.000")

    with pytest.raises(ValidationError, match="pourcentages"):
        close(organization, actor, shrimp)


# ---- The migration of lots closed before D-325 ----


def test_the_migration_gives_each_old_partner_result_its_partnership_result(organization, actor, finished_lot):
    import importlib

    from django.db import connection
    from django.db.migrations.loader import MigrationLoader

    from apps.partnerships.models import CapitalEntry, PartnerSettlement, ProfitShareEntry

    line_result = close(organization, actor, finished_lot)
    services.settle_lot(
        organization=organization,
        actor=actor,
        batch_id=finished_lot.pk,
        payments=[{"amount": "1286.000", "method": "cash"}],
    )
    expected = PartnershipResult.objects.get()
    # As the data stood before D-325: no partnership result, the ledgers by line result only.
    with connection.cursor() as cursor:
        cursor.execute("DELETE FROM closing_partnershipresult")
        for table in ("capitalentry", "profitshareentry", "partnersettlement"):
            cursor.execute(f"UPDATE partnerships_{table} SET partnership_result_id = NULL")

    migration = importlib.import_module("apps.closing.migrations.0004_partnership_results_of_old_lots")
    # The models as the migration sees them (plain managers, as in `migrate`).
    state = MigrationLoader(connection).project_state(("closing", "0004_partnership_results_of_old_lots"))
    migration.forwards(state.apps, None)

    migrated = PartnershipResult.objects.get()
    fields = ("partnership_id", "status", "net_result", "partner_share", "owner_share", "capital_deducted")
    assert [getattr(migrated, name) for name in fields] == [getattr(expected, name) for name in fields]
    assert migrated.lot_result_ids == [line_result.pk]
    assert migrated.data["partner"] == expected.data["partner"]
    assert [step["code"] for step in migrated.data["steps"]] == [step["code"] for step in expected.data["steps"]]
    for model in (CapitalEntry, ProfitShareEntry, PartnerSettlement):
        rows = model.objects.filter(lot_result_id=line_result.pk)
        assert rows.exists()
        assert set(rows.values_list("partnership_result_id", flat=True)) == {migrated.pk}
