from types import SimpleNamespace
from unittest.mock import AsyncMock

from asgiref.sync import async_to_sync
from django.test import SimpleTestCase, TestCase

from botapp.models import (
    ForcedMembershipInviteLink,
    ForcedMembershipRule,
    ForcedMembershipUserState,
    GroupSettings,
)


class ForcedMembershipPermissionTest(SimpleTestCase):
    def test_management_access_is_owner_or_super_admin_only(self):
        from botapp.forced_membership_runtime import can_manage_rule

        assert can_manage_rule("creator", "member", False) is True
        assert can_manage_rule("member", "creator", False) is True
        assert can_manage_rule("member", "member", True) is True
        assert can_manage_rule("administrator", "administrator", False) is False


class ForcedMembershipExemptionTest(SimpleTestCase):
    @staticmethod
    def message(*, sender_chat=None):
        user = SimpleNamespace(id=42, is_bot=False)
        return SimpleNamespace(
            chat=SimpleNamespace(id=-1001, type="supergroup"),
            from_user=user,
            sender_chat=sender_chat,
            new_chat_members=None,
            left_chat_member=None,
            pinned_message=None,
        )

    def test_only_same_chat_sender_chat_is_exempt(self):
        from botapp.forced_membership_runtime import _is_exempt_message

        anonymous_admin = self.message(sender_chat=SimpleNamespace(id=-1001))
        external_channel = self.message(sender_chat=SimpleNamespace(id=-2001))

        assert _is_exempt_message(anonymous_admin) is True
        assert _is_exempt_message(external_channel) is False

    def test_dispatcher_installs_forced_membership_middleware_on_edited_messages_too(self):
        from botapp.forced_membership_handlers import router as forced_router
        from botapp.forced_membership_runtime import ForcedMembershipMiddleware
        from botapp.management.commands.runbot import build_dispatcher, router as main_router

        try:
            dispatcher = build_dispatcher("NuyaRobot")
            assert any(
                isinstance(middleware, ForcedMembershipMiddleware)
                for middleware in dispatcher.edited_message.outer_middleware._middlewares
            )
        finally:
            forced_router._parent_router = None
            main_router._parent_router = None


