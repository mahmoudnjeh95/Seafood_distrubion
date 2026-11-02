"""Every write on stock locations, batches and stock movements goes through these functions (ARCHITECTURE §3)."""

import datetime as dt
import itertools
import uuid
from collections.abc import Mapping, Sequence
from decimal import Decimal
from typing import TYPE_CHECKING, Any, TypedDict

from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import connection, models, transaction
from django.dispatch import Signal
from django.utils import timezone
from django.utils.translation import gettext as _

from apps.boxes import services as box_services
from apps.catalog import selectors as catalog
from apps.core import audit, numbering
from apps.core.images import reencoded_photo
from apps.core.models import Organization, User
from apps.core.money import Number, checked_amount, checked_quantity

from . import selectors
from .models import (
    FIFO_ORDER,
    Batch,
    CountStatus,
    LossStatus,
    StockCount,
    StockCountLine,
    StockLocation,
    StockLoss,
    StockMovement,
    StockOnHand,
    StockSettings,
    Transfer,
    TransferBoxLine,
    TransferDelivery,
    TransferKind,
    TransferLine,
    TransferLinePick,
    TransferStatus,
)
from .models import LocationKind as LocationKind  # re-exported for apps that create locations
from .models import LossReason as LossReason  # re-exported for apps that record losses
from .models import MovementKind as MovementKind  # re-exported for apps that post movements

if TYPE_CHECKING:
    from django.core.files.uploadedfile import UploadedFile

    from apps.catalog.models import Product
    from apps.partners.models import Customer, Supplier


def _snapshot(location: StockLocation) -> dict[str, Any]:
    return {"kind": location.kind, "name": location.name, "counter_sales": location.counter_sales}


def _clean_location(location: StockLocation) -> None:
    errors: dict[str, str] = {}
    location.name = location.name.strip()
    if location.kind not in LocationKind.values:
        errors["kind"] = _("Type d'emplacement inconnu.")
    if not location.name:
        errors["name"] = _("Le nom est obligatoire.")
    elif (
        StockLocation.objects.for_organization(location.organization)
        .filter(name__iexact=location.name)
        .exclude(pk=location.pk)
        .exists()
    ):
        errors["name"] = _("Un autre emplacement porte déjà ce nom.")
    if location.kind == LocationKind.TRUCK:
        # A truck always sells; the flag only means something for the other kinds.
        location.counter_sales = False
    if errors:
        raise ValidationError(errors)


@transaction.atomic
def create_location(
    *, organization: Organization, actor: User | None, kind: str, name: str, counter_sales: bool = False
) -> StockLocation:
    """A new cold room or other location. A truck's location is made by `fleet.services.create_truck`."""
    location = StockLocation(organization=organization, kind=kind, name=name, counter_sales=counter_sales)
    _clean_location(location)
    location.save()
    audit.record(
        organization=organization, actor=actor, action="location.created", target=location, after=_snapshot(location)
    )
    return location


OPENING_LOCATION_NAME = "Solde d'ouverture"


@transaction.atomic
def opening_balance_location(*, organization: Organization, actor: User | None) -> StockLocation:
    """The archived, empty "place" that opening customer debts hang on (a sale needs one). It holds no stock, takes
    none and never shows in pickers: created and archived the first time it is asked for."""
    found = StockLocation.objects.for_organization(organization).filter(name__iexact=OPENING_LOCATION_NAME).first()
    if found is not None:
        return found
    location = create_location(
        organization=organization, actor=actor, kind=LocationKind.OTHER, name=OPENING_LOCATION_NAME
    )
    return set_location_active(location=location, actor=actor, is_active=False)


@transaction.atomic
def update_location(
    *, location: StockLocation, actor: User | None, name: str | None = None, counter_sales: bool | None = None
) -> StockLocation:
    """Rename a location or change whether it sells at the counter. Its kind never changes."""
    location = StockLocation.objects.select_for_update().get(pk=location.pk)
    before = _snapshot(location)
    if name is not None:
        location.name = name
    if counter_sales is not None:
        location.counter_sales = counter_sales
    _clean_location(location)
    location.save()
    after = _snapshot(location)
    changed = [field for field in after if after[field] != before[field]]
    if changed:
        audit.record(
            organization=location.organization,
            actor=actor,
            action="location.updated",
            target=location,
            before={field: before[field] for field in changed},
            after={field: after[field] for field in changed},
        )
    return location


@transaction.atomic
def set_location_active(*, location: StockLocation, actor: User | None, is_active: bool) -> StockLocation:
    """Archive a location (it keeps its history but receives no more stock), or bring it back.

    A location still holding stock cannot be archived: its stock is moved out first.
    """
    location = StockLocation.objects.select_for_update().get(pk=location.pk)
    if not is_active and StockOnHand.objects.filter(location=location, quantity__gt=0).exists():
        raise ValidationError(
            _("« %(name)s » contient encore du stock : videz-le avant de l'archiver.") % {"name": location.name}
        )
    if location.is_active != is_active:
        location.is_active = is_active
        location.save(update_fields=["is_active", "updated_at"])
        action = "location.restored" if is_active else "location.archived"
        audit.record(organization=location.organization, actor=actor, action=action, target=location)
    return location


def _batch_snapshot(batch: Batch) -> dict[str, Any]:
    return {
        "number": batch.number,
        "product": batch.product.reference,
        "supplier": batch.supplier.reference,
        "receipt_reference": batch.receipt_reference,
        "received_on": batch.received_on.isoformat(),
        "unit_cost": str(batch.unit_cost),
        "use_by": batch.use_by.isoformat() if batch.use_by else None,
    }


@transaction.atomic
def create_batch(
    *,
    organization: Organization,
    actor: User | None,
    product: "Product",
    supplier: "Supplier",
    received_on: dt.date,
    unit_cost: Number,
    receipt_reference: str = "",
    use_by: dt.date | None = None,
    bought_with_vat: bool = False,
) -> Batch:
    """A new batch with the next number. Called by the goods receipt (P1-T07) and the demo data.

    Refused (ValidationError per field): a product or supplier of another organization or archived, a
    receipt date in the future, a cost that is negative or finer than a millime, a use-by date before
    the receipt date.
    """
    errors: dict[str, str] = {}
    if product.organization_id != organization.pk:
        errors["product"] = _("Produit inconnu.")
    elif not product.is_active:
        errors["product"] = _("Ce produit est archivé.")
    if supplier.organization_id != organization.pk:
        errors["supplier"] = _("Fournisseur inconnu.")
    elif not supplier.is_active:
        errors["supplier"] = _("Ce fournisseur est archivé.")
    if received_on > timezone.localdate():
        errors["received_on"] = _("La date de réception ne peut pas être dans le futur.")
    if use_by is not None and use_by < received_on:
        errors["use_by"] = _("La date limite ne peut pas précéder la réception.")
    cost = None
    try:
        cost = checked_amount(unit_cost)
    except ValueError as error:
        errors["unit_cost"] = str(error)
    if errors or cost is None:
        raise ValidationError(errors)

    batch = Batch.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "batch"),
        product=product,
        supplier=supplier,
        receipt_reference=receipt_reference.strip(),
        received_on=received_on,
        unit_cost=cost,
        use_by=use_by,
        bought_with_vat=bought_with_vat,
    )
    audit.record(
        organization=organization, actor=actor, action="batch.created", target=batch, after=_batch_snapshot(batch)
    )
    return batch


