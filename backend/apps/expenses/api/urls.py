from django.urls import path

from . import cost_views, views

urlpatterns = [
    # P5-T01 · expenses
    path("expense-categories", views.ExpenseCategoryListView.as_view(), name="expense-category-list"),
    path(
        "expense-categories/<int:category_id>",
        views.ExpenseCategoryDetailView.as_view(),
        name="expense-category-detail",
    ),
    path("my-expense-categories", views.MyRoadCategoriesView.as_view(), name="my-expense-categories"),
    path("my-expenses", views.MyRoadExpensesView.as_view(), name="my-expenses"),
    path("expenses", views.ExpenseListView.as_view(), name="expense-list"),
    path("expenses/totals", views.ExpenseTotalsView.as_view(), name="expense-totals"),
    path("expenses/<int:expense_id>", views.ExpenseDetailView.as_view(), name="expense-detail"),
    path("expenses/<int:expense_id>/approve", views.ExpenseApproveView.as_view(), name="expense-approve"),
    path("expenses/<int:expense_id>/reject", views.ExpenseRejectView.as_view(), name="expense-reject"),
    path("expenses/<int:expense_id>/receipt", views.ExpenseReceiptView.as_view(), name="expense-receipt"),
    path("lot-costs", views.LotCostsView.as_view(), name="lot-costs"),
    # P5-T03 · day labour
    path("day-labourers", views.DayLabourerListView.as_view(), name="day-labourer-list"),
    path("day-labourers/<int:labourer_id>", views.DayLabourerDetailView.as_view(), name="day-labourer-detail"),
    path("day-labour", views.DayLabourListView.as_view(), name="day-labour-list"),
    path("day-labour/<int:entry_id>", views.DayLabourDetailView.as_view(), name="day-labour-detail"),
    # P5-T02 · cold-room cost per day
    path("cold-room-weights", cost_views.ColdRoomWeightListView.as_view(), name="cold-room-weight-list"),
    path("cold-room-shares", cost_views.ColdRoomSharesView.as_view(), name="cold-room-shares"),
    path(
        "cold-room-weights/<int:location_id>",
        cost_views.ColdRoomWeightDetailView.as_view(),
        name="cold-room-weight-detail",
    ),
    path("cold-room-costs", cost_views.ColdRoomMonthView.as_view(), name="cold-room-month"),
    path("cold-room-estimate", cost_views.ColdRoomEstimateView.as_view(), name="cold-room-estimate"),
    path("electricity-bills", cost_views.ElectricityBillListView.as_view(), name="electricity-bill-list"),
    path(
        "electricity-bills/<int:bill_id>",
        cost_views.ElectricityBillDetailView.as_view(),
        name="electricity-bill-detail",
    ),
    path(
        "electricity-bills/<int:bill_id>/approve",
        cost_views.ElectricityBillApproveView.as_view(),
        name="electricity-bill-approve",
    ),
    # P5-T05 · general costs on lots
    path("recurring-costs", cost_views.RecurringCostListView.as_view(), name="recurring-cost-list"),
    path("recurring-costs/generate", cost_views.RecurringCostGenerateView.as_view(), name="recurring-cost-generate"),
    path("recurring-costs/<int:cost_id>", cost_views.RecurringCostDetailView.as_view(), name="recurring-cost-detail"),
    path("general-costs", cost_views.GeneralCostListView.as_view(), name="general-cost-list"),
    path("general-costs/<int:period_id>", cost_views.GeneralCostDetailView.as_view(), name="general-cost-detail"),
]
