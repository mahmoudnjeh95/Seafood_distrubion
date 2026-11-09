"""Lot recall (D-302): who received a lot's kilos, and where the rest still is."""

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.http import Http404
from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.request import Request
from rest_framework.response import Response

from apps.inventory import selectors as inventory
from apps.sales import selectors

from .views import OfficeView


class RecallCustomerSerializer(serializers.Serializer[Any]):
    customer_id = serializers.IntegerField(read_only=True)
    customer_name = serializers.CharField(read_only=True)
    phone = serializers.CharField(read_only=True)
    city = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)
    first_on = serializers.DateField(read_only=True)
    last_on = serializers.DateField(read_only=True)
    sales = serializers.ListField(child=serializers.CharField(), read_only=True)


class RecallStockSerializer(serializers.Serializer[Any]):
    location_id = serializers.IntegerField(read_only=True)
    location_name = serializers.CharField(read_only=True)
    quantity = serializers.DecimalField(max_digits=12, decimal_places=3, read_only=True)


class LotRecallSerializer(serializers.Serializer[Any]):
    batch_id = serializers.IntegerField(read_only=True)
    batch_number = serializers.CharField(read_only=True)
    product_name = serializers.CharField(read_only=True)
    scientific_name = serializers.CharField(read_only=True)
    supplier_name = serializers.CharField(read_only=True)
    health_approval = serializers.CharField(read_only=True)
    received_on = serializers.DateField(read_only=True)
    use_by = serializers.DateField(read_only=True, allow_null=True)
    catch_area = serializers.CharField(read_only=True)
    production_method = serializers.CharField(read_only=True)
    origin = serializers.CharField(read_only=True)
    customers = RecallCustomerSerializer(many=True, read_only=True)
    in_stock = RecallStockSerializer(many=True, read_only=True)


class LotRecallView(OfficeView):
    @extend_schema(operation_id="getLotRecall", responses=LotRecallSerializer)
    def get(self, request: Request, batch_id: int) -> Response:
        """A recall sheet for one lot: its origin, the customers who kept kilos of it (the most first, with their
        phone and BL), and the places that still hold some."""
        try:
            batch = inventory.batch_of(self.organization, batch_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        stock = [
            {"location_id": row.location_id, "location_name": row.location.name, "quantity": row.quantity}
            for row in inventory.on_hand_of(self.organization, batch_id=batch.pk)
        ]
        body = {
            "batch_id": batch.pk,
            "batch_number": batch.number,
            "product_name": batch.product.name,
            "scientific_name": batch.product.scientific_name,
            "supplier_name": batch.supplier.name,
            "health_approval": batch.supplier.health_approval,
            "received_on": batch.received_on,
            "use_by": batch.use_by,
            "catch_area": batch.catch_area,
            "production_method": batch.production_method,
            "origin": batch.origin,
            "customers": [vars(row) for row in selectors.recall_customers(self.organization, batch_id=batch.pk)],
            "in_stock": stock,
        }
        return Response(LotRecallSerializer(body).data)
