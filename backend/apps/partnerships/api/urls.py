from django.urls import path

from . import views

urlpatterns = [
    path("partnerships", views.LotPartnershipListView.as_view(), name="partnership-list"),
    path("partnerships/<int:partnership_id>", views.LotPartnershipDetailView.as_view(), name="partnership-detail"),
    path(
        "partnerships/<int:partnership_id>/cancel",
        views.LotPartnershipCancelView.as_view(),
        name="partnership-cancel",
    ),
    path(
        "partnerships/<int:partnership_id>/advances",
        views.LotPartnershipAdvanceView.as_view(),
        name="partnership-advance",
    ),
]
