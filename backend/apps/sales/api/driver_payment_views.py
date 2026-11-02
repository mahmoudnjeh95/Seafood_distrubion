"""Customer payments collected by a driver on the road (P3-T11, D-111)."""

from django.core.exceptions import ObjectDoesNotExist
from django.utils import timezone
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.clock import moment_from_phone
from apps.core.permissions import IsDriver, membership_of
from apps.dayclose import selectors as dayclose
from apps.partners import selectors as partners
from apps.sales import selectors, services

from .driver_payment_serializers import CashLimitSerializer, RoadPaymentSerializer, RoadPaymentWriteSerializer


class MyCashLimitView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="getMyCashLimit", responses=CashLimitSerializer)
    def get(self, request: Request) -> Response:
        """The amount from which a cash collection needs the driver's confirmation (D-273, D-280): the phone asks
        before sending, and keeps the answer for when it has no connection."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        limit = selectors.cash_limit_on(membership.organization, timezone.localdate())
        return Response(CashLimitSerializer({"cash_limit": limit}).data)


class MyPaymentsView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="listMyPayments", responses=RoadPaymentSerializer(many=True))
    def get(self, request: Request) -> Response:
        """What the driver collected from customers today, newest first."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        rows = selectors.payments_received_by(
            membership.organization, user_id=membership.user_id, day=timezone.localdate()
        )
        return Response(RoadPaymentSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="collectMyPayment", request=RoadPaymentWriteSerializer, responses={201: RoadPaymentSerializer}
    )
    def post(self, request: Request) -> Response:
        """Record money a customer handed over today. It settles their oldest open sales first, and counts in
        the day's cash when it is cash. The same `client_uuid` sent twice records it once."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = RoadPaymentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        made_at = moment_from_phone(data["made_at"], field="made_at")
        dayclose.refuse_sale_outside_day(membership, made_at)
        try:
            customer = partners.customer_of(membership.organization, data["customer"])
        except ObjectDoesNotExist:
            return Response({"customer": ["Client inconnu."]}, status=status.HTTP_400_BAD_REQUEST)
        payment = services.record_customer_payment(
            organization=membership.organization,
            actor=membership.user,
            customer=customer,
            amount=data["amount"],
            method=data["method"],
            client_uuid=data["client_uuid"],
            made_at=made_at,
            confirm_cash_limit=data["confirm_cash_limit"],
        )
        return Response(RoadPaymentSerializer(payment).data, status=status.HTTP_201_CREATED)
