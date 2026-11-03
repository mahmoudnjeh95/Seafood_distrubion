from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.permissions import IsMember, IsOwnerOrManager, membership_of
from apps.purchasing import selectors as purchasing

from .. import selectors, services
from .serializers import (
    MarkReadSerializer,
    NotificationListSerializer,
    PaymentOrderNoticeSerializer,
    RecipientSerializer,
    UnreadSerializer,
)


class MyNotificationsView(APIView):
    """What the office or a driver is told (D-175): both apps ask for it every few seconds."""

    permission_classes = (IsMember,)

    @extend_schema(operation_id="listMyNotifications", responses=NotificationListSerializer)
    def get(self, request: Request) -> Response:
        """The newest notifications of the logged-in person, newest first, and how many they have not read."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        answer = {"unread": selectors.unread_count(membership), "results": selectors.latest_for(membership)}
        return Response(NotificationListSerializer(answer).data)


class MyNotificationsReadView(APIView):
    permission_classes = (IsMember,)

    @extend_schema(operation_id="markMyNotificationsRead", request=MarkReadSerializer, responses=UnreadSerializer)
    def post(self, request: Request) -> Response:
        """Some notifications (`ids`), or all of them (`all`), are read by the logged-in person."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = MarkReadSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ids = None if serializer.validated_data["all"] else serializer.validated_data["ids"]
        unread = services.mark_read(membership=membership, ids=ids)
        return Response(UnreadSerializer({"unread": unread}).data)


class NoticeRecipientsView(APIView):
    permission_classes = (IsOwnerOrManager,)

    @extend_schema(operation_id="listNoticeRecipients", responses=RecipientSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The people a payment order can be sent to: the active owners and managers (D-255)."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        return Response(RecipientSerializer(selectors.office_recipients(membership.organization), many=True).data)


class PaymentOrderNoticeView(APIView):
    permission_classes = (IsOwnerOrManager,)

    @extend_schema(operation_id="notifyPaymentOrder", request=PaymentOrderNoticeSerializer, responses={204: None})
    def post(self, request: Request, plan_line_id: int) -> Response:
        """Tell one person about a payment order (a planned payment to a supplier, D-192): they see it in their bell
        and it opens the supplier règlements."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = PaymentOrderNoticeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            line = purchasing.plan_line_of(membership.organization, plan_line_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        recipient = (
            selectors.office_recipients(membership.organization)
            .filter(user_id=serializer.validated_data["recipient"])
            .first()
        )
        if recipient is None:
            raise ValidationError({"recipient": _("Choisissez un propriétaire ou un gérant.")})
        services.tell_person(
            organization=membership.organization,
            actor=membership.user,
            recipient=recipient.user,
            kind="payment_order",
            params={
                "supplier": line.invoice.supplier.name,
                "invoice": line.invoice.number,
                "amount": f"{line.amount:.3f}",
                "date": line.planned_on.isoformat(),
                "sender": membership.user.get_full_name() or membership.user.username,
            },
            link="/achats/reglements",
        )
        return Response(status=status.HTTP_204_NO_CONTENT)
