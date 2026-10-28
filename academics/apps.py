# academics/apps.py
from django.apps import AppConfig


class AcademicsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'academics'
    verbose_name = 'Academic Structure'

    def ready(self):
        from django.db.models.signals import pre_save

        from .models import Subject
        pre_save.connect(_discipline_of_new_subject, sender=Subject, dispatch_uid='academics-subject-discipline')


def _discipline_of_new_subject(sender, instance, raw=False, **kwargs):
    """A subject saved without a discipline (a class list import, the admin) gets one from DepEd's curriculum
    (academics/subject_catalog.py), so the School Head's pages count it. Never stops the save."""
    if raw or instance.subject_family_id or not instance.school_id:
        return
    try:
        from .subject_catalog import family_for
        family, _ = family_for(instance.school, instance.subject_name, instance.subject_code, create=True)
        if family is not None:
            instance.subject_family = family
    except Exception:
        pass
