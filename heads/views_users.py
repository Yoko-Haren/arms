"""School head — User Management.

The principal sees and manages only the accounts of their own school, and may
add registrar accounts. System-wide user administration belongs to the admin panel.
"""
import csv
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
from django.views.decorators.http import require_GET, require_POST

from accounts.models import UserProfile
from registrars.forms import TeacherAccountForm, school_email_domain

from .views import _log

# Roles a principal manages inside the school. Administrators are never listed.
SCHOOL_ROLES = ['schoolhead', 'registrar', 'teacher', 'guidance']

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


def school_head_api(view):
    """JSON endpoints: only a school head with an assigned school."""
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role != 'schoolhead':
            return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
        if not profile.school_id:
            return JsonResponse({'success': False, 'error': 'You are not assigned to a school.'}, status=403)
        return view(request, *args, **kwargs)
    return wrapper


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
    }


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
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'schoolhead':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    if not profile.school_id:
        messages.error(request, 'You are not assigned to any school. Contact the administrator.')
        return redirect('heads-ai-dashboard')

    return render(request, 'heads/users/user_management.html', {
        'school': profile.school,
        'stats': _stats(request),
        'email_domain': school_email_domain(profile.school),
        'designations': DESIGNATIONS,
    })


# =============================================================================
# JSON API
# =============================================================================

@school_head_api
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
        row = _serialize(profile)
        row['is_self'] = profile.user_id == request.user.id
        rows.append(row)

    return JsonResponse({
        'success': True, 'users': rows, 'total': total, 'page': page,
        'total_pages': total_pages, 'stats': _stats(request),
    })


@school_head_api
@require_GET
def user_detail_data(request, user_id):
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
    data = _serialize(profile)
    data['is_self'] = profile.user_id == request.user.id
    data['designations'] = DESIGNATIONS.get(profile.role, [])
    return JsonResponse({'success': True, 'user': data})


@school_head_api
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


@school_head_api
@require_POST
def user_update(request, user_id):
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
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


@school_head_api
@require_POST
def user_toggle_status(request, user_id):
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
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


@school_head_api
@require_POST
def user_reset_password(request, user_id):
    """Set a new temporary password for any account of the school."""
    profile = _get(request, user_id)
    if not profile:
        return JsonResponse({'success': False, 'error': 'User not found'}, status=404)
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


@login_required
def user_export(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'schoolhead' or not profile.school_id:
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

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = f'attachment; filename="{profile.school.short_name}_users_{date.today():%Y%m%d}.csv"'
    writer = csv.writer(response)
    writer.writerow(['Employee Number', 'First Name', 'Last Name', 'Username', 'Email', 'Role', 'Designation',
                     'Department', 'Sign-in', 'Status', 'Last Active'])
    for p in users:
        u = p.user
        writer.writerow([
            p.employee_number or '', u.first_name, u.last_name, u.username, u.email, p.get_role_display(),
            p.designation, p.teaching_area, 'Google linked' if p.google_sub else 'Password only',
            'Active' if _is_active(p) else 'Inactive',
            u.last_login.strftime('%Y-%m-%d %H:%M') if u.last_login else 'Never',
        ])
    return response
