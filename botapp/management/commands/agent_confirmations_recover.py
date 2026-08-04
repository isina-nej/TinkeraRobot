"""Report (and optionally fail) agent confirmations stuck in ``executing``.

A confirmation can be left in ``executing`` if the process died after the
operation was claimed but before the tool finished. This command surfaces such
records for admin review. With ``--fail`` it transitions them to ``failed`` so
they are visible in the audit trail. It NEVER re-runs the underlying dangerous
operation automatically; an admin must decide whether to re-issue the command.
"""

from django.core.management.base import BaseCommand

from botapp.agent import confirmations


class Command(BaseCommand):
    help = "Report or fail agent confirmations stuck in the 'executing' state."

    def add_arguments(self, parser):
        parser.add_argument(
            "--stuck-minutes",
            type=int,
            default=5,
            help="Age (minutes) after which an 'executing' record is considered stuck.",
        )
        parser.add_argument(
            "--fail",
            action="store_true",
            help="Transition stuck records to 'failed' (does NOT re-run the operation).",
        )

    def handle(self, *args, **options):
        minutes = options["stuck_minutes"]
        stuck = list(confirmations.find_stuck_executing(minutes))
        if not stuck:
            self.stdout.write(f"No confirmations stuck in 'executing' for over {minutes} minute(s).")
            return

        self.stdout.write(f"Found {len(stuck)} stuck confirmation(s):")
        for row in stuck:
            self.stdout.write(
                f"  id={row.id} chat={row.chat_id} tool={row.tool_name} "
                f"requester={row.requester_user_id} since={row.executing_started_at}"
            )

        if options["fail"]:
            failed = confirmations.fail_stuck_executing(minutes)
            self.stdout.write(
                self.style.WARNING(
                    f"Marked {failed} record(s) as 'failed'. The operations were NOT re-run; "
                    "review the audit log and re-issue commands manually if needed."
                )
            )
        else:
            self.stdout.write("Run again with --fail to mark these as failed (no re-execution).")
