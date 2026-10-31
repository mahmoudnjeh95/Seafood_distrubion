"""Every write on sales documents goes through these functions (ARCHITECTURE §3)."""

import datetime as dt
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import TYPE_CHECKING, Any, TypedDict, Unpack

from django.core.exceptions import ValidationError
from django.core.files.base import ContentFile
from django.db import transaction
from django.db.models import F, Sum
from django.utils import timezone
from django.utils.formats import date_format
from django.utils.translation import gettext as _

from apps.boxes import services as box_services
from apps.catalog import selectors as catalog
from apps.core import audit
from apps.core.clock import CLOCK_MARGIN
from apps.core.images import reencoded_photo
from apps.core.models import Membership, Organization, Role, User
from apps.core.money import Number, checked_amount, checked_quantity, display_money, line_total, money
from apps.expenses import selectors as expenses_selectors
from apps.expenses import services as expenses
from apps.inventory import selectors as inventory_selectors
from apps.inventory import services as inventory
from apps.notifications import services as notifications
from apps.partners import services as partners
from apps.treasury import services as treasury

from . import invoicing, receivables, selectors
from .models import (
    INSTRUMENT_METHODS,
    CreditNote,
    CreditNoteKind,
    CreditNoteLine,
    CreditNoteLineBatch,
    CreditNoteStock,
    CreditPolicy,
    CreditStatus,
    CustomerPayment,
    CustomerPaymentLine,
    CustomerPaymentMethod,
    DeliveryStatus,
    DocumentCounter,
    FinanceSettings,
    Invoice,
    InvoiceLine,
    InvoiceSale,
    InvoiceStatus,
    InvoiceVatLine,
    PaymentAllocation,
    PriceSource,
    Quote,
    QuoteLine,
    QuoteStatus,
    Sale,
    SaleBoxLine,
    SaleLine,
    SaleLineBatch,
    SaleLinePick,
    SalePaymentMethod,
    SaleRevision,
    SaleRevisionKind,
    SaleStatus,
    UnpaidEffet,
    UnpaidRelease,
    WithholdingCertificate,
)

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from apps.catalog.models import Product
    from apps.inventory.models import Batch, StockLocation, Transfer
    from apps.partners.models import Customer
    from apps.treasury.models import Bank

# ---- Quotes (P2-T03, D-050) ----

QUOTE_SERIES = "DV"
# Validity when none is given: the prototype's quote is "valable 3 jours". Provisional (D-050): seafood
# prices move daily, so a short validity is the safe default.
DEFAULT_VALIDITY_DAYS = 3
MAX_DISCOUNT_RATE = Decimal("100")
_RATE_STEP = Decimal("0.01")


class QuoteLineFields(TypedDict, total=False):
    product: "Product"
    quantity: Number
    # DT per kg; empty takes the sale price in force on the quote's day.
    unit_price: Number | None
    # Percent with at most 2 decimals; empty means none.
    discount_rate: Number | None
    # The lot the kilos should come from (D-201); empty: the oldest lot first.
    batch: "Batch | None"


def line_error_key(index: int, field: str) -> str:
    """Errors of a document line are reported on `lines.<index>.<field>`, under the line's own input."""
    return f"lines.{index}.{field}"


def _next_number(organization: Organization, series: str) -> str:
    """DV-0001, DV-0002... per organization and series, taken under a row lock (same scheme as batches).

    Taken in the transaction that creates the document and quotes are never deleted, so there are no gaps.
    """
    DocumentCounter.objects.bulk_create(
        [DocumentCounter(organization=organization, series=series)], ignore_conflicts=True
    )
    counter = DocumentCounter.objects.select_for_update().get(organization=organization, series=series)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"{series}-{counter.last_number:04d}"


def moment_of(day: dt.date) -> dt.datetime:
    """The moment whose sale prices a quote of `day` uses: now when it is today, noon of that day otherwise."""
    if day == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(dt.datetime.combine(day, dt.time(12, 0)))


