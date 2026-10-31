from django.urls import path

from . import views

urlpatterns = [
    path("treasury/banks", views.BankListView.as_view(), name="treasury-bank-list"),
    path("treasury/banks/<int:bank_id>", views.BankDetailView.as_view(), name="treasury-bank-detail"),
    path("treasury/instruments", views.InstrumentListView.as_view(), name="treasury-instrument-list"),
]
