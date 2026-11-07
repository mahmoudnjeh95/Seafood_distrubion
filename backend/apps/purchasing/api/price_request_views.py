"""Price requests to several suppliers, their offers side by side, and the orders made from the chosen ones (D-289)."""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import serializers, status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response

from apps.catalog import selectors as catalog
from apps.core.api.pagination import PagedList
from apps.core.models import Organization
from apps.partners import selectors as partners
from apps.purchasing import selectors, services
from apps.purchasing.models import (
    PriceRequest,
    PriceRequestLine,
    PriceRequestStatus,
    PurchaseOrderStatus,
    SupplierOffer,
    SupplierOfferLine,
)

from .serializers import RefSerializer
from .views import PurchasingView


class PriceRequestLineSerializer(serializers.ModelSerializer[PriceRequestLine]):
    product = RefSerializer(read_only=True)

    class Meta:
        model = PriceRequestLine
        fields = ("id", "product", "quantity")
        read_only_fields = fields


class SupplierOfferLineSerializer(serializers.ModelSerializer[SupplierOfferLine]):
    class Meta:
        model = SupplierOfferLine
        fields = ("request_line", "unit_cost", "retained")
        read_only_fields = fields


class OfferOrderSerializer(serializers.Serializer[Any]):
    id = serializers.IntegerField(read_only=True)
    number = serializers.CharField(read_only=True)
    status = serializers.ChoiceField(choices=PurchaseOrderStatus.choices, read_only=True)


class SupplierOfferSerializer(serializers.ModelSerializer[SupplierOffer]):
    supplier = RefSerializer(read_only=True)
    # A price per kg per request line the supplier offers (`request_line` is the line's id).
    lines = SupplierOfferLineSerializer(many=True, read_only=True)
    # The purchase order made from it, once chosen.
    order = OfferOrderSerializer(read_only=True, allow_null=True)

    class Meta:
        model = SupplierOffer
        fields = ("id", "supplier", "reference", "received_on", "valid_until", "notes", "lines", "order")
        read_only_fields = fields


class PriceRequestSerializer(serializers.ModelSerializer[PriceRequest]):
    status = serializers.ChoiceField(choices=PriceRequestStatus.choices, read_only=True)
    lines = PriceRequestLineSerializer(many=True, read_only=True)
    offers = SupplierOfferSerializer(many=True, read_only=True)
    created_by = serializers.SerializerMethodField()

    class Meta:
        model = PriceRequest
        fields = ("id", "number", "requested_on", "status", "notes", "lines", "offers", "created_by", "created_at")
        read_only_fields = fields

    def get_created_by(self, request: PriceRequest) -> str:
        user = request.created_by
        if user is None:
            return ""
        return f"{user.first_name} {user.last_name}".strip() or str(user.username)


class PriceRequestLineWriteSerializer(serializers.Serializer[Any]):
    product = serializers.IntegerField(min_value=1)
    quantity = serializers.CharField(max_length=20)


class PriceRequestWriteSerializer(serializers.Serializer[Any]):
    requested_on = serializers.DateField()
    suppliers = serializers.ListField(child=serializers.IntegerField(min_value=1), allow_empty=True)
    lines = PriceRequestLineWriteSerializer(many=True, allow_empty=True)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class OfferPriceWriteSerializer(serializers.Serializer[Any]):
    request_line = serializers.IntegerField(min_value=1)
    # Price per kg without VAT, in DT ("23.500"); empty: not offered.
    unit_cost = serializers.CharField(max_length=20, allow_blank=True, allow_null=True)


class OfferWriteSerializer(serializers.Serializer[Any]):
    supplier = serializers.IntegerField(min_value=1)
    prices = OfferPriceWriteSerializer(many=True, allow_empty=True)
    reference = serializers.CharField(required=False, allow_blank=True, default="", max_length=50)
    received_on = serializers.DateField(required=False, allow_null=True, default=None)
    valid_until = serializers.DateField(required=False, allow_null=True, default=None)
    notes = serializers.CharField(required=False, allow_blank=True, default="")


class OrderChoiceWriteSerializer(serializers.Serializer[Any]):
    request_line = serializers.IntegerField(min_value=1)
    supplier = serializers.IntegerField(min_value=1)


class OrderFromOffersWriteSerializer(serializers.Serializer[Any]):
    choices = OrderChoiceWriteSerializer(many=True, allow_empty=True)
    ordered_on = serializers.DateField()
    expected_on = serializers.DateField(required=False, allow_null=True, default=None)


class PriceRequestFilterSerializer(serializers.Serializer[Any]):
    status = serializers.ChoiceField(choices=PriceRequestStatus.choices, required=False)
    search = serializers.CharField(required=False, default="", allow_blank=True, max_length=100)


def _suppliers(organization: Organization, ids: list[int], field: str) -> dict[int, Any]:
    found: dict[int, Any] = {}
    for supplier_id in ids:
        try:
            found[supplier_id] = partners.supplier_of(organization, supplier_id)
        except ObjectDoesNotExist:
            raise ValidationError({field: _("Fournisseur inconnu.")}) from None
    return found