def _header_errors(
    organization: Organization,
    customer: "Customer",
    location: "StockLocation | None",
    quoted_on: dt.date,
    valid_until: dt.date,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if customer.organization_id != organization.pk:
        errors["customer"] = _("Client inconnu.")
    elif not customer.is_active:
        errors["customer"] = _("Ce client est archivé.")
    if location is not None:
        if location.organization_id != organization.pk:
            errors["location"] = _("Emplacement inconnu.")
        elif not location.is_active:
            errors["location"] = _("« %(name)s » est archivé.") % {"name": location.name}
    if quoted_on > timezone.localdate():
        errors["quoted_on"] = _("La date du devis ne peut pas être dans le futur.")
    if valid_until < quoted_on:
        errors["valid_until"] = _("La date de validité ne peut pas précéder la date du devis.")
    return errors


# A price the driver's phone showed stays valid for a sale made within this time of it: a sale kept on the phone
# keeps the price that was in force then, even when the office has changed it since (P3-T02, D-148).
PHONE_PRICE_WINDOW = dt.timedelta(hours=24)


def shown_price_in_force(product: "Product", price: Decimal, at: dt.datetime) -> bool:
    """Whether `price` was a daily price of the product at some moment in the `PHONE_PRICE_WINDOW` before `at`."""
    since = at - PHONE_PRICE_WINDOW
    if product.prices.filter(valid_from__gt=since, valid_from__lte=at, price=price).exists():
        return True
    # The price already in force when the window opens.
    before = catalog.price_at(product, since)
    return before is not None and before.price == price


def _shown_price(
    product: "Product | None", price: Any, at: dt.datetime, customer: "Customer"
) -> tuple[Decimal, str] | str:
    """The price of a line a driver's phone priced (`PriceSource.SHOWN`). The customer's own price list wins when it
    holds the product (D-049), whatever the phone showed; otherwise the shown price must have been a real price."""
    if product is not None:
        in_force = catalog.price_in_force(product, at, customer_id=customer.pk)
        if in_force is not None and in_force.source == "price_list":
            return in_force.price, in_force.source
    try:
        amount = checked_amount(price)
    except (ValueError, TypeError):
        amount = None
    if amount is None or amount <= 0:
        return _("Indiquez un prix en DT par kg, supérieur à zéro, au millime près.")
    if product is None or not shown_price_in_force(product, amount, at):
        return _("Ce prix n'est plus valable : rafraîchissez les prix sur le téléphone et refaites la vente.")
    return amount, PriceSource.SHOWN


def _checked_price(
    product: "Product | None", price: Any, at: dt.datetime, customer: "Customer", typed_source: str = PriceSource.TYPED
) -> tuple[Decimal, str] | str:
    """The price per kg of a line and where it comes from (`PriceSource`), or the message saying why there is
    none.

    Empty takes what the customer is charged at `at` (`catalog.price_in_force`, D-049): their own price
    list when it holds the product, else the daily price. A typed price must be above zero; it is recorded
    as `typed_source` (typed by hand, or copied from a quote). A driver's shown price is checked (`_shown_price`).
    """
    if price in (None, ""):
        in_force = catalog.price_in_force(product, at, customer_id=customer.pk) if product is not None else None
        if in_force is None:
            return _("Aucun prix de vente en vigueur : indiquez un prix.")
        return in_force.price, in_force.source
    if typed_source == PriceSource.SHOWN:
        return _shown_price(product, price, at, customer)
    try:
        amount = checked_amount(price)
    except (ValueError, TypeError):
        amount = None
    if amount is None or amount <= 0:
        return _("Indiquez un prix en DT par kg, supérieur à zéro, au millime près.")
    return amount, typed_source


def _checked_rate(rate: Any) -> Decimal | None:
    """A discount in percent, from 0 to 100 with at most 2 decimals; None when it is not one."""
    if rate in (None, ""):
        return Decimal("0.00")
    if isinstance(rate, bool) or not isinstance(rate, Decimal | int | str):
        return None
    try:
        value = Decimal(rate)
    except InvalidOperation:
        return None
    if not value.is_finite() or value != value.quantize(_RATE_STEP) or not 0 <= value <= MAX_DISCOUNT_RATE:
        return None
    return value.quantize(_RATE_STEP)


def priced_line(quantity: Decimal, unit_price: Decimal, discount_rate: Decimal) -> dict[str, Decimal]:
    """The amounts of a line: gross = kg × price, discount = gross × rate / 100, each rounded once to the
    millime (half up), and amount = gross − discount."""
    gross = line_total(quantity, unit_price)
    discount = money(gross * discount_rate / 100)
    return {"gross_amount": gross, "discount_amount": discount, "amount": gross - discount}


def _checked_lines(
    organization: Organization,
    customer: "Customer",
    lines: Sequence[QuoteLineFields],
    at: dt.datetime,
    errors: dict[str, str],
    typed_source: str = PriceSource.TYPED,
    below_minimum_reason: str = "",
) -> list[dict[str, Any]]:
    """The lines' values once checked and priced; each problem is added to `errors` under the line's keys.

    Each line also says where its price comes from (`price_source`) and whether it is below the product's
    minimum price (`below_minimum`). A price once the discount is taken off may not go under that minimum: the
    line is refused (D-163), unless an owner or manager gave a `below_minimum_reason` (D-193); the line is then
    kept, flagged `below_minimum` and `approved_below_minimum`."""
    checked_lines: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, line in enumerate(lines):
        product = line.get("product")
        checked: dict[str, Any] = {"product": product}
        if product is None or product.organization_id != organization.pk:
            errors[line_error_key(index, "product")] = _("Produit inconnu.")
        elif not product.is_active:
            errors[line_error_key(index, "product")] = _("Ce produit est archivé.")
        elif product.pk in seen:
            errors[line_error_key(index, "product")] = _("Ce produit est déjà sur une autre ligne.")
        else:
            seen.add(product.pk)
        try:
            value: Any = line.get("quantity", "")
            checked["quantity"] = checked_quantity(value)
        except (ValueError, TypeError):
            errors[line_error_key(index, "quantity")] = _("Indiquez un poids en kg, supérieur à zéro.")
        if line_error_key(index, "product") not in errors:
            price = _checked_price(product, line.get("unit_price"), at, customer, typed_source)
            if isinstance(price, tuple):
                checked["unit_price"], checked["price_source"] = price
                checked["below_minimum"] = product is not None and catalog.is_below_minimum(product, price[0])
            else:
                errors[line_error_key(index, "unit_price")] = price
        rate = _checked_rate(line.get("discount_rate"))
        if rate is None:
            errors[line_error_key(index, "discount_rate")] = _(
                "Indiquez une remise en %, de 0 à 100, avec 2 décimales au plus."
            )
        checked["discount_rate"] = rate
        if rate is not None and "unit_price" in checked and product is not None and product.min_price is not None:
            net = checked["unit_price"] * (100 - rate) / 100
            if net < product.min_price:
                if below_minimum_reason.strip():
                    checked["below_minimum"] = True
                    checked["approved_below_minimum"] = True
                else:
                    key = line_error_key(index, "discount_rate" if rate > 0 else "unit_price")
                    errors[key] = _("Le prix après remise ({net} DT/kg) est sous le minimum ({minimum} DT/kg).").format(
                        net=money(net), minimum=product.min_price
                    )
        if "quantity" in checked and "unit_price" in checked and rate is not None:
            checked.update(priced_line(checked["quantity"], checked["unit_price"], rate))
        checked_lines.append(checked)
    return checked_lines


def _prepared(
    organization: Organization,
    customer: "Customer",
    location: "StockLocation | None",
    quoted_on: dt.date,
    valid_until: dt.date | None,
    lines: Sequence[QuoteLineFields],
    below_minimum_reason: str = "",
) -> tuple[dt.date, list[dict[str, Any]]]:
    """The validity date and the checked lines of a quote, or a ValidationError with every problem at once."""
    if valid_until is None:
        valid_until = quoted_on + dt.timedelta(days=DEFAULT_VALIDITY_DAYS)
    errors = _header_errors(organization, customer, location, quoted_on, valid_until)
    if not lines:
        errors["lines"] = _("Ajoutez au moins un produit.")
    checked_lines = _checked_lines(
        organization, customer, lines, moment_of(quoted_on), errors, below_minimum_reason=below_minimum_reason
    )
    _checked_batches(organization, lines, checked_lines, errors)
    if errors:
        raise ValidationError(errors)
    return valid_until, checked_lines


def _write_lines(quote: Quote, checked_lines: list[dict[str, Any]]) -> None:
    """Replace the lines and set the quote's totals from them (no VAT yet: P2-T05)."""
    QuoteLine.objects.bulk_create(
        [
            QuoteLine(
                organization_id=quote.organization_id,
                quote=quote,
                product=values["product"],
                quantity=values["quantity"],
                unit_price=values["unit_price"],
                discount_rate=values["discount_rate"],
                gross_amount=values["gross_amount"],
                discount_amount=values["discount_amount"],
                amount=values["amount"],
                requested_batch=values.get("requested_batch"),
            )
            for values in checked_lines
        ]
    )
    quote.subtotal = sum((values["gross_amount"] for values in checked_lines), Decimal("0.000"))
    quote.discount_total = sum((values["discount_amount"] for values in checked_lines), Decimal("0.000"))
    quote.total_excl_tax = quote.subtotal - quote.discount_total
    # A quote shows no VAT: only the invoice of its sale carries the tax detail (D-057).
    quote.tax_amount = None
    quote.total = quote.total_excl_tax
    quote.save(update_fields=["subtotal", "discount_total", "total_excl_tax", "tax_amount", "total", "updated_at"])


def _snapshot(quote: Quote) -> dict[str, Any]:
    return {
        "number": quote.number,
        "status": quote.status,
        "customer": quote.customer.reference,
        "location": quote.location.name if quote.location is not None else None,
        "quoted_on": quote.quoted_on.isoformat(),
        "valid_until": quote.valid_until.isoformat(),
        "lines": [
            {
                "product": line.product.reference,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "discount_rate": str(line.discount_rate),
                "amount": str(line.amount),
            }
            for line in quote.lines.select_related("product").order_by("id")
        ],
        "total": str(quote.total),
    }


def _record_floor_approval(
    *,
    organization: Organization,
    actor: User | None,
    target: Quote | Sale,
    reason: str,
    checked_lines: list[dict[str, Any]],
) -> None:
    """Audit the lines an owner or manager let go under the product's minimum price, with their reason (D-193)."""
    approved = [values for values in checked_lines if values.get("approved_below_minimum")]
    if not approved:
        return
    prefix = "quote" if isinstance(target, Quote) else "sale"
    audit.record(
        organization=organization,
        actor=actor,
        action=f"{prefix}.price_below_minimum_approved",
        target=target,
        after={
            "reason": reason.strip(),
            "lines": [
                {
                    "product": values["product"].pk,
                    "unit_price": str(values["unit_price"]),
                    "discount_rate": str(values["discount_rate"]),
                    "minimum": str(values["product"].min_price),
                }
                for values in approved
            ],
        },
    )


@transaction.atomic
def create_quote(
    *,
    organization: Organization,
    actor: User | None,
    customer: "Customer",
    quoted_on: dt.date,
    lines: Sequence[QuoteLineFields],
    valid_until: dt.date | None = None,
    location: "StockLocation | None" = None,
    notes: str = "",
    client_uuid: uuid.UUID | None = None,
    send: bool = False,
    below_minimum_reason: str = "",
) -> Quote:
    """Prepare a quote as a draft; with `send`, also mark it sent (one transaction).

    A line without a price takes the sale price in force on the quote's day; the price is then kept on
    the line. Without a validity date the quote is valid `DEFAULT_VALIDITY_DAYS` days. A `client_uuid`
    already used returns that quote.
    """
    if client_uuid is not None:
        existing = Quote.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    valid_until, checked_lines = _prepared(
        organization, customer, location, quoted_on, valid_until, lines, below_minimum_reason
    )
    quote = Quote.objects.create(
        organization=organization,
        number=_next_yearly_number(organization, QUOTE_SERIES, timezone.localdate().year),
        customer=customer,
        location=location,
        quoted_on=quoted_on,
        valid_until=valid_until,
        notes=notes.strip(),
        created_by=actor,
        client_uuid=client_uuid,
    )
    _write_lines(quote, checked_lines)
    audit.record(organization=organization, actor=actor, action="quote.created", target=quote, after=_snapshot(quote))
    _record_floor_approval(
        organization=organization, actor=actor, target=quote, reason=below_minimum_reason, checked_lines=checked_lines
    )
    if send:
        return send_quote(quote=quote, actor=actor)
    return quote


def _locked(quote: Quote) -> Quote:
    """The quote locked until commit, so two answers recorded at once never both apply."""
    return (
        Quote.objects.select_for_update(of=("self",))
        .select_related("organization", "customer", "location")
        .get(pk=quote.pk)
    )


def _status_name(quote: Quote) -> str:
    return str(QuoteStatus(quote.status).label).lower()


def _locked_draft(quote: Quote) -> Quote:
    locked = _locked(quote)
    if locked.status != QuoteStatus.DRAFT:
        raise ValidationError(_("Ce devis est %(status)s : il ne se modifie plus.") % {"status": _status_name(locked)})
    return locked


@transaction.atomic
def update_quote(
    *,
    quote: Quote,
    actor: User | None,
    customer: "Customer",
    quoted_on: dt.date,
    lines: Sequence[QuoteLineFields],
    valid_until: dt.date | None = None,
    location: "StockLocation | None" = None,
    notes: str = "",
    send: bool = False,
    below_minimum_reason: str = "",
) -> Quote:
    """Change a draft: customer, place, dates, notes and lines (all replaced). With `send`, send it too."""
    quote = _locked_draft(quote)
    organization = quote.organization
    before = _snapshot(quote)
    valid_until, checked_lines = _prepared(
        organization, customer, location, quoted_on, valid_until, lines, below_minimum_reason
    )
    quote.customer = customer
    quote.location = location
    quote.quoted_on = quoted_on
    quote.valid_until = valid_until
    quote.notes = notes.strip()
    quote.save()
    quote.lines.all().delete()
    _write_lines(quote, checked_lines)
    audit.record(
        organization=organization,
        actor=actor,
        action="quote.updated",
        target=quote,
        before=before,
        after=_snapshot(quote),
    )
    _record_floor_approval(
        organization=organization, actor=actor, target=quote, reason=below_minimum_reason, checked_lines=checked_lines
    )
    if send:
        return send_quote(quote=quote, actor=actor)
    return quote


def _expiry_error(quote: Quote) -> ValidationError:
    return ValidationError(
        {
            "valid_until": _("Ce devis n'est plus valable depuis le %(date)s : faites un nouveau devis.")
            % {"date": date_format(quote.valid_until, "SHORT_DATE_FORMAT")}
        }
    )


@transaction.atomic
def send_quote(*, quote: Quote, actor: User | None) -> Quote:
    """Mark a draft as given to the customer: from now on it no longer changes. Refused when its validity
    date has already passed or its customer was archived meanwhile."""
    quote = _locked_draft(quote)
    if quote.valid_until < timezone.localdate():
        raise _expiry_error(quote)
    if not quote.customer.is_active:
        raise ValidationError({"customer": _("Ce client est archivé.")})
    quote.status = QuoteStatus.SENT
    quote.sent_by = actor
    quote.sent_at = timezone.now()
    quote.save(update_fields=["status", "sent_by", "sent_at", "updated_at"])
    audit.record(organization=quote.organization, actor=actor, action="quote.sent", target=quote)
    return quote


def _locked_sent(quote: Quote) -> Quote:
    locked = _locked(quote)
    if locked.status == QuoteStatus.DRAFT:
        raise ValidationError(_("Envoyez d'abord ce devis au client."))
    if locked.status != QuoteStatus.SENT:
        raise ValidationError(_("Ce devis est déjà %(status)s.") % {"status": _status_name(locked)})
    return locked


@transaction.atomic
def accept_quote(*, quote: Quote, actor: User | None) -> Quote:
    """Record the customer's yes on a sent quote, up to its validity date included. The accepted quote
    keeps its prices and becomes a sale in P2-T04; no stock is reserved."""
    quote = _locked_sent(quote)
    if quote.valid_until < timezone.localdate():
        raise _expiry_error(quote)
    quote.status = QuoteStatus.ACCEPTED
    quote.answered_by = actor
    quote.answered_at = timezone.now()
    quote.save(update_fields=["status", "answered_by", "answered_at", "updated_at"])
    audit.record(organization=quote.organization, actor=actor, action="quote.accepted", target=quote)
    return quote


@transaction.atomic
def refuse_quote(*, quote: Quote, actor: User | None, reason: str = "") -> Quote:
    """Record the customer's no on a sent quote, with an optional reason (too dear, bought elsewhere...).
    Allowed after the validity date too: the answer is worth keeping."""
    quote = _locked_sent(quote)
    quote.status = QuoteStatus.REFUSED
    quote.answered_by = actor
    quote.answered_at = timezone.now()
    quote.refusal_reason = reason.strip()[:255]
    quote.save(update_fields=["status", "answered_by", "answered_at", "refusal_reason", "updated_at"])
    audit.record(
        organization=quote.organization,
        actor=actor,
        action="quote.refused",
        target=quote,
        after={"reason": quote.refusal_reason},
    )
    return quote


@transaction.atomic
def expire_quotes(*, organization: Organization, actor: User | None = None, today: dt.date | None = None) -> int:
    """Mark as expired the sent quotes whose validity date is before `today` (the nightly job). Returns
    how many. The screens already show them expired before this runs (`selectors.current_quote_status`)."""
    today = today or timezone.localdate()
    now = timezone.now()
    expired = 0
    for quote in selectors.quotes_to_expire(organization, today=today).select_for_update().order_by("id"):
        quote.status = QuoteStatus.EXPIRED
        quote.expired_at = now
        quote.save(update_fields=["status", "expired_at", "updated_at"])
        audit.record(organization=organization, actor=actor, action="quote.expired", target=quote)
        expired += 1
    return expired


# ---- Sales (P2-T04, D-051) ----

SALE_SERIES = "VE"
# A validated sale is a delivery note (bon de livraison): BL-2026-0001, restarting every year (D-095).
DELIVERY_NOTE_PREFIX = "BL"


class LotPickFields(TypedDict):
    """A lot picked by hand for a sale line, and the kilos to take from it first (D-121, D-208)."""

    batch: "Batch"
    quantity: Number


class SaleLineFields(TypedDict, total=False):
    product: "Product"
    quantity: Number
    # DT per kg; empty takes what the customer is charged at the sale's moment (`catalog.price_in_force`).
    unit_price: Number | None
    # Percent with at most 2 decimals; empty means none.
    discount_rate: Number | None
    # Picked by hand instead of FIFO (D-121); empty takes the oldest lot first, as always.
    batch: "Batch | None"
    # Several lots picked by hand, each with its kilos (D-208); they take precedence over `batch`.
    picks: Sequence[LotPickFields]


class QuoteDeliveryFields(TypedDict):
    """The part of one quote line a BL takes (D-115)."""

    # The quote line's id.
    quote_line: int
    quantity: Number


class PaymentFields(TypedDict, total=False):
    # What the customer pays on the spot; empty means nothing.
    amount_paid: Number | None
    # The whole total is paid on the spot (a counter sale): `amount_paid` is then ignored.
    paid_in_full: bool
    payment_method: str
    payment_reference: str


def _sale_header_errors(
    organization: Organization,
    customer: "Customer",
    location: "StockLocation",
    sold_at: dt.datetime,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if customer.organization_id != organization.pk:
        errors["customer"] = _("Client inconnu.")
    elif not customer.is_active:
        errors["customer"] = _("Ce client est archivé.")
    if location.organization_id != organization.pk:
        errors["location"] = _("Emplacement inconnu.")
    elif not location.is_active:
        errors["location"] = _("« %(name)s » est archivé.") % {"name": location.name}
    elif not location.sells:
        errors["location"] = _("« %(name)s » ne fait pas de vente au comptoir.") % {"name": location.name}
    if sold_at > timezone.now() + CLOCK_MARGIN:
        errors["sold_at"] = _("Une vente ne peut pas être datée dans le futur.")
    return errors


def _checked_payment(total: Decimal, payment: PaymentFields, errors: dict[str, str]) -> dict[str, Any]:
    """The payment made on the spot, checked against the sale's total; problems are added to `errors`."""
    method = (payment.get("payment_method") or "").strip()
    reference = (payment.get("payment_reference") or "").strip()[:50]
    if payment.get("paid_in_full"):
        paid = total
    else:
        raw: Any = payment.get("amount_paid")
        try:
            paid = checked_amount(raw) if raw not in (None, "") else Decimal("0.000")
        except (ValueError, TypeError):
            errors["amount_paid"] = _("Indiquez un montant en DT, au millime près.")
            paid = Decimal("0.000")
        if paid > total:
            errors["amount_paid"] = _("Le montant payé dépasse le total de la vente (%(total)s DT).") % {
                "total": display_money(total)
            }
    if paid > 0 and not method:
        errors["payment_method"] = _("Indiquez le mode de paiement.")
    elif method and method not in SalePaymentMethod.values:
        errors["payment_method"] = _("Mode de paiement inconnu.")
    if paid == 0:
        method, reference = "", ""
    return {"amount_paid": paid, "payment_method": method, "payment_reference": reference}


def _checked_batches(
    organization: Organization,
    lines: Sequence[SaleLineFields] | Sequence[QuoteLineFields],
    checked_lines: list[dict[str, Any]],
    errors: dict[str, str],
) -> None:
    """Resolve each line's lot picked by hand (D-121): must be of that organization and the line's product.

    Mutates `checked_lines` in place, adding `requested_batch` (None keeps FIFO, the default).
    """
    for index, (line, checked) in enumerate(zip(lines, checked_lines, strict=True)):
        batch = line.get("batch")
        checked["requested_batch"] = None
        if batch is None:
            continue
        product = checked.get("product")
        if batch.organization_id != organization.pk:
            errors[line_error_key(index, "batch")] = _("Lot inconnu.")
        elif product is not None and batch.product_id != product.pk:
            errors[line_error_key(index, "batch")] = _("Ce lot ne correspond pas au produit de la ligne.")
        else:
            checked["requested_batch"] = batch


def _checked_picks(
    organization: Organization,
    lines: Sequence[SaleLineFields],
    checked_lines: list[dict[str, Any]],
    errors: dict[str, str],
) -> None:
    """Check each sale line's lots picked by hand (D-208): of that organization and the line's product, each lot
    once, with kilos above zero, and together no more kilos than the line asks. A single `batch` (D-121) is one
    pick of the line's whole weight.

    Mutates `checked_lines` in place, adding `picks` as `[(batch, kg)]` (empty keeps FIFO, the default).
    """
    for index, (line, checked) in enumerate(zip(lines, checked_lines, strict=True)):
        key = line_error_key(index, "picks")
        product = checked.get("product")
        picks: list[tuple[Batch, Decimal]] = []
        if line.get("picks"):
            for pick in line["picks"]:
                batch = pick["batch"]
                try:
                    kg = checked_quantity(pick["quantity"])
                except (ValueError, TypeError):
                    errors.setdefault(key, _("Indiquez un poids en kg pour chaque lot, supérieur à zéro."))
                    continue
                if batch.organization_id != organization.pk:
                    errors.setdefault(key, _("Lot inconnu."))
                elif product is not None and batch.product_id != product.pk:
                    errors.setdefault(key, _("Ce lot ne correspond pas au produit de la ligne."))
                elif any(batch.pk == picked.pk for picked, _kg in picks):
                    errors.setdefault(key, _("Un lot ne peut être choisi qu'une fois par ligne."))
                else:
                    picks.append((batch, kg))
        elif checked.get("requested_batch") is not None and "quantity" in checked:
            picks = [(checked["requested_batch"], checked["quantity"])]
        checked["picks"] = picks
        if "quantity" in checked and sum((kg for _batch, kg in picks), Decimal("0")) > checked["quantity"]:
            errors.setdefault(key, _("Les lots choisis dépassent le poids de la ligne."))


def _prepared_sale(
    organization: Organization,
    customer: "Customer",
    location: "StockLocation",
    sold_at: dt.datetime,
    lines: Sequence[SaleLineFields],
    payment: PaymentFields,
    typed_source: str = PriceSource.TYPED,
    below_minimum_reason: str = "",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """The checked lines and payment of a sale, or a ValidationError with every problem at once."""
    errors = _sale_header_errors(organization, customer, location, sold_at)
    if not lines:
        errors["lines"] = _("Ajoutez au moins un produit.")
    checked_lines = _checked_lines(organization, customer, lines, sold_at, errors, typed_source, below_minimum_reason)
    _checked_batches(organization, lines, checked_lines, errors)
    _checked_picks(organization, lines, checked_lines, errors)
    total = sum((values.get("amount", Decimal("0.000")) for values in checked_lines), Decimal("0.000"))
    paid = _checked_payment(total, payment, errors)
    if errors:
        raise ValidationError(errors)
    return checked_lines, paid


def _checked_sale_boxes(boxes: Mapping[str, object] | None) -> dict[str, int]:
    """The non-zero box counts of a sale, or a ValidationError naming each problem (boxes.<box type>)."""
    errors: dict[str, str] = {}
    counts = box_services.checked_box_counts(boxes, errors, prefix="boxes")
    if errors:
        raise ValidationError(errors)
    return counts


def _write_sale_boxes(sale: Sale, box_counts: Mapping[str, int]) -> None:
    """Replace the boxes left with the client by this sale's (none when no box is left)."""
    SaleBoxLine.objects.bulk_create(
        [
            SaleBoxLine(organization_id=sale.organization_id, sale=sale, box_type=box_type, count=count)
            for box_type, count in box_counts.items()
        ]
    )


def _post_sale_boxes(sale: Sale, actor: User | None, kind: str, *, from_customer: bool) -> None:
    """Move the sale's boxes between the client and the place the goods leave from, in the caller's
    transaction: leave when confirmed, collect when cancelled. A refusal rolls the whole sale back."""
    counts = {line.box_type: line.count for line in sale.box_lines.all()}
    if not counts:
        return
    customer_holder = box_services.holder_for(organization=sale.organization, customer=sale.customer)
    location_holder = box_services.holder_for(organization=sale.organization, location=sale.location)
    from_holder, to_holder = (customer_holder, location_holder) if from_customer else (location_holder, customer_holder)
    try:
        box_services.post_box_counts(
            organization=sale.organization,
            actor=actor,
            kind=kind,
            counts=counts,
            from_holder=from_holder,
            to_holder=to_holder,
            source=sale,
        )
    except ValidationError as error:
        raise ValidationError({"boxes": error.messages}) from error


def _settings_on_day_of(organization: Organization, sold_at: dt.datetime) -> FinanceSettings:
    """The finance settings in force the day the sale was made (D-224): its prices' VAT and its rates."""
    day = timezone.localdate(sold_at)
    return selectors.finance_settings_on(organization, day) or ensure_finance_settings(organization=organization)


def _line_vat_rate(product: "Product", vat_product_ids: set[int], version: FinanceSettings) -> Decimal | None:
    """The VAT rate a BL line takes (D-224): none unless its product is sold with VAT (kilos bought with VAT,
    D-202), else the rate the invoice would propose (`_default_rate`)."""
    return _default_rate(product, version) if product.pk in vat_product_ids else None


def _apply_bl_vat(lines: Sequence[SaleLine], *, prices_include_vat: bool) -> None:
    """The VAT of a BL's lines (D-224), from the rate each line snapshotted: the invoice's own arithmetic
    (`invoicing.compute`), so a BL and its invoice agree. A line without a rate carries no VAT."""
    amounts = invoicing.compute(
        [
            invoicing.LineInput(
                amount=line.amount,
                vat_rate=line.vat_rate if line.vat_rate is not None else invoicing.NO_RATE,
            )
            for line in lines
        ],
        apply_vat=True,
        prices_include_vat=prices_include_vat,
        fiscal_stamp=Decimal("0.000"),
        withholding_rate=None,
    )
    for line, result in zip(lines, amounts.lines, strict=True):
        line.amount_excl_tax = result.amount_excl_tax
        line.vat_amount = result.vat_amount
        line.amount_incl_tax = result.amount_incl_tax


def _set_bl_vat_totals(sale: Sale, lines: Sequence[SaleLine]) -> None:
    """The sale's VAT total and total with VAT, the sum of its lines (D-224)."""
    sale.vat_total = sum((line.vat_amount for line in lines), Decimal("0.000"))
    sale.total_incl_tax = sum((line.amount_incl_tax for line in lines), Decimal("0.000"))


def _write_sale_lines(sale: Sale, checked_lines: list[dict[str, Any]], paid: dict[str, Any]) -> None:
    """Replace the lines and set the sale's totals, VAT snapshot and payment from them. The VAT of the lines
    sold with VAT is written now, from the settings of the sale's day, and kept (D-224)."""
    version = _settings_on_day_of(sale.organization, sale.sold_at)
    vat_ids = set(inventory_selectors.vat_product_ids(sale.organization))
    new_lines = [
        SaleLine(
            organization_id=sale.organization_id,
            sale=sale,
            product=values["product"],
            quantity=values["quantity"],
            unit_price=values["unit_price"],
            price_source=values["price_source"],
            below_minimum=values["below_minimum"],
            requested_batch=values.get("requested_batch"),
            discount_rate=values["discount_rate"],
            gross_amount=values["gross_amount"],
            discount_amount=values["discount_amount"],
            amount=values["amount"],
            vat_rate=_line_vat_rate(values["product"], vat_ids, version),
        )
        for values in checked_lines
    ]
    _apply_bl_vat(new_lines, prices_include_vat=version.prices_include_vat)
    SaleLine.objects.bulk_create(new_lines)
    SaleLinePick.objects.bulk_create(
        [
            SaleLinePick(organization_id=sale.organization_id, line=line, batch=batch, quantity=kg)
            for line, values in zip(new_lines, checked_lines, strict=True)
            for batch, kg in values["picks"]
        ]
    )
    sale.subtotal = sum((values["gross_amount"] for values in checked_lines), Decimal("0.000"))
    sale.discount_total = sum((values["discount_amount"] for values in checked_lines), Decimal("0.000"))
    sale.total_excl_tax = sale.subtotal - sale.discount_total
    # The fiscal stamp and the withholding live on the sale's invoice (D-057); `tax_amount` is set when that
    # invoice is issued. The VAT of the lines sold with VAT is on the BL already (D-224).
    sale.tax_amount = None
    sale.total = sale.total_excl_tax
    sale.prices_include_vat = version.prices_include_vat
    _set_bl_vat_totals(sale, new_lines)
    sale.amount_paid = paid["amount_paid"]
    sale.payment_method = paid["payment_method"]
    sale.payment_reference = paid["payment_reference"]
    sale.amount_due = sale.total - sale.amount_paid
    sale.save()


def _sale_snapshot(sale: Sale) -> dict[str, Any]:
    return {
        "number": sale.number,
        "status": sale.status,
        "customer": sale.customer.reference,
        "location": sale.location.name,
        "sold_at": sale.sold_at.isoformat(),
        "quote": sale.quote.number if sale.quote is not None else None,
        "delivery_address": sale.delivery_address,
        "lines": [
            {
                "product": line.product.reference,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price),
                "price_source": line.price_source,
                "discount_rate": str(line.discount_rate),
                "amount": str(line.amount),
            }
            for line in sale.lines.select_related("product").order_by("id")
        ],
        "total": str(sale.total),
        "amount_paid": str(sale.amount_paid),
        "payment_method": sale.payment_method,
        "amount_due": str(sale.amount_due),
    }


@transaction.atomic
def create_sale(
    *,
    organization: Organization,
    actor: User | None,
    customer: "Customer | None",
    location: "StockLocation",
    lines: Sequence[SaleLineFields],
    sold_at: dt.datetime | None = None,
    notes: str = "",
    payment: PaymentFields | None = None,
    client_uuid: uuid.UUID | None = None,
    confirm: bool = False,
    approve_credit: bool = False,
    quote: Quote | None = None,
    typed_source: str = PriceSource.TYPED,
    boxes: Mapping[str, object] | None = None,
    stock_held_since: bool = False,
    delivery_address: str | None = None,
    transfer: "Transfer | None" = None,
    below_minimum_reason: str = "",
) -> Sale:
    """Type a sale as a draft; with `confirm`, also confirm it (one transaction: a refusal leaves nothing).

    No customer means the walk-in customer (a counter sale, D-047). A line without a price takes what the
    customer is charged at `sold_at` (now by default), kept on the line. A `client_uuid` already used
    returns that sale. `stock_held_since` is for a sale whose `sold_at` comes from a driver's phone (D-133):
    see `confirm_sale`. `delivery_address` is where this delivery goes when it is not the customer's address (D-160);
    `transfer` is the truck load a draft BL was prepared with.
    """
    if client_uuid is not None:
        existing = Sale.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    if customer is None:
        customer = partners.ensure_walk_in_customer(organization=organization, actor=actor)
    sold_at = sold_at or timezone.now()
    checked_lines, paid = _prepared_sale(
        organization, customer, location, sold_at, lines, payment or {}, typed_source, below_minimum_reason
    )
    box_counts = _checked_sale_boxes(boxes)
    sale = Sale.objects.create(
        organization=organization,
        number=_next_number(organization, SALE_SERIES),
        customer=customer,
        location=location,
        sold_at=sold_at,
        quote=quote,
        notes=notes.strip(),
        delivery_address=(delivery_address or "").strip()[:255],
        transfer=transfer,
        created_by=actor,
        client_uuid=client_uuid,
    )
    _write_sale_lines(sale, checked_lines, paid)
    _write_sale_boxes(sale, box_counts)
    audit.record(organization=organization, actor=actor, action="sale.created", target=sale, after=_sale_snapshot(sale))
    _record_floor_approval(
        organization=organization, actor=actor, target=sale, reason=below_minimum_reason, checked_lines=checked_lines
    )
    if confirm:
        return confirm_sale(sale=sale, actor=actor, approve_credit=approve_credit, stock_held_since=stock_held_since)
    return sale


@transaction.atomic
def create_delivery_drafts(*, transfer: "Transfer", actor: User | None) -> list[Sale]:
    """One BL per client of a validated truck load (D-160): their products at the load's prices, their boxes and
    the address of this delivery. It is validated at once with its BL number, to be printed and taken on the road
    (D-178); nothing is sold yet: the delivery takes the kilos delivered off the truck, records what the client owes
    for them and hands over the boxes. Called when the load is validated; a load already holding its BLs makes none
    again."""
    if transfer.delivery_notes.exists():
        return []
    lines = list(transfer.lines.filter(customer__isnull=False).select_related("product").order_by("id"))
    boxes = list(transfer.box_lines.filter(customer__isnull=False).order_by("id"))
    sold_at = timezone.now()
    drafts = []
    for delivery in transfer.deliveries.select_related("customer").order_by("id"):
        own = [line for line in lines if line.customer_id == delivery.customer_id]
        drafts.append(
            create_sale(
                organization=transfer.organization,
                actor=actor,
                customer=delivery.customer,
                location=transfer.to_location,
                lines=[
                    {"product": line.product, "quantity": line.quantity, "unit_price": line.unit_price} for line in own
                ],
                sold_at=sold_at,
                boxes={line.box_type: line.count for line in boxes if line.customer_id == delivery.customer_id},
                delivery_address=delivery.delivery_address,
                transfer=transfer,
            )
        )
    for sale in drafts:
        _issue_load_bl(sale, actor)
    return drafts


# ---- The BL of a truck load: validated at the load, then delivered (D-178) ----


class DeliveredLineFields(TypedDict, total=False):
    # The BL line's id.
    line: int
    # The kg delivered: zero takes the product off the BL; more than written is the weight at the client.
    quantity: Number


def _written(line: SaleLine) -> Decimal:
    """The kg the printed BL says for this line."""
    return line.ordered_quantity if line.ordered_quantity is not None else line.quantity


def _revision_lines(sale: Sale, *, delivered: bool, removed: Sequence[SaleLine] = ()) -> list[dict[str, Any]]:
    rows = [
        {
            "product": line.product_id,
            "name": line.product.name,
            "ordered": str(_written(line)),
            "delivered": str(line.quantity) if delivered else None,
            "unit_price": str(line.unit_price),
            "amount": str(line.amount),
        }
        for line in sale.lines.select_related("product").order_by("id")
    ]
    rows += [
        {
            "product": line.product_id,
            "name": line.product.name,
            "ordered": str(_written(line)),
            "delivered": "0.000",
            "unit_price": str(line.unit_price),
            "amount": "0.000",
        }
        for line in removed
    ]
    return rows


def _add_revision(
    sale: Sale, kind: str, actor: User | None, *, note: str = "", removed: Sequence[SaleLine] = ()
) -> SaleRevision:
    return SaleRevision.objects.create(
        organization_id=sale.organization_id,
        sale=sale,
        version=sale.version,
        kind=kind,
        lines=_revision_lines(sale, delivered=kind == SaleRevisionKind.DELIVERED, removed=removed),
        boxes={line.box_type: line.count for line in sale.box_lines.all()},
        total=sale.total,
        note=note[:255],
        actor=actor,
    )


def _issue_load_bl(sale: Sale, actor: User | None) -> None:
    """The client's BL of a load gets its BL number now and is version 1, the one printed and taken on the road."""
    sale.number = _next_yearly_number(sale.organization, DELIVERY_NOTE_PREFIX, timezone.localdate().year)
    sale.issued_at = timezone.now()
    sale.delivery_status = DeliveryStatus.TO_DELIVER
    sale.version = 1
    sale.save(update_fields=["number", "issued_at", "delivery_status", "version", "updated_at"])
    sale.lines.update(ordered_quantity=F("quantity"))
    _add_revision(sale, SaleRevisionKind.ISSUED, actor)
    audit.record(
        organization=sale.organization,
        actor=actor,
        action="sale.issued",
        target=sale,
        after={"number": sale.number, "transfer": sale.transfer_id},
    )


def _locked_to_deliver(sale: Sale) -> Sale:
    locked = _locked_sale(sale)
    if locked.status != SaleStatus.DRAFT or locked.delivery_status != DeliveryStatus.TO_DELIVER:
        label = DeliveryStatus(locked.delivery_status).label if locked.delivery_status else _sale_status_name(locked)
        raise ValidationError(_("Ce bon n'est plus à livrer (%(status)s).") % {"status": str(label).lower()})
    return locked


def _by_delivery_uuid(organization: Organization, delivery_uuid: uuid.UUID | None) -> Sale | None:
    if delivery_uuid is None:
        return None
    return Sale.objects.for_organization(organization).filter(delivery_uuid=delivery_uuid).first()


def delivery_by_uuid(organization: Organization, delivery_uuid: uuid.UUID | None) -> Sale | None:
    """The BL a phone already delivered (or gave up) with this `delivery_uuid`, for its retry."""
    return _by_delivery_uuid(organization, delivery_uuid)


@transaction.atomic
def deliver_sale(
    *,
    sale: Sale,
    actor: User | None,
    lines: Sequence[DeliveredLineFields] = (),
    boxes: Mapping[str, object] | None = None,
    note: str = "",
    payment: PaymentFields | None = None,
    delivery_uuid: uuid.UUID | None = None,
) -> Sale:
    """The driver delivers the BL of a load (D-178), as written or changed at the client's door.

    A line left out is delivered as written. A line at zero takes the product off; less is a part delivery, more
    is the weight found at the client. The price never changes. The BL is then confirmed with what was delivered:
    only those kilos leave the truck (oldest batch first) and the client owes only them; the rest stays on the
    truck, for the road or the return to the cold room. Boxes given replace the BL's. Nothing delivered at all is
    `cancel_delivery`. A changed BL takes the next version; every version is kept (`SaleRevision`). A retry with
    the same `delivery_uuid` answers with the delivery already recorded."""
    done = _by_delivery_uuid(sale.organization, delivery_uuid)
    if done is not None:
        return done
    sale = _locked_to_deliver(sale)
    current = list(sale.lines.select_related("product").order_by("id"))
    by_id = {line.pk: line for line in current}
    delivered = {line.pk: line.quantity for line in current}
    errors: dict[str, str] = {}
    for index, row in enumerate(lines):
        found = by_id.get(int(row.get("line") or 0))
        if found is None:
            errors[line_error_key(index, "line")] = _("Cette ligne n'est pas sur le bon.")
            continue
        try:
            delivered[found.pk] = checked_quantity(row.get("quantity", ""), allow_zero=True)
        except (ValueError, TypeError):
            errors[line_error_key(index, "quantity")] = _("Indiquez les kg livrés : zéro ou plus, au gramme près.")
    if errors:
        raise ValidationError(errors)
    if all(quantity == 0 for quantity in delivered.values()):
        return cancel_delivery(sale=sale, actor=actor, note=note, delivery_uuid=delivery_uuid)
    box_counts = _checked_sale_boxes(boxes) if boxes is not None else None
    before_boxes = {line.box_type: line.count for line in sale.box_lines.all()}
    removed = [line for line in current if delivered[line.pk] == 0]
    partial = any(delivered[line.pk] < _written(line) for line in current)
    changed = any(delivered[line.pk] != _written(line) for line in current)
    kept = [(line, delivered[line.pk]) for line in current if delivered[line.pk] > 0]
    for line in removed:
        line.delete()
    for line, quantity in kept:
        if quantity != line.quantity:
            line.quantity = quantity
            priced = priced_line(line.quantity, line.unit_price, line.discount_rate)
            line.gross_amount = priced["gross_amount"]
            line.discount_amount = priced["discount_amount"]
            line.amount = priced["amount"]
            line.save(update_fields=["quantity", "gross_amount", "discount_amount", "amount"])
    kept_lines = [line for line, _kg in kept]
    # The VAT rate snapshot stays; the VAT follows the kilos left (D-224).
    _apply_bl_vat(kept_lines, prices_include_vat=sale.prices_include_vat)
    SaleLine.objects.bulk_update(kept_lines, ["amount_excl_tax", "vat_amount", "amount_incl_tax"])
    _set_bl_vat_totals(sale, kept_lines)
    sale.subtotal = sum((line.gross_amount for line, _kg in kept), Decimal("0.000"))
    sale.discount_total = sum((line.discount_amount for line, _kg in kept), Decimal("0.000"))
    sale.total_excl_tax = sale.subtotal - sale.discount_total
    sale.total = sale.total_excl_tax
    paid = _checked_payment(sale.total, payment or {}, errors)
    if errors:
        raise ValidationError(errors)
    sale.amount_paid = paid["amount_paid"]
    sale.payment_method = paid["payment_method"]
    sale.payment_reference = paid["payment_reference"]
    sale.amount_due = sale.total - sale.amount_paid
    if box_counts is not None and box_counts != before_boxes:
        changed = True
        sale.box_lines.all().delete()
        _write_sale_boxes(sale, box_counts)
    if changed:
        sale.version += 1
    sale.delivery_status = DeliveryStatus.PARTIAL if partial else DeliveryStatus.DELIVERED
    sale.delivered_at = timezone.now()
    # Sold at the door, not at the load (D-185): the kilos leave the truck and count in the driver's day then.
    sale.sold_at = sale.delivered_at
    sale.delivered_by = actor
    sale.delivery_note = note.strip()[:255]
    sale.delivery_uuid = delivery_uuid
    sale.save()
    _add_revision(sale, SaleRevisionKind.DELIVERED, actor, note=sale.delivery_note, removed=removed)
    return confirm_sale(sale=sale, actor=actor)


@transaction.atomic
def cancel_delivery(*, sale: Sale, actor: User | None, note: str = "", delivery_uuid: uuid.UUID | None = None) -> Sale:
    """The BL of a load is not delivered at all (D-178): the client refused it, was closed, or the day ended
    first. Nothing was sold: the kilos and the boxes are still on the truck and go back with the return to the
    cold room. The note is optional."""
    done = _by_delivery_uuid(sale.organization, delivery_uuid)
    if done is not None:
        return done
    sale = _locked_to_deliver(sale)
    sale.delivered_at = timezone.now()
    sale.delivered_by = actor
    sale.delivery_note = note.strip()[:255]
    sale.delivery_uuid = delivery_uuid
    sale.save(update_fields=["delivered_at", "delivered_by", "delivery_note", "delivery_uuid", "updated_at"])
    return cancel_sale(sale=sale, actor=actor, reason=sale.delivery_note or _("Non livré"))


def cancel_undelivered(*, organization: Organization, location_id: int, actor: User | None) -> list[Sale]:
    """The BL of the truck at `location_id` still to deliver when the driver's day ends: not delivered (D-178)."""
    waiting = Sale.objects.for_organization(organization).filter(
        location_id=location_id, status=SaleStatus.DRAFT, delivery_status=DeliveryStatus.TO_DELIVER
    )
    return [
        cancel_delivery(sale=sale, actor=actor, note=_("Non livré à la fin de la journée"))
        for sale in waiting.order_by("id")
    ]


def _locked_sale(sale: Sale) -> Sale:
    """The sale locked until commit, so it is never confirmed or cancelled twice at once."""
    return (
        Sale.objects.select_for_update(of=("self",))
        .select_related("organization", "customer", "location", "quote")
        .get(pk=sale.pk)
    )


def _sale_status_name(sale: Sale) -> str:
    return str(SaleStatus(sale.status).label).lower()


def _locked_draft_sale(sale: Sale) -> Sale:
    locked = _locked_sale(sale)
    if locked.status != SaleStatus.DRAFT:
        raise ValidationError(
            _("Cette vente est %(status)s : elle ne se modifie plus.") % {"status": _sale_status_name(locked)}
        )
    return locked


@transaction.atomic
def update_sale(
    *,
    sale: Sale,
    actor: User | None,
    customer: "Customer | None",
    location: "StockLocation",
    lines: Sequence[SaleLineFields],
    sold_at: dt.datetime | None = None,
    notes: str = "",
    payment: PaymentFields | None = None,
    confirm: bool = False,
    approve_credit: bool = False,
    boxes: Mapping[str, object] | None = None,
    delivery_address: str | None = None,
    below_minimum_reason: str = "",
) -> Sale:
    """Change a draft: customer, place, moment, notes, payment, lines and boxes (all replaced). With `confirm`,
    confirm it too. Without `sold_at` the draft keeps its moment, so its prices stay those of that moment.
    Without `delivery_address` the address of this BL stays as it is, and without `boxes` its boxes stay
    (D-160): a draft BL made from a truck load keeps both when its lines are changed."""
    sale = _locked_draft_sale(sale)
    organization = sale.organization
    if sale.delivery_status in (DeliveryStatus.DELIVERED, DeliveryStatus.PARTIAL):
        raise ValidationError(_("Ce bon est déjà livré : il ne se modifie plus."))
    if customer is None:
        customer = partners.ensure_walk_in_customer(organization=organization, actor=actor)
    before = _sale_snapshot(sale)
    sold_at = sold_at or sale.sold_at
    # A sale made from a quote keeps "quote" as the source of the prices typed again from it.
    typed_source = PriceSource.QUOTE if sale.quote_id is not None else PriceSource.TYPED
    checked_lines, paid = _prepared_sale(
        organization, customer, location, sold_at, lines, payment or {}, typed_source, below_minimum_reason
    )
    box_counts = _checked_sale_boxes(boxes) if boxes is not None else None
    sale.customer = customer
    sale.location = location
    sale.sold_at = sold_at
    sale.notes = notes.strip()
    if delivery_address is not None:
        sale.delivery_address = delivery_address.strip()[:255]
    # A changed draft is checked again against the credit limit: an earlier request for approval is void.
    sale.credit_status = ""
    sale.credit_over_by = Decimal("0.000")
    sale.credit_decided_by = None
    sale.credit_decided_at = None
    sale.lines.all().delete()
    _write_sale_lines(sale, checked_lines, paid)
    if box_counts is not None:
        sale.box_lines.all().delete()
        _write_sale_boxes(sale, box_counts)
    audit.record(
        organization=organization,
        actor=actor,
        action="sale.updated",
        target=sale,
        before=before,
        after=_sale_snapshot(sale),
    )
    _record_floor_approval(
        organization=organization, actor=actor, target=sale, reason=below_minimum_reason, checked_lines=checked_lines
    )
    if sale.delivery_status == DeliveryStatus.TO_DELIVER:
        # The BL on the road changes (D-178): a new version, and what it says now is what is to deliver.
        sale.version += 1
        sale.save(update_fields=["version", "updated_at"])
        sale.lines.update(ordered_quantity=F("quantity"))
        _add_revision(sale, SaleRevisionKind.EDITED, actor)
        audit.record(
            organization=organization,
            actor=actor,
            action="sale.delivery_changed",
            target=sale,
            after={"version": sale.version, "total": str(sale.total)},
        )
    if confirm:
        return confirm_sale(sale=sale, actor=actor, approve_credit=approve_credit)
    return sale


class CreditApprovalRequired(ValidationError):
    """The sale takes the customer above their limit and the company asks for approval (D-062). Raised by
    `check_credit`; `confirm_sale` turns it into a pending draft."""

    def __init__(self, message: str, over_by: Decimal) -> None:
        super().__init__({"credit_limit": message})
        self.over_by = over_by


def _is_driver(user: User, organization: Organization) -> bool:
    return Membership.objects.filter(user=user, organization=organization, role=Role.DRIVER, is_active=True).exists()


def check_credit(sale: Sale, *, actor: User | None = None, approve_credit: bool = False) -> None:
    """The customer's credit limit, checked at confirmation for every seller, drivers included (Q16, D-062).

    The customer's balance now plus what this sale leaves unpaid must not exceed their limit (0 = no credit).
    Above it, the company setting decides (D-018): `block` refuses; `approval` keeps the sale as a pending
    draft until the owner or a manager confirms it (`approve_credit`, granted by the view only to them);
    `warn` lets it through and logs it. The customer row is locked so two sellers cannot both pass. The
    walk-in customer always pays everything on the spot (D-047).
    """
    due = sale.total - sale.amount_paid
    if sale.customer.is_walk_in:
        if due > 0:
            raise ValidationError({"amount_paid": _("Un client de passage paie toute la vente sur place.")})
        return
    sale.credit_status = ""
    sale.credit_over_by = Decimal("0.000")
    if due <= 0:
        return
    customer = type(sale.customer).objects.select_for_update().get(pk=sale.customer_id)
    balance = receivables.customer_balance(sale.organization, customer.pk).balance
    over_by = balance + due - customer.credit_limit
    if over_by <= 0:
        return
    version = selectors.finance_settings_on(sale.organization) or ensure_finance_settings(
        organization=sale.organization
    )
    policy = version.credit_policy
    sale.credit_over_by = over_by
    message = _(
        "Limite de crédit dépassée : %(name)s doit déjà %(balance)s DT, cette vente ajoute %(due)s DT, "
        "pour une limite de %(limit)s DT."
    ) % {
        "name": customer.name,
        "balance": display_money(max(balance, Decimal("0.000"))),
        "due": display_money(due),
        "limit": display_money(customer.credit_limit),
    }
    if actor is not None and _is_driver(actor, sale.organization):
        # A driver never reads what a customer owes (D-207): the refusal says what to do, not the balance.
        message = _(
            "Limite de crédit dépassée pour %(name)s : faites payer davantage sur place ou appelez le bureau."
        ) % {"name": customer.name}
    if policy == CreditPolicy.WARN:
        sale.credit_status = CreditStatus.WARNED
        return
    if policy == CreditPolicy.APPROVAL:
        if not approve_credit:
            raise CreditApprovalRequired(message, over_by)
        sale.credit_status = CreditStatus.APPROVED
        sale.credit_decided_by = actor
        sale.credit_decided_at = timezone.now()
        return
    raise ValidationError({"credit_limit": message})


OPENING_RECEIVABLE_PREFIX = "OUV"


@transaction.atomic
def create_opening_receivable(
    *,
    organization: Organization,
    actor: User | None,
    customer: "Customer",
    amount: Number,
    owed_on: dt.date,
    notes: str = "",
) -> Sale:
    """What a customer already owed when the system started: a confirmed sale without lines or stock (D-112).

    It is a receivable like any other (balance, ageing from `owed_on`, payments allocated to it) but is never
    invoiced and is left out of sales counts and lot results. `OUV-<year>-0001`; immutable, like every confirmed
    sale: a mistake is cancelled with a reason."""
    errors: dict[str, str] = {}
    if customer.organization_id != organization.pk:
        errors["customer"] = _("Client inconnu.")
    elif customer.is_walk_in:
        errors["customer"] = _("Le client de passage ne peut pas avoir de dette.")
    try:
        total = checked_amount(amount)
    except (ValueError, TypeError):
        total = Decimal("0.000")
        errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    else:
        if total <= 0:
            errors["amount"] = _("Le montant doit être supérieur à 0.")
    if owed_on > timezone.localdate():
        errors["owed_on"] = _("La date ne peut pas être dans le futur.")
    if errors:
        raise ValidationError(errors)
    location = inventory.opening_balance_location(organization=organization, actor=actor)
    moment = timezone.make_aware(dt.datetime.combine(owed_on, dt.time(12, 0)))
    now = timezone.now()
    sale = Sale.objects.create(
        organization=organization,
        number=_next_yearly_number(organization, OPENING_RECEIVABLE_PREFIX, owed_on.year),
        status=SaleStatus.CONFIRMED,
        customer=customer,
        location=location,
        sold_at=moment,
        notes=notes.strip(),
        subtotal=total,
        total_excl_tax=total,
        total=total,
        total_incl_tax=total,
        cost_total=Decimal("0.000"),
        amount_due=total,
        is_opening=True,
        created_by=actor,
        confirmed_by=actor,
        confirmed_at=now,
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="sale.opening_receivable",
        target=sale,
        after={
            "number": sale.number,
            "customer": customer.reference,
            "amount": str(total),
            "owed_on": owed_on.isoformat(),
        },
    )
    return sale


def record_receivable(sale: Sale) -> None:
    """A confirmed sale is a receivable: its outstanding amount is refreshed (the customer's balance itself is
    always computed from the documents, `receivables.customer_balance`)."""
    refresh_sale_due(sale)


def _revenue_parts(amount: Decimal, quantities: Sequence[Decimal]) -> list[Decimal]:
    """`amount` shared by kg over `quantities`, each part rounded once; the last part takes the rest, so the
    parts always add up to `amount`."""
    total_kg = sum(quantities, Decimal("0.000"))
    parts = [money(amount * kg / total_kg) for kg in quantities[:-1]]
    return [*parts, amount - sum(parts, Decimal("0.000"))]


def _post_line(sale: Sale, line: SaleLine, actor: User | None, *, stock_held_since: bool = False) -> None:
    """Take the line's kilos out of the sale's place and keep which batches went.

    Oldest batch first (FIFO, the default) unless lots were picked by hand (D-121, D-208): each picked lot gives
    the kilos picked from it, and the rest still comes from the other lots, oldest first — stock never goes
    negative. The till warns beforehand when a picked lot looks short. The movements are dated at the sale's
    moment; with `stock_held_since`, a sale of an earlier day takes only kilos the place has held since that
    day (D-133).
    """
    movements = inventory.post_fifo_movements(
        organization=sale.organization,
        actor=actor,
        kind=inventory.MovementKind.SALE,
        product_id=line.product_id,
        quantity=line.quantity,
        from_location=sale.location,
        reason=sale.number,
        source=line,
        occurred_at=sale.sold_at,
        picks=[(pick.batch_id, pick.quantity) for pick in line.picks.order_by("id")],
        held_since_then=stock_held_since,
    )
    revenues = _revenue_parts(line.amount, [movement.quantity for movement in movements])
    rows = [
        SaleLineBatch(
            organization_id=sale.organization_id,
            line=line,
            batch_id=movement.batch_id,
            quantity=movement.quantity,
            unit_cost=movement.unit_cost,
            cost_amount=line_total(movement.quantity, movement.unit_cost),
            revenue_amount=revenue,
        )
        for movement, revenue in zip(movements, revenues, strict=True)
    ]
    SaleLineBatch.objects.bulk_create(rows)
    line.cost_amount = sum((row.cost_amount for row in rows), Decimal("0.000"))
    line.save(update_fields=["cost_amount"])


@transaction.atomic
def confirm_sale(
    *, sale: Sale, actor: User | None, approve_credit: bool = False, stock_held_since: bool = False
) -> Sale:
    """Confirm a draft, or leave it pending when the customer's credit limit asks for approval (D-062).

    Above the limit under the "approval" policy the sale stays a draft marked `pending`, and the owner or a
    manager confirms it with `approve_credit`. Everything else is `_confirm_sale`.

    `stock_held_since` (a driver's sale dated by their phone, D-133): when the sale is dated on an earlier
    day, each line takes only kilos its place has held since that day, and is refused otherwise."""
    try:
        with transaction.atomic():
            return _confirm_sale(
                sale=sale, actor=actor, approve_credit=approve_credit, stock_held_since=stock_held_since
            )
    except CreditApprovalRequired as required:
        pending = _locked_draft_sale(sale)
        pending.credit_status = CreditStatus.PENDING
        pending.credit_over_by = required.over_by
        pending.save(update_fields=["credit_status", "credit_over_by", "updated_at"])
        audit.record(
            organization=pending.organization,
            actor=actor,
            action="sale.credit_approval_requested",
            target=pending,
            after={"over_by": str(required.over_by), "customer": pending.customer.reference},
        )
        return pending


def _confirm_sale(*, sale: Sale, actor: User | None, approve_credit: bool, stock_held_since: bool = False) -> Sale:
    """The goods leave the stock and the customer owes what was not paid, all in one transaction.

    Each line's kilos leave the sale's place oldest batch first (D-037); the line keeps which batches went,
    their cost per kg then and their cost (COGS). Refused as a whole when any line asks more than the place
    holds (each on `lines.<index>.quantity`), when the customer or the place were archived meanwhile, or when
    a walk-in customer does not pay everything. Lines are posted in product order, so two sales confirmed at
    once lock the same rows in the same order.
    """
    sale = _locked_draft_sale(sale)
    organization = sale.organization
    # A load's BL the office marks delivered is sold now, not at the load (D-185).
    if sale.delivery_status == DeliveryStatus.TO_DELIVER:
        sale.sold_at = timezone.now()
    errors = _sale_header_errors(organization, sale.customer, sale.location, sale.sold_at)
    if errors:
        raise ValidationError(errors)
    check_credit(sale, actor=actor, approve_credit=approve_credit)
    # The validated sale is the delivery note (D-095): it takes the next BL number of the year now, at the
    # server, so a driver who sold offline gets the next free number when the phone reconnects. A refusal
    # below rolls the counter back with everything else: no gap.
    draft_number = sale.number
    # The BL of a load has its number since the load (D-178).
    if sale.issued_at is None:
        sale.number = _next_yearly_number(organization, DELIVERY_NOTE_PREFIX, timezone.localdate().year)
    lines = list(sale.lines.order_by("id"))
    for index, line in sorted(enumerate(lines), key=lambda pair: pair[1].product_id):
        try:
            _post_line(sale, line, actor, stock_held_since=stock_held_since)
        except ValidationError as error:
            # The line's own savepoint is rolled back; the other lines are still checked, then all is refused.
            for field, messages in getattr(error, "message_dict", {"lines": error.messages}).items():
                key = line_error_key(index, "quantity") if field == "quantity" else field
                errors.setdefault(key, messages[0])
    if errors:
        raise ValidationError(errors)
    # The boxes leave with the goods, in this same transaction: a refused box movement refuses the sale (D-122).
    _post_sale_boxes(sale, actor, box_services.BoxMovementKind.LEAVE, from_customer=False)
    sale.cost_total = sum((line.cost_amount or Decimal("0.000") for line in lines), Decimal("0.000"))
    sale.amount_due = sale.total - sale.amount_paid
    sale.status = SaleStatus.CONFIRMED
    sale.confirmed_by = actor
    sale.confirmed_at = timezone.now()
    # A load's BL confirmed without the delivery screen (the office, or an older phone) is delivered as written.
    as_written = sale.delivery_status == DeliveryStatus.TO_DELIVER
    if as_written:
        sale.delivery_status = DeliveryStatus.DELIVERED
        sale.delivered_at = sale.confirmed_at
        sale.delivered_by = actor
    sale.save(
        update_fields=[
            "sold_at",
            "delivery_status",
            "delivered_at",
            "delivered_by",
            "number",
            "cost_total",
            "amount_due",
            "status",
            "confirmed_by",
            "confirmed_at",
            "credit_status",
            "credit_over_by",
            "credit_decided_by",
            "credit_decided_at",
            "updated_at",
        ]
    )
    record_receivable(sale)
    if sale.credit_status in (CreditStatus.WARNED, CreditStatus.APPROVED):
        audit.record(
            organization=organization,
            actor=actor,
            action="sale.credit_limit_exceeded",
            target=sale,
            after={"policy": sale.credit_status, "over_by": str(sale.credit_over_by)},
        )
    audit.record(
        organization=organization,
        actor=actor,
        action="sale.confirmed",
        target=sale,
        after={**_sale_snapshot(sale), "draft_number": draft_number},
    )
    if as_written:
        _add_revision(sale, SaleRevisionKind.DELIVERED, actor)
    if sale.delivery_status in (DeliveryStatus.DELIVERED, DeliveryStatus.PARTIAL):
        audit.record(
            organization=organization,
            actor=actor,
            action="sale.delivered",
            target=sale,
            after={"status": sale.delivery_status, "version": sale.version, "total": str(sale.total)},
        )
    below = [line for line in lines if line.below_minimum]
    if below:
        audit.record(
            organization=organization,
            actor=actor,
            action="sale.price_below_minimum",
            target=sale,
            after={"lines": [{"product": line.product_id, "unit_price": str(line.unit_price)} for line in below]},
        )
    return sale


@transaction.atomic
def cancel_sale(*, sale: Sale, actor: User | None, reason: str = "") -> Sale:
    """Give up a sale; it is never deleted. A draft simply stops. A confirmed sale is not edited either: its
    kilos come back to the same batches at the same place by `customer_return` movements (at the cost they
    left with), and it stays, marked cancelled, with who, when and why. Its batch rows stay; its status says
    they no longer count.

    An invoiced sale is refused: its issued invoice must first be cancelled by a full credit note (D-057); a
    draft invoice is thrown away with the sale. P2-T06 hook: money already paid on a cancelled sale becomes
    the customer's credit (refunded or allocated).
    """
    sale = _locked_sale(sale)
    if sale.status == SaleStatus.CANCELLED:
        raise ValidationError(_("Cette vente est déjà annulée."))
    invoice = sale.invoices.exclude(status=InvoiceStatus.CANCELLED).first()
    if invoice is not None and invoice.status == InvoiceStatus.ISSUED:
        raise ValidationError(
            _("Cette vente est facturée (%(number)s) : annulez d'abord la facture par un avoir.")
            % {"number": invoice.number}
        )
    if invoice is not None and invoice.sale_links.count() > 1:
        raise ValidationError(
            _("Cette vente est sur un brouillon de facture groupée : supprimez d'abord ce brouillon.")
        )
    if invoice is not None:
        delete_invoice(invoice=invoice, actor=actor)
    reason = reason.strip()[:255]
    if sale.status == SaleStatus.CONFIRMED:
        if not reason:
            raise ValidationError({"reason": _("Indiquez la raison de l'annulation.")})
        rows = list(
            SaleLineBatch.objects.filter(line__sale=sale).select_related("batch", "line").order_by("batch_id", "id")
        )
        returned = selectors.returned_by_sale_batch([row.pk for row in rows])
        for row in rows:
            # Kilos already given back by a credit note (D-070) are not returned twice.
            left = row.quantity - returned.get(row.pk, Decimal("0.000"))
            if left <= 0:
                continue
            try:
                inventory.post_movement(
                    organization=sale.organization,
                    actor=actor,
                    kind=inventory.MovementKind.CUSTOMER_RETURN,
                    batch=row.batch,
                    quantity=left,
                    to_location=sale.location,
                    reason=_("Annulation de la vente %(number)s") % {"number": sale.number},
                    source=row.line,
                )
            except ValidationError as error:
                messages = getattr(error, "message_dict", {})
                raise ValidationError({"location": messages.get("to_location", error.messages)[0]}) from None
    if sale.status == SaleStatus.CONFIRMED:
        # The boxes the client kept come back with the goods (D-122); refused when the client no longer has them.
        _post_sale_boxes(sale, actor, box_services.BoxMovementKind.COLLECT, from_customer=True)
    sale.status = SaleStatus.CANCELLED
    sale.cancelled_by = actor
    sale.cancelled_at = timezone.now()
    sale.cancel_reason = reason
    # The BL of a load given up, delivered or not, is "not delivered" (D-178); its versions say what it was.
    if sale.delivery_status:
        sale.delivery_status = DeliveryStatus.CANCELLED
    sale.save(
        update_fields=["status", "cancelled_by", "cancelled_at", "cancel_reason", "delivery_status", "updated_at"]
    )
    if sale.delivery_status:
        _add_revision(sale, SaleRevisionKind.CANCELLED, actor, note=reason)
    audit.record(
        organization=sale.organization, actor=actor, action="sale.cancelled", target=sale, after={"reason": reason}
    )
    return sale


@transaction.atomic
def create_sale_from_quote(
    *,
    quote: Quote,
    actor: User | None,
    location: "StockLocation | None" = None,
    sold_at: dt.datetime | None = None,
    payment: PaymentFields | None = None,
    confirm: bool = False,
    lines: Sequence[QuoteDeliveryFields] | None = None,
) -> Sale:
    """Turn an accepted quote, still valid, into a sale (a BL): same customer, products, prices and discounts.

    A quote may be delivered in several BL (D-115). Without `lines` the BL takes every kilo not on a BL yet;
    with `lines` it takes the kg given for each quote line, at most what is left on it. Kilos on a draft BL
    count as taken; cancelling a BL frees them. The place is the quote's unless another is given. The quote
    stays accepted and its sales point to it (`Sale.quote`). The quote is locked meanwhile, so two people
    cannot deliver the same kilos twice.
    """
    quote = _locked(quote)
    if quote.status != QuoteStatus.ACCEPTED:
        raise ValidationError(_("Seul un devis accepté devient une vente."))
    if quote.valid_until < timezone.localdate():
        raise _expiry_error(quote)
    quote_lines = {line.pk: line for line in quote.lines.select_related("product", "requested_batch").order_by("id")}
    delivery = selectors.quote_delivery(quote)
    if all(delivery[pk].remaining <= 0 for pk in quote_lines):
        numbers = ", ".join(sale.number for sale in selectors.live_sales_of(quote))
        raise ValidationError(_("Ce devis est déjà livré en entier (%(numbers)s).") % {"numbers": numbers})
    taken: list[tuple[QuoteLine, Decimal]] = []
    if lines is None:
        taken = [(line, delivery[pk].remaining) for pk, line in quote_lines.items() if delivery[pk].remaining > 0]
    else:
        errors: dict[str, str] = {}
        seen: set[int] = set()
        for index, fields in enumerate(lines):
            line = quote_lines.get(fields["quote_line"])
            if line is None or line.pk in seen:
                errors[line_error_key(index, "quote_line")] = _("Ligne de devis inconnue.")
                continue
            seen.add(line.pk)
            try:
                quantity = checked_quantity(fields["quantity"], allow_zero=True)
            except ValueError as error:
                errors[line_error_key(index, "quantity")] = str(error)
                continue
            left = delivery[line.pk].remaining
            if quantity > left:
                errors[line_error_key(index, "quantity")] = _("Il reste %(kg)s kg à livrer sur cette ligne.") % {
                    "kg": left
                }
            elif quantity > 0:
                taken.append((line, quantity))
        if errors:
            raise ValidationError(errors)
        if not taken:
            raise ValidationError(_("Indiquez au moins un poids à livrer."))
    location = location or quote.location
    if location is None:
        raise ValidationError({"location": _("Indiquez d'où part la marchandise.")})
    sale = create_sale(
        organization=quote.organization,
        actor=actor,
        customer=quote.customer,
        location=location,
        sold_at=sold_at,
        lines=[
            {
                "product": line.product,
                "quantity": quantity,
                "unit_price": line.unit_price,
                "discount_rate": line.discount_rate,
                # The lot picked on the quote goes on the BL (D-201).
                "batch": line.requested_batch,
            }
            for line, quantity in taken
        ],
        notes=quote.notes,
        payment=payment,
        quote=quote,
        typed_source=PriceSource.QUOTE,
        confirm=confirm,
        # The quote already passed the price floor, or an owner let it go (D-193): its prices are agreed.
        below_minimum_reason="devis",
    )
    audit.record(
        organization=quote.organization,
        actor=actor,
        action="quote.converted",
        target=quote,
        after={"sale": sale.number},
    )
    return sale


# ---- Finance settings (P2-T05, D-018, D-056) ----

# The first version every organization gets: the client's answers to Q5. The owner changes them on screen.
FIRST_SETTINGS: dict[str, Any] = {
    "vat_rate": Decimal("19.00"),
    "fiscal_stamp": Decimal("1.000"),
    "prices_include_vat": False,
    "withholding_rate": Decimal("0.00"),
}
SETTINGS_TEXT_FIELDS = ("legal_name", "address", "phone", "tax_id", "trade_register")
_TEXT_LENGTHS = {"legal_name": 200, "address": 255, "phone": 50, "tax_id": 30, "trade_register": 50}


class FinanceSettingsFields(TypedDict, total=False):
    # Percent with at most 2 decimals, as typed ("19", "7.50").
    vat_rate: Number
    # DT per invoice.
    fiscal_stamp: Number
    prices_include_vat: bool
    withholding_rate: Number
    # `block`, `approval` or `warn` (D-018, D-062).
    credit_policy: str
    legal_name: str
    address: str
    phone: str
    tax_id: str
    trade_register: str


def ensure_finance_settings(*, organization: Organization) -> FinanceSettings:
    """The organization's first finance settings version, made when missing (from its creation day)."""
    first = FinanceSettings.objects.for_organization(organization).order_by("valid_from").first()
    if first is not None:
        return first
    created = organization.created_at or timezone.now()
    return FinanceSettings.objects.create(
        organization=organization,
        valid_from=timezone.localdate(created),
        legal_name=organization.name,
        **FIRST_SETTINGS,
    )


def _percent(value: Any) -> Decimal | None:
    """A rate in percent typed by a person: 0 to 100 with at most 2 decimals; None when it is not one."""
    if value in (None, "") or isinstance(value, bool) or not isinstance(value, Decimal | int | str):
        return None
    try:
        rate = Decimal(value)
    except InvalidOperation:
        return None
    if not rate.is_finite() or rate != rate.quantize(_RATE_STEP) or not 0 <= rate <= MAX_DISCOUNT_RATE:
        return None
    return rate.quantize(_RATE_STEP)


def _settings_snapshot(version: FinanceSettings) -> dict[str, Any]:
    return {
        "valid_from": version.valid_from.isoformat(),
        "vat_rate": str(version.vat_rate),
        "fiscal_stamp": str(version.fiscal_stamp),
        "prices_include_vat": version.prices_include_vat,
        "withholding_rate": str(version.withholding_rate),
        "credit_policy": version.credit_policy,
        **{name: getattr(version, name) for name in SETTINGS_TEXT_FIELDS},
    }


@transaction.atomic
def save_finance_settings(
    *,
    organization: Organization,
    actor: User | None,
    valid_from: dt.date | None = None,
    **fields: Unpack[FinanceSettingsFields],
) -> FinanceSettings:
    """A new version of the finance settings from `valid_from` (today by default; a later day plans it). The
    past is refused: invoices already issued keep the values they copied anyway. Saving again for the same
    day replaces that day's version. Audited with the values before and after."""
    today = timezone.localdate()
    valid_from = valid_from or today
    errors: dict[str, str] = {}
    if valid_from < today:
        errors["valid_from"] = _("Une version ne peut pas commencer dans le passé.")
    in_force = selectors.finance_settings_on(organization, valid_from) or ensure_finance_settings(
        organization=organization
    )
    values: dict[str, Any] = {}
    for name in ("vat_rate", "withholding_rate"):
        raw: Any = fields.get(name, getattr(in_force, name))
        rate = _percent(raw)
        if rate is None:
            errors[name] = _("Indiquez un taux en %, de 0 à 100, avec 2 décimales au plus.")
        values[name] = rate
    stamp: Any = fields.get("fiscal_stamp", in_force.fiscal_stamp)
    try:
        values["fiscal_stamp"] = checked_amount(stamp)
    except (ValueError, TypeError):
        errors["fiscal_stamp"] = _("Indiquez un montant en DT, au millime près.")
    values["prices_include_vat"] = bool(fields.get("prices_include_vat", in_force.prices_include_vat))
    policy = str(fields.get("credit_policy", in_force.credit_policy))
    if policy not in CreditPolicy.values:
        errors["credit_policy"] = _("Choisissez bloquer, demander l'approbation ou avertir.")
    values["credit_policy"] = policy
    for name in SETTINGS_TEXT_FIELDS:
        text = str(fields.get(name, getattr(in_force, name)) or "").strip()
        if len(text) > _TEXT_LENGTHS[name]:
            errors[name] = _("Au plus %(count)d caractères.") % {"count": _TEXT_LENGTHS[name]}
        values[name] = text
    if errors:
        raise ValidationError(errors)
    existing = (
        FinanceSettings.objects.for_organization(organization).select_for_update().filter(valid_from=valid_from).first()
    )
    before = _settings_snapshot(existing) if existing is not None else _settings_snapshot(in_force)
    if existing is None:
        version = FinanceSettings.objects.create(
            organization=organization, valid_from=valid_from, created_by=actor, **values
        )
    else:
        version = existing
        for name, value in values.items():
            setattr(version, name, value)
        version.created_by = actor
        version.save()
    audit.record(
        organization=organization,
        actor=actor,
        action="finance_settings.saved",
        target=version,
        before=before,
        after=_settings_snapshot(version),
    )
    return version


# ---- Invoices and credit notes (P2-T05, D-057) ----

INVOICE_PREFIX = "FA"
CREDIT_NOTE_PREFIX = "AV"


def _next_yearly_number(organization: Organization, prefix: str, year: int) -> str:
    """FA-2026-0001, FA-2026-0002... per organization and year, under the counter's row lock.

    Called inside the transaction that issues the document, after every check: if anything fails later the
    transaction rolls back with the counter, so the series never has a gap (ARCHITECTURE §4.11).
    """
    series = f"{prefix}-{year}"
    DocumentCounter.objects.bulk_create(
        [DocumentCounter(organization=organization, series=series)], ignore_conflicts=True
    )
    counter = DocumentCounter.objects.select_for_update().get(organization=organization, series=series)
    counter.last_number += 1
    counter.save(update_fields=["last_number"])
    return f"{series}-{counter.last_number:04d}"


class InvoiceChoices(TypedDict, total=False):
    """What the person may change on a draft invoice; empty values take the settings (D-056)."""

    # False: an invoice without VAT.
    apply_vat: bool
    # One per line, in the order of the lines: the VAT rate in percent; empty = the product's or the settings'.
    vat_rates: Sequence[Number | None] | None
    # Typed VAT amounts by rate (percent → DT); a rate left out keeps the computed amount.
    vat_amounts: dict[Number, Number | None] | None
    # Empty = the settings' stamp.
    fiscal_stamp: Number | None
    # "Frais" in DT; empty = none (D-126).
    fees: Number | None
    withholding_applied: bool
    # Empty = the settings' rate.
    withholding_rate: Number | None
    notes: str


@dataclass(frozen=True)
class _Overrides:
    """The values typed on a draft, checked; None everywhere means "take the settings"."""

    apply_vat: bool
    vat_rates: list[Decimal | None]
    vat_amounts: dict[Decimal, Decimal]
    fiscal_stamp: Decimal | None
    withholding_applied: bool
    withholding_rate: Decimal | None
    notes: str
    fees: Decimal = Decimal("0.000")


def _settings_in_force(organization: Organization) -> FinanceSettings:
    return selectors.finance_settings_on(organization) or ensure_finance_settings(organization=organization)


def _checked_choices(choices: InvoiceChoices, line_count: int) -> _Overrides:
    """The typed values of a draft, or a ValidationError naming each wrong field (`lines.<i>.vat_rate`,
    `vat_amounts.<rate>`, `fiscal_stamp`, `withholding_rate`)."""
    errors: dict[str, str] = {}
    rate_message = _("Indiquez un taux en %, de 0 à 100, avec 2 décimales au plus.")
    typed_rates = list(choices.get("vat_rates") or [])
    if typed_rates and len(typed_rates) != line_count:
        errors["lines"] = _("Indiquez un taux par ligne de la facture.")
    rates: list[Decimal | None] = []
    for index in range(line_count):
        raw = typed_rates[index] if index < len(typed_rates) else None
        if raw in (None, ""):
            rates.append(None)
            continue
        rate = _percent(raw)
        if rate is None:
            errors[line_error_key(index, "vat_rate")] = rate_message
        rates.append(rate)
    amounts: dict[Decimal, Decimal] = {}
    for raw_rate, raw_amount in (choices.get("vat_amounts") or {}).items():
        rate = _percent(raw_rate)
        if rate is None:
            errors["vat_amounts"] = rate_message
            continue
        if raw_amount in (None, ""):
            continue
        try:
            amounts[rate] = checked_amount(raw_amount)
        except (ValueError, TypeError):
            errors[f"vat_amounts.{rate}"] = _("Indiquez un montant en DT, au millime près.")
    stamp: Decimal | None = None
    raw_stamp: Any = choices.get("fiscal_stamp")
    if raw_stamp not in (None, ""):
        try:
            stamp = checked_amount(raw_stamp)
        except (ValueError, TypeError):
            errors["fiscal_stamp"] = _("Indiquez un montant en DT, au millime près.")
    fees = Decimal("0.000")
    raw_fees: Any = choices.get("fees")
    if raw_fees not in (None, ""):
        try:
            fees = checked_amount(raw_fees)
        except (ValueError, TypeError):
            errors["fees"] = _("Indiquez un montant en DT, au millime près.")
    withholding_rate: Decimal | None = None
    raw_withholding = choices.get("withholding_rate")
    if raw_withholding not in (None, ""):
        withholding_rate = _percent(raw_withholding)
        if withholding_rate is None:
            errors["withholding_rate"] = rate_message
    if errors:
        raise ValidationError(errors)
    return _Overrides(
        apply_vat=choices.get("apply_vat", True),
        vat_rates=rates,
        vat_amounts=amounts,
        fiscal_stamp=stamp,
        withholding_applied=choices.get("withholding_applied", False),
        withholding_rate=withholding_rate,
        notes=(choices.get("notes") or "").strip(),
        fees=fees,
    )


def _stored_overrides(invoice: Invoice) -> _Overrides:
    """The values typed on a draft, read back from it (what was not typed follows the settings)."""
    lines = list(invoice.lines.order_by("id"))
    return _Overrides(
        apply_vat=invoice.apply_vat,
        vat_rates=[line.vat_rate if line.vat_rate_overridden else None for line in lines],
        vat_amounts={row.rate: row.amount for row in invoice.vat_lines.filter(amount_overridden=True)},
        fiscal_stamp=invoice.fiscal_stamp if invoice.fiscal_stamp_overridden else None,
        withholding_applied=invoice.withholding_applied,
        withholding_rate=invoice.withholding_rate if invoice.withholding_rate_overridden else None,
        notes=invoice.notes,
        fees=invoice.fees,
    )


def _default_rate(product: "Product", version: FinanceSettings) -> Decimal:
    """The rate a line takes when none is typed: the product's own (0 = exempt), else the settings'."""
    own: Decimal | None = product.vat_rate
    return own if own is not None else version.vat_rate


def _compute(invoice: Invoice, version: FinanceSettings, overrides: _Overrides) -> None:
    """Set every amount of a draft from its lines, the settings `version` and the typed values, and store
    which values were typed (`*_overridden`). Raises a ValidationError for a typed VAT amount above what
    its rate holds."""
    lines = list(invoice.lines.select_related("product").order_by("id"))
    rates: list[Decimal] = []
    rate_typed: list[bool] = []
    for line, typed in zip(lines, overrides.vat_rates, strict=True):
        default = _default_rate(line.product, version)
        rates.append(typed if typed is not None else default)
        rate_typed.append(typed is not None and typed != default)
    stamp = overrides.fiscal_stamp if overrides.fiscal_stamp is not None else version.fiscal_stamp
    withholding_rate = (
        overrides.withholding_rate if overrides.withholding_rate is not None else version.withholding_rate
    )
    amounts = invoicing.compute(
        [
            invoicing.LineInput(amount=line.amount, vat_rate=rate, unit_price=line.unit_price)
            for line, rate in zip(lines, rates, strict=True)
        ],
        apply_vat=overrides.apply_vat,
        prices_include_vat=version.prices_include_vat,
        fiscal_stamp=stamp,
        withholding_rate=withholding_rate if overrides.withholding_applied else None,
        vat_overrides=overrides.vat_amounts if overrides.apply_vat else {},
        fees=overrides.fees,
    )
    if amounts.refused_overrides:
        raise ValidationError(
            {
                f"vat_amounts.{rate}": _("La TVA à %(rate)s %% ne peut pas dépasser le montant de ses lignes.")
                % {"rate": rate}
                for rate in amounts.refused_overrides
            }
        )
    for line, result, is_typed in zip(lines, amounts.lines, rate_typed, strict=True):
        line.vat_rate = result.vat_rate
        line.vat_rate_overridden = is_typed and overrides.apply_vat
        line.unit_price_excl_tax = result.unit_price_excl_tax
        line.amount_excl_tax = result.amount_excl_tax
        line.vat_amount = result.vat_amount
        line.amount_incl_tax = result.amount_incl_tax
    InvoiceLine.objects.bulk_update(
        lines,
        [
            "vat_rate",
            "vat_rate_overridden",
            "unit_price_excl_tax",
            "amount_excl_tax",
            "vat_amount",
            "amount_incl_tax",
        ],
    )
    invoice.vat_lines.all().delete()
    InvoiceVatLine.objects.bulk_create(
        [
            InvoiceVatLine(
                organization_id=invoice.organization_id,
                invoice=invoice,
                rate=group.rate,
                base=group.base,
                computed_amount=group.computed_amount,
                amount=group.amount,
                amount_overridden=group.overridden,
            )
            for group in amounts.vat_groups
        ]
    )
    invoice.settings_version = version
    invoice.prices_include_vat = version.prices_include_vat
    invoice.apply_vat = overrides.apply_vat
    invoice.subtotal = sum((line.gross_amount for line in lines), Decimal("0.000"))
    invoice.discount_total = sum((line.discount_amount for line in lines), Decimal("0.000"))
    invoice.total_excl_tax = amounts.total_excl_tax
    invoice.vat_total = amounts.vat_total
    invoice.fiscal_stamp = amounts.fiscal_stamp
    invoice.fiscal_stamp_overridden = stamp != version.fiscal_stamp
    invoice.fees = amounts.fees
    invoice.total_incl_tax = amounts.total_incl_tax
    invoice.withholding_applied = overrides.withholding_applied
    invoice.withholding_rate = withholding_rate
    invoice.withholding_rate_overridden = withholding_rate != version.withholding_rate
    invoice.withholding_amount = amounts.withholding_amount
    invoice.net_to_pay = amounts.net_to_pay
    invoice.notes = overrides.notes
    invoice.save()


def _invoice_snapshot(invoice: Invoice) -> dict[str, Any]:
    """What an invoice says, for the audit: totals and every value typed by hand (`overrides`)."""
    lines = list(invoice.lines.select_related("product").order_by("id"))
    vat_lines = list(invoice.vat_lines.order_by("-rate"))
    return {
        "number": invoice.number,
        "status": invoice.status,
        "sales": [sale.number for sale in invoice.sales.order_by("sold_at", "id")],
        "apply_vat": invoice.apply_vat,
        "prices_include_vat": invoice.prices_include_vat,
        "vat": [{"rate": str(row.rate), "base": str(row.base), "amount": str(row.amount)} for row in vat_lines],
        "total_excl_tax": str(invoice.total_excl_tax),
        "vat_total": str(invoice.vat_total),
        "fiscal_stamp": str(invoice.fiscal_stamp),
        "fees": str(invoice.fees),
        "total_incl_tax": str(invoice.total_incl_tax),
        "withholding_applied": invoice.withholding_applied,
        "withholding_rate": str(invoice.withholding_rate),
        "withholding_amount": str(invoice.withholding_amount),
        "net_to_pay": str(invoice.net_to_pay),
        "overrides": {
            "vat_rates": {line.product.reference: str(line.vat_rate) for line in lines if line.vat_rate_overridden},
            "vat_amounts": {
                str(row.rate): {"computed": str(row.computed_amount), "typed": str(row.amount)}
                for row in vat_lines
                if row.amount_overridden
            },
            "fiscal_stamp": str(invoice.fiscal_stamp) if invoice.fiscal_stamp_overridden else None,
            "withholding_rate": str(invoice.withholding_rate) if invoice.withholding_rate_overridden else None,
        },
    }


def _lots_of(line: SaleLine) -> str:
    numbers = [row.batch.number for row in line.batches.select_related("batch").order_by("id")]
    return ", ".join(numbers)[:255]


def _checked_sale_to_invoice(sale: Sale) -> None:
    if sale.status != SaleStatus.CONFIRMED:
        raise ValidationError(_("Seule une vente confirmée se facture."))
    if sale.is_opening:
        raise ValidationError(_("Un solde d'ouverture ne se facture pas : la facture existe déjà sur papier."))
    if sale.customer.is_walk_in:
        raise ValidationError(
            {"customer": _("Une vente au client de passage ne se facture pas : la facture nomme son client.")}
        )
    live = sale.invoices.exclude(status=InvoiceStatus.CANCELLED).first()
    if live is not None:
        raise ValidationError(
            _("Cette vente a déjà sa facture %(number)s.") % {"number": live.number or _("(brouillon)")}
        )


@transaction.atomic
def create_invoice(
    *,
    sale: Sale | None = None,
    sales: Sequence[Sale] = (),
    actor: User | None,
    issue: bool = False,
    **choices: Unpack[InvoiceChoices],
) -> Invoice:
    """Prepare the invoice of one or several confirmed sales (BL) of one customer (a draft, without number),
    or with `issue` issue it at once.

    The lines are the sales', as charged (kg, prices, discounts), BL after BL. VAT, stamp (one per invoice)
    and withholding are proposed from the finance settings in force and each product's own rate; `choices`
    may leave VAT out or type a rate, an amount of VAT, the stamp or the withholding rate. A BL is on one live
    invoice at most; the walk-in customer is not invoiced (provisional, D-057). Several BLs make a "facture
    récapitulative" (D-101).
    """
    wanted = {chosen.pk: chosen for chosen in (*sales, *([sale] if sale is not None else []))}
    if not wanted:
        raise ValidationError({"sales": _("Choisissez au moins un bon de livraison à facturer.")})
    locked = sorted(
        (_locked_sale(chosen) for _pk, chosen in sorted(wanted.items())), key=lambda row: (row.sold_at, row.pk)
    )
    if len({chosen.customer_id for chosen in locked}) > 1:
        raise ValidationError({"sales": _("Une facture ne regroupe que les bons de livraison d'un même client.")})
    for chosen in locked:
        _checked_sale_to_invoice(chosen)
    sale = locked[0]
    sale_lines = [line for chosen in locked for line in chosen.lines.select_related("product").order_by("id")]
    overrides = _checked_choices(choices, len(sale_lines))
    invoice = Invoice.objects.create(
        organization=sale.organization,
        customer=sale.customer,
        created_by=actor,
    )
    InvoiceSale.objects.bulk_create(
        [InvoiceSale(organization_id=sale.organization_id, invoice=invoice, sale=chosen) for chosen in locked]
    )
    InvoiceLine.objects.bulk_create(
        [
            InvoiceLine(
                organization_id=sale.organization_id,
                invoice=invoice,
                sale_line=line,
                product=line.product,
                product_reference=line.product.reference,
                product_name=line.product.name,
                lots=_lots_of(line),
                quantity=line.quantity,
                unit_price=line.unit_price,
                discount_rate=line.discount_rate,
                gross_amount=line.gross_amount,
                discount_amount=line.discount_amount,
                amount=line.amount,
                unit_price_excl_tax=line.unit_price,
                amount_excl_tax=line.amount,
                amount_incl_tax=line.amount,
            )
            for line in sale_lines
        ]
    )
    _compute(invoice, _settings_in_force(sale.organization), overrides)
    audit.record(
        organization=sale.organization,
        actor=actor,
        action="invoice.created",
        target=invoice,
        after=_invoice_snapshot(invoice),
    )
    if issue:
        return issue_invoice(invoice=invoice, actor=actor)
    return invoice


def _locked_invoice(invoice: Invoice) -> Invoice:
    """The invoice locked until commit, so it is never issued or credited twice at once."""
    return Invoice.objects.select_for_update(of=("self",)).select_related("organization", "customer").get(pk=invoice.pk)


def _locked_draft_invoice(invoice: Invoice) -> Invoice:
    locked = _locked_invoice(invoice)
    if locked.status != InvoiceStatus.DRAFT:
        raise ValidationError(
            _("La facture %(number)s est émise : elle ne change plus. Corrigez-la par un avoir.")
            % {"number": locked.number}
        )
    return locked


@transaction.atomic
def update_invoice(
    *, invoice: Invoice, actor: User | None, issue: bool = False, **choices: Unpack[InvoiceChoices]
) -> Invoice:
    """Change a draft: with or without VAT, rates, amounts of VAT, stamp, withholding and notes (all given
    again: an empty value takes the settings). Every typed value is flagged and the change is audited. With
    `issue`, issue it too (one transaction)."""
    invoice = _locked_draft_invoice(invoice)
    before = _invoice_snapshot(invoice)
    overrides = _checked_choices(choices, invoice.lines.count())
    _compute(invoice, _settings_in_force(invoice.organization), overrides)
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="invoice.updated",
        target=invoice,
        before=before,
        after=_invoice_snapshot(invoice),
    )
    if issue:
        return issue_invoice(invoice=invoice, actor=actor)
    return invoice


@transaction.atomic
def delete_invoice(*, invoice: Invoice, actor: User | None) -> None:
    """Throw a draft away (it has no number, so nothing is lost). An issued invoice is never deleted."""
    invoice = _locked_draft_invoice(invoice)
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="invoice.deleted",
        target=invoice,
        before=_invoice_snapshot(invoice),
    )
    invoice.delete()


