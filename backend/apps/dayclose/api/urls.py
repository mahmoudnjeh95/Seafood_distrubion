from django.urls import path

from . import views

urlpatterns = [
    path("my-day-summary", views.MyDaySummaryView.as_view(), name="my-day-summary"),
    path("my-day-closing", views.MyDayClosingView.as_view(), name="my-day-closing"),
    path("my-days", views.MyDayListView.as_view(), name="my-day-list"),
    path("my-days/<int:day_id>", views.MyDayDetailView.as_view(), name="my-day-detail"),
    path("my-days/<int:day_id>/closing", views.MyPastDayClosingView.as_view(), name="my-past-day-closing"),
    path("my-sync-problems", views.MySyncProblemsView.as_view(), name="my-sync-problems"),
    path("sync-problems", views.SyncProblemListView.as_view(), name="sync-problem-list"),
    path(
        "sync-problems/<int:problem_id>/resolve",
        views.SyncProblemResolveView.as_view(),
        name="sync-problem-resolve",
    ),
    path("day-overview", views.DayOverviewListView.as_view(), name="day-overview-list"),
    path("day-overview/drivers", views.DayOverviewDriversView.as_view(), name="day-overview-drivers"),
    path("day-overview/<int:day_id>", views.DayOverviewDetailView.as_view(), name="day-overview-detail"),
    path("day-overview/<int:day_id>/route", views.DayOverviewRouteView.as_view(), name="day-overview-route"),
    path(
        "day-overview/<int:day_id>/expenses/<int:expense_id>/decide",
        views.DayOverviewExpenseDecisionView.as_view(),
        name="day-overview-expense-decide",
    ),
    path(
        "day-overview/<int:day_id>/purchases/<int:purchase_id>/validate",
        views.DayOverviewPurchaseValidateView.as_view(),
        name="day-overview-purchase-validate",
    ),
    path(
        "day-overview/<int:day_id>/return-to-stock",
        views.DayOverviewReturnToStockView.as_view(),
        name="day-overview-return-to-stock",
    ),
    path("day-closings", views.DayClosingListView.as_view(), name="day-closing-list"),
    path("day-closings/<int:closing_id>", views.DayClosingDetailView.as_view(), name="day-closing-detail"),
    path("day-closings/<int:closing_id>/approve", views.DayClosingApproveView.as_view(), name="day-closing-approve"),
    path("day-closings/<int:closing_id>/count", views.DayClosingCountView.as_view(), name="day-closing-count"),
    path("day-closings/<int:closing_id>/correct", views.DayClosingCorrectView.as_view(), name="day-closing-correct"),
    path(
        "day-closings/<int:closing_id>/request-justification",
        views.DayClosingJustificationView.as_view(),
        name="day-closing-justification",
    ),
]
