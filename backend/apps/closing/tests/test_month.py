"""The month-end valuation, cost of goods sold and the monthly closing (P6-T05, P6-T06, D-073, D-074)."""

import datetime as dt
from decimal import Decimal

import pytest
from django.core.exceptions import ValidationError
from django.urls import reverse
from django.utils import timezone

from apps.catalog.tests.factories import ProductFactory
from apps.closing import month_services, monthly
from apps.closing.models import MonthlyClosingStatus
from apps.core.models import AuditLog, Role
from apps.expenses import selectors as expense_selectors
from apps.expenses import services as expense_services
from apps.hr import services as hr
from apps.hr.tests.factories import EmployeeFactory
from apps.inventory import services as inventory
from apps.inventory.models import LossReason, MovementKind
from apps.inventory.tests.factories import BatchFactory
from apps.partners.tests.factories import CustomerFactory
from apps.partnerships import services as partnership_services
from apps.sales import services as sales

from .conftest import client_for, member

pytestmark = pytest.mark.django_db
D = Decimal


def moment(day: dt.date, hour: int = 10) -> dt.datetime:
    return timezone.make_aware(dt.datetime.combine(day, dt.time(hour)))


@pytest.fixture
def last_month():
    """The first day of the previous month."""
    today = timezone.localdate()
    first = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)
    return first


def day_of(first: dt.date, number: int) -> dt.date:
    return first.replace(day=number)


def build_month(organization, actor, cold_room, first):
    """The hand-made month, dated inside `first`'s month. Returns the batch."""
    product = ProductFactory.create(organization=organization, name="Dorade")
    batch = BatchFactory.create(
        organization=organization, product=product, unit_cost=D("20.000"), received_on=day_of(first, 2)
    )
    inventory.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity="100.000",
        to_location=cold_room,
        occurred_at=moment(day_of(first, 2)),
    )
    sales.create_sale(
        organization=organization,
        actor=actor,
        customer=CustomerFactory.create(organization=organization),
        location=cold_room,
        lines=[{"product": product, "quantity": "40.000", "unit_price": "32.500"}],
        sold_at=moment(day_of(first, 4)),
        payment={"paid_in_full": True, "payment_method": "cash"},
        confirm=True,
    )
    inventory.record_loss(
        organization=organization,
        actor=actor,
        location=cold_room,
        product=product,
        quantity="5.000",
        reason=LossReason.SPOILED,
        lost_on=day_of(first, 6),
        may_approve=True,
    )
    expense_services.create_expense(
        organization=organization,
        actor=actor,
        spent_on=day_of(first, 7),
        category=expense_selectors.category_by_code(organization, "transport"),
        amount="120.000",
        approve=True,
    )
    return batch


def test_the_month_is_worked_out_from_sales_not_from_purchases(organization, actor, cold_room, last_month):
    build_month(organization, actor, cold_room, last_month)

    report = monthly.month_report(organization, month=last_month)

    assert report.sales_count == 1
    assert report.revenue == D("1300.000")
    assert report.cogs == D("800.000")  # 40 kg × 20.000, not the 2 000.000 bought
    assert report.gross_margin == D("500.000")
    assert (report.spoilage, report.spoilage_quantity) == (D("100.000"), D("5.000"))
    assert report.expenses_total == D("120.000")
    assert report.personnel == D("0.000")
    assert report.net_result == D("280.000")
    # Unsold stock stays an asset: 55 kg at 20.000.
    assert report.purchases == D("2000.000")
    assert report.opening_value == D("0.000")
    assert report.closing_value == D("1100.000")
    assert report.rounding_difference == D("0.000")
    assert [(row.kind, row.value) for row in report.ledger] == [
        ("receipt", D("2000.000")),
        ("sale", D("-800.000")),
        ("loss", D("-100.000")),
    ]
    assert [(row.code, row.total) for row in report.expense_categories] == [("transport", D("120.000"))]


