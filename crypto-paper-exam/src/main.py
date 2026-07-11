"""Entry point: runs the Exam V1 scheduler continuously, once per hour, on
the hour, in the exam timezone (spec section 4.5). For a single manual run
use scripts/run_once.py instead.
"""
from __future__ import annotations

import datetime as dt
import logging

from apscheduler.schedulers.blocking import BlockingScheduler
from apscheduler.triggers.cron import CronTrigger

from database.connection import init_db
from scheduler import run_hourly
from settings import get_settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def _job() -> None:
    settings = get_settings()
    now = dt.datetime.now(dt.timezone.utc).replace(minute=0, second=0, microsecond=0)
    outcome = run_hourly(now, settings=settings)
    if outcome.already_completed:
        logger.info("run %s already completed; skipped", outcome.run.run_id)
    else:
        logger.info("run %s completed: action=%s errors=%s", outcome.run.run_id, outcome.run.action, outcome.errors)


def main() -> None:
    settings = get_settings()
    init_db(settings)

    scheduler = BlockingScheduler(timezone=settings.exam_timezone)
    scheduler.add_job(_job, CronTrigger(minute=0), id="exam_v1_hourly", misfire_grace_time=3600)
    logger.info("Exam V1 scheduler started (timezone=%s)", settings.exam_timezone)

    # Catch up immediately in case the process restarted mid-hour — the
    # scheduler's own idempotency (run_id keyed by scheduled hour) makes
    # this safe to call even if the current hour was already completed.
    _job()

    scheduler.start()


if __name__ == "__main__":
    main()