def record_invoice_receivable(invoice: Invoice) -> None:
    """An issued invoice's `net_to_pay` (VAT and stamp in, withholding out) is what the customer owes for its
    sale from now on (D-062): the sale's outstanding amount is refreshed."""
    refresh_invoice_sales(invoice)


def _refuse_no_vat_on_vat_lots(sales: Sequence[Sale]) -> None:
    """Goods bought with VAT are sold with VAT (D-202): an invoice without VAT is refused when one of its BL took
    kilos from a lot bought with VAT, and the message names the products."""
    names = sorted(
        set(
            SaleLineBatch.objects.filter(line__sale__in=sales, batch__bought_with_vat=True).values_list(
                "line__product__name", flat=True
            )
        )
    )
    if names:
        raise ValidationError(
            {
                "apply_vat": _("Achetés avec TVA, ces produits se facturent avec TVA : %(products)s.")
                % {"products": ", ".join(names)}
            }
        )


@transaction.atomic
def issue_invoice(*, invoice: Invoice, actor: User | None) -> Invoice:
    """Number and freeze a draft, all in one transaction.

    What was not typed by hand is computed again from the finance settings in force now; the seller (from the
    settings) and the customer are copied; the date is today and the due date today + the customer's payment
    terms. The number (FA-<year>-0001...) is taken last, so a refusal never uses one. From then on the
    invoice never changes: a credit note corrects it. The sale's `tax_amount` becomes the invoice's VAT.
    """
    invoice = _locked_draft_invoice(invoice)
    sales = _locked_sales_of(invoice)
    if any(sale.status != SaleStatus.CONFIRMED for sale in sales):
        raise ValidationError(_("Seule une vente confirmée se facture."))
    version = _settings_in_force(invoice.organization)
    _compute(invoice, version, _stored_overrides(invoice))
    if invoice.lines.count() == 0:
        raise ValidationError(_("Cette facture n'a aucune ligne."))
    if not invoice.apply_vat:
        _refuse_no_vat_on_vat_lots(sales)
    customer = invoice.customer
    today = timezone.localdate()
    invoice.seller_name = version.legal_name or invoice.organization.name
    invoice.seller_address = version.address
    invoice.seller_phone = version.phone
    invoice.seller_tax_id = version.tax_id
    invoice.seller_trade_register = version.trade_register
    invoice.customer_name = customer.name
    invoice.customer_address = customer.address
    invoice.customer_city = customer.city
    invoice.customer_tax_id = customer.tax_id
    invoice.issued_on = today
    invoice.due_on = today + dt.timedelta(days=customer.payment_terms_days)
    invoice.issued_by = actor
    invoice.issued_at = timezone.now()
    invoice.status = InvoiceStatus.ISSUED
    invoice.number = _next_yearly_number(invoice.organization, INVOICE_PREFIX, today.year)
    invoice.save()
    lines = list(invoice.lines.select_related("product", "sale_line"))
    for line in lines:
        line.product_reference = line.product.reference
        line.product_name = line.product.name
    InvoiceLine.objects.bulk_update(lines, ["product_reference", "product_name"])
    # The invoice's VAT is shared over its BLs by what each one holds (all of it for a single BL).
    shares = receivables.split(
        invoice.vat_total,
        [sum((line.amount for line in lines if line.sale_line.sale_id == sale.pk), Decimal("0.000")) for sale in sales],
    )
    for sale, share in zip(sales, shares, strict=True):
        sale.tax_amount = share
        sale.save(update_fields=["tax_amount", "updated_at"])
    record_invoice_receivable(invoice)
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="invoice.issued",
        target=invoice,
        after=_invoice_snapshot(invoice),
    )
    return invoice