# Which side each kind of movement needs: (from a location, to a location). None: exactly one of the two,
# the side giving the direction (an adjustment or a count correction adds or removes).
MOVEMENT_SIDES: dict[str, tuple[bool, bool] | None] = {
    MovementKind.RECEIPT: (False, True),
    MovementKind.CUSTOMER_RETURN: (False, True),
    MovementKind.SALE: (True, False),
    MovementKind.SUPPLIER_RETURN: (True, False),
    MovementKind.LOSS: (True, False),
    MovementKind.TRANSFER: (True, True),
    MovementKind.ADJUSTMENT: None,
    MovementKind.COUNT_CORRECTION: None,
}
# A person must say why stock disappeared or was changed by hand.
KINDS_NEEDING_A_REASON = frozenset({MovementKind.LOSS, MovementKind.ADJUSTMENT})


def _locked_on_hand(location: StockLocation, batch: Batch) -> StockOnHand:
    """The on-hand row of this location and batch, created at zero when missing, locked until commit."""
    StockOnHand.objects.bulk_create(
        [
            StockOnHand(
                organization_id=location.organization_id, location=location, batch=batch, product_id=batch.product_id
            )
        ],
        ignore_conflicts=True,
    )
    return StockOnHand.objects.select_for_update().get(location=location, batch=batch)


def _movement_errors(
    organization: Organization,
    kind: str,
    batch: Batch,
    from_location: StockLocation | None,
    to_location: StockLocation | None,
    reason: str,
) -> dict[str, str]:
    if kind not in MOVEMENT_SIDES:
        return {"kind": _("Type de mouvement inconnu.")}
    errors: dict[str, str] = {}
    if batch.organization_id != organization.pk:
        errors["batch"] = _("Lot inconnu.")
    sides = MOVEMENT_SIDES[kind]
    if sides is None:
        if (from_location is None) == (to_location is None):
            errors["to_location"] = _("Indiquez un seul emplacement : celui qui gagne ou celui qui perd du stock.")
    else:
        needs_from, needs_to = sides
        for field, location, needed in (
            ("from_location", from_location, needs_from),
            ("to_location", to_location, needs_to),
        ):
            if needed and location is None:
                errors[field] = _("L'emplacement est obligatoire pour ce mouvement.")
            elif not needed and location is not None:
                errors[field] = _("Ce mouvement ne passe pas par cet emplacement.")
    if from_location is not None and from_location == to_location:
        errors["to_location"] = _("Les emplacements de départ et d'arrivée doivent être différents.")
    for field, location in (("from_location", from_location), ("to_location", to_location)):
        if location is None or field in errors:
            continue
        if location.organization_id != organization.pk:
            errors[field] = _("Emplacement inconnu.")
        elif not location.is_active:
            errors[field] = _("« %(name)s » est archivé.") % {"name": location.name}
    if kind in KINDS_NEEDING_A_REASON and not reason:
        errors["reason"] = _("Indiquez la raison.")
    return errors


@transaction.atomic
def post_movement(
    *,
    organization: Organization,
    actor: User | None,
    kind: str,
    batch: Batch,
    quantity: Number,
    from_location: StockLocation | None = None,
    to_location: StockLocation | None = None,
    reason: str = "",
    source: models.Model | None = None,
    client_uuid: uuid.UUID | None = None,
    occurred_at: dt.datetime | None = None,
) -> StockMovement:
    """Post one movement of one batch and update the stock on hand in the same transaction (D-006).

    The on-hand rows involved are locked, always in the same order so two movements never wait for each
    other forever; a location never goes below zero. A `client_uuid` already posted returns that movement
    instead of posting it twice. Refused with a ValidationError per field.
    """
    if client_uuid is not None:
        posted = StockMovement.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if posted is not None:
            return posted

    reason = reason.strip()
    errors = _movement_errors(organization, kind, batch, from_location, to_location, reason)
    amount = None
    try:
        amount = checked_quantity(quantity)
    except ValueError as error:
        errors["quantity"] = str(error)
    if errors or amount is None:
        raise ValidationError(errors)

    involved = sorted((loc for loc in (from_location, to_location) if loc is not None), key=lambda loc: loc.pk)
    rows = {location.pk: _locked_on_hand(location, batch) for location in involved}
    if from_location is not None:
        source_row = rows[from_location.pk]
        if source_row.quantity < amount:
            raise ValidationError(
                {
                    "quantity": _("Stock insuffisant : %(available)s kg du lot %(batch)s à « %(location)s ».")
                    % {"available": source_row.quantity, "batch": batch.number, "location": from_location.name}
                }
            )
        source_row.quantity -= amount
        source_row.save(update_fields=["quantity", "updated_at"])
    if to_location is not None:
        target_row = rows[to_location.pk]
        target_row.quantity += amount
        target_row.save(update_fields=["quantity", "updated_at"])

    return StockMovement.objects.create(
        organization=organization,
        kind=kind,
        product_id=batch.product_id,
        batch=batch,
        from_location=from_location,
        to_location=to_location,
        quantity=amount,
        unit_cost=batch.unit_cost,
        source_type=ContentType.objects.get_for_model(source) if source is not None else None,
        source_id=source.pk if source is not None else None,
        user=actor,
        occurred_at=occurred_at or timezone.now(),
        reason=reason,
        client_uuid=client_uuid,
    )


def _part_uuid(client_uuid: uuid.UUID, index: int) -> uuid.UUID:
    """The `client_uuid` of the n-th movement posted for one request taken from several batches."""
    return uuid.uuid5(client_uuid, str(index))


def _posted_parts(organization: Organization, client_uuid: uuid.UUID) -> list[StockMovement]:
    movements = StockMovement.objects.for_organization(organization)
    posted: list[StockMovement] = []
    for index in itertools.count():
        movement = movements.filter(client_uuid=_part_uuid(client_uuid, index)).first()
        if movement is None:
            return posted
        posted.append(movement)
    return posted  # pragma: no cover - itertools.count never ends


