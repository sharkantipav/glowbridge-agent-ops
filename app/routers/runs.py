"""Manual run endpoints — POST /runs/{agent} to trigger any agent on demand.

Useful for testing without waiting for cron.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.agents import outreach, prospect, reply, research, social
from app.routers.auth_dep import require_admin

router = APIRouter(prefix="/runs", tags=["runs"], dependencies=[Depends(require_admin)])


@router.post("/prospect")
def run_prospect(target: int = 25):
    return prospect.run(target=target)


@router.post("/research")
def run_research(limit: int = 50):
    return research.run(limit=limit)


@router.post("/outreach")
def run_outreach(limit: int = 25):
    return outreach.run(limit=limit)


@router.post("/reply")
def run_reply():
    return reply.run()


@router.post("/social")
def run_social():
    return social.run()


@router.post("/{agent}")
def run_unknown(agent: str):
    raise HTTPException(status_code=404, detail=f"unknown agent: {agent}")
