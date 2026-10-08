"""Google sign-in and binding, emailed-code password reset, and the account settings page."""

import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login, update_session_auth_hash
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.core.validators import validate_email
from django.db.models import Q
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.http import require_http_methods

from .models import LoginAttempt, UserProfile
from .services import google_oauth
from .services.sessions import end_other_sessions
from .services.email_codes import CodeError, issue_code, latest_code, mask_email, verify_code
from .views import _get_dashboard_url

logger = logging.getLogger(__name__)

BIND_USER_KEY = 'bind_user_id'      # user finishing a Google link (may not be signed in yet)
RESET_USER_KEY = 'reset_user_id'    # user resetting a password (None when no account matched)
RESET_SENT_KEY = 'reset_sent_to'
RESET_VERIFIED_KEY = 'reset_verified'  # set once the emailed code was correct
RESET_VERIFIED_MINUTES = 10


def _client(request):
    return request.META.get('REMOTE_ADDR', ''), request.META.get('HTTP_USER_AGENT', '')[:255]


def _finish_login(request, user):
    """Sign the user in the same way the password form does: log it, single session."""
    ip, user_agent = _client(request)
    LoginAttempt.objects.create(
        username_attempted=user.username, ip_address=ip or '0.0.0.0',
        user_agent=user_agent, attempt_result='SUCCESS', user=user,
    )
    login(request, user, backend=settings.AUTHENTICATION_BACKENDS[0])
    end_other_sessions(user, request.session.session_key)


def _account_active(user):
    profile = getattr(user, 'profile', None)
    return user.is_active and profile is not None and profile.is_active


# =============================================================================
# GOOGLE SIGN-IN
# =============================================================================

def google_login(request):
    """Send the browser to Google. Signed-in users are linking; everyone else is signing in."""
    if not settings.GOOGLE_SIGNIN_ENABLED:
        messages.error(request, 'Google sign-in is not set up yet. Please use your username and password.')
        return redirect('signin')
    intent = 'bind' if request.user.is_authenticated else 'login'
    return redirect(google_oauth.authorization_url(request, intent))


def google_callback(request):
    if not settings.GOOGLE_SIGNIN_ENABLED:
        return redirect('signin')
    try:
        intent, identity = google_oauth.complete(request)
    except google_oauth.GoogleError as exc:
        messages.error(request, str(exc))
        return redirect('google_bind' if request.user.is_authenticated else 'signin')

    owner = UserProfile.objects.filter(google_sub=identity['sub']).select_related('user').first()

    # ----- a signed-in user is linking (or changing) their Google account -----
    if request.user.is_authenticated:
        if owner and owner.user_id == request.user.id:
            messages.info(request, f'{identity["email"]} is already linked to your account.')
            return redirect(_get_dashboard_url(request.user.profile.role))
        if owner:
            messages.error(request, f'{identity["email"]} is already linked to another ARMS account.')
            return redirect('google_bind')
        return _start_binding(request, request.user, identity)

    # ----- signing in -----
    if owner:
        if not _account_active(owner.user):
            messages.error(request, 'Your account has been deactivated. Contact your administrator.')
            return redirect('signin')
        _finish_login(request, owner.user)
        return redirect(_get_dashboard_url(owner.role))

    # Not linked yet: an account registered under this exact Google address may link itself,
    # after confirming the code sent to that address.
    matches = list(
        User.objects.filter(is_active=True, profile__is_active=True, profile__google_sub__isnull=True)
        .filter(Q(email__iexact=identity['email']) | Q(username__iexact=identity['email']))
        .distinct()[:2]
    )
    if len(matches) == 1:
        return _start_binding(request, matches[0], identity)

    messages.error(
        request,
        f'{identity["email"]} is not linked to an ARMS account yet. Sign in with your username and '
        'password once, and you will be asked to link your Google account.'
    )
    return redirect('signin')


def _start_binding(request, user, identity):
    try:
        issue_code(user, 'bind_google', identity['email'], payload=identity)
    except CodeError as exc:
        messages.error(request, str(exc))
        return redirect('google_bind' if request.user.is_authenticated else 'signin')
    request.session[BIND_USER_KEY] = user.id
    return redirect('google_verify')


def _binding_user(request):
    if request.user.is_authenticated:
        return request.user
    return User.objects.filter(id=request.session.get(BIND_USER_KEY), is_active=True).first()


