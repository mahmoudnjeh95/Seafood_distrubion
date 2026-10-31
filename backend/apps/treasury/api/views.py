"""Treasury: the banks list and the effets (D-196, P9-T01).

Office data: the owner and the manager write, the accountant reads, drivers get 403.
"""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.db.models import QuerySet
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.pagination import PagedList
from apps.core.models import Membership, Organization
from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of

from .. import selectors, services
from ..models import Instrument
from .serializers import (
    BankFilterSerializer,
    BankSerializer,
    BankWriteSerializer,
    InstrumentFilterSerializer,
    InstrumentSerializer,
)


class OfficeView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization


class BankListView(OfficeView):
    @extend_schema(operation_id="listBanks", parameters=[BankFilterSerializer], responses=BankSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The banks an effet may be drawn on, in the list's order; `active_only=false` adds those taken off."""
        filters = BankFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        banks = selectors.banks_of(self.organization, active_only=filters.validated_data["active_only"])
        return Response(BankSerializer(banks, many=True).data)

    @extend_schema(operation_id="createBank", request=BankWriteSerializer, responses={201: BankSerializer})
    def post(self, request: Request) -> Response:
        """Add a bank to the list (owner or manager): its short name (sigle) and its name."""
        serializer = BankWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = services.create_bank(
            organization=self.organization,
            actor=self.membership.user,
            code=serializer.validated_data["code"],
            name=serializer.validated_data["name"],
        )
        return Response(BankSerializer(bank).data, status=status.HTTP_201_CREATED)


class BankDetailView(OfficeView):
    @extend_schema(operation_id="updateBank", request=BankWriteSerializer, responses=BankSerializer)
    def put(self, request: Request, bank_id: int) -> Response:
        """Rename a bank, or take it off the lists (`is_active` false); effets already drawn on it keep it."""
        try:
            bank = selectors.bank_of(self.organization, bank_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        serializer = BankWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        bank = services.update_bank(
            bank=bank,
            actor=self.membership.user,
            code=serializer.validated_data["code"],
            name=serializer.validated_data["name"],
            is_active=serializer.validated_data["is_active"],
        )
        return Response(BankSerializer(bank).data)


class InstrumentListView(OfficeView, ListAPIView[Instrument]):
    serializer_class = InstrumentSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Instrument]:
        filters = InstrumentFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        data: dict[str, Any] = filters.validated_data
        return selectors.instruments_of(
            self.organization,
            direction=data.get("direction"),
            kind=data.get("kind"),
            statuses=data["status"],
            customer_id=data.get("customer"),
            supplier_id=data.get("supplier"),
            due_from=data.get("due_from"),
            due_to=data.get("due_to"),
            search=data["search"],
        )

    @extend_schema(operation_id="listInstruments", parameters=[InstrumentFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Cheques and traites, received and issued, soonest due first, paginated. Filter by direction, kind,
        status (comma separated), customer, supplier, due days (inclusive) or `search` (number, drawer, règlement,
        party)."""
        return super().get(request, *args, **kwargs)
