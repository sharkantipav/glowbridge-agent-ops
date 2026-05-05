from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.agents.prospect_agent import ProspectAgent
from app.agents.social_agent import SocialAgent

scheduler = AsyncIOScheduler(timezone="UTC")


def schedule_jobs() -> None:
    # UTC equivalents of requested schedule should be adjusted for local timezone in production.
    scheduler.add_job(lambda: ProspectAgent().run(limit=25), "cron", hour=7, minute=0, id="prospects")
    scheduler.add_job(lambda: SocialAgent().generate_daily(), "cron", hour=18, minute=0, id="social")
    scheduler.start()
