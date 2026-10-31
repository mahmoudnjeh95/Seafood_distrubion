"""Which audited actions tell someone, and what (D-175).

Read from the audit entry each service already writes (ARCHITECTURE §4.9), so no service has to know about
notifications. A driver's action tells the office; the office's action on a driver's day, load, purchase, loss,
expense or truck tells that driver. `services.tell_office` and `services.tell_driver` check who is who.
"""

from collections.abc import Callable
from decimal import Decimal
from typing import TYPE_CHECKING, Any, cast

from django.utils import timezone

from apps.core.models import AuditLog, User
from apps.fleet import selectors as fleet

from . import services

if TYPE_CHECKING:
    from apps.dayclose.models import DayClosing, SyncProblem
    from apps.expenses.models import Expense
    from apps.fleet.models import DriverDay, TruckAssignment
    from apps.inventory.models import StockLoss, Transfer
    from apps.partners.models import Customer
    from apps.purchasing.models import FieldPurchase
    from apps.sales.models import CustomerPayment, Sale
    from apps.storefront.models import WebRequest


def _name(user: User) -> str:
    return user.get_full_name() or user.username


def _amount(value: Decimal | None) -> str:
    return f"{value or Decimal(0):.3f}"


def _office(entry: AuditLog, kind: str, params: dict[str, Any], link: str = "") -> None:
    if entry.actor is None:
        return  # done by the system, not by a driver
    services.tell_office(
        organization=entry.organization,
        driver=entry.actor,
        kind=kind,
        params={"driver": _name(entry.actor), **params},
        link=link,
    )


def _driver(entry: AuditLog, driver: User | None, kind: str, params: dict[str, Any], link: str = "") -> None:
    services.tell_driver(
        organization=entry.organization, driver=driver, actor=entry.actor, kind=kind, params=params, link=link
    )


# ---- What a driver does, told to the office ----


def _day_opened(entry: AuditLog) -> None:
    day = cast("DriverDay", entry.target)
    _office(entry, "day_started", {"truck": day.truck.location.name}, "/journees")


def _day_sent(entry: AuditLog) -> None:
    closing = cast("DayClosing", entry.target)
    kind = "day_sent" if entry.action == "day_closing.submitted" else "day_resent"
    # The office counts the cash when the driver is back (D-213): the send says only that the day came.
    params = {"date": closing.driver_day.date.isoformat()}
    _office(entry, kind, params, "/journees")


def _sale_confirmed(entry: AuditLog) -> None:
    sale = cast("Sale", entry.target)
    if entry.action == "sale.confirmed" and sale.delivery_status:
        return  # the BL of a load: its delivery tells the office (`_delivered`)
    kind = "sale_confirmed" if entry.action == "sale.confirmed" else "credit_requested"
    params = {"number": sale.number, "customer": sale.customer.name, "total": _amount(sale.total)}
    _office(entry, kind, params, f"/ventes/{sale.pk}")


def _payment_recorded(entry: AuditLog) -> None:
    payment = cast("CustomerPayment", entry.target)
    params = {"number": payment.number, "customer": payment.customer.name, "amount": _amount(payment.amount)}
    _office(entry, "payment_recorded", params, "/reglements")


def _expense_created(entry: AuditLog) -> None:
    expense = cast("Expense", entry.target)
    params = {"number": expense.number, "category": expense.category.name, "amount": _amount(expense.amount)}
    _office(entry, "expense_created", params, f"/charges/{expense.pk}")


def _loss_recorded(entry: AuditLog) -> None:
    loss = cast("StockLoss", entry.target)
    kind = "loss_waiting" if loss.status == "pending" else "loss_recorded"
    params = {"number": loss.number, "product": loss.product.name, "quantity": f"{loss.quantity:.3f}"}
    _office(entry, kind, params, f"/stock/pertes/{loss.pk}")


def _purchase_sent(entry: AuditLog) -> None:
    purchase = cast("FieldPurchase", entry.target)
    supplier = purchase.supplier.name if purchase.supplier is not None else purchase.proposed_supplier
    kind = "purchase_sent" if entry.action == "field_purchase.submitted" else "purchase_edited"
    _office(entry, kind, {"number": purchase.number, "supplier": supplier}, f"/achats/terrain/{purchase.pk}")


def _customer_created(entry: AuditLog) -> None:
    customer = cast("Customer", entry.target)
    _office(entry, "customer_created", {"name": customer.name}, f"/clients/{customer.pk}")


def _sync_problem(entry: AuditLog) -> None:
    problem = cast("SyncProblem", entry.target)
    _office(entry, "sync_problem", {"label": problem.label}, "/journees")


def _delivered(entry: AuditLog) -> None:
    sale = cast("Sale", entry.target)
    kind = "delivery_partial" if sale.delivery_status == "partial" else "delivery_done"
    params = {
        "number": sale.number,
        "customer": sale.customer.name,
        "total": _amount(sale.total),
        "note": sale.delivery_note,
    }
    _office(entry, kind, params, f"/ventes/{sale.pk}")


def _load_bl_driver(entry: AuditLog, sale: "Sale") -> User | None:
    """The driver who has the truck of a load's BL on the day it was loaded (D-178)."""
    return fleet.driver_of_location(
        entry.organization, location_id=sale.location_id, on=timezone.localtime(sale.sold_at).date()
    )


def _sale_cancelled(entry: AuditLog) -> None:
    sale = cast("Sale", entry.target)
    if not sale.delivery_status:
        return
    params = {"number": sale.number, "customer": sale.customer.name, "note": sale.delivery_note}
    # The driver gave it up at the client's (or at the end of the day): the office hears; the office gave it up:
    # the driver hears. Each `tell_*` checks who acted.
    _office(entry, "delivery_cancelled", params, f"/ventes/{sale.pk}")
    _driver(entry, _load_bl_driver(entry, sale), "bl_cancelled", params, "/livraisons")


