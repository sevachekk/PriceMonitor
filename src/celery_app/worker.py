import os
from datetime import timedelta

from celery import Celery

broker_url = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
result_backend = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")
beat_interval_minutes = int(os.getenv("CELERY_BEAT_INTERVAL_MINUTES", "5"))

celery = Celery(
    "app",
    broker=broker_url,
    backend=result_backend,
    include=["celery_app.tasks.tasks"],
)

celery.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="Europe/Moscow",
    enable_utc=True,
)

# Пример расписания (beat)
celery.conf.beat_schedule = {
    "monitoring-jobs-dispatcher": {
        "task": "app.tasks.periodic_job",   # <-- module.function
        "schedule": timedelta(minutes=beat_interval_minutes),
        "args": (),
    },
}
