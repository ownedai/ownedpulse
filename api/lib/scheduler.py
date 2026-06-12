"""APScheduler — daily RSS ingestion job, replaces n8n webhook trigger."""

import os
import asyncio
import logging
import subprocess
import uuid
from datetime import datetime, timezone, timedelta
from lib import ingestion_lock
from lib.db import get_pg_conn

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger

logger = logging.getLogger(__name__)

RSS_SCHEDULE_HOUR = int(os.environ.get("RSS_SCHEDULE_HOUR", "9"))
RSS_SCHEDULE_MINUTE = int(os.environ.get("RSS_SCHEDULE_MINUTE", "0"))
RSS_SCHEDULE_TIMEZONE = os.environ.get("RSS_SCHEDULE_TIMEZONE", "Europe/Berlin")

PIPELINE_SCRIPT = os.environ.get("PIPELINE_SCRIPT", "/opt/scripts/rss/run_pipeline.py")

scheduler = AsyncIOScheduler()


def get_scheduler() -> AsyncIOScheduler:
    return scheduler


def _write_run_log_error_or_insert(
    run_id: str, trigger_source: str, triggered_by: str, feed_id: str, detail: str
):
    """Update existing run_log row to error, or insert a new one if fetch_feed.py never ran."""
    try:
        conn = get_pg_conn()
        try:
            with conn.cursor() as c:
                c.execute(
                    """UPDATE run_log SET status='error', completed_at=NOW(), error_detail=%s
                       WHERE run_id=%s""",
                    (detail[:500], run_id),
                )
                if c.rowcount == 0:
                    c.execute(
                        """INSERT INTO run_log
                               (run_id, trigger_source, triggered_by, feed_source, status,
                                completed_at, error_detail)
                           VALUES (%s, %s, %s, %s, 'error', NOW(), %s)
                           ON CONFLICT (run_id) DO NOTHING""",
                        (run_id, trigger_source, triggered_by, feed_id, detail[:500]),
                    )
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()
    except Exception as e:
        logger.warning(f"scheduler: could not write run_log error: {e}")


def _get_enabled_feeds() -> list[str]:
    conn = get_pg_conn()
    try:
        with conn.cursor() as c:
            c.execute("SELECT feed_id FROM feed_config WHERE enabled = TRUE ORDER BY feed_id")
            return [row[0] for row in c.fetchall()]
    finally:
        conn.close()


async def run_rss_ingestion_job(feed_id: str | None = None, triggered_by: str = "scheduler"):
    """Run RSS ingestion for all enabled feeds (or a single feed_id).

    Calls fetch_feed.py as a subprocess per feed — same execution path as
    the n8n Execute Command node used previously.
    """
    detail = feed_id or "all-feeds"
    if not ingestion_lock.acquire("rss", detail):
        run_date = datetime.now(timezone.utc) + timedelta(minutes=30)
        scheduler.add_job(
            run_rss_ingestion_job,
            trigger=DateTrigger(run_date=run_date),
            id="rss_deferred_run",
            replace_existing=True,
            kwargs={"feed_id": feed_id, "triggered_by": "deferred"},
        )
        logger.info(
            f"RSS ingestion deferred to {run_date.strftime('%H:%M UTC')} "
            f"({ingestion_lock.conflict_detail()})"
        )
        return

    try:
        feeds = [feed_id] if feed_id else _get_enabled_feeds()
    except Exception as e:
        logger.error(f"RSS ingestion: failed to load feed list: {e}")
        ingestion_lock.release()
        return

    logger.info(f"RSS ingestion starting: {len(feeds)} feed(s), triggered_by={triggered_by}")

    try:
        for fid in feeds:
            run_id = str(uuid.uuid4())
            trigger_source = "scheduled" if triggered_by == "scheduler" else "manual"
            cmd = [
                "python", PIPELINE_SCRIPT,
                "--feed-id", fid,
                "--trigger-source", trigger_source,
                "--triggered-by", triggered_by,
                "--run-id", run_id,
            ]
            logger.info(f"RSS ingestion: starting feed={fid} run_id={run_id}")
            error_detail = None
            try:
                env = os.environ.copy()
                pg_host = env.get("POSTGRES_HOST", "postgres")
                pg_port = env.get("POSTGRES_PORT", "5432")
                pg_user = env.get("POSTGRES_USER", "postgres")
                pg_pass = env.get("POSTGRES_PASSWORD", "")
                pg_db   = env.get("POSTGRES_DB", "knowledge_base")
                env.setdefault("PG_DSN",
                    f"postgresql://{pg_user}:{pg_pass}@{pg_host}:{pg_port}/{pg_db}")
                proc = await asyncio.create_subprocess_exec(
                    *cmd,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)
                if proc.returncode == 0:
                    logger.info(f"RSS ingestion: feed={fid} run_id={run_id} complete")
                    continue
                else:
                    error_detail = f"Process exited rc={proc.returncode}: {stderr.decode()[:400]}"
                    logger.error(f"RSS ingestion: feed={fid} run_id={run_id} failed: {error_detail}")
            except asyncio.TimeoutError:
                error_detail = "Timed out after 30 minutes"
                logger.error(f"RSS ingestion: feed={fid} run_id={run_id} timed out")
            except Exception as e:
                error_detail = str(e)
                logger.error(f"RSS ingestion: feed={fid} run_id={run_id} exception: {e}")

            if error_detail:
                _write_run_log_error_or_insert(run_id, trigger_source, triggered_by, fid, error_detail)
    finally:
        ingestion_lock.release()


def reschedule_rss_job(hour: int, minute: int, timezone: str):
    """Reschedule the RSS ingestion job with new cron parameters at runtime."""
    scheduler.reschedule_job(
        "rss_daily_ingestion",
        trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
    )
    logger.info(f"RSS ingestion rescheduled: daily at {hour:02d}:{minute:02d} {timezone}")


def setup_scheduler():
    """Add jobs and configure schedule. Called once at application startup."""
    scheduler.add_job(
        run_rss_ingestion_job,
        trigger=CronTrigger(
            hour=RSS_SCHEDULE_HOUR,
            minute=RSS_SCHEDULE_MINUTE,
            timezone=RSS_SCHEDULE_TIMEZONE,
        ),
        id="rss_daily_ingestion",
        name="Daily RSS Ingestion",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        f"RSS ingestion scheduled: daily at "
        f"{RSS_SCHEDULE_HOUR:02d}:{RSS_SCHEDULE_MINUTE:02d} {RSS_SCHEDULE_TIMEZONE}"
    )
