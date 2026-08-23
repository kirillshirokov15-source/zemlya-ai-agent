from fastapi import APIRouter
from app.worker import celery_app

router = APIRouter(prefix="/qualification", tags=["qualification"])

@router.post("/discovery-test")
def start_qualification_discovery_test():
    task = celery_app.send_task("qualification.discovery_test")
    return {"task_id": task.id, "status": "queued"}
