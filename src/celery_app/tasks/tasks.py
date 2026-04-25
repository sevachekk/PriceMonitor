# celery_app/tasks/tasks.py
import os

import httpx

from celery_app.worker import celery

@celery.task(name="app.tasks.periodic_job")
def periodic_job():
    base_url = os.getenv("APP_BASE_URL", "http://127.0.0.1:8000").rstrip("/")
    url = f"{base_url}/admin-api/jobs/run-due"
    headers = {
        "X-Internal-Task-Secret": os.getenv("INTERNAL_TASK_SECRET", "internal-task-secret"),
    }
    try:
        with httpx.Client(timeout=600.0) as client:
            response = client.post(url, headers=headers)
            try:
                return response.json()
            except Exception:
                return {"status": response.status_code, "text": response.text}
    except Exception as exc:
        return {"error": str(exc)}
