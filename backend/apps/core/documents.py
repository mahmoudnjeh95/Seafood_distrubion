"""The shape every app uses to list its documents on the "Documents" page (P2-T11, D-102).

Sales (quotes, BL, invoices, credit notes) and purchasing (purchase orders, receipts, supplier invoices) each
describe their own documents with `DocumentRow` from their selectors; `apps.doclist` merges them. The row says
what the document is, who it is with, its amount, how far it went, which documents it came from and what the
person asking may do with it next. Nothing here writes: the actions run through each app's own endpoints.
"""

import datetime as dt
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Literal

# The document codes as printed on the documents themselves.
DocumentType = Literal["DV", "BL", "FA", "AV", "BA", "BR", "FF"]
DOCUMENT_TYPES: tuple[DocumentType, ...] = ("DV", "BL", "FA", "AV", "BA", "BR", "FF")

# How far a document went, for the colour of its status: still being typed, waiting for something (sent, open,
# partly received), finished (validated, issued, received, paid) or cancelled (refused, expired, cancelled).
Tone = Literal["draft", "waiting", "done", "cancelled"]
TONES: tuple[Tone, ...] = ("draft", "waiting", "done", "cancelled")

PartnerSide = Literal["customer", "supplier"]
PARTNER_SIDES: tuple[PartnerSide, ...] = ("customer", "supplier")

# As Django choices, for the API schema (`ENUM_NAME_OVERRIDES`).
DOCUMENT_TYPE_CHOICES = [(value, value) for value in DOCUMENT_TYPES]
TONE_CHOICES = [(value, value) for value in TONES]
PARTNER_SIDE_CHOICES = [(value, value) for value in PARTNER_SIDES]


def document_key(kind: DocumentType, object_id: int) -> str:
    """The id of a document across every type: "BL:12"."""
    return f"{kind}:{object_id}"


@dataclass(frozen=True)
class DocumentFilters:
    """What the "Documents" page asks for. Days are both included; `search` matches number and partner."""

    date_from: dt.date | None = None
    date_to: dt.date | None = None
    search: str = ""
    # Empty: every type.
    types: frozenset[str] = frozenset()


@dataclass
class DocumentRow:
    type: DocumentType
    id: int
    number: str
    partner_side: PartnerSide
    partner_id: int
    partner_name: str
    date: dt.date
    amount: Decimal
    # The model's own status and its label ("sent", "Envoyé").
    status: str
    status_label: str
    tone: Tone
    # The documents it came from, as `document_key`s: a BL's quote, an invoice's BL, a receipt's order...
    parents: list[str] = field(default_factory=list)
    # What the person asking may do next (see `apps.doclist` for the list); empty for read-only roles.
    actions: list[str] = field(default_factory=list)
    # The PDF kind of `apps.documents` when a PDF exists for it in this state, else "".
    pdf: str = ""

    @property
    def key(self) -> str:
        return document_key(self.type, self.id)


@dataclass(frozen=True)
class PartyDocuments:
    """What one customer or supplier has on paper, for the règlement forms (D-211): its BL (a customer) or BR (a
    supplier), its invoices, and their total (a customer's net to pay, a supplier's invoiced total). Drafts and
    cancelled documents are not counted."""

    party_id: int
    deliveries: int = 0
    invoices: int = 0
    total: Decimal = Decimal("0.000")
