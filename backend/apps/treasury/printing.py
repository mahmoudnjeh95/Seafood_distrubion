"""The PDF bordereau of a remise en banque (P9-T04a, D-216): the effets handed to the bank, for its counter."""

from decimal import Decimal
from typing import Any

from django.utils.text import slugify

from apps.core.models import Organization
from apps.documents import services as documents
from apps.sales import selectors as sales

from .selectors import deposit_of


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


def deposit_printable(organization: Organization, deposit_id: int) -> documents.Printable:
    deposit = deposit_of(organization, deposit_id)
    effets = list(deposit.instruments.all())
    context: dict[str, Any] = {
        "number": deposit.number,
        "seller": _seller_of(organization),
        "deposit": deposit,
        "doc_date": deposit.deposited_on,
        "party": {
            "label": "Banque",
            "name": f"{deposit.bank.code} · {deposit.bank.name}",
            "address": "",
            "phone": "",
            "tax_id": "",
        },
        "effets": [
            {
                "kind": effet.get_kind_display(),
                "number": effet.number,
                "bank": effet.bank.code if effet.bank else "",
                "drawer": effet.drawer or (effet.customer.name if effet.customer else ""),
                "due_on": effet.due_on,
                "amount": effet.amount,
            }
            for effet in effets
        ],
        "cheques": sum(1 for effet in effets if effet.kind == "cheque"),
        "bills": sum(1 for effet in effets if effet.kind == "bill"),
        "total": sum((effet.amount for effet in effets), Decimal("0.000")),
    }
    return documents.Printable(
        template="treasury/pdf/deposit.html",
        context=context,
        version=deposit.updated_at.isoformat(),
        filename=f"bordereau-{slugify(deposit.number) or 'document'}.pdf",
        title=f"Bordereau de remise {deposit.number}",
    )


def register_printables() -> None:
    documents.register(documents.DocumentKind.BANK_DEPOSIT, deposit_printable)
