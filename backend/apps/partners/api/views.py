from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.models import Membership, Organization
from apps.core.permissions import IsDriver, ReadOfficeWriteOwnerOrManager, membership_of
from apps.fleet import selectors as fleet
from apps.partners import selectors, services
from apps.partners.models import Customer, Supplier
from apps.sales import selectors as sales

from .serializers import (
    CustomerChoiceSerializer,
    CustomerFilterSerializer,
    CustomerLocationSerializer,
    CustomerSerializer,
    CustomerWriteSerializer,
    MyCustomerWriteSerializer,
    SupplierFilterSerializer,
    SupplierSerializer,
    SupplierWriteSerializer,
)


# Base of the supplier views: every row is read inside the user's organization (D-022). Drivers get 403.
# A comment, not a docstring: a docstring would become the description of every endpoint in the schema.
class SupplierView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization

    def supplier(self, supplier_id: int) -> Supplier:
        try:
            return selectors.supplier_of(self.organization, supplier_id)
        except Supplier.DoesNotExist:
            raise Http404 from None

    def supplier_answer(self, supplier_id: int, status_code: int = status.HTTP_200_OK) -> Response:
        # Read again so the answer carries the contacts as saved.
        return Response(SupplierSerializer(self.supplier(supplier_id)).data, status=status_code)


