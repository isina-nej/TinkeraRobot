from types import SimpleNamespace

from asgiref.sync import async_to_sync
from django.db import IntegrityError, transaction
from django.test import SimpleTestCase, TestCase


class ForcedMembershipDestinationParserTest(SimpleTestCase):
    def test_normalizes_public_username_url_and_numeric_chat_id(self):
        from botapp.forced_membership import normalize_destination_reference

        assert normalize_destination_reference("  @Tinkera_News  ").value == "@tinkera_news"
        assert normalize_destination_reference("https://t.me/Tinkera_News?start=ignored").value == "@tinkera_news"
        numeric = normalize_destination_reference(" -1001234567890 ")
        assert numeric.value == -1001234567890
        assert numeric.kind == "chat_id"

    def test_rejects_private_and_invalid_destinations(self):
        from botapp.forced_membership import normalize_destination_reference

        for value in ("", "https://t.me/+secret", "not telegram", "@bad"):
            with self.assertRaises(ValueError):
                normalize_destination_reference(value)


class TelegramMembershipStatusTest(SimpleTestCase):
    def test_restricted_requires_is_member(self):
        from botapp.forced_membership import normalize_membership_status

        assert normalize_membership_status("creator").is_member is True
        assert normalize_membership_status("administrator").is_member is True
        assert normalize_membership_status("member").is_member is True
        from aiogram.enums import ChatMemberStatus
        assert normalize_membership_status(ChatMemberStatus.MEMBER).is_member is True
        assert normalize_membership_status("restricted", restricted_is_member=True).is_member is True
        assert normalize_membership_status("restricted", restricted_is_member=False).is_member is False
        assert normalize_membership_status("left").is_member is False
        assert normalize_membership_status("kicked").is_member is False
        assert normalize_membership_status("banned").normalized == "kicked"


class ForcedMembershipPersistenceTest(TestCase):
    def setUp(self):
        from botapp.models import ForcedMembershipRule, GroupSettings

        self.source = GroupSettings.objects.create(chat_id=-1001, chat_title="source")
        self.rule = ForcedMembershipRule.objects.create(
            source_group=self.source,
            destination_chat_id=-2001,
            destination_chat_title="destination",
            destination_chat_type="channel",
            destination_username="destination",
            destination_join_url="https://t.me/destination",
            created_by_user_id=7,
        )

    def test_rule_and_user_state_are_isolated_and_unique(self):
        from botapp.models import ForcedMembershipRule, ForcedMembershipUserState

        state = ForcedMembershipUserState.objects.create(rule=self.rule, telegram_user_id=42)
        assert state.rule_id == self.rule.id
        with self.assertRaises(IntegrityError), transaction.atomic():
            ForcedMembershipUserState.objects.create(rule=self.rule, telegram_user_id=42)
        with self.assertRaises(IntegrityError), transaction.atomic():
            ForcedMembershipRule.objects.create(
                source_group=self.source,
                destination_chat_id=-2001,
                created_by_user_id=7,
            )

    def test_first_nonmember_message_warns_then_later_messages_delete(self):
        from botapp.forced_membership import evaluate_nonmember_message
        from botapp.models import ForcedMembershipUserState

        user = SimpleNamespace(id=42, username=None, first_name="<Ali>", last_name="")
        first = async_to_sync(evaluate_nonmember_message)(self.rule.id, user, 100, 10)
        second = async_to_sync(evaluate_nonmember_message)(self.rule.id, user, 101, 11)
        duplicate = async_to_sync(evaluate_nonmember_message)(self.rule.id, user, 101, 11)

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        assert first.action == "warn"
        assert second.action == "delete"
        assert duplicate.action == "ignore"
        assert state.message_count_while_not_member == 2
        assert state.first_warning_at is not None

    def test_membership_transitions_record_join_leave_and_rejoin_once(self):
        from botapp.forced_membership import evaluate_nonmember_message, observe_membership
        from botapp.models import ForcedMembershipEvent, ForcedMembershipUserState

        user = SimpleNamespace(id=42, username="ali", first_name="Ali", last_name="Test")
        async_to_sync(evaluate_nonmember_message)(self.rule.id, user, 200, 20)
        async_to_sync(observe_membership)(self.rule.id, user, "member", update_id=201)
        async_to_sync(observe_membership)(self.rule.id, user, "left", update_id=202)
        async_to_sync(observe_membership)(self.rule.id, user, "member", update_id=203)
        async_to_sync(observe_membership)(self.rule.id, user, "member", update_id=203)

        state = ForcedMembershipUserState.objects.get(rule=self.rule, telegram_user_id=42)
        assert state.current_membership_status == "member"
        assert state.is_currently_member is True
        assert state.has_ever_joined is True
        assert state.join_count == 2
        assert state.leave_count == 1
        assert state.rejoin_count == 1
        assert ForcedMembershipEvent.objects.filter(rule=self.rule, event_type="joined").count() == 1
        assert ForcedMembershipEvent.objects.filter(rule=self.rule, event_type="left").count() == 1
        assert ForcedMembershipEvent.objects.filter(rule=self.rule, event_type="rejoined").count() == 1