@require_http_methods(['GET', 'POST'])
def google_verify(request):
    """Enter the emailed code to finish linking the Google account."""
    user = _binding_user(request)
    pending = latest_code(user, 'bind_google') if user else None
    if not user or not pending:
        return redirect('google_bind' if request.user.is_authenticated else 'signin')

    error = None
    if request.method == 'POST':
        if request.POST.get('action') == 'resend':
            try:
                issue_code(user, 'bind_google', pending.sent_to, payload=pending.payload)
                messages.success(request, 'A new code is on its way.')
            except CodeError as exc:
                messages.error(request, str(exc))
            return redirect('google_verify')
        try:
            record = verify_code(user, 'bind_google', request.POST.get('code', ''))
            sub = record.payload['sub']
            if UserProfile.objects.filter(google_sub=sub).exclude(user=user).exists():
                raise CodeError('That Google account was just linked to another ARMS account.')
            profile = user.profile
            profile.google_sub = sub
            profile.google_email = record.payload['email']
            profile.google_linked_at = timezone.now()
            profile.save(update_fields=['google_sub', 'google_email', 'google_linked_at', 'updated_at'])
            request.session.pop(BIND_USER_KEY, None)
            if not request.user.is_authenticated:
                if not _account_active(user):
                    messages.error(request, 'Your account has been deactivated. Contact your administrator.')
                    return redirect('signin')
                _finish_login(request, user)
            messages.success(request, f'Google account {profile.google_email} linked. Next time, just choose "Sign in with Google".')
            return redirect(_get_dashboard_url(profile.role))
        except CodeError as exc:
            error = str(exc)

    return render(request, 'accounts/code_verify.html', {
        'title': 'Check your email',
        'icon': 'fi-rr-envelope-open',
        'lead': 'We sent a 6-digit code to',
        'sent_to': pending.sent_to,
        'note': 'Enter it to finish linking your Google account.',
        'submit_label': 'Verify and link',
        'error': error,
        'back_url': 'signout' if request.user.is_authenticated else 'signin',
        'back_label': 'Sign out' if request.user.is_authenticated else 'Back to sign in',
    })


@login_required
def google_bind(request):
    """Shown until a signed-in user has linked a Google account."""
    profile = request.user.profile
    if not settings.GOOGLE_SIGNIN_ENABLED or (profile.google_sub and not request.GET.get('change')):
        return redirect(_get_dashboard_url(profile.role))
    return render(request, 'accounts/google_bind.html', {
        'changing': bool(profile.google_sub),
        'required': settings.GOOGLE_BINDING_REQUIRED and not profile.google_sub,
        'dashboard_url': _get_dashboard_url(profile.role),
    })


# =============================================================================
# PASSWORD RESET WITH AN EMAILED CODE
# =============================================================================

def _find_reset_user(identifier):
    matches = list(
        User.objects.filter(is_active=True)
        .filter(Q(email__iexact=identifier) | Q(username__iexact=identifier) | Q(profile__google_email__iexact=identifier))
        .distinct()[:2]
    )
    return matches[0] if len(matches) == 1 else None


def _reset_address(user):
    return user.email or getattr(user.profile, 'google_email', '')


@require_http_methods(['GET', 'POST'])
def password_reset_request(request):
    """Ask for the account's email or username and send a reset code."""
    identifier = (request.POST.get('email') or request.GET.get('email') or '').strip()
    error = None
    if request.method == 'POST':
        if not identifier:
            error = 'Enter your email address or username.'
        else:
            user = _find_reset_user(identifier)
            address = _reset_address(user) if user else ''
            # The same answer is given whether or not an account matched.
            request.session[RESET_USER_KEY] = None
            request.session.pop(RESET_VERIFIED_KEY, None)
            request.session[RESET_SENT_KEY] = mask_email(address) if address else (
                mask_email(identifier) if '@' in identifier else 'the email on your account'
            )
            if user and address:
                try:
                    issue_code(user, 'password_reset', address)
                    request.session[RESET_USER_KEY] = user.id
                except CodeError as exc:
                    error = str(exc)
            if not error:
                return redirect('password_reset_verify')

    return render(request, 'accounts/password_reset.html', {'email': identifier, 'error': error})


@require_http_methods(['GET', 'POST'])
def password_reset_verify(request):
    """Step 2: enter the emailed code. Only a correct code opens the new-password page."""
    if RESET_SENT_KEY not in request.session:
        return redirect('password_reset')
    user = User.objects.filter(id=request.session.get(RESET_USER_KEY), is_active=True).first()

    error = None
    if request.method == 'POST':
        if request.POST.get('action') == 'resend':
            if user:
                try:
                    issue_code(user, 'password_reset', _reset_address(user))
                except CodeError as exc:
                    messages.error(request, str(exc))
                    return redirect('password_reset_verify')
            messages.success(request, 'If the account exists, a new code is on its way.')
            return redirect('password_reset_verify')
        try:
            if not user:
                raise CodeError('That code is not correct.')
            verify_code(user, 'password_reset', request.POST.get('code', ''))
            request.session[RESET_VERIFIED_KEY] = {'user': user.id, 'at': timezone.now().timestamp()}
            return redirect('password_reset_new')
        except CodeError as exc:
            error = str(exc)

    return render(request, 'accounts/password_reset_verify.html', {
        'sent_to': request.session[RESET_SENT_KEY], 'error': error,
    })


