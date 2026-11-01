from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import FileResponse, Http404, HttpResponse
from django.utils.translation import gettext as _
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.generics import ListAPIView
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors as catalog
from apps.core.api.pagination import PagedList
from apps.core.models import Membership, Organization, Role
from apps.core.permissions import ReadOfficeWriteOwnerOrManager, membership_of
from apps.core.xlsx import XLSX_TYPE, workbook_bytes, xlsx_response
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.purchasing import selectors, services
from apps.purchasing.models import (
    FieldPurchase,
    GoodsReceipt,
    GoodsReceiptLine,
    PurchaseOrder,
    SupplierInvoice,
    SupplierPayment,
    SupplierPaymentLine,
    SupplierPaymentPlanLine,
)
from apps.treasury import selectors as treasury

from .serializers import (
    DifferenceFilterSerializer,
    DifferenceLineSerializer,
    EffetRejectSerializer,
    FieldPurchaseCreateSerializer,
    FieldPurchaseFilterSerializer,
    FieldPurchaseListSerializer,
    FieldPurchaseRefuseSerializer,
    FieldPurchaseSerializer,
    FieldPurchaseWriteSerializer,
    LastCostFilterSerializer,
    LastCostSerializer,
    OrderFilterSerializer,
    OrderSerializer,
    OrderWriteSerializer,
    PaymentAllocateSerializer,
    PaymentTotalsSerializer,
    PaymentVoidSerializer,
    PlanWriteSerializer,
    ReceiptFilterSerializer,
    ReceiptSerializer,
    ReceiptWriteSerializer,
    SettlementFilterSerializer,
    SettlementRowSerializer,
    SettlementsSerializer,
    SupplierBalanceSerializer,
    SupplierDebtsSerializer,
    SupplierInvoiceFilterSerializer,
    SupplierInvoiceSerializer,
    SupplierInvoiceUpdateSerializer,
    SupplierInvoiceWriteSerializer,
    SupplierPaymentDetailSerializer,
    SupplierPaymentFilterSerializer,
    SupplierPaymentSerializer,
    SupplierPaymentWriteSerializer,
)


# Purchases are office data (D-032): owner, manager and accountant read; owner and manager record; drivers 403.
# Rows of the user's organization only (D-022). A comment, not a docstring: it would describe every endpoint.
class PurchasingView(APIView):
    permission_classes = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization


def _resolved(organization: Organization, data: dict[str, Any], *, is_owner: bool = False) -> dict[str, Any]:
    """The ids of a receipt replaced by the rows they name in the organization; unknown ids are field errors."""
    errors: dict[str, str] = {}
    supplier = location = None
    try:
        supplier = partners.supplier_of(organization, data["supplier"])
    except ObjectDoesNotExist:
        errors["supplier"] = _("Fournisseur inconnu.")
    try:
        location = inventory.location_of(organization, data["location"])
    except ObjectDoesNotExist:
        errors["location"] = _("Emplacement inconnu.")
    order = None
    if data.get("purchase_order") is not None:
        try:
            order = selectors.order_of(organization, data["purchase_order"])
        except PurchaseOrder.DoesNotExist:
            errors["purchase_order"] = _("Commande d'achat inconnue.")
    lines = []
    for index, line in enumerate(data["lines"]):
        try:
            product = catalog.product_of(organization, line["product"])
        except ObjectDoesNotExist:
            errors[services.line_error_key(index, "product")] = _("Produit inconnu.")
            continue
        partner = None
        if line.get("partner") is not None:
            # Partners are the owner's business (D-060), like the rest of the partnership screens.
            if not is_owner:
                errors[services.line_error_key(index, "partner")] = _("Seul le propriétaire choisit un partenaire.")
            else:
                try:
                    partner = partners.supplier_of(organization, line["partner"])
                except ObjectDoesNotExist:
                    errors[services.line_error_key(index, "partner")] = _("Fournisseur inconnu.")
        lines.append({**line, "product": product, "partner": partner})
    if errors:
        raise ValidationError(errors)
    return {**data, "supplier": supplier, "location": location, "purchase_order": order, "lines": lines}


