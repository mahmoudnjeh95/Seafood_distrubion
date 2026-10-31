from django.urls import path

from . import views

urlpatterns = [
    path("truck-assignments", views.TruckAssignmentListView.as_view(), name="truck-assignment-list"),
    path(
        "truck-assignments/<int:assignment_id>",
        views.TruckAssignmentDetailView.as_view(),
        name="truck-assignment-detail",
    ),
    path("my-truck-choices", views.MyTruckChoicesView.as_view(), name="my-truck-choices"),
    path("my-day", views.MyDayView.as_view(), name="my-day"),
    path("my-day/fund", views.MyDayFundView.as_view(), name="my-day-fund"),
    path("day-funds", views.DayFundListView.as_view(), name="day-fund-list"),
    path("my-day/locations", views.MyLocationsView.as_view(), name="my-locations"),
    path("my-day/purchase-float", views.MyPurchaseFloatView.as_view(), name="my-purchase-float"),
    path("trucks", views.TruckListView.as_view(), name="truck-list"),
    path("trucks/<int:truck_id>", views.TruckDetailView.as_view(), name="truck-detail"),
    path("trucks/<int:truck_id>/archive", views.TruckArchiveView.as_view(), name="truck-archive"),
    path("trucks/<int:truck_id>/restore", views.TruckRestoreView.as_view(), name="truck-restore"),
]
