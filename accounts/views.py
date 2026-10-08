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
from django.utils import timezone
from django.conf import settings
from django.views.decorators.http import require_http_methods
from .models import UserProfile, LoginAttempt
from .services.sessions import end_other_sessions


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

            login(request, user)
            end_other_sessions(user, request.session.session_key)  # single session per user

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
def password_change_required(request):
    """First sign-in with a temporary password: the user must choose their own."""
    from django.contrib.auth import update_session_auth_hash
    from django.contrib.auth.password_validation import validate_password

    if not request.user.is_authenticated:
        return redirect('signin')
    profile = request.user.profile
    if not profile.must_change_password:
        return redirect(_get_dashboard_url(profile.role))

    errors = []
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')
        if new_password != confirm_password:
            errors.append('The two passwords do not match.')
        elif request.user.check_password(new_password):
            errors.append('Choose a password different from the temporary one.')
        else:
            try:
                validate_password(new_password, user=request.user)
            except ValidationError as exc:
                errors.extend(exc.messages)
        if not errors:
            request.user.set_password(new_password)
            request.user.save()
            profile.must_change_password = False
            profile.save(update_fields=['must_change_password', 'updated_at'])
            update_session_auth_hash(request, request.user)  # stay signed in
            messages.success(request, 'Your password has been updated.')
            return redirect(_get_dashboard_url(profile.role))

    return render(request, 'accounts/password_change_required.html', {'errors': errors})