@transaction.atomic
def post_fifo_movements(
    *,
    organization: Organization,
    actor: User | None,
    kind: str,
    product_id: int,
    quantity: Number,
    from_location: StockLocation,
    to_location: StockLocation | None = None,
    reason: str = "",
    source: models.Model | None = None,
    client_uuid: uuid.UUID | None = None,
    occurred_at: dt.datetime | None = None,
    picks: Sequence[tuple[int, Decimal]] = (),
    held_since_then: bool = False,
) -> list[StockMovement]:
    """Take `quantity` kg of a product out of `from_location`, oldest batch first, one movement per batch.

    Used by transfers, sales and losses: nobody picks batches by hand (D-009) — except a sale line may ask
    to take kilos from lots first (`picks`, `[(batch id, kg)]`, D-121, D-208): each picked lot gives the kilos
    picked from it, and the rest still comes from the other lots, oldest first, same as always (never below
    zero, a short lot topped up the same way). Every on-hand row of the product at both locations is locked
    first, in location then batch order, the same order as `post_movement`, so two requests never wait for each
    other forever.
    Refused as a whole (ValidationError per field) when the location holds less than asked in total. A
    `client_uuid` already used returns the movements it posted.

    With `held_since_then` and an `occurred_at` on an earlier day (a driver's sale that reached the server
    after its day, D-133), a lot gives at most what the location has held of it at the end of every day since
    (`selectors.least_held_since`): the movement is dated on its own day, so the kilos must have been there
    that day and must not have left since, or a day in between would start below zero.
    """
    if client_uuid is not None:
        posted = _posted_parts(organization, client_uuid)
        if posted:
            return posted
    sides = MOVEMENT_SIDES.get(kind)
    if sides is not None and not sides[0]:
        raise ValidationError({"kind": _("Ce mouvement ne prend pas de stock à un emplacement.")})
    if from_location.organization_id != organization.pk:
        raise ValidationError({"from_location": _("Emplacement inconnu.")})
    try:
        amount = checked_quantity(quantity)
    except ValueError as error:
        raise ValidationError({"quantity": str(error)}) from None

    locations = [location for location in (from_location, to_location) if location is not None]
    locked = (
        StockOnHand.objects.select_for_update(of=("self",))
        .filter(product_id=product_id, location__in=locations)
        .select_related("batch")
        .order_by("location_id", "batch_id")
    )
    # A document typed for an earlier day cannot take a batch that arrived after it (D-106).
    day = timezone.localtime(occurred_at).date() if occurred_at is not None else timezone.localdate()
    holdings = sorted(
        (
            row
            for row in locked
            if row.location_id == from_location.pk and row.quantity > 0 and row.batch.received_on <= day
        ),
        key=lambda row: tuple(getattr(row.batch, field) for field in FIFO_ORDER),
    )
    limits = None
    if held_since_then and day < timezone.localdate():
        limits = selectors.least_held_since(organization, location_id=from_location.pk, product_id=product_id, day=day)
    allocations = selectors.picked_split(holdings, amount, picks, limits)
    if sum((taken for _batch, taken in allocations), Decimal(0)) < amount:
        available = sum((selectors.takeable(row, limits) for row in holdings), Decimal("0.000"))
        if limits is not None:
            raise selectors.not_enough_stock_since(available, from_location, day)
        raise selectors.not_enough_stock(available, from_location)

    return [
        post_movement(
            organization=organization,
            actor=actor,
            kind=kind,
            batch=batch,
            quantity=taken,
            from_location=from_location,
            to_location=to_location,
            reason=reason,
            source=source,
            client_uuid=_part_uuid(client_uuid, index) if client_uuid is not None else None,
            occurred_at=occurred_at,
        )
        for index, (batch, taken) in enumerate(allocations)
    ]


@transaction.atomic
def rebuild_on_hand(*, organization: Organization, actor: User | None) -> list[selectors.OnHandDifference]:
    """Set the stock on hand of every location and batch back to the sum of its movements (D-038).

    The ledger is the truth; the cache only speeds up reading it. Returns what was wrong, empty when
    nothing was. Writes are blocked on the cache (of every organization) for the few milliseconds this
    takes: `post_movement` updates the cache before it writes its movement, so a movement either finished
    before the rebuild or starts after it, never in the middle. Reads are not blocked.
    """
    with connection.cursor() as cursor:
        cursor.execute(f"LOCK TABLE {StockOnHand._meta.db_table} IN EXCLUSIVE MODE")
    differences = selectors.on_hand_differences(organization)
    if not differences:
        return []
    negative = [difference for difference in differences if difference.ledger < 0]
    if negative:
        # Movements are checked before posting, so this cannot happen without editing the database by hand.
        raise ValidationError(
            _("Le journal donne un stock négatif pour %(count)s ligne(s) : réparation impossible, à examiner.")
            % {"count": len(negative)}
        )
    for difference in differences:
        row, _created = StockOnHand.objects.get_or_create(
            location_id=difference.location_id,
            batch_id=difference.batch_id,
            defaults={"organization": organization, "product_id": difference.product_id},
        )
        row.quantity = difference.ledger
        row.save(update_fields=["quantity", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="stock.on_hand_rebuilt",
        before={"rows": [_difference_entry(difference, difference.cached) for difference in differences]},
        after={"rows": [_difference_entry(difference, difference.ledger) for difference in differences]},
    )
    return differences


def _difference_entry(difference: selectors.OnHandDifference, quantity: Decimal) -> dict[str, Any]:
    return {"location": difference.location_id, "batch": difference.batch_id, "quantity": quantity}


# ---- Transfers between locations (P1-T09, D-044) ----

# Sent when a load into a truck is validated, inside the same transaction, with `transfer` and `actor`. Apps
# that depend on inventory react to it there (the driver's sent day opens again, D-134); a receiver that
# raises refuses the validation.
load_validated = Signal()


class LotPickFields(TypedDict):
    """A lot picked by hand for a line, and the kilos to take from it first (D-212, D-215)."""

    batch: "Batch"
    quantity: Number


class TransferLineFields(TypedDict, total=False):
    product: "Product"
    quantity: Number
    # DT per kg, on a truck load only; empty takes the sale price in force.
    unit_price: Number | None
    # Lots picked by hand instead of FIFO (D-215); empty takes the oldest lot first.
    picks: Sequence[LotPickFields]


class TransferDeliveryFields(TypedDict, total=False):
    """The part of a truck load that is for one client (D-160): their kg and boxes, and where it is delivered."""

    customer: "Customer"
    # Empty takes the client's own address; a typed one is for this load's BL only.
    delivery_address: str
    lines: Sequence[TransferLineFields]
    boxes: Mapping[str, int] | None


def line_error_key(index: int, field: str) -> str:
    """Errors of a document line are reported on `lines.<index>.<field>`, under the line's own input."""
    return f"lines.{index}.{field}"


def checked_lot_picks(
    organization: Organization,
    product: "Product | None",
    picks: Sequence[LotPickFields],
    quantity: Decimal | None,
    errors: dict[str, str],
    key: str,
) -> list[tuple["Batch", Decimal]]:
    """Check the lots picked by hand on one line (D-212, D-215): of that organization and the line's product, each
    lot once, with kilos above zero, and together no more kilos than the line asks (`quantity`, None when the
    line's weight is itself wrong). A problem is reported on `key`, the line's own field."""
    checked: list[tuple[Batch, Decimal]] = []
    for pick in picks:
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
        elif any(batch.pk == picked.pk for picked, _kg in checked):
            errors.setdefault(key, _("Un lot ne peut être choisi qu'une fois par ligne."))
        else:
            checked.append((batch, kg))
    if quantity is not None and sum((kg for _batch, kg in checked), Decimal("0")) > quantity:
        errors.setdefault(key, _("Les lots choisis dépassent le poids de la ligne."))
    return checked


def transfer_kind(from_location: StockLocation, to_location: StockLocation) -> str:
    """A load goes into a truck, a return comes out of one; anything else moves between two places."""
    from_truck = from_location.kind == LocationKind.TRUCK
    to_truck = to_location.kind == LocationKind.TRUCK
    if to_truck and not from_truck:
        return TransferKind.LOAD
    if from_truck and not to_truck:
        return TransferKind.RETURN
    return TransferKind.INTERNAL


def moment_of(day: dt.date) -> dt.datetime:
    """When a document of `day` happened: now when it is today, noon of that day otherwise.

    Noon keeps the ledger in date order for a day typed afterwards, as goods receipts do (D-039).
    """
    if day == timezone.localdate():
        return timezone.now()
    return timezone.make_aware(dt.datetime.combine(day, dt.time(12, 0)))


def _transfer_header_errors(
    organization: Organization,
    from_location: StockLocation,
    to_location: StockLocation,
    from_cold_rooms: bool = False,
) -> dict[str, str]:
    errors: dict[str, str] = {}
    if from_cold_rooms and (from_location.kind != LocationKind.COLD_ROOM or to_location.kind != LocationKind.TRUCK):
        errors["from_location"] = _("Seul un chargement de camion part des chambres froides ensemble.")
    for field, location in (("from_location", from_location), ("to_location", to_location)):
        if location.organization_id != organization.pk:
            errors[field] = _("Emplacement inconnu.")
        elif not location.is_active:
            errors[field] = _("« %(name)s » est archivé.") % {"name": location.name}
    if not errors and from_location.pk == to_location.pk:
        errors["to_location"] = _("Les emplacements de départ et d'arrivée doivent être différents.")
    return errors


def _checked_load_price(product: "Product | None", price: Any, at: dt.datetime) -> Decimal | str:
    """The price per kg of a load line, or the message saying why there is none.

    Empty takes the sale price in force at `at` (`catalog.ProductPrice`); a typed price is checked.
    """
    if price in (None, ""):
        in_force = catalog.price_at(product, at) if product is not None else None
        if in_force is None:
            return _("Aucun prix de vente en vigueur : indiquez le prix du jour.")
        return in_force.price
    try:
        amount = checked_amount(price)
    except (ValueError, TypeError):
        amount = None
    if amount is None or amount <= 0:
        return _("Indiquez un prix en DT par kg, supérieur à zéro, au millime près.")
    return amount


def _checked_transfer_lines(
    organization: Organization,
    kind: str,
    lines: Sequence[TransferLineFields],
    at: dt.datetime,
    errors: dict[str, str],
    prefix: str = "",
    from_cold_rooms: bool = False,
) -> list[dict[str, Any]]:
    """The lines' values once checked; each problem is added to `errors` under the line's own keys
    (`prefix` puts them under a client's part of a load: `deliveries.<i>.`).

    Only a load carries a price per kg (the driver sells at it); the other kinds keep none. Lots picked by hand
    need one place to take them from, so a load from several cold rooms (D-174) takes none.
    """

    def key(index: int, field: str) -> str:
        return prefix + line_error_key(index, field)

    checked_lines: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, line in enumerate(lines):
        product = line.get("product")
        checked: dict[str, Any] = {"product": product, "quantity": None, "unit_price": None}
        if product is None or product.organization_id != organization.pk:
            errors[key(index, "product")] = _("Produit inconnu.")
        elif not product.is_active:
            errors[key(index, "product")] = _("Ce produit est archivé.")
        elif product.pk in seen:
            errors[key(index, "product")] = _("Ce produit est déjà sur une autre ligne.")
        else:
            seen.add(product.pk)
        try:
            value: Any = line.get("quantity", "")
            checked["quantity"] = checked_quantity(value)
        except (ValueError, TypeError):
            errors[key(index, "quantity")] = _("Indiquez un poids en kg, supérieur à zéro.")
        if kind == TransferKind.LOAD and key(index, "product") not in errors:
            price = _checked_load_price(product, line.get("unit_price"), at)
            if isinstance(price, Decimal):
                checked["unit_price"] = price
            else:
                errors[key(index, "unit_price")] = price
        picks = line.get("picks") or []
        if picks and from_cold_rooms:
            errors[key(index, "picks")] = _("Les lots se choisissent depuis une seule chambre froide.")
            picks = []
        checked["picks"] = checked_lot_picks(
            organization, product, picks, checked["quantity"], errors, key(index, "picks")
        )
        checked_lines.append(checked)
    return checked_lines


def _transfer_snapshot(transfer: Transfer) -> dict[str, Any]:
    return {
        "number": transfer.number,
        "kind": transfer.kind,
        "status": transfer.status,
        "from_location": transfer.from_location.name,
        "to_location": transfer.to_location.name,
        "from_cold_rooms": transfer.from_cold_rooms,
        "transferred_on": transfer.transferred_on.isoformat(),
        "lines": [
            {
                "product": line.product.reference,
                "quantity": str(line.quantity),
                "unit_price": str(line.unit_price) if line.unit_price is not None else None,
                "customer": line.customer.reference if line.customer is not None else None,
            }
            for line in transfer.lines.select_related("product", "customer").order_by("id")
        ],
        "deliveries": [
            {"customer": delivery.customer.reference, "delivery_address": delivery.delivery_address}
            for delivery in transfer.deliveries.select_related("customer").order_by("id")
        ],
    }


def _write_transfer_lines(
    transfer: Transfer, checked_lines: list[dict[str, Any]], customer: "Customer | None" = None
) -> None:
    new_lines = [
        TransferLine(
            organization_id=transfer.organization_id,
            transfer=transfer,
            customer=customer,
            product=values["product"],
            quantity=values["quantity"],
            unit_price=values["unit_price"],
        )
        for values in checked_lines
    ]
    TransferLine.objects.bulk_create(new_lines)
    TransferLinePick.objects.bulk_create(
        [
            TransferLinePick(organization_id=transfer.organization_id, line=line, batch=batch, quantity=kg)
            for line, values in zip(new_lines, checked_lines, strict=True)
            for batch, kg in values["picks"]
        ]
    )


def _checked_deliveries(
    organization: Organization,
    kind: str,
    deliveries: Sequence[TransferDeliveryFields],
    at: dt.datetime,
    errors: dict[str, str],
    from_cold_rooms: bool = False,
) -> list[dict[str, Any]]:
    """The client parts of a load, checked: a known active client once, at least one product, boxes."""
    if deliveries and kind != TransferKind.LOAD:
        errors["deliveries"] = _("Seul un chargement de camion se prépare par client.")
        return []
    checked: list[dict[str, Any]] = []
    seen: set[int] = set()
    for index, delivery in enumerate(deliveries):
        prefix = f"deliveries.{index}."
        customer = delivery.get("customer")
        if customer is None or customer.organization_id != organization.pk:
            errors[f"{prefix}customer"] = _("Client inconnu.")
        elif not customer.is_active:
            errors[f"{prefix}customer"] = _("Ce client est archivé.")
        elif customer.pk in seen:
            errors[f"{prefix}customer"] = _("Ce client a déjà son bon sur ce chargement.")
        else:
            seen.add(customer.pk)
        lines = delivery.get("lines") or []
        if not lines:
            errors[f"{prefix}lines"] = _("Ajoutez au moins un produit pour ce client.")
        address = (delivery.get("delivery_address") or "").strip()
        if len(address) > 255:
            errors[f"{prefix}delivery_address"] = _("255 caractères au plus.")
        box_counts = box_services.checked_box_counts(delivery.get("boxes"), errors, prefix=f"{prefix}boxes")
        checked.append(
            {
                "customer": customer,
                "address": address,
                "lines": _checked_transfer_lines(organization, kind, lines, at, errors, prefix, from_cold_rooms),
                "boxes": box_counts,
            }
        )
    return checked


def _client_address(customer: "Customer") -> str:
    """The client's own address as a BL prints it: street, then city."""
    return ", ".join(part for part in (customer.address, customer.city) if part)[:255]


def _prepared_transfer(
    organization: Organization,
    from_location: StockLocation,
    to_location: StockLocation,
    transferred_on: dt.date,
    lines: Sequence[TransferLineFields],
    boxes: Mapping[str, int] | None,
    deliveries: Sequence[TransferDeliveryFields] = (),
    from_cold_rooms: bool = False,
) -> tuple[str, list[dict[str, Any]], dict[str, int], list[dict[str, Any]]]:
    """The kind, the checked lines, the box counts and the client parts of a transfer, or a ValidationError
    with every problem. `lines` and `boxes` are the part not given to a client (kept on the truck)."""
    errors = _transfer_header_errors(organization, from_location, to_location, from_cold_rooms)
    if not lines and not deliveries and not boxes:
        errors["lines"] = _("Ajoutez au moins un produit.")
    kind = transfer_kind(from_location, to_location)
    at = moment_of(transferred_on)
    checked_lines = _checked_transfer_lines(organization, kind, lines, at, errors, from_cold_rooms=from_cold_rooms)
    checked_deliveries = _checked_deliveries(organization, kind, deliveries, at, errors, from_cold_rooms)
    box_counts = box_services.checked_box_counts(boxes, errors, prefix="boxes")
    # Boxes follow a load (D-122), or a return from a truck to a cold room (P1-T14e, D-124); no other transfer.
    returns_to_cold_room = kind == TransferKind.RETURN and to_location.kind == LocationKind.COLD_ROOM
    if box_counts and kind != TransferKind.LOAD and not returns_to_cold_room:
        errors["boxes"] = _("Les caisses ne se transfèrent que vers un camion, au chargement.")
    if errors:
        raise ValidationError(errors)
    return kind, checked_lines, box_counts, checked_deliveries


def _write_box_lines(transfer: Transfer, box_counts: Mapping[str, int], customer: "Customer | None" = None) -> None:
    TransferBoxLine.objects.bulk_create(
        [
            TransferBoxLine(
                organization_id=transfer.organization_id,
                transfer=transfer,
                customer=customer,
                box_type=box_type,
                count=count,
            )
            for box_type, count in box_counts.items()
        ]
    )


def _write_deliveries(transfer: Transfer, checked_deliveries: list[dict[str, Any]]) -> None:
    """The client parts of a load: who, where to, and their lines and boxes. An empty address takes the client's."""
    for part in checked_deliveries:
        customer = part["customer"]
        TransferDelivery.objects.create(
            organization_id=transfer.organization_id,
            transfer=transfer,
            customer=customer,
            delivery_address=part["address"] or _client_address(customer),
        )
        _write_transfer_lines(transfer, part["lines"], customer)
        _write_box_lines(transfer, part["boxes"], customer)


@transaction.atomic
def create_transfer(
    *,
    organization: Organization,
    actor: User | None,
    from_location: StockLocation,
    to_location: StockLocation,
    transferred_on: dt.date,
    lines: Sequence[TransferLineFields],
    notes: str = "",
    client_uuid: uuid.UUID | None = None,
    validate: bool = False,
    boxes: Mapping[str, int] | None = None,
    deliveries: Sequence[TransferDeliveryFields] = (),
    from_cold_rooms: bool = False,
) -> Transfer:
    """Prepare a transfer as a draft; with `validate`, also move the stock at once (one transaction).

    The kind (load, return, between places) comes from the two locations. A load line without a price
    takes the sale price in force. A load may carry returnable boxes (`boxes`, per box type): they move
    with the stock when it is validated. A load may be split by client (`deliveries`, D-160): each client's kg and
    boxes, with `lines` and `boxes` left for the part kept on the truck; validating it makes a draft BL per
    client. With `from_cold_rooms` a load takes each line from the cold rooms together (D-174). A `client_uuid`
    already used returns that transfer.
    """
    if client_uuid is not None:
        existing = Transfer.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    kind, checked_lines, box_counts, checked_deliveries = _prepared_transfer(
        organization, from_location, to_location, transferred_on, lines, boxes, deliveries, from_cold_rooms
    )
    transfer = Transfer.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "transfer"),
        kind=kind,
        from_location=from_location,
        from_cold_rooms=from_cold_rooms,
        to_location=to_location,
        transferred_on=transferred_on,
        notes=notes.strip(),
        created_by=actor,
        client_uuid=client_uuid,
    )
    _write_transfer_lines(transfer, checked_lines)
    _write_box_lines(transfer, box_counts)
    _write_deliveries(transfer, checked_deliveries)
    audit.record(
        organization=organization,
        actor=actor,
        action="transfer.created",
        target=transfer,
        after=_transfer_snapshot(transfer),
    )
    if validate:
        return validate_transfer(transfer=transfer, actor=actor)
    return transfer