@require_http_methods(['GET', 'POST'])
def password_reset_new(request):
    """Step 3: choose the new password. Reachable only right after a correct code."""
    verified = request.session.get(RESET_VERIFIED_KEY) or {}
    fresh = timezone.now().timestamp() - verified.get('at', 0) <= RESET_VERIFIED_MINUTES * 60
    user = User.objects.filter(id=verified.get('user'), is_active=True).first() if fresh else None
    if not user:
        request.session.pop(RESET_VERIFIED_KEY, None)
        if verified:
            messages.error(request, 'That took too long. Please request a new code.')
        return redirect('password_reset')

    errors = []
    if request.method == 'POST':
        new_password = request.POST.get('new_password', '')
        if new_password != request.POST.get('confirm_password', ''):
            errors.append('The two passwords do not match.')
        else:
            try:
                validate_password(new_password, user=user)
            except ValidationError as exc:
                errors.extend(exc.messages)
        if not errors:
            user.set_password(new_password)
            user.save()
            profile = user.profile
            if profile.must_change_password:
                profile.must_change_password = False
                profile.save(update_fields=['must_change_password', 'updated_at'])
            for key in (RESET_USER_KEY, RESET_SENT_KEY, RESET_VERIFIED_KEY):
                request.session.pop(key, None)
            messages.success(request, 'Your password has been reset. You can sign in now.')
            return redirect('signin')

    return render(request, 'accounts/password_reset_new.html', {'errors': errors, 'account': user})


def password_reset_done(request):
    # Kept for old links: the reset now finishes on the code page.
    return redirect('password_reset_verify')


# =============================================================================
# ACCOUNT SETTINGS
# =============================================================================

SETTINGS_BASES = {
    'teacher': 'teachers/base.html',
    'registrar': 'registrars/base.html',
    'schoolhead': 'heads/base.html',
}


@login_required
@require_http_methods(['GET', 'POST'])
def account_settings(request):
    user = request.user
    profile = user.profile
    errors = {}

    if request.method == 'POST':
        action = request.POST.get('action')

        if action == 'profile':
            first = ' '.join(request.POST.get('first_name', '').split())
            last = ' '.join(request.POST.get('last_name', '').split())
            if not first or not last:
                errors['profile'] = 'First and last name are both required.'
            else:
                user.first_name, user.last_name = first[:150], last[:150]
                user.save()
                messages.success(request, 'Your name has been updated.')
                return redirect('account_settings')

        elif action == 'email':
            new_email = request.POST.get('email', '').strip().lower()
            try:
                validate_email(new_email)
                if new_email == (user.email or '').lower():
                    raise ValidationError('That is already your email address.')
                if User.objects.filter(Q(email__iexact=new_email) | Q(username__iexact=new_email)).exclude(pk=user.pk).exists():
                    raise ValidationError('Another account already uses that email address.')
                issue_code(user, 'change_email', new_email, payload={'email': new_email})
                messages.success(request, f'We sent a code to {new_email}. Enter it below to confirm the change.')
                return redirect('account_settings')
            except ValidationError as exc:
                errors['email'] = ' '.join(exc.messages)
            except CodeError as exc:
                errors['email'] = str(exc)

        elif action == 'email_confirm':
            try:
                record = verify_code(user, 'change_email', request.POST.get('code', ''))
                new_email = record.payload['email']
                if User.objects.filter(Q(email__iexact=new_email) | Q(username__iexact=new_email)).exclude(pk=user.pk).exists():
                    raise CodeError('Another account already uses that email address.')
                user.email = new_email
                user.save()
                messages.success(request, f'Your email is now {new_email}.')
                return redirect('account_settings')
            except CodeError as exc:
                errors['email_confirm'] = str(exc)

        elif action == 'email_cancel':
            pending = latest_code(user, 'change_email')
            if pending:
                pending.used_at = timezone.now()
                pending.save(update_fields=['used_at'])
            return redirect('account_settings')

        elif action == 'password':
            new_password = request.POST.get('new_password', '')
            if not user.check_password(request.POST.get('current_password', '')):
                errors['password'] = 'Your current password is not correct.'
            elif new_password != request.POST.get('confirm_password', ''):
                errors['password'] = 'The two new passwords do not match.'
            else:
                try:
                    validate_password(new_password, user=user)
                    user.set_password(new_password)
                    user.save()
                    update_session_auth_hash(request, user)  # stay signed in
                    messages.success(request, 'Your password has been changed.')
                    return redirect('account_settings')
                except ValidationError as exc:
                    errors['password'] = ' '.join(exc.messages)

    pending_email = latest_code(user, 'change_email')
    if pending_email and not pending_email.is_usable:
        pending_email = None
    return render(request, 'accounts/settings.html', {
        'base_template': SETTINGS_BASES.get(profile.role, 'accounts/settings_shell.html'),
        'profile': profile,
        'errors': errors,
        'pending_email': pending_email,
        'google_enabled': settings.GOOGLE_SIGNIN_ENABLED,
        'dashboard_url': _get_dashboard_url(profile.role),
    })
