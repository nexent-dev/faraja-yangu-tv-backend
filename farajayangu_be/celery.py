from __future__ import absolute_import, unicode_literals
import os
from celery import Celery
from celery.schedules import crontab

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'farajayangu_be.settings.base')
app = Celery('farajayangu_be')
app.config_from_object('django.conf:settings', namespace='CELERY')
app.autodiscover_tasks()

app.conf.beat_schedule = {
    'cleanup-stale-chunks-midnight': {
        'task': 'apps.streaming.tasks.tasks.cleanup_stale_chunks',
        'schedule': crontab(hour=0, minute=0),  # Run at midnight
    },
}