def _locked_draft(transfer: Transfer) -> Transfer:
    """The transfer locked until commit, refused when it is no longer a draft."""
    locked = (
        Transfer.objects.select_for_update(of=("self",))
        .select_related("organization", "from_location", "to_location")
        .get(pk=transfer.pk)
    )
    if locked.status == TransferStatus.VALIDATED:
        raise ValidationError(_("Ce transfert est déjà validé : il ne se modifie plus."))
    if locked.status == TransferStatus.CANCELLED:
        raise ValidationError(_("Ce transfert est annulé."))
    return locked


@transaction.atomic
def update_transfer(
    *,
    transfer: Transfer,
    actor: User | None,
    from_location: StockLocation,
    to_location: StockLocation,
    transferred_on: dt.date,
    lines: Sequence[TransferLineFields],
    notes: str = "",
    validate: bool = False,
    boxes: Mapping[str, int] | None = None,
    deliveries: Sequence[TransferDeliveryFields] = (),
    from_cold_rooms: bool = False,
) -> Transfer:
    """Change a draft: its places, day, notes, lines, boxes and client parts (all replaced). With `validate`,
    validate it too."""
    transfer = _locked_draft(transfer)
    organization = transfer.organization
    before = _transfer_snapshot(transfer)
    kind, checked_lines, box_counts, checked_deliveries = _prepared_transfer(
        organization, from_location, to_location, transferred_on, lines, boxes, deliveries, from_cold_rooms
    )
    transfer.kind = kind
    transfer.from_location = from_location
    transfer.from_cold_rooms = from_cold_rooms
    transfer.to_location = to_location
    transfer.transferred_on = transferred_on
    transfer.notes = notes.strip()
    transfer.save()
    transfer.lines.all().delete()
    _write_transfer_lines(transfer, checked_lines)
    transfer.box_lines.all().delete()
    _write_box_lines(transfer, box_counts)
    transfer.deliveries.all().delete()
    _write_deliveries(transfer, checked_deliveries)
    audit.record(
        organization=organization,
        actor=actor,
        action="transfer.updated",
        target=transfer,
        before=before,
        after=_transfer_snapshot(transfer),
    )
    if validate:
        return validate_transfer(transfer=transfer, actor=actor)
    return transfer


