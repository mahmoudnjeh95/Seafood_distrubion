from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db.models import QuerySet
from django.http import FileResponse, Http404
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

from apps.core.api.pagination import PagedList
from apps.core.clock import moment_from_phone
from apps.core.models import Membership, Organization, Role
from apps.core.permissions import IsDriver, ReadOfficeWriteOwnerOrManager, membership_of
from apps.dayclose import selectors as dayclose
from apps.expenses import selectors, services
from apps.expenses.models import DayLabourEntry, DayLabourer, Expense, ExpenseCategory, ExpensePaymentMethod
from apps.fleet import selectors as fleet
from apps.inventory import selectors as inventory

from .serializers import (
    DayLabourEntrySerializer,
    DayLabourerFilterSerializer,
    DayLabourerSerializer,
    DayLabourerWriteSerializer,
    DayLabourFilterSerializer,
    DayLabourWriteSerializer,
    ExpenseCategoryFilterSerializer,
    ExpenseCategorySerializer,
    ExpenseCategoryUpdateSerializer,
    ExpenseCategoryWriteSerializer,
    ExpenseDetailSerializer,
    ExpenseFilterSerializer,
    ExpenseReceiptSerializer,
    ExpenseRejectSerializer,
    ExpenseSerializer,
    ExpenseTotalsSerializer,
    ExpenseWriteSerializer,
    LotCostFilterSerializer,
    LotCostsSerializer,
    RoadCategorySerializer,
    RoadExpenseSerializer,
    RoadExpenseWriteSerializer,
)


# Expenses are office documents (D-053): owner, manager and accountant read, owner and manager write and
# approve, drivers get 403 until their phone screen (P3-T04). Rows of the user's organization only (D-022).
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


def _require_owner(membership: Membership) -> None:
    """The owner alone adds, renames and archives categories (checked here, D-053)."""
    if membership.role != Role.OWNER:
        raise PermissionDenied(_("Seul le propriétaire gère les catégories de dépenses."))


# ---- Categories (P5-T01) ----


