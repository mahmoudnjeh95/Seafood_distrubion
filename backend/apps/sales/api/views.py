import datetime as dt
from decimal import Decimal
from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import Http404
from django.utils import timezone
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.exceptions import PermissionDenied
from rest_framework.generics import ListAPIView
from rest_framework.permissions import SAFE_METHODS, BasePermission
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.catalog import selectors as catalog
from apps.core.api.pagination import PagedList
from apps.core.clock import moment_from_phone
from apps.core.models import Membership, Organization, Role
from apps.core.permissions import HasRole, IsDriver, IsOwnerOrManager, ReadOfficeWriteOwnerOrManager, membership_of
from apps.dayclose import selectors as dayclose
from apps.fleet import selectors as fleet
from apps.inventory import selectors as inventory
from apps.partners import selectors as partners
from apps.sales import selectors, services
from apps.sales.models import CreditNote, DeliveryStatus, Invoice, PriceSource, Quote, Sale, SaleStatus

from .serializers import (
    BatchSalesSerializer,
    CreditNoteFilterSerializer,
    CreditNoteSerializer,
    CreditNoteWriteSerializer,
    DeliverSerializer,
    FinanceSettingsOverviewSerializer,
    FinanceSettingsWriteSerializer,
    InvoiceChoicesSerializer,
    InvoiceCreateSerializer,
    InvoiceDetailSerializer,
    InvoiceFilterSerializer,
    InvoiceSerializer,
    NotDeliveredSerializer,
    QuoteConvertSerializer,
    QuoteDetailSerializer,
    QuoteFilterSerializer,
    QuoteRefuseSerializer,
    QuoteSerializer,
    QuoteWriteSerializer,
    SaleCancelSerializer,
    SaleConfirmSerializer,
    SaleDetailSerializer,
    SaleFilterSerializer,
    SaleSerializer,
    SaleWriteSerializer,
)


