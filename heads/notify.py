"""Notifications for School Heads when something changes the data they monitor."""
from django.contrib.auth.models import User

from communication.models import Notification


def notify_school_heads(school, notification_type, title, message, action_url='', priority='Normal'):
    """Send one notification to every active School Head of the school. Never raises."""
    if school is None:
        return 0
    try:
        heads = User.objects.filter(profile__school=school, profile__role='schoolhead', is_active=True,
                                    profile__is_active=True)
        Notification.objects.bulk_create([
            Notification(recipient=head, notification_type=notification_type, title=title[:255], message=message,
                         action_url=action_url[:255], priority=priority)
            for head in heads
        ])
        return len(heads)
    except Exception:
        return 0
