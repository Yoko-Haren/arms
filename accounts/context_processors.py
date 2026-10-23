from django.conf import settings


def auth_options(request):
    """Sign-in options the templates need to know about."""
    return {'google_signin_enabled': settings.GOOGLE_SIGNIN_ENABLED, 'remember_me_days': settings.REMEMBER_ME_DAYS}
