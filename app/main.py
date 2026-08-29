from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.tasks import router as tasks_router
from app.api.routes.discovery import router as discovery_router
from app.api.routes.qualification import router as qualification_router
from app.api.routes.projects import router as projects_router

app = FastAPI(
    title="Zemlya AI Agent",
    version="0.2.0",
)

app.include_router(health_router)
app.include_router(tasks_router)
app.include_router(discovery_router)
app.include_router(qualification_router)


@app.get("/")
def root():
    return {
        "service": "zemlya-ai-agent",
        "status": "ok",
        "version": "0.2.0",
    }
