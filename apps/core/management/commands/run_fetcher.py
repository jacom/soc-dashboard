"""
Management command: run_fetcher
รัน Wazuh fetch loop ทุก 60 วินาที พร้อม pipeline queue

Pipeline processing ทั้งหมดทำใน process นี้ (soc-fetcher) เท่านั้น
เพื่อป้องกัน race condition กับ Gunicorn workers หลาย process

Trigger file: /tmp/soc_batch_trigger
  - สร้างโดย batch_analyze web endpoint เพื่อสั่งให้ scan หา unanalyzed alerts
  - ลบโดย run_fetcher หลัง enqueue เสร็จ

Status file: /tmp/soc_pipeline_status.json
  - เขียนโดย run_fetcher ทุก loop
  - อ่านโดย pipeline_status web endpoint
"""
import json
import pathlib
import time
import logging
from django.core.management.base import BaseCommand

logger = logging.getLogger(__name__)

TRIGGER_FILE = pathlib.Path('/tmp/soc_batch_trigger')
STATUS_FILE  = pathlib.Path('/tmp/soc_pipeline_status.json')


def _write_status(busy, queue_depth, analyzed, total):
    try:
        STATUS_FILE.write_text(json.dumps({
            'busy':        busy,
            'queue_depth': queue_depth,
            'analyzed':    analyzed,
            'total':       total,
            'pending':     total - analyzed,
        }))
    except Exception:
        pass


def _run_autodismiss(stdout):
    """Auto-dismiss old alerts based on IntegrationConfig settings."""
    try:
        from apps.config.models import IntegrationConfig
        from apps.alerts.models import Alert
        from django.utils import timezone

        configs = {c.key: c.value for c in IntegrationConfig.objects.filter(
            key__in=['AUTODISMISS_ENABLED', 'AUTODISMISS_DAYS', 'AUTODISMISS_SEVERITIES']
        )}
        if configs.get('AUTODISMISS_ENABLED', 'false') != 'true':
            return

        try:
            days = int(configs.get('AUTODISMISS_DAYS', '90'))
        except ValueError:
            days = 90
        sevs = [s.strip() for s in configs.get('AUTODISMISS_SEVERITIES', 'INFO,LOW').split(',') if s.strip()]
        if not sevs:
            return

        cutoff = timezone.now() - timezone.timedelta(days=days)
        count = Alert.objects.filter(
            severity__in=sevs,
            timestamp__lt=cutoff,
            dismissed=False,
        ).update(dismissed=True, dismissed_at=timezone.now())

        if count:
            stdout.write(f'[AUTO-DISMISS] Dismissed {count} alerts older than {days} days ({",".join(sevs)})')
            logger.info(f'run_fetcher auto-dismiss: {count} alerts dismissed')
    except Exception as e:
        logger.error(f'run_fetcher auto-dismiss error: {e}')


def _scan_unanalyzed(stdout, include_medium=False):
    """Scan DB for unanalyzed alerts and enqueue into soc-fetcher pipeline."""
    from apps.alerts.models import Alert
    from apps.alerts.pipeline import enqueue_pipeline, is_busy, queue_depth as qd

    if is_busy() or qd() > 0:
        return 0  # Already has work

    sevs = ['CRITICAL', 'HIGH']
    if include_medium:
        sevs.append('MEDIUM')

    missed = Alert.objects.filter(
        severity__in=sevs,
        ai_analysis__isnull=True,
    ).order_by('timestamp')
    count = missed.count()
    for alert in missed:
        enqueue_pipeline(alert)
    if count:
        stdout.write(f'[SCAN] Enqueued {count} unanalyzed {"CRIT+HIGH+MED" if include_medium else "CRIT+HIGH"} alerts')
        logger.info(f'run_fetcher scan: enqueued {count} alerts (medium={include_medium})')
    return count


class Command(BaseCommand):
    help = 'Run Wazuh alert fetcher loop every 60 seconds'

    def add_arguments(self, parser):
        parser.add_argument('--interval', type=int, default=60,
                            help='Fetch interval in seconds (default: 60)')
        parser.add_argument('--hours', type=int, default=1,
                            help='Look-back window in hours (default: 1)')
        parser.add_argument('--min-level', type=int, default=3,
                            help='Minimum rule level (default: 3)')

    def handle(self, *args, **options):
        interval  = options['interval']
        hours     = options['hours']
        min_level = options['min_level']

        self.stdout.write(self.style.SUCCESS(
            f'Starting Wazuh fetcher — interval={interval}s, hours={hours}, min_level={min_level}'
        ))
        logger.info(f'run_fetcher started: interval={interval}s')

        # Startup: re-enqueue unanalyzed HIGH/CRITICAL (handles server-restart queue loss)
        try:
            count = _scan_unanalyzed(self.stdout, include_medium=False)
            if count:
                self.stdout.write(self.style.WARNING(f'[STARTUP] Re-enqueued {count} unanalyzed HIGH/CRITICAL alerts'))
        except Exception as e:
            logger.error(f'run_fetcher startup scan error: {e}')

        loop_count = 0
        while True:
            loop_count += 1

            # ── Check batch trigger (from web UI Batch Analyze button) ────────
            if TRIGGER_FILE.exists():
                try:
                    TRIGGER_FILE.unlink()
                    count = _scan_unanalyzed(self.stdout, include_medium=True)
                    self.stdout.write(self.style.SUCCESS(
                        f'[BATCH] Trigger received — enqueued {count} alerts (CRIT+HIGH+MED)'
                    ))
                except Exception as e:
                    logger.error(f'run_fetcher batch trigger error: {e}')

            # ── Auto-dismiss: รันทุก 24 ชั่วโมง (1440 iterations × 60s) ────────
            if loop_count % 1440 == 0:
                _run_autodismiss(self.stdout)

            # ── Periodic re-scan every 5 min: catch HIGH/CRITICAL that slipped ─
            if loop_count % 5 == 0:
                try:
                    _scan_unanalyzed(self.stdout, include_medium=False)
                except Exception as e:
                    logger.error(f'run_fetcher periodic scan error: {e}')

            # ── Normal Wazuh fetch ────────────────────────────────────────────
            try:
                from apps.alerts.wazuh_fetcher import fetch_and_save
                stats = fetch_and_save(hours=hours, min_level=min_level)

                if stats['error_msg']:
                    self.stdout.write(self.style.ERROR(f'[ERROR] {stats["error_msg"]}'))
                else:
                    msg = (f'[OK] fetched={stats["fetched"]} '
                           f'created={stats["created"]} '
                           f'skipped={stats["skipped"]}')
                    if stats['created']:
                        self.stdout.write(self.style.SUCCESS(msg))
                    else:
                        self.stdout.write(msg)

            except Exception as e:
                logger.error(f'run_fetcher error: {e}')
                self.stdout.write(self.style.ERROR(f'[EXCEPTION] {e}'))

            # ── Write status file for web UI pipeline_status endpoint ─────────
            try:
                from apps.alerts.pipeline import is_busy, queue_depth
                from apps.alerts.models import Alert, AIAnalysis
                total    = Alert.objects.filter(severity__in=['CRITICAL', 'HIGH', 'MEDIUM']).count()
                analyzed = AIAnalysis.objects.filter(alert__severity__in=['CRITICAL', 'HIGH', 'MEDIUM']).count()
                _write_status(is_busy(), queue_depth(), analyzed, total)
            except Exception:
                pass

            time.sleep(interval)
