from django.core.management.base import BaseCommand

from apps.market.services import seed_instruments
from apps.strategies.services import seed_strategy_catalog


class Command(BaseCommand):
    help = "Seed the fixed v1 ETF universe and three immutable strategy versions"

    def handle(self, *args, **options):
        instruments = seed_instruments()
        strategies = seed_strategy_catalog()
        self.stdout.write(
            self.style.SUCCESS(f"Seeded {len(instruments)} instruments and {len(strategies)} strategies")
        )
