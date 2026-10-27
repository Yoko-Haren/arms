"""Notifications for School Heads when something changes the data they monitor."""
from django.contrib.auth.models import User
from django.urls import reverse
from django.utils.http import urlencode

from communication.models import Notification


def subject_view_url(subject_id, quarter):
    """The Academic Dashboard for one subject in one grading period: where a School Head reviews a class's grades."""
    return reverse('heads-ai-dashboard') + '?' + urlencode({'view_mode': 'subject', 'subject': subject_id,
                                                           'quarter': quarter.quarter_label, 'school_year': quarter.school_year_id})


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
