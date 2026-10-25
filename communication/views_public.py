"""The public endpoint behind the landing page's "Contact us" form and the sign-in help dialog.

Each request is saved (administrators see it on the admin portal's Requests page) and emailed to
settings.ARMS_CONTACT_EMAIL with Reply-To set to the sender, so a reply goes straight to them.
Sign-in help from someone with a school account also reaches that school's School Head and the staff
they trusted with the accounts, so the System Administrator is not the only one who can help.
"""
import logging

from django.conf import settings
from django.contrib import messages
from django.core.cache import cache
from django.core.mail import EmailMessage
from django.http import JsonResponse
from django.shortcuts import redirect
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .forms import ContactRequestForm
from .models import ContactRequest

logger = logging.getLogger(__name__)

LIMIT_PER_HOUR = 5      # messages one device may send in an hour
FAILED = 'Your message could not be sent. Please try again, or email us directly.'


def _wants_json(request):
    return request.headers.get('X-Requested-With') == 'fetch'


def _back(request):
    """Where a browser without JavaScript returns to after posting the form."""
    target = request.POST.get('next') or reverse('home')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse('home')
    return target


def _reply(request, ok, status=200, **data):
    if _wants_json(request):
        return JsonResponse({'ok': ok, **data}, status=status)
    if ok:
        messages.success(request, f'Thank you, {data["name"]}. We received your message and will reply to {data["email"]}.',
                         extra_tags='contact')
    else:
        errors = data.get('errors') or {}
        messages.error(request, next(iter(errors.values()))[0] if errors else data.get('error', FAILED), extra_tags='contact')
    return redirect(_back(request))


def _notify(contact, request):
    """Email the request to the ARMS administrator. Returns whether the mail server accepted it."""
    school = contact.topic == ContactRequest.TOPIC_SCHOOL
    subject = f'[ARMS] School request: {contact.school_name}' if school else f'[ARMS] Sign-in help: {contact.name}'
    rows = [
        ('Type', contact.get_topic_display()),
        ('School', contact.school_name),
        ('Name', contact.name),
        ('Position', contact.position),
        ('Email', contact.email),
        ('Phone', contact.phone),
    ]
    body = '\n'.join(
        ['A new message was sent from the ARMS website.', '']
        + [f'{label}: {value}' for label, value in rows if value]
        + ['', 'Message:', contact.message or '(none)', '',
           f'Sent {timezone.localtime(contact.created_at):%B %d, %Y at %I:%M %p}.',
           'Reply to this email to answer them directly.',
           f'All requests: {request.build_absolute_uri(reverse("admin_panel:request_list"))}']
    )
    try:
        EmailMessage(subject, body, settings.DEFAULT_FROM_EMAIL, [settings.ARMS_CONTACT_EMAIL],
                     reply_to=[contact.email]).send()
        return True
    except Exception:
        logger.exception('Could not email contact request %s', contact.pk)
        return False


def _tell_school(contact):
    """Bell notification for the School Head and the account helpers of the school the person belongs to."""
    if contact.topic != ContactRequest.TOPIC_SUPPORT:
        return 0
    try:
        from django.contrib.auth.models import User
        from django.db.models import Q

        from accounts.models import UserProfile
        from .notify import notify

        address = contact.email.strip()
        person = UserProfile.objects.filter(
            Q(user__email__iexact=address) | Q(user__username__iexact=address) | Q(google_email__iexact=address),
            school__isnull=False).select_related('user').first()
        if person is None:
            return 0
        helpers = User.objects.filter(
            Q(profile__role='schoolhead') | Q(profile__can_manage_accounts=True, profile__role__in=['registrar', 'teacher']),
            profile__school_id=person.school_id, is_active=True, profile__is_active=True).exclude(pk=person.user_id)
        said = f': "{contact.message.strip()[:180]}"' if contact.message.strip() else '.'
        return notify(helpers, 'MESSAGE_RECEIVED', f'Sign-in help: {contact.name}'[:255],
                      f'{contact.name} ({address}) asked for help signing in{said} Check that it is really them, then reset '
                      'their password on User Management (Accounts).', action_url=reverse('heads-user-management'))
    except Exception:
        logger.exception('Could not tell the school about contact request %s', contact.pk)
        return 0


@require_POST
def contact_submit(request):
    # The hidden "website" field is invisible to people; bots fill it in. Pretend it worked.
    if request.POST.get('website'):
        return _reply(request, True, name=request.POST.get('name', '').strip()[:120], email=request.POST.get('email', '').strip()[:254])

    ip = request.META.get('REMOTE_ADDR') or None
    limit_key = f'contact-limit:{ip}'
    if cache.get(limit_key, 0) >= LIMIT_PER_HOUR:
        return _reply(request, False, status=429,
                      error='Too many messages were sent from this device. Please try again later, or email us directly.')

    form = ContactRequestForm(request.POST)
    if not form.is_valid():
        return _reply(request, False, status=400, errors={field: [str(e) for e in errs] for field, errs in form.errors.items()})

    contact = form.save(commit=False)
    contact.ip_address = ip
    contact.user_agent = request.META.get('HTTP_USER_AGENT', '')[:255]
    contact.save()
    if not cache.add(limit_key, 1, 3600):
        cache.incr(limit_key)

    contact.email_sent = _notify(contact, request)
    contact.save(update_fields=['email_sent'])
    _tell_school(contact)
    return _reply(request, True, name=contact.name, email=contact.email)
