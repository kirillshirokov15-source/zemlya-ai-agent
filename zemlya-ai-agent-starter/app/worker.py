import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "zemlya_ai_agent",
    broker=redis_url,
    backend=redis_url,
)

@celery_app.task(name="healthcheck")
def healthcheck():
    return {"status": "ok"}