class CreditLineFields(TypedDict, total=False):
    # None: an id not on the invoice (reported on `lines.<index>.invoice_line`).
    invoice_line: InvoiceLine | None
    # Kilos given back (a return, a weight dispute); empty or 0 for a price correction.
    quantity: Number | None
    # Amount without VAT given back; empty = the kilos' share of the line.
    amount: Number | None


@dataclass(frozen=True)
class _CreditPart:
    invoice_line: InvoiceLine
    quantity: Decimal
    excl: Decimal
    vat: Decimal


def _full_credit_parts(invoice: Invoice, credited: dict[int, selectors.CreditedLine]) -> list[_CreditPart]:
    parts = []
    for line in invoice.lines.order_by("id"):
        done = credited.get(line.pk)
        quantity = line.quantity - (done.quantity if done else Decimal("0.000"))
        excl = line.amount_excl_tax - (done.amount_excl_tax if done else Decimal("0.000"))
        vat = line.vat_amount - (done.vat_amount if done else Decimal("0.000"))
        if quantity > 0 or excl > 0 or vat > 0:
            parts.append(_CreditPart(line, max(quantity, Decimal("0.000")), excl, vat))
    return parts


def _partial_credit_parts(
    invoice: Invoice, lines: Sequence[CreditLineFields], credited: dict[int, selectors.CreditedLine]
) -> list[_CreditPart]:
    """The kilos and amounts given back per line, checked against what each line still holds; problems come
    back on `lines.<index>.<field>`."""
    errors: dict[str, str] = {}
    parts: list[_CreditPart] = []
    seen: set[int] = set()
    if not lines:
        errors["lines"] = _("Indiquez au moins une ligne à rendre.")
    for index, fields in enumerate(lines):
        line = fields.get("invoice_line")
        if line is None or line.invoice_id != invoice.pk:
            errors[line_error_key(index, "invoice_line")] = _("Cette ligne n'est pas sur la facture.")
            continue
        if line.pk in seen:
            errors[line_error_key(index, "invoice_line")] = _("Cette ligne est déjà rendue plus haut.")
            continue
        seen.add(line.pk)
        done = credited.get(line.pk)
        quantity_left = line.quantity - (done.quantity if done else Decimal("0.000"))
        excl_left = line.amount_excl_tax - (done.amount_excl_tax if done else Decimal("0.000"))
        vat_left = line.vat_amount - (done.vat_amount if done else Decimal("0.000"))
        raw_quantity: Any = fields.get("quantity")
        quantity = Decimal("0.000")
        if raw_quantity not in (None, ""):
            try:
                quantity = checked_quantity(raw_quantity, allow_zero=True)
            except (ValueError, TypeError):
                errors[line_error_key(index, "quantity")] = _("Indiquez un poids en kg, au gramme près.")
                continue
            if quantity > quantity_left:
                errors[line_error_key(index, "quantity")] = _("Il reste %(kg)s kg à rendre sur cette ligne.") % {
                    "kg": quantity_left
                }
                continue
        raw_amount: Any = fields.get("amount")
        if raw_amount not in (None, ""):
            try:
                excl = checked_amount(raw_amount)
            except (ValueError, TypeError):
                errors[line_error_key(index, "amount")] = _("Indiquez un montant en DT, au millime près.")
                continue
        elif quantity == quantity_left:
            excl = excl_left
        else:
            excl = min(money(line.amount_excl_tax * quantity / line.quantity), excl_left)
        if excl > excl_left:
            errors[line_error_key(index, "amount")] = _(
                "Il reste %(amount)s DT hors taxe à rendre sur cette ligne."
            ) % {"amount": display_money(excl_left)}
            continue
        if excl <= 0:
            errors[line_error_key(index, "amount")] = _("Indiquez les kilos ou le montant hors taxe à rendre.")
            continue
        if excl == excl_left:
            vat = vat_left
        elif line.amount_excl_tax > 0:
            vat = min(money(line.vat_amount * excl / line.amount_excl_tax), vat_left)
        else:
            vat = Decimal("0.000")
        parts.append(_CreditPart(line, quantity, excl, vat))
    if errors:
        raise ValidationError(errors)
    return parts


