"""The partner statement PDF (P6-T04, D-072): everything a partner needs to read one lot without help.

One statement per partnership lot. A closed lot shows its frozen result; an open one shows "so far" and says
so. Registered with the documents app when `closing` starts.
"""

import hashlib
import json
from typing import Any

from django.utils import timezone
from django.utils.text import slugify

from apps.core.models import Organization
from apps.documents import services as documents
from apps.partnerships import selectors as partnerships
from apps.sales import selectors as sales

from . import engine, selectors

# The labels of the cost groups, as the lot page shows them.
COST_KIND_LABELS = {
    "lot": "Frais du lot",
    "truck_day": "Part des frais camion du jour",
    "employee": "Employés (jours × salaire / 26)",
    "cold_room": "Chambre froide",
    "cold_room_adjustment": "Chambre froide : correction après la facture",
    "general": "Frais généraux (loyer, comptable…)",
}


def _seller_of(organization: Organization) -> dict[str, str]:
    version = sales.finance_settings_on(organization)
    if version is None:
        return {"name": organization.name, "address": "", "phone": "", "tax_id": "", "trade_register": ""}
    return {
        "name": version.legal_name or organization.name,
        "address": version.address,
        "phone": version.phone,
        "tax_id": version.tax_id,
        "trade_register": version.trade_register,
    }


def partner_statement_printable(organization: Organization, partnership_id: int) -> documents.Printable:
    partnership = partnerships.partnership_of(organization, partnership_id)
    result = selectors.closed_result_of(organization, batch_id=partnership.batch_id)
    closed = result is not None and result.partnership_id == partnership.pk
    if closed and result is not None:
        data: dict[str, Any] = result.data
    else:
        data = engine.to_json(selectors.live_result(organization, batch_id=partnership.batch_id))
    settlement = partnerships.settlement_of(partnership)
    capital_entries = list(partnerships.capital_entries_of(partnership))
    share_entries = list(partnerships.profit_share_entries_of(partnership))

    partner = data["partner"]
    supplier = partnership.partner
    # A closed lot's statement is dated the day it closed; an open one the day it is printed ("à ce jour").
    statement_on = timezone.localdate()
    if closed and result is not None:
        statement_on = timezone.localtime(result.closed_at).date()
    groups = [{**group, "label": COST_KIND_LABELS.get(group["kind"], group["kind"])} for group in data["cost_groups"]]
    context: dict[str, Any] = {
        "number": data["batch"]["batch_number"],
        "seller": _seller_of(organization),
        "partnership": partnership,
        "partner_name": supplier.name,
        "doc_date": statement_on,
        # The partner block of the shared document header (D-131).
        "party": {
            "label": "Partenaire",
            "name": supplier.name,
            "reference": supplier.reference,
            "address": ", ".join(part for part in (supplier.address, supplier.city) if part),
            "phone": supplier.phone,
            "tax_id": supplier.tax_id,
        },
        "closed": closed,
        "closed_at": result.closed_at if closed and result is not None else None,
        "data": data,
        "batch": data["batch"],
        "partner": partner,
        "groups": groups,
        "outcome": data["outcome"],
        "capital_entries": capital_entries,
        "share_entries": share_entries,
        "settlement": settlement,
        "payments": list(settlement.payments.all()) if settlement is not None else [],
    }
    # The file changes whenever a figure on it does: the frozen result, the ledgers or the settlement.
    fingerprint = json.dumps(
        {
            "data": data,
            "closed": closed,
            "capital": [(e.pk, str(e.amount)) for e in capital_entries],
            "share": [(e.pk, str(e.amount)) for e in share_entries],
            "settlement": settlement.updated_at.isoformat() if settlement is not None else "",
            "status": partnership.status,
            "on": statement_on.isoformat(),
        },
        sort_keys=True,
        default=str,
    )
    return documents.Printable(
        template="closing/pdf/partner_statement.html",
        context=context,
        version=hashlib.sha1(fingerprint.encode(), usedforsecurity=False).hexdigest(),
        filename=f"releve-{slugify(data['batch']['batch_number']) or 'lot'}-{slugify(partnership.partner.name)}.pdf",
        title=f"Relevé du lot {data['batch']['batch_number']}",
        email_to=partnership.partner.email_addresses(),
    )


def register_printables() -> None:
    # The owner's own money, like the lot result (D-061): the owner and the accountant, not managers.
    documents.register(
        documents.DocumentKind.PARTNER_STATEMENT, partner_statement_printable, roles=frozenset({"owner", "accountant"})
    )
