from django.urls import path

from . import credit_note_views, driver_views, price_request_views, views

urlpatterns = [
    path("receipts", views.ReceiptListView.as_view(), name="receipt-list"),
    path("receipts/differences", views.ReceiptDifferenceListView.as_view(), name="receipt-differences"),
    path("receipts/last-costs", views.LastCostListView.as_view(), name="receipt-last-costs"),
    path("receipts/<int:receipt_id>", views.ReceiptDetailView.as_view(), name="receipt-detail"),
    path("receipts/<int:receipt_id>/revise", views.ReceiptReviseView.as_view(), name="receipt-revise"),
    path("receipts/<int:receipt_id>/dispute", views.ReceiptDisputeView.as_view(), name="receipt-dispute"),
    path(
        "receipts/<int:receipt_id>/resolve-dispute",
        views.ReceiptResolveDisputeView.as_view(),
        name="receipt-resolve-dispute",
    ),
    path("price-requests", price_request_views.PriceRequestListView.as_view(), name="price-request-list"),
    path(
        "price-requests/<int:request_id>",
        price_request_views.PriceRequestDetailView.as_view(),
        name="price-request-detail",
    ),
    path(
        "price-requests/<int:request_id>/offers",
        price_request_views.PriceRequestOfferView.as_view(),
        name="price-request-offers",
    ),
    path(
        "price-requests/<int:request_id>/order",
        price_request_views.PriceRequestOrderView.as_view(),
        name="price-request-order",
    ),
    path(
        "price-requests/<int:request_id>/cancel",
        price_request_views.PriceRequestCancelView.as_view(),
        name="price-request-cancel",
    ),
    path("purchase-orders", views.OrderListView.as_view(), name="purchase-order-list"),
    path("purchase-orders/<int:order_id>", views.OrderDetailView.as_view(), name="purchase-order-detail"),
    path("purchase-orders/<int:order_id>/cancel", views.OrderCancelView.as_view(), name="purchase-order-cancel"),
    path("purchase-orders/<int:order_id>/close", views.OrderCloseView.as_view(), name="purchase-order-close"),
    path("supplier-credit-notes", credit_note_views.CreditNoteListView.as_view(), name="supplier-credit-note-list"),
    path(
        "supplier-credit-notes/creditable-lines",
        credit_note_views.CreditableLinesView.as_view(),
        name="supplier-creditable-lines",
    ),
    path("supplier-credit-notes/weight-gaps", credit_note_views.WeightGapsView.as_view(), name="supplier-weight-gaps"),
    path(
        "supplier-credit-notes/<int:credit_note_id>",
        credit_note_views.CreditNoteDetailView.as_view(),
        name="supplier-credit-note-detail",
    ),
    path("supplier-invoices", views.SupplierInvoiceListView.as_view(), name="supplier-invoice-list"),
    path(
        "supplier-invoices/<int:invoice_id>", views.SupplierInvoiceDetailView.as_view(), name="supplier-invoice-detail"
    ),
    path(
        "supplier-invoices/<int:invoice_id>/post", views.SupplierInvoicePostView.as_view(), name="supplier-invoice-post"
    ),
    path(
        "supplier-invoices/<int:invoice_id>/plan", views.SupplierInvoicePlanView.as_view(), name="supplier-invoice-plan"
    ),
    path("supplier-plan-lines/<int:line_id>", views.SupplierPlanLineView.as_view(), name="supplier-plan-line"),
    path("supplier-settlements", views.SupplierSettlementsView.as_view(), name="supplier-settlements"),
    path("supplier-payments", views.SupplierPaymentListView.as_view(), name="supplier-payment-list"),
    path(
        "supplier-effets/<int:instrument_id>/reject",
        views.SupplierEffetRejectView.as_view(),
        name="supplier-effet-reject",
    ),
    path("supplier-payments/totals", views.SupplierPaymentTotalsView.as_view(), name="supplier-payment-totals"),
    path("supplier-invoices/export", views.SupplierInvoiceExportView.as_view(), name="supplier-invoice-export"),
    path("supplier-payments/export", views.SupplierPaymentExportView.as_view(), name="supplier-payment-export"),
    path(
        "supplier-payments/<int:payment_id>", views.SupplierPaymentDetailView.as_view(), name="supplier-payment-detail"
    ),
    path(
        "supplier-payments/<int:payment_id>/allocations",
        views.SupplierPaymentAllocateView.as_view(),
        name="supplier-payment-allocate",
    ),
    path(
        "supplier-payments/<int:payment_id>/void", views.SupplierPaymentVoidView.as_view(), name="supplier-payment-void"
    ),
    path("supplier-balances/<int:supplier_id>", views.SupplierBalanceView.as_view(), name="supplier-balance"),
    path(
        "supplier-balances/<int:supplier_id>/write-off",
        views.SupplierBalanceWriteOffView.as_view(),
        name="supplier-balance-write-off",
    ),
    path("field-purchases", views.FieldPurchaseListView.as_view(), name="field-purchase-list"),
    path("field-purchases/<int:purchase_id>", views.FieldPurchaseDetailView.as_view(), name="field-purchase-detail"),
    path("my-field-purchases", driver_views.MyFieldPurchasesView.as_view(), name="my-field-purchases"),
    path(
        "my-field-purchases/<int:purchase_id>",
        driver_views.MyFieldPurchaseView.as_view(),
        name="my-field-purchase",
    ),
    path(
        "my-field-purchases/<int:purchase_id>/paper",
        driver_views.MyFieldPurchasePaperView.as_view(),
        name="my-field-purchase-paper",
    ),
    path("my-suppliers", driver_views.MySuppliersView.as_view(), name="my-suppliers"),
    path("supplier-debts", views.SupplierDebtsView.as_view(), name="supplier-debts"),
    path(
        "field-purchases/<int:purchase_id>/paper", views.FieldPurchasePaperView.as_view(), name="field-purchase-paper"
    ),
    path("my-purchase-costs", driver_views.MyPurchaseCostsView.as_view(), name="my-purchase-costs"),
    path(
        "field-purchases/<int:purchase_id>/refuse",
        views.FieldPurchaseRefuseView.as_view(),
        name="field-purchase-refuse",
    ),
]
