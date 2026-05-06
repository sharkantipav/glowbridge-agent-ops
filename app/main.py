"""FastAPI entry point.

Mounts:
  GET  /                — health
  GET  /admin           — dashboard (bearer auth)
  POST /webhooks/stripe — Stripe webhook (signature-verified)
  POST /runs/<agent>    — manual triggers (bearer auth)
  /admin/approvals/*    — approval queue (bearer auth)
"""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from app import scheduler
from app.config import get_settings
from app.integrations import stripe_wh
from app.logging_setup import configure_logging, get_logger
from app.routers import admin, approvals, runs, webhooks

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging()
    s = get_settings()
    stripe_wh.init_stripe()
    if s.app_env != "test":
        scheduler.start()
    log.info("startup_complete", env=s.app_env, tz=s.timezone)
    try:
        yield
    finally:
        scheduler.shutdown()
        log.info("shutdown_complete")


app = FastAPI(title="GlowBridge Agent Ops", version="0.1.0", lifespan=lifespan)

app.include_router(admin.router)
app.include_router(approvals.router)
app.include_router(runs.router)
app.include_router(webhooks.router)


@app.get("/")
def root():
    return {"ok": True, "service": "glowbridge-agent-ops", "version": "0.1.0"}