class PriceRequestListView(PurchasingView, ListAPIView[PriceRequest]):
    serializer_class = PriceRequestSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[PriceRequest]:
        filters = PriceRequestFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.price_requests_of(
            self.organization, status=filters.validated_data.get("status"), search=filters.validated_data["search"]
        )

    @extend_schema(operation_id="listPriceRequests", parameters=[PriceRequestFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Price requests ("demandes de prix", D-289), newest first, paginated, with their lines and the suppliers'
        offers. Filter by status or `search` (number, product, supplier)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createPriceRequest", request=PriceRequestWriteSerializer, responses={201: PriceRequestSerializer}
    )
    def post(self, request: Request) -> Response:
        """Ask several suppliers for their prices on products and kilos. Errors on `suppliers`, `lines`,
        `lines.<index>.<field>`, `requested_on`. Owner or manager."""
        serializer = PriceRequestWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        organization = self.organization
        suppliers = _suppliers(organization, data["suppliers"], "suppliers")
        errors: dict[str, str] = {}
        lines: list[services.PriceRequestLineFields] = []
        for index, line in enumerate(data["lines"]):
            try:
                product = catalog.product_of(organization, line["product"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "product")] = _("Produit inconnu.")
                continue
            lines.append({"product": product, "quantity": line["quantity"]})
        if errors:
            raise ValidationError(errors)
        created = services.create_price_request(
            organization=organization,
            actor=self.membership.user,
            requested_on=data["requested_on"],
            lines=lines,
            suppliers=[suppliers[supplier_id] for supplier_id in data["suppliers"]],
            notes=data["notes"],
        )
        body = PriceRequestSerializer(selectors.price_request_of(organization, created.pk)).data
        return Response(body, status=status.HTTP_201_CREATED)


class PriceRequestView(PurchasingView):
    def price_request(self, request_id: int) -> PriceRequest:
        try:
            return selectors.price_request_of(self.organization, request_id)
        except PriceRequest.DoesNotExist:
            raise Http404 from None

    def answer(self, request_id: int) -> Response:
        return Response(PriceRequestSerializer(self.price_request(request_id)).data)


class PriceRequestDetailView(PriceRequestView):
    @extend_schema(operation_id="getPriceRequest", responses=PriceRequestSerializer)
    def get(self, request: Request, request_id: int) -> Response:
        return self.answer(request_id)


class PriceRequestOfferView(PriceRequestView):
    @extend_schema(operation_id="recordSupplierOffer", request=OfferWriteSerializer, responses=PriceRequestSerializer)
    def post(self, request: Request, request_id: int) -> Response:
        """Type a supplier's answer: a price per kg per request line (empty: not offered), their reference, the
        day it came and how long it holds. A supplier not asked yet is added. Replaces their earlier answer.
        Errors on `prices.<line id>`, `supplier`, `received_on`, `valid_until`. Only while the request is open."""
        serializer = OfferWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        price_request = self.price_request(request_id)
        supplier = _suppliers(self.organization, [data["supplier"]], "supplier")[data["supplier"]]
        services.record_offer(
            request=price_request,
            actor=self.membership.user,
            supplier=supplier,
            prices={row["request_line"]: row["unit_cost"] for row in data["prices"]},
            reference=data["reference"],
            received_on=data["received_on"],
            valid_until=data["valid_until"],
            notes=data["notes"],
        )
        return self.answer(request_id)


class PriceRequestOrderView(PriceRequestView):
    @extend_schema(
        operation_id="orderFromOffers", request=OrderFromOffersWriteSerializer, responses=PriceRequestSerializer
    )
    def post(self, request: Request, request_id: int) -> Response:
        """Turn the chosen offers into purchase orders, one per supplier: `choices` gives the supplier retained per
        request line; a line left out is not ordered. Refused (`choices.<line id>`) without a price from that
        supplier or when their offer is no longer valid. The request is then "commandée"."""
        serializer = OrderFromOffersWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        price_request = self.price_request(request_id)
        ids = sorted({row["supplier"] for row in data["choices"]})
        suppliers = _suppliers(self.organization, ids, "choices")
        services.order_from_offers(
            request=price_request,
            actor=self.membership.user,
            choices={row["request_line"]: suppliers[row["supplier"]] for row in data["choices"]},
            ordered_on=data["ordered_on"],
            expected_on=data["expected_on"],
        )
        return self.answer(request_id)


class PriceRequestCancelView(PriceRequestView):
    @extend_schema(operation_id="cancelPriceRequest", request=None, responses=PriceRequestSerializer)
    def post(self, request: Request, request_id: int) -> Response:
        """Give up a price request still open: nothing is ordered."""
        services.cancel_price_request(request=self.price_request(request_id), actor=self.membership.user)
        return self.answer(request_id)
