"""School head — User Management.

The principal sees and manages only the accounts of their own school, and may
add registrar accounts. System-wide user administration belongs to the admin panel.

When the School Head is busy, they can let a registrar or a teacher (an ICT coordinator, say) manage the school's
accounts too: edit details, reset passwords, activate and deactivate. A delegate works in their own portal, never
touches a School Head's account, cannot add registrars and cannot pass the permission on. Everyone can also reset a
forgotten password from the sign-in page, and sign-in help requests from the school's staff reach the School Head
and the delegates (communication/views_public.py), so the System Administrator is not the only way back in.
"""
import json
import secrets
from datetime import date
from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import Group, User
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_GET, require_POST

from accounts.models import UserProfile
from communication.notify import notify
from registrars.forms import TeacherAccountForm, school_email_domain

from .views import _log

# Roles a principal manages inside the school. Administrators are never listed.
SCHOOL_ROLES = ['schoolhead', 'registrar', 'teacher', 'guidance']
# Roles the School Head may trust with account management (each has a portal of its own to work in)
DELEGABLE_ROLES = ['registrar', 'teacher']
PORTAL_BASE = {'schoolhead': 'heads/base.html', 'registrar': 'registrars/base.html', 'teacher': 'teachers/base.html'}

# Designation choices offered in the Edit User form, by role.
DESIGNATIONS = {
    'registrar': ['School Registrar', 'Registrar I', 'Registrar II', 'Registrar III',
                  'Administrative Officer II', 'Administrative Assistant III'],
    'teacher': ['Teacher I', 'Teacher II', 'Teacher III', 'Teacher IV', 'Teacher V', 'Teacher VI', 'Teacher VII',
                'Master Teacher I', 'Master Teacher II', 'Master Teacher III', 'Master Teacher IV',
                'Head Teacher I', 'Head Teacher II', 'Head Teacher III'],
    'schoolhead': ['Principal I', 'Principal II', 'Principal III', 'Principal IV',
                   'Assistant Principal', 'Head Teacher (Officer-in-Charge)', 'School Head'],
    'guidance': ['Guidance Counselor I', 'Guidance Counselor II', 'Guidance Counselor III', 'Guidance Coordinator'],
}


def account_manager(user):
    """The user's profile when they may manage their school's accounts: the School Head, or a registrar or teacher the
    School Head trusted with it. None otherwise."""
    profile = getattr(user, 'profile', None)
    if not profile or not profile.school_id or not profile.is_active:
        return None
    if profile.role == 'schoolhead' or (profile.can_manage_accounts and profile.role in DELEGABLE_ROLES):
        return profile
    return None


def _is_head(request):
    return request.user.profile.role == 'schoolhead'


def accounts_api(head_only=False):
    """JSON endpoints for the School Head, and (unless head_only) the staff they trusted with the school's accounts."""
    def decorator(view):
        @login_required
        @wraps(view)
        def wrapper(request, *args, **kwargs):
            profile = account_manager(request.user)
            if profile is None or (head_only and profile.role != 'schoolhead'):
                return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
            return view(request, *args, **kwargs)
        return wrapper
    return decorator


def _editable(request, profile):
    """A delegate never changes a School Head's account; the School Head can change every account of the school."""
    return _is_head(request) or profile.role != 'schoolhead'


NOT_EDITABLE = 'Only the School Head can change a School Head account.'


def _school_users(request):
    """Accounts of the principal's own school."""
    return UserProfile.objects.filter(
        school=request.user.profile.school, role__in=SCHOOL_ROLES
    ).select_related('user')


def _is_active(profile):
    return profile.is_active and profile.user.is_active


def _stats(request):
    users = _school_users(request)
    active = users.filter(is_active=True, user__is_active=True)
    return {
        'total': users.count(),
        'active': active.count(),
        'inactive': users.count() - active.count(),
        'google': users.filter(google_sub__isnull=False).count(),
    }


def _serialize(profile):
    u = profile.user
    return {
        'id': profile.id,
        'name': u.get_full_name() or u.username,
        'first_name': u.first_name,
        'last_name': u.last_name,
        'username': u.username,
        'email': u.email,
        'google_linked': bool(profile.google_sub),
        'google_email': profile.google_email,
        'temporary_password': profile.must_change_password,
        'role': profile.role,
        'role_display': profile.get_role_display(),
        'department': profile.teaching_area or '',
        'status': 'active' if _is_active(profile) else 'inactive',
        'last_active': u.last_login.strftime('%b %d, %Y %H:%M') if u.last_login else None,
        'designation': profile.designation or '',
        'employee_number': profile.employee_number or '',
        'is_self': False,
        'manages_accounts': bool(profile.can_manage_accounts) and profile.role in DELEGABLE_ROLES,
    }


