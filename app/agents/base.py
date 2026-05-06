"""Shared agent run wrapper.

Every agent's `run()` should be wrapped in `with run_context(agent_name) as run:`
so we get a row in `agent_runs` for every invocation, with timing and errors.
"""
from __future__ import annotations

import time
import traceback
from contextlib import contextmanager
from typing import Any, Iterator

from app import db
from app.logging_setup import get_logger

log = get_logger("agent")


class AgentRun:
    def __init__(self, run_id: str, agent: str):
        self.id = run_id
        self.agent = agent
        self.output: dict[str, Any] = {}

    def info(self, message: str, **data: Any) -> None:
        log.info(message, agent=self.agent, run=self.id, **data)
        db.log(self.agent, "info", message, data=data, run_id=self.id)

    def warn(self, message: str, **data: Any) -> None:
        log.warning(message, agent=self.agent, run=self.id, **data)
        db.log(self.agent, "warn", message, data=data, run_id=self.id)

    def error(self, message: str, **data: Any) -> None:
        log.error(message, agent=self.agent, run=self.id, **data)
        db.log(self.agent, "error", message, data=data, run_id=self.id)


@contextmanager
def run_context(agent: str, input_payload: dict[str, Any] | None = None) -> Iterator[AgentRun]:
    started = time.time()
    row = db.insert(
        "agent_runs",
        {"agent": agent, "status": "started", "input": input_payload or {}},
    )
    run = AgentRun(run_id=row["id"], agent=agent)
    try:
        yield run
        db.update(
            "agent_runs",
            run.id,
            {
                "status": "completed",
                "output": run.output,
                "duration_ms": int((time.time() - started) * 1000),
                "completed_at": "now()",
            },
        )
    except Exception as e:  # noqa: BLE001
        tb = traceback.format_exc()
        run.error("agent_failed", error=str(e), traceback=tb[-2000:])
        db.update(
            "agent_runs",
            run.id,
            {
                "status": "failed",
                "error": f"{e}\n{tb[-1500:]}",
                "duration_ms": int((time.time() - started) * 1000),
                "completed_at": "now()",
            },
        )
        raise
