"""What the assistant can look up (P12-T01: reads only). Each tool is one call to an existing endpoint.

`roles` only decides which tools the model is offered, so it does not try what the user's role cannot do. The
real check is the endpoint's own permission, run as the user (api_caller). After the roles matrix merges,
`roles` becomes a section and a level of that matrix (P12-T05).
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from apps.core.models import Membership, Role

from .api_caller import call_api

MAX_RESULT = 12_000
OFFICE = frozenset({Role.OWNER, Role.MANAGER, Role.ACCOUNTANT})
DRIVER = frozenset({Role.DRIVER})
EVERYONE = OFFICE | DRIVER

UNAVAILABLE = "Outil indisponible."
REFUSED = "Refusé : ce rôle n'a pas accès à cette information."
NOT_FOUND = "Introuvable."


@dataclass(frozen=True)
class Tool:
    name: str
    description: str
    properties: dict[str, dict[str, Any]]
    roles: frozenset[Role]
    request: Callable[[dict[str, Any]], tuple[str, dict[str, str]]]

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": self.properties,
            "required": list(self.properties),
            "additionalProperties": False,
        }

    def definition(self) -> dict[str, Any]:
        """The tool as the Messages API takes it."""
        return {"name": self.name, "description": self.description, "input_schema": self.input_schema, "strict": True}


TEXT = {"type": "string"}
ID = {"type": "integer"}
DAY = {"type": "string", "description": "Date AAAA-MM-JJ"}

READ_TOOLS: tuple[Tool, ...] = (
    Tool(
        name="find_customer",
        description=(
            "Chercher un client par nom, référence ou téléphone. À utiliser avant toute question sur un client "
            "précis (ex. « 9addech ysalni Mohamed? ») pour obtenir son id."
        ),
        properties={"query": TEXT},
        roles=OFFICE,
        request=lambda args: ("customers", {"search": str(args["query"])}),
    ),
    Tool(
        name="customer_balance",
        description="Solde d'un client (ce qu'il doit), par son id. Ex. « 9addech ysalni ? »",
        properties={"customer_id": ID},
        roles=OFFICE,
        request=lambda args: (f"customers/{int(args['customer_id'])}/balance", {}),
    ),
    Tool(
        name="receivables_ageing",
        description="Tous les clients qui doivent de l'argent, par ancienneté. Ex. « chkoun ma khallasch ? »",
        properties={},
        roles=OFFICE,
        request=lambda args: ("receivables/ageing", {}),
    ),
    Tool(
        name="find_product",
        description="Chercher un produit par nom ou référence, pour obtenir son id. Ex. « 9ar3oun », « dorade ».",
        properties={"query": TEXT},
        roles=EVERYONE,
        request=lambda args: ("products", {"search": str(args["query"])}),
    ),
    Tool(
        name="stock_overview",
        description="Le stock de tous les produits, chambre froide et camions. Ex. « chnowa 3andi f frigo ? »",
        properties={},
        roles=OFFICE,
        request=lambda args: ("stock/overview", {}),
    ),
    Tool(
        name="product_stock",
        description="Le stock d'un produit par emplacement et par lot (dates), par son id.",
        properties={"product_id": ID},
        roles=OFFICE,
        request=lambda args: (f"stock/products/{int(args['product_id'])}", {}),
    ),
    Tool(
        name="sales_report",
        description=(
            "Les ventes d'une période (dates incluses), groupées par client, produit, camion, chauffeur, jour, "
            "semaine ou mois. Ex. « 9addech bi3na lyoum ? » : date_from = date_to = aujourd'hui."
        ),
        properties={
            "date_from": DAY,
            "date_to": DAY,
            "group_by": {"type": "string", "enum": ["customer", "product", "truck", "driver", "day", "week", "month"]},
        },
        roles=OFFICE,
        request=lambda args: (
            "reports/sales",
            {"date_from": str(args["date_from"]), "date_to": str(args["date_to"]), "group_by": str(args["group_by"])},
        ),
    ),
    Tool(
        name="my_stock",
        description="Pour un chauffeur : ce qu'il a dans son camion aujourd'hui.",
        properties={},
        roles=DRIVER,
        request=lambda args: ("my-stock", {}),
    ),
    Tool(
        name="my_truck_day",
        description="Pour un chauffeur : sa journée (camion, chargements, ventes, caisse).",
        properties={},
        roles=DRIVER,
        request=lambda args: ("my-truck-day", {}),
    ),
)


def tools_for(membership: Membership) -> list[Tool]:
    return [tool for tool in READ_TOOLS if membership.role in tool.roles]


def run_tool(membership: Membership, name: str, arguments: dict[str, Any]) -> str:
    """Run a tool the model asked for and give back what it may read, as text."""
    tool = next((tool for tool in tools_for(membership) if tool.name == name), None)
    if tool is None:
        return UNAVAILABLE
    try:
        path, query = tool.request(arguments)
    except (KeyError, TypeError, ValueError):
        return UNAVAILABLE
    answer = call_api(user=membership.user, method="GET", path=path, query=query)
    if answer.status in (401, 403):
        return REFUSED
    if answer.status == 404:
        return NOT_FOUND
    if answer.status >= 400:
        return f"Erreur {answer.status} : {compact(answer.data)}"
    return compact(answer.data)


def compact(data: Any) -> str:
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"), default=str)
    if len(text) > MAX_RESULT:
        return text[:MAX_RESULT] + "… (tronqué)"
    return text
