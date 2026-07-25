import json
from functools import wraps

from django.http import JsonResponse
from django.middleware.csrf import CsrfViewMiddleware
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods

from botapp.models import GroupSettings, ModerationAction
from botapp.moderation import (
    ACTION_TYPES,
    authenticate_api_key,
    cancel_action,
    create_action,
)


def _json_body(request):
    try:
        body = json.loads(request.body or b"{}")
    except (TypeError, ValueError) as exc:
        raise ValueError("invalid JSON body") from exc
    if not isinstance(body, dict):
        raise ValueError("JSON body must be an object")
    return body


def api_authenticated(view):
    @csrf_exempt
    @wraps(view)
    def wrapped(request, *args, **kwargs):
        raw_key = request.headers.get("X-API-Key", "")
        key = authenticate_api_key(raw_key)
        if key:
            request.api_actor = key
            return view(request, *args, **kwargs)
        if request.user.is_authenticated and request.user.is_staff:
            csrf_failure = CsrfViewMiddleware(lambda _request: None).process_view(
                request,
                view,
                args,
                kwargs,
            )
            if csrf_failure:
                return JsonResponse({"error": "CSRF verification failed"}, status=403)
            request.api_actor = request.user
            return view(request, *args, **kwargs)
        return JsonResponse({"error": "authentication required"}, status=401)
    return wrapped


def _action_json(action, created=None):
    payload = {
        "id": action.id,
        "chat_id": action.group.chat_id,
        "action": action.action,
        "target_user_id": action.target_user_id,
        "target_name": action.target_name,
        "reason": action.reason,
        "execute_at": action.execute_at.isoformat(),
        "duration_minutes": action.duration_minutes,
        "status": action.status,
        "idempotency_key": action.idempotency_key,
        "source": action.source,
    }
    if created is not None:
        payload["created"] = created
    return payload


@require_http_methods(["GET", "POST"])
@api_authenticated
def group_settings_api(request, chat_id):
    try:
        chat_id = int(chat_id)
    except (TypeError, ValueError):
        return JsonResponse({"error": "invalid chat_id"}, status=400)
    group = GroupSettings.objects.filter(chat_id=chat_id).first()
    if request.method == "GET":
        if not group:
            return JsonResponse({"error": "group not found"}, status=404)
        return JsonResponse({
            "chat_id": group.chat_id,
            "chat_title": group.chat_title,
            "max_warnings": group.max_warnings,
            "max_warnings_action": group.max_warnings_action,
            "max_warnings_action_delay_minutes": group.max_warnings_action_delay_minutes,
            "max_warnings_action_duration_minutes": group.max_warnings_action_duration_minutes,
            "message_templates": group.message_templates,
        })

    try:
        body = _json_body(request)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    group, _ = GroupSettings.objects.get_or_create(chat_id=chat_id)
    allowed = {
        "max_warnings",
        "max_warnings_action",
        "max_warnings_action_delay_minutes",
        "max_warnings_action_duration_minutes",
        "message_templates",
    }
    unknown = set(body) - allowed
    if unknown:
        return JsonResponse({"error": f"unknown fields: {', '.join(sorted(unknown))}"}, status=400)
    if "max_warnings_action" in body and body["max_warnings_action"] not in {"mute", "ban"}:
        return JsonResponse({"error": "max_warnings_action must be mute or ban"}, status=400)
    if "message_templates" in body and not isinstance(body["message_templates"], dict):
        return JsonResponse({"error": "message_templates must be an object"}, status=400)
    for field, value in body.items():
        setattr(group, field, value)
    try:
        group.full_clean()
        group.save(update_fields=[*body.keys(), "updated_at"])
    except Exception as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse({"updated": True, "chat_id": chat_id})


@require_http_methods(["POST"])
@api_authenticated
def create_action_api(request):
    try:
        body = _json_body(request)
        action_type = body.get("action")
        if action_type not in ACTION_TYPES:
            raise ValueError("unsupported action")
        chat_id = int(body["chat_id"])
        group, _ = GroupSettings.objects.get_or_create(chat_id=chat_id)
        actor = request.api_actor
        actor_id = getattr(actor, "id", None)
        actor_name = getattr(actor, "username", "") or getattr(actor, "name", "")
        action, created = create_action(
            group=group,
            action=action_type,
            target_user_id=body.get("target_user_id"),
            target_name=str(body.get("target_name", "")),
            actor_user_id=actor_id,
            actor_name=actor_name,
            reason=str(body.get("reason", "")),
            delay_minutes=body.get("delay_minutes", 0),
            duration_minutes=body.get("duration_minutes"),
            idempotency_key=request.headers.get("Idempotency-Key") or body.get("idempotency_key"),
            source="api",
        )
    except (KeyError, TypeError, ValueError) as exc:
        return JsonResponse({"error": str(exc)}, status=400)
    return JsonResponse(_action_json(action, created), status=201 if created else 200)


@require_http_methods(["GET"])
@api_authenticated
def action_detail_api(request, action_id):
    action = ModerationAction.objects.select_related("group").filter(pk=action_id).first()
    if not action:
        return JsonResponse({"error": "action not found"}, status=404)
    return JsonResponse(_action_json(action))


@require_http_methods(["POST"])
@api_authenticated
def cancel_action_api(request, action_id):
    action = ModerationAction.objects.filter(pk=action_id).first()
    if not action:
        return JsonResponse({"error": "action not found"}, status=404)
    try:
        cancel_action(action)
    except ValueError as exc:
        return JsonResponse({"error": str(exc)}, status=409)
    return JsonResponse({"id": action.id, "status": action.status})
