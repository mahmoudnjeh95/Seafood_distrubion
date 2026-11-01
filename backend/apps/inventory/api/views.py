from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import FileResponse, Http404
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.parsers import MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors as catalog
from apps.core.api.pagination import PagedList
from apps.core.clock import moment_from_phone
from apps.core.models import Membership, Organization, Role
from apps.core.permissions import IsDriver, ReadOfficeWriteOwnerOrManager, membership_of
from apps.dayclose import selectors as dayclose
from apps.fleet import selectors as fleet
from apps.inventory import selectors, services
from apps.inventory.models import Batch, StockCount, StockLocation, StockLoss, Transfer
from apps.partners import selectors as partners

from .serializers import (
    BatchFilterSerializer,
    BatchSerializer,
    CountedSerializer,
    CountFilterSerializer,
    CountSerializer,
    CountWriteSerializer,
    LocationBatchSerializer,
    LocationStockSerializer,
    LossDetailSerializer,
    LossFilterSerializer,
    LossPhotoSerializer,
    LossRejectSerializer,
    LossSerializer,
    LossWriteSerializer,
    MyStockFilterSerializer,
    MyStockLineSerializer,
    ProductStockDetailSerializer,
    RoadLossSerializer,
    RoadLossWriteSerializer,
    RoadReturnSerializer,
    StockLocationCreateSerializer,
    StockLocationFilterSerializer,
    StockLocationSerializer,
    StockLocationUpdateSerializer,
    StockMovementFilterSerializer,
    StockMovementSerializer,
    StockOverviewSerializer,
    StockSettingsSerializer,
    StockSettingsWriteSerializer,
    TransferDetailSerializer,
    TransferFilterSerializer,
    TransferSerializer,
    TransferWriteSerializer,
    TruckDayFilterSerializer,
    TruckDaySerializer,
    VatProductsSerializer,
)


# Rows of the user's organization only (D-022); drivers get 403 and read their own truck from `/me`.
# A comment, not a docstring: a docstring would describe every endpoint in the schema.
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


class LocationView(OfficeView):
    def location(self, location_id: int) -> StockLocation:
        try:
            return selectors.location_of(self.organization, location_id)
        except StockLocation.DoesNotExist:
            raise Http404 from None

    def standalone_location(self, location_id: int) -> StockLocation:
        """A location changed on its own: a truck's location changes through its truck."""
        location = self.location(location_id)
        if location.kind not in selectors.STANDALONE_KINDS:
            raise ValidationError(_("Un camion se modifie depuis la liste des camions."))
        return location


