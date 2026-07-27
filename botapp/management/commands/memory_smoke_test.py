from django.core.management.base import BaseCommand
from django.utils import timezone
from botapp.models import MemoryConversation, MemoryConversationMember, MemoryItem, TelegramUser, MemorySource, MemoryLifecycleEvent
from botapp.memory.storage import ingest_message
from botapp.memory.context import build_memory_context


class Command(BaseCommand):
    help = "Run a non-destructive smoke test of the memory system"

    def handle(self, *args, **options):
        self.stdout.write("Starting memory smoke test...")

        test_user_id = -999999
        test_chat_id = -888888
        test_conversation_id = f"telegram:{test_chat_id}:0"

        try:
            # 1. Create a test user
            self.stdout.write("1. Testing user creation...")
            user, created = TelegramUser.objects.get_or_create(telegram_user_id=test_user_id)
            
            # 2. Create a test conversation
            self.stdout.write("2. Testing conversation creation...")
            conversation, created = MemoryConversation.objects.get_or_create(
                platform="telegram",
                chat_id=test_chat_id,
                thread_id=0,
                conversation_id=test_conversation_id,
                defaults={"chat_type": "private", "title": "Smoke Test Conversation"}
            )

            # 3. Create a test member
            self.stdout.write("3. Testing member creation...")
            member, created = MemoryConversationMember.objects.get_or_create(
                conversation=conversation,
                user=user
            )
            
            # 4. Test Ingestion
            self.stdout.write("4. Testing memory ingestion...")
            items = ingest_message(
                user_id=test_user_id,
                conversation=conversation,
                message_id=1,
                text="یادت باشه اسم من تستر است.",
                timestamp=timezone.now(),
                is_command=False,
                is_forwarded=False,
                source_kind="smoke_test"
            )
            
            if not items:
                self.stderr.write("Ingestion failed: No memory items returned.")
                return

            memory_item = items[0]
            if memory_item.status != MemoryItem.Status.ACTIVE:
                self.stderr.write("Ingestion failed: Item is not active.")
                return

            # 5. Test Context Builder (Retrieval)
            self.stdout.write("5. Testing memory retrieval...")
            context = build_memory_context(
                user_id=test_user_id,
                conversation=conversation,
                query="اسم من چیست؟",
                max_tokens=600
            )

            if "تستر" not in context.text:
                self.stderr.write("Retrieval failed: Text not found in context.")
                return
                
            self.stdout.write(self.style.SUCCESS("All smoke tests passed successfully!"))

        except Exception as e:
            self.stderr.write(f"Smoke test failed with exception: {str(e)}")
            
        finally:
            self.stdout.write("Cleaning up smoke test data...")
            # Clean up all created items. Order matters due to foreign keys.
            try:
                if 'user' in locals():
                    MemoryLifecycleEvent.objects.filter(actor_user=user).delete()
                    MemorySource.objects.filter(speaker_user=user).delete()
                    MemoryItem.objects.filter(owner_user=user).delete()
                    MemoryConversationMember.objects.filter(user=user).delete()
                    TelegramUser.objects.filter(telegram_user_id=test_user_id).delete()
                
                if 'conversation' in locals():
                    MemoryConversation.objects.filter(conversation_id=test_conversation_id).delete()
                    
                self.stdout.write(self.style.SUCCESS("Cleanup complete."))
            except Exception as e:
                self.stderr.write(f"Cleanup failed with exception: {str(e)}")
