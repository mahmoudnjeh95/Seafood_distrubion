from typing import Any

from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db.models import QuerySet
from django.http import Http404
from django.utils.translation import gettext as _
from drf_spectacular.utils import extend_schema
from rest_framework import status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core import selectors as core
from apps.core.models import Membership, Organization, User
from apps.core.permissions import membership_of
from apps.hr import selectors, services
from apps.hr.models import Employee, LotWorkDay, SalaryPayment, SalaryRecord
from apps.inventory import selectors as inventory

from .permissions import ReadOwnerOrAccountantWriteOwner
from .serializers import (
    AdjustmentWriteSerializer,
    ApprovedMonthSerializer,
    EmployeeFilterSerializer,
    EmployeeSerializer,
    EmployeeWriteSerializer,
    GeneratedMonthSerializer,
    LotWorkDayFilterSerializer,
    LotWorkDaySerializer,
    LotWorkDayWriteSerializer,
    MonthSerializer,
    PayrollSummarySerializer,
    SalaryAdjustmentSerializer,
    SalaryPaymentAllocateSerializer,
    SalaryPaymentFilterSerializer,
    SalaryPaymentSerializer,
    SalaryPaymentWriteSerializer,
    SalaryRecordFilterSerializer,
    SalaryRecordSerializer,
    SalaryRecordUpdateSerializer,
)


# Base of every HR view: pay is private (D-055). The owner reads and writes, the accountant reads, managers
# and drivers get 403. A comment, not a docstring: it would describe every endpoint in the schema.
class HrView(APIView):
    permission_classes = (ReadOwnerOrAccountantWriteOwner,)

    @property
    def membership(self) -> Membership:
        membership = membership_of(self.request)
        assert membership is not None  # guaranteed by the permission class
        return membership

    @property
    def organization(self) -> Organization:
        return self.membership.organization

    def employee(self, employee_id: int) -> Employee:
        try:
            return selectors.employee_of(self.organization, employee_id)
        except Employee.DoesNotExist:
            raise Http404 from None


def _login(organization: Organization, user_id: int | None) -> User | None:
    """The login of an employee: a member of the organization, or an error on `user`."""
    if user_id is None:
        return None
    for membership in core.members_of(organization):
        if membership.user_id == user_id and membership.is_active:
            return membership.user
    raise ValidationError({"user": _("Utilisateur inconnu.")})


def _employee_fields(organization: Organization, data: dict[str, Any]) -> dict[str, Any]:
    fields = dict(data)
    if "user" in fields:
        fields["user"] = _login(organization, fields["user"])
    return fields


# ---- Employees ----


