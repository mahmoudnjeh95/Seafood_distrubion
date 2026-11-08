from django.urls import path

from . import views

urlpatterns = [
    path("my-day/odometer", views.MyOdometerView.as_view(), name="my-odometer"),
    path("fleet/odometer", views.FleetOdometerView.as_view(), name="fleet-odometer"),
    path("trucks/<int:truck_id>/odometer-readings", views.TruckOdometerView.as_view(), name="truck-odometer"),
    path("odometer-readings/<int:reading_id>/photo", views.OdometerPhotoView.as_view(), name="odometer-photo"),
    path("maintenance-settings", views.MaintenanceSettingsView.as_view(), name="maintenance-settings"),
    path("maintenance-types", views.MaintenanceTypeListView.as_view(), name="maintenance-type-list"),
    path("maintenance-types/defaults", views.MaintenanceTypeDefaultsView.as_view(), name="maintenance-type-defaults"),
    path("maintenance-types/<int:type_id>", views.MaintenanceTypeDetailView.as_view(), name="maintenance-type-detail"),
    path("maintenance-plans", views.MaintenancePlanListView.as_view(), name="maintenance-plan-list"),
    path("maintenance-plans/<int:plan_id>", views.MaintenancePlanDetailView.as_view(), name="maintenance-plan-detail"),
    path(
        "maintenance-plans/<int:plan_id>/records",
        views.MaintenanceRecordListView.as_view(),
        name="maintenance-record-list",
    ),
    path("papers", views.PaperListView.as_view(), name="paper-list"),
    path("papers/board", views.PaperBoardView.as_view(), name="paper-board"),
    path("papers/<int:paper_id>/scan", views.PaperScanView.as_view(), name="paper-scan"),
    path("trucks/<int:truck_id>/day-allowances", views.TruckDayAllowanceView.as_view(), name="truck-day-allowances"),
    path("fleet/alerts", views.FleetAlertsView.as_view(), name="fleet-alerts"),
    path("my-day/alerts", views.MyAlertsView.as_view(), name="my-alerts"),
]