def test_partner_cost_participation_groups_the_months_shared_costs_by_category(
    organization, actor, cold_room, last_month, partner
):
    """A partnership lot's costs this month should show up next to "Dépenses approuvées", grouped by
    category and by partner, so the partner sees where the charge went (owner request, 2026-10-13)."""
    product = ProductFactory.create(organization=organization, name="Loup")
    batch = BatchFactory.create(
        organization=organization, product=product, unit_cost=D("15.000"), received_on=day_of(last_month, 3)
    )
    inventory.post_movement(
        organization=organization,
        actor=None,
        kind=MovementKind.RECEIPT,
        batch=batch,
        quantity="50.000",
        to_location=cold_room,
        occurred_at=moment(day_of(last_month, 3)),
    )
    partnership_services.create_partnership(
        organization=organization,
        actor=actor,
        batch=batch,
        partner=partner,
        owner_capital="500.000",
        partner_capital="500.000",
        profit_rate="50",
        loss_rate="50",
    )
    expense_services.create_expense(
        organization=organization,
        actor=actor,
        spent_on=day_of(last_month, 5),
        category=expense_selectors.category_by_code(organization, "transport"),
        amount="60.000",
        batch=batch,
        approve=True,
    )
    employee = EmployeeFactory.create(organization=organization, monthly_salary=D("2600.000"))
    hr.add_lot_work_day(
        organization=organization,
        actor=actor,
        employee=employee,
        work_date=day_of(last_month, 6),
        days="1.00",
        batch=batch,
    )
    # An own-stock lot's cost (no partner): never counted in a partner's participation.
    expense_services.create_expense(
        organization=organization,
        actor=actor,
        spent_on=day_of(last_month, 5),
        category=expense_selectors.category_by_code(organization, "transport"),
        amount="999.000",
        approve=True,
    )

    report = monthly.month_report(organization, month=last_month)

    [share] = report.partner_cost_shares
    assert (share.partner_id, share.partner_name, share.total) == (partner.pk, partner.name, D("160.000"))
    transport, employees = share.categories
    assert (transport.key, transport.name, transport.is_employee, transport.amount, transport.count) == (
        "Transport",
        "Transport",
        False,
        D("60.000"),
        1,
    )
    assert transport.category_id == expense_selectors.category_by_code(organization, "transport").pk
    assert (employees.key, employees.name, employees.is_employee, employees.amount, employees.count) == (
        "employee",
        "",
        True,
        D("100.000"),
        1,
    )
    assert employees.category_id is None


def test_the_stock_valuation_of_a_past_day_does_not_change_later(organization, actor, cold_room, last_month):
    batch = build_month(organization, actor, cold_room, last_month)
    end = monthly.month_end(last_month)
    before = monthly.month_report(organization, month=last_month)

    # Today the lot is sold again: last month's valuation stays what the ledger said that day.
    sales.create_sale(
        organization=organization,
        actor=actor,
        customer=CustomerFactory.create(organization=organization),
        location=cold_room,
        lines=[{"product": batch.product, "quantity": "10.000", "unit_price": "30.000"}],
        confirm=True,
    )
    after = monthly.month_report(organization, month=last_month)

    assert (before.closing_value, after.closing_value) == (D("1100.000"), D("1100.000"))
    assert after.net_result == before.net_result
    [row] = after.stock_rows
    assert (row.quantity, row.value) == (D("55.000"), D("1100.000"))
    # And the next month opens with it.
    next_first = end + dt.timedelta(days=1)
    assert monthly.month_report(organization, month=next_first).opening_value == D("1100.000")


def test_checks_block_a_review_until_expenses_and_losses_are_decided(organization, actor, cold_room, last_month):
    build_month(organization, actor, cold_room, last_month)
    expense_services.create_expense(
        organization=organization,
        actor=actor,
        spent_on=day_of(last_month, 8),
        category=expense_selectors.category_by_code(organization, "transport"),
        amount="30.000",
    )  # a draft

    report = monthly.month_report(organization, month=last_month)

    failed = {check.code: check for check in report.checks if not check.ok}
    assert set(failed) == {"expenses_approved"}
    assert (failed["expenses_approved"].count, failed["expenses_approved"].amount) == (1, D("30.000"))
    with pytest.raises(ValidationError, match="dépenses"):
        month_services.review_month(organization=organization, actor=actor, month=last_month)
    assert report.net_result == D("280.000")  # the draft is not counted


def test_the_current_month_cannot_be_closed(organization, actor):
    with pytest.raises(ValidationError, match="pas terminé"):
        month_services.review_month(organization=organization, actor=actor, month=timezone.localdate())


def test_review_then_approval_freezes_the_figures(organization, actor, cold_room, last_month):
    build_month(organization, actor, cold_room, last_month)
    accountant = member(organization, Role.ACCOUNTANT).user

    with pytest.raises(ValidationError, match="vérifier"):
        month_services.approve_month(organization=organization, actor=actor, month=last_month)
    reviewed = month_services.review_month(
        organization=organization, actor=accountant, month=last_month, notes="Contrôlé avec les relevés"
    )
    assert (reviewed.status, reviewed.net_result, reviewed.closing_stock_value) == (
        MonthlyClosingStatus.REVIEWED,
        D("280.000"),
        D("1100.000"),
    )
    approved = month_services.approve_month(organization=organization, actor=actor, month=last_month)

    assert approved.pk == reviewed.pk
    assert (approved.status, approved.approved_by) == (MonthlyClosingStatus.APPROVED, actor)
    assert approved.data["net_result"] == "280.000"
    assert approved.data["stock"]["closing_value"] == "1100.000"
    assert AuditLog.objects.filter(action__in=["month.reviewed", "month.approved"]).count() == 2
    with pytest.raises(ValidationError, match="déjà approuvé"):
        month_services.review_month(organization=organization, actor=accountant, month=last_month)


