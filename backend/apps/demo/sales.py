"""Demo sales (P2-T04): a counter sale to the walk-in customer at the fresh cold room, paid in cash; a sale from
Camion 1 by the demo driver to Restaurant Le Corail, partly paid; the accepted quote of Café-Resto Sidi Mansour
turned into a sale on credit; a draft for Hôtel Thyna; and the whole of the Surgelés du Sahel partnership lot
(SDS-2026-342, Symphonie Marine) sold to Poissonnerie El Bahr, paid in cash (P6-T01, D-060).

Each sale has a fixed `client_uuid`, so running the seed again creates nothing. They are made at the moment of
the first seed. A sale the stock or the quote no longer allows (staging data changed by hand, the quote's
validity date passed) is skipped rather than failing the deploy.
"""

import uuid
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

from apps.catalog import selectors as catalog
from apps.core.models import Organization, User
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.sales import selectors, services

if TYPE_CHECKING:
    from apps.inventory.models import StockLocation

SEED_NAMESPACE = uuid.UUID("5c0f8e1a-9d2b-4c47-a6e3-1f7b20d93c58")
FRESH_ROOM = "Chambre froide 1 (frais)"
FROZEN_ROOM = "Chambre froide 2 (congelé)"
TRUCK = "Camion 1"
QUOTE_CUSTOMER = "C-004"
# key, customer reference (None: walk-in), place, seller ("driver" or "owner"), confirm,
# payment, lines: product reference and kg (prices in force)
SALES: list[tuple[str, str | None, str, str, bool, services.PaymentFields, list[tuple[str, str]]]] = [
    (
        "comptoir",
        None,
        FRESH_ROOM,
        "owner",
        True,
        {"paid_in_full": True, "payment_method": "cash"},
        [("DO-003", "2"), ("RO-009", "1.5")],
    ),
    (
        "corail-camion",
        "C-001",
        TRUCK,
        "driver",
        True,
        {"amount_paid": "50.000", "payment_method": "cash"},
        [("CR-001", "3"), ("MO-007", "4")],
    ),
    ("thyna-brouillon", "C-002", FRESH_ROOM, "owner", False, {}, [("LO-004", "5")]),
    (
        "bahr-symphonie",
        "C-003",
        FROZEN_ROOM,
        "owner",
        True,
        {"paid_in_full": True, "payment_method": "cash"},
        [("SY-008", "20")],
    ),
]


def seed_sales(*, organization: Organization, actor: User | None, driver: User | None) -> int:
    """Create the demo sales that do not exist yet. Returns how many were created."""
    customers = {customer.reference: customer for customer in partners.customers_of(organization, status="all")}
    products = {product.reference: product for product in catalog.products_of(organization, status="all")}
    locations = {location.name: location for location in inventory.locations_of(organization, status="all")}
    existing = set(selectors.sales_of(organization).exclude(client_uuid=None).values_list("client_uuid", flat=True))
    created = 0
    for key, customer, place, seller, confirm, payment, lines in SALES:
        client_uuid = uuid.uuid5(SEED_NAMESPACE, key)
        if client_uuid in existing:
            continue
        try:
            services.create_sale(
                organization=organization,
                actor=driver if seller == "driver" else actor,
                customer=customers[customer] if customer is not None else None,
                location=locations[place],
                lines=[{"product": products[reference], "quantity": kg} for reference, kg in lines],
                payment=payment,
                client_uuid=client_uuid,
                confirm=confirm,
            )
        except ValidationError:
            continue
        created += 1
    return created + _convert_accepted_quote(organization, actor, locations[FRESH_ROOM])


def _convert_accepted_quote(organization: Organization, actor: User | None, location: "StockLocation") -> int:
    """Sidi Mansour's accepted quote becomes a confirmed sale on credit, once."""
    accepted = selectors.quotes_of(organization, status="accepted").filter(customer__reference=QUOTE_CUSTOMER)
    for quote in accepted:
        if quote.sales.exists():
            return 0
        try:
            services.create_sale_from_quote(quote=quote, actor=actor, location=location, confirm=True)
        except ValidationError:
            return 0
        return 1
    return 0