def _take_back(
    *, note: CreditNote, credit_line: CreditNoteLine, part: _CreditPart, index: int, sale: Sale, actor: User | None
) -> None:
    """Share what one credit note line gives back over the batches of the sale line, and move the stock.

    Kilos that come back (`restock` or `loss`) are taken from the batches the sale line left, in order, up to
    what each batch has not yet got back; they re-enter `sale.location` by `customer_return` movements at the
    cost they left with, and a `loss` note writes them off at once (reason: the credit note), on the same
    batch. The amount without VAT is shared by those kilos; with no kilos back (price correction, goods not
    taken back) it is shared by the kilos sold. Each part is rounded once, the last one takes the rest.
    """
    batch_rows = list(
        SaleLineBatch.objects.filter(line_id=part.invoice_line.sale_line_id).select_related("batch").order_by("id")
    )
    returned = selectors.returned_by_sale_batch([row.pk for row in batch_rows])
    taken: list[tuple[SaleLineBatch, Decimal]] = []
    if note.stock != CreditNoteStock.NONE and part.quantity > 0:
        needed = part.quantity
        for row in batch_rows:
            left = row.quantity - returned.get(row.pk, Decimal("0.000"))
            take = min(left, needed)
            if take > 0:
                taken.append((row, take))
                needed -= take
        if needed > 0:
            raise ValidationError(
                {
                    line_error_key(index, "quantity"): _(
                        "Il ne reste que %(kg)s kg de cette vente à remettre dans les lots d'origine."
                    )
                    % {"kg": part.quantity - needed}
                }
            )
    weighted = taken or [(row, row.quantity) for row in batch_rows]
    revenues = _revenue_parts(part.excl, [weight for _row, weight in weighted])
    for (row, weight), revenue in zip(weighted, revenues, strict=True):
        kilos = weight if taken else Decimal("0.000")
        CreditNoteLineBatch.objects.create(
            organization_id=note.organization_id,
            line=credit_line,
            sale_line_batch=row,
            quantity=kilos,
            revenue_amount=revenue,
            cost_amount=line_total(kilos, row.unit_cost),
        )
        if kilos == 0:
            continue
        inventory.post_movement(
            organization=note.organization,
            actor=actor,
            kind=inventory.MovementKind.CUSTOMER_RETURN,
            batch=row.batch,
            quantity=kilos,
            to_location=sale.location,
            reason=_("Retour client · avoir %(number)s") % {"number": note.number},
            source=credit_line,
        )
        if note.stock == CreditNoteStock.LOSS:
            inventory.post_movement(
                organization=note.organization,
                actor=actor,
                kind=inventory.MovementKind.LOSS,
                batch=row.batch,
                quantity=kilos,
                from_location=sale.location,
                reason=_("Retour client avarié · avoir %(number)s") % {"number": note.number},
                source=credit_line,
            )