def _cold_rooms(organization: Organization) -> list[StockLocation]:
    """The active cold rooms, by id: a load "from the cold rooms" empties the first one first (D-174)."""
    return list(
        StockLocation.objects.for_organization(organization)
        .filter(kind=LocationKind.COLD_ROOM, is_active=True)
        .order_by("id")
    )


def _post_line_from(
    rooms: Sequence[StockLocation],
    line: TransferLine,
    transfer: Transfer,
    actor: User | None,
    occurred_at: dt.datetime,
) -> None:
    """Move one line's kg out of `rooms`, the first one first: one place as before, or the cold rooms together
    (D-174). Refused as a whole when they hold less than the line together."""
    portions: list[tuple[StockLocation, Decimal]] = [(rooms[0], line.quantity)] if rooms else []
    if len(rooms) > 1:
        day = timezone.localtime(occurred_at).date()
        held = selectors.held_by_location(
            transfer.organization, product_id=line.product_id, location_ids=[room.pk for room in rooms], day=day
        )
        left = line.quantity
        portions = []
        for room in rooms:
            taken = min(left, held.get(room.pk, Decimal("0.000")))
            if taken > 0:
                portions.append((room, taken))
                left -= taken
        if left > 0:
            raise ValidationError(
                {
                    "quantity": _("Stock insuffisant : %(available)s kg dans les chambres froides.")
                    % {"available": line.quantity - left}
                }
            )
    picks = [(pick.batch_id, pick.quantity) for pick in line.picks.order_by("id")]
    for room, quantity in portions:
        post_fifo_movements(
            organization=transfer.organization,
            actor=actor,
            kind=MovementKind.TRANSFER,
            product_id=line.product_id,
            quantity=quantity,
            from_location=room,
            to_location=transfer.to_location,
            source=line,
            occurred_at=occurred_at,
            picks=picks,
        )


def _box_totals(box_lines: Sequence[TransferBoxLine]) -> dict[str, int]:
    """The boxes of every part of a transfer, added up per box type."""
    totals: dict[str, int] = {}
    for line in box_lines:
        totals[line.box_type] = totals.get(line.box_type, 0) + line.count
    return totals


def _line_keys(transfer: Transfer, lines: Sequence[TransferLine]) -> list[str]:
    """Where a form shows each line: `lines.<i>.` for the part kept on the truck, `deliveries.<d>.lines.<i>.` for a
    client's part. The lines were written in the order the form sent them, so ids keep that order."""
    client_order = {
        pk: position
        for position, pk in enumerate(transfer.deliveries.order_by("id").values_list("customer_id", flat=True))
    }
    seen: dict[int | None, int] = {}
    keys = []
    for line in lines:
        position = seen.get(line.customer_id, 0)
        seen[line.customer_id] = position + 1
        if line.customer_id is None:
            keys.append(f"lines.{position}.")
        else:
            keys.append(f"deliveries.{client_order[line.customer_id]}.lines.{position}.")
    return keys


@transaction.atomic
def validate_transfer(*, transfer: Transfer, actor: User | None) -> Transfer:
    """Move the stock of a draft: each line's kg leave the source, the lots picked on the line first and then the
    oldest batch first (D-037, D-215).

    Refused as a whole when any line asks more than the source holds (each on `lines.<index>.quantity`),
    when a location is archived, or for a day still to come. Lines are posted in product order, so two
    transfers validated at once lock the same rows in the same order and never wait for each other forever.
    """
    transfer = _locked_draft(transfer)
    organization = transfer.organization
    errors = _transfer_header_errors(
        organization, transfer.from_location, transfer.to_location, transfer.from_cold_rooms
    )
    if transfer.transferred_on > timezone.localdate():
        errors["transferred_on"] = _("Un transfert d'un jour à venir se valide ce jour-là.")
    if errors:
        raise ValidationError(errors)
    occurred_at = moment_of(transfer.transferred_on)
    lines = list(transfer.lines.order_by("id"))
    keys = _line_keys(transfer, lines)
    rooms = _cold_rooms(organization) if transfer.from_cold_rooms else [transfer.from_location]
    for index, line in sorted(enumerate(lines), key=lambda pair: pair[1].product_id):
        try:
            with transaction.atomic():
                _post_line_from(rooms, line, transfer, actor, occurred_at)
        except ValidationError as error:
            # The line's own savepoint is rolled back; the other lines are still checked, then all is refused.
            for field, messages in getattr(error, "message_dict", {"lines": error.messages}).items():
                key = f"{keys[index]}quantity" if field == "quantity" else field
                errors.setdefault(key, messages[0])
    if errors:
        raise ValidationError(errors)
    # The boxes move with the stock, in this same transaction: a refused box movement (not enough boxes at
    # the source, say) refuses the whole validation and leaves the stock where it was.
    box_lines = list(transfer.box_lines.all())
    if box_lines:
        box_kind = (
            box_services.BoxMovementKind.TRUCK_RETURN
            if transfer.kind == TransferKind.RETURN
            else box_services.BoxMovementKind.LOAD
        )
        try:
            box_services.post_box_counts(
                organization=organization,
                actor=actor,
                kind=box_kind,
                counts=_box_totals(box_lines),
                from_holder=box_services.holder_for(organization=organization, location=transfer.from_location),
                to_holder=box_services.holder_for(organization=organization, location=transfer.to_location),
                source=transfer,
            )
        except ValidationError as error:
            raise ValidationError({"boxes": error.messages}) from error
    transfer.status = TransferStatus.VALIDATED
    transfer.validated_by = actor
    transfer.validated_at = timezone.now()
    transfer.save(update_fields=["status", "validated_by", "validated_at", "updated_at"])
    audit.record(
        organization=organization,
        actor=actor,
        action="transfer.validated",
        target=transfer,
        after=_transfer_snapshot(transfer),
    )
    if transfer.kind == TransferKind.LOAD:
        load_validated.send(sender=Transfer, transfer=transfer, actor=actor)
    return transfer


@transaction.atomic
def cancel_transfer(*, transfer: Transfer, actor: User | None) -> Transfer:
    """Give up a draft. A validated transfer is corrected by a transfer the other way instead."""
    transfer = _locked_draft(transfer)
    transfer.status = TransferStatus.CANCELLED
    transfer.save(update_fields=["status", "updated_at"])
    audit.record(organization=transfer.organization, actor=actor, action="transfer.cancelled", target=transfer)
    return transfer


# ---- Losses (P1-T10, D-045) ----


@transaction.atomic
def update_stock_settings(
    *, organization: Organization, actor: User | None, loss_approval_threshold: Number
) -> StockSettings:
    """Change the weight above which a loss waits for the owner's approval (zero: every loss waits)."""
    try:
        threshold = checked_quantity(loss_approval_threshold, allow_zero=True)
    except (ValueError, TypeError) as error:
        raise ValidationError({"loss_approval_threshold": str(error)}) from None
    StockSettings.objects.bulk_create([StockSettings(organization=organization)], ignore_conflicts=True)
    row = StockSettings.objects.select_for_update().get(organization=organization)
    before = row.loss_approval_threshold
    if before != threshold:
        row.loss_approval_threshold = threshold
        row.save(update_fields=["loss_approval_threshold", "updated_at"])
        audit.record(
            organization=organization,
            actor=actor,
            action="stock.settings_updated",
            target=row,
            before={"loss_approval_threshold": before},
            after={"loss_approval_threshold": threshold},
        )
    return row