class LocationListView(LocationView):
    @extend_schema(
        operation_id="listLocations",
        parameters=[StockLocationFilterSerializer],
        responses=StockLocationSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Cold rooms, trucks and other locations, sorted by kind then name. Archived ones only when asked."""
        filters = StockLocationFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        kind = filters.validated_data.get("kind")
        locations = selectors.locations_of(
            self.organization, kinds=[kind] if kind else None, status=filters.validated_data["status"]
        )
        return Response(StockLocationSerializer(locations, many=True).data)

    @extend_schema(
        operation_id="createLocation",
        request=StockLocationCreateSerializer,
        responses={201: StockLocationSerializer},
    )
    def post(self, request: Request) -> Response:
        """A new cold room or other location. A truck is created with `createTruck`."""
        serializer = StockLocationCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        location = services.create_location(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return Response(StockLocationSerializer(location).data, status=status.HTTP_201_CREATED)


class LocationDetailView(LocationView):
    @extend_schema(operation_id="getLocation", responses=StockLocationSerializer)
    def get(self, request: Request, location_id: int) -> Response:
        return Response(StockLocationSerializer(self.location(location_id)).data)

    @extend_schema(
        operation_id="updateLocation", request=StockLocationUpdateSerializer, responses=StockLocationSerializer
    )
    def patch(self, request: Request, location_id: int) -> Response:
        """Rename a cold room or other location, or change whether it sells at the counter."""
        location = self.standalone_location(location_id)
        serializer = StockLocationUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        location = services.update_location(location=location, actor=self.membership.user, **serializer.validated_data)
        return Response(StockLocationSerializer(location).data)


class LocationArchiveView(LocationView):
    @extend_schema(operation_id="archiveLocation", request=None, responses=StockLocationSerializer)
    def post(self, request: Request, location_id: int) -> Response:
        """An archived location keeps its history but receives no more stock."""
        location = services.set_location_active(
            location=self.standalone_location(location_id), actor=self.membership.user, is_active=False
        )
        return Response(StockLocationSerializer(location).data)


class LocationRestoreView(LocationView):
    @extend_schema(operation_id="restoreLocation", request=None, responses=StockLocationSerializer)
    def post(self, request: Request, location_id: int) -> Response:
        location = services.set_location_active(
            location=self.standalone_location(location_id), actor=self.membership.user, is_active=True
        )
        return Response(StockLocationSerializer(location).data)


class BatchListView(OfficeView, ListAPIView[Batch]):
    serializer_class = BatchSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Batch]:
        filters = BatchFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.batches_of(
            self.organization,
            product_id=filters.validated_data.get("product"),
            supplier_id=filters.validated_data.get("supplier"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listBatches", parameters=[BatchFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Batches, newest receipt first, paginated (`limit`, `offset`). Filter by product or supplier;
        `search` matches the batch number, the supplier's receipt reference, product and supplier.
        Batches are created by goods receipts, not here."""
        return super().get(request, *args, **kwargs)


class BatchDetailView(OfficeView):
    @extend_schema(operation_id="getBatch", responses=BatchSerializer)
    def get(self, request: Request, batch_id: int) -> Response:
        try:
            batch = selectors.batch_of(self.organization, batch_id)
        except Batch.DoesNotExist:
            raise Http404 from None
        return Response(BatchSerializer(batch).data)


class LocationStockView(LocationView):
    @extend_schema(operation_id="listLocationStock", responses=LocationStockSerializer(many=True))
    def get(self, request: Request, location_id: int) -> Response:
        """What a location holds now per product, all batches together, by product name."""
        location = self.location(location_id)
        rows = selectors.location_stock(self.organization, location_id=location.pk)
        return Response(LocationStockSerializer(rows, many=True).data)


class LocationBatchesView(LocationView):
    @extend_schema(operation_id="listLocationBatches", responses=LocationBatchSerializer(many=True))
    def get(self, request: Request, location_id: int, product_id: int) -> Response:
        """The lots of one product at this location, oldest first: to pick one by hand on a sale (D-121)."""
        location = self.location(location_id)
        rows = selectors.location_batches(self.organization, product_id=product_id, location_id=location.pk)
        return Response(LocationBatchSerializer(rows, many=True).data)


class ProductBatchesView(OfficeView):
    @extend_schema(operation_id="listProductBatches", responses=LocationBatchSerializer(many=True))
    def get(self, request: Request, product_id: int) -> Response:
        """The lots of one product in every cold room, oldest first: to pick one on a quote or a sale (D-201)."""
        rows = selectors.product_batches(self.organization, product_id=product_id)
        return Response(LocationBatchSerializer(rows, many=True).data)


class VatProductsView(OfficeView):
    @extend_schema(operation_id="listVatProducts", responses=VatProductsSerializer)
    def get(self, request: Request) -> Response:
        """The ids of the products with kilos in stock bought with VAT: the quote and sale forms flag them (D-202)."""
        return Response(VatProductsSerializer({"products": selectors.vat_product_ids(self.organization)}).data)


# ---- Transfers (P1-T09) ----


def _transfer_fields(organization: Organization, data: dict[str, Any]) -> dict[str, Any]:
    """The ids of a transfer replaced by the rows they name in the organization; unknown ids are field errors."""
    errors: dict[str, str] = {}
    places: dict[str, StockLocation] = {}
    for field in ("from_location", "to_location"):
        try:
            places[field] = selectors.location_of(organization, data[field])
        except StockLocation.DoesNotExist:
            errors[field] = _("Emplacement inconnu.")
    lines = _transfer_lines(organization, data["lines"], errors)
    deliveries = []
    for index, delivery in enumerate(data["deliveries"]):
        prefix = f"deliveries.{index}."
        try:
            customer = partners.customer_of(organization, delivery["customer"])
        except ObjectDoesNotExist:
            errors[f"{prefix}customer"] = _("Client inconnu.")
            continue
        part_lines = _transfer_lines(organization, delivery["lines"], errors, prefix)
        deliveries.append({**delivery, "customer": customer, "lines": part_lines})
    if errors:
        raise ValidationError(errors)
    fields = {key: value for key, value in data.items() if key != "validate_now"}
    return {**fields, **places, "lines": lines, "deliveries": deliveries, "validate": data["validate_now"]}


def _transfer_lines(
    organization: Organization, rows: list[dict[str, Any]], errors: dict[str, str], prefix: str = ""
) -> list[dict[str, Any]]:
    """The lines of a transfer (or of a client's part) with their product rows; unknown products are errors."""
    lines = []
    for index, line in enumerate(rows):
        try:
            product = catalog.product_of(organization, line["product"])
        except ObjectDoesNotExist:
            errors[prefix + services.line_error_key(index, "product")] = _("Produit inconnu.")
            continue
        picks = []
        for pick in line.get("picks") or []:
            try:
                batch = selectors.batch_of(organization, pick["batch"])
            except ObjectDoesNotExist:
                errors[prefix + services.line_error_key(index, "picks")] = _("Lot inconnu.")
                break
            picks.append({"batch": batch, "quantity": pick["quantity"]})
        lines.append({**line, "product": product, "picks": picks})
    return lines


def _transfer_answer(
    organization: Organization, transfer_id: int, *, status_code: int = status.HTTP_200_OK
) -> Response:
    transfer = selectors.transfer_of(organization, transfer_id)
    movements = selectors.movements_from_sources(list(transfer.lines.all()))
    return Response(TransferDetailSerializer(transfer, context={"movements": movements}).data, status=status_code)


class TransferView(OfficeView):
    def transfer(self, transfer_id: int) -> Transfer:
        try:
            return selectors.transfer_of(self.organization, transfer_id)
        except Transfer.DoesNotExist:
            raise Http404 from None


class TransferListView(TransferView, ListAPIView[Transfer]):
    serializer_class = TransferSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Transfer]:
        filters = TransferFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.transfers_of(
            self.organization,
            kind=filters.validated_data.get("kind"),
            status=filters.validated_data.get("status"),
            location_id=filters.validated_data.get("location"),
            date_from=filters.validated_data.get("date_from"),
            date_to=filters.validated_data.get("date_to"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listTransfers", parameters=[TransferFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Transfers (truck loads, evening returns, moves between cold rooms), newest day first, paginated
        (`limit`, `offset`). Filter by kind, status, location (in or out), days (inclusive) or `search`
        (number, place names)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createTransfer", request=TransferWriteSerializer, responses={201: TransferDetailSerializer}
    )
    def post(self, request: Request) -> Response:
        """Prepare a transfer (a draft), or with `validate` also move the stock at once. Its kind comes
        from the places: into a truck is a load, out of one a return. A load line without `unit_price`
        takes the sale price in force. Errors of a line come back on `lines.<index>.<field>`."""
        serializer = TransferWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _transfer_fields(self.organization, serializer.validated_data)
        transfer = services.create_transfer(organization=self.organization, actor=self.membership.user, **data)
        return _transfer_answer(self.organization, transfer.pk, status_code=status.HTTP_201_CREATED)


class TransferDetailView(TransferView):
    @extend_schema(operation_id="getTransfer", responses=TransferDetailSerializer)
    def get(self, request: Request, transfer_id: int) -> Response:
        """One transfer; once validated, each line lists the batches its kg came from."""
        return _transfer_answer(self.organization, self.transfer(transfer_id).pk)

    @extend_schema(operation_id="updateTransfer", request=TransferWriteSerializer, responses=TransferDetailSerializer)
    def put(self, request: Request, transfer_id: int) -> Response:
        """Change a draft (every line is replaced), and with `validate` move the stock too."""
        transfer = self.transfer(transfer_id)
        serializer = TransferWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _transfer_fields(self.organization, serializer.validated_data)
        services.update_transfer(transfer=transfer, actor=self.membership.user, **data)
        return _transfer_answer(self.organization, transfer.pk)


class TransferValidateView(TransferView):
    @extend_schema(operation_id="validateTransfer", request=None, responses=TransferDetailSerializer)
    def post(self, request: Request, transfer_id: int) -> Response:
        """Validate a draft: its kg move, oldest batch first. Refused as a whole when the source holds
        too little (on `lines.<index>.quantity`) or for a day still to come. A load of today into a truck
        whose driver already sent the day opens that day again."""
        services.validate_transfer(transfer=self.transfer(transfer_id), actor=self.membership.user)
        return _transfer_answer(self.organization, transfer_id)


class TransferCancelView(TransferView):
    @extend_schema(operation_id="cancelTransfer", request=None, responses=TransferDetailSerializer)
    def post(self, request: Request, transfer_id: int) -> Response:
        """Give up a draft. A validated transfer is corrected by a transfer the other way."""
        services.cancel_transfer(transfer=self.transfer(transfer_id), actor=self.membership.user)
        return _transfer_answer(self.organization, transfer_id)


class TruckDayView(OfficeView):
    @extend_schema(operation_id="getTruckDay", parameters=[TruckDayFilterSerializer], responses=TruckDaySerializer)
    def get(self, request: Request) -> Response:
        """A truck's day per product from its validated transfers: kg loaded, kg returned, and loaded −
        returned, sold or lost, with the day's price per kg and what that is worth."""
        filters = TruckDayFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        try:
            location = selectors.location_of(self.organization, filters.validated_data["location"])
        except StockLocation.DoesNotExist:
            raise Http404 from None
        day = filters.validated_data["date"]
        lines = selectors.truck_day(self.organization, location_id=location.pk, day=day)
        total = sum((line.amount for line in lines if line.amount is not None), Decimal("0.000"))
        return Response(TruckDaySerializer({"location": location, "date": day, "lines": lines, "amount": total}).data)


class MyTruckDayView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="getMyTruckDay", responses=TruckDaySerializer)
    def get(self, request: Request) -> Response:
        """The signed-in driver's truck today: what was loaded, with the price per kg. 404 without a truck."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        truck = fleet.truck_of_driver(membership)
        if truck is None:
            raise Http404
        day = timezone.localdate()
        lines = selectors.truck_day(membership.organization, location_id=truck.location_id, day=day)
        total = sum((line.amount for line in lines if line.amount is not None), Decimal("0.000"))
        return Response(
            TruckDaySerializer({"location": truck.location, "date": day, "lines": lines, "amount": total}).data
        )


def _photo_url(product: Any) -> str | None:
    if not product.photo.name:
        return None
    # The file name changes with every upload, so the address can be cached for good.
    version = product.photo.name.rsplit("/", 1)[-1].split(".", 1)[0]
    return f"{reverse('product-photo', args=[product.pk])}?v={version}"


class MyStockView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(
        operation_id="listMyStock", parameters=[MyStockFilterSerializer], responses=MyStockLineSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """What the driver's truck holds now per product, with today's price per kg. With `customer`, the price that
        customer pays (their own price list first). 404 without a truck."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        filters = MyStockFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        customer_id = filters.validated_data.get("customer")
        customer = None
        if customer_id is not None:
            try:
                customer = partners.customer_of(membership.organization, customer_id)
            except ObjectDoesNotExist:
                raise ValidationError({"customer": _("Client inconnu.")}) from None
        truck = fleet.truck_of_driver(membership)
        if truck is None:
            raise Http404
        now = timezone.now()
        rows = []
        for row in selectors.location_stock(membership.organization, location_id=truck.location_id):
            product = catalog.product_of(membership.organization, row["product_id"])
            price = catalog.price_in_force(product, now, customer_id=customer.pk if customer else None)
            rows.append(
                {
                    "product_id": row["product_id"],
                    "product_name": row["product__name"],
                    "quantity": row["quantity"],
                    "unit_price": None if price is None else price.price,
                    "photo_url": _photo_url(product),
                }
            )
        return Response(MyStockLineSerializer(rows, many=True).data)


