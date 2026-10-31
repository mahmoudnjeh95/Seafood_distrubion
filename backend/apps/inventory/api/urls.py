from django.urls import path

from . import views

urlpatterns = [
    path("locations", views.LocationListView.as_view(), name="location-list"),
    path("locations/<int:location_id>", views.LocationDetailView.as_view(), name="location-detail"),
    path("locations/<int:location_id>/archive", views.LocationArchiveView.as_view(), name="location-archive"),
    path("locations/<int:location_id>/restore", views.LocationRestoreView.as_view(), name="location-restore"),
    path("batches", views.BatchListView.as_view(), name="batch-list"),
    path("batches/<int:batch_id>", views.BatchDetailView.as_view(), name="batch-detail"),
    # P1-T09 · transfers
    path("locations/<int:location_id>/stock", views.LocationStockView.as_view(), name="location-stock"),
    path(
        "locations/<int:location_id>/stock/<int:product_id>/batches",
        views.LocationBatchesView.as_view(),
        name="location-batches",
    ),
    path("stock/<int:product_id>/batches", views.ProductBatchesView.as_view(), name="product-batches"),
    path("vat-products", views.VatProductsView.as_view(), name="vat-products"),
    path("transfers", views.TransferListView.as_view(), name="transfer-list"),
    path("my-losses", views.MyLossesView.as_view(), name="my-losses"),
    path("my-return", views.MyReturnView.as_view(), name="my-return"),
    path("my-stock", views.MyStockView.as_view(), name="my-stock"),
    path("my-truck-day", views.MyTruckDayView.as_view(), name="my-truck-day"),
    path("transfers/truck-day", views.TruckDayView.as_view(), name="transfer-truck-day"),
    path("transfers/<int:transfer_id>", views.TransferDetailView.as_view(), name="transfer-detail"),
    path("transfers/<int:transfer_id>/validate", views.TransferValidateView.as_view(), name="transfer-validate"),
    path("transfers/<int:transfer_id>/cancel", views.TransferCancelView.as_view(), name="transfer-cancel"),
    # P1-T10 · losses and stock counts
    path("stock-settings", views.StockSettingsView.as_view(), name="stock-settings"),
    path("losses", views.LossListView.as_view(), name="loss-list"),
    path("losses/<int:loss_id>", views.LossDetailView.as_view(), name="loss-detail"),
    path("losses/<int:loss_id>/approve", views.LossApproveView.as_view(), name="loss-approve"),
    path("losses/<int:loss_id>/reject", views.LossRejectView.as_view(), name="loss-reject"),
    path("losses/<int:loss_id>/photo", views.LossPhotoView.as_view(), name="loss-photo"),
    path("counts", views.CountListView.as_view(), name="count-list"),
    path("counts/<int:count_id>", views.CountDetailView.as_view(), name="count-detail"),
    path("counts/<int:count_id>/lines", views.CountLinesView.as_view(), name="count-lines"),
    path("counts/<int:count_id>/approve", views.CountApproveView.as_view(), name="count-approve"),
    path("counts/<int:count_id>/cancel", views.CountCancelView.as_view(), name="count-cancel"),
    # P1-T11 · stock screens
    path("stock/overview", views.StockOverviewView.as_view(), name="stock-overview"),
    path("stock/products/<int:product_id>", views.ProductStockView.as_view(), name="stock-product"),
    path("stock/movements", views.MovementListView.as_view(), name="movement-list"),
]
