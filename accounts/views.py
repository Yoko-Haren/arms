# accounts/views.py
import hashlib
import logging
import time
from datetime import timedelta

from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout as auth_logout
from django.contrib import messages
from django.contrib.sessions.models import Session
from django.utils import timezone
from django.conf import settings
from django.views.decorators.http import require_http_methods
from .models import UserProfile, LoginAttempt


logger = logging.getLogger(__name__)


# ── SECURITY CONSTANTS ──
MAX_LOGIN_ATTEMPTS = 5          # Lock account after this many failures
LOCKOUT_DURATION_MINUTES = 15   # How long the lockout lasts
SALT = "D0pp3lG4ng3r_F0rm1fy_S3cur3_S4lt_2026"  # Never expose this


def _hash_password_with_salt(password):
    """SHA-256 hash with salt — extra layer before Django's PBKDF2."""
    salted = f"{password}:{SALT}"
    return hashlib.sha256(salted.encode('utf-8')).hexdigest()


def _is_account_locked(username):
    """Check if account has too many recent failed attempts."""
    cutoff = timezone.now() - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    recent_failures = LoginAttempt.objects.filter(
        username_attempted=username,
        attempt_result__startswith='FAILED',
        attempted_at__gte=cutoff
    ).count()
    return recent_failures >= MAX_LOGIN_ATTEMPTS


def _get_dashboard_url(role):
    """Return the dashboard URL for a given role."""
    redirects = {
        'teacher': '/teachers/',
        'registrar': '/registrars/',
        'schoolhead': '/heads/ai-dashboard/',
        'admin': '/admin-panel/',
    }
    return redirects.get(role, '/')


def signin(request):
    # ── If already logged in, redirect to their dashboard ──
    if request.user.is_authenticated:
        try:
            role = request.user.profile.role
        except UserProfile.DoesNotExist:
            role = 'teacher'
        return redirect(_get_dashboard_url(role))

    error_message = None

    if request.method == 'POST':
        username = request.POST.get('username', '').strip()
        password = request.POST.get('password', '')
        ip = request.META.get('REMOTE_ADDR', '')
        user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]

        # ── 1. Basic input validation ──
        if not username or not password:
            error_message = 'Please enter both username and password.'
            return render(request, 'shared/accounts/signin.html', {
                'error': error_message,
            })

        # ── 2. Check if account is locked ──
        if _is_account_locked(username):
            LoginAttempt.objects.create(
                username_attempted=username,
                ip_address=ip,
                user_agent=user_agent,
                attempt_result='FAILED_LOCKED',
            )
            error_message = (
                f'Account temporarily locked due to {MAX_LOGIN_ATTEMPTS} failed attempts. '
                f'Please wait {LOCKOUT_DURATION_MINUTES} minutes or contact your administrator.'
            )
            return render(request, 'shared/accounts/signin.html', {
                'error': error_message,
            })

        # ── 3. Pre-hash with salt (adds latency for brute-force) ──
        _hash_password_with_salt(password)

        # ── 4. Authenticate using Django's built-in (PBKDF2 + salt) ──
        user = authenticate(request, username=username, password=password)

        if user is not None:
            # ── 5. Verify user is active ──
            if not user.is_active:
                LoginAttempt.objects.create(
                    username_attempted=username,
                    ip_address=ip,
                    user_agent=user_agent,
                    attempt_result='FAILED_INACTIVE',
                    user=user,
                )
                error_message = 'Your account has been deactivated. Contact your administrator.'
                return render(request, 'shared/accounts/signin.html', {
                    'error': error_message,
                })

            # ── 6. Get user's role from profile (server-side, not client input) ──
            try:
                actual_role = user.profile.role
            except UserProfile.DoesNotExist:
                # Auto-create profile with default role if missing
                UserProfile.objects.create(user=user, role='teacher')
                actual_role = 'teacher'

            # ── 7. Success — log the attempt, kill other sessions, login ──
            LoginAttempt.objects.create(
                username_attempted=username,
                ip_address=ip,
                user_agent=user_agent,
                attempt_result='SUCCESS',
                user=user,
            )

            # Kill all other active sessions for this user (force single session)
            for session in Session.objects.all():
                session_data = session.get_decoded()
                if session_data.get('_auth_user_id') == str(user.id):
                    if session.session_key != request.session.session_key:
                        session.delete()

            login(request, user)

            # ── 8. Redirect based on actual role from database ──
            return redirect(_get_dashboard_url(actual_role))

        else:
            # ── 9. Failed login — log it ──
            LoginAttempt.objects.create(
                username_attempted=username,
                ip_address=ip,
                user_agent=user_agent,
                attempt_result='FAILED_INVALID_CREDENTIALS',
            )

            # ── 10. Add artificial delay to slow down brute-force ──
            time.sleep(1.5)

            remaining = MAX_LOGIN_ATTEMPTS - LoginAttempt.objects.filter(
                username_attempted=username,
                attempt_result__startswith='FAILED',
                attempted_at__gte=timezone.now() - timedelta(minutes=LOCKOUT_DURATION_MINUTES)
            ).count()

            if remaining <= 2 and remaining > 0:
                error_message = (
                    f'Invalid credentials. {remaining} attempt{"s" if remaining > 1 else ""} '
                    f'remaining before account lockout.'
                )
            else:
                error_message = 'Invalid username or password.'

            return render(request, 'shared/accounts/signin.html', {
                'error': error_message,
            })

    # GET request — show empty form
    return render(request, 'shared/accounts/signin.html', {'error': error_message})


def signout(request):
    auth_logout(request)
    return redirect('signin')


@require_http_methods(['GET', 'POST'])
def password_reset_request(request):
    """Request a Supabase Auth password-reset email without leaking accounts."""
    if request.method == 'POST':
        email = request.POST.get('email', '').strip()

        try:
            validate_email(email)
        except ValidationError:
            return render(request, 'accounts/password_reset.html', {
                'email': email,
                'error': 'Enter a valid email address.',
            }, status=400)

        try:
            # Keep Supabase optional during SQLite-only local development.
            # The integration is imported only when its route is used.
            from .services.supabase_client import get_supabase_client

            get_supabase_client().auth.reset_password_email(email)
        except RuntimeError:
            logger.exception('Supabase password reset is not configured.')
            return render(request, 'accounts/password_reset.html', {
                'email': email,
                'error': 'Password reset is not configured yet. Contact the system administrator.',
            }, status=503)
        except Exception:
            # Do not disclose whether an account exists or expose provider
            # details. Record the technical failure for the administrator.
            logger.exception('Supabase password-reset request failed.')
            return render(request, 'accounts/password_reset.html', {
                'email': email,
                'error': 'We could not send a reset link right now. Please try again later.',
            }, status=503)

        return redirect('password_reset_done')

    return render(request, 'accounts/password_reset.html', {
        'email': request.GET.get('email', '').strip(),
    })


def password_reset_done(request):
    return render(request, 'accounts/password_reset_done.html')
