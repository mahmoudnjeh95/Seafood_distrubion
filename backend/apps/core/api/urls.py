from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health, name="health"),
    path("health/stock-check", views.stock_check_health, name="health-stock-check"),
    path("auth/csrf", views.CsrfView.as_view(), name="auth-csrf"),
    path("auth/login", views.LoginView.as_view(), name="auth-login"),
    path("auth/logout", views.LogoutView.as_view(), name="auth-logout"),
    path("me", views.MeView.as_view(), name="me"),
    path("me/profile", views.MyProfileView.as_view(), name="my-profile"),
    path("me/password", views.MyPasswordView.as_view(), name="my-password"),
    path("me/avatar", views.MyAvatarView.as_view(), name="my-avatar"),
    path("users/<int:user_id>/avatar", views.UserAvatarView.as_view(), name="user-avatar"),
    path("organizations/<int:organization_id>/logo", views.OrganizationLogoView.as_view(), name="organization-logo"),
    path("numbering", views.NumberingView.as_view(), name="numbering"),
    path("members", views.MemberListView.as_view(), name="member-list"),
    path("members/<int:member_id>", views.MemberDetailView.as_view(), name="member-detail"),
    path("members/<int:member_id>/role", views.MemberRoleView.as_view(), name="member-role"),
    path("members/<int:member_id>/deactivate", views.MemberDeactivateView.as_view(), name="member-deactivate"),
    path("members/<int:member_id>/can-buy", views.MemberCanBuyView.as_view(), name="member-can-buy"),
    path("members/<int:member_id>/reactivate", views.MemberReactivateView.as_view(), name="member-reactivate"),
    path(
        "members/<int:member_id>/reset-password",
        views.MemberPasswordResetView.as_view(),
        name="member-reset-password",
    ),
]
