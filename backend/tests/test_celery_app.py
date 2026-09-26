"""Regression test for Celery task registration.

``celery_app.py``'s own comment explains why this matters: a worker
module missing from ``include=[...]`` means the task silently never
runs — the API's ``.delay()`` call succeeds and returns 202/200, but
the worker rejects the message as an unregistered task. This has
happened in production before (``run_detection_pipeline``). This test
would have caught ``generate_compliance_report`` shipping unregistered.
"""
from __future__ import annotations

from app.workers.celery_app import celery_app


def test_compliance_report_task_module_is_included() -> None:
    assert "app.workers.compliance_report_task" in celery_app.conf.include


def test_compliance_report_task_actually_registers() -> None:
    celery_app.loader.import_default_modules()
    assert "generate_compliance_report" in celery_app.tasks
