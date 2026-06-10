from django.urls import path

from . import views

urlpatterns = [
    path("auth/register", views.register),
    path("auth/login", views.login),
    path("auth/admin-login", views.admin_login),
    path("me", views.me),
    path("conversations", views.conversations),
    path("conversations/<int:conversation_id>", views.conversation_detail),
    path("chat", views.chat),
    path("recharge", views.recharge),
    path("pay/alipay/notify", views.alipay_notify),
    path("admin/overview", views.admin_overview),
    path("admin/users", views.admin_users),
    path("admin/users/credits", views.admin_user_credits),
    path("admin/users/status", views.admin_user_status),
    path("admin/recharges", views.admin_recharges),
    path("admin/recharges/confirm", views.admin_confirm_recharge),
    path("admin/settings", views.admin_settings),
]
