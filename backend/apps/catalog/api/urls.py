from django.urls import path

from . import views

urlpatterns = [
    path("categories", views.CategoryListView.as_view(), name="category-list"),
    path("categories/<int:category_id>", views.CategoryDetailView.as_view(), name="category-detail"),
    path("products", views.ProductListView.as_view(), name="product-list"),
    path("vat-rates", views.VatRateListView.as_view(), name="vat-rate-list"),
    path("vat-rates/<int:rate_id>", views.VatRateDetailView.as_view(), name="vat-rate-detail"),
    path("products/<int:product_id>", views.ProductDetailView.as_view(), name="product-detail"),
    path("products/<int:product_id>/archive", views.ProductArchiveView.as_view(), name="product-archive"),
    path("products/<int:product_id>/restore", views.ProductRestoreView.as_view(), name="product-restore"),
    path("products/<int:product_id>/prices", views.ProductPriceListView.as_view(), name="product-prices"),
    path("products/<int:product_id>/photo", views.ProductPhotoView.as_view(), name="product-photo"),
    path("price-board", views.PriceBoardView.as_view(), name="price-board"),
    path("price-lists", views.PriceListListView.as_view(), name="price-list-list"),
    path("price-lists/<int:price_list_id>", views.PriceListDetailView.as_view(), name="price-list-detail"),
]