class MyLossesView(APIView):
    permission_classes = (IsDriver,)
    parser_classes = (MultiPartParser,)

    @extend_schema(
        operation_id="reportMyLoss",
        request={"multipart/form-data": RoadLossWriteSerializer},
        responses={201: RoadLossSerializer},
    )
    def post(self, request: Request) -> Response:
        """Report kilos lost on the driver's truck today, with a photo. Small losses leave the stock at once;
        a heavy one waits for the owner."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        organization = membership.organization
        serializer = RoadLossWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        made_at = moment_from_phone(data["made_at"], field="made_at")
        dayclose.refuse_sale_outside_day(membership, made_at)
        truck = fleet.truck_of_driver(membership)
        if truck is None:
            raise ValidationError({"truck": _("Choisissez d'abord votre camion.")})
        try:
            product = catalog.product_of(organization, data["product"])
        except ObjectDoesNotExist:
            raise ValidationError({"product": _("Produit inconnu.")}) from None
        loss = services.report_road_loss(
            organization=organization,
            actor=membership.user,
            location=truck.location,
            product=product,
            quantity=data["quantity"],
            reason=data["reason"],
            note=data["note"],
            upload=data.get("photo"),
            client_uuid=data["client_uuid"],
            made_at=made_at,
        )
        return Response(RoadLossSerializer(loss).data, status=status.HTTP_201_CREATED)


class MyReturnView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="returnMyStock", request=None, responses={201: RoadReturnSerializer})
    def post(self, request: Request) -> Response:
        """Bring everything left on the driver's truck back to the cold room it was loaded from."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        organization = membership.organization
        dayclose.refuse_if_day_closed(membership)
        truck = fleet.truck_of_driver(membership)
        if truck is None:
            raise ValidationError({"truck": _("Choisissez d'abord votre camion.")})
        room = selectors.return_destination(organization, truck_location_id=truck.location_id)
        if room is None:
            raise ValidationError({"to_location": _("Aucune chambre froide pour recevoir le retour.")})
        rows = selectors.location_stock(organization, location_id=truck.location_id)
        if not rows:
            raise ValidationError({"lines": _("Il ne reste rien dans le camion.")})
        lines: list[services.TransferLineFields] = [
            {"product": catalog.product_of(organization, row["product_id"]), "quantity": row["quantity"]}
            for row in rows
        ]
        transfer = services.create_transfer(
            organization=organization,
            actor=membership.user,
            from_location=truck.location,
            to_location=room,
            transferred_on=timezone.localdate(),
            lines=lines,
            validate=True,
        )
        answer = {
            "number": transfer.number,
            "to_location": room,
            "total_quantity": sum((row["quantity"] for row in rows), Decimal("0.000")),
        }
        return Response(RoadReturnSerializer(answer).data, status=status.HTTP_201_CREATED)