@transaction.atomic
def create_credit_note(
    *,
    invoice: Invoice,
    actor: User | None,
    kind: str,
    reason: str,
    lines: Sequence[CreditLineFields] = (),
    stock: str = CreditNoteStock.NONE,
) -> CreditNote:
    """Correct an issued invoice: the only way (D-057). Numbered AV-<year>-0001... at once, never changed.

    `full` gives back everything the invoice still holds (lines, VAT, stamp, the rest of the withholding) and
    cancels the invoice, so its sale may be invoiced again. `partial` gives back, per line, kilos (their
    share of the line) or an amount without VAT, with the line's VAT in proportion, and the withholding at
    the invoice's rate.

    `stock` says what happens to the kilos given back (customer returns, D-070): `none` moves nothing,
    `restock` puts them back in the sale's place on the batches they left, `loss` does the same and writes
    them off. Either way the lot's revenue and cost of goods drop by what came back.
    """
    invoice = _locked_invoice(invoice)
    if invoice.status == InvoiceStatus.DRAFT:
        raise ValidationError(_("Un brouillon se modifie ou se supprime : émettez d'abord la facture."))
    if invoice.status == InvoiceStatus.CANCELLED:
        raise ValidationError(_("La facture %(number)s est déjà annulée par avoir.") % {"number": invoice.number})
    reason = reason.strip()[:255]
    if not reason:
        raise ValidationError({"reason": _("Indiquez la raison de l'avoir.")})
    if kind not in CreditNoteKind.values:
        raise ValidationError({"kind": _("Type d'avoir inconnu.")})
    if stock not in CreditNoteStock.values:
        raise ValidationError({"stock": _("Indiquez ce que deviennent les kilos rendus.")})
    credited = selectors.credited_by_line(invoice)
    already = invoice.credit_notes.aggregate(
        stamp=Sum("fiscal_stamp"), fees=Sum("fees"), withholding=Sum("withholding_amount")
    )
    withholding_left = invoice.withholding_amount - (already["withholding"] or Decimal("0.000"))
    if kind == CreditNoteKind.FULL:
        parts = _full_credit_parts(invoice, credited)
        stamp = invoice.fiscal_stamp - (already["stamp"] or Decimal("0.000"))
        fees = invoice.fees - (already["fees"] or Decimal("0.000"))
        withholding = withholding_left
    else:
        parts = _partial_credit_parts(invoice, lines, credited)
        stamp = Decimal("0.000")
        fees = Decimal("0.000")
        goods = sum((part.excl + part.vat for part in parts), Decimal("0.000"))
        withholding = Decimal("0.000")
        if invoice.withholding_amount > 0:
            withholding = min(money(goods * invoice.withholding_rate / 100), withholding_left)
    total_excl = sum((part.excl for part in parts), Decimal("0.000"))
    vat_total = sum((part.vat for part in parts), Decimal("0.000"))
    today = timezone.localdate()
    note = CreditNote.objects.create(
        organization=invoice.organization,
        number=_next_yearly_number(invoice.organization, CREDIT_NOTE_PREFIX, today.year),
        invoice=invoice,
        kind=kind,
        issued_on=today,
        reason=reason,
        stock=stock,
        total_excl_tax=total_excl,
        vat_total=vat_total,
        fiscal_stamp=stamp,
        fees=fees,
        total_incl_tax=total_excl + vat_total + stamp + fees,
        withholding_amount=withholding,
        net_amount=total_excl + vat_total + stamp + fees - withholding,
        created_by=actor,
    )
    sales = {sale.pk: sale for sale in _locked_sales_of(invoice)}
    for index, part in enumerate(parts):
        credit_line = CreditNoteLine.objects.create(
            organization_id=invoice.organization_id,
            credit_note=note,
            invoice_line=part.invoice_line,
            quantity=part.quantity,
            vat_rate=part.invoice_line.vat_rate,
            amount_excl_tax=part.excl,
            vat_amount=part.vat,
            amount_incl_tax=part.excl + part.vat,
        )
        sale = sales[part.invoice_line.sale_line.sale_id]
        _take_back(note=note, credit_line=credit_line, part=part, index=index, sale=sale, actor=actor)
    if kind == CreditNoteKind.FULL:
        invoice.status = InvoiceStatus.CANCELLED
        invoice.cancelled_at = timezone.now()
        invoice.save(update_fields=["status", "cancelled_at", "updated_at"])
        # Its BLs are free again: they may be invoiced anew.
        InvoiceSale.objects.filter(invoice=invoice).update(is_live=False)
        for sale in sales.values():
            sale.tax_amount = None
            sale.save(update_fields=["tax_amount", "updated_at"])
    refresh_invoice_sales(invoice)
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="credit_note.created",
        target=note,
        after={
            "number": note.number,
            "invoice": invoice.number,
            "kind": kind,
            "reason": reason,
            "stock": stock,
            "total_excl_tax": str(note.total_excl_tax),
            "vat_total": str(note.vat_total),
            "fiscal_stamp": str(note.fiscal_stamp),
            "fees": str(note.fees),
            "withholding_amount": str(note.withholding_amount),
            "net_amount": str(note.net_amount),
        },
    )
    return note