def _loss_reason_text(loss: StockLoss) -> str:
    """The reason kept on the ledger: the kind of loss, then the note when there is one."""
    label = str(LossReason(loss.reason).label)
    return f"{label} · {loss.note}" if loss.note else label


def _post_loss(loss: StockLoss, actor: User | None) -> None:
    """The lost kg leave the location, oldest batch first, the loss being the movements' source."""
    try:
        post_fifo_movements(
            organization=loss.organization,
            actor=actor,
            kind=MovementKind.LOSS,
            product_id=loss.product_id,
            quantity=loss.quantity,
            from_location=loss.location,
            reason=_loss_reason_text(loss),
            source=loss,
            # A loss the phone dated keeps that moment, and the stock must have held the kilos then.
            occurred_at=loss.made_at or moment_of(loss.lost_on),
            held_since_then=loss.made_at is not None,
        )
    except ValidationError as error:
        fields = getattr(error, "message_dict", {"quantity": error.messages})
        raise ValidationError(
            {("location" if field == "from_location" else field): messages for field, messages in fields.items()}
        ) from None


def _loss_snapshot(loss: StockLoss) -> dict[str, Any]:
    return {
        "number": loss.number,
        "status": loss.status,
        "location": loss.location.name,
        "product": loss.product.reference,
        "quantity": str(loss.quantity),
        "reason": loss.reason,
        "lost_on": loss.lost_on.isoformat(),
    }


@transaction.atomic
def record_loss(
    *,
    organization: Organization,
    actor: User | None,
    location: StockLocation,
    product: "Product",
    quantity: Number,
    reason: str,
    lost_on: dt.date,
    note: str = "",
    may_approve: bool = False,
    client_uuid: uuid.UUID | None = None,
    made_at: dt.datetime | None = None,
) -> StockLoss:
    """Record kilos lost at a location. Up to the threshold (or when `may_approve`: the owner), they leave
    the stock at once, oldest batch first; above it, the loss waits for the owner and nothing moves yet.

    Refused on its field: an unknown or archived location, a product of another organization, a weight
    that is not valid or more than the location holds, an unknown reason, a day still to come. A
    `client_uuid` already used returns that loss.
    """
    if client_uuid is not None:
        existing = StockLoss.objects.for_organization(organization).filter(client_uuid=client_uuid).first()
        if existing is not None:
            return existing
    errors: dict[str, str] = {}
    if location.organization_id != organization.pk:
        errors["location"] = _("Emplacement inconnu.")
    elif not location.is_active:
        errors["location"] = _("« %(name)s » est archivé.") % {"name": location.name}
    if product.organization_id != organization.pk:
        errors["product"] = _("Produit inconnu.")
    if reason not in LossReason.values:
        errors["reason"] = _("Choisissez la raison de la perte.")
    if lost_on > timezone.localdate():
        errors["lost_on"] = _("La date ne peut pas être dans le futur.")
    amount = None
    try:
        amount = checked_quantity(quantity)
    except (ValueError, TypeError):
        errors["quantity"] = _("Indiquez un poids en kg, supérieur à zéro.")
    if not errors and amount is not None:
        try:
            # Checked now so a loss waiting for approval is possible at least today.
            selectors.allocate_fifo(
                organization, product_id=product.pk, location=location, quantity=amount, day=lost_on
            )
        except ValidationError as error:
            errors.update({field: messages[0] for field, messages in error.message_dict.items()})
    if errors or amount is None:
        raise ValidationError(errors)

    immediate = may_approve or amount <= selectors.stock_settings(organization).loss_approval_threshold
    loss = StockLoss.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "loss"),
        status=LossStatus.APPROVED if immediate else LossStatus.PENDING,
        location=location,
        product=product,
        quantity=amount,
        reason=reason,
        note=note.strip(),
        lost_on=lost_on,
        made_at=made_at,
        created_by=actor,
        decided_by=actor if immediate else None,
        decided_at=timezone.now() if immediate else None,
        client_uuid=client_uuid,
    )
    if immediate:
        _post_loss(loss, actor)
    audit.record(
        organization=organization, actor=actor, action="loss.recorded", target=loss, after=_loss_snapshot(loss)
    )
    return loss


def _locked_pending_loss(loss: StockLoss) -> StockLoss:
    locked = (
        StockLoss.objects.select_for_update(of=("self",))
        .select_related("organization", "location", "product")
        .get(pk=loss.pk)
    )
    if locked.status != LossStatus.PENDING:
        raise ValidationError(_("Cette perte est déjà décidée : elle ne change plus."))
    return locked


@transaction.atomic
def approve_loss(*, loss: StockLoss, actor: User | None) -> StockLoss:
    """The owner accepts a loss that was waiting: its kg leave the stock now, oldest batch first."""
    loss = _locked_pending_loss(loss)
    _post_loss(loss, actor)
    loss.status = LossStatus.APPROVED
    loss.decided_by = actor
    loss.decided_at = timezone.now()
    loss.save(update_fields=["status", "decided_by", "decided_at", "updated_at"])
    audit.record(organization=loss.organization, actor=actor, action="loss.approved", target=loss)
    return loss


@transaction.atomic
def reject_loss(*, loss: StockLoss, actor: User | None, reason: str) -> StockLoss:
    """The owner refuses a loss that was waiting, saying why. Nothing moves."""
    reason = reason.strip()
    if not reason:
        raise ValidationError({"reason": _("Indiquez pourquoi la perte est refusée.")})
    loss = _locked_pending_loss(loss)
    loss.status = LossStatus.REJECTED
    loss.decided_by = actor
    loss.decided_at = timezone.now()
    loss.rejection_reason = reason
    loss.save(update_fields=["status", "decided_by", "decided_at", "rejection_reason", "updated_at"])
    audit.record(
        organization=loss.organization, actor=actor, action="loss.rejected", target=loss, after={"reason": reason}
    )
    return loss


@transaction.atomic
def add_loss_photo(*, loss: StockLoss, actor: User | None, upload: "UploadedFile[bytes]") -> StockLoss:
    """Join a photo to a loss, as proof. Once joined it is never replaced or removed."""
    content = reencoded_photo(upload)
    loss = StockLoss.objects.select_for_update().get(pk=loss.pk)
    if loss.photo:
        raise ValidationError({"photo": _("Une photo est déjà jointe à cette perte.")})
    loss.photo.save("photo.webp", content, save=False)
    try:
        loss.save(update_fields=["photo", "updated_at"])
        audit.record(organization=loss.organization, actor=actor, action="loss.photo_added", target=loss)
    except BaseException:
        # The file is written before the row: never leave it behind when the change is rolled back.
        if loss.photo.name:
            loss.photo.storage.delete(loss.photo.name)
        raise
    return loss


