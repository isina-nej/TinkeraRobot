from asgiref.sync import async_to_sync
from django.core.management.base import BaseCommand
from django.utils import timezone

from botapp.models import GroupSettings
from botapp.services import purge_old_moderation_logs


class Command(BaseCommand):
    help = "Delete moderation logs older than each group's retention policy."

    def handle(self, *args, **options):
        total = 0
        for group in GroupSettings.objects.only("id", "log_retention_days"):
            total += async_to_sync(purge_old_moderation_logs)(
                group.id,
                group.log_retention_days,
            )
        self.stdout.write(
            self.style.SUCCESS(
                f"Deleted {total} moderation logs at {timezone.now().isoformat()}."
            )
        )