# ---- Customer payments, balance, credit, withholding certificates (P2-T06, D-062, D-063) ----

PAYMENT_SERIES = "RG"
MAX_CERTIFICATE_BYTES = 8 * 1024 * 1024


class AllocationFields(TypedDict, total=False):
    # One of the two: a sale (BL), or an invoice whose amount is spread over its BLs, oldest first (D-197).
    sale: Sale
    invoice: Invoice
    amount: Number


class PaymentLineFields(TypedDict, total=False):
    """One means of payment of a règlement (D-197). A cheque or a traite also gives its number, bank, drawer
    and échéance (`due_on`); other methods may give a reference."""

    method: str
    amount: Number
    reference: str
    number: str
    bank: "Bank | None"
    drawer: str
    due_on: dt.date | None


# At most this many lines in one règlement.
MAX_PAYMENT_LINES = 50


def refresh_sale_due(sale: Sale) -> None:
    """Write the sale's outstanding amount (`amount_due`) from its documents: what it owes (invoice, credit
    notes, withholding) less what was paid on the spot and allocated. Only a confirmed sale is a receivable."""
    if sale.status != SaleStatus.CONFIRMED:
        return
    rows = receivables.sale_receivables(sale.organization, sale_ids=[sale.pk])
    if rows and rows[0].outstanding != sale.amount_due:
        sale.amount_due = rows[0].outstanding
        sale.save(update_fields=["amount_due", "updated_at"])


def _locked_sales_of(invoice: Invoice) -> list[Sale]:
    """The invoice's BLs, locked in a fixed order (by id), then listed oldest first."""
    ids = sorted(invoice.sale_links.values_list("sale_id", flat=True))
    return sorted((_locked_sale(Sale(pk=pk)) for pk in ids), key=lambda row: (row.sold_at, row.pk))


def refresh_invoice_sales(invoice: Invoice) -> None:
    """Refresh the outstanding amount of every BL the invoice bills."""
    for sale in _locked_sales_of(invoice):
        refresh_sale_due(sale)


def _payment_snapshot(payment: CustomerPayment) -> dict[str, Any]:
    return {
        "number": payment.number,
        "customer": payment.customer.reference,
        "amount": str(payment.amount),
        "method": payment.method,
        "received_on": payment.received_on.isoformat(),
        "reference": payment.reference,
        "lines": [_line_snapshot(line) for line in payment.lines.select_related("instrument__bank").order_by("id")],
        "allocations": [
            {"sale": row.sale.number, "amount": str(row.amount)}
            for row in payment.allocations.select_related("sale").order_by("id")
        ],
    }


def _line_snapshot(line: CustomerPaymentLine) -> dict[str, Any]:
    row: dict[str, Any] = {"method": line.method, "amount": str(line.amount), "reference": line.reference}
    if line.instrument is not None:
        row["number"] = line.instrument.number
        row["bank"] = line.instrument.bank.code if line.instrument.bank else ""
        row["due_on"] = line.instrument.due_on.isoformat()
    return row


def _allocated_total(payment: CustomerPayment) -> Decimal:
    """What the payment settles on sales now: its allocations less what its impayés took back (D-217)."""
    allocated = payment.allocations.aggregate(total=Sum("amount"))["total"] or Decimal("0.000")
    released = UnpaidRelease.objects.filter(unpaid__payment=payment).aggregate(total=Sum("amount"))["total"]
    return allocated - (released or Decimal("0.000"))


def _unpaid_total(payment: CustomerPayment) -> Decimal:
    return UnpaidEffet.objects.filter(payment=payment).aggregate(total=Sum("amount"))["total"] or Decimal("0.000")


def _allocate(
    payment: CustomerPayment,
    available: Decimal,
    requested: Sequence[AllocationFields] | None,
) -> list[PaymentAllocation]:
    """Write the allocations of `payment`, at most `available` in all: the sales named in `requested` (each
    no more than what it still owes), or, with None, the customer's oldest open sales first. The customer's
    sales are locked, so two payments cannot settle the same amount twice."""
    organization = payment.organization
    list(
        Sale.objects.select_for_update(of=("self",))
        .filter(organization=organization, customer_id=payment.customer_id, status=SaleStatus.CONFIRMED)
        .order_by("id")
        .values_list("pk", flat=True)
    )
    open_rows = {
        row.sale_id: row
        for row in receivables.sale_receivables(organization, customer_id=payment.customer_id)
        if row.outstanding > 0
    }
    plan: list[tuple[int, Decimal]] = []
    errors: dict[str, str] = {}
    if requested is None:
        left = available
        for row in sorted(open_rows.values(), key=lambda row: (row.document_date, row.sale_id)):
            if left <= 0:
                break
            part = min(left, row.outstanding)
            plan.append((row.sale_id, part))
            left -= part
    else:
        taken: dict[int, Decimal] = {}
        for index, item in enumerate(requested):
            key = f"allocations.{index}.amount"
            try:
                amount = checked_amount(item["amount"])
            except (ValueError, TypeError):
                errors[key] = _("Indiquez un montant en DT, au millime près.")
                continue
            invoice = item.get("invoice")
            if invoice is not None:
                _plan_invoice(payment, invoice, amount, open_rows, taken, plan, errors, key)
                continue
            sale = item["sale"]
            open_row = open_rows.get(sale.pk)
            if open_row is None or sale.organization_id != organization.pk or sale.customer_id != payment.customer_id:
                errors[key] = _("Cette vente ne doit plus rien à ce client.")
            elif amount <= 0:
                errors[key] = _("Le montant doit être supérieur à zéro.")
            elif taken.get(sale.pk, Decimal("0.000")) + amount > open_row.outstanding:
                errors[key] = _("%(number)s ne doit plus que %(due)s DT.") % {
                    "number": open_row.number,
                    "due": display_money(open_row.outstanding),
                }
            else:
                taken[sale.pk] = taken.get(sale.pk, Decimal("0.000")) + amount
                plan.append((sale.pk, amount))
        if not errors and sum((amount for _id, amount in plan), Decimal("0.000")) > available:
            errors["allocations"] = _("Les montants affectés dépassent le paiement (%(available)s DT disponibles).") % {
                "available": display_money(available)
            }
    if errors:
        raise ValidationError(errors)
    rows = PaymentAllocation.objects.bulk_create(
        [
            PaymentAllocation(organization=organization, payment=payment, sale_id=sale_id, amount=amount)
            for sale_id, amount in plan
        ]
    )
    for sale in Sale.objects.filter(pk__in=[sale_id for sale_id, _amount in plan]).select_related("organization"):
        refresh_sale_due(sale)
    return rows


def _plan_invoice(
    payment: CustomerPayment,
    invoice: Invoice,
    amount: Decimal,
    open_rows: Mapping[int, receivables.SaleReceivable],
    taken: dict[int, Decimal],
    plan: list[tuple[int, Decimal]],
    errors: dict[str, str],
    key: str,
) -> None:
    """Spread `amount` over the open BLs of `invoice`, oldest first (D-197); an error on `key` when the invoice
    is not the customer's or owes less."""
    rows = sorted(
        (row for row in open_rows.values() if row.invoice_id == invoice.pk),
        key=lambda row: (row.sold_at, row.sale_id),
    )
    left_by_row = [(row, row.outstanding - taken.get(row.sale_id, Decimal("0.000"))) for row in rows]
    due = sum((left for _row, left in left_by_row), Decimal("0.000"))
    if invoice.organization_id != payment.organization_id or invoice.customer_id != payment.customer_id or due <= 0:
        errors[key] = _("Cette facture ne doit plus rien à ce client.")
    elif amount <= 0:
        errors[key] = _("Le montant doit être supérieur à zéro.")
    elif amount > due:
        errors[key] = _("%(number)s ne doit plus que %(due)s DT.") % {
            "number": invoice.number,
            "due": display_money(due),
        }
    else:
        left = amount
        for row, row_left in left_by_row:
            if left <= 0:
                break
            part = min(left, row_left)
            if part <= 0:
                continue
            taken[row.sale_id] = taken.get(row.sale_id, Decimal("0.000")) + part
            plan.append((row.sale_id, part))
            left -= part


def _checked_payment_lines(
    organization: Organization,
    customer: "Customer",
    received_on: dt.date,
    lines: Sequence[PaymentLineFields],
    errors: dict[str, str],
) -> list[tuple[str, Decimal, PaymentLineFields]]:
    """The règlement's lines with their amount checked; errors on `lines.<index>.<field>`."""
    checked: list[tuple[str, Decimal, PaymentLineFields]] = []
    if not lines:
        errors["lines"] = _("Ajoutez au moins un moyen de paiement.")
        return checked
    if len(lines) > MAX_PAYMENT_LINES:
        errors["lines"] = _("%(count)s moyens de paiement au plus par règlement.") % {"count": MAX_PAYMENT_LINES}
        return checked
    taken: list[tuple[str, int | None, str]] = []
    for index, line in enumerate(lines):
        method = line.get("method", "")
        known = method in CustomerPaymentMethod.values and method != CustomerPaymentMethod.MIXED
        if not known:
            errors[line_error_key(index, "method")] = _("Mode de paiement inconnu.")
        try:
            value = checked_amount(line.get("amount", ""))
            if value <= 0:
                errors[line_error_key(index, "amount")] = _("Le montant doit être supérieur à zéro.")
        except (ValueError, TypeError):
            value = Decimal("0.000")
            errors[line_error_key(index, "amount")] = _("Indiquez un montant en DT, au millime près.")
        if not known:
            continue
        if method in INSTRUMENT_METHODS:
            bank = line.get("bank")
            number = line.get("number", "")
            found = treasury.instrument_errors(
                organization=organization,
                direction="received",
                kind=method,
                number=number,
                bank=bank,
                issued_on=received_on,
                due_on=line.get("due_on"),
                customer=customer,
                taken=taken,
            )
            for field, message in found.items():
                errors[line_error_key(index, field)] = message
            taken.append((method, bank.pk if bank else None, number.strip()))
        checked.append((method, value, line))
    return checked


def _header_reference(reference: str | None, checked: Sequence[tuple[str, Decimal, PaymentLineFields]]) -> str:
    """The règlement's own reference, shown in its list: the one typed, else that of its only line (a transfer
    reference, a cheque number); none for several lines, each keeping its own."""
    if reference is None:
        reference = ""
        if len(checked) == 1:
            line = checked[0][2]
            reference = line.get("number", "") if checked[0][0] in INSTRUMENT_METHODS else line.get("reference", "")
    return reference.strip()[:50]


