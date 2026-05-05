from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from app.api.routes import router
from app.core.logging import setup_logging
from app.jobs.scheduler import schedule_jobs

setup_logging()
app = FastAPI(title="GlowBridge Agent Ops")
app.include_router(router)


@app.on_event("startup")
async def startup_event():
    schedule_jobs()


@app.get("/admin", response_class=HTMLResponse)
def admin_dashboard():
    return """
    <html><body><h1>GlowBridge Admin</h1>
    <p>Use API endpoints for approval queue, logs, and job control.</p></body></html>
    """
