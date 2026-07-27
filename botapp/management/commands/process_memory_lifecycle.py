from django.core.management.base import BaseCommand

from botapp.memory import expire_memories


class Command(BaseCommand):
    help = "Expire non-critical memory items according to their configured TTL."

    def handle(self, *args, **options):
        count = expire_memories()
        self.stdout.write(self.style.SUCCESS(f"Expired {count} memory item(s)."))
