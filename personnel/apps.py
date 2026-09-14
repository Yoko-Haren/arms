# personnel/apps.py
from django.apps import AppConfig


class PersonnelConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'personnel'
    verbose_name = 'Teacher & Personnel Management'