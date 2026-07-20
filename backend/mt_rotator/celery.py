import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mt_rotator.settings")

app = Celery("mt_rotator")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()