def _row(request, profile):
    row = _serialize(profile)
    row['is_self'] = profile.user_id == request.user.id
    row['editable'] = _editable(request, profile)
    # the School Head may trust a registrar or teacher with the accounts (never themselves)
    row['delegable'] = _is_head(request) and profile.role in DELEGABLE_ROLES and not row['is_self'] and _is_active(profile)
    return row


def _body(request):
    try:
        data = json.loads(request.body or '{}')
        return data if isinstance(data, dict) else {}
    except ValueError:
        return {}


def _get(request, user_id):
    return _school_users(request).filter(id=user_id).first()


# =============================================================================
# PAGE
# =============================================================================

@login_required
def user_management(request):
    profile = account_manager(request.user)
    if profile is None:
        own = getattr(request.user, 'profile', None)
        if own and own.role == 'schoolhead' and not own.school_id:
            messages.error(request, 'You are not assigned to any school. Contact the administrator.')
            return redirect('heads-ai-dashboard')
        messages.error(request, 'Access denied.')
        return redirect('signin')

    school = profile.school
    head = UserProfile.objects.filter(school=school, role='schoolhead', is_active=True).select_related('user').first()
    delegates = UserProfile.objects.filter(school=school, role__in=DELEGABLE_ROLES, can_manage_accounts=True,
                                           is_active=True, user__is_active=True).select_related('user').order_by('user__last_name')
    return render(request, 'heads/users/user_management.html', {
        'base_template': PORTAL_BASE.get(profile.role, 'heads/base.html'),
        'is_head': profile.role == 'schoolhead',
        'head_name': head.user.get_full_name() if head else 'the School Head',
        'delegates': list(delegates),
        'school': school,
        'stats': _stats(request),
        'email_domain': school_email_domain(school),
        'designations': DESIGNATIONS,
    })


# =============================================================================
# JSON API
# =============================================================================