class SupplierListView(SupplierView):
    @extend_schema(
        operation_id="listSuppliers", parameters=[SupplierFilterSerializer], responses=SupplierSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Suppliers sorted by name, with their contacts. Archived ones only when asked (`status`). Not
        paginated: the company works with a handful of suppliers (D-032)."""
        filters = SupplierFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        suppliers = selectors.suppliers_of(
            self.organization, search=filters.validated_data["search"], status=filters.validated_data["status"]
        )
        return Response(SupplierSerializer(suppliers, many=True).data)

    @extend_schema(operation_id="createSupplier", request=SupplierWriteSerializer, responses={201: SupplierSerializer})
    def post(self, request: Request) -> Response:
        """A new supplier. Without a reference it gets the next free `F-NNN`."""
        serializer = SupplierWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        supplier = services.create_supplier(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return self.supplier_answer(supplier.pk, status.HTTP_201_CREATED)


class SupplierDetailView(SupplierView):
    @extend_schema(operation_id="getSupplier", responses=SupplierSerializer)
    def get(self, request: Request, supplier_id: int) -> Response:
        return self.supplier_answer(supplier_id)

    @extend_schema(operation_id="updateSupplier", request=SupplierWriteSerializer, responses=SupplierSerializer)
    def patch(self, request: Request, supplier_id: int) -> Response:
        """Change a supplier. `contacts`, when sent, replaces the whole list."""
        supplier = self.supplier(supplier_id)
        serializer = SupplierWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_supplier(supplier=supplier, actor=self.membership.user, **serializer.validated_data)
        return self.supplier_answer(supplier_id)


class SupplierArchiveView(SupplierView):
    @extend_schema(operation_id="archiveSupplier", request=None, responses=SupplierSerializer)
    def post(self, request: Request, supplier_id: int) -> Response:
        """Archived suppliers keep their history but can no longer be bought from."""
        services.set_supplier_active(supplier=self.supplier(supplier_id), actor=self.membership.user, is_active=False)
        return self.supplier_answer(supplier_id)


class SupplierRestoreView(SupplierView):
    @extend_schema(operation_id="restoreSupplier", request=None, responses=SupplierSerializer)
    def post(self, request: Request, supplier_id: int) -> Response:
        services.set_supplier_active(supplier=self.supplier(supplier_id), actor=self.membership.user, is_active=True)
        return self.supplier_answer(supplier_id)


# Base of the customer views: office data like suppliers (D-032, D-047); drivers get 403.
class CustomerView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization

    def customer(self, customer_id: int) -> Customer:
        try:
            return selectors.customer_of(self.organization, customer_id)
        except Customer.DoesNotExist:
            raise Http404 from None

    def customer_answer(self, customer_id: int, status_code: int = status.HTTP_200_OK) -> Response:
        return Response(CustomerSerializer(self.customer(customer_id)).data, status=status_code)


class CustomerListView(CustomerView):
    @extend_schema(
        operation_id="listCustomers", parameters=[CustomerFilterSerializer], responses=CustomerSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Customers sorted by name, with their contacts. Archived ones only when asked (`status`); `kind`
        keeps one type. Not paginated (D-047)."""
        filters = CustomerFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        customers = selectors.customers_of(
            self.organization,
            search=filters.validated_data["search"],
            status=filters.validated_data["status"],
            kind=filters.validated_data.get("kind", ""),
        )
        return Response(CustomerSerializer(customers, many=True).data)

    @extend_schema(operation_id="createCustomer", request=CustomerWriteSerializer, responses={201: CustomerSerializer})
    def post(self, request: Request) -> Response:
        """A new customer. Without a reference it gets the next free `C-NNN`."""
        serializer = CustomerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        customer = services.create_customer(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return self.customer_answer(customer.pk, status.HTTP_201_CREATED)


class CustomerDetailView(CustomerView):
    @extend_schema(operation_id="getCustomer", responses=CustomerSerializer)
    def get(self, request: Request, customer_id: int) -> Response:
        return self.customer_answer(customer_id)

    @extend_schema(operation_id="updateCustomer", request=CustomerWriteSerializer, responses=CustomerSerializer)
    def patch(self, request: Request, customer_id: int) -> Response:
        """Change a customer. `contacts`, when sent, replaces the whole list."""
        customer = self.customer(customer_id)
        serializer = CustomerWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_customer(customer=customer, actor=self.membership.user, **serializer.validated_data)
        return self.customer_answer(customer_id)


class CustomerLocationView(CustomerView):
    @extend_schema(operation_id="setCustomerLocation", request=CustomerLocationSerializer, responses=CustomerSerializer)
    def put(self, request: Request, customer_id: int) -> Response:
        """Save where the customer is (owner or manager), from a stop of a driver's route; empty values forget it."""
        serializer = CustomerLocationSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_customer_location(
            customer=self.customer(customer_id), actor=self.membership.user, **serializer.validated_data
        )
        return self.customer_answer(customer_id)


class CustomerArchiveView(CustomerView):
    @extend_schema(operation_id="archiveCustomer", request=None, responses=CustomerSerializer)
    def post(self, request: Request, customer_id: int) -> Response:
        """Archived customers keep their history but can no longer be sold to. The walk-in one cannot be archived."""
        services.set_customer_active(customer=self.customer(customer_id), actor=self.membership.user, is_active=False)
        return self.customer_answer(customer_id)


class CustomerRestoreView(CustomerView):
    @extend_schema(operation_id="restoreCustomer", request=None, responses=CustomerSerializer)
    def post(self, request: Request, customer_id: int) -> Response:
        services.set_customer_active(customer=self.customer(customer_id), actor=self.membership.user, is_active=True)
        return self.customer_answer(customer_id)


class MyCustomersView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(
        operation_id="listMyCustomers",
        parameters=[CustomerFilterSerializer],
        responses=CustomerChoiceSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Active customers for a driver to sell to (name and city only, never what they owe: D-197): the ones
        they sold to lately first, the walk-in customer last. Filter with `search`. At most 30 rows. When today's
        load of the driver's truck names clients, only those clients and the walk-in customer are listed (D-174)."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        filters = CustomerFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        found = list(selectors.customers_of(membership.organization, search=filters.validated_data["search"]))
        truck = fleet.truck_of_driver(membership)
        loaded_for = (
            set(
                sales.load_customer_ids(
                    membership.organization, location_id=truck.location_id, day=timezone.localdate()
                )
            )
            if truck is not None
            else set()
        )
        if loaded_for:
            found = [customer for customer in found if customer.pk in loaded_for or customer.is_walk_in]
        # The ones this driver sold to lately come first, then the others by name; the walk-in customer last.
        recent = sales.recent_customer_ids(membership.organization, user_id=membership.user_id)
        rank = {customer_id: position for position, customer_id in enumerate(recent)}
        found.sort(key=lambda customer: (customer.is_walk_in, rank.get(customer.pk, len(rank)), customer.name))
        rows = [
            {
                "id": customer.pk,
                "name": customer.name,
                "city": customer.city,
                "is_walk_in": customer.is_walk_in,
                "on_load": customer.pk in loaded_for,
            }
            for customer in found[:30]
        ]
        return Response(CustomerChoiceSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="createMyCustomer",
        request=MyCustomerWriteSerializer,
        responses={201: CustomerChoiceSerializer},
    )
    def post(self, request: Request) -> Response:
        """A driver adds a customer they sell to, with a name and optionally a phone and a city. Its credit limit
        is zero, cash only, until the office sets one. A name an active customer already has is refused."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = MyCustomerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        name = data["name"].strip()
        if not name:
            raise ValidationError({"name": _("Indiquez le nom du client.")})
        if selectors.customers_of(membership.organization).filter(name__iexact=name).exists():
            raise ValidationError({"name": _("Un client porte déjà ce nom : choisissez-le dans la liste.")})
        customer = services.create_customer(
            organization=membership.organization,
            actor=membership.user,
            name=name,
            phone=data["phone"].strip(),
            city=data["city"].strip(),
        )
        row = {
            "id": customer.pk,
            "name": customer.name,
            "city": customer.city,
            "is_walk_in": False,
            "on_load": False,
        }
        return Response(CustomerChoiceSerializer(row).data, status=status.HTTP_201_CREATED)
