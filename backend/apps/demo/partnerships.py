"""Demo partnership lots (P6-T01, D-060), one per partner supplier of docs/spec/sample/suppliers.csv:

- Pêcherie Kerkennah (F-001, `profit_sharing`, 40 % of a profit, 25 % of a loss) shares its seiche lot
  KRK-1192 (15 kg at 20.500 DT) with the owner.
- Surgelés du Sahel (F-004, `joint_investment`, 30 % of a profit, 20 % of a loss) funds its own lot of
  Symphonie Marine, SDS-2026-342 (20 kg at 25.500 DT = 510.000 DT), entirely with their capital.

Each partnership is set before the demo sales, so each lot's seeded sale is its first sale; a cost typed on
each lot comes after the demo expenses. Both lots stay open: their "Résultat du lot" card shows the result
so far (seiche: 150.000 DT before the owner's late costs; Symphonie Marine: 660.000 − 510.000 − 12.000 =
138.000 DT net, split 30/70 between Surgelés du Sahel and the owner). Running the seed again creates nothing.
"""

import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError
from django.utils import timezone

from apps.core.models import Organization, User
from apps.expenses import selectors as expense_selectors
from apps.expenses import services as expenses
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.partnerships import selectors, services

if TYPE_CHECKING:
    from apps.inventory.models import Batch

SEED_NAMESPACE = uuid.UUID("8d1f2b7c-4a6e-4f3b-9c2d-7e5a1b0c3d48")


@dataclass(frozen=True)
class PartnerLot:
    partner: str
    delivery_note: str
    product: str
    owner_capital: str
    partner_capital: str
    profit_rate: str
    loss_rate: str
    notes: str
    cost_key: str
    cost_amount: str
    cost_description: str
    cost_payee: str


LOTS = [
    PartnerLot(
        partner="F-001",
        delivery_note="KRK-1192",
        product="SE-012",
        owner_capital="200.000",
        partner_capital="107.500",
        profit_rate="40",
        loss_rate="25",
        notes="Lot acheté à deux : 15 kg de seiche à 20,500 DT/kg (exemple).",
        cost_key="transport-seiche",
        cost_amount="18.000",
        cost_description="Transport Kerkennah → dépôt",
        cost_payee="Transports Ben Ammar",
    ),
    PartnerLot(
        partner="F-004",
        delivery_note="SDS-2026-342",
        product="SY-008",
        owner_capital="0.000",
        partner_capital="510.000",
        profit_rate="30",
        loss_rate="20",
        notes="Lot financé par le partenaire investisseur : 20 kg de Symphonie Marine à 25,500 DT/kg.",
        cost_key="transport-symphonie",
        cost_amount="12.000",
        cost_description="Transport Sousse → dépôt",
        cost_payee="Transports Ben Ammar",
    ),
]


def _lot(organization: Organization, lot: PartnerLot) -> "Batch | None":
    return (
        inventory.batches_of(organization)
        .filter(receipt_reference=lot.delivery_note, product__reference=lot.product)
        .order_by("id")
        .first()
    )


def seed_partnerships(*, organization: Organization, actor: User | None) -> int:
    """Put each demo lot in partnership with its partner supplier, once. Returns how many were created."""
    created = 0
    for lot in LOTS:
        batch = _lot(organization, lot)
        if batch is None or selectors.partnerships_of(organization, batch_id=batch.pk).exists():
            continue
        partner = partners.suppliers_of(organization, status="all").filter(reference=lot.partner).first()
        if partner is None:
            continue
        try:
            services.create_partnership(
                organization=organization,
                actor=actor,
                batch=batch,
                partner=partner,
                owner_capital=lot.owner_capital,
                partner_capital=lot.partner_capital,
                profit_rate=lot.profit_rate,
                loss_rate=lot.loss_rate,
                notes=lot.notes,
            )
        except ValidationError:  # the lot was sold or changed by hand on staging
            continue
        created += 1
    return created


def seed_partnership_costs(*, organization: Organization, actor: User | None) -> int:
    """A cost typed on each partnership lot, approved. Returns how many were created."""
    created = 0
    for lot in LOTS:
        batch = _lot(organization, lot)
        if batch is None:
            continue
        client_uuid = uuid.uuid5(SEED_NAMESPACE, lot.cost_key)
        if expense_selectors.expenses_of(organization).filter(client_uuid=client_uuid).exists():
            continue
        expenses.create_expense(
            organization=organization,
            actor=actor,
            spent_on=max(batch.received_on, timezone.localdate()),
            category=expense_selectors.category_by_code(organization, "transport"),
            amount=lot.cost_amount,
            description=lot.cost_description,
            payee=lot.cost_payee,
            batch=batch,
            client_uuid=client_uuid,
            approve=True,
        )
        created += 1
    return created
