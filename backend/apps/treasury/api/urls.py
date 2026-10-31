from django.urls import path

from . import views

urlpatterns = [
    path("treasury/banks", views.BankListView.as_view(), name="treasury-bank-list"),
    path("treasury/banks/<int:bank_id>", views.BankDetailView.as_view(), name="treasury-bank-detail"),
    path("treasury/instruments", views.InstrumentListView.as_view(), name="treasury-instrument-list"),
    path("treasury/instruments/totals", views.InstrumentTotalsView.as_view(), name="treasury-instrument-totals"),
    path("treasury/instruments/cash", views.InstrumentCashView.as_view(), name="treasury-instrument-cash"),
    path("treasury/instruments/withdraw", views.InstrumentWithdrawView.as_view(), name="treasury-instrument-withdraw"),
    path("treasury/instruments/debit", views.InstrumentDebitView.as_view(), name="treasury-instrument-debit"),
    path("treasury/instruments/return", views.InstrumentReturnView.as_view(), name="treasury-instrument-return"),
    path("treasury/deposits", views.DepositListView.as_view(), name="treasury-deposit-list"),
    path("treasury/deposits/<int:deposit_id>", views.DepositDetailView.as_view(), name="treasury-deposit-detail"),
]
