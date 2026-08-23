from fastapi import APIRouter

from app.worker import celery_app

router = APIRouter(prefix="/discovery", tags=["discovery"])


@router.post("/tavily-test")
def start_tavily_discovery_test():
    task = celery_app.send_task("discovery.tavily_test")

    return {
        "task_id": task.id,
        "status": "queued",
    }