@transaction.atomic
def report_road_loss(
    *,
    organization: Organization,
    actor: User,
    location: StockLocation,
    product: "Product",
    quantity: Number,
    reason: str,
    note: str = "",
    upload: "UploadedFile[bytes] | None" = None,
    client_uuid: uuid.UUID | None = None,
    made_at: dt.datetime | None = None,
) -> StockLoss:
    """A driver reports kilos lost on their truck, with a photo as proof: today, or at the moment the phone
    says (`made_at`). Up to the threshold they leave the stock at once; above it the loss waits for the
    owner (P3-T05)."""
    loss = record_loss(
        organization=organization,
        actor=actor,
        location=location,
        product=product,
        quantity=quantity,
        reason=reason,
        lost_on=timezone.localtime(made_at or timezone.now()).date(),
        note=note,
        client_uuid=client_uuid,
        made_at=made_at,
    )
    if upload is not None and not loss.photo:
        loss = add_loss_photo(loss=loss, actor=actor, upload=upload)
    return loss


# ---- Stock counts (P1-T10, D-045) ----


class CountedFields(TypedDict):
    line: int
    # Empty clears what was typed; zero means nothing of the batch was found.
    counted_quantity: Number | None


@transaction.atomic
def start_count(
    *, organization: Organization, actor: User | None, location: StockLocation, counted_on: dt.date, notes: str = ""
) -> StockCount:
    """Open a count sheet for a location: one line per batch it holds, with the kg the ledger expects.

    One count at a time per location. Movements may go on while counting: approval posts each line's
    difference against this snapshot, not against the stock at approval time.
    """
    errors: dict[str, str] = {}
    if location.organization_id != organization.pk:
        raise ValidationError({"location": _("Emplacement inconnu.")})
    # Two counts started at once for the same place: the second waits here, then sees the first.
    location = StockLocation.objects.select_for_update().get(pk=location.pk)
    if not location.is_active:
        errors["location"] = _("« %(name)s » est archivé.") % {"name": location.name}
    open_count = StockCount.objects.filter(location=location, status=CountStatus.COUNTING).first()
    if open_count is not None:
        errors["location"] = _("Un inventaire est déjà en cours ici : %(number)s.") % {"number": open_count.number}
    if counted_on > timezone.localdate():
        errors["counted_on"] = _("La date ne peut pas être dans le futur.")
    holdings = list(selectors.on_hand_of(organization, location_id=location.pk))
    if not holdings and "location" not in errors:
        errors["location"] = _("Cet emplacement ne contient aucun stock à compter.")
    if errors:
        raise ValidationError(errors)
    count = StockCount.objects.create(
        organization=organization,
        number=numbering.next_number(organization, "count"),
        location=location,
        counted_on=counted_on,
        notes=notes.strip(),
        created_by=actor,
    )
    StockCountLine.objects.bulk_create(
        [
            StockCountLine(
                organization=organization,
                count=count,
                batch=row.batch,
                product_id=row.product_id,
                expected_quantity=row.quantity,
            )
            for row in holdings
        ]
    )
    audit.record(
        organization=organization,
        actor=actor,
        action="count.started",
        target=count,
        after={"location": location.name, "counted_on": counted_on.isoformat(), "lines": len(holdings)},
    )
    return count


def _locked_open_count(count: StockCount) -> StockCount:
    locked = (
        StockCount.objects.select_for_update(of=("self",)).select_related("organization", "location").get(pk=count.pk)
    )
    if locked.status == CountStatus.APPROVED:
        raise ValidationError(_("Cet inventaire est déjà validé : il ne change plus."))
    if locked.status == CountStatus.CANCELLED:
        raise ValidationError(_("Cet inventaire est annulé."))
    return locked


@transaction.atomic
def record_counted(*, count: StockCount, actor: User | None, lines: Sequence[CountedFields]) -> StockCount:
    """Type the kg counted on some lines of an open sheet. Errors come back on `lines.<index>.counted_quantity`
    (the index in `lines`, as sent)."""
    count = _locked_open_count(count)
    own_lines = {line.pk: line for line in count.lines.all()}
    errors: dict[str, str] = {}
    changed: list[StockCountLine] = []
    for index, item in enumerate(lines):
        line = own_lines.get(item["line"])
        if line is None:
            errors[line_error_key(index, "line")] = _("Cette ligne n'est pas sur cette feuille.")
            continue
        value: Any = item.get("counted_quantity")
        if value in (None, ""):
            line.counted_quantity = None
        else:
            try:
                line.counted_quantity = checked_quantity(value, allow_zero=True)
            except (ValueError, TypeError):
                errors[line_error_key(index, "counted_quantity")] = _("Indiquez un poids en kg (0 si rien trouvé).")
                continue
        changed.append(line)
    if errors:
        raise ValidationError(errors)
    StockCountLine.objects.bulk_update(changed, ["counted_quantity"])
    return count


@transaction.atomic
def approve_count(*, count: StockCount, actor: User | None) -> StockCount:
    """Post a count correction for every line whose counted kg differ from the sheet's, then freeze it.

    Every line must be counted. A shortage larger than what the batch still holds (it moved away since
    the sheet was made) is refused on that line, and nothing is posted.
    """
    count = _locked_open_count(count)
    # Errors name lines by their place on the sheet, as the API lists them.
    lines = list(count.lines.select_related("batch").order_by(*selectors.COUNT_SHEET_ORDER))
    missing = sum(1 for line in lines if line.counted_quantity is None)
    if missing:
        raise ValidationError({"lines": _("Il reste %(count)s ligne(s) à compter.") % {"count": missing}})
    errors: dict[str, str] = {}
    occurred_at = moment_of(count.counted_on)
    reason = _("Inventaire %(number)s") % {"number": count.number}
    # Batch order: the same lock order as every other posting at this location.
    for index, line in sorted(enumerate(lines), key=lambda pair: pair[1].batch_id):
        difference = line.difference
        if not difference:
            continue
        try:
            post_movement(
                organization=count.organization,
                actor=actor,
                kind=MovementKind.COUNT_CORRECTION,
                batch=line.batch,
                quantity=abs(difference),
                from_location=count.location if difference < 0 else None,
                to_location=count.location if difference > 0 else None,
                reason=reason,
                source=line,
                occurred_at=occurred_at,
            )
        except ValidationError as error:
            for field, messages in getattr(error, "message_dict", {"lines": error.messages}).items():
                key = line_error_key(index, "counted_quantity") if field == "quantity" else field
                errors.setdefault(key, messages[0])
    if errors:
        raise ValidationError(errors)
    count.status = CountStatus.APPROVED
    count.approved_by = actor
    count.approved_at = timezone.now()
    count.save(update_fields=["status", "approved_by", "approved_at", "updated_at"])
    audit.record(
        organization=count.organization,
        actor=actor,
        action="count.approved",
        target=count,
        after={
            "differences": [
                {"batch": line.batch.number, "difference": str(line.difference)} for line in lines if line.difference
            ]
        },
    )
    return count


@transaction.atomic
def cancel_count(*, count: StockCount, actor: User | None) -> StockCount:
    """Give up an open count. Nothing moved; the location may be counted again."""
    count = _locked_open_count(count)
    count.status = CountStatus.CANCELLED
    count.save(update_fields=["status", "updated_at"])
    audit.record(organization=count.organization, actor=actor, action="count.cancelled", target=count)
    return count