def test_figures_that_moved_since_the_review_must_be_reviewed_again(organization, actor, cold_room, last_month):
    build_month(organization, actor, cold_room, last_month)
    month_services.review_month(organization=organization, actor=actor, month=last_month)
    expense_services.create_expense(
        organization=organization,
        actor=actor,
        spent_on=day_of(last_month, 9),
        category=expense_selectors.category_by_code(organization, "transport"),
        amount="30.000",
        approve=True,
    )

    with pytest.raises(ValidationError, match="ont changé"):
        month_services.approve_month(organization=organization, actor=actor, month=last_month)
    again = month_services.review_month(organization=organization, actor=actor, month=last_month)
    approved = month_services.approve_month(organization=organization, actor=actor, month=last_month)

    assert again.net_result == approved.net_result == D("250.000")


def test_a_reopened_month_keeps_its_history_and_needs_a_reason(organization, actor, cold_room, last_month):
    build_month(organization, actor, cold_room, last_month)
    month_services.review_month(organization=organization, actor=actor, month=last_month)
    month_services.approve_month(organization=organization, actor=actor, month=last_month)

    with pytest.raises(ValidationError):
        month_services.reopen_month(organization=organization, actor=actor, month=last_month, reason=" ")
    reopened = month_services.reopen_month(
        organization=organization, actor=actor, month=last_month, reason="Facture d'électricité oubliée"
    )

    assert reopened.status == MonthlyClosingStatus.REOPENED
    assert reopened.reopen_reason == "Facture d'électricité oubliée"
    # A new review makes a new closing; the reopened one stays as history.
    fresh = month_services.review_month(organization=organization, actor=actor, month=last_month)
    assert fresh.pk != reopened.pk
    assert AuditLog.objects.filter(action="month.reopened").count() == 1


def test_an_approved_month_does_not_move_when_something_is_recorded_after(
    organization, actor, cold_room, last_month, api
):
    build_month(organization, actor, cold_room, last_month)
    month_services.review_month(organization=organization, actor=actor, month=last_month)
    month_services.approve_month(organization=organization, actor=actor, month=last_month)
    expense_services.create_expense(
        organization=organization,
        actor=actor,
        spent_on=day_of(last_month, 9),
        category=expense_selectors.category_by_code(organization, "transport"),
        amount="30.000",
        approve=True,
    )

    data = api.get(reverse("month-detail", args=[last_month.strftime("%Y-%m")])).json()

    assert data["state"] == "approved"
    assert data["report"]["net_result"] == "280.000"  # frozen
    assert data["live_net_result"] == "250.000"  # what it would be now: the screen shows the difference


def test_the_api_roles_the_accountant_reviews_and_only_the_owner_approves(organization, actor, cold_room, last_month):
    build_month(organization, actor, cold_room, last_month)
    month = last_month.strftime("%Y-%m")
    accountant = client_for(member(organization, Role.ACCOUNTANT))
    manager = client_for(member(organization, Role.MANAGER))
    driver = client_for(member(organization, Role.DRIVER))
    owner = client_for(member(organization, Role.OWNER))

    assert manager.get(reverse("month-detail", args=[month])).status_code == 403
    assert driver.get(reverse("month-list")).status_code == 403
    listed = accountant.get(reverse("month-list")).json()
    assert len(listed) == 12
    assert listed[1]["month"] == last_month.isoformat()

    detail = accountant.get(reverse("month-detail", args=[month])).json()
    assert detail["state"] == "open"
    assert (detail["can_review"], detail["can_approve"]) == (True, False)
    assert detail["report"]["net_result"] == "280.000"

    assert accountant.post(reverse("month-approve", args=[month])).status_code == 403
    reviewed = accountant.post(reverse("month-review", args=[month]), {"notes": "ok"}, format="json")
    assert reviewed.status_code == 200, reviewed.json()
    assert reviewed.json()["state"] == "reviewed"
    assert reviewed.json()["can_approve"] is True
    assert accountant.post(reverse("month-reopen", args=[month]), {"reason": "x"}, format="json").status_code == 403

    approved = owner.post(reverse("month-approve", args=[month]))
    assert approved.status_code == 200, approved.json()
    assert approved.json()["state"] == "approved"
    assert approved.json()["closing"]["reviewed_by_name"]
    assert owner.post(reverse("month-reopen", args=[month]), {"reason": ""}, format="json").status_code == 400
    assert owner.get(reverse("month-detail", args=["nonsense"])).status_code == 404
