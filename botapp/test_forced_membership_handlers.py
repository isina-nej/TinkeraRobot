from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from asgiref.sync import async_to_sync
from django.test import TestCase

from botapp.models import ForcedMembershipRule, ForcedMembershipUserState, GroupSettings


class ForcedMembershipHandlerTest(TestCase):
    def message(self, user_id=7):
        message = SimpleNamespace(
            text="عضویت اجباری @destination",
            chat=SimpleNamespace(id=-1001, title="source", type="supergroup"),
            from_user=SimpleNamespace(id=user_id, first_name="Owner"),
            reply=AsyncMock(),
        )
        return message

    def test_deleting_rule_disables_matching_legacy_setting(self):
        from botapp.forced_membership_handlers import delete_rule

        group = GroupSettings.objects.create(
            chat_id=-1001,
            mandatory_channel="@destination",
            channel_join_required=True,
        )
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_username="destination",
            created_by_user_id=7,
        )

        async_to_sync(delete_rule)(rule.id)

        group.refresh_from_db()
        assert group.mandatory_channel == ""
        assert group.channel_join_required is False
        assert ForcedMembershipRule.objects.count() == 0

    def test_non_creator_cannot_configure_rule(self):
        from botapp.forced_membership_handlers import configure_forced_membership

        bot = AsyncMock()
        bot.get_chat_member.return_value = SimpleNamespace(status="member")
        message = self.message(user_id=8)

        async_to_sync(configure_forced_membership)(message, bot)

        assert ForcedMembershipRule.objects.count() == 0
        assert "فقط سازنده" in message.reply.await_args.args[0]

    def test_group_panel_lists_rules_only_for_source_creator(self):
        from botapp.forced_membership_handlers import forced_membership_group_panel

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_chat_title="destination",
            destination_username="destination",
            destination_join_url="https://t.me/destination",
            created_by_user_id=7,
        )
        callback = SimpleNamespace(
            data="fmr:list:-1001",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        bot = AsyncMock()
        bot.get_chat_member.return_value = SimpleNamespace(status="creator")

        async_to_sync(forced_membership_group_panel)(callback, bot)

        keyboard = callback.message.edit_text.await_args.kwargs["reply_markup"]
        assert keyboard.inline_keyboard[0][0].callback_data == f"fmr:report:{rule.id}"

        callback.from_user = SimpleNamespace(id=8)
        callback.message.edit_text.reset_mock()
        callback.answer.reset_mock()
        bot.get_chat_member.return_value = SimpleNamespace(status="administrator")
        async_to_sync(forced_membership_group_panel)(callback, bot)
        callback.answer.assert_awaited_once_with("دسترسی ندارید.", show_alert=True)
        callback.message.edit_text.assert_not_awaited()

    def test_private_report_starts_with_chat_then_role_then_rule(self):
        from botapp.forced_membership_handlers import (
            forced_membership_report_callback,
            forced_membership_report_command,
        )

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_chat_title="destination",
            destination_username="destination",
            destination_join_url="https://t.me/destination",
            created_by_user_id=7,
        )
        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="member"),
        ]
        message = SimpleNamespace(
            chat=SimpleNamespace(type="private"),
            from_user=SimpleNamespace(id=7),
            reply=AsyncMock(),
        )

        async_to_sync(forced_membership_report_command)(message, bot)

        first_keyboard = message.reply.await_args.kwargs["reply_markup"]
        assert first_keyboard.inline_keyboard[0][0].callback_data == "fmr:roles:-1001"

        callback = SimpleNamespace(
            data="fmr:roles:-1001",
            from_user=SimpleNamespace(id=7),
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="member"),
        ]
        async_to_sync(forced_membership_report_callback)(callback, bot)
        role_keyboard = callback.message.edit_text.await_args.kwargs["reply_markup"]
        assert role_keyboard.inline_keyboard[0][0].callback_data == "fmr:source:-1001"

        callback.data = "fmr:source:-1001"
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="member"),
        ]
        async_to_sync(forced_membership_report_callback)(callback, bot)
        rule_keyboard = callback.message.edit_text.await_args.kwargs["reply_markup"]
        assert rule_keyboard.inline_keyboard[0][0].callback_data == f"fmr:report:{rule.id}"

    def test_owner_can_change_destination_without_creating_second_rule(self):
        from botapp.forced_membership_handlers import change_forced_membership_destination

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_chat_title="old",
            destination_username="old_destination",
            destination_join_url="https://t.me/old_destination",
            created_by_user_id=7,
        )
        ForcedMembershipUserState.objects.create(
            rule=rule,
            telegram_user_id=42,
            has_ever_joined=True,
            is_currently_member=True,
            join_count=1,
        )
        message = self.message()
        message.text = f"تغییر مقصد {rule.id} @new_destination"
        bot = AsyncMock()
        bot.get_me.return_value = SimpleNamespace(id=99)
        bot.get_chat.return_value = SimpleNamespace(
            id=-2002,
            title="new",
            type="channel",
            username="new_destination",
        )
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="member"),
            SimpleNamespace(status="administrator", can_delete_messages=True),
            SimpleNamespace(status="administrator"),
        ]

        async_to_sync(change_forced_membership_destination)(message, bot)

        rule.refresh_from_db()
        assert ForcedMembershipRule.objects.count() == 1
        assert rule.destination_chat_id == -2002
        assert rule.destination_username == "new_destination"
        assert not ForcedMembershipUserState.objects.filter(rule=rule).exists()
        assert "تغییر کرد" in message.reply.await_args.args[0]

    def test_old_destination_owner_cannot_redirect_to_unowned_destination(self):
        from botapp.forced_membership_handlers import change_forced_membership_destination

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_chat_title="old",
            destination_username="old_destination",
            destination_join_url="https://t.me/old_destination",
            created_by_user_id=7,
        )
        message = self.message(user_id=9)
        message.text = f"تغییر مقصد {rule.id} @new_destination"
        bot = AsyncMock()
        bot.get_me.return_value = SimpleNamespace(id=99)
        bot.get_chat.return_value = SimpleNamespace(
            id=-2002,
            title="new",
            type="channel",
            username="new_destination",
        )
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="administrator", can_delete_messages=True),
            SimpleNamespace(status="administrator"),
            SimpleNamespace(status="member"),
        ]

        async_to_sync(change_forced_membership_destination)(message, bot)

        rule.refresh_from_db()
        assert rule.destination_chat_id == -2001
        assert "مالک مقصد جدید" in message.reply.await_args.args[0]

    def test_dashboard_shows_owner_and_creation_date(self):
        from botapp.forced_membership import forced_membership_report
        from botapp.forced_membership_handlers import _report_text

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_chat_title="destination",
            created_by_user_id=777,
        )
        report = async_to_sync(forced_membership_report)(rule.id)

        text = _report_text(rule, report)

        assert "Owner: 777" in text
        assert rule.created_at.strftime("%Y-%m-%d") in text

    def test_csv_neutralizes_spreadsheet_formula_values(self):
        from botapp.forced_membership_handlers import export_rule_csv

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_chat_title="destination",
            created_by_user_id=7,
        )
        ForcedMembershipUserState.objects.create(
            rule=rule,
            telegram_user_id=42,
            username="=HYPERLINK(\"https://evil\")",
            first_name="+cmd",
        )

        payload = async_to_sync(export_rule_csv)(rule.id).decode("utf-8-sig")

        assert "'=HYPERLINK" in payload
        assert "'+cmd" in payload

    def test_report_callback_revalidates_access(self):
        from botapp.forced_membership_handlers import forced_membership_callback

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            created_by_user_id=7,
        )
        callback = SimpleNamespace(
            data=f"fmr:report:{rule.id}",
            from_user=SimpleNamespace(id=99),
            message=SimpleNamespace(edit_text=AsyncMock()),
            answer=AsyncMock(),
        )
        bot = AsyncMock()
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="member"),
            SimpleNamespace(status="administrator"),
        ]

        async_to_sync(forced_membership_callback)(callback, bot)

        callback.answer.assert_awaited_once_with("دسترسی ندارید.", show_alert=True)
        callback.message.edit_text.assert_not_awaited()

    def test_destination_channel_member_update_does_not_run_group_welcome(self):
        from botapp.management.commands.runbot import handle_member_update

        event = SimpleNamespace(
            chat=SimpleNamespace(id=-2001, title="destination", type="channel"),
            new_chat_member=SimpleNamespace(
                user=SimpleNamespace(id=42, username="u", first_name="U", last_name=""),
                status="member",
                is_member=True,
            ),
            old_chat_member=SimpleNamespace(status="left"),
            invite_link=None,
        )
        bot = AsyncMock()

        async_to_sync(handle_member_update)(event, bot, SimpleNamespace(update_id=17))

        bot.send_message.assert_not_awaited()
        assert not GroupSettings.objects.filter(chat_id=-2001).exists()

    def test_private_rule_keyboard_has_no_empty_destination_url(self):
        from botapp.forced_membership_handlers import _management_keyboard

        group = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        rule = ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2001,
            destination_chat_title="private",
            destination_join_url="",
            created_by_user_id=7,
        )

        keyboard = _management_keyboard(rule)

        assert all(button.url for row in keyboard.inline_keyboard for button in row if button.url is not None)
        assert not any(button.text == "مشاهده مقصد" for row in keyboard.inline_keyboard for button in row)

    def test_chat_type_enum_is_stored_as_value(self):
        from aiogram.enums import ChatType
        from botapp.forced_membership_handlers import save_rule

        source = SimpleNamespace(id=-1001, title="source")
        destination = SimpleNamespace(
            id=-2001,
            title="destination",
            type=ChatType.CHANNEL,
            username="destination",
        )

        rule = async_to_sync(save_rule)(source, destination, 7, "https://t.me/destination")

        assert rule.destination_chat_type == "channel"

    def test_bot_creator_permissions_are_valid_for_configuration(self):
        from botapp.forced_membership_handlers import configure_forced_membership

        bot = AsyncMock()
        bot.get_me.return_value = SimpleNamespace(id=99)
        bot.get_chat.return_value = SimpleNamespace(
            id=-2001,
            title="destination",
            type="channel",
            username="destination",
        )
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="creator"),
        ]
        message = self.message()

        async_to_sync(configure_forced_membership)(message, bot)

        assert ForcedMembershipRule.objects.filter(destination_chat_id=-2001).exists()
        assert "موفقیت" in message.reply.await_args.args[0]

    def test_private_destination_validation_revokes_probe_invite(self):
        from botapp.forced_membership_handlers import configure_forced_membership

        bot = AsyncMock()
        bot.get_me.return_value = SimpleNamespace(id=99)
        bot.get_chat.return_value = SimpleNamespace(
            id=-2001,
            title="private destination",
            type="channel",
            username=None,
        )
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="administrator", can_delete_messages=True),
            SimpleNamespace(status="administrator"),
        ]
        bot.create_chat_invite_link.return_value = SimpleNamespace(invite_link="https://t.me/+probe")
        message = self.message()
        message.text = "عضویت اجباری -2001"

        async_to_sync(configure_forced_membership)(message, bot)

        bot.revoke_chat_invite_link.assert_awaited_once_with(-2001, "https://t.me/+probe")
        rule = ForcedMembershipRule.objects.get()
        assert rule.destination_join_url == ""

    def test_creator_with_permissions_can_configure_rule(self):
        from botapp.forced_membership_handlers import configure_forced_membership

        bot = AsyncMock()
        bot.get_me.return_value = SimpleNamespace(id=99)
        bot.get_chat.return_value = SimpleNamespace(
            id=-2001,
            title="destination",
            type="channel",
            username="destination",
        )
        bot.get_chat_member.side_effect = [
            SimpleNamespace(status="creator"),
            SimpleNamespace(status="administrator", can_delete_messages=True),
            SimpleNamespace(status="administrator"),
        ]
        message = self.message()

        async_to_sync(configure_forced_membership)(message, bot)

        rule = ForcedMembershipRule.objects.get()
        assert rule.destination_chat_id == -2001
        assert rule.is_active is True
        assert "موفقیت" in message.reply.await_args.args[0]


