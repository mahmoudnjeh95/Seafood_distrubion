from django.urls import path

from . import driver_payment_views, payment_views, recall_views, views

urlpatterns = [
    path("batches/<int:batch_id>/recall", recall_views.LotRecallView.as_view(), name="lot-recall"),
    path("my-deliveries", views.MyDeliveriesView.as_view(), name="my-deliveries"),
    path("my-deliveries/done", views.MyDeliveredView.as_view(), name="my-delivered"),
    path("my-deliveries/<int:sale_id>/deliver", views.MyDeliveryDeliverView.as_view(), name="my-delivery-deliver"),
    path(
        "my-deliveries/<int:sale_id>/not-delivered",
        views.MyDeliveryNotDeliveredView.as_view(),
        name="my-delivery-not-delivered",
    ),
    path("my-payments", driver_payment_views.MyPaymentsView.as_view(), name="my-payments"),
    path("my-cash-limit", driver_payment_views.MyCashLimitView.as_view(), name="my-cash-limit"),
    path("my-receipt-header", driver_payment_views.MyReceiptHeaderView.as_view(), name="my-receipt-header"),
    # P2-T03 · quotes
    path("quotes", views.QuoteListView.as_view(), name="quote-list"),
    path("quotes/<int:quote_id>", views.QuoteDetailView.as_view(), name="quote-detail"),
    path("quotes/<int:quote_id>/send", views.QuoteSendView.as_view(), name="quote-send"),
    path("quotes/<int:quote_id>/accept", views.QuoteAcceptView.as_view(), name="quote-accept"),
    path("quotes/<int:quote_id>/refuse", views.QuoteRefuseView.as_view(), name="quote-refuse"),
    # P2-T04 · sales
    path("quotes/<int:quote_id>/convert", views.QuoteConvertView.as_view(), name="quote-convert"),
    path("sales", views.SaleListView.as_view(), name="sale-list"),
    path("sales/<int:sale_id>", views.SaleDetailView.as_view(), name="sale-detail"),
    path("sales/<int:sale_id>/billing", views.SaleBillingView.as_view(), name="sale-billing"),
    path("sales/<int:sale_id>/confirm", views.SaleConfirmView.as_view(), name="sale-confirm"),
    path("sales/<int:sale_id>/cancel", views.SaleCancelView.as_view(), name="sale-cancel"),
    path("sales/<int:sale_id>/issue", views.SaleIssueView.as_view(), name="sale-issue"),
    path("sales/<int:sale_id>/deliver", views.SaleDeliverView.as_view(), name="sale-deliver"),
    path("sales/<int:sale_id>/not-delivered", views.SaleNotDeliveredView.as_view(), name="sale-not-delivered"),
    path("batches/<int:batch_id>/sales", views.BatchSalesView.as_view(), name="batch-sales"),
    # P2-T05 · finance settings, invoices, credit notes
    path("finance-settings", views.FinanceSettingsView.as_view(), name="finance-settings"),
    path("einvoicing-settings", views.EInvoicingSettingsView.as_view(), name="einvoicing-settings"),
    path("invoices", views.InvoiceListView.as_view(), name="invoice-list"),
    path("invoices/estimate", views.InvoiceEstimateView.as_view(), name="invoice-estimate"),
    path("invoices/to-invoice-counts", views.InvoiceToInvoiceCountsView.as_view(), name="invoice-to-invoice-counts"),
    path("invoices/<int:invoice_id>", views.InvoiceDetailView.as_view(), name="invoice-detail"),
    path("invoices/<int:invoice_id>/give-up-gap", views.InvoiceGiveUpGapView.as_view(), name="invoice-give-up-gap"),
    path("invoices/<int:invoice_id>/issue", views.InvoiceIssueView.as_view(), name="invoice-issue"),
    path("invoices/<int:invoice_id>/credit-notes", views.InvoiceCreditNoteView.as_view(), name="invoice-credit-notes"),
    path("credit-notes", views.CreditNoteListView.as_view(), name="credit-note-list"),
    path("refunds", views.RefundListView.as_view(), name="refund-list"),
    path("refunds/<int:refund_id>/payments", views.RefundPayView.as_view(), name="refund-pay"),
    path("credit-notes/<int:credit_note_id>", views.CreditNoteDetailView.as_view(), name="credit-note-detail"),
    path("credit-notes/<int:credit_note_id>/rebill", views.CreditNoteRebillView.as_view(), name="credit-note-rebill"),
    # P2-T06 · customer payments, balances, withholding certificates
    path("customer-payments", payment_views.CustomerPaymentListView.as_view(), name="customer-payment-list"),
    path(
        "customer-effets/<int:instrument_id>/unpaid",
        payment_views.CustomerEffetUnpaidView.as_view(),
        name="customer-effet-unpaid",
    ),
    path("customer-payments/totals", payment_views.CustomerPaymentTotalsView.as_view(), name="customer-payment-totals"),
    path("sales/export", views.SaleExportView.as_view(), name="sale-export"),
    path("invoices/export", views.InvoiceExportView.as_view(), name="invoice-export"),
    path("customer-payments/export", payment_views.CustomerPaymentExportView.as_view(), name="customer-payment-export"),
    path(
        "customer-payments/<int:payment_id>",
        payment_views.CustomerPaymentDetailView.as_view(),
        name="customer-payment-detail",
    ),
    path(
        "customer-payments/<int:payment_id>/allocate",
        payment_views.CustomerPaymentAllocateView.as_view(),
        name="customer-payment-allocate",
    ),
    path(
        "customer-payments/<int:payment_id>/void",
        payment_views.CustomerPaymentVoidView.as_view(),
        name="customer-payment-void",
    ),
    path("customers/<int:customer_id>/balance", payment_views.CustomerBalanceView.as_view(), name="customer-balance"),
    path(
        "customers/<int:customer_id>/write-off",
        payment_views.CustomerWriteOffView.as_view(),
        name="customer-write-off",
    ),
    path("receivables/ageing", payment_views.ReceivablesAgeingView.as_view(), name="receivables-ageing"),
    path(
        "invoices/<int:invoice_id>/withholding-certificate",
        payment_views.InvoiceCertificateView.as_view(),
        name="invoice-withholding-certificate",
    ),
    path("withholding-summary", payment_views.WithholdingSummaryView.as_view(), name="withholding-summary"),
    path(
        "withholding-certificates/<int:certificate_id>/file",
        payment_views.WithholdingCertificateView.as_view(),
        name="withholding-certificate-file",
    ),
    path(
        "withholding-certificates/<int:certificate_id>/void",
        payment_views.WithholdingCertificateVoidView.as_view(),
        name="withholding-certificate-void",
    ),
]
