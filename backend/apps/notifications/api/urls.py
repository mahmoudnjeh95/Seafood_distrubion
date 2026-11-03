from django.urls import path

from . import views

urlpatterns = [
    path("me/notifications", views.MyNotificationsView.as_view(), name="my-notifications"),
    path("me/notifications/read", views.MyNotificationsReadView.as_view(), name="my-notifications-read"),
    path("notifications/recipients", views.NoticeRecipientsView.as_view(), name="notice-recipients"),
    path(
        "notifications/payment-orders/<int:plan_line_id>",
        views.PaymentOrderNoticeView.as_view(),
        name="notice-payment-order",
    ),
]
