"""APScheduler bootstrap — registers the daily cron jobs from the brief.

Times are interpreted in the timezone from settings (default America/New_York).
The scheduler is started inside FastAPI's lifespan in app/main.py.
"""
from __future__ import annotations

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.agents import followup, outreach, prospect, reply, research, social
from app.config import get_settings
from app.logging_setup import get_logger

log = get_logger("scheduler")

_scheduler: AsyncIOScheduler | None = None


def _wrap(fn, name: str):
    """Run an agent fn in a thread (the agent code uses sync supabase + httpx)."""
    import asyncio
    async def _run():
        log.info("scheduled_run_start", agent=name)
        try:
            result = await asyncio.to_thread(fn)
            log.info("scheduled_run_done", agent=name, result=result)
        except Exception as e:  # noqa: BLE001
            log.error("scheduled_run_failed", agent=name, error=str(e))
    return _run


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    s = get_settings()
    sched = AsyncIOScheduler(timezone=s.timezone)

    # Daily schedule from the brief.
    sched.add_job(_wrap(lambda: prospect.run(target=80), "prospect"),
                  CronTrigger(hour=7, minute=0), id="prospect_daily")
    sched.add_job(_wrap(lambda: research.run(limit=100), "research"),
                  CronTrigger(hour=7, minute=30), id="research_daily")
    sched.add_job(_wrap(lambda: outreach.run(limit=40), "outreach"),
                  CronTrigger(hour=8, minute=0), id="outreach_daily")
    sched.add_job(_wrap(lambda: followup.run(limit=15), "followup"),
                  CronTrigger(hour=10, minute=0), id="followup_morning")
    sched.add_job(_wrap(reply.run, "reply"),
                  CronTrigger(hour=12, minute=0), id="reply_noon")
    sched.add_job(_wrap(reply.run, "reply"),
                  CronTrigger(hour=16, minute=0), id="reply_afternoon")
    sched.add_job(_wrap(social.run, "social"),
                  CronTrigger(hour=18, minute=0), id="social_evening")

    sched.start()
    _scheduler = sched
    log.info("scheduler_started", tz=s.timezone, jobs=[j.id for j in sched.get_jobs()])


def shutdown() -> None:
    global _scheduler
    if _scheduler:
        _scheduler.shutdown(wait=False)
        _scheduler = None
