from fastapi import APIRouter
from celery.result import AsyncResult

from app.worker import celery_app

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("/healthcheck")
def enqueue_healthcheck():
    task = celery_app.send_task("healthcheck")
    return {
        "task_id": task.id,
        "status": "queued",
    }


@router.get("/{task_id}")
def get_task_status(task_id: str):
    result = AsyncResult(task_id, app=celery_app)

    response = {
        "task_id": task_id,
        "status": result.status,
    }

    if result.successful():
        response["result"] = result.result
    elif result.failed():
        response["error"] = str(result.result)

    return response
