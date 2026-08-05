"""Domain-specific errors for the admin agent.

Every error carries a stable ``code`` (used for audit logging without leaking
sensitive data) and a Persian ``user_message`` shown to the admin.
"""


class AgentError(Exception):
    code = "agent_error"
    user_message = "❌ خطایی در پردازش دستور رخ داد."

    def __init__(self, user_message: str | None = None, *, code: str | None = None):
        if user_message:
            self.user_message = user_message
        if code:
            self.code = code
        super().__init__(self.user_message)


class AgentPermissionDenied(AgentError):
    code = "permission_denied"
    user_message = "❌ فقط مدیران گروه/کانال می‌توانند از دستیار مدیریتی استفاده کنند."


class BotCapabilityMissing(AgentError):
    code = "bot_capability_missing"
    user_message = "❌ ربات دسترسی لازم برای این عملیات را ندارد."


class UnknownTool(AgentError):
    code = "unknown_tool"
    user_message = "❌ این عملیات پشتیبانی نمی‌شود."


class InvalidToolInput(AgentError):
    code = "invalid_tool_input"
    user_message = "❌ پارامترهای دستور نامعتبر است."


class AmbiguousTarget(AgentError):
    code = "ambiguous_target"
    user_message = "❌ امکان تشخیص قطعی کاربر هدف وجود ندارد."


class TargetNotFound(AgentError):
    code = "target_not_found"
    user_message = "❌ کاربر هدف پیدا نشد."


class ProtectedTarget(AgentError):
    code = "protected_target"
    user_message = "❌ نمی‌توان این عملیات را روی این کاربر انجام داد."


class ConfirmationExpired(AgentError):
    code = "confirmation_expired"
    user_message = "❌ این درخواست منقضی شده است. دستور را دوباره ارسال کنید."


class ConfirmationAlreadyHandled(AgentError):
    code = "confirmation_already_handled"
    user_message = "❌ این درخواست قبلاً پردازش شده است."


class AgentParseError(AgentError):
    code = "parse_error"
    user_message = "❌ متوجه دستور نشدم. لطفاً واضح‌تر بنویسید."


class AIProviderError(AgentError):
    code = "ai_provider_error"
    user_message = "❌ ارتباط با هوش مصنوعی برقرار نشد. لطفاً دوباره تلاش کنید."


class TelegramOperationError(AgentError):
    code = "telegram_operation_error"
    user_message = "❌ اجرای عملیات در تلگرام ناموفق بود."


class UnsupportedTelegramCapability(AgentError):
    code = "unsupported_telegram_capability"
    user_message = "❌ این قابلیت در تلگرام برای ربات‌ها پشتیبانی نمی‌شود."


class ArchiveUnavailable(AgentError):
    code = "archive_unavailable"
    user_message = "❌ آرشیو پیام‌ها برای این گروه فعال نیست."