def _bl_changed(entry: AuditLog) -> None:
    sale = cast("Sale", entry.target)
    params = {"number": sale.number, "customer": sale.customer.name, "version": str(sale.version)}
    _driver(entry, _load_bl_driver(entry, sale), "bl_changed", params, "/livraisons")


# ---- What the office does, told to the driver ----


def _transfer_validated(entry: AuditLog) -> None:
    transfer = cast("Transfer", entry.target)
    if transfer.kind == "return":
        _office(entry, "truck_returned", {"number": transfer.number}, f"/stock/transferts/{transfer.pk}")
    elif transfer.kind == "load":
        driver = fleet.driver_of_location(
            entry.organization, location_id=transfer.to_location_id, on=transfer.transferred_on
        )
        params = {"number": transfer.number, "truck": transfer.to_location.name}
        _driver(entry, driver, "load_validated", params, "/stock")


def _day_reviewed(entry: AuditLog) -> None:
    closing = cast("DayClosing", entry.target)
    day = closing.driver_day
    params: dict[str, Any] = {"date": day.date.isoformat()}
    if entry.action == "day_closing.approved":
        _driver(entry, day.driver, "day_approved", params, f"/historique/{day.pk}")
    elif entry.action == "day_closing.justification_requested":
        _driver(entry, day.driver, "day_justification", {**params, "reason": closing.review_note}, "/cloture")
    else:
        _driver(entry, day.driver, "day_reopened", params, "/cloture")


def _purchase_decided(entry: AuditLog) -> None:
    purchase = cast("FieldPurchase", entry.target)
    kind = {
        "field_purchase.validated": "purchase_validated",
        "field_purchase.refused": "purchase_refused",
        "field_purchase.edited": "purchase_changed",
    }[entry.action]
    params = {"number": purchase.number, "note": purchase.office_note}
    _driver(entry, purchase.buyer, kind, params, "/achats")


def _purchase_edited(entry: AuditLog) -> None:
    # The driver changing their own purchase tells the office; the office changing it tells the driver.
    purchase = cast("FieldPurchase", entry.target)
    if entry.actor is not None and entry.actor.pk == purchase.buyer_id:
        _purchase_sent(entry)
    else:
        _purchase_decided(entry)


def _loss_decided(entry: AuditLog) -> None:
    loss = cast("StockLoss", entry.target)
    kind = "loss_approved" if entry.action == "loss.approved" else "loss_rejected"
    params = {"number": loss.number, "product": loss.product.name, "reason": loss.rejection_reason}
    _driver(entry, loss.created_by, kind, params)


def _expense_decided(entry: AuditLog) -> None:
    expense = cast("Expense", entry.target)
    kind = "expense_approved" if entry.action == "expense.approved" else "expense_rejected"
    params = {"number": expense.number, "amount": _amount(expense.amount), "reason": expense.rejection_reason}
    _driver(entry, expense.entered_by, kind, params)


def _truck_assigned(entry: AuditLog) -> None:
    assignment = cast("TruckAssignment | None", entry.target)
    if assignment is None or assignment.date < timezone.localdate():
        return
    params = {"truck": assignment.truck.location.name, "date": assignment.date.isoformat()}
    _driver(entry, assignment.driver, "truck_assigned", params, "/")


def _sync_resolved(entry: AuditLog) -> None:
    problem = cast("SyncProblem", entry.target)
    _driver(entry, problem.driver, "sync_resolved", {"label": problem.label})


# ---- What a visitor of the public site sends, told to the office (D-186) ----


def _web_request(entry: AuditLog) -> None:
    request = cast("WebRequest", entry.target)
    kind = "web_order" if request.kind == "order" else "web_quote"
    params = {"number": request.number, "name": request.full_name, "phone": request.phone}
    services.tell_office_from_site(
        organization=entry.organization, kind=kind, params=params, link=f"/demandes-site/{request.pk}"
    )


RULES: dict[str, Callable[[AuditLog], None]] = {
    "driver_day.opened": _day_opened,
    "day_closing.submitted": _day_sent,
    "day_closing.resubmitted": _day_sent,
    "sale.confirmed": _sale_confirmed,
    "sale.credit_approval_requested": _sale_confirmed,
    "sale.delivered": _delivered,
    "sale.cancelled": _sale_cancelled,
    "sale.delivery_changed": _bl_changed,
    "customer_payment.recorded": _payment_recorded,
    "expense.created": _expense_created,
    "loss.recorded": _loss_recorded,
    "field_purchase.submitted": _purchase_sent,
    "field_purchase.edited": _purchase_edited,
    "customer.created": _customer_created,
    "sync_problem.reported": _sync_problem,
    "transfer.validated": _transfer_validated,
    "day_closing.approved": _day_reviewed,
    "day_closing.justification_requested": _day_reviewed,
    "day_closing.reopened": _day_reviewed,
    "field_purchase.validated": _purchase_decided,
    "field_purchase.refused": _purchase_decided,
    "loss.approved": _loss_decided,
    "loss.rejected": _loss_decided,
    "expense.approved": _expense_decided,
    "expense.rejected": _expense_decided,
    "truck_assignment.created": _truck_assigned,
    "truck_assignment.changed": _truck_assigned,
    "sync_problem.resolved": _sync_resolved,
    "web_request.received": _web_request,
}


def apply(entry: AuditLog) -> None:
    """Write the notification an audit entry calls for, if any."""
    rule = RULES.get(entry.action)
    if rule is not None and entry.target is not None:
        rule(entry)