class ForcedMembershipIsolationTest(TestCase):
    def test_same_user_has_independent_state_in_two_groups(self):
        from botapp.forced_membership import evaluate_nonmember_message

        group_a = GroupSettings.objects.create(chat_id=-1001)
        group_b = GroupSettings.objects.create(chat_id=-1002)
        rule_a = ForcedMembershipRule.objects.create(
            source_group=group_a,
            destination_chat_id=-2001,
            created_by_user_id=7,
        )
        rule_b = ForcedMembershipRule.objects.create(
            source_group=group_b,
            destination_chat_id=-2002,
            created_by_user_id=8,
        )
        user = SimpleNamespace(id=42, username="u", first_name="U", last_name="")

        first_a = async_to_sync(evaluate_nonmember_message)(rule_a.id, user, 1, 101)
        second_a = async_to_sync(evaluate_nonmember_message)(rule_a.id, user, 2, 102)
        first_b = async_to_sync(evaluate_nonmember_message)(rule_b.id, user, 1, 201)

        assert first_a.action == "warn"
        assert second_a.action == "delete"
        assert first_b.action == "warn"
        assert ForcedMembershipUserState.objects.filter(telegram_user_id=42).count() == 2

    def test_inactive_rule_does_not_gate_messages(self):
        from botapp.forced_membership_runtime import enforce_forced_membership_message

        group = GroupSettings.objects.create(chat_id=-1003)
        ForcedMembershipRule.objects.create(
            source_group=group,
            destination_chat_id=-2003,
            created_by_user_id=7,
            is_active=False,
        )
        message = SimpleNamespace(
            message_id=1,
            chat=SimpleNamespace(id=-1003, type="supergroup"),
            from_user=SimpleNamespace(
                id=42,
                username="u",
                first_name="U",
                last_name="",
                is_bot=False,
            ),
            sender_chat=None,
            new_chat_members=None,
            left_chat_member=None,
            pinned_message=None,
        )
        bot = AsyncMock()

        blocked = async_to_sync(enforce_forced_membership_message)(message, bot, update_id=1)

        assert blocked is False
        bot.get_chat_member.assert_not_awaited()
