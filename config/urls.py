from django.contrib import admin
from django.urls import path

from botapp.api import (
    action_detail_api,
    cancel_action_api,
    create_action_api,
    group_settings_api,
)
from botapp.views import healthcheck

urlpatterns = [
    path("health/", healthcheck, name="healthcheck"),
    path("api/groups/<str:chat_id>/settings/", group_settings_api, name="group-settings-api"),
    path("api/moderation/actions/", create_action_api, name="create-action-api"),
    path("api/moderation/actions/<int:action_id>/", action_detail_api, name="action-detail-api"),
    path("api/moderation/actions/<int:action_id>/cancel/", cancel_action_api, name="cancel-action-api"),
    path("admin/", admin.site.urls),
]