class ExpenseCategoryListView(OfficeView):
    @extend_schema(
        operation_id="listExpenseCategories",
        parameters=[ExpenseCategoryFilterSerializer],
        responses=ExpenseCategorySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Expense categories: the default ones first, in the brief's order, then the owner's."""
        filters = ExpenseCategoryFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        categories = selectors.categories_of(self.organization, status=filters.validated_data["status"])
        return Response(ExpenseCategorySerializer(categories, many=True).data)

    @extend_schema(
        operation_id="createExpenseCategory",
        request=ExpenseCategoryWriteSerializer,
        responses={201: ExpenseCategorySerializer},
    )
    def post(self, request: Request) -> Response:
        """Add a category (owner only)."""
        _require_owner(self.membership)
        serializer = ExpenseCategoryWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.create_category(
            organization=self.organization,
            actor=self.membership.user,
            name=serializer.validated_data["name"],
            for_drivers=serializer.validated_data["for_drivers"],
        )
        return Response(ExpenseCategorySerializer(category).data, status=status.HTTP_201_CREATED)


class ExpenseCategoryDetailView(OfficeView):
    @extend_schema(
        operation_id="updateExpenseCategory",
        request=ExpenseCategoryUpdateSerializer,
        responses=ExpenseCategorySerializer,
    )
    def patch(self, request: Request, category_id: int) -> Response:
        """Rename a category or archive it (owner only). A default category is never archived."""
        _require_owner(self.membership)
        try:
            category = selectors.category_of(self.organization, category_id)
        except ExpenseCategory.DoesNotExist:
            raise Http404 from None
        serializer = ExpenseCategoryUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        category = services.update_category(category=category, actor=self.membership.user, **serializer.validated_data)
        return Response(ExpenseCategorySerializer(category).data)

    @extend_schema(operation_id="deleteExpenseCategory", responses={204: None})
    def delete(self, request: Request, category_id: int) -> Response:
        """Remove a category never used (owner only, D-205); a used one is archived instead."""
        _require_owner(self.membership)
        try:
            category = selectors.category_of(self.organization, category_id)
        except ExpenseCategory.DoesNotExist:
            raise Http404 from None
        services.delete_category(category=category, actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- Expenses (P5-T01) ----


def _expense_fields(organization: Organization, data: dict[str, Any]) -> dict[str, Any]:
    """The ids of an expense replaced by the rows they name in the organization; unknown ids are field errors."""
    errors: dict[str, str] = {}
    fields = {key: value for key, value in data.items() if key != "approve_now"}
    try:
        fields["category"] = selectors.category_of(organization, data["category"])
    except ObjectDoesNotExist:
        errors["category"] = _("Catégorie inconnue.")
    if data["batch"] is not None:
        try:
            fields["batch"] = inventory.batch_of(organization, data["batch"])
        except ObjectDoesNotExist:
            errors["batch"] = _("Lot inconnu.")
    if data["truck"] is not None:
        try:
            fields["truck"] = fleet.truck_of(organization, data["truck"])
        except ObjectDoesNotExist:
            errors["truck"] = _("Camion inconnu.")
    if errors:
        raise DjangoValidationError(errors)
    return {**fields, "approve": data["approve_now"]}


def _expense_answer(organization: Organization, expense_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
    expense = selectors.expense_of(organization, expense_id)
    shares = selectors.truck_day_shares(organization, expenses=[expense]).get(expense.pk, [])
    return Response(ExpenseDetailSerializer(expense, context={"shares": shares}).data, status=status_code)


class ExpenseView(OfficeView):
    def expense(self, expense_id: int) -> Expense:
        try:
            return selectors.expense_of(self.organization, expense_id)
        except Expense.DoesNotExist:
            raise Http404 from None

    def filtered(self) -> QuerySet[Expense]:
        filters = ExpenseFilterSerializer(data=self.request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        return selectors.expenses_of(
            self.organization,
            status=data.get("status"),
            category_id=data.get("category"),
            batch_id=data.get("batch"),
            truck_id=data.get("truck"),
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            search=data["search"],
        )


class ExpenseListView(ExpenseView, ListAPIView[Expense]):
    serializer_class = ExpenseSerializer
    pagination_class = PagedList

    def get_queryset(self) -> QuerySet[Expense]:
        return self.filtered()

    @extend_schema(operation_id="listExpenses", parameters=[ExpenseFilterSerializer])
    def get(self, request: Request, *args: object, **kwargs: object) -> Response:
        """Expenses, newest day first, paginated (`limit`, `offset`). Filter by status, category, lot,
        truck, days (inclusive) or `search` (number, description, payee, lot number)."""
        return super().get(request, *args, **kwargs)

    @extend_schema(
        operation_id="createExpense", request=ExpenseWriteSerializer, responses={201: ExpenseDetailSerializer}
    )
    def post(self, request: Request) -> Response:
        """Record an expense as a draft, or with `approve_now` approved at once. `batch` charges it to a
        lot; `truck` makes it a truck cost of that day, split over the lots loaded that day by kg. A day
        labourer's day is recorded in the day-labour calendar instead."""
        serializer = ExpenseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _expense_fields(self.organization, serializer.validated_data)
        expense = services.create_expense(organization=self.organization, actor=self.membership.user, **data)
        return _expense_answer(self.organization, expense.pk, status_code=status.HTTP_201_CREATED)


class ExpenseTotalsView(ExpenseView):
    @extend_schema(
        operation_id="getExpenseTotals", parameters=[ExpenseFilterSerializer], responses=ExpenseTotalsSerializer
    )
    def get(self, request: Request) -> Response:
        """How many expenses the same filters as `listExpenses` keep, and their totals: approved, and still
        waiting (drafts and sent for approval)."""
        return Response(ExpenseTotalsSerializer(selectors.expense_totals(self.filtered())).data)


class ExpenseDetailView(ExpenseView):
    @extend_schema(operation_id="getExpense", responses=ExpenseDetailSerializer)
    def get(self, request: Request, expense_id: int) -> Response:
        """One expense; a truck cost of the day comes with its split over the lots loaded that day."""
        return _expense_answer(self.organization, self.expense(expense_id).pk)

    @extend_schema(operation_id="updateExpense", request=ExpenseWriteSerializer, responses=ExpenseDetailSerializer)
    def put(self, request: Request, expense_id: int) -> Response:
        """Correct a draft or an expense waiting for approval; with `approve_now`, approve it too. An approved
        or refused expense never changes: a correction is a new expense."""
        expense = self.expense(expense_id)
        serializer = ExpenseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _expense_fields(self.organization, serializer.validated_data)
        services.update_expense(expense=expense, actor=self.membership.user, **data)
        return _expense_answer(self.organization, expense.pk)

    @extend_schema(operation_id="deleteExpense", responses={204: None})
    def delete(self, request: Request, expense_id: int) -> Response:
        """Delete a draft typed by mistake. An expense sent for approval is refused instead."""
        services.delete_expense(expense=self.expense(expense_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class ExpenseApproveView(ExpenseView):
    @extend_schema(operation_id="approveExpense", request=None, responses=ExpenseDetailSerializer)
    def post(self, request: Request, expense_id: int) -> Response:
        """Approve a draft or a waiting expense (owner or manager): it counts in the costs from now on."""
        services.approve_expense(expense=self.expense(expense_id), actor=self.membership.user)
        return _expense_answer(self.organization, expense_id)


class ExpenseRejectView(ExpenseView):
    @extend_schema(operation_id="rejectExpense", request=ExpenseRejectSerializer, responses=ExpenseDetailSerializer)
    def post(self, request: Request, expense_id: int) -> Response:
        """Refuse a draft or a waiting expense, saying why. It never counts."""
        expense = self.expense(expense_id)
        serializer = ExpenseRejectSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.reject_expense(expense=expense, actor=self.membership.user, reason=serializer.validated_data["reason"])
        return _expense_answer(self.organization, expense_id)


class ExpenseReceiptView(ExpenseView):
    parser_classes = (MultiPartParser,)

    # Read by an <img> tag or a link, not by the generated client: kept out of the API contract.
    @extend_schema(exclude=True)
    def get(self, request: Request, expense_id: int) -> FileResponse:
        expense = self.expense(expense_id)
        if not expense.receipt:
            raise Http404
        is_pdf = (expense.receipt.name or "").endswith(".pdf")
        response = FileResponse(expense.receipt.open("rb"), content_type="application/pdf" if is_pdf else "image/webp")
        # A new receipt gets a new random file name, and the API answers its address again.
        response["Cache-Control"] = "private, max-age=3600"
        return response

    @extend_schema(
        operation_id="addExpenseReceipt",
        request={"multipart/form-data": ExpenseReceiptSerializer},
        responses={200: ExpenseDetailSerializer, 400: OpenApiResponse(description="Not a photo or a PDF")},
    )
    def put(self, request: Request, expense_id: int) -> Response:
        """Join the receipt: a photo (turned upright, shrunk, stored as WebP without metadata) or a PDF.
        It can be replaced while the expense is open; once decided, only joined if there was none."""
        serializer = ExpenseReceiptSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.add_expense_receipt(
            expense=self.expense(expense_id), actor=self.membership.user, upload=serializer.validated_data["receipt"]
        )
        return _expense_answer(self.organization, expense_id)


# ---- Costs of a lot ----


class LotCostsView(OfficeView):
    @extend_schema(operation_id="getLotCosts", parameters=[LotCostFilterSerializer], responses=LotCostsSerializer)
    def get(self, request: Request) -> Response:
        """The costs charged to one lot so far: expenses typed on it and its share of the truck costs of
        each day it was on a truck (by kg loaded). `total` counts approved lines only; drafts and waiting
        expenses are listed for information."""
        filters = LotCostFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        batch_id = filters.validated_data["batch"]
        try:
            inventory.batch_of(self.organization, batch_id)
        except ObjectDoesNotExist:
            raise Http404 from None
        lines = selectors.lot_cost_lines(self.organization, batch_id=batch_id, approved_only=False)
        answer = {"batch_id": batch_id, "total": selectors.lot_cost_total(lines), "lines": lines}
        return Response(LotCostsSerializer(answer).data)


# ---- Day labour (P5-T03) ----


class DayLabourerListView(OfficeView):
    @extend_schema(
        operation_id="listDayLabourers",
        parameters=[DayLabourerFilterSerializer],
        responses=DayLabourerSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Day labourers by name."""
        filters = DayLabourerFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        labourers = selectors.labourers_of(self.organization, status=filters.validated_data["status"])
        return Response(DayLabourerSerializer(labourers, many=True).data)

    @extend_schema(
        operation_id="createDayLabourer", request=DayLabourerWriteSerializer, responses={201: DayLabourerSerializer}
    )
    def post(self, request: Request) -> Response:
        """Add a day labourer (not an employee: no payroll)."""
        serializer = DayLabourerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = {key: value for key, value in serializer.validated_data.items() if key != "is_active"}
        labourer = services.create_labourer(organization=self.organization, actor=self.membership.user, **data)
        return Response(DayLabourerSerializer(labourer).data, status=status.HTTP_201_CREATED)


class DayLabourerDetailView(OfficeView):
    @extend_schema(
        operation_id="updateDayLabourer", request=DayLabourerWriteSerializer, responses=DayLabourerSerializer
    )
    def put(self, request: Request, labourer_id: int) -> Response:
        """Change a day labourer, or archive them (`is_active` false): their days stay."""
        try:
            labourer = selectors.labourer_of(self.organization, labourer_id)
        except DayLabourer.DoesNotExist:
            raise Http404 from None
        serializer = DayLabourerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        labourer = services.update_labourer(labourer=labourer, actor=self.membership.user, **serializer.validated_data)
        return Response(DayLabourerSerializer(labourer).data)


def _day_labour_fields(organization: Organization, data: dict[str, Any]) -> dict[str, Any]:
    errors: dict[str, str] = {}
    fields = {key: value for key, value in data.items() if key != "approve_now"}
    try:
        fields["labourer"] = selectors.labourer_of(organization, data["labourer"])
    except ObjectDoesNotExist:
        errors["labourer"] = _("Journalier inconnu.")
    if data["batch"] is not None:
        try:
            fields["batch"] = inventory.batch_of(organization, data["batch"])
        except ObjectDoesNotExist:
            errors["batch"] = _("Lot inconnu.")
    if errors:
        raise DjangoValidationError(errors)
    return {**fields, "approve": data["approve_now"]}


def _day_labour_answer(organization: Organization, entry_id: int, *, status_code: int = status.HTTP_200_OK) -> Response:
    entry = selectors.day_labour_entry_of(organization, entry_id)
    return Response(DayLabourEntrySerializer(entry).data, status=status_code)


class DayLabourView(OfficeView):
    def entry(self, entry_id: int) -> DayLabourEntry:
        try:
            return selectors.day_labour_entry_of(self.organization, entry_id)
        except DayLabourEntry.DoesNotExist:
            raise Http404 from None


class DayLabourListView(DayLabourView):
    @extend_schema(
        operation_id="listDayLabour",
        parameters=[DayLabourFilterSerializer],
        responses=DayLabourEntrySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Days worked by day labourers, by day then name: a month for the calendar (`date_from`,
        `date_to`, inclusive), or the days of one lot or one labourer. Each day is also an expense."""
        filters = DayLabourFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        data = filters.validated_data
        entries = selectors.day_labour_of(
            self.organization,
            date_from=data.get("date_from"),
            date_to=data.get("date_to"),
            labourer_id=data.get("labourer"),
            batch_id=data.get("batch"),
        )
        return Response(DayLabourEntrySerializer(entries, many=True).data)

    @extend_schema(
        operation_id="createDayLabour", request=DayLabourWriteSerializer, responses={201: DayLabourEntrySerializer}
    )
    def post(self, request: Request) -> Response:
        """Record a day worked, from the calendar or from a lot (the same single record, an expense of
        category day labour). Without `amount`, the labourer's usual daily pay; without `batch`, a general
        cost. A draft until approved (`approve_now` approves at once)."""
        serializer = DayLabourWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _day_labour_fields(self.organization, serializer.validated_data)
        entry = services.create_day_labour(organization=self.organization, actor=self.membership.user, **data)
        return _day_labour_answer(self.organization, entry.pk, status_code=status.HTTP_201_CREATED)


class DayLabourDetailView(DayLabourView):
    @extend_schema(operation_id="updateDayLabour", request=DayLabourWriteSerializer, responses=DayLabourEntrySerializer)
    def put(self, request: Request, entry_id: int) -> Response:
        """Correct a day not approved yet; with `approve_now`, approve it too."""
        entry = self.entry(entry_id)
        serializer = DayLabourWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = _day_labour_fields(self.organization, serializer.validated_data)
        services.update_day_labour(entry=entry, actor=self.membership.user, **data)
        return _day_labour_answer(self.organization, entry.pk)

    @extend_schema(operation_id="deleteDayLabour", responses={204: None})
    def delete(self, request: Request, entry_id: int) -> Response:
        """Delete a day typed by mistake while it is a draft (its expense goes with it)."""
        services.delete_day_labour(entry=self.entry(entry_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---- Driver app (P3-T04) ----


class MyRoadCategoriesView(APIView):
    permission_classes = (IsDriver,)

    @extend_schema(operation_id="listRoadCategories", responses=RoadCategorySerializer(many=True))
    def get(self, request: Request) -> Response:
        """The few categories a driver can spend on from the road: fuel, transport, handling, other."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        return Response(RoadCategorySerializer(selectors.road_categories(membership.organization), many=True).data)


class MyRoadExpensesView(APIView):
    permission_classes = (IsDriver,)
    parser_classes = (MultiPartParser,)

    @extend_schema(operation_id="listMyExpenses", responses=RoadExpenseSerializer(many=True))
    def get(self, request: Request) -> Response:
        """What the driver entered today, newest first."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        rows = selectors.road_expenses(membership.organization, user_id=membership.user_id, day=timezone.localdate())
        return Response(RoadExpenseSerializer(rows, many=True).data)

    @extend_schema(
        operation_id="addMyExpense",
        request={"multipart/form-data": RoadExpenseWriteSerializer},
        responses={201: RoadExpenseSerializer},
    )
    def post(self, request: Request) -> Response:
        """Enter an expense of today, with a photo of the receipt, paid with the day's cash, out of the driver's
        pocket or by card (`paid_with`, D-205). It is a cost of the driver's truck of the day and waits for the
        office to approve it."""
        membership = membership_of(request)
        assert membership is not None  # guaranteed by the permission class
        organization = membership.organization
        serializer = RoadExpenseWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        made_at = moment_from_phone(data["made_at"], field="made_at")
        dayclose.refuse_sale_outside_day(membership, made_at)
        truck = fleet.truck_of_driver(membership)
        if truck is None:
            raise DjangoValidationError({"truck": _("Choisissez d'abord votre camion.")})
        try:
            category = selectors.category_of(organization, data["category"])
        except ExpenseCategory.DoesNotExist:
            raise DjangoValidationError({"category": _("Catégorie inconnue.")}) from None
        expense = services.submit_road_expense(
            organization=organization,
            actor=membership.user,
            truck=truck,
            category=category,
            amount=data["amount"],
            description=data["description"],
            upload=data.get("receipt"),
            client_uuid=data["client_uuid"],
            made_at=made_at,
            payment_method=ExpensePaymentMethod.OTHER if data["paid_with"] == "card" else ExpensePaymentMethod.CASH,
            paid_by_driver=data["paid_with"] == "pocket",
        )
        return Response(RoadExpenseSerializer(expense).data, status=status.HTTP_201_CREATED)
