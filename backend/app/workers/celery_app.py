"""Celery application for async background jobs."""

from __future__ import annotations

from celery import Celery

from app.config import settings

celery_app = Celery(
    "aqp",
    broker=settings.CELERY_BROKER_URL,
    backend=settings.CELERY_RESULT_BACKEND,
    include=[
        "app.workers.tasks.document_processing",
        "app.workers.tasks.llm_tasks",
        "app.workers.tasks.notifications",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone=settings.TIMEZONE,
    enable_utc=True,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_default_queue="default",
    task_routes={
        "app.workers.tasks.document_processing.*": {"queue": "documents"},
        "app.workers.tasks.llm_tasks.*": {"queue": "llm"},
        "app.workers.tasks.notifications.*": {"queue": "notifications"},
    },
    worker_max_tasks_per_child=100,  # mitigate memory leaks
    worker_prefetch_multiplier=1,    # important for long LLM jobs
    broker_connection_retry_on_startup=True,
)
