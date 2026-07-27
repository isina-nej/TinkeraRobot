from django.contrib import admin
from django.test import TestCase

from botapp.models import (
    MemoryConversation,
    MemoryConversationMember,
    MemoryItem,
    MemoryLifecycleEvent,
    MemorySource,
)


class MemoryAdminTest(TestCase):
    def test_memory_models_are_registered_with_read_only_audit_models(self):
        for model in (
            MemoryConversation,
            MemoryConversationMember,
            MemoryItem,
            MemorySource,
            MemoryLifecycleEvent,
        ):
            assert model in admin.site._registry

        assert set(field.name for field in MemorySource._meta.fields) <= set(
            admin.site._registry[MemorySource].readonly_fields
        )
        assert set(field.name for field in MemoryLifecycleEvent._meta.fields) <= set(
            admin.site._registry[MemoryLifecycleEvent].readonly_fields
        )
