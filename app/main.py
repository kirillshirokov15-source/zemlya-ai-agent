from fastapi import FastAPI

from app.api.routes.health import router as health_router
from app.api.routes.tasks import router as tasks_router

app = FastAPI(
    title="Zemlya AI Agent",
    version="0.1.0",
)

app.include_router(health_router)
app.include_router(tasks_router)


@app.get("/")
def root():
    return {
        "service": "zemlya-ai-agent",
        "status": "ok",
    }
