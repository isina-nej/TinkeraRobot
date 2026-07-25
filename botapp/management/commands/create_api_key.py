from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError

from botapp.moderation import create_api_key


class Command(BaseCommand):
    help = "Create a hashed staff API key; the plaintext is printed once."

    def add_arguments(self, parser):
        parser.add_argument("name")
        parser.add_argument("--username")

    def handle(self, *args, **options):
        user = None
        if options["username"]:
            user = get_user_model().objects.filter(
                username=options["username"],
                is_staff=True,
            ).first()
            if not user:
                raise CommandError("Staff user not found.")
        key, raw = create_api_key(options["name"], user)
        self.stdout.write(self.style.SUCCESS(f"API key created: {key.name}"))
        self.stdout.write(raw)
        self.stdout.write("Store it now; it cannot be recovered later.")
