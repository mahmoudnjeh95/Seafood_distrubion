from typing import Any

from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.permissions import BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import access
from apps.core.permissions import membership_of
from apps.search import selectors


class OfficePerson(BasePermission):
    """Anyone of the office, whatever their role (custom roles included); drivers 403. What each person finds is
    then cut to the sections they may read."""

    def has_permission(self, request: Request, view: APIView) -> bool:
        membership = membership_of(request)
        return membership is not None and access.is_office(membership)


class SearchQuerySerializer(serializers.Serializer[Any]):
    q = serializers.CharField(max_length=100, allow_blank=True)


class SearchHitSerializer(serializers.Serializer[Any]):
    kind = serializers.ChoiceField(choices=sorted(selectors.KIND_SECTIONS), read_only=True)
    id = serializers.IntegerField(read_only=True)
    title = serializers.CharField(source="label", read_only=True)
    detail = serializers.CharField(read_only=True)


class SearchView(APIView):
    permission_classes: tuple[type[BasePermission], ...] = (OfficePerson,)

    @extend_schema(
        operation_id="searchEverything", parameters=[SearchQuerySerializer], responses=SearchHitSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Customers, suppliers, products, lots, BL and invoices matching `q` (D-330), at most five of each, only of
        the sections the person may read. Fewer than two characters: nothing."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        query = SearchQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        kinds = {
            kind
            for kind, section in selectors.KIND_SECTIONS.items()
            if access.can(membership, section, access.Level.READ)
        }
        hits = selectors.search(membership.organization, query.validated_data["q"], kinds=kinds)
        return Response(SearchHitSerializer([vars(hit) for hit in hits], many=True).data)
