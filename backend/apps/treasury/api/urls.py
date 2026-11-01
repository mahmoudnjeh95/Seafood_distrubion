from django.urls import path

from . import views

urlpatterns = [
    path("treasury/banks", views.BankListView.as_view(), name="treasury-bank-list"),
    path("treasury/banks/<int:bank_id>", views.BankDetailView.as_view(), name="treasury-bank-detail"),
    path("treasury/instruments", views.InstrumentListView.as_view(), name="treasury-instrument-list"),
    path("treasury/party-documents", views.PartyDocumentsView.as_view(), name="treasury-party-documents"),
    path("treasury/instruments/totals", views.InstrumentTotalsView.as_view(), name="treasury-instrument-totals"),
    path("treasury/instruments/cash", views.InstrumentCashView.as_view(), name="treasury-instrument-cash"),
    path("treasury/instruments/withdraw", views.InstrumentWithdrawView.as_view(), name="treasury-instrument-withdraw"),
    path("treasury/instruments/debit", views.InstrumentDebitView.as_view(), name="treasury-instrument-debit"),
    path("treasury/instruments/return", views.InstrumentReturnView.as_view(), name="treasury-instrument-return"),
    path("treasury/deposits", views.DepositListView.as_view(), name="treasury-deposit-list"),
    path("treasury/deposits/<int:deposit_id>", views.DepositDetailView.as_view(), name="treasury-deposit-detail"),
    path("treasury/accounts", views.AccountListView.as_view(), name="treasury-account-list"),
    path("treasury/accounts/<int:account_id>", views.AccountDetailView.as_view(), name="treasury-account-detail"),
    path(
        "treasury/accounts/<int:account_id>/movements",
        views.AccountMovementsView.as_view(),
        name="treasury-account-movements",
    ),
    path(
        "treasury/accounts/<int:account_id>/movements/export",
        views.AccountMovementsExportView.as_view(),
        name="treasury-account-movements-export",
    ),
    path("treasury/transfers", views.TransferListView.as_view(), name="treasury-transfer-list"),
    path("treasury/transfers/<int:transfer_id>/void", views.TransferVoidView.as_view(), name="treasury-transfer-void"),
    path("treasury/cash-counts", views.CashCountListView.as_view(), name="treasury-cash-count-list"),
]