@transaction.atomic
def record_customer_payment(
    *,
    organization: Organization,
    actor: User | None,
    customer: "Customer",
    amount: Number | None = None,
    method: str = "",
    lines: Sequence[PaymentLineFields] | None = None,
    received_on: dt.date | None = None,
    reference: str = "",
    notes: str = "",
    allocations: Sequence[AllocationFields] | None = None,
    client_uuid: uuid.UUID | None = None,
    made_at: dt.datetime | None = None,
) -> CustomerPayment:
    """Register a règlement received from a customer and allocate it (D-062, D-197).

    `lines` gives its means (some cash, cheques, traites...): each cheque or traite becomes an effet of the
    treasury, in portfolio. Without `lines`, `amount`, `method` and `reference` make its one line (the driver
    app, the older form); with `lines`, an `amount` given must equal their sum. A `client_uuid` already used
    returns that payment (the driver app retries).

    `allocations` None takes the customer's oldest open sales first; a list names the sales and amounts
    (empty keeps everything as credit). What is not allocated stays the customer's credit: their balance
    already counts the whole payment, and `allocate_customer_payment` can settle sales with it later.
    Refused for the walk-in customer (they pay on the spot). Numbered RG-0001... in the same transaction.
    """
    if client_uuid is not None:
        existing = CustomerPayment.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    errors: dict[str, str] = {}
    if customer.organization_id != organization.pk:
        errors["customer"] = _("Client inconnu.")
    elif customer.is_walk_in:
        errors["customer"] = _("Le client de passage paie sur place : pas de règlement ultérieur.")
    # Dated by the moment it was received (the phone's time, when there is one), else today.
    received_on = received_on or timezone.localtime(made_at or timezone.now()).date()
    if received_on > timezone.localdate():
        errors["received_on"] = _("Un règlement ne peut pas être daté dans le futur.")
    if lines is None:
        # One line made of the single fields; its errors stay on `amount` and `method`.
        single: dict[str, str] = {}
        one_line: PaymentLineFields = {
            "method": method,
            "amount": amount if amount is not None else "",
            "reference": reference,
        }
        checked = _checked_payment_lines(organization, customer, received_on, [one_line], single)
        for key, message in single.items():
            errors[key.removeprefix("lines.0.")] = message
    else:
        checked = _checked_payment_lines(organization, customer, received_on, lines, errors)
        if amount is not None and not errors:
            try:
                if checked_amount(amount) != sum((value for _method, value, _line in checked), Decimal("0.000")):
                    errors["amount"] = _("Le total ne correspond pas à la somme des moyens de paiement.")
            except (ValueError, TypeError):
                errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    if errors:
        raise ValidationError(errors)
    paid = sum((value for _method, value, _line in checked), Decimal("0.000"))
    methods = {line_method for line_method, _value, _line in checked}
    number = _next_number(organization, PAYMENT_SERIES)
    payment = CustomerPayment.objects.create(
        organization=organization,
        number=number,
        customer=customer,
        amount=paid,
        method=methods.pop() if len(methods) == 1 else CustomerPaymentMethod.MIXED,
        received_on=received_on,
        made_at=made_at,
        reference=_header_reference(reference if lines is None else None, checked),
        notes=notes.strip(),
        created_by=actor,
        client_uuid=client_uuid,
    )
    for line_method, value, line in checked:
        instrument = None
        if line_method in INSTRUMENT_METHODS:
            instrument = treasury.register_instrument(
                organization=organization,
                actor=actor,
                direction="received",
                kind=line_method,
                number=line.get("number", ""),
                bank=line.get("bank"),
                amount=value,
                issued_on=received_on,
                due_on=line.get("due_on"),
                drawer=line.get("drawer", "") or customer.name,
                customer=customer,
                source_number=number,
            )
        CustomerPaymentLine.objects.create(
            organization=organization,
            payment=payment,
            method=line_method,
            amount=value,
            reference=(line.get("reference", "") if instrument is None else "").strip()[:50],
            instrument=instrument,
        )
    _allocate(payment, paid, allocations)
    audit.record(
        organization=organization,
        actor=actor,
        action="customer_payment.recorded",
        target=payment,
        after=_payment_snapshot(payment),
    )
    return payment


def _locked_payment(payment: CustomerPayment) -> CustomerPayment:
    return (
        CustomerPayment.objects.select_for_update(of=("self",))
        .select_related("organization", "customer")
        .get(pk=payment.pk)
    )


@transaction.atomic
def allocate_customer_payment(
    *, payment: CustomerPayment, actor: User | None, allocations: Sequence[AllocationFields] | None = None
) -> CustomerPayment:
    """Settle sales with what is left of a payment (its credit): the named sales, or the oldest open ones
    with None. Rows already written never change."""
    payment = _locked_payment(payment)
    if payment.voided_at is not None:
        raise ValidationError(_("Ce règlement est annulé."))
    left = payment.amount - _unpaid_total(payment) - _allocated_total(payment)
    if left <= 0:
        raise ValidationError(_("Ce règlement est déjà entièrement affecté."))
    rows = _allocate(payment, left, allocations)
    audit.record(
        organization=payment.organization,
        actor=actor,
        action="customer_payment.allocated",
        target=payment,
        after={"rows": [{"sale": row.sale_id, "amount": str(row.amount)} for row in rows]},
    )
    return payment


@transaction.atomic
def void_customer_payment(*, payment: CustomerPayment, actor: User | None, reason: str) -> CustomerPayment:
    """Cancel a payment typed by mistake: it stays, marked voided with who, when and why; its allocations
    stop counting, the sales owe again and its cheques and traites are cancelled. Never deleted.

    Refused once one of its effets moved on (at the bank, cashed, unpaid...): the effet's own life handles it.
    """
    payment = _locked_payment(payment)
    if payment.voided_at is not None:
        raise ValidationError(_("Ce règlement est déjà annulé."))
    reason = reason.strip()[:255]
    if not reason:
        raise ValidationError({"reason": _("Indiquez la raison de l'annulation.")})
    instrument_ids = [pk for pk in payment.lines.values_list("instrument_id", flat=True) if pk is not None]
    if instrument_ids:
        treasury.cancel_instruments(
            instrument_ids=instrument_ids,
            actor=actor,
            happened_on=timezone.localdate(),
            note=_("Règlement %(number)s annulé : %(reason)s") % {"number": payment.number, "reason": reason},
        )
    sale_ids = list(payment.allocations.values_list("sale_id", flat=True))
    payment.voided_at = timezone.now()
    payment.voided_by = actor
    payment.void_reason = reason
    payment.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    for sale in Sale.objects.filter(pk__in=sale_ids).select_related("organization"):
        refresh_sale_due(sale)
    audit.record(
        organization=payment.organization,
        actor=actor,
        action="customer_payment.voided",
        target=payment,
        after={"reason": reason, "amount": str(payment.amount)},
    )
    return payment


def _certificate_content(upload: "UploadedFile[bytes]") -> tuple[ContentFile[bytes], str]:
    """A PDF kept as it is, or a photo turned upright and stored as WebP; with the file name."""
    head = upload.read(5)
    upload.seek(0)
    if head == b"%PDF-":
        if upload.size is not None and upload.size > MAX_CERTIFICATE_BYTES:
            raise ValidationError({"file": _("Le fichier dépasse 8 Mo.")})
        return ContentFile(upload.read()), "certificate.pdf"
    return reencoded_photo(upload, field="file"), "certificate.webp"


def _certificate_snapshot(certificate: WithholdingCertificate) -> dict[str, Any]:
    return {
        "invoice": certificate.invoice.number,
        "number": certificate.number,
        "issued_on": certificate.issued_on.isoformat(),
        "amount": str(certificate.amount),
        "has_file": bool(certificate.file.name),
    }


@transaction.atomic
def record_withholding_certificate(
    *,
    invoice: Invoice,
    actor: User | None,
    number: str,
    issued_on: dt.date,
    amount: Number,
    upload: "UploadedFile[bytes] | None" = None,
) -> WithholdingCertificate:
    """Record what a customer withheld on an issued invoice, with the certificate they gave (D-063).

    The amount replaces the withholding the invoice planned: the sale's receivable becomes the invoice's
    total with VAT and stamp, less credit notes, less this amount. One live certificate per invoice (void
    it to type another). The file (photo or PDF) may come later (`add_certificate_file`).
    """
    invoice = _locked_invoice(invoice)
    errors: dict[str, str] = {}
    if invoice.status != InvoiceStatus.ISSUED:
        raise ValidationError(_("Seule une facture émise reçoit une retenue à la source."))
    number = number.strip()
    if not number:
        errors["number"] = _("Indiquez le numéro du certificat.")
    elif len(number) > 50:
        errors["number"] = _("Au plus 50 caractères.")
    if issued_on > timezone.localdate():
        errors["issued_on"] = _("Le certificat ne peut pas être daté dans le futur.")
    try:
        withheld = checked_amount(amount)
        if withheld <= 0:
            errors["amount"] = _("Le montant doit être supérieur à zéro.")
        elif withheld > invoice.total_incl_tax:
            errors["amount"] = _("La retenue dépasse le total de la facture (%(total)s DT).") % {
                "total": display_money(invoice.total_incl_tax)
            }
    except (ValueError, TypeError):
        withheld = Decimal("0.000")
        errors["amount"] = _("Indiquez un montant en DT, au millime près.")
    if invoice.certificates.filter(voided_at__isnull=True).exists():
        errors["number"] = _("Cette facture a déjà un certificat : annulez-le avant d'en saisir un autre.")
    content: tuple[ContentFile[bytes], str] | None = None
    if upload is not None:
        try:
            content = _certificate_content(upload)
        except ValidationError as error:
            errors.update({field: messages[0] for field, messages in error.message_dict.items()})
    if errors:
        raise ValidationError(errors)
    certificate = WithholdingCertificate(
        organization=invoice.organization,
        invoice=invoice,
        number=number,
        issued_on=issued_on,
        amount=withheld,
        created_by=actor,
    )
    if content is not None:
        certificate.file.save(content[1], content[0], save=False)
    try:
        certificate.save()
    except BaseException:
        if certificate.file.name:
            certificate.file.storage.delete(certificate.file.name)
        raise
    refresh_invoice_sales(invoice)
    audit.record(
        organization=invoice.organization,
        actor=actor,
        action="withholding_certificate.recorded",
        target=certificate,
        after=_certificate_snapshot(certificate),
    )
    return certificate


@transaction.atomic
def add_certificate_file(
    *, certificate: WithholdingCertificate, actor: User | None, upload: "UploadedFile[bytes]"
) -> WithholdingCertificate:
    """Join (or replace) the file of a live certificate: a photo or a PDF."""
    content, name = _certificate_content(upload)
    certificate = (
        WithholdingCertificate.objects.select_for_update(of=("self",))
        .select_related("organization", "invoice")
        .get(pk=certificate.pk)
    )
    if certificate.voided_at is not None:
        raise ValidationError(_("Ce certificat est annulé."))
    previous = certificate.file.name
    storage = certificate.file.storage
    certificate.file.save(name, content, save=False)
    try:
        certificate.save(update_fields=["file", "updated_at"])
    except BaseException:
        storage.delete(certificate.file.name or "")
        raise
    if previous:
        transaction.on_commit(lambda: storage.delete(previous))
    audit.record(
        organization=certificate.organization,
        actor=actor,
        action="withholding_certificate.file_added",
        target=certificate,
    )
    return certificate


@transaction.atomic
def void_withholding_certificate(
    *, certificate: WithholdingCertificate, actor: User | None, reason: str
) -> WithholdingCertificate:
    """Cancel a certificate typed by mistake: it stays, marked voided; the invoice's own planned withholding
    counts again."""
    certificate = (
        WithholdingCertificate.objects.select_for_update(of=("self",))
        .select_related("organization", "invoice")
        .get(pk=certificate.pk)
    )
    if certificate.voided_at is not None:
        raise ValidationError(_("Ce certificat est déjà annulé."))
    reason = reason.strip()[:255]
    if not reason:
        raise ValidationError({"reason": _("Indiquez la raison de l'annulation.")})
    certificate.voided_at = timezone.now()
    certificate.voided_by = actor
    certificate.void_reason = reason
    certificate.save(update_fields=["voided_at", "voided_by", "void_reason", "updated_at"])
    refresh_invoice_sales(certificate.invoice)
    audit.record(
        organization=certificate.organization,
        actor=actor,
        action="withholding_certificate.voided",
        target=certificate,
        after={"reason": reason, **_certificate_snapshot(certificate)},
    )
    return certificate


# ---- Impayés: a customer effet the bank refused (P9-T04b, D-217) ----

# The expense category of the bank's charges (expenses.DEFAULT_CATEGORIES).
BANK_CHARGES_CATEGORY = "financial"


@transaction.atomic
def record_unpaid_effet(
    *,
    organization: Organization,
    actor: User | None,
    instrument_id: int,
    unpaid_on: dt.date | None,
    reason: str,
    bank_charges: Number = "0",
) -> UnpaidEffet:
    """The bank refused a customer's cheque or traite: the customer owes its amount again (D-217).

    A new record, the règlement untouched: `UnpaidEffet` adds the amount back to the balance; what the règlement
    had settled on sales beyond its credit left is taken back, newest allocation first (`UnpaidRelease`), so those
    sales owe again. The effet becomes "Impayé" in the treasury; the bank's charges are an approved expense
    "Frais financiers"; the office is told.
    """
    errors: dict[str, str] = {}
    reason = " ".join(reason.split())[:255]
    if not reason:
        errors["reason"] = _("Indiquez le motif du rejet (sans provision, signature...).")
    try:
        charges = checked_amount(bank_charges or "0")
        if charges < 0:
            errors["bank_charges"] = _("Les frais ne peuvent pas être négatifs.")
    except (ValueError, TypeError):
        charges = Decimal("0.000")
        errors["bank_charges"] = _("Indiquez un montant en DT, au millime près.")
    line = (
        CustomerPaymentLine.objects.select_related("payment", "payment__customer", "instrument")
        .filter(organization=organization, instrument_id=instrument_id)
        .first()
    )
    if line is None:
        errors["instrument"] = _("Cet effet n'est pas celui d'un règlement client.")
    if errors:
        raise ValidationError(errors)
    assert line is not None
    payment = _locked_payment(line.payment)
    if payment.voided_at is not None:
        raise ValidationError({"instrument": _("Ce règlement est annulé.")})
    treasury.mark_unpaid(
        organization=organization, actor=actor, instrument_id=instrument_id, unpaid_on=unpaid_on, note=reason
    )
    assert unpaid_on is not None  # checked by the treasury
    free = payment.amount - _unpaid_total(payment) - _allocated_total(payment)
    to_release = max(line.amount - max(free, Decimal("0.000")), Decimal("0.000"))
    unpaid = UnpaidEffet.objects.create(
        organization=organization,
        payment=payment,
        line=line,
        customer=payment.customer,
        amount=line.amount,
        unpaid_on=unpaid_on,
        reason=reason,
        bank_charges=charges,
        created_by=actor,
    )
    # Each sale's part still settled by this règlement, the newest allocation first.
    net: dict[int, Decimal] = {}
    for allocation in payment.allocations.order_by("-id"):
        net[allocation.sale_id] = net.get(allocation.sale_id, Decimal("0.000")) + allocation.amount
    for row in UnpaidRelease.objects.filter(unpaid__payment=payment).values("sale_id").annotate(total=Sum("amount")):
        net[row["sale_id"]] = net.get(row["sale_id"], Decimal("0.000")) - row["total"]
    released: dict[int, Decimal] = {}
    for sale_id, settled in net.items():
        if to_release <= 0:
            break
        part = min(settled, to_release)
        if part <= 0:
            continue
        UnpaidRelease.objects.create(organization=organization, unpaid=unpaid, sale_id=sale_id, amount=part)
        released[sale_id] = part
        to_release -= part
    touched = list(released)
    for sale in Sale.objects.filter(pk__in=touched).select_related("organization").order_by("id"):
        refresh_sale_due(sale)
    if charges > 0:
        expense = expenses.create_expense(
            organization=organization,
            actor=actor,
            spent_on=unpaid_on,
            category=expenses_selectors.category_by_code(organization, BANK_CHARGES_CATEGORY),
            amount=charges,
            payment_method="transfer",
            description=_("Frais d'impayé %(effet)s (%(number)s)")
            % {"effet": line.instrument or "", "number": payment.number},
            payee=line.instrument.bank.code if line.instrument and line.instrument.bank else "",
            approve=True,
        )
        unpaid.expense_number = expense.number
        unpaid.save(update_fields=["expense_number"])
    notifications.tell_office_of(
        organization=organization,
        actor=actor,
        kind="effet_unpaid",
        params={
            "customer": payment.customer.name,
            "number": line.instrument.number if line.instrument else "",
            "amount": str(line.amount),
        },
        link=f"/reglements/{payment.pk}",
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="customer_payment.unpaid",
        target=payment,
        after={
            "effet": str(line.instrument),
            "amount": str(line.amount),
            "reason": reason,
            "bank_charges": str(charges),
            "released": {str(sale_id): str(amount) for sale_id, amount in released.items()},
        },
    )
    return unpaid