@accounts_api()
@require_GET
def user_list_data(request):
    users = _school_users(request)

    role = request.GET.get('role', 'all')
    if role in SCHOOL_ROLES:
        users = users.filter(role=role)

    status = request.GET.get('status', 'all')
    if status == 'active':
        users = users.filter(is_active=True, user__is_active=True)
    elif status == 'inactive':
        users = users.filter(Q(is_active=False) | Q(user__is_active=False))

    login_type = request.GET.get('login_type', 'all')
    if login_type == 'google':
        users = users.filter(google_sub__isnull=False)
    elif login_type == 'password':
        users = users.filter(google_sub__isnull=True)

    search = request.GET.get('search', '').strip()
    if search:
        users = users.filter(
            Q(user__first_name__icontains=search) | Q(user__last_name__icontains=search)
            | Q(user__email__icontains=search) | Q(user__username__icontains=search)
            | Q(employee_number__icontains=search) | Q(designation__icontains=search)
        )

    try:
        page = max(int(request.GET.get('page', 1)), 1)
        per_page = min(max(int(request.GET.get('per_page', 10)), 1), 100)
    except ValueError:
        page, per_page = 1, 10

    users = users.order_by('role', 'user__last_name', 'user__first_name')
    total = users.count()
    total_pages = max((total + per_page - 1) // per_page, 1)
    page = min(page, total_pages)
    rows = []
    for profile in users[(page - 1) * per_page: page * per_page]:
        rows.append(_row(request, profile))

    return JsonResponse({
        'success': True, 'users': rows, 'total': total, 'page': page,
        'total_pages': total_pages, 'stats': _stats(request),
    })


@accounts_api()
@require_GET
def user_detail_data(request, user_id):
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    data = _row(request, profile)
    data['designations'] = DESIGNATIONS.get(profile.role, [])
    return JsonResponse({'success': True, 'user': data})


@accounts_api(head_only=True)
@require_POST
def user_create(request):
    """Add a registrar account for the principal's school."""
    school = request.user.profile.school
    data = _body(request)
    form = TeacherAccountForm({
        'first_name': data.get('first_name', ''),
        'last_name': data.get('last_name', ''),
        'email': data.get('email', ''),
        'employee_number': data.get('employee_number', ''),
        'designation': data.get('designation', ''),
        'teaching_area': '',
    }, school=school)
    if not form.is_valid():
        error = next(iter(form.errors.values()))[0]
        return JsonResponse({'success': False, 'error': error}, status=400)

    cleaned = form.cleaned_data
    designation = cleaned['designation'] if cleaned['designation'] in DESIGNATIONS['registrar'] else 'School Registrar'
    password = secrets.token_urlsafe(9)
    with transaction.atomic():
        user = User.objects.create_user(
            username=cleaned['email'], email=cleaned['email'], password=password,
            first_name=cleaned['first_name'], last_name=cleaned['last_name'],
        )
        profile = user.profile  # created by the post_save signal
        profile.role = 'registrar'
        profile.school = school
        profile.employee_number = cleaned['employee_number'] or None
        profile.designation = designation
        profile.position_title = 'School Registrar'
        profile.employment_status = 'Regular_Permanent'
        profile.institutional_email = cleaned['email']
        profile.must_change_password = True
        profile.save()
        user.groups.add(Group.objects.get_or_create(name='Registrar')[0])

    _log(request, 'CREATE_USER', 'UserProfile', profile.id, f'Created registrar account {user.username}')
    return JsonResponse({
        'success': True,
        'message': f'Registrar account created for {user.get_full_name()}.',
        'username': user.username,
        'temporary_password': password,
    })


@accounts_api()
@require_POST
def user_update(request, user_id):
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    if not _editable(request, profile):
        return JsonResponse({'success': False, 'error': NOT_EDITABLE}, status=403)
    user = profile.user
    data = _body(request)

    first = ' '.join(str(data.get('first_name', '')).split())
    last = ' '.join(str(data.get('last_name', '')).split())
    email = str(data.get('email', '')).strip().lower()
    employee_number = str(data.get('employee_number', '')).strip()
    designation = str(data.get('designation', '')).strip()[:150]
    department = str(data.get('department', '')).strip()[:150]
    status = data.get('status', 'active')

    if not first or not last or not email:
        return JsonResponse({'success': False, 'error': 'First name, last name and email are required.'}, status=400)
    if User.objects.filter(Q(email__iexact=email) | Q(username__iexact=email)).exclude(pk=user.pk).exists():
        return JsonResponse({'success': False, 'error': 'Another account already uses that email address.'}, status=400)
    if employee_number and UserProfile.objects.filter(employee_number=employee_number).exclude(pk=profile.pk).exists():
        return JsonResponse({'success': False, 'error': f'Employee number {employee_number} is already assigned.'}, status=400)
    if status == 'inactive' and user.id == request.user.id:
        return JsonResponse({'success': False, 'error': 'You cannot deactivate your own account.'}, status=400)

    with transaction.atomic():
        user.first_name, user.last_name, user.email = first[:150], last[:150], email
        user.is_active = status != 'inactive'
        user.save()
        profile.is_active = user.is_active
        profile.employee_number = employee_number or None
        profile.designation = designation
        profile.teaching_area = department
        profile.save()

    _log(request, 'UPDATE_USER', 'UserProfile', profile.id, f'Updated {user.username}')
    return JsonResponse({'success': True, 'message': f'{user.get_full_name()} updated.'})


@accounts_api()
@require_POST
def user_toggle_status(request, user_id):
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    if not _editable(request, profile):
        return JsonResponse({'success': False, 'error': NOT_EDITABLE}, status=403)
    user = profile.user
    if user.id == request.user.id:
        return JsonResponse({'success': False, 'error': 'You cannot deactivate your own account.'}, status=400)

    activate = not _is_active(profile)
    user.is_active = activate
    user.save()
    profile.is_active = activate
    profile.save()

    word = 'activated' if activate else 'deactivated'
    _log(request, 'TOGGLE_USER', 'UserProfile', profile.id, f'{word.capitalize()} {user.username}')
    return JsonResponse({'success': True, 'message': f'{user.get_full_name()} {word}.'})


@accounts_api()
@require_POST
def user_reset_password(request, user_id):
    """Set a new temporary password for any account of the school (a delegate: any but a School Head's)."""
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    if not _editable(request, profile):
        return JsonResponse({'success': False, 'error': NOT_EDITABLE}, status=403)
    user = profile.user
    password = str(_body(request).get('password', ''))
    try:
        validate_password(password, user=user)
    except ValidationError as exc:
        return JsonResponse({'success': False, 'error': ' '.join(exc.messages)}, status=400)

    user.set_password(password)
    user.save()
    # Saved after the user: the user's post_save signal re-saves its own copy of the profile.
    UserProfile.objects.filter(pk=profile.pk).update(must_change_password=user.id != request.user.id)

    _log(request, 'RESET_PASSWORD', 'UserProfile', profile.id, f'Reset password of {user.username}')
    return JsonResponse({
        'success': True,
        'message': f'Password reset for {user.get_full_name()}. They will be asked to set their own at next sign-in.',
    })


@accounts_api(head_only=True)
@require_POST
def user_toggle_delegate(request, user_id):
    """The School Head lets a registrar or teacher manage the school's accounts, or takes that back."""
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    if profile.role not in DELEGABLE_ROLES or profile.user_id == request.user.id or not _is_active(profile):
        return JsonResponse({'success': False, 'error': 'Only an active registrar or teacher can manage accounts for you.'}, status=400)
    grant = not profile.can_manage_accounts
    UserProfile.objects.filter(pk=profile.pk).update(can_manage_accounts=grant)
    name, head = profile.user.get_full_name() or profile.user.username, request.user.get_full_name() or request.user.username
    if grant:
        notify([profile.user], 'SYSTEM_UPDATE', 'You can now manage school accounts',
               f'{head} asked you to help manage the accounts of {request.user.profile.school.school_name}: edit details, reset '
               'passwords, activate and deactivate. Open Accounts in your menu.', action_url=reverse('heads-user-management'))
    else:
        notify([profile.user], 'SYSTEM_UPDATE', 'Account management handed back',
               f'{head} took back the management of the school accounts. Thank you for your help.')
    _log(request, 'UPDATE_USER', 'UserProfile', profile.id,
         f'{"Let" if grant else "Stopped letting"} {profile.user.username} manage the school accounts')
    return JsonResponse({'success': True, 'message': f'{name} {"can now manage" if grant else "no longer manages"} the school accounts.'})


@login_required
def user_export(request):
    profile = account_manager(request.user)
    if profile is None:
        messages.error(request, 'Access denied.')
        return redirect('signin')

    users = _school_users(request).order_by('role', 'user__last_name', 'user__first_name')
    role = request.GET.get('role', 'all')
    if role in SCHOOL_ROLES:
        users = users.filter(role=role)
    status = request.GET.get('status', 'all')
    if status == 'active':
        users = users.filter(is_active=True, user__is_active=True)
    elif status == 'inactive':
        users = users.filter(Q(is_active=False) | Q(user__is_active=False))

    from core.xlsx import Report, safe_filename

    users = list(users.select_related('user'))
    active = sum(1 for p in users if _is_active(p))
    shown = {'all': 'All roles'}.get(role) or dict(UserProfile.ROLE_CHOICES).get(role, role)
    report = Report('School Accounts', profile.school.school_name, request.user.get_full_name() or request.user.username)
    # usernames are usually the email address; then one column is enough
    same = all(p.user.username == p.user.email for p in users)
    widths = [15, 24] + ([36] if same else [30, 34]) + [22, 22, 24, 15, 10, 20]
    sheet = report.sheet('Accounts', widths,
                         subtitle='Accounts of this school', meta=[('Role', shown), ('Status', status.title() if status != 'all' else 'Active and inactive')])
    sheet.figures([('Accounts', str(len(users)), None), ('Active', str(active), 'good'),
                   ('Inactive', str(len(users) - active), 'risk' if len(users) - active else None),
                   ('Google linked', str(sum(1 for p in users if p.google_sub)), None)])
    sheet.table(
        [{'title': 'Employee no.'}, {'title': 'Name'}] + ([{'title': 'Username and email'}] if same else [{'title': 'Username'}, {'title': 'Email'}])
        + [{'title': 'Role', 'wrap': True}, {'title': 'Designation', 'wrap': True}, {'title': 'Department', 'wrap': True},
           {'title': 'Sign-in'}, {'title': 'Status'}, {'title': 'Last active'}],
        [[p.employee_number or '', f'{p.user.last_name}, {p.user.first_name}'.strip(', ')]
         + ([p.user.email] if same else [p.user.username, p.user.email])
         + [p.get_role_display(), p.designation, p.teaching_area, 'Google linked' if p.google_sub else 'Password only',
          ('Active', 'advanced') if _is_active(p) else ('Inactive', 'beginning'),
          p.user.last_login.strftime('%b %d, %Y %I:%M %p') if p.user.last_login else 'Never'] for p in users])
    return report.response(f'{safe_filename(profile.school.short_name or "school", "accounts", date.today().strftime("%Y%m%d"))}.xlsx')
