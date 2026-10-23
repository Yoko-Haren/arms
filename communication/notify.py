"""Bell notifications between teachers and registrars about a class's grades.

Sending never raises: a notification that fails must not undo the grade action that caused it.
"""
from datetime import timedelta

from django.contrib.auth.models import User
from django.utils import timezone

from .models import Notification


def notify(users, notification_type, title, message, action_url='', priority='Normal', assignment_id=None):
    """One notification per user. Returns how many were sent."""
    try:
        rows = [Notification(recipient=u, notification_type=notification_type, title=title[:255], message=message,
                             action_url=action_url[:255], priority=priority,
                             related_entity_type='ClassAssignment' if assignment_id else '', related_entity_id=assignment_id)
                for u in users if u is not None]
        Notification.objects.bulk_create(rows)
        return len(rows)
    except Exception:
        return 0


def school_registrars(school):
    return User.objects.filter(profile__school=school, profile__role='registrar', is_active=True, profile__is_active=True)


def sent_recently(user, notification_type, assignment_id, title_start, hours=12):
    """Whether this kind of notice (about this class, or about any class when assignment_id is None) already
    went to the user in the last hours, so reminders are not repeated."""
    recent = Notification.objects.filter(recipient=user, notification_type=notification_type, title__startswith=title_start,
                                         created_at__gte=timezone.now() - timedelta(hours=hours))
    if assignment_id is not None:
        recent = recent.filter(related_entity_type='ClassAssignment', related_entity_id=assignment_id)
    return recent.exists()
