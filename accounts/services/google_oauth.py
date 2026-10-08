"""Google Sign-In: OAuth 2.0 authorisation-code flow with OpenID Connect."""

import base64
import json
import logging
import secrets
import time
from urllib.parse import urlencode

import requests
from django.conf import settings
from django.urls import reverse

logger = logging.getLogger(__name__)

AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth'
TOKEN_URL = 'https://oauth2.googleapis.com/token'
ISSUERS = ('https://accounts.google.com', 'accounts.google.com')
SESSION_KEY = 'google_oauth'


class GoogleError(Exception):
    """Shown to the user as-is."""


def redirect_uri(request):
    return settings.GOOGLE_REDIRECT_URI or request.build_absolute_uri(reverse('google_callback'))


def authorization_url(request, intent, login_hint=''):
    """Start the flow. `intent` is remembered for the callback ('login' or 'bind')."""
    state, nonce = secrets.token_urlsafe(24), secrets.token_urlsafe(24)
    request.session[SESSION_KEY] = {'state': state, 'nonce': nonce, 'intent': intent}
    params = {
        'client_id': settings.GOOGLE_CLIENT_ID,
        'redirect_uri': redirect_uri(request),
        'response_type': 'code',
        'scope': 'openid email profile',
        'state': state,
        'nonce': nonce,
        'prompt': 'select_account',
    }
    if login_hint:
        params['login_hint'] = login_hint
    return f'{AUTH_URL}?{urlencode(params)}'


def _decode_id_token(id_token):
    # The token comes straight from Google's token endpoint over TLS in exchange
    # for our client secret, so its claims are trusted without a signature check
    # (OpenID Connect Core 3.1.3.7). The claims are still validated below.
    try:
        payload = id_token.split('.')[1]
        payload += '=' * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except (IndexError, ValueError):
        raise GoogleError('Google returned an unreadable response. Please try again.')


def complete(request):
    """Finish the flow on the callback. Returns (intent, identity dict)."""
    saved = request.session.pop(SESSION_KEY, None)
    if request.GET.get('error'):
        raise GoogleError('Google sign-in was cancelled.')
    if not saved or not secrets.compare_digest(saved['state'], request.GET.get('state', '')):
        raise GoogleError('That sign-in attempt expired. Please try again.')
    code = request.GET.get('code')
    if not code:
        raise GoogleError('Google did not return a sign-in code. Please try again.')

    try:
        response = requests.post(TOKEN_URL, data={
            'code': code,
            'client_id': settings.GOOGLE_CLIENT_ID,
            'client_secret': settings.GOOGLE_CLIENT_SECRET,
            'redirect_uri': redirect_uri(request),
            'grant_type': 'authorization_code',
        }, timeout=15)
        tokens = response.json()
    except (requests.RequestException, ValueError):
        logger.exception('Google token exchange failed')
        raise GoogleError('Could not reach Google. Check your connection and try again.')
    if response.status_code != 200 or 'id_token' not in tokens:
        logger.error('Google token exchange rejected: %s', tokens.get('error_description') or tokens.get('error'))
        raise GoogleError('Google rejected the sign-in. Please try again.')

    claims = _decode_id_token(tokens['id_token'])
    if (
        claims.get('iss') not in ISSUERS
        or claims.get('aud') != settings.GOOGLE_CLIENT_ID
        or float(claims.get('exp', 0)) < time.time()
        or not secrets.compare_digest(str(claims.get('nonce', '')), saved['nonce'])
        or not claims.get('sub')
    ):
        raise GoogleError('Google sign-in could not be verified. Please try again.')
    if not claims.get('email') or claims.get('email_verified') not in (True, 'true'):
        raise GoogleError('That Google account has no verified email address.')

    return saved['intent'], {
        'sub': str(claims['sub']),
        'email': claims['email'].strip().lower(),
        'name': claims.get('name', ''),
    }
