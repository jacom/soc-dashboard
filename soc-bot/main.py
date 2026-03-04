#!/usr/bin/env python3
"""
SOC Bot - Main entry point.
APScheduler-based polling loop that fetches Wazuh alerts and processes them.
"""
import logging
import os
import sys
import signal
from datetime import datetime, timedelta, timezone
from pathlib import Path

# Load environment variables from .env file
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / '.env')

import redis
from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.interval import IntervalTrigger

from engine.alert_processor import process_batch, get_redis_client
from engine.rule_engine import load_config
from integrations import wazuh, ollama

# Configure logging
LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO').upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s [%(levelname)s] %(name)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger('soc-bot')

POLL_INTERVAL = int(os.environ.get('POLL_INTERVAL', '30'))
REDIS_URL = os.environ.get('REDIS_URL', 'redis://127.0.0.1:6379/2')

# Redis keys for state tracking
LAST_POLL_KEY = 'soc:last_poll_time'
STATS_PROCESSED_KEY = 'soc:stats:total_processed'
STATS_ERRORS_KEY = 'soc:stats:total_errors'


def poll_and_process():
    """
    Main polling job: fetch new Wazuh alerts and process them.
    Called every POLL_INTERVAL seconds by APScheduler.
    """
    logger.debug("--- Poll cycle starting ---")

    config = load_config()
    wazuh_config = config.get('wazuh', {})
    min_level = wazuh_config.get('min_rule_level', 3)
    lookback = wazuh_config.get('lookback_minutes', 5)
    max_alerts = wazuh_config.get('max_alerts_per_poll', 100)

    try:
        r = get_redis_client()

        # Determine start time for fetching alerts
        last_poll_str = r.get(LAST_POLL_KEY)
        if last_poll_str:
            try:
                since = datetime.fromisoformat(last_poll_str)
            except ValueError:
                since = datetime.now(timezone.utc) - timedelta(minutes=lookback)
        else:
            since = datetime.now(timezone.utc) - timedelta(minutes=lookback)

        # Update last poll timestamp BEFORE fetching (to avoid gaps on error)
        now = datetime.now(timezone.utc)
        r.set(LAST_POLL_KEY, now.isoformat())

        # Fetch alerts from Wazuh
        raw_alerts = wazuh.fetch_alerts(since=since, min_level=min_level, limit=max_alerts)

        if not raw_alerts:
            logger.debug("No new alerts from Wazuh")
            return

        # Parse alerts
        parsed_alerts = []
        for raw in raw_alerts:
            try:
                parsed = wazuh.parse_alert(raw)
                parsed_alerts.append(parsed)
            except Exception as e:
                logger.error(f"Failed to parse alert: {e}")

        if not parsed_alerts:
            return

        logger.info(f"Processing {len(parsed_alerts)} new alert(s)...")

        # Process the batch
        processed, skipped = process_batch(parsed_alerts, r, config)
        logger.info(f"Batch complete: {processed} processed, {skipped} skipped/deduped")

        # Update stats
        r.incrby(STATS_PROCESSED_KEY, processed)

    except redis.ConnectionError as e:
        logger.error(f"Redis connection failed: {e}")
    except Exception as e:
        logger.error(f"Poll cycle error: {e}", exc_info=True)
        try:
            r = get_redis_client()
            r.incr(STATS_ERRORS_KEY)
        except Exception:
            pass


def startup_checks():
    """Run startup checks and log service status."""
    logger.info("=" * 60)
    logger.info("SOC Bot starting up...")
    logger.info(f"  Poll interval: {POLL_INTERVAL}s")
    logger.info(f"  Wazuh API: {os.environ.get('WAZUH_API_URL', 'not set')}")
    logger.info(f"  Dashboard: {os.environ.get('DASHBOARD_URL', 'not set')}")
    logger.info(f"  Ollama: {os.environ.get('OLLAMA_URL', 'not set')} (model: {os.environ.get('OLLAMA_MODEL', 'openchat')})")
    logger.info(f"  TheHive: {os.environ.get('THEHIVE_URL', 'disabled')}")
    logger.info(f"  LINE Notify: {'enabled' if os.environ.get('LINE_NOTIFY_TOKEN') else 'disabled'}")

    # Check Redis
    try:
        r = get_redis_client()
        r.ping()
        logger.info("  Redis: connected")
    except Exception as e:
        logger.warning(f"  Redis: FAILED ({e}) — deduplication will not work!")

    # Check Ollama
    if ollama.check_ollama_available():
        logger.info(f"  Ollama: available (model: {os.environ.get('OLLAMA_MODEL')})")
    else:
        logger.warning(f"  Ollama: NOT available — AI analysis will be skipped")

    logger.info("=" * 60)


def main():
    startup_checks()

    scheduler = BlockingScheduler(timezone='UTC')
    scheduler.add_job(
        poll_and_process,
        trigger=IntervalTrigger(seconds=POLL_INTERVAL),
        id='poll_wazuh',
        name='Poll Wazuh Alerts',
        max_instances=1,  # Prevent overlapping runs
        coalesce=True,    # Skip missed runs
        misfire_grace_time=30,
    )

    # Handle graceful shutdown
    def shutdown(signum, frame):
        logger.info("Received shutdown signal, stopping scheduler...")
        scheduler.shutdown(wait=False)
        sys.exit(0)

    signal.signal(signal.SIGTERM, shutdown)
    signal.signal(signal.SIGINT, shutdown)

    logger.info(f"Starting scheduler (polling every {POLL_INTERVAL}s)...")

    # Run one poll immediately on startup
    try:
        poll_and_process()
    except Exception as e:
        logger.error(f"Initial poll failed: {e}")

    try:
        scheduler.start()
    except (KeyboardInterrupt, SystemExit):
        logger.info("SOC Bot stopped.")


if __name__ == '__main__':
    main()
