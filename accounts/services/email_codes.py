"""One-time 6-digit codes sent by email (Google binding, password reset, email change)."""

import logging
import secrets
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone
from django.utils.crypto import constant_time_compare, salted_hmac
from django.utils.html import escape

from ..models import EmailCode

logger = logging.getLogger(__name__)

MAX_CODES_PER_WINDOW = 3  # per user and purpose, within the code lifetime

SUBJECTS = {
    'bind_google': 'Confirm your Google account for ARMS',
    'password_reset': 'Your ARMS password reset code',
    'change_email': 'Confirm your new ARMS email address',
}
INTROS = {
    'bind_google': 'Use this code to finish linking your Google account to ARMS.',
    'password_reset': 'Use this code to reset your ARMS password.',
    'change_email': 'Use this code to confirm this address as your new ARMS email.',
}


class CodeError(Exception):
    """Shown to the user as-is."""


def _hash(user, purpose, code):
    return salted_hmac(f'arms-email-code:{purpose}', f'{user.pk}:{code}').hexdigest()


def issue_code(user, purpose, sent_to, payload=None):
    """Create a code and email it. Earlier unused codes for the same purpose stop working."""
    window = timezone.now() - timedelta(minutes=settings.EMAIL_CODE_MINUTES)
    recent = EmailCode.objects.filter(user=user, purpose=purpose, created_at__gte=window).count()
    if recent >= MAX_CODES_PER_WINDOW:
        raise CodeError(
            f'Too many codes were requested. Please wait {settings.EMAIL_CODE_MINUTES} minutes and try again.'
        )

    code = f'{secrets.randbelow(10 ** 6):06d}'
    now = timezone.now()
    EmailCode.objects.filter(user=user, purpose=purpose, used_at__isnull=True).update(used_at=now)
    record = EmailCode.objects.create(
        user=user, purpose=purpose, sent_to=sent_to, payload=payload or {},
        code_hash=_hash(user, purpose, code),
        expires_at=now + timedelta(minutes=settings.EMAIL_CODE_MINUTES),
    )

    name = user.first_name or user.username
    text = (
        f'Hi {name},\n\n{INTROS[purpose]}\n\n'
        f'    {code}\n\n'
        f'The code expires in {settings.EMAIL_CODE_MINUTES} minutes and can be used once.\n'
        'If you did not ask for this, you can ignore this email; nothing will change.\n\n'
        'ARMS — Academic Records Management System'
    )
    html = (
        '<div style="font-family:Segoe UI,Arial,sans-serif;background:#f5f7fb;padding:24px;">'
        '<div style="max-width:440px;margin:0 auto;background:#ffffff;border-radius:18px;padding:28px;border:1px solid #e9ecef;">'
        '<div style="font-size:18px;font-weight:700;color:#00072D;">ARMS</div>'
        f'<p style="font-size:14px;color:#2d3748;margin:16px 0 6px;">Hi {escape(name)},</p>'
        f'<p style="font-size:14px;color:#718096;margin:0 0 18px;line-height:1.5;">{INTROS[purpose]}</p>'
        '<div style="font-size:30px;font-weight:800;letter-spacing:8px;text-align:center;color:#123499;'
        f'background:#f5f7fb;border-radius:12px;padding:16px;">{code}</div>'
        f'<p style="font-size:12px;color:#718096;margin:18px 0 0;line-height:1.5;">The code expires in '
        f'{settings.EMAIL_CODE_MINUTES} minutes and can be used once. If you did not ask for this, ignore this email.</p>'
        '</div></div>'
    )
    try:
        send_mail(SUBJECTS[purpose], text, settings.DEFAULT_FROM_EMAIL, [sent_to], html_message=html)
    except Exception:
        logger.exception('Could not send %s code email to %s', purpose, sent_to)
        record.delete()
        raise CodeError('We could not send the email right now. Please try again in a moment.')
    return record


def latest_code(user, purpose):
    return EmailCode.objects.filter(user=user, purpose=purpose, used_at__isnull=True).order_by('-created_at').first()


def verify_code(user, purpose, code):
    """Return the matching EmailCode and mark it used, or raise CodeError."""
    record = latest_code(user, purpose)
    if not record or timezone.now() >= record.expires_at:
        raise CodeError('That code has expired. Request a new one.')
    if record.attempts >= EmailCode.MAX_ATTEMPTS:
        raise CodeError('Too many wrong attempts. Request a new code.')

    code = ''.join(ch for ch in str(code) if ch.isdigit())
    if not constant_time_compare(record.code_hash, _hash(user, purpose, code)):
        record.attempts += 1
        record.save(update_fields=['attempts'])
        left = EmailCode.MAX_ATTEMPTS - record.attempts
        if left <= 0:
            raise CodeError('Too many wrong attempts. Request a new code.')
        raise CodeError(f'That code is not correct. {left} attempt{"s" if left != 1 else ""} left.')

    record.used_at = timezone.now()
    record.save(update_fields=['used_at'])
    return record


def mask_email(email):
    """ma***@gmail.com — enough to recognise the address without revealing it."""
    local, _, domain = email.partition('@')
    if not domain:
        return email
    return f'{local[:2]}{"*" * max(len(local) - 2, 3)}@{domain}'