# Quotes are office documents (D-050): owner, manager and accountant read, owner and manager write, drivers
# get 403. Rows of the user's organization only (D-022). A comment, not a docstring: a docstring would
# describe every endpoint in the schema.
class OfficeView(APIView):
    permission_classes: tuple[type[BasePermission], ...] = (ReadOfficeWriteOwnerOrManager,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization


# ---- Quotes (P2-T03) ----


def may_approve_below_minimum(membership: Membership) -> bool:
    """Only the owner and the manager let a price go under a product's minimum, with a reason (D-193)."""
    return membership.role in (Role.OWNER, Role.MANAGER)


def _quote_fields(organization: Organization, data: dict[str, Any], *, may_approve: bool = False) -> dict[str, Any]:
    """The ids of a quote replaced by the rows they name in the organization; unknown ids are field errors.
    The reason to go under a minimum price counts only from someone who may approve it."""
    errors: dict[str, str] = {}
    fields = {key: value for key, value in data.items() if key != "send_now"}
    fields["below_minimum_reason"] = data["below_minimum_reason"] if may_approve else ""
    try:
        fields["customer"] = partners.customer_of(organization, data["customer"])
    except ObjectDoesNotExist:
        errors["customer"] = _("Client inconnu.")
    if data["location"] is not None:
        try:
            fields["location"] = inventory.location_of(organization, data["location"])
        except ObjectDoesNotExist:
            errors["location"] = _("Emplacement inconnu.")
    lines = []
    for index, line in enumerate(data["lines"]):
        try:
            product = catalog.product_of(organization, line["product"])
        except ObjectDoesNotExist:
            errors[services.line_error_key(index, "product")] = _("Produit inconnu.")
            continue
        batch = None
        if line.get("batch") is not None:
            try:
                batch = inventory.batch_of(organization, line["batch"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "batch")] = _("Lot inconnu.")
                continue
        lines.append({**line, "product": product, "batch": batch})
    if errors:
        raise ValidationError(errors)
    return {**fields, "lines": lines, "send": data["send_now"]}


def _quote_answer(organization: Organization, quote_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
    return Response(QuoteDetailSerializer(selectors.quote_of(organization, quote_id)).data, status=status_code)


class QuoteView(OfficeView):
    def quote(self, quote_id: int) -> Quote:
        try:
            return selectors.quote_of(self.organization, quote_id)
        except Quote.DoesNotExist:
            raise Http404 from None


class QuoteListView(QuoteView, ListAPIView[Quote]):
    serializer_class = QuoteSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Quote]:
        filters = QuoteFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.quotes_of(
            self.organization,
            status=filters.validated_data.get("status"),
            customer_id=filters.validated_data.get("customer"),
            date_from=filters.validated_data.get("date_from"),
            date_to=filters.validated_data.get("date_to"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listQuotes", parameters=[QuoteFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Quotes, newest first, paginated (`limit`, `offset`). Filter by status (a sent quote past its
        validity date counts as expired), customer, days (inclusive) or `search` (number, customer)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(operation_id="createQuote", request=QuoteWriteSerializer, responses={201: QuoteDetailSerializer})
    def post(self, request: Request) -> Response:
        """Prepare a quote (a draft), or with `send_now` mark it sent at once. A line without `unit_price`
        takes the sale price in force on the quote's day; without `valid_until` it is valid 3 days.
        Errors of a line come back on `lines.<index>.<field>`."""
        serializer = QuoteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _quote_fields(
            self.organization, serializer.validated_data, may_approve=may_approve_below_minimum(self.membership)
        )
        quote = services.create_quote(organization=self.organization, actor=self.membership.user, **data)
        return _quote_answer(self.organization, quote.pk, status_code=status.HTTP_201_CREATED)


class QuoteDetailView(QuoteView):
    @extend_schema(operation_id="getQuote", responses=QuoteDetailSerializer)
    def get(self, request: Request, quote_id: int) -> Response:
        """One quote with its lines and totals (without VAT until P2-T05)."""
        return _quote_answer(self.organization, self.quote(quote_id).pk)

    @extend_schema(operation_id="updateQuote", request=QuoteWriteSerializer, responses=QuoteDetailSerializer)
    def put(self, request: Request, quote_id: int) -> Response:
        """Change a draft (every line is replaced), and with `send_now` send it too. A sent quote no longer
        changes."""
        quote = self.quote(quote_id)
        serializer = QuoteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _quote_fields(
            self.organization, serializer.validated_data, may_approve=may_approve_below_minimum(self.membership)
        )
        services.update_quote(quote=quote, actor=self.membership.user, **data)
        return _quote_answer(self.organization, quote.pk)


class QuoteSendView(QuoteView):
    @extend_schema(operation_id="sendQuote", request=None, responses=QuoteDetailSerializer)
    def post(self, request: Request, quote_id: int) -> Response:
        """Mark a draft as given to the customer: it no longer changes. Refused once its validity date has
        passed."""
        services.send_quote(quote=self.quote(quote_id), actor=self.membership.user)
        return _quote_answer(self.organization, quote_id)


class QuoteAcceptView(QuoteView):
    @extend_schema(operation_id="acceptQuote", request=None, responses=QuoteDetailSerializer)
    def post(self, request: Request, quote_id: int) -> Response:
        """Record the customer's yes on a sent quote, up to its validity date included. No stock is
        reserved; the sale comes from it in P2-T04."""
        services.accept_quote(quote=self.quote(quote_id), actor=self.membership.user)
        return _quote_answer(self.organization, quote_id)


class QuoteRefuseView(QuoteView):
    @extend_schema(operation_id="refuseQuote", request=QuoteRefuseSerializer, responses=QuoteDetailSerializer)
    def post(self, request: Request, quote_id: int) -> Response:
        """Record the customer's no on a sent quote, with an optional reason."""
        serializer = QuoteRefuseSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.refuse_quote(
            quote=self.quote(quote_id), actor=self.membership.user, reason=serializer.validated_data["reason"]
        )
        return _quote_answer(self.organization, quote_id)


# ---- Sales (P2-T04) ----

SELLER_ROLES = frozenset({Role.OWNER, Role.MANAGER, Role.DRIVER})


class SalesPermission(HasRole):
    """Owners, managers and the accountant read sales; owners, managers and drivers sell. What a driver may
    see and where they may sell is checked by the views (their own sales, their truck of the day)."""

    roles = frozenset({Role.OWNER, Role.MANAGER, Role.ACCOUNTANT, Role.DRIVER})

    def has_permission(self, request: Request, view: APIView) -> bool:
        if not super().has_permission(request, view):
            return False
        membership = membership_of(request)
        return request.method in SAFE_METHODS or (membership is not None and membership.role in SELLER_ROLES)


def _payment(data: dict[str, Any], *, driver: bool) -> services.PaymentFields | None:
    """What a driver's phone says was paid on the spot (D-133). The office types no payment: its money comes in
    through a règlement of the treasury (D-245), so a payment typed there is refused, and `None` leaves the sale
    unpaid (or keeps what a draft already says, see `services.update_sale`)."""
    if not driver:
        if data["paid_in_full"] or data["amount_paid"] not in (None, "") or data["payment_method"]:
            raise ValidationError(
                {"detail": _("Le paiement d'une vente se saisit dans Règlements clients (trésorerie).")}
            )
        return None
    return {
        "amount_paid": data["amount_paid"],
        "paid_in_full": data["paid_in_full"],
        "payment_method": data["payment_method"],
        "payment_reference": data["payment_reference"],
    }


class SaleView(OfficeView):
    permission_classes: tuple[type[BasePermission], ...] = (SalesPermission,)

    @property
    def is_driver(self) -> bool:
        return self.membership.role == Role.DRIVER

    def sales(self) -> QuerySet[Sale]:
        # A driver sees the sales they made, nothing else.
        created_by_id = self.membership.user_id if self.is_driver else None
        return selectors.sales_of(
            self.organization, created_by_id=created_by_id, load_location_id=self.driver_truck_location()
        )

    def driver_truck_location(self) -> int | None:
        """The place of the driver's truck of the day: the BL prepared with its load are theirs to deliver (D-160)."""
        if not self.is_driver:
            return None
        truck = fleet.truck_of_driver(self.membership)
        return truck.location_id if truck is not None else None

    def sale(self, sale_id: int) -> Sale:
        try:
            return self.sales().get(pk=sale_id)
        except Sale.DoesNotExist:
            raise Http404 from None

    def answer(self, sale_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
        data = SaleDetailSerializer(self.sale(sale_id), context={"show_costs": not self.is_driver}).data
        return Response(data, status=status_code)

    def check_location(
        self, location_id: int, on: dt.date | None = None, *, made_at: dt.datetime | None = None
    ) -> None:
        """A driver sells only from the truck of their day (D-042, D-046): today, or `on` for a sale made on an
        earlier day and sent later (D-133). And only on a day that takes the sale (D-134): the driver's day
        that covers the moment the sale was made (`made_at`, now by default) must not have been sent before
        that moment, nor be approved by the office (D-094)."""
        if not fleet.may_use_location(self.membership, location_id, on):
            if on is None or on == timezone.localdate():
                raise PermissionDenied(_("Un chauffeur ne vend que depuis son camion du jour."))
            raise PermissionDenied(
                _("Ce camion n'était pas le vôtre le %(day)s : la vente n'est pas enregistrée.")
                % {"day": on.strftime("%d/%m/%Y")}
            )
        dayclose.refuse_sale_outside_day(self.membership, made_at)

    def sale_fields(self, data: dict[str, Any], *, new: bool = False) -> dict[str, Any]:
        """The ids of a sale replaced by the rows they name in the organization; unknown ids are field errors.
        `new` is a sale being created: only then does a driver's phone say when it was made (D-133)."""
        errors: dict[str, str] = {}
        organization = self.organization
        sold_at: dt.datetime | None = data["sold_at"]
        made_on: dt.date | None = None
        if self.is_driver:
            # The sale is dated when it was made, as the phone says, once checked: not in the future, on a day
            # the driver had this truck and the office has not approved. Without a time, or for a draft being
            # changed, the moment stays the server's.
            sold_at = moment_from_phone(sold_at) if new else None
            made_on = timezone.localtime(sold_at).date() if sold_at is not None else None
        self.check_location(data["location"], made_on, made_at=sold_at if self.is_driver else None)
        fields: dict[str, Any] = {
            "customer": None,
            "notes": data["notes"],
            "payment": _payment(data, driver=self.is_driver),
            "sold_at": sold_at,
        }
        if data["customer"] is not None:
            try:
                fields["customer"] = partners.customer_of(organization, data["customer"])
            except ObjectDoesNotExist:
                errors["customer"] = _("Client inconnu.")
        try:
            fields["location"] = inventory.location_of(organization, data["location"])
        except ObjectDoesNotExist:
            errors["location"] = _("Emplacement inconnu.")
        lines = []
        for index, line in enumerate(data["lines"]):
            try:
                product = catalog.product_of(organization, line["product"])
            except ObjectDoesNotExist:
                errors[services.line_error_key(index, "product")] = _("Produit inconnu.")
                continue
            batch = None
            if line.get("batch") is not None:
                try:
                    batch = inventory.batch_of(organization, line["batch"])
                except ObjectDoesNotExist:
                    errors[services.line_error_key(index, "batch")] = _("Lot inconnu.")
                    continue
            picks = []
            for pick in line["picks"]:
                try:
                    pick_batch = inventory.batch_of(organization, pick["batch"])
                except ObjectDoesNotExist:
                    errors[services.line_error_key(index, "picks")] = _("Lot inconnu.")
                    break
                picks.append({"batch": pick_batch, "quantity": pick["quantity"]})
            lines.append({**line, "product": product, "batch": batch, "picks": picks})
        if errors:
            raise ValidationError(errors)
        return {
            **fields,
            "lines": lines,
            "confirm": data["confirm_now"],
            "approve_credit": self.may_approve_credit(data["approve_credit"]),
            "boxes": data["boxes"],
            "delivery_address": data["delivery_address"],
            "below_minimum_reason": data["below_minimum_reason"] if may_approve_below_minimum(self.membership) else "",
        }

    def may_approve_credit(self, asked: bool) -> bool:
        """Only the owner and the manager may accept a sale above a customer's credit limit (D-062)."""
        if asked and self.is_driver:
            raise PermissionDenied(_("Seul le propriétaire ou le gérant approuve un dépassement de crédit."))
        return asked

    def check_own_place(self, sale: Sale) -> None:
        if self.is_driver:
            self.check_location(sale.location_id)


class SaleListView(SaleView, ListAPIView[Sale]):
    serializer_class = SaleSerializer
    pagination_class = PagedList

    def get_serializer_context(self) -> dict[str, Any]:
        return {**super().get_serializer_context(), "show_costs": not self.is_driver}

    def get_queryset(self) -> QuerySet[Sale]:
        filters = SaleFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.sales_of(
            self.organization,
            status=filters.validated_data.get("status"),
            customer_id=filters.validated_data.get("customer"),
            location_id=filters.validated_data.get("location"),
            uninvoiced=filters.validated_data["uninvoiced"],
            delivery_status=filters.validated_data.get("delivery_status"),
            created_by_id=self.membership.user_id if self.is_driver else None,
            load_location_id=self.driver_truck_location(),
            date_from=filters.validated_data.get("date_from"),
            date_to=filters.validated_data.get("date_to"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listSales", parameters=[SaleFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Sales, newest first, paginated (`limit`, `offset`). Filter by status, customer, place, days of the
        sale (inclusive) or `search` (number, customer). A driver sees only their own sales, without costs."""
        return super().get(request, *args, **kwargs)

    @extend_schema(operation_id="createSale", request=SaleWriteSerializer, responses={201: SaleDetailSerializer})
    def post(self, request: Request) -> Response:
        """Type a sale (a draft), or with `confirm_now` confirm it at once: the stock leaves oldest batch first
        and the customer owes what is not paid. Without `customer` it is the walk-in customer (counter sale).
        The office types no payment: the money comes in through a règlement of the treasurer. A driver's phone says
        what was paid. A line without `unit_price` takes the customer's price in force at `sold_at`.
        Errors of a line come back on `lines.<index>.<field>`. A driver sells only from their truck of the
        day. A driver's phone sends in `sold_at` when the sale was made: the sale takes that date and that
        day's price, also when it was kept without connection and sent later. Within 5 minutes of the
        server's clock the server's own time is used; further in the future is refused (400), as is a day the
        office has approved or a truck the driver did not have that day (403), and stock the truck has not
        held since that day (400)."""
        serializer = SaleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # A phone that lost the answer sends the same sale again: it gets the sale back, even if the day has been
        # approved since (D-094). Checked before the day and the time, or the retry would be refused as a new sale.
        recorded = selectors.sale_by_client_uuid(self.organization, serializer.validated_data["client_uuid"])
        if recorded is not None:
            return self.answer(recorded.pk, status_code=status.HTTP_201_CREATED)
        data = self.sale_fields(serializer.validated_data, new=True)
        sale = services.create_sale(
            organization=self.organization,
            actor=self.membership.user,
            client_uuid=serializer.validated_data["client_uuid"],
            # A phone's time is checked against the ledger too: the truck must have held the kilos since.
            stock_held_since=self.is_driver,
            # A phone sends the price it showed: the server checks it was a real price (P3-T02).
            typed_source=PriceSource.SHOWN if self.is_driver else PriceSource.TYPED,
            **data,
        )
        return self.answer(sale.pk, status_code=status.HTTP_201_CREATED)


class SaleDetailView(SaleView):
    @extend_schema(operation_id="getSale", responses=SaleDetailSerializer)
    def get(self, request: Request, sale_id: int) -> Response:
        """One sale with its lines and, once confirmed, the lots each line came from with their cost (not
        shown to drivers). Totals are without VAT until P2-T05."""
        return self.answer(self.sale(sale_id).pk)

    @extend_schema(operation_id="updateSale", request=SaleWriteSerializer, responses=SaleDetailSerializer)
    def put(self, request: Request, sale_id: int) -> Response:
        """Change a draft (every line is replaced), and with `confirm_now` confirm it too. A confirmed sale no
        longer changes: cancel it instead."""
        sale = self.sale(sale_id)
        self.check_own_place(sale)
        serializer = SaleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = self.sale_fields(serializer.validated_data)
        services.update_sale(sale=sale, actor=self.membership.user, **data)
        return self.answer(sale.pk)


class SaleConfirmView(SaleView):
    @extend_schema(operation_id="confirmSale", request=SaleConfirmSerializer, responses=SaleDetailSerializer)
    def post(self, request: Request, sale_id: int) -> Response:
        """Confirm a draft: the stock leaves oldest batch first and the customer owes what is not paid. Refused
        as a whole when the place holds too little (`lines.<index>.quantity`) or, under the company's "block"
        policy, when the customer would go above their credit limit (`credit_limit`). Under the "approval"
        policy the sale stays a draft with `credit_status` pending until the owner or a manager confirms it
        with `approve_credit`."""
        serializer = SaleConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        sale = self.sale(sale_id)
        self.check_own_place(sale)
        services.confirm_sale(
            sale=sale,
            actor=self.membership.user,
            approve_credit=self.may_approve_credit(serializer.validated_data["approve_credit"]),
        )
        return self.answer(sale_id)


class SaleCancelView(SaleView):
    permission_classes = (IsOwnerOrManager,)

    @extend_schema(operation_id="cancelSale", request=SaleCancelSerializer, responses=SaleDetailSerializer)
    def post(self, request: Request, sale_id: int) -> Response:
        """Cancel a sale (owner or manager). A confirmed sale needs a reason: its kilos come back to the same
        lots at the same place; the sale stays, marked cancelled."""
        serializer = SaleCancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.cancel_sale(
            sale=self.sale(sale_id), actor=self.membership.user, reason=serializer.validated_data["reason"]
        )
        return self.answer(sale_id)


class QuoteConvertView(QuoteView):
    @extend_schema(
        operation_id="convertQuoteToSale", request=QuoteConvertSerializer, responses={201: SaleDetailSerializer}
    )
    def post(self, request: Request, quote_id: int) -> Response:
        """Turn an accepted quote, still valid, into a sale (a draft, or confirmed with `confirm_now`): same
        customer, products, prices and discounts, from the quote's place unless `location` is given. Without
        `lines` it takes every kilo not on a BL yet; with `lines`, the kg given per quote line, at most what is
        left (a quote may be delivered in several BL, D-115). The quote stays accepted and links to its sales."""
        quote = self.quote(quote_id)
        serializer = QuoteConvertSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        location = None
        if data["location"] is not None:
            try:
                location = inventory.location_of(self.organization, data["location"])
            except ObjectDoesNotExist:
                raise ValidationError({"location": _("Emplacement inconnu.")}) from None
        sale = services.create_sale_from_quote(
            quote=quote,
            actor=self.membership.user,
            location=location,
            sold_at=data["sold_at"],
            payment=_payment(data, driver=False),
            confirm=data["confirm_now"],
            lines=data["lines"],
        )
        detail = SaleDetailSerializer(selectors.sale_of(self.organization, sale.pk)).data
        return Response(detail, status=status.HTTP_201_CREATED)


class BatchSalesView(OfficeView):
    @extend_schema(operation_id="getBatchSales", responses=BatchSalesSerializer)
    def get(self, request: Request, batch_id: int) -> Response:
        """What one lot sold over its confirmed sales: kg, revenue without VAT, cost of the goods and margin,
        then each sale line that took from it (oldest first). Office data: drivers get 403."""
        try:
            batch = inventory.batch_of(self.organization, batch_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        totals = selectors.batch_sales_totals(self.organization, batch_ids=[batch.pk]).get(batch.pk)
        zero = Decimal("0.000")
        data = {
            "batch_id": batch.pk,
            "quantity": totals.quantity if totals else zero,
            "revenue": totals.revenue if totals else zero,
            "cost": totals.cost if totals else zero,
            "margin": totals.margin if totals else zero,
            "rows": selectors.batch_sales(self.organization, batch_id=batch.pk),
        }
        return Response(BatchSalesSerializer(data).data)


# ---- Finance settings (P2-T05, D-056) ----


class FinanceSettingsView(OfficeView):
    def overview(self) -> Response:
        organization = self.organization
        in_force = selectors.finance_settings_on(organization) or services.ensure_finance_settings(
            organization=organization
        )
        data = {
            "in_force": in_force,
            "history": selectors.finance_settings_history(organization),
            "may_edit": self.membership.role == Role.OWNER,
        }
        return Response(FinanceSettingsOverviewSerializer(data).data)

    @extend_schema(operation_id="getFinanceSettings", responses=FinanceSettingsOverviewSerializer)
    def get(self, request: Request) -> Response:
        """The finance settings in force today (VAT rate, fiscal stamp, prices with or without VAT, withholding
        rate, the seller printed on invoices) and every version with its start day. Office roles read."""
        return self.overview()

    @extend_schema(
        operation_id="saveFinanceSettings",
        request=FinanceSettingsWriteSerializer,
        responses=FinanceSettingsOverviewSerializer,
    )
    def post(self, request: Request) -> Response:
        """A new version of the finance settings from `valid_from` (today when empty; the past is refused). The
        owner only: a manager gets 403. Saving again for the same day replaces that day's version."""
        if self.membership.role != Role.OWNER:
            raise PermissionDenied(_("Seul le propriétaire change les paramètres financiers."))
        serializer = FinanceSettingsWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.save_finance_settings(
            organization=self.organization, actor=self.membership.user, **serializer.validated_data
        )
        return self.overview()


# ---- Invoices and credit notes (P2-T05, D-057) ----


def _invoice_choices(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "apply_vat": data["apply_vat"],
        "vat_rates": [line["vat_rate"] for line in data["lines"]] or None,
        "vat_amounts": {row["rate"]: row["amount"] for row in data["vat_amounts"]},
        "fiscal_stamp": data["fiscal_stamp"],
        "fees": data["fees"],
        "withholding_applied": data["withholding_applied"],
        "withholding_rate": data["withholding_rate"],
        "notes": data["notes"],
    }


class InvoiceView(OfficeView):
    def invoice(self, invoice_id: int) -> Invoice:
        try:
            return selectors.invoice_of(self.organization, invoice_id)
        except Invoice.DoesNotExist:
            raise Http404 from None

    def answer(self, invoice_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
        invoice = self.invoice(invoice_id)
        context = {"credited": selectors.credited_by_line(invoice)}
        return Response(InvoiceDetailSerializer(invoice, context=context).data, status=status_code)


class InvoiceListView(InvoiceView, ListAPIView[Invoice]):
    serializer_class = InvoiceSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Invoice]:
        filters = InvoiceFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.invoices_of(
            self.organization,
            status=filters.validated_data.get("status"),
            customer_id=filters.validated_data.get("customer"),
            sale_id=filters.validated_data.get("sale"),
            date_from=filters.validated_data.get("date_from"),
            date_to=filters.validated_data.get("date_to"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listInvoices", parameters=[InvoiceFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Invoices, drafts first then the newest issued, paginated (`limit`, `offset`). Filter by status,
        customer, sale, issue days (inclusive) or `search` (number, sale number, customer). Office roles read."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createInvoice", request=InvoiceCreateSerializer, responses={201: InvoiceDetailSerializer}
    )
    def post(self, request: Request) -> Response:
        """Prepare the invoice of a confirmed sale (a draft without number), or with `issue_now` issue it at
        once. VAT, stamp and withholding are proposed from the finance settings and each product's own rate;
        `apply_vat` false makes an invoice without VAT, and every typed value is flagged and audited. Errors:
        `lines.<index>.vat_rate`, `vat_amounts.<rate>`, `fiscal_stamp`, `fees`, `withholding_rate`."""
        serializer = InvoiceCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        ids = list(dict.fromkeys([*([data["sale"]] if "sale" in data else []), *data.get("sales", [])]))
        if not ids:
            raise ValidationError({"sales": _("Choisissez au moins un bon de livraison à facturer.")})
        try:
            sales = [selectors.sale_of(self.organization, sale_id) for sale_id in ids]
        except Sale.DoesNotExist:
            raise ValidationError({"sales": _("Vente inconnue.")}) from None
        invoice = services.create_invoice(
            sales=sales, actor=self.membership.user, issue=data["issue_now"], **_invoice_choices(data)
        )
        return self.answer(invoice.pk, status_code=status.HTTP_201_CREATED)


class InvoiceDetailView(InvoiceView):
    @extend_schema(operation_id="getInvoice", responses=InvoiceDetailSerializer)
    def get(self, request: Request, invoice_id: int) -> Response:
        """One invoice as printed: seller, customer, lines, VAT per rate, stamp, totals, withholding and its
        credit notes. A draft shows the values the settings propose beside the typed ones."""
        return self.answer(self.invoice(invoice_id).pk)

    @extend_schema(operation_id="updateInvoice", request=InvoiceChoicesSerializer, responses=InvoiceDetailSerializer)
    def put(self, request: Request, invoice_id: int) -> Response:
        """Change a draft (every value given again; empty takes the settings), and with `issue_now` issue it.
        An issued invoice never changes: make a credit note."""
        invoice = self.invoice(invoice_id)
        serializer = InvoiceChoicesSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        services.update_invoice(
            invoice=invoice, actor=self.membership.user, issue=data["issue_now"], **_invoice_choices(data)
        )
        return self.answer(invoice_id)

    @extend_schema(operation_id="deleteInvoice", request=None, responses={204: None})
    def delete(self, request: Request, invoice_id: int) -> Response:
        """Throw a draft away (it has no number yet). An issued invoice is never deleted."""
        services.delete_invoice(invoice=self.invoice(invoice_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class InvoiceIssueView(InvoiceView):
    @extend_schema(operation_id="issueInvoice", request=None, responses=InvoiceDetailSerializer)
    def post(self, request: Request, invoice_id: int) -> Response:
        """Issue a draft: the next number of the year (FA-2026-0001...), today's date, the settings in force now
        for what was not typed, seller and customer copied. From then on it never changes. Nothing is sent to
        TTN / El Fatoora (D-016)."""
        services.issue_invoice(invoice=self.invoice(invoice_id), actor=self.membership.user)
        return self.answer(invoice_id)


class InvoiceCreditNoteView(InvoiceView):
    @extend_schema(
        operation_id="createCreditNote", request=CreditNoteWriteSerializer, responses={201: CreditNoteSerializer}
    )
    def post(self, request: Request, invoice_id: int) -> Response:
        """Correct an issued invoice with a credit note (AV-2026-0001...), the only correction. `full` gives back
        everything left and cancels the invoice; `partial` gives back, per line, kilos (`quantity`) or an
        amount without VAT (`amount`), with the line's VAT. `stock` says what happens to the kilos given back:
        `none` (nothing moves), `restock` (back in the sale's place, on the batches they left) or `loss`
        (back, then written off on the same lot). Errors: `lines.<index>.<field>`, `reason`, `stock`."""
        invoice = self.invoice(invoice_id)
        serializer = CreditNoteWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        by_id = {line.pk: line for line in invoice.lines.all()}
        lines: list[services.CreditLineFields] = [
            {"invoice_line": by_id.get(row["invoice_line"]), "quantity": row["quantity"], "amount": row["amount"]}
            for row in data["lines"]
        ]
        note = services.create_credit_note(
            invoice=invoice,
            actor=self.membership.user,
            kind=data["kind"],
            reason=data["reason"],
            lines=lines,
            stock=data["stock"],
        )
        detail = CreditNoteSerializer(selectors.credit_notes_of(self.organization).get(pk=note.pk)).data
        return Response(detail, status=status.HTTP_201_CREATED)


class CreditNoteListView(OfficeView, ListAPIView[CreditNote]):
    serializer_class = CreditNoteSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[CreditNote]:
        filters = CreditNoteFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        return selectors.credit_notes_of(
            self.organization,
            customer_id=filters.validated_data.get("customer"),
            date_from=filters.validated_data.get("date_from"),
            date_to=filters.validated_data.get("date_to"),
            search=filters.validated_data["search"],
        )

    @extend_schema(operation_id="listCreditNotes", parameters=[CreditNoteFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Credit notes, newest first, paginated, with their invoice and lines. Filter by customer, days or
        `search` (number, invoice number, customer)."""
        return super().get(request, *args, **kwargs)


class CreditNoteDetailView(OfficeView):
    @extend_schema(operation_id="getCreditNote", responses=CreditNoteSerializer)
    def get(self, request: Request, credit_note_id: int) -> Response:
        """One credit note with its invoice and lines."""
        try:
            note = selectors.credit_notes_of(self.organization).get(pk=credit_note_id)
        except CreditNote.DoesNotExist:
            raise Http404 from None
        return Response(CreditNoteSerializer(note).data)


class MyDeliveriesView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="listMyDeliveries", responses=SaleDetailSerializer(many=True))
    def get(self, request: Request) -> Response:
        """The BL prepared for the driver's truck with its load, still to deliver, oldest first, each with its
        client, address, products and boxes. Delivering one (`deliverMyDelivery`) is the sale (D-160, D-178)."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        truck = fleet.truck_of_driver(membership)
        if truck is None:
            raise Http404
        sales = selectors.sales_of(
            membership.organization,
            status=SaleStatus.DRAFT,
            delivery_status=DeliveryStatus.TO_DELIVER,
            location_id=truck.location_id,
        ).order_by("sold_at", "id")
        return Response(SaleDetailSerializer(sales, many=True, context={"show_costs": False}).data)


class MyDeliveryView(APIView):
    """One BL of the driver's truck to deliver (D-178); a retry finds the delivery it already recorded."""

    permission_classes = (IsDriver,)

    def delivery(self, membership: Membership, sale_id: int, client_uuid: Any) -> tuple[Sale, bool]:
        """The BL, and whether this request was already recorded (a retry of the phone)."""
        recorded = services.delivery_by_uuid(membership.organization, client_uuid)
        if recorded is not None and recorded.pk == sale_id:
            return recorded, True
        truck = fleet.truck_of_driver(membership)
        if truck is None:
            raise Http404
        try:
            sale = selectors.sales_of(membership.organization, location_id=truck.location_id).get(
                pk=sale_id, transfer__isnull=False
            )
        except Sale.DoesNotExist:
            raise Http404 from None
        # A day already sent or approved takes nothing more (D-134, D-094).
        dayclose.refuse_sale_outside_day(membership, None)
        return sale, False

    def answer(self, membership: Membership, sale_id: int) -> Response:
        sale = selectors.sale_of(membership.organization, sale_id)
        return Response(SaleDetailSerializer(sale, context={"show_costs": False}).data)


class MyDeliveryDeliverView(MyDeliveryView):
    @extend_schema(operation_id="deliverMyDelivery", request=DeliverSerializer, responses=SaleDetailSerializer)
    def post(self, request: Request, sale_id: int) -> Response:
        """Deliver a BL of the load: send only the lines that changed (`lines`: kg delivered, zero takes the
        product off), the boxes left and what the client paid. Only the kg delivered leave the truck and are owed;
        the rest stays on the truck. Nothing delivered is "not delivered". Errors of a line come back on
        `lines.<index>.<field>`."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = DeliverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sale, recorded = self.delivery(membership, sale_id, data["client_uuid"])
        if not recorded:
            services.deliver_sale(
                sale=sale,
                actor=membership.user,
                lines=data["lines"],
                boxes=data["boxes"],
                note=data["note"],
                payment=_payment(data, driver=True),
                delivery_uuid=data["client_uuid"],
            )
        return self.answer(membership, sale_id)


class MyDeliveryNotDeliveredView(MyDeliveryView):
    @extend_schema(
        operation_id="notDeliveredMyDelivery", request=NotDeliveredSerializer, responses=SaleDetailSerializer
    )
    def post(self, request: Request, sale_id: int) -> Response:
        """The BL is not delivered (refused, closed): nothing is sold, the goods and boxes stay on the truck and go
        back to the cold room with the return. The note is optional."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        serializer = NotDeliveredSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        sale, recorded = self.delivery(membership, sale_id, data["client_uuid"])
        if not recorded:
            services.cancel_delivery(
                sale=sale, actor=membership.user, note=data["note"], delivery_uuid=data["client_uuid"]
            )
        return self.answer(membership, sale_id)
