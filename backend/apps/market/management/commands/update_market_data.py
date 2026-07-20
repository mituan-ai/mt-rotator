from datetime import date

from django.core.management.base import BaseCommand

from apps.market.services import import_market_data


class Command(BaseCommand):
    help = "Fetch and validate the free ETF end-of-day dataset"

    def add_arguments(self, parser):
        parser.add_argument("--start", default=None)

    def handle(self, *args, **options):
        batch = import_market_data(
            triggered_by="management-command",
            start=date.fromisoformat(options["start"]) if options["start"] else None,
        )
        self.stdout.write(f"batch={batch.id} status={batch.status} rows={batch.row_count}")
        if batch.errors:
            self.stderr.write(str(batch.errors))
