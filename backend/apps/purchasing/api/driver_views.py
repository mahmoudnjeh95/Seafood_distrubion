"""The driver's side of buying at the port (P3-T12b, D-158): their own purchases, sent from the phone.

Only a driver the owner lets buy (`Membership.can_buy`) sends or changes one; any driver reads their own. The
office checks and validates them (`views.FieldPurchase*`); until then nothing enters stock and nothing is owed.
"""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors as catalog
from apps.core.clock import moment_from_phone
from apps.core.models import Membership
from apps.core.permissions import IsDriver, membership_of
from apps.dayclose import selectors as dayclose
from apps.fleet import selectors as fleet
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.purchasing import selectors, services
from apps.purchasing.models import FieldPurchase

from .serializers import (
    FieldPurchasePaperSerializer,
    LastCostFilterSerializer,
    LastCostSerializer,
    MyFieldPurchaseCreateSerializer,
    MyFieldPurchaseSerializer,
    MyFieldPurchaseUpdateSerializer,
    MySupplierSerializer,
)


class DriverView(APIView):
    permission_classes = (IsDriver,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    def buyer(self) -> Membership:
        """The driver, refused unless the owner lets them buy."""
        if not self.membership.can_buy:
            raise PermissionDenied(_("Vous n'êtes pas autorisé à acheter : demandez au propriétaire."))
        return self.membership


def _driver_fields(membership: Membership, data: dict[str, Any]) -> services.FieldPurchaseFields:
    """The ids the phone sent replaced by the rows they name; an unknown one is a field error. Archived ones are
    refused by the service."""
    organization = membership.organization
    errors: dict[str, str] = {}
    supplier = None
    if data.get("supplier") is not None:
        try:
            supplier = partners.supplier_of(organization, data["supplier"])
        except ObjectDoesNotExist:
            errors["supplier"] = _("Fournisseur inconnu.")
    lines: list[services.FieldLineFields] = []
    for index, line in enumerate(data["lines"]):
        product = None
        if line.get("product") is not None:
            try:
                product = catalog.product_of(organization, line["product"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "product")] = _("Produit inconnu.")
        lines.append(
            {
                "product": product,
                "proposed_product": line["proposed_product"],
                "declared_quantity": line["declared_quantity"],
                "unit_cost": line["unit_cost"],
            }
        )
    if errors:
        raise ValidationError(errors)
    return {
        "supplier": supplier,
        "proposed_supplier": data["proposed_supplier"],
        "proposed_supplier_phone": data["proposed_supplier_phone"],
        "terms": data["terms"],
        "due_days": data["due_days"],
        "supplier_reference": data["supplier_reference"],
        "notes": data["notes"],
        "lines": lines,
        "payments": data["payments"],
    }


class MyFieldPurchasesView(DriverView):
    @extend_schema(operation_id="listMyFieldPurchases", responses=MyFieldPurchaseSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The driver's own purchases of the last 30 days, newest first, with what the office decided and its note."""
        rows = selectors.field_purchases_of_buyer(self.membership.organization, buyer_id=self.membership.user_id)
        return Response(MyFieldPurchaseSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="sendMyFieldPurchase",
        request=MyFieldPurchaseCreateSerializer,
        responses={201: MyFieldPurchaseSerializer},
    )
    def post(self, request: Request) -> Response:
        """Send what was bought at the port: the supplier (or a new name), the products (or new names), kg, price,
        the deal and the money given. It waits for the office; nothing enters stock and nothing is owed before.
        `client_uuid` makes a retry answer with the purchase already saved; `made_at` is the phone's time."""
        membership = self.buyer()
        serializer = MyFieldPurchaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        made_at = moment_from_phone(data["made_at"], field="made_at")
        # Bought after the day's closing was sent, or on a day the office approved: refused, as an expense.
        dayclose.refuse_sale_outside_day(membership, made_at)
        fields = _driver_fields(membership, data)
        fields["bought_on"] = timezone.localtime(made_at or timezone.now()).date()
        # The goods go on the driver's truck of that day (D-211); the office may still choose another place.
        truck = fleet.truck_of_driver(membership, on=fields["bought_on"])
        fields["location"] = truck.location if truck is not None else None
        purchase = services.submit_field_purchase(
            organization=membership.organization,
            buyer=membership.user,
            fields=fields,
            client_uuid=data["client_uuid"],
            made_at=made_at,
        )
        return Response(
            MyFieldPurchaseSerializer(selectors.field_purchase_of(membership.organization, purchase.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class MyFieldPurchaseView(DriverView):
    @extend_schema(
        operation_id="changeMyFieldPurchase",
        request=MyFieldPurchaseUpdateSerializer,
        responses=MyFieldPurchaseSerializer,
    )
    def put(self, request: Request, purchase_id: int) -> Response:
        """Change a purchase the office has not decided yet (a new revision). What the office set stays: the kg
        received, the place, the boxes, its note. `revision` must be the current one, else 400 on `revision`."""
        membership = self.buyer()
        try:
            purchase = selectors.field_purchases_of_buyer(membership.organization, buyer_id=membership.user_id).get(
                pk=purchase_id
            )
        except FieldPurchase.DoesNotExist:
            raise Http404 from None
        serializer = MyFieldPurchaseUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        services.update_field_purchase_by_buyer(
            purchase=purchase,
            buyer=membership.user,
            revision=data["revision"],
            fields=_driver_fields(membership, data),
        )
        return Response(
            MyFieldPurchaseSerializer(selectors.field_purchase_of(membership.organization, purchase_id)).data
        )


class MySuppliersView(DriverView):
    @extend_schema(operation_id="listMySuppliers", responses=MySupplierSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The suppliers a driver who buys may pick, by name (no balances, no partnership terms)."""
        membership = self.buyer()
        return Response(MySupplierSerializer(partners.suppliers_of(membership.organization), many=True).data)


class MyPurchaseCostsView(DriverView):
    @extend_schema(
        operation_id="listMyPurchaseCosts",
        parameters=[LastCostFilterSerializer],
        responses=LastCostSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """What was last paid one supplier for each product: the hint next to the price the driver types."""
        membership = self.buyer()
        filters = LastCostFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        batches = inventory.last_batches_from(membership.organization, supplier_id=filters.validated_data["supplier"])
        return Response(LastCostSerializer(batches, many=True).data)


class MyFieldPurchasePaperView(DriverView):
    parser_classes = (MultiPartParser,)

    @extend_schema(
        operation_id="addMyFieldPurchasePaper",
        request={"multipart/form-data": FieldPurchasePaperSerializer},
        responses=MyFieldPurchaseSerializer,
    )
    def put(self, request: Request, purchase_id: int) -> Response:
        """Join the photo of the supplier's paper to one of the driver's purchases (D-159): turned upright, shrunk,
        stored as WebP without the phone's metadata. Replaced while the office has not decided the purchase."""
        membership = self.buyer()
        try:
            purchase = selectors.field_purchases_of_buyer(membership.organization, buyer_id=membership.user_id).get(
                pk=purchase_id
            )
        except FieldPurchase.DoesNotExist:
            raise Http404 from None
        serializer = FieldPurchasePaperSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_field_purchase_paper(
            purchase=purchase, actor=membership.user, upload=serializer.validated_data["paper"]
        )
        return Response(
            MyFieldPurchaseSerializer(selectors.field_purchase_of(membership.organization, purchase_id)).data
        )
