from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.pagination import PagedList
from apps.core.models import Membership, Organization
from apps.core.permissions import ReadOwnerOrAccountantWriteOwner, membership_of
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.partnerships import selectors, services
from apps.partnerships.models import LotPartnership

from .serializers import (
    LotPartnershipAdvanceSerializer,
    LotPartnershipCancelSerializer,
    LotPartnershipDetailSerializer,
    LotPartnershipFilterSerializer,
    LotPartnershipSerializer,
    LotPartnershipUpdateSerializer,
    LotPartnershipWriteSerializer,
)


# A partner's capital and share are the owner's business (D-060): the owner reads and writes, the
# accountant reads, managers and drivers get 403 (provisional). Rows of the user's organization only.
# A comment, not a docstring: a docstring would describe every endpoint in the schema.
class PartnershipView(APIView):
    permission_classes = (ReadOwnerOrAccountantWriteOwner,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization

    def partnership(self, partnership_id: int) -> LotPartnership:
        try:
            return selectors.partnership_of(self.organization, partnership_id)
        except LotPartnership.DoesNotExist:
            raise Http404 from None

    def answer(self, partnership_id: int, status_code: int = status.HTTP_200_OK) -> Response:
        partnership = self.partnership(partnership_id)
        context = {"has_sold": services.has_sold(self.organization, batch_id=partnership.batch_id)}
        return Response(LotPartnershipDetailSerializer(partnership, context=context).data, status=status_code)


def _partner(organization: Organization, partner_id: int) -> Any:
    try:
        return partners.supplier_of(organization, partner_id)
    except ObjectDoesNotExist:
        raise DjangoValidationError({"partner": _("Fournisseur inconnu.")}) from None


class LotPartnershipListView(PartnershipView, ListAPIView[LotPartnership]):
    serializer_class = LotPartnershipSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[LotPartnership]:
        filters = LotPartnershipFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        return selectors.partnerships_of(
            self.organization,
            status=data.get("status"),
            partner_id=data.get("partner"),
            batch_id=data.get("batch"),
            search=data["search"],
        )

    @extend_schema(operation_id="listPartnerships", parameters=[LotPartnershipFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Partnership lots, newest first, paginated (`limit`, `offset`), each with the partner's capital
        now. Cancelled ones only when asked for by `status`. Filter by partner, lot, or `search`."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createPartnership",
        request=LotPartnershipWriteSerializer,
        responses={201: LotPartnershipDetailSerializer},
    )
    def post(self, request: Request) -> Response:
        """Put a lot in partnership with one supplier (owner only): at receipt or on an open lot before its
        first sale. One partner per lot; the partner's capital opens their capital ledger in this lot."""
        serializer = LotPartnershipWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        try:
            batch = inventory.batch_of(self.organization, data.pop("batch"))
        except ObjectDoesNotExist:
            raise DjangoValidationError({"batch": _("Lot inconnu.")}) from None
        partner = _partner(self.organization, data.pop("partner"))
        partnership = services.create_partnership(
            organization=self.organization, actor=self.membership.user, batch=batch, partner=partner, **data
        )
        return self.answer(partnership.pk, status.HTTP_201_CREATED)


class LotPartnershipDetailView(PartnershipView):
    @extend_schema(operation_id="getPartnership", responses=LotPartnershipDetailSerializer)
    def get(self, request: Request, partnership_id: int) -> Response:
        """One partnership with the partner's capital ledger in this lot."""
        return self.answer(partnership_id)

    @extend_schema(
        operation_id="updatePartnership",
        request=LotPartnershipUpdateSerializer,
        responses=LotPartnershipDetailSerializer,
    )
    def patch(self, request: Request, partnership_id: int) -> Response:
        """Change the terms (owner only) while the partnership is open and the lot not sold yet. A changed
        partner capital posts a correction on the ledger."""
        partnership = self.partnership(partnership_id)
        serializer = LotPartnershipUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        if "partner" in data:
            data["partner"] = _partner(self.organization, data["partner"])
        services.update_partnership(partnership=partnership, actor=self.membership.user, **data)
        return self.answer(partnership_id)


class LotPartnershipCancelView(PartnershipView):
    @extend_schema(
        operation_id="cancelPartnership",
        request=LotPartnershipCancelSerializer,
        responses=LotPartnershipDetailSerializer,
    )
    def post(self, request: Request, partnership_id: int) -> Response:
        """Cancel a partnership set by mistake, before the lot's first sale (owner only, reason required).
        The capital still in goes back to the partner."""
        partnership = self.partnership(partnership_id)
        serializer = LotPartnershipCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.cancel_partnership(
            partnership=partnership, actor=self.membership.user, reason=serializer.validated_data["reason"]
        )
        return self.answer(partnership_id)


class LotPartnershipAdvanceView(PartnershipView):
    @extend_schema(
        operation_id="advancePartnerCapital",
        request=LotPartnershipAdvanceSerializer,
        responses=LotPartnershipDetailSerializer,
    )
    def post(self, request: Request, partnership_id: int) -> Response:
        """Pay the partner an advance from the capital they put in this lot (owner only). Up to the capital
        still in; the settlement pays the rest."""
        partnership = self.partnership(partnership_id)
        serializer = LotPartnershipAdvanceSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.advance_capital(partnership=partnership, actor=self.membership.user, **serializer.validated_data)
        return self.answer(partnership_id)
