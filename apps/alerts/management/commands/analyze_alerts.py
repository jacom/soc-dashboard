from django.core.management.base import BaseCommand
from apps.alerts.models import Alert
from apps.alerts.ai_analyzer import analyze_alert


class Command(BaseCommand):
    help = 'Run AI analysis on unanalyzed alerts (CRITICAL/HIGH/MEDIUM by default)'

    def add_arguments(self, parser):
        parser.add_argument(
            '--limit', type=int, default=50,
            help='Max alerts to process per run (default: 50)'
        )
        parser.add_argument(
            '--all-severities', action='store_true',
            help='Include LOW and INFO alerts too'
        )

    def handle(self, *args, **options):
        limit = options['limit']
        all_severities = options['all_severities']

        qs = Alert.objects.filter(ai_analysis__isnull=True)
        if not all_severities:
            qs = qs.filter(severity__in=['CRITICAL', 'HIGH', 'MEDIUM'])
        qs = qs.order_by('-timestamp')[:limit]

        alerts = list(qs)
        self.stdout.write(f'Found {len(alerts)} unanalyzed alert(s) to process...')

        done = 0
        failed = 0
        for alert in alerts:
            ok = analyze_alert(alert)
            if ok:
                done += 1
                self.stdout.write(f'  ✓ Alert #{alert.id} [{alert.severity}] {alert.rule_description[:50]}')
            else:
                failed += 1
                self.stdout.write(self.style.WARNING(
                    f'  ✗ Alert #{alert.id} [{alert.severity}] — Ollama failed (check URL/Model in Settings)'
                ))

        self.stdout.write(self.style.SUCCESS(
            f'Done — analyzed: {done}  failed: {failed}'
        ))
