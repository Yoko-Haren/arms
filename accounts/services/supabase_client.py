"""Server-side Supabase client helpers."""

from functools import lru_cache

from django.conf import settings
from supabase import Client, create_client


@lru_cache(maxsize=1)
def get_supabase_client() -> Client:
    """Return the client used for ordinary Supabase Auth requests.

    Password-reset requests use the anon key. The service-role key is reserved
    for explicitly privileged server jobs and must never reach a template or
    browser.
    """
    if not settings.SUPABASE_URL or not settings.SUPABASE_ANON_KEY:
        raise RuntimeError(
            'SUPABASE_URL and SUPABASE_ANON_KEY must be configured.'
        )

    return create_client(settings.SUPABASE_URL, settings.SUPABASE_ANON_KEY)