class EmployeeListView(HrView):
    @extend_schema(
        operation_id="listEmployees", parameters=[EmployeeFilterSerializer], responses=EmployeeSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        """Employees sorted by name, each with what is still unpaid. Archived ones only when asked (`status`).
        Not paginated: the company has 6 to 10 employees (Q6)."""
        filters = EmployeeFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        employees = selectors.employees_of(
            self.organization, search=filters.validated_data["search"], status=filters.validated_data["status"]
        )
        context = {"unpaid": selectors.unpaid_by_employee(self.organization)}
        return Response(EmployeeSerializer(employees, many=True, context=context).data)

    @extend_schema(operation_id="createEmployee", request=EmployeeWriteSerializer, responses={201: EmployeeSerializer})
    def post(self, request: Request) -> Response:
        """A new employee. Without a reference it gets the next free `E-NNN`; the CNSS rate defaults to 17.07 %."""
        serializer = EmployeeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # An omitted rate gets the default; a typed 0 % (an apprentice) stays 0.
        employee = services.create_employee(
            organization=self.organization,
            actor=self.membership.user,
            **_employee_fields(self.organization, dict(serializer.validated_data)),
        )
        return self._answer(employee.pk, status.HTTP_201_CREATED)

    def _answer(self, employee_id: int, status_code: int) -> Response:
        context = {"unpaid": selectors.unpaid_by_employee(self.organization)}
        return Response(EmployeeSerializer(self.employee(employee_id), context=context).data, status=status_code)


class EmployeeDetailView(HrView):
    def _answer(self, employee_id: int) -> Response:
        context = {"unpaid": selectors.unpaid_by_employee(self.organization)}
        return Response(EmployeeSerializer(self.employee(employee_id), context=context).data)

    @extend_schema(operation_id="getEmployee", responses=EmployeeSerializer)
    def get(self, request: Request, employee_id: int) -> Response:
        return self._answer(employee_id)

    @extend_schema(operation_id="updateEmployee", request=EmployeeWriteSerializer, responses=EmployeeSerializer)
    def patch(self, request: Request, employee_id: int) -> Response:
        """Change an employee. A new salary applies to the months generated afterwards."""
        employee = self.employee(employee_id)
        serializer = EmployeeWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_employee(
            employee=employee,
            actor=self.membership.user,
            **_employee_fields(self.organization, dict(serializer.validated_data)),
        )
        return self._answer(employee_id)


class EmployeeArchiveView(HrView):
    @extend_schema(operation_id="archiveEmployee", request=None, responses=EmployeeSerializer)
    def post(self, request: Request, employee_id: int) -> Response:
        """An archived employee keeps their history and gets no new salary record."""
        employee = self.employee(employee_id)
        services.set_employee_active(employee=employee, actor=self.membership.user, is_active=False)
        return Response(EmployeeSerializer(self.employee(employee_id)).data)


class EmployeeRestoreView(HrView):
    @extend_schema(operation_id="restoreEmployee", request=None, responses=EmployeeSerializer)
    def post(self, request: Request, employee_id: int) -> Response:
        employee = self.employee(employee_id)
        services.set_employee_active(employee=employee, actor=self.membership.user, is_active=True)
        return Response(EmployeeSerializer(self.employee(employee_id)).data)


# ---- Salary records ----


class SalaryRecordView(HrView):
    def record(self, record_id: int) -> SalaryRecord:
        try:
            return selectors.salary_record_of(self.organization, record_id)
        except SalaryRecord.DoesNotExist:
            raise Http404 from None

    def answer(self, record_id: int, status_code: int = status.HTTP_200_OK) -> Response:
        return Response(SalaryRecordSerializer(self.record(record_id)).data, status=status_code)


class SalaryRecordListView(SalaryRecordView):
    @extend_schema(
        operation_id="listSalaryRecords",
        parameters=[SalaryRecordFilterSerializer],
        responses=SalaryRecordSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Salary records, newest month first, with what is paid and still owed. Filter by `month` (any day of
        it), `employee` or `status`. Not paginated (6 to 10 employees)."""
        filters = SalaryRecordFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        records: QuerySet[SalaryRecord] = selectors.salary_records_of(
            self.organization,
            month=filters.validated_data.get("month"),
            employee_id=filters.validated_data.get("employee"),
            status=filters.validated_data.get("status", ""),
        )
        return Response(SalaryRecordSerializer(records, many=True).data)


class SalaryRecordGenerateView(HrView):
    @extend_schema(operation_id="generateSalaryMonth", request=MonthSerializer, responses=GeneratedMonthSerializer)
    def post(self, request: Request) -> Response:
        """Create the draft salary records of a month for every active employee who has none: base = monthly
        salary, employer CNSS from their rate. Running it twice creates nothing more."""
        serializer = MonthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data["month"].replace(day=1)
        created = services.generate_month(organization=self.organization, actor=self.membership.user, month=month)
        records = selectors.salary_records_of(self.organization, month=month)
        data = {"month": month, "created": len(created), "records": records}
        return Response(GeneratedMonthSerializer(data).data)


class SalaryRecordApproveMonthView(HrView):
    @extend_schema(operation_id="approveSalaryMonth", request=MonthSerializer, responses=ApprovedMonthSerializer)
    def post(self, request: Request) -> Response:
        """Approve every draft of a month at once."""
        serializer = MonthSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        month = serializer.validated_data["month"].replace(day=1)
        approved = services.approve_month(organization=self.organization, actor=self.membership.user, month=month)
        return Response(ApprovedMonthSerializer({"month": month, "approved": len(approved)}).data)


class SalaryRecordDetailView(SalaryRecordView):
    @extend_schema(operation_id="getSalaryRecord", responses=SalaryRecordSerializer)
    def get(self, request: Request, record_id: int) -> Response:
        return self.answer(record_id)

    @extend_schema(
        operation_id="updateSalaryRecord", request=SalaryRecordUpdateSerializer, responses=SalaryRecordSerializer
    )
    def patch(self, request: Request, record_id: int) -> Response:
        """Change a draft (bonus, overtime, deductions...). An approved salary no longer changes (400): add an
        adjustment."""
        record = self.record(record_id)
        serializer = SalaryRecordUpdateSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        services.update_salary_record(
            record=record,
            actor=self.membership.user,
            **dict(serializer.validated_data),
        )
        return self.answer(record_id)

    @extend_schema(operation_id="deleteSalaryRecord", responses={204: None})
    def delete(self, request: Request, record_id: int) -> Response:
        """Delete a draft. An approved salary is never deleted (400)."""
        services.delete_salary_record(record=self.record(record_id), actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class SalaryRecordApproveView(SalaryRecordView):
    @extend_schema(operation_id="approveSalaryRecord", request=None, responses=SalaryRecordSerializer)
    def post(self, request: Request, record_id: int) -> Response:
        """Approve a draft: it becomes the month's expense and is final."""
        services.approve_salary_record(record=self.record(record_id), actor=self.membership.user)
        return self.answer(record_id)


class SalaryRecordAdjustView(SalaryRecordView):
    @extend_schema(
        operation_id="adjustSalaryRecord",
        request=AdjustmentWriteSerializer,
        responses={201: SalaryAdjustmentSerializer},
    )
    def post(self, request: Request, record_id: int) -> Response:
        """Correct an approved salary with a signed amount and a reason."""
        record = self.record(record_id)
        serializer = AdjustmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        adjustment = services.add_adjustment(record=record, actor=self.membership.user, **serializer.validated_data)
        return Response(SalaryAdjustmentSerializer(adjustment).data, status=status.HTTP_201_CREATED)


class SalaryRecordPrimeView(SalaryRecordView):
    @extend_schema(
        operation_id="addSalaryPrime",
        request=AdjustmentWriteSerializer,
        responses={201: SalaryAdjustmentSerializer},
    )
    def post(self, request: Request, record_id: int) -> Response:
        """Add a prime to an approved salary: a positive amount and its reason. It is due on top of the salary,
        with no separate payment (D-234)."""
        record = self.record(record_id)
        serializer = AdjustmentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        prime = services.add_prime(record=record, actor=self.membership.user, **serializer.validated_data)
        return Response(SalaryAdjustmentSerializer(prime).data, status=status.HTTP_201_CREATED)


class PayrollSummaryView(HrView):
    @extend_schema(operation_id="getPayrollSummary", parameters=[MonthSerializer], responses=PayrollSummarySerializer)
    def get(self, request: Request) -> Response:
        """Totals of one month (gross, employer CNSS, net, expense, paid, outstanding) and the unpaid salaries
        of all months."""
        filters = MonthSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        summary = selectors.payroll_summary(self.organization, month=filters.validated_data["month"])
        return Response(PayrollSummarySerializer(summary.__dict__).data)


# ---- Salary payments ----


def _allocations(organization: Organization, lines: list[dict[str, Any]]) -> list[services.AllocationFields]:
    errors: dict[str, str] = {}
    resolved: list[services.AllocationFields] = []
    for index, line in enumerate(lines):
        try:
            record = selectors.salary_record_of(organization, line["salary_record"])
        except SalaryRecord.DoesNotExist:
            errors[services.allocation_error_key(index, "salary_record")] = _("Paie inconnue.")
            continue
        resolved.append({"salary_record": record, "amount": line["amount"]})
    if errors:
        raise ValidationError(errors)
    return resolved


class SalaryPaymentView(HrView):
    def payment(self, payment_id: int) -> SalaryPayment:
        try:
            return selectors.payment_of(self.organization, payment_id)
        except SalaryPayment.DoesNotExist:
            raise Http404 from None


class SalaryPaymentListView(SalaryPaymentView):
    @extend_schema(
        operation_id="listSalaryPayments",
        parameters=[SalaryPaymentFilterSerializer],
        responses=SalaryPaymentSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Salary payments, newest first, with the salaries each settled and the part not allocated.
        Filter by `employee` or `search` (number, reference, name). Not paginated."""
        filters = SalaryPaymentFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        payments = selectors.payments_of(
            self.organization,
            employee_id=filters.validated_data.get("employee"),
            search=filters.validated_data["search"],
        )
        return Response(SalaryPaymentSerializer(payments, many=True).data)

    @extend_schema(
        operation_id="recordSalaryPayment",
        request=SalaryPaymentWriteSerializer,
        responses={201: SalaryPaymentSerializer},
    )
    def post(self, request: Request) -> Response:
        """Record cash paid to an employee and the approved salaries it settles. What is not allocated is an
        advance. An advance (`kind` advance) is allocated in full to the salary of its month; above what is still
        due it is refused unless `confirm_overpay`. Each payment writes its treasury movement. Errors of an
        allocation come back on `allocations.<index>.<field>`."""
        serializer = SalaryPaymentWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        employee = self.employee_or_error(data.pop("employee"))
        allocations = _allocations(self.organization, data.pop("allocations"))
        payment = services.record_payment(
            organization=self.organization,
            actor=self.membership.user,
            employee=employee,
            allocations=allocations,
            **data,
        )
        return Response(
            SalaryPaymentSerializer(selectors.payment_of(self.organization, payment.pk)).data,
            status=status.HTTP_201_CREATED,
        )

    def employee_or_error(self, employee_id: int) -> Employee:
        try:
            return selectors.employee_of(self.organization, employee_id)
        except ObjectDoesNotExist:
            raise ValidationError({"employee": _("Employé inconnu.")}) from None


class SalaryPaymentDetailView(SalaryPaymentView):
    @extend_schema(operation_id="getSalaryPayment", responses=SalaryPaymentSerializer)
    def get(self, request: Request, payment_id: int) -> Response:
        return Response(SalaryPaymentSerializer(self.payment(payment_id)).data)


class SalaryPaymentAllocateView(SalaryPaymentView):
    @extend_schema(
        operation_id="allocateSalaryPayment", request=SalaryPaymentAllocateSerializer, responses=SalaryPaymentSerializer
    )
    def post(self, request: Request, payment_id: int) -> Response:
        """Allocate the part of a payment not allocated yet (an advance) to approved salaries of its employee."""
        payment = self.payment(payment_id)
        serializer = SalaryPaymentAllocateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        allocations = _allocations(self.organization, serializer.validated_data["allocations"])
        services.allocate_payment(payment=payment, actor=self.membership.user, allocations=allocations)
        return Response(SalaryPaymentSerializer(self.payment(payment_id)).data)


# ---- Days on a lot ----


class LotWorkDayListView(HrView):
    @extend_schema(
        operation_id="listLotWorkDays",
        parameters=[LotWorkDayFilterSerializer],
        responses=LotWorkDaySerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        """Days worked on lots, newest first, each with its cost (days × salary / 26). Filter by `employee`,
        `batch` or `month`."""
        filters = LotWorkDayFilterSerializer(data=request.query_params)
        filters.is_valid(raise_exception=True)
        days = selectors.lot_work_days_of(
            self.organization,
            employee_id=filters.validated_data.get("employee"),
            batch_id=filters.validated_data.get("batch"),
            month=filters.validated_data.get("month"),
        )
        return Response(LotWorkDaySerializer(days, many=True).data)

    @extend_schema(
        operation_id="createLotWorkDay", request=LotWorkDayWriteSerializer, responses={201: LotWorkDaySerializer}
    )
    def post(self, request: Request) -> Response:
        """Record days an employee worked on a lot (a fraction of a day, at most 1 per employee and date)."""
        serializer = LotWorkDayWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        errors: dict[str, str] = {}
        employee = batch = None
        try:
            employee = selectors.employee_of(self.organization, data.pop("employee"))
        except ObjectDoesNotExist:
            errors["employee"] = _("Employé inconnu.")
        batch_id = data.pop("batch")
        if batch_id is not None:
            try:
                batch = inventory.batch_of(self.organization, batch_id)
            except ObjectDoesNotExist:
                errors["batch"] = _("Lot inconnu.")
        if errors:
            raise ValidationError(errors)
        assert employee is not None
        work_day = services.add_lot_work_day(
            organization=self.organization, actor=self.membership.user, employee=employee, batch=batch, **data
        )
        saved = selectors.lot_work_day_of(self.organization, work_day.pk)
        return Response(LotWorkDaySerializer(saved).data, status=status.HTTP_201_CREATED)


class LotWorkDayDetailView(HrView):
    @extend_schema(operation_id="deleteLotWorkDay", responses={204: None})
    def delete(self, request: Request, work_day_id: int) -> Response:
        """Remove a mistaken entry."""
        try:
            work_day: LotWorkDay = selectors.lot_work_day_of(self.organization, work_day_id)
        except LotWorkDay.DoesNotExist:
            raise Http404 from None
        services.delete_lot_work_day(work_day=work_day, actor=self.membership.user)
        return Response(status=status.HTTP_204_NO_CONTENT)