# ---- Losses and stock counts (P1-T10) ----


def _require_owner(membership: Membership, message: str) -> None:
    """Approving a loss and changing the stock rules are the owner's alone (checked here, D-045)."""
    if membership.role != Role.OWNER:
        raise PermissionDenied(message)


class StockSettingsView(OfficeView):
    @extend_schema(operation_id="getStockSettings", responses=StockSettingsSerializer)
    def get(self, request: Request) -> Response:
        """The stock rules: above `loss_approval_threshold` kg a loss waits for the owner's approval."""
        return Response(StockSettingsSerializer(selectors.stock_settings(self.organization)).data)

    @extend_schema(
        operation_id="updateStockSettings", request=StockSettingsWriteSerializer, responses=StockSettingsSerializer
    )
    def put(self, request: Request) -> Response:
        """Change the loss approval threshold (kg; 0: every loss waits). The owner only."""
        _require_owner(self.membership, _("Seul le propriétaire change ce seuil."))
        serializer = StockSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        row = services.update_stock_settings(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return Response(StockSettingsSerializer(row).data)


def _loss_answer(organization: Organization, loss_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
    loss = selectors.loss_of(organization, loss_id)
    movements = selectors.movements_from_sources([loss])
    return Response(LossDetailSerializer(loss, context={"movements": movements}).data, status=status_code)


class LossView(OfficeView):
    def loss(self, loss_id: int) -> StockLoss:
        try:
            return selectors.loss_of(self.organization, loss_id)
        except StockLoss.DoesNotExist:
            raise Http404 from None


class LossListView(LossView, ListAPIView[StockLoss]):
    serializer_class = LossSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[StockLoss]:
        filters = LossFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.losses_of(
            self.organization,
            status=filters.validated_data.get("status"),
            location_id=filters.validated_data.get("location"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listLosses", parameters=[LossFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Losses, newest day first, paginated (`limit`, `offset`). Filter by status, location or `search`
        (number, product, location)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(operation_id="recordLoss", request=LossWriteSerializer, responses={201: LossDetailSerializer})
    def post(self, request: Request) -> Response:
        """Record kilos lost at a location. Up to the threshold, or recorded by the owner, they leave the
        stock at once (oldest batch first); above it the loss waits for the owner (`pending`)."""
        serializer = LossWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        errors: dict[str, str] = {}
        try:
            data["location"] = selectors.location_of(self.organization, data["location"])
        except StockLocation.DoesNotExist:
            errors["location"] = _("Emplacement inconnu.")
        try:
            data["product"] = catalog.product_of(self.organization, data["product"])
        except ObjectDoesNotExist:
            errors["product"] = _("Produit inconnu.")
        if errors:
            raise ValidationError(errors)
        loss = services.record_loss(
            organization=self.organization,
            actor=self.membership.user,
            may_approve=self.membership.role == Role.OWNER,
            **data,
        )
        return _loss_answer(self.organization, loss.pk, status_code=status.HTTP_201_CREATED)


class LossDetailView(LossView):
    @extend_schema(operation_id="getLoss", responses=LossDetailSerializer)
    def get(self, request: Request, loss_id: int) -> Response:
        """One loss; once it left the stock, the batches it came from and their cost."""
        return _loss_answer(self.organization, self.loss(loss_id).pk)


class LossApproveView(LossView):
    @extend_schema(operation_id="approveLoss", request=None, responses=LossDetailSerializer)
    def post(self, request: Request, loss_id: int) -> Response:
        """The owner accepts a waiting loss: its kg leave the stock now, oldest batch first."""
        loss = self.loss(loss_id)
        _require_owner(self.membership, _("Seul le propriétaire valide une perte en attente."))
        services.approve_loss(loss=loss, actor=self.membership.user)
        return _loss_answer(self.organization, loss_id)


class LossRejectView(LossView):
    @extend_schema(operation_id="rejectLoss", request=LossRejectSerializer, responses=LossDetailSerializer)
    def post(self, request: Request, loss_id: int) -> Response:
        """The owner refuses a waiting loss, saying why. Nothing moves."""
        loss = self.loss(loss_id)
        _require_owner(self.membership, _("Seul le propriétaire refuse une perte en attente."))
        serializer = LossRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reject_loss(loss=loss, actor=self.membership.user, reason=serializer.validated_data["reason"])
        return _loss_answer(self.organization, loss_id)


class LossPhotoView(LossView):
    parser_classes = (MultiPartParser,)

    # Read by an <img> tag, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, loss_id: int) -> FileResponse:
        loss = self.loss(loss_id)
        if not loss.photo:
            raise Http404
        response = FileResponse(loss.photo.open("rb"), content_type="image/webp")
        # A loss's photo never changes once joined.
        response["Cache-Control"] = "private, max-age=31536000, immutable"
        return response

    @extend_schema(
        operation_id="addLossPhoto",
        request={"multipart/form-data": LossPhotoSerializer},
        responses={200: LossDetailSerializer, 400: OpenApiResponse(description="Not a readable JPEG, PNG or WebP")},
    )
    def put(self, request: Request, loss_id: int) -> Response:
        """Join a photo as proof, once: it is turned upright, shrunk and stored as WebP without metadata."""
        serializer = LossPhotoSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_loss_photo(
            loss=self.loss(loss_id), actor=self.membership.user, upload=serializer.validated_data["photo"]
        )
        return _loss_answer(self.organization, loss_id)


class CountView(OfficeView):
    def count(self, count_id: int) -> StockCount:
        try:
            return selectors.count_of(self.organization, count_id)
        except StockCount.DoesNotExist:
            raise Http404 from None

    def answer(self, count_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
        return Response(CountSerializer(selectors.count_of(self.organization, count_id)).data, status=status_code)


class CountListView(CountView, ListAPIView[StockCount]):
    serializer_class = CountSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[StockCount]:
        filters = CountFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.counts_of(
            self.organization,
            status=filters.validated_data.get("status"),
            location_id=filters.validated_data.get("location"),
        )

    @extend_schema(operation_id="listCounts", parameters=[CountFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Stock counts, newest first, paginated, each with its sheet. Filter by status or location."""
        return super().get(request, *args, **kwargs)

    @extend_schema(operation_id="startCount", request=CountWriteSerializer, responses={201: CountSerializer})
    def post(self, request: Request) -> Response:
        """Open a count sheet for a location: one line per batch it holds, with the kg the ledger expects.
        One count at a time per location."""
        serializer = CountWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        try:
            data["location"] = selectors.location_of(self.organization, data["location"])
        except StockLocation.DoesNotExist:
            raise ValidationError({"location": _("Emplacement inconnu.")}) from None
        count = services.start_count(organization=self.organization, actor=self.membership.user, **data)
        return self.answer(count.pk, status_code=status.HTTP_201_CREATED)


class CountDetailView(CountView):
    @extend_schema(operation_id="getCount", responses=CountSerializer)
    def get(self, request: Request, count_id: int) -> Response:
        return self.answer(self.count(count_id).pk)


class CountLinesView(CountView):
    @extend_schema(operation_id="recordCounted", request=CountedSerializer, responses=CountSerializer)
    def put(self, request: Request, count_id: int) -> Response:
        """Type the kg counted on lines of an open sheet (empty clears, 0 = nothing found). Errors come
        back on `lines.<index>.counted_quantity`."""
        count = self.count(count_id)
        serializer = CountedSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.record_counted(count=count, actor=self.membership.user, lines=serializer.validated_data["lines"])
        return self.answer(count_id)


class CountApproveView(CountView):
    @extend_schema(operation_id="approveCount", request=None, responses=CountSerializer)
    def post(self, request: Request, count_id: int) -> Response:
        """Post a count correction for every difference and freeze the count. Every line must be counted."""
        services.approve_count(count=self.count(count_id), actor=self.membership.user)
        return self.answer(count_id)


class CountCancelView(CountView):
    @extend_schema(operation_id="cancelCount", request=None, responses=CountSerializer)
    def post(self, request: Request, count_id: int) -> Response:
        """Give up an open count: nothing moved."""
        services.cancel_count(count=self.count(count_id), actor=self.membership.user)
        return self.answer(count_id)


# ---- Stock screens (P1-T11) ----


class StockOverviewView(OfficeView):
    @extend_schema(operation_id="getStockOverview", responses=StockOverviewSerializer)
    def get(self, request: Request) -> Response:
        """Each active location with the kg and cost it holds, and each product with its kg per location,
        its low-stock warning and its average and last purchase cost (pricing information only, D-040)."""
        overview = {
            "locations": selectors.location_totals(self.organization),
            "products": selectors.product_stocks(self.organization),
        }
        return Response(StockOverviewSerializer(overview).data)


class _StockWithBatches:
    """A product's stock with its batches, as one object for the serializer."""

    def __init__(self, stock: selectors.ProductStock, batches: list[selectors.BatchHolding]) -> None:
        self.product = stock.product
        self.quantity = stock.quantity
        self.by_location = stock.by_location
        self.average_cost = stock.average_cost
        self.last_cost = stock.last_cost
        self.is_low = stock.is_low
        self.batches = batches


class ProductStockView(OfficeView):
    @extend_schema(operation_id="getProductStock", responses=ProductStockDetailSerializer)
    def get(self, request: Request, product_id: int) -> Response:
        """One product's stock like the overview, plus the batches still on hand with their locations."""
        try:
            stock = selectors.product_stock(self.organization, product_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        batches = selectors.batch_holdings(self.organization, product_id=product_id)
        return Response(ProductStockDetailSerializer(_StockWithBatches(stock, batches)).data)


class MovementListView(OfficeView, ListAPIView[Any]):
    serializer_class = StockMovementSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Any]:
        filters = StockMovementFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        return selectors.movements_of(
            self.organization,
            location_id=data.get("location"),
            product_id=data.get("product"),
            batch_id=data.get("batch"),
            kind=data.get("kind"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
        )

    @extend_schema(operation_id="listMovements", parameters=[StockMovementFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """The stock ledger, newest first, paginated (`limit`, `offset`). A location filter keeps the
        movements coming in or going out of it; dates are inclusive."""
        return super().get(request, *args, **kwargs)