class ReceiptListView(PurchasingView, ListAPIView[GoodsReceipt]):
    serializer_class = ReceiptSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[GoodsReceipt]:
        filters = ReceiptFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.receipts_of(
            self.organization,
            supplier_id=filters.validated_data.get("supplier"),
            search=filters.validated_data["search"],
            with_differences=filters.validated_data["differences"],
            uninvoiced=filters.validated_data["uninvoiced"],
            purchase_order_id=filters.validated_data.get("purchase_order"),
        )

    @extend_schema(operation_id="listReceipts", parameters=[ReceiptFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Goods receipts, newest first, paginated (`limit`, `offset`), each with its lines and totals.
        Filter by supplier, by `search` (number, supplier's reference, supplier name) or to receipts with
        a weight difference."""
        return super().get(request, *args, **kwargs)

    @extend_schema(operation_id="createReceipt", request=ReceiptWriteSerializer, responses={201: ReceiptSerializer})
    def post(self, request: Request) -> Response:
        """Record goods received from a supplier: one batch per line, its accepted net weight into stock.
        Errors of a line come back on `lines.<index>.<field>`. With `purchase_order`, it is a delivery
        against that commande d'achat: only its products, and only the part that arrived (partial receipts). With
        `invoice_now`, what is owed is recorded at once: a posted supplier invoice due by `terms` and `due_days`."""
        serializer = ReceiptWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _resolved(self.organization, serializer.validated_data, is_owner=self.membership.role == Role.OWNER)
        invoice_now, terms, due_days = data.pop("invoice_now"), data.pop("terms"), data.pop("due_days")
        payments = data.pop("payments", [])
        if payments and not invoice_now:
            raise ValidationError({"payments": _("Un paiement à la réception demande « Dû dès la réception ».")})
        if invoice_now:
            # Owed at once, due by the deal made for this delivery (D-159).
            receipt = services.receive_and_invoice(
                organization=self.organization,
                actor=self.membership.user,
                terms=terms,
                due_days=due_days,
                payments=payments,
                **data,
            )
        else:
            receipt = services.create_receipt(organization=self.organization, actor=self.membership.user, **data)
        return Response(
            ReceiptSerializer(selectors.receipt_of(self.organization, receipt.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class ReceiptDetailView(PurchasingView):
    @extend_schema(operation_id="getReceipt", responses=ReceiptSerializer)
    def get(self, request: Request, receipt_id: int) -> Response:
        try:
            receipt = selectors.receipt_of(self.organization, receipt_id)
        except GoodsReceipt.DoesNotExist:
            raise Http404 from None
        return Response(ReceiptSerializer(receipt).data)


class ReceiptDifferenceListView(PurchasingView, ListAPIView[GoodsReceiptLine]):
    serializer_class = DifferenceLineSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[GoodsReceiptLine]:
        filters = DifferenceFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.difference_lines(
            self.organization,
            supplier_id=filters.validated_data.get("supplier"),
            date_from=filters.validated_data.get("date_from"),
            date_to=filters.validated_data.get("date_to"),
        )

    @extend_schema(operation_id="listReceiptDifferences", parameters=[DifferenceFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Weight differences report: receipt lines whose accepted weight is not the invoiced or ordered
        weight, newest first, paginated. Filter by supplier and by receipt dates (inclusive)."""
        return super().get(request, *args, **kwargs)


class LastCostListView(PurchasingView):
    @extend_schema(
        operation_id="listLastPurchaseCosts",
        parameters=[LastCostFilterSerializer],
        responses=LastCostSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """What was last paid one supplier for each product (its latest batch). The receipt form suggests
        it and shows the change. The full history per product and supplier is `listBatches`."""
        filters = LastCostFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        batches = inventory.last_batches_from(self.organization, supplier_id=filters.validated_data["supplier"])
        return Response(LastCostSerializer(batches, many=True).data)


# ---- Purchase orders, the "commande d'achat" (D-076) ----


class OrderListView(PurchasingView, ListAPIView[PurchaseOrder]):
    serializer_class = OrderSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[PurchaseOrder]:
        filters = OrderFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.orders_of(
            self.organization,
            supplier_id=filters.validated_data.get("supplier"),
            status=filters.validated_data.get("status"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listPurchaseOrders", parameters=[OrderFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Purchase orders (commandes d'achat), newest first, paginated, each with its lines (ordered, received
        and remaining weight) and its receipts. Filter by supplier, status (`pending` = still waiting for
        goods) or `search` (number, supplier's name)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(operation_id="createPurchaseOrder", request=OrderWriteSerializer, responses={201: OrderSerializer})
    def post(self, request: Request) -> Response:
        """Record a purchase order: what we ask a supplier to deliver, at what price. It moves no stock;
        deliveries are goods receipts against it, as many as the supplier makes."""
        serializer = OrderWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        supplier = _supplier(self.organization, data.pop("supplier"))
        errors: dict[str, str] = {}
        lines: list[Any] = []
        for index, line in enumerate(data.pop("lines")):
            try:
                product = catalog.product_of(self.organization, line["product"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "product")] = _("Produit inconnu.")
                continue
            lines.append({**line, "product": product})
        if errors:
            raise ValidationError(errors)
        order = services.create_order(
            organization=self.organization, actor=self.membership.user, supplier=supplier, lines=lines, **data
        )
        return Response(
            OrderSerializer(selectors.order_of(self.organization, order.pk)).data, status=status.HTTP_201_CREATED
        )


class OrderView(PurchasingView):
    def _order(self, order_id: int) -> PurchaseOrder:
        try:
            return selectors.order_of(self.organization, order_id)
        except PurchaseOrder.DoesNotExist:
            raise Http404 from None


class OrderDetailView(OrderView):
    @extend_schema(operation_id="getPurchaseOrder", responses=OrderSerializer)
    def get(self, request: Request, order_id: int) -> Response:
        return Response(OrderSerializer(self._order(order_id)).data)


class OrderCancelView(OrderView):
    @extend_schema(operation_id="cancelPurchaseOrder", request=None, responses=OrderSerializer)
    def post(self, request: Request, order_id: int) -> Response:
        """Cancel an order nothing was delivered against."""
        services.cancel_order(order=self._order(order_id), actor=self.membership.user)
        return Response(OrderSerializer(self._order(order_id)).data)


class OrderCloseView(OrderView):
    @extend_schema(operation_id="closePurchaseOrder", request=None, responses=OrderSerializer)
    def post(self, request: Request, order_id: int) -> Response:
        """Close an order that was delivered in part: the rest will not come. Receipts stay as they are."""
        services.close_order(order=self._order(order_id), actor=self.membership.user)
        return Response(OrderSerializer(self._order(order_id)).data)


# ---- Supplier invoices and payments (P1-T08, D-043) ----


def _supplier(organization: Organization, supplier_id: int) -> Any:
    try:
        return partners.supplier_of(organization, supplier_id)
    except ObjectDoesNotExist:
        raise ValidationError({"supplier": _("Fournisseur inconnu.")}) from None


def _receipts(organization: Organization, receipt_ids: list[int]) -> list[GoodsReceipt]:
    """The receipts named by id in the organization; an unknown one is an error on `receipts`."""
    found = list(selectors.receipts_of(organization).filter(pk__in=receipt_ids))
    if len(found) != len(set(receipt_ids)):
        raise ValidationError({"receipts": _("Réception inconnue.")})
    return found


def _allocations(organization: Organization, lines: list[dict[str, Any]]) -> list[services.AllocationFields]:
    """The invoices named by id in the organization; an unknown one is an error on its own line."""
    errors: dict[str, str] = {}
    resolved: list[services.AllocationFields] = []
    for index, line in enumerate(lines):
        try:
            invoice = selectors.invoices_of(organization).get(pk=line["invoice"])
        except SupplierInvoice.DoesNotExist:
            errors[services.allocation_error_key(index, "invoice")] = _("Facture inconnue.")
            continue
        resolved.append({"invoice": invoice, "amount": line["amount"]})
    if errors:
        raise ValidationError(errors)
    return resolved


def _plan_line(organization: Organization, line_id: int | None) -> SupplierPaymentPlanLine | None:
    """The plan line named by id in the organization (D-192); an unknown one is an error on `plan_line`."""
    if line_id is None:
        return None
    try:
        return selectors.plan_line_of(organization, line_id)
    except SupplierPaymentPlanLine.DoesNotExist:
        raise ValidationError({"plan_line": _("Ligne de règlement inconnue.")}) from None


def _plan_lines(organization: Organization, line_ids: list[int]) -> list[SupplierPaymentPlanLine]:
    """The plan lines named by id (D-208); an unknown one is an error on `plan_lines.<index>`."""
    errors: dict[str, str] = {}
    found: list[SupplierPaymentPlanLine] = []
    for index, line_id in enumerate(line_ids):
        try:
            found.append(selectors.plan_line_of(organization, line_id))
        except SupplierPaymentPlanLine.DoesNotExist:
            errors[f"plan_lines.{index}"] = _("Ligne de règlement inconnue.")
    if errors:
        raise ValidationError(errors)
    return found


def _payment_lines(organization: Organization, lines: list[dict[str, Any]]) -> list[services.PaymentLineFields]:
    """The règlement's lines with their bank and account resolved in the organization; an unknown one is an error
    on its line."""
    errors: dict[str, str] = {}
    resolved: list[services.PaymentLineFields] = []
    for index, line in enumerate(lines):
        row: services.PaymentLineFields = {
            "method": line["method"],
            "amount": line["amount"],
            "reference": line["reference"],
            "number": line["number"],
            "due_on": line["due_on"],
            "bank": None,
            "account": None,
        }
        if line["bank"] is not None:
            try:
                row["bank"] = treasury.bank_of(organization, line["bank"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "bank")] = _("Banque inconnue.")
        if line.get("account") is not None:
            try:
                row["account"] = treasury.account_of(organization, line["account"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "account")] = _("Compte inconnu.")
        resolved.append(row)
    if errors:
        raise ValidationError(errors)
    return resolved


class SupplierInvoiceListView(PurchasingView, ListAPIView[SupplierInvoice]):
    serializer_class = SupplierInvoiceSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[SupplierInvoice]:
        filters = SupplierInvoiceFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.invoices_of(
            self.organization,
            supplier_id=filters.validated_data.get("supplier"),
            status=filters.validated_data.get("status"),
            search=filters.validated_data["search"],
            overdue=filters.validated_data["overdue"],
        )

    @extend_schema(operation_id="listSupplierInvoices", parameters=[SupplierInvoiceFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Supplier invoices, newest first, paginated, each with its receipts, payments, paid amount and what
        is still owed. Filter by supplier, status (`open` = posted and not fully paid), overdue, or `search`
        (our number, the supplier's invoice number, the supplier's name)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createSupplierInvoice",
        request=SupplierInvoiceWriteSerializer,
        responses={201: SupplierInvoiceSerializer},
    )
    def post(self, request: Request) -> Response:
        """Record a supplier invoice for some of their receipts, as a draft, or posted at once with `post`.
        Its amount is the receipts' invoiced amount (invoiced kg × cost); a receipt goes on one invoice only."""
        serializer = SupplierInvoiceWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        supplier = _supplier(self.organization, data.pop("supplier"))
        receipts = _receipts(self.organization, data.pop("receipts"))
        invoice = services.create_invoice(
            organization=self.organization, actor=self.membership.user, supplier=supplier, receipts=receipts, **data
        )
        return Response(
            SupplierInvoiceSerializer(selectors.invoice_of(self.organization, invoice.pk)).data,
            status=status.HTTP_201_CREATED,
        )


def _settlement_data(row: selectors.SettlementRow) -> Any:
    """A settlement row as the serializer reads it."""
    invoice = row.invoice
    purchase = getattr(invoice, "field_purchase", None)
    return SettlementRowSerializer(
        {
            "invoice_id": invoice.pk,
            "number": invoice.number,
            "supplier_reference": invoice.supplier_reference,
            "supplier": {"id": invoice.supplier_id, "name": invoice.supplier.name},
            "purchase_type": row.purchase_type,
            "field_purchase_number": purchase.number if purchase else None,
            "invoice_date": invoice.invoice_date,
            "due_date": invoice.due_date,
            "posted_at": invoice.posted_at,
            "age_hours": row.age_hours,
            "total": row.total,
            "paid": row.paid,
            "planned": row.planned,
            "undefined": row.undefined,
            "state": row.state,
            "plan_lines": row.plan_lines,
        }
    ).data


class InvoiceView(PurchasingView):
    def _invoice(self, invoice_id: int) -> SupplierInvoice:
        try:
            return selectors.invoice_of(self.organization, invoice_id)
        except SupplierInvoice.DoesNotExist:
            raise Http404 from None


class SupplierInvoiceDetailView(InvoiceView):
    @extend_schema(operation_id="getSupplierInvoice", responses=SupplierInvoiceSerializer)
    def get(self, request: Request, invoice_id: int) -> Response:
        return Response(SupplierInvoiceSerializer(self._invoice(invoice_id)).data)

    @extend_schema(
        operation_id="updateSupplierInvoice",
        request=SupplierInvoiceUpdateSerializer,
        responses=SupplierInvoiceSerializer,
    )
    def put(self, request: Request, invoice_id: int) -> Response:
        """Change a draft invoice: receipts, dates, reference, notes; `post` posts it afterwards. A posted
        invoice no longer changes (400). The supplier does not change."""
        invoice = self._invoice(invoice_id)
        serializer = SupplierInvoiceUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        receipts = _receipts(self.organization, data.pop("receipts"))
        services.update_invoice(invoice=invoice, actor=self.membership.user, receipts=receipts, **data)
        return Response(SupplierInvoiceSerializer(self._invoice(invoice_id)).data)

    @extend_schema(operation_id="deleteSupplierInvoice", responses={204: None})
    def delete(self, request: Request, invoice_id: int) -> Response:
        """Delete a draft invoice; its receipts can go on another one. A posted invoice is never deleted (400)."""
        services.delete_invoice(invoice=self._invoice(invoice_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SupplierInvoicePostView(InvoiceView):
    @extend_schema(operation_id="postSupplierInvoice", request=None, responses=SupplierInvoiceSerializer)
    def post(self, request: Request, invoice_id: int) -> Response:
        """Post a draft invoice: it is owed to the supplier, counts in their balance and can be paid. Final."""
        services.post_invoice(invoice=self._invoice(invoice_id), actor=self.membership.user)
        return Response(SupplierInvoiceSerializer(self._invoice(invoice_id)).data)


class SupplierInvoicePlanView(InvoiceView):
    @extend_schema(
        operation_id="setSupplierInvoicePlan", request=PlanWriteSerializer, responses=SettlementRowSerializer
    )
    def put(self, request: Request, invoice_id: int) -> Response:
        """Replace the open plan lines of a posted invoice: how, when and how much will be paid (D-192). Their sum
        may not exceed what is left to pay. A plan is not a payment: the supplier balance does not move. Errors of a
        line come back on `lines.<index>.<field>`; an empty list clears the plan."""
        invoice = self._invoice(invoice_id)
        serializer = PlanWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.set_payment_plan(invoice=invoice, actor=self.membership.user, lines=serializer.validated_data["lines"])
        return Response(_settlement_data(selectors.settlement_of(self.organization, invoice_id)))


class SupplierPlanLineView(PurchasingView):
    @extend_schema(operation_id="cancelSupplierPlanLine", responses=SettlementRowSerializer)
    def delete(self, request: Request, line_id: int) -> Response:
        """Cancel an open plan line: its amount goes back to "undefined". Answers the invoice's settlement row. A
        line already paid is kept (400)."""
        try:
            line = selectors.plan_line_of(self.organization, line_id)
        except SupplierPaymentPlanLine.DoesNotExist:
            raise Http404 from None
        services.cancel_plan_line(line=line, actor=self.membership.user)
        return Response(_settlement_data(selectors.settlement_of(self.organization, line.invoice_id)))


class SupplierSettlementsView(PurchasingView):
    @extend_schema(
        operation_id="listSupplierSettlements",
        parameters=[SettlementFilterSerializer],
        responses=SettlementsSerializer,
    )
    def get(self, request: Request) -> Response:
        """Every posted supplier invoice with what is paid, planned and still undefined, and its state: settled,
        overdue, planned or undefined (D-192). The summary covers the type and supplier filters, whatever the
        `state`, so the tabs can show their counts; `rows` are kept to `state` when given."""
        filters = SettlementFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        found = selectors.supplier_settlements(
            self.organization,
            state=filters.validated_data.get("state"),
            purchase_type=filters.validated_data.get("type"),
            supplier_id=filters.validated_data.get("supplier"),
        )
        data = {"rows": [_settlement_data(row) for row in found.rows], "summary": found.summary}
        return Response(SettlementsSerializer(data).data)


class SupplierPaymentListView(PurchasingView, ListAPIView[SupplierPayment]):
    serializer_class = SupplierPaymentSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[SupplierPayment]:
        return _filtered_payments(self.organization, self.request)

    @extend_schema(operation_id="listSupplierPayments", parameters=[SupplierPaymentFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Payments to suppliers, newest first, paginated (voided ones too), with their means, the invoices each
        one settled and the part not allocated yet. Filter by supplier, days paid, means (`mixed`: several),
        state (`active`, `voided`, `unallocated`) or `search` (number, cheque or transfer reference, supplier)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="recordSupplierPayment",
        request=SupplierPaymentWriteSerializer,
        responses={201: SupplierPaymentSerializer},
    )
    def post(self, request: Request) -> Response:
        """Record money paid to a supplier and the posted invoices it settles. Its means come in `lines` (some
        cash, our cheques and traites, each one an effet the treasury follows), or as one means in `amount`,
        `method`, `reference` and `cash_on`. What is not allocated is an advance, to allocate later;
        `auto_allocate` pays the invoices due first. Errors come back on `lines.<index>.<field>`,
        `allocations.<index>.<field>` and `plan_lines.<index>`."""
        serializer = SupplierPaymentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        supplier = _supplier(self.organization, data.pop("supplier"))
        allocations = _allocations(self.organization, data.pop("allocations"))
        auto = data.pop("auto_allocate")
        plan_line = _plan_line(self.organization, data.pop("plan_line"))
        plan_lines = _plan_lines(self.organization, data.pop("plan_lines"))
        lines = data.pop("lines", None)
        payment = services.record_payment(
            organization=self.organization,
            actor=self.membership.user,
            supplier=supplier,
            lines=_payment_lines(self.organization, lines) if lines is not None else None,
            allocations=None if auto else allocations,
            plan_line=plan_line,
            plan_lines=plan_lines,
            amount=data.pop("amount", None),
            method=data.pop("method", ""),
            **data,
        )
        return Response(
            SupplierPaymentSerializer(selectors.payment_of(self.organization, payment.pk)).data,
            status=status.HTTP_201_CREATED,
        )


def _filtered_payments(organization: Organization, request: Request) -> QuerySet[SupplierPayment]:
    filters = SupplierPaymentFilterSerializer(data=request.query_params)
    filters.is_valid(raise_exception=True)
    data = filters.validated_data
    return selectors.payments_of(
        organization,
        supplier_id=data.get("supplier"),
        search=data["search"],
        unallocated=data["unallocated"],
        date_from=data.get("date_from"),
        date_to=data.get("date_to"),
        method=data.get("method"),
        state=data.get("state"),
    )


class SupplierPaymentTotalsView(PurchasingView):
    @extend_schema(
        operation_id="getSupplierPaymentTotals",
        parameters=[SupplierPaymentFilterSerializer],
        responses=PaymentTotalsSerializer,
    )
    def get(self, request: Request) -> Response:
        """What the règlements of the same filters as the list add up to (voided ones left out): their count,
        total, allocated, advance, and what each means paid."""
        return Response(
            PaymentTotalsSerializer(selectors.payment_totals(_filtered_payments(self.organization, request))).data
        )


class SupplierPaymentExportView(PurchasingView):
    @extend_schema(
        operation_id="exportSupplierPayments",
        parameters=[SupplierPaymentFilterSerializer],
        responses={(200, XLSX_TYPE): OpenApiTypes.BINARY},
    )
    def get(self, request: Request) -> HttpResponse:
        """The règlements of the same filters as the list, as an Excel file (one row each, voided ones marked)."""
        payments = list(_filtered_payments(self.organization, request)[:5000])
        rows = [
            [
                payment.number,
                payment.paid_on,
                payment.supplier.name,
                payment.get_method_display(),
                ", ".join(_line_label(line) for line in payment.lines.all()),
                payment.amount,
                getattr(payment, "allocated_amount"),  # noqa: B009
                getattr(payment, "unallocated_amount"),  # noqa: B009
                _("Annulé") if payment.voided_at else "",
            ]
            for payment in payments
        ]
        live = [payment for payment in payments if payment.voided_at is None]
        content = workbook_bytes(
            title=_("Règlements fournisseurs"),
            headers=[
                _("N°"),
                _("Date"),
                _("Fournisseur"),
                _("Mode"),
                _("Moyens"),
                _("Montant"),
                _("Affecté"),
                _("Avance"),
                _("État"),
            ],
            rows=rows,
            totals=[
                _("Total"),
                "",
                "",
                "",
                "",
                sum((payment.amount for payment in live), Decimal("0.000")),
                sum((getattr(payment, "allocated_amount") for payment in live), Decimal("0.000")),  # noqa: B009
                sum((getattr(payment, "unallocated_amount") for payment in live), Decimal("0.000")),  # noqa: B009
                "",
            ],
        )
        return xlsx_response("reglements-fournisseurs", content)


def _line_label(line: SupplierPaymentLine) -> str:
    label = str(line.get_method_display())
    if line.instrument is not None:
        label += f" {line.instrument.number}"
    elif line.reference:
        label += f" {line.reference}"
    return f"{label} ({line.amount})"


class PaymentView(PurchasingView):
    def _payment(self, payment_id: int) -> SupplierPayment:
        try:
            return selectors.payment_of(self.organization, payment_id)
        except SupplierPayment.DoesNotExist:
            raise Http404 from None


class SupplierPaymentDetailView(PaymentView):
    @extend_schema(operation_id="getSupplierPayment", responses=SupplierPaymentDetailSerializer)
    def get(self, request: Request, payment_id: int) -> Response:
        """One règlement: its means (each effet with its history), the invoices it settled, the advance left."""
        return Response(SupplierPaymentDetailSerializer(self._payment(payment_id)).data)


class SupplierEffetRejectView(PaymentView):
    @extend_schema(
        operation_id="rejectIssuedEffet", request=EffetRejectSerializer, responses=SupplierPaymentDetailSerializer
    )
    def post(self, request: Request, instrument_id: int) -> Response:
        """Our bank refused to pay this cheque or traite (owner or manager): it becomes "Rejeté" and the supplier is
        owed its amount again (the invoices its règlement settled owe again beyond its advance, D-218). Answers
        with the règlement."""
        serializer = EffetRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rejected = services.reject_issued_effet(
            organization=self.organization,
            actor=self.membership.user,
            instrument_id=instrument_id,
            rejected_on=serializer.validated_data["rejected_on"],
            reason=serializer.validated_data["reason"],
        )
        return Response(SupplierPaymentDetailSerializer(self._payment(rejected.payment_id)).data)


class SupplierPaymentVoidView(PaymentView):
    @extend_schema(
        operation_id="voidSupplierPayment", request=PaymentVoidSerializer, responses=SupplierPaymentDetailSerializer
    )
    def post(self, request: Request, payment_id: int) -> Response:
        """Void a règlement typed by mistake (owner or manager), with its reason: it stays in the list, marked
        voided; its invoices owe again, the plan lines it paid are planned again, its cheques and traites are
        cancelled. Refused once one of them was debited, and for money given at the port with a purchase."""
        payment = self._payment(payment_id)
        serializer = PaymentVoidSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.void_payment(payment=payment, actor=self.membership.user, reason=serializer.validated_data["reason"])
        return Response(SupplierPaymentDetailSerializer(self._payment(payment_id)).data)


class SupplierPaymentAllocateView(PaymentView):
    @extend_schema(
        operation_id="allocateSupplierPayment", request=PaymentAllocateSerializer, responses=SupplierPaymentSerializer
    )
    def post(self, request: Request, payment_id: int) -> Response:
        """Allocate the part of a payment not allocated yet (an advance) to posted invoices of its supplier."""
        payment = self._payment(payment_id)
        serializer = PaymentAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allocations = _allocations(self.organization, serializer.validated_data["allocations"])
        services.allocate_payment(payment=payment, actor=self.membership.user, allocations=allocations)
        return Response(SupplierPaymentSerializer(self._payment(payment_id)).data)


class SupplierBalanceView(PurchasingView):
    @extend_schema(operation_id="getSupplierBalance", responses=SupplierBalanceSerializer)
    def get(self, request: Request, supplier_id: int) -> Response:
        """The trade balance with one supplier: posted invoices − payments, with what is overdue, advances not
        allocated, drafts and receipts not invoiced yet. A partner's capital and profit share are not in it."""
        try:
            supplier = partners.supplier_of(self.organization, supplier_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        return Response(SupplierBalanceSerializer(selectors.supplier_balance(self.organization, supplier.pk)).data)


# ---- Buying at the port, the "achat terrain" (P3-T12, D-176) ----
# The office checks what a driver bought: owner and manager change, validate or refuse it; the accountant reads.


def _field_purchase_fields(
    organization: Organization, data: dict[str, Any], *, is_owner: bool, kept_partners: set[int]
) -> services.FieldPurchaseFields:
    """The ids of a purchase replaced by the rows they name in the organization; unknown ids are field errors.

    A partner is the owner's choice (D-060): anyone else may only keep the partners the purchase already has.
    """
    errors: dict[str, str] = {}
    supplier = location = None
    if data.get("supplier") is not None:
        try:
            supplier = partners.supplier_of(organization, data["supplier"])
        except ObjectDoesNotExist:
            errors["supplier"] = _("Fournisseur inconnu.")
    if data.get("location") is not None:
        try:
            location = inventory.location_of(organization, data["location"])
        except ObjectDoesNotExist:
            errors["location"] = _("Emplacement inconnu.")
    lines: list[services.FieldLineFields] = []
    for index, line in enumerate(data["lines"]):
        product = partner = None
        if line.get("product") is not None:
            try:
                product = catalog.product_of(organization, line["product"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "product")] = _("Produit inconnu.")
        if line.get("partner") is not None:
            if not is_owner and line["partner"] not in kept_partners:
                errors[services.line_error_key(index, "partner")] = _("Seul le propriétaire choisit un partenaire.")
            else:
                try:
                    partner = partners.supplier_of(organization, line["partner"])
                except ObjectDoesNotExist:
                    errors[services.line_error_key(index, "partner")] = _("Fournisseur inconnu.")
        lines.append(
            {
                "product": product,
                "proposed_product": line["proposed_product"],
                "declared_quantity": line["declared_quantity"],
                "received_quantity": line["received_quantity"],
                "unit_cost": line["unit_cost"],
                "partner": partner,
            }
        )
    if errors:
        raise ValidationError(errors)
    return {
        "supplier": supplier,
        "proposed_supplier": data["proposed_supplier"],
        "proposed_supplier_phone": data["proposed_supplier_phone"],
        "bought_on": data["bought_on"],
        "terms": data["terms"],
        "due_days": data["due_days"],
        "supplier_reference": data["supplier_reference"],
        "notes": data["notes"],
        "location": location,
        "boxes": data["boxes"],
        "lines": lines,
        "payments": data["payments"],
    }


class FieldPurchaseListView(PurchasingView, ListAPIView[FieldPurchase]):
    serializer_class = FieldPurchaseListSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[FieldPurchase]:
        filters = FieldPurchaseFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.field_purchases_of(
            self.organization, status=filters.validated_data.get("status"), search=filters.validated_data["search"]
        )

    @extend_schema(operation_id="listFieldPurchases", parameters=[FieldPurchaseFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """What drivers bought at the port, newest first, paginated, with lines, money given and what is left to pay.
        Filter by status (`submitted` = to check) or `search` (number, supplier, the supplier's paper number)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createFieldPurchase",
        request=FieldPurchaseCreateSerializer,
        responses={201: FieldPurchaseSerializer},
    )
    def post(self, request: Request) -> Response:
        """Type a purchase at the port for the office (a driver who phoned it in): it waits to be checked like one
        sent from the phone, and the person who types it is its buyer."""
        serializer = FieldPurchaseCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        fields = _field_purchase_fields(
            self.organization,
            dict(serializer.validated_data),
            is_owner=self.membership.role == Role.OWNER,
            kept_partners=set(),
        )
        purchase = services.submit_field_purchase(
            organization=self.organization, buyer=self.membership.user, fields=fields
        )
        return Response(
            FieldPurchaseSerializer(selectors.field_purchase_of(self.organization, purchase.pk)).data,
            status=status.HTTP_201_CREATED,
        )


class FieldPurchaseView(PurchasingView):
    def _purchase(self, purchase_id: int) -> FieldPurchase:
        try:
            return selectors.field_purchase_of(self.organization, purchase_id)
        except FieldPurchase.DoesNotExist:
            raise Http404 from None

    def _response(self, purchase_id: int) -> Response:
        return Response(FieldPurchaseSerializer(self._purchase(purchase_id)).data)


class FieldPurchaseDetailView(FieldPurchaseView):
    @extend_schema(operation_id="getFieldPurchase", responses=FieldPurchaseSerializer)
    def get(self, request: Request, purchase_id: int) -> Response:
        """One purchase with its revisions, each with what it changed."""
        return self._response(purchase_id)

    @extend_schema(
        operation_id="updateFieldPurchase", request=FieldPurchaseWriteSerializer, responses=FieldPurchaseSerializer
    )
    def put(self, request: Request, purchase_id: int) -> Response:
        """Change a purchase still to check (a new revision when anything changed); `confirm` validates it after:
        the kg received enter stock (a BR), what is owed for them is a posted invoice due by the deal (FF), and each
        sum given at the port is a payment (RF). `revision` must be the current one, else 400 on `revision`."""
        purchase = self._purchase(purchase_id)
        serializer = FieldPurchaseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        kept = {line.partner_id for line in purchase.lines.all() if line.partner_id is not None}
        fields = _field_purchase_fields(
            self.organization, data, is_owner=self.membership.role == Role.OWNER, kept_partners=kept
        )
        services.update_field_purchase(
            purchase=purchase,
            actor=self.membership.user,
            revision=data["revision"],
            fields=fields,
            office_note=data["office_note"],
            validate=data["confirm"],
        )
        return self._response(purchase_id)


class FieldPurchaseRefuseView(FieldPurchaseView):
    @extend_schema(
        operation_id="refuseFieldPurchase", request=FieldPurchaseRefuseSerializer, responses=FieldPurchaseSerializer
    )
    def post(self, request: Request, purchase_id: int) -> Response:
        """Turn a purchase down with the reason for the driver: nothing enters stock and nothing is owed. Final."""
        purchase = self._purchase(purchase_id)
        serializer = FieldPurchaseRefuseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.refuse_field_purchase(
            purchase=purchase,
            actor=self.membership.user,
            revision=serializer.validated_data["revision"],
            note=serializer.validated_data["office_note"],
        )
        return self._response(purchase_id)


# ---- Paying suppliers (P3-T12c, D-159) ----


class SupplierDebtsView(PurchasingView):
    @extend_schema(operation_id="getSupplierDebts", responses=SupplierDebtsSerializer)
    def get(self, request: Request) -> Response:
        """What the company owes each supplier for goods, biggest first: still to pay, overdue, due within 7 days,
        advances; and the cheques and traites given with a cashing day, from a week back on."""
        return Response(SupplierDebtsSerializer(selectors.supplier_debts(self.organization)).data)


class FieldPurchasePaperView(FieldPurchaseView):
    # Read by an <img> tag, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, purchase_id: int) -> FileResponse:
        """The photo of the supplier's paper of a purchase at the port."""
        purchase = self._purchase(purchase_id)
        if not purchase.paper:
            raise Http404
        response = FileResponse(purchase.paper.open("rb"), content_type="image/webp")
        # A new photo gets a new random file name, and the API answers its address again.
        response["Cache-Control"] = "private, max-age=3600"
        return response