class ForcedMembershipRuntimeTest(TestCase):
    def setUp(self):
        self.group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        self.rule = ForcedMembershipRule.objects.create(
            source_group=self.group,
            destination_chat_id=-2001,
            destination_chat_title="destination",
            destination_chat_type="channel",
            destination_username="destination",
            destination_join_url="https://t.me/destination",
            created_by_user_id=7,
            bot_source_permissions_valid=True,
            bot_destination_permissions_valid=True,
        )
        self.user = SimpleNamespace(
            id=42,
            username=None,
            first_name="<Ali>",
            last_name="",
            is_bot=False,
        )

    def message(self, message_id, *, media_group_id=None):
        return SimpleNamespace(
            message_id=message_id,
            chat=SimpleNamespace(id=-1001, type="supergroup"),
            from_user=self.user,
            sender_chat=None,
            new_chat_members=None,
            left_chat_member=None,
            pinned_message=None,
            media_group_id=media_group_id,
        )

    def test_first_nonmember_message_warns_and_second_is_deleted(self):
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="left"),
            SimpleNamespace(status="member"),
            SimpleNamespace(status="left"),
        ]

        first_blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(100), bot, update_id=10
        )
        second_blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(101), bot, update_id=11
        )

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        assert first_blocked is True
        assert second_blocked is True
        assert bot.delete_message.await_count == 1
        assert bot.send_message.await_count == 2
        assert bot.send_message.await_args_list[0].kwargs["reply_to_message_id"] == 100
        assert "reply_to_message_id" not in bot.send_message.await_args_list[1].kwargs
        assert "&lt;Ali&gt;" in bot.send_message.await_args_list[1].kwargs["text"]
        assert state.deleted_message_count == 1

    def test_media_group_deletes_every_item_and_sends_one_warning(self):
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"), SimpleNamespace(status="left"),
            SimpleNamespace(status="member"), SimpleNamespace(status="left"),
            SimpleNamespace(status="member"), SimpleNamespace(status="left"),
        ]

        for message_id, update_id in ((120, 40), (121, 41), (122, 42)):
            assert async_to_sync(enforce_forced_membership_message)(
                self.message(message_id, media_group_id="album-1"),
                bot,
                update_id=update_id,
            ) is True

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        assert bot.delete_message.await_count == 3
        assert bot.send_message.await_count == 1
        assert "reply_to_message_id" not in bot.send_message.await_args.kwargs
        assert state.deleted_message_count == 3

    def test_failed_private_invite_creation_does_not_advance_warning_state(self):
        from aiogram.exceptions import TelegramNetworkError
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        self.rule.destination_username = ""
        self.rule.destination_join_url = ""
        self.rule.save(update_fields=["destination_username", "destination_join_url"])
        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="left"),
        ]
        bot.create_chat_invite_link.side_effect = TelegramNetworkError(
            method=AsyncMock(), message="offline"
        )

        with self.assertRaises(TelegramNetworkError):
            async_to_sync(enforce_forced_membership_message)(
                self.message(107), bot, update_id=19
            )

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        assert state.first_warning_at is None
        assert state.message_count_while_not_member == 0

    def test_failed_first_warning_does_not_advance_user_to_delete(self):
        from aiogram.exceptions import TelegramNetworkError
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="left"),
        ]
        bot.send_message.side_effect = TelegramNetworkError(method=AsyncMock(), message="offline")

        blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(106), bot, update_id=18
        )

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        assert blocked is True
        assert state.first_warning_at is None
        assert state.message_count_while_not_member == 0
        bot.delete_message.assert_not_awaited()

    def test_member_is_allowed_without_warning(self):
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="member"),
        ]

        blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(102), bot, update_id=12
        )

        assert blocked is False
        bot.send_message.assert_not_awaited()
        bot.delete_message.assert_not_awaited()

    def test_legacy_mandatory_channel_is_promoted_to_rule(self):
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        self.rule.delete()
        self.group.mandatory_channel = "@legacy_channel"
        self.group.channel_join_required = True
        self.group.save(update_fields=["mandatory_channel", "channel_join_required"])
        bot = AsyncMock()
        bot.get_chat.side_effect = [
            SimpleNamespace(
                id=-2999,
                title="legacy",
                type="channel",
                username="legacy_channel",
            )
        ]
        bot.id = 999
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="administrator", can_delete_messages=True),
            SimpleNamespace(status="administrator"),
            SimpleNamespace(status="member"),
            SimpleNamespace(status="member"),
        ]

        blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(103), bot, update_id=13
        )

        assert blocked is False
        rule = ForcedMembershipRule.objects.get(source_group=self.group)
        assert rule.destination_chat_id == -2999
        assert rule.destination_username == "legacy_channel"

    def test_legacy_promotion_requires_bot_permissions_in_source_and_destination(self):
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        self.rule.delete()
        self.group.mandatory_channel = "@legacy_channel"
        self.group.channel_join_required = True
        self.group.save(update_fields=["mandatory_channel", "channel_join_required"])
        bot = AsyncMock()
        bot.id = 999
        bot.get_chat.return_value = SimpleNamespace(
            id=-2999,
            title="legacy",
            type="channel",
            username="legacy_channel",
        )
        bot.get_chat_member.side_effect = [SimpleNamespace(status="member")]

        blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(108), bot, update_id=23
        )

        assert blocked is True
        assert ForcedMembershipRule.objects.count() == 0

    def test_private_destination_creates_and_attributes_user_invite(self):
        from botapp.forced_membership import mark_tracked_invite_used, observe_membership
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        self.rule.destination_username = ""
        self.rule.destination_join_url = ""
        self.rule.save(update_fields=["destination_username", "destination_join_url"])
        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="left"),
        ]
        bot.create_chat_invite_link.return_value = SimpleNamespace(
            invite_link="https://t.me/+tracked",
            name=f"fm:{self.rule.id}:42",
            expire_date=None,
            member_limit=1,
            is_revoked=False,
        )

        blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(104), bot, update_id=14
        )
        link = ForcedMembershipInviteLink.objects.get(rule=self.rule, telegram_user_id=42)
        keyboard = bot.send_message.await_args.kwargs["reply_markup"]
        async_to_sync(observe_membership)(self.rule.id, self.user, "member", update_id=15)
        async_to_sync(mark_tracked_invite_used)(self.rule.id, 42, link.invite_link)

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        link.refresh_from_db()
        assert blocked is True
        assert keyboard.inline_keyboard[0][0].url == "https://t.me/+tracked"
        assert link.used_at is not None
        assert state.joined_via_tracked_invite is True

    def test_used_private_invite_is_not_reused(self):
        from botapp.forced_membership import mark_tracked_invite_used
        from botapp.forced_membership_runtime import _join_url

        self.rule.destination_username = ""
        self.rule.destination_join_url = ""
        self.rule.save(update_fields=["destination_username", "destination_join_url"])
        bot = AsyncMock()
        bot.create_chat_invite_link.side_effect = [
            SimpleNamespace(
                invite_link="https://t.me/+first",
                name=f"fm:{self.rule.id}:42",
                expire_date=None,
                member_limit=1,
                is_revoked=False,
            ),
            SimpleNamespace(
                invite_link="https://t.me/+second",
                name=f"fm:{self.rule.id}:42",
                expire_date=None,
                member_limit=1,
                is_revoked=False,
            ),
        ]

        first = async_to_sync(_join_url)(self.rule, 42, bot)
        async_to_sync(mark_tracked_invite_used)(self.rule.id, 42, first)
        second = async_to_sync(_join_url)(self.rule, 42, bot)

        assert first == "https://t.me/+first"
        assert second == "https://t.me/+second"
        assert bot.create_chat_invite_link.await_count == 2

    def test_destination_chat_member_event_attributes_tracked_invite(self):
        from botapp.forced_membership import process_destination_member_update

        self.rule.destination_username = ""
        self.rule.destination_join_url = ""
        self.rule.save(update_fields=["destination_username", "destination_join_url"])
        ForcedMembershipInviteLink.objects.create(
            rule=self.rule,
            telegram_user_id=42,
            invite_link="https://t.me/+tracked-event",
            member_limit=1,
        )

        async_to_sync(process_destination_member_update)(
            chat_id=self.rule.destination_chat_id,
            user=self.user,
            status="member",
            update_id=16,
            invite_url="https://t.me/+tracked-event",
        )

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        link = ForcedMembershipInviteLink.objects.get(rule=self.rule, telegram_user_id=42)
        assert state.is_currently_member is True
        assert state.joined_via_tracked_invite is True
        assert link.used_at is not None

    def test_previous_member_who_leaves_is_deleted_without_first_warning(self):
        from botapp.forced_membership import process_destination_member_update
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        async_to_sync(process_destination_member_update)(
            chat_id=self.rule.destination_chat_id,
            user=self.user,
            status="member",
            update_id=20,
        )
        async_to_sync(process_destination_member_update)(
            chat_id=self.rule.destination_chat_id,
            user=self.user,
            status="left",
            update_id=21,
        )
        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="left"),
        ]

        blocked = async_to_sync(enforce_forced_membership_message)(
            self.message(105), bot, update_id=22
        )

        assert blocked is True
        bot.delete_message.assert_awaited_once_with(-1001, 105)
        assert "reply_to_message_id" not in bot.send_message.await_args.kwargs

    def test_production_like_warning_delete_join_leave_rejoin_report(self):
        from botapp.forced_membership import (
            forced_membership_report,
            process_destination_member_update,
        )
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"), SimpleNamespace(status="left"),
            SimpleNamespace(status="member"), SimpleNamespace(status="left"),
            SimpleNamespace(status="member"), SimpleNamespace(status="member"),
            SimpleNamespace(status="member"), SimpleNamespace(status="left"),
            SimpleNamespace(status="member"), SimpleNamespace(status="member"),
        ]

        assert async_to_sync(enforce_forced_membership_message)(self.message(110), bot, update_id=30) is True
        assert async_to_sync(enforce_forced_membership_message)(self.message(111), bot, update_id=31) is True
        async_to_sync(process_destination_member_update)(
            chat_id=self.rule.destination_chat_id, user=self.user, status="member", update_id=32
        )
        assert async_to_sync(enforce_forced_membership_message)(self.message(112), bot, update_id=33) is False
        async_to_sync(process_destination_member_update)(
            chat_id=self.rule.destination_chat_id, user=self.user, status="left", update_id=34
        )
        assert async_to_sync(enforce_forced_membership_message)(self.message(113), bot, update_id=35) is True
        async_to_sync(process_destination_member_update)(
            chat_id=self.rule.destination_chat_id, user=self.user, status="member", update_id=36
        )
        assert async_to_sync(enforce_forced_membership_message)(self.message(114), bot, update_id=37) is False

        report = async_to_sync(forced_membership_report)(self.rule.id)
        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        assert bot.delete_message.await_count == 2
        assert state.join_count == 2
        assert state.leave_count == 1
        assert state.rejoin_count == 1
        assert report.checked_users == 1
        assert report.joined_users == 1
        assert report.deleted_messages == 2
        assert report.rejoin_count == 1

    def test_report_counts_are_rule_scoped(self):
        from botapp.forced_membership import forced_membership_report

        ForcedMembershipUserState.objects.create(
            rule=self.rule,
            telegram_user_id=1,
            first_warning_at="2026-01-01T00:00:00Z",
            has_ever_joined=True,
            is_currently_member=True,
            join_count=1,
            deleted_message_count=2,
        )
        ForcedMembershipUserState.objects.create(
            rule=self.rule,
            telegram_user_id=2,
            first_warning_at="2026-01-01T00:00:00Z",
            has_ever_joined=False,
            is_currently_member=False,
            message_count_while_not_member=2,
            deleted_message_count=1,
        )
        ForcedMembershipUserState.objects.create(
            rule=self.rule,
            telegram_user_id=3,
            first_warning_at="2026-01-01T00:00:00Z",
            has_ever_joined=True,
            is_currently_member=False,
            join_count=2,
            leave_count=1,
            rejoin_count=1,
        )

        report = async_to_sync(forced_membership_report)(self.rule.id)
        assert report.checked_users == 3
        assert report.joined_users == 2
        assert report.non_joined_users == 1
        assert report.left_after_join_users == 1
        assert report.deleted_messages == 3
        assert report.rejoin_count == 1
