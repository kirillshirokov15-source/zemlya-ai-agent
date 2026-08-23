import os
from celery import Celery

redis_url = os.getenv("REDIS_URL", "redis://localhost:6379/0")

celery_app = Celery(
    "zemlya_ai_agent",
    broker=redis_url,
    backend=redis_url,
)

celery_app.conf.update(
    task_track_started=True,
    result_expires=86400,
)


@celery_app.task(name="healthcheck")
def healthcheck():
    return {"status": "ok"}


# Import task modules so Celery registers them.
import app.tasks.discovery  # noqa: E402,F401
