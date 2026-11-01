from django.urls import path

from . import views

urlpatterns = [
    path("employees", views.EmployeeListView.as_view(), name="employee-list"),
    path("employees/<int:employee_id>", views.EmployeeDetailView.as_view(), name="employee-detail"),
    path("employees/<int:employee_id>/archive", views.EmployeeArchiveView.as_view(), name="employee-archive"),
    path("employees/<int:employee_id>/restore", views.EmployeeRestoreView.as_view(), name="employee-restore"),
    path("salary-records", views.SalaryRecordListView.as_view(), name="salary-record-list"),
    path("salary-records/generate", views.SalaryRecordGenerateView.as_view(), name="salary-record-generate"),
    path(
        "salary-records/approve-month", views.SalaryRecordApproveMonthView.as_view(), name="salary-record-approve-month"
    ),
    path("salary-records/<int:record_id>", views.SalaryRecordDetailView.as_view(), name="salary-record-detail"),
    path(
        "salary-records/<int:record_id>/approve", views.SalaryRecordApproveView.as_view(), name="salary-record-approve"
    ),
    path(
        "salary-records/<int:record_id>/adjustments",
        views.SalaryRecordAdjustView.as_view(),
        name="salary-record-adjust",
    ),
    path("salary-records/<int:record_id>/primes", views.SalaryRecordPrimeView.as_view(), name="salary-record-prime"),
    path("payroll-summary", views.PayrollSummaryView.as_view(), name="payroll-summary"),
    path("salary-payments", views.SalaryPaymentListView.as_view(), name="salary-payment-list"),
    path("salary-payments/<int:payment_id>", views.SalaryPaymentDetailView.as_view(), name="salary-payment-detail"),
    path(
        "salary-payments/<int:payment_id>/allocations",
        views.SalaryPaymentAllocateView.as_view(),
        name="salary-payment-allocate",
    ),
    path("lot-work-days", views.LotWorkDayListView.as_view(), name="lot-work-day-list"),
    path("lot-work-days/<int:work_day_id>", views.LotWorkDayDetailView.as_view(), name="lot-work-day-detail"),
]
