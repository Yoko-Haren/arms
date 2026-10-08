"""One active session per user, without scanning the whole session table on every sign-in."""
from importlib import import_module

from django.conf import settings
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.utils import timezone

SessionStore = import_module(settings.SESSION_ENGINE).SessionStore


def _key(user):
    return f'user-session:{user.pk}'


def end_other_sessions(user, keep_key):
    """Sign the user out everywhere except the session `keep_key` (call right after login)."""
    previous = cache.get(_key(user))
    if previous:
        if previous != keep_key:
            SessionStore(session_key=previous).delete()      # clears the cache copy and the row
    else:
        # First sign-in since tracking started (or the cache was cleared): look once.
        Session.objects.filter(expire_date__lt=timezone.now()).delete()
        for session in Session.objects.filter(expire_date__gte=timezone.now()):
            if session.session_key == keep_key:
                continue
            try:
                owner = session.get_decoded().get('_auth_user_id')
            except Exception:
                owner = None
            if owner == str(user.pk):
                SessionStore(session_key=session.session_key).delete()
    cache.set(_key(user), keep_key, settings.SESSION_COOKIE_AGE)
