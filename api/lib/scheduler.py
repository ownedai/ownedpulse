"""APScheduler — daily ingestion job, replaces n8n webhook trigger."""

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


_active_proc = None
_active_run_id = None


def stop_ingestion() -> bool:
    """Kill the currently running RSS subprocess. Returns True if killed."""
    global _active_proc
    if _active_proc and _active_proc.returncode is None:
        try:
            _active_proc.kill()
            return True
        except Exception:
            pass
    return False


async def run_ingestion_job(feed_id: str | None = None, triggered_by: str = "scheduler"):
    """Run ingestion for all enabled feeds (or a single feed_id).

    Calls fetch_feed.py as a subprocess per feed — same execution path as
    the n8n Execute Command node used previously. Scope is controlled by
    --max-age-days (default 30) in run_pipeline.py.
    """
    global _active_proc, _active_run_id
    detail = feed_id or "all-feeds"
    if not ingestion_lock.acquire("rss", detail):
        run_date = datetime.now(timezone.utc) + timedelta(minutes=30)
        scheduler.add_job(
            run_ingestion_job,
            trigger=DateTrigger(run_date=run_date),
            id="deferred_run",
            replace_existing=True,
            kwargs={"feed_id": feed_id, "triggered_by": "deferred"},
        )
        logger.info(
            f"ingestion deferred to {run_date.strftime('%H:%M UTC')} "
            f"({ingestion_lock.conflict_detail()})"
        )
        return

    try:
        feeds = [feed_id] if feed_id else _get_enabled_feeds()
    except Exception as e:
        logger.error(f"ingestion: failed to load feed list: {e}")
        ingestion_lock.release()
        return

    logger.info(f"ingestion starting: {len(feeds)} feed(s), triggered_by={triggered_by}")

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
            logger.info(f"ingestion: starting feed={fid} run_id={run_id}")
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
                _active_proc = proc
                _active_run_id = run_id
                stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=1800)
                _active_proc = None
                _active_run_id = None
                if proc.returncode == 0:
                    logger.info(f"ingestion: feed={fid} run_id={run_id} complete")
                    continue
                else:
                    error_detail = f"Process exited rc={proc.returncode}: {stderr.decode()[:400]}"
                    logger.error(f"ingestion: feed={fid} run_id={run_id} failed: {error_detail}")
            except asyncio.TimeoutError:
                error_detail = "Timed out after 30 minutes"
                logger.error(f"ingestion: feed={fid} run_id={run_id} timed out")
            except Exception as e:
                error_detail = str(e)
                logger.error(f"ingestion: feed={fid} run_id={run_id} exception: {e}")

            if error_detail:
                _write_run_log_error_or_insert(run_id, trigger_source, triggered_by, fid, error_detail)
    finally:
        ingestion_lock.release()


def reschedule_ingestion_job(hour: int, minute: int, timezone: str):
    """Reschedule the ingestion job with new cron parameters at runtime."""
    scheduler.reschedule_job(
        "daily_ingestion",
        trigger=CronTrigger(hour=hour, minute=minute, timezone=timezone),
    )
    logger.info(f"ingestion rescheduled: daily at {hour:02d}:{minute:02d} {timezone}")


def _read_schedule_from_db():
    """Read schedule from system_config, falling back to env var defaults."""
    hour = RSS_SCHEDULE_HOUR
    minute = RSS_SCHEDULE_MINUTE
    tz = RSS_SCHEDULE_TIMEZONE
    try:
        conn = get_pg_conn()
        try:
            cur = conn.cursor()
            cur.execute(
                "SELECT key, value FROM system_config WHERE key IN "
                "('rss_schedule_hour', 'rss_schedule_minute', 'rss_schedule_timezone')"
            )
            rows = dict(cur.fetchall())
            cur.close()
            if rows:
                hour = int(rows.get("rss_schedule_hour", hour))
                minute = int(rows.get("rss_schedule_minute", minute))
                tz = rows.get("rss_schedule_timezone", tz)
        finally:
            conn.close()
    except Exception as e:
        logger.warning("Could not read schedule from system_config, using env defaults: %s", e)
    return hour, minute, tz


def setup_scheduler():
    """Add jobs and configure schedule. Called once at application startup.

    Reads persisted schedule from system_config (written by the admin UI).
    Falls back to env var defaults if the DB is unavailable or empty.
    """
    hour, minute, tz = _read_schedule_from_db()
    scheduler.add_job(
        run_ingestion_job,
        trigger=CronTrigger(hour=hour, minute=minute, timezone=tz),
        id="daily_ingestion",
        name="Daily Source Ingestion",
        replace_existing=True,
        misfire_grace_time=3600,
    )
    logger.info(
        f"Source ingestion scheduled: daily at {hour:02d}:{minute:02d} {tz}"
    )
