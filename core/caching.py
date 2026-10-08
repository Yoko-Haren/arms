"""Caching layers for ARMS.

1. Browser      — unchanged pages answer with 304 (ConditionalGetMiddleware + ETag).
2. Process      — `local` cache (memory of this server process), a few seconds.
3. Shared       — `default` cache (files on this machine, or Redis when REDIS_URL is
                  set so several app servers share it). Sessions live here too.
4. Database     — persistent connections; the signed-in user and profile load in one query.

Rendered pages are cached per user. Any successful write request (POST/PUT/PATCH/DELETE)
bumps a data version that is part of every page key, so nobody is served a page that
is older than the last change. A short timeout covers changes made outside the app.
"""
import hashlib
from functools import wraps
from urllib.parse import urlencode

from django.conf import settings
from django.contrib.messages import get_messages
from django.core.cache import caches
from django.http import HttpResponse
from django.shortcuts import redirect

VERSION_KEY = 'data-version'
PAGE_TTL = 300          # seconds a rendered page may be reused when nothing changed
LOCAL_TTL = 20          # seconds a page stays in this process's memory


def _shared():
    return caches['default']


def _local():
    return caches['local']


def data_version():
    version = _shared().get(VERSION_KEY)
    if version is None:
        version = 1
        _shared().set(VERSION_KEY, version, None)
    return version


def bump_data_version():
    """Call after data changes: every cached page becomes stale at once."""
    try:
        _shared().incr(VERSION_KEY)
    except ValueError:
        _shared().set(VERSION_KEY, 2, None)


def tiered_get(key):
    """Process memory first, then the shared cache (and remember it locally)."""
    value = _local().get(key)
    if value is None:
        value = _shared().get(key)
        if value is not None:
            _local().set(key, value, LOCAL_TTL)
    return value


def tiered_set(key, value, ttl=PAGE_TTL):
    _local().set(key, value, min(ttl, LOCAL_TTL))
    _shared().set(key, value, ttl)


class DataVersionMiddleware:
    """A successful write by anyone invalidates the cached pages."""

    UNSAFE = {'POST', 'PUT', 'PATCH', 'DELETE'}

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if request.method in self.UNSAFE and response.status_code < 400:
            bump_data_version()
        return response


def cache_page_for_user(ttl=PAGE_TTL):
    """Reuse a view's rendered page for the same signed-in user and URL until data changes.

    Skipped when there are one-time messages to show, or when the browser has no CSRF
    cookie yet (the cached form tokens would not match a newly issued one).
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            user = getattr(request, 'user', None)
            if (
                not getattr(settings, 'PAGE_CACHE_ENABLED', True)
                or request.method != 'GET' or user is None or not user.is_authenticated
                or 'csrftoken' not in request.COOKIES or len(get_messages(request))
            ):
                return view(request, *args, **kwargs)

            path = hashlib.sha1(request.get_full_path().encode()).hexdigest()
            key = f'page:{data_version()}:{user.pk}:{request.session.session_key}:{path}'
            cached = tiered_get(key)
            if cached is not None:
                response = HttpResponse(cached['content'], content_type=cached['content_type'])
                response['X-ARMS-Cache'] = 'HIT'
                return response

            response = view(request, *args, **kwargs)
            storage = get_messages(request)
            if (
                response.status_code == 200 and not response.streaming
                and not storage.used and not storage.added_new
                and response.get('Content-Type', '').startswith('text/html')
            ):
                tiered_set(key, {'content': response.content, 'content_type': response['Content-Type']}, ttl)
                response['X-ARMS-Cache'] = 'MISS'
            return response
        return wrapper
    return decorator


def remember_filters(name, params):
    """Keep a page's filter choices for the session.

    Opening the page without any query string returns to the filters used last
    time, so moving to another page and back does not reset them. `?reset=1`
    clears them.
    """
    def decorator(view):
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            if request.method == 'GET' and hasattr(request, 'session'):
                key = f'filters:{name}'
                if 'reset' in request.GET:
                    request.session.pop(key, None)
                    return redirect(request.path)
                chosen = {p: request.GET[p] for p in params if p in request.GET}
                if chosen:
                    if request.session.get(key) != chosen:
                        request.session[key] = chosen
                elif not request.GET and request.session.get(key):
                    return redirect(f'{request.path}?{urlencode(request.session[key])}')
            return view(request, *args, **kwargs)
        return wrapper
    return decorator
