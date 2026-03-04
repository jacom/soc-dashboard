from django.core.management.base import BaseCommand
from apps.alerts.wazuh_fetcher import fetch_and_save


class Command(BaseCommand):
    help = 'Fetch alerts from Wazuh API and save new ones to the database'

    def add_arguments(self, parser):
        parser.add_argument(
            '--hours', type=int, default=1,
            help='Fetch alerts from the last N hours (default: 1)'
        )
        parser.add_argument(
            '--min-level', type=int, default=3,
            help='Minimum Wazuh rule level to fetch (default: 3)'
        )
        parser.add_argument(
            '--limit', type=int, default=500,
            help='Maximum number of alerts to fetch per run (default: 500)'
        )

    def handle(self, *args, **options):
        hours = options['hours']
        min_level = options['min_level']
        limit = options['limit']

        self.stdout.write(
            f'Fetching Wazuh alerts (last {hours}h, level>={min_level}, limit={limit})...'
        )

        stats = fetch_and_save(hours=hours, min_level=min_level, limit=limit)

        if stats['error_msg']:
            self.stderr.write(self.style.ERROR(f"Error: {stats['error_msg']}"))
            return

        self.stdout.write(self.style.SUCCESS(
            f"Done — fetched: {stats['fetched']}  "
            f"new: {stats['created']}  "
            f"skipped: {stats['skipped']}  "
            f"errors: {stats['errors']}"
        ))
