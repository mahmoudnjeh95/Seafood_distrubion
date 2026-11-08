from django.urls import path

from . import views

urlpatterns = [
    path("my-day/odometer", views.MyOdometerView.as_view(), name="my-odometer"),
    path("fleet/odometer", views.FleetOdometerView.as_view(), name="fleet-odometer"),
    path("trucks/<int:truck_id>/odometer-readings", views.TruckOdometerView.as_view(), name="truck-odometer"),
    path("odometer-readings/<int:reading_id>/photo", views.OdometerPhotoView.as_view(), name="odometer-photo"),
    path("maintenance-settings", views.MaintenanceSettingsView.as_view(), name="maintenance-settings"),
]
