# transfers/apps.py
from django.apps import AppConfig


class TransfersConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'transfers'
    verbose_name = 'Transfer Management'