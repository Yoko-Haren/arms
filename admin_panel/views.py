from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.db.models import Count, Q, Sum, Avg
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.conf import settings
from django.db import transaction
from django.db.models import ProtectedError
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from datetime import datetime, time, timedelta
import secrets

# ===== USE THE REAL MODELS =====
from academics.models import School, GradeLevel, SchoolYear, Quarter, GradingSchema
from accounts.models import UserProfile
from enrollment.models import Enrollment

from core.caching import remember_filters

from .forms import (
    AdminLoginForm, SchoolForm, PrincipalCreationForm, PrincipalEditForm,
    RegistrarCreationForm, GradeLevelForm, SchoolYearForm, QuarterForm,
    QuarterUpdateForm, GRADE_NUMBERS, PERIOD_CONFIG, period_config,
    default_registrar_account,
)


# =============================================================================
# HELPERS
# =============================================================================

def is_admin(user):
    return user.is_authenticated and (
        user.is_superuser or user.groups.filter(name='Admin').exists()
    )


def get_school_principals(school):
    return UserProfile.objects.filter(role='schoolhead', school=school, is_active=True)


def get_school_registrars(school):
    return UserProfile.objects.filter(role='registrar', school=school, is_active=True)


def get_school_teachers(school):
    return UserProfile.objects.filter(role='teacher', school=school, is_active=True)


def get_school_students(school):
    return Enrollment.objects.filter(
        section__school=school, status__in=['Enrolled', 'Transferred_In']
    ).select_related('student', 'section__grade_level')


def _period_deadlines(date_end):
    """Default grade encoding / validation deadlines: 7 and 14 days after a period ends."""
    end = datetime.combine(date_end, time(23, 59))
    if settings.USE_TZ:
        end = timezone.make_aware(end)
    return end + timedelta(days=7), end + timedelta(days=14)


def _generate_periods(sy):
    """Create the missing grading periods of a school year, split evenly over its dates.

    The number of periods and their labels follow the school's period type.
    Returns (created, already_existing).
    """
    cfg = period_config(sy.school)
    count = cfg['count']
    length = ((sy.date_end - sy.date_start).days + 1) // count
    created = 0
    with transaction.atomic():
        for i in range(count):
            start = sy.date_start + timedelta(days=length * i)
            end = sy.date_end if i == count - 1 else start + timedelta(days=length - 1)
            encoding, validation = _period_deadlines(end)
            _, was_created = Quarter.objects.get_or_create(
                school_year=sy,
                quarter_number=i + 1,
                defaults={
                    'quarter_label': f'{cfg["prefix"]}{i + 1}',
                    'date_start': start,
                    'date_end': end,
                    'grade_encoding_deadline': encoding,
                    'grade_validation_deadline': validation,
                },
            )
            created += was_created
    return created, count - created


def _with_period_info(school_years):
    """Attach period wording and progress to each school year for the templates."""
    school_years = list(school_years)
    for sy in school_years:
        sy.period_cfg = period_config(sy.school)
        sy.periods = list(sy.quarters.all())
        sy.missing_periods = max(sy.period_cfg['count'] - len(sy.periods), 0)
    return school_years


def _log_admin_action(request, action_type, description):
    try:
        from audit.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user if request.user.is_authenticated else None,
            user_name=request.user.get_full_name() if request.user.is_authenticated else 'System',
            user_role='admin', action_type=action_type,
            resource_type='Admin Panel', resource_id='',
            details_json={'description': description},
            ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
    except Exception:
        pass


# =============================================================================
# AUTHENTICATION
# =============================================================================

def admin_login(request):
    if request.user.is_authenticated and is_admin(request.user):
        return redirect('admin_panel:dashboard')
    if request.method == 'POST':
        form = AdminLoginForm(request.POST)
        if form.is_valid():
            username = form.cleaned_data['username']
            password = form.cleaned_data['password']
            user = authenticate(request, username=username, password=password)
            if user and is_admin(user):
                login(request, user)
                messages.success(request, f'Welcome back, {user.get_full_name() or user.username}!')
                return redirect(request.GET.get('next', 'admin_panel:dashboard'))
            elif user:
                messages.error(request, 'You do not have admin privileges.')
            else:
                messages.error(request, 'Invalid username or password.')
    else:
        form = AdminLoginForm()
    return render(request, 'admin/login.html', {'form': form})


def admin_logout(request):
    if request.user.is_authenticated:
        logout(request)
        messages.info(request, 'You have been successfully logged out.')
    return redirect('signin')

# =============================================================================
# DASHBOARD
# =============================================================================

# Replace the dashboard function with this:

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def dashboard(request):
    """Admin dashboard with comprehensive statistics"""
    current_sy = SchoolYear.objects.filter(is_current=True).first()

    total_schools = School.objects.filter(is_active=True).count()
    total_inactive_schools = School.objects.filter(is_active=False).count()
    total_principals = UserProfile.objects.filter(role='schoolhead', is_active=True).count()
    total_registrars = UserProfile.objects.filter(role='registrar', is_active=True).count()
    total_teachers = UserProfile.objects.filter(role='teacher', is_active=True).count()
    total_students = Enrollment.objects.filter(status__in=['Enrolled', 'Transferred_In']).count()
    total_grade_levels = GradeLevel.objects.all().count()

    # ✅ FIXED: School has NO school_type field — remove this or use grading_scale
    # Instead, group by grading_scale which DOES exist
    school_distribution = School.objects.filter(is_active=True).values(
        'grading_scale'
    ).annotate(count=Count('id')).order_by('grading_scale')

    recent_schools = School.objects.filter(is_active=True).order_by('-created_at')[:5]

    recent_principals = UserProfile.objects.filter(
        role='schoolhead'
    ).select_related('user', 'school').order_by('-created_at')[:5]

    schools_with_principals = UserProfile.objects.filter(
        role='schoolhead', is_active=True, school__isnull=False
    ).values_list('school_id', flat=True)
    schools_without_principal = School.objects.filter(is_active=True).exclude(
        id__in=schools_with_principals
    ).count()

    schools_with_sy = SchoolYear.objects.values_list('school_id', flat=True)
    schools_without_sy = School.objects.filter(is_active=True).exclude(
        id__in=schools_with_sy
    ).count()

    context = {
        'total_schools': total_schools,
        'total_inactive_schools': total_inactive_schools,
        'total_principals': total_principals,
        'total_registrars': total_registrars,
        'total_teachers': total_teachers,
        'total_students': total_students,
        'total_grade_levels': total_grade_levels,
        'active_school_years': SchoolYear.objects.filter(is_current=True).count(),
        'current_sy': current_sy,
        'recent_schools': recent_schools,
        'recent_principals': recent_principals,
        'school_distribution': school_distribution,  # ✅ Renamed from school_type_distribution
        'schools_without_principal': schools_without_principal,
        'schools_without_sy': schools_without_sy,
    }
    return render(request, 'admin/dashboard.html', context)


# =============================================================================
# SCHOOL MANAGEMENT
# =============================================================================

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
@remember_filters('admin-school_list', ['search', 'grading', 'status', 'sort'])
def school_list(request):
    """List all schools"""
    schools = School.objects.all().annotate(
        principal_count=Count('staff_profiles', filter=Q(staff_profiles__role='schoolhead', staff_profiles__is_active=True)),
        registrar_count=Count('staff_profiles', filter=Q(staff_profiles__role='registrar', staff_profiles__is_active=True)),
        teacher_count=Count('staff_profiles', filter=Q(staff_profiles__role='teacher', staff_profiles__is_active=True)),
    )

    search = request.GET.get('search', '')
    if search:
        schools = schools.filter(
            Q(school_name__icontains=search) | 
            Q(school_id__icontains=search) | 
            Q(address__icontains=search)
        )

    # ✅ FIXED: Filter by grading_scale instead of school_type
    grading_filter = request.GET.get('grading', '')
    if grading_filter:
        schools = schools.filter(grading_scale=grading_filter)

    status = request.GET.get('status', 'active')
    if status == 'inactive':
        schools = schools.filter(is_active=False)
    elif status != 'all':
        schools = schools.filter(is_active=True)

    sort = request.GET.get('sort', '-created_at')
    valid_sorts = ['school_name', '-school_name', 'created_at', '-created_at']
    schools = schools.order_by(sort if sort in valid_sorts else '-created_at')

    paginator = Paginator(schools, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'schools': page_obj,
        'search': search,
        'grading_filter': grading_filter,
        'status': status,
        'sort': sort,
        'total_count': schools.count(),
        'active_count': School.objects.filter(is_active=True).count(),
        'inactive_count': School.objects.filter(is_active=False).count(),
    }
    return render(request, 'admin/school_list.html', context)

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_create(request):
    if request.method == 'POST':
        form = SchoolForm(request.POST)
        if form.is_valid():
            try:
                with transaction.atomic():
                    school = form.save(commit=False)
                    school.save()
                    
                    schema_type = form.cleaned_data.get('grading_schema_type')
                    if schema_type and not GradingSchema.objects.filter(school=school).exists():
                        form._create_default_schema(school, schema_type)
                    
                    messages.success(request, f'School "{school.school_name}" created!')
                    return redirect('admin_panel:school_list')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = SchoolForm()
    
    return render(request, 'admin/school_create.html', {
        'form': form, 'edit_mode': False, 'period_config': PERIOD_CONFIG,
        'title': 'Create New School', 'submit_text': 'Create School',
    })

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_detail(request, school_id):
    school = get_object_or_404(School, id=school_id)
    principals = get_school_principals(school)
    registrars = get_school_registrars(school)
    teachers = get_school_teachers(school)
    students = get_school_students(school)
    grade_levels = GradeLevel.objects.filter(school=school).order_by('grade_number')  # ✅ No is_active
    school_years = SchoolYear.objects.filter(school=school).prefetch_related('quarters')

    context = {
        'school': school,
        'principals': principals,
        'registrars': registrars,
        'teachers': teachers,
        'students': students,
        'grade_levels': grade_levels,
        'school_years': school_years,
        'current_sy': school_years.filter(is_current=True).first(),
        'principal_count': principals.count(),
        'registrar_count': registrars.count(),
        'teacher_count': teachers.count(),
        'student_count': students.count(),
    }
    return render(request, 'admin/school_detail.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_edit(request, school_id):
    school = get_object_or_404(School, id=school_id)
    if request.method == 'POST':
        form = SchoolForm(request.POST, instance=school)
        if form.is_valid():
            form.save()
            messages.success(request, f'School "{school.school_name}" updated!')
            return redirect('admin_panel:school_detail', school_id=school.id)
        _form_errors_to_messages(request, form)
    else:
        form = SchoolForm(instance=school)
    return render(request, 'admin/school_create.html', {'form': form, 'school': school, 'edit_mode': True, 'period_config': PERIOD_CONFIG, 'title': f'Edit: {school.school_name}', 'submit_text': 'Update School'})


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_toggle_status(request, school_id):
    school = get_object_or_404(School, id=school_id)
    if request.method == 'POST':
        school.is_active = not school.is_active
        school.save()
        status = "activated" if school.is_active else "deactivated"
        messages.success(request, f'School "{school.school_name}" {status}.')
    return redirect('admin_panel:school_detail', school_id=school.id)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_delete(request, school_id):
    school = get_object_or_404(School, id=school_id)
    if request.method == 'POST':
        has_staff = UserProfile.objects.filter(school=school).exists()
        has_students = Enrollment.objects.filter(section__school=school).exists()
        if has_staff or has_students:
            messages.error(request, f'Cannot delete "{school.school_name}". Deactivate it instead.')
        else:
            school.delete()
            messages.success(request, f'School "{school.school_name}" deleted.')
            return redirect('admin_panel:school_list')
    return render(request, 'admin/school_confirm_delete.html', {'school': school})


# =============================================================================
# PRINCIPAL MANAGEMENT
# =============================================================================

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
@remember_filters('admin-principal_list', ['search', 'school', 'status', 'sort'])
def principal_list(request):
    principals = UserProfile.objects.filter(role='schoolhead').select_related('user', 'school').annotate(
        registrar_count=Count('school__staff_profiles', filter=Q(school__staff_profiles__role='registrar', school__staff_profiles__is_active=True)),
        teacher_count=Count('school__staff_profiles', filter=Q(school__staff_profiles__role='teacher', school__staff_profiles__is_active=True)),
    ).order_by('user__last_name')

    search = request.GET.get('search', '')
    if search:
        principals = principals.filter(Q(user__first_name__icontains=search) | Q(user__last_name__icontains=search) | Q(user__email__icontains=search) | Q(employee_number__icontains=search) | Q(school__school_name__icontains=search))

    school_filter = request.GET.get('school', '')
    if school_filter:
        principals = principals.filter(school_id=school_filter)

    status = request.GET.get('status', 'active')
    if status == 'inactive':
        principals = principals.filter(is_active=False)
    elif status == 'active':
        principals = principals.filter(is_active=True)

    sort = request.GET.get('sort', 'user__last_name')
    valid_sorts = {'user__last_name', '-user__last_name', 'school__school_name', '-school__school_name', '-created_at', 'created_at'}
    principals = principals.order_by(sort if sort in valid_sorts else 'user__last_name')

    paginator = Paginator(principals, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'principals': page_obj,
        'search': search, 'school_filter': school_filter, 'status': status, 'sort': sort,
        'schools': School.objects.filter(is_active=True),
        'active_count': UserProfile.objects.filter(role='schoolhead', is_active=True).count(),
        'inactive_count': UserProfile.objects.filter(role='schoolhead', is_active=False).count(),
    }
    return render(request, 'admin/principal_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def principal_create(request):
    schools = School.objects.filter(is_active=True)
    form = PrincipalCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        user, school = _create_school_staff(form.cleaned_data, 'schoolhead', 'Principal', 'School Principal')
        messages.success(request, f'Principal "{user.get_full_name()}" created for {school.school_name}.')
        return redirect('admin_panel:principal_list')
    _form_errors_to_messages(request, form)
    return render(request, 'admin/principal_create.html', {'schools': schools, 'form': form})


def _form_errors_to_messages(request, form):
    if form.is_bound:
        for field, errors in form.errors.items():
            for error in errors:
                messages.error(request, f'{field}: {error}')


def _create_school_staff(data, role, group_name, position_title):
    """Create a school-scoped user, profile, and role group together."""
    with transaction.atomic():
        user = User.objects.create_user(
            username=data['username'].strip().lower(),
            email=data['email'].strip().lower(),
            password=data['password'],
            first_name=data['first_name'].strip(),
            last_name=data['last_name'].strip(),
            is_active=True,
            is_staff=False,
        )
        profile = user.profile
        profile.role = role
        profile.school = data['school']
        profile.employee_number = data.get('employee_id') or None
        profile.designation = data.get('designation') or group_name
        profile.position_title = position_title
        profile.employment_status = 'Regular_Permanent'
        profile.must_change_password = True  # the admin-issued password is temporary
        profile.save()
        group, _ = Group.objects.get_or_create(name=group_name)
        user.groups.add(group)
    return user, data['school']


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
@remember_filters('admin-registrar_list', ['search', 'status'])
def registrar_list(request):
    registrars = UserProfile.objects.filter(role='registrar').select_related('user', 'school').order_by('user__last_name')
    search = request.GET.get('search', '').strip()
    if search:
        registrars = registrars.filter(
            Q(user__first_name__icontains=search) | Q(user__last_name__icontains=search)
            | Q(user__email__icontains=search) | Q(employee_number__icontains=search)
            | Q(school__school_name__icontains=search)
        )
    status = request.GET.get('status', 'active')
    if status == 'active':
        registrars = registrars.filter(is_active=True)
    elif status == 'inactive':
        registrars = registrars.filter(is_active=False)
    return render(request, 'admin/registrar_list.html', {
        'registrars': Paginator(registrars, 10).get_page(request.GET.get('page', 1)),
        'search': search, 'status': status,
        'active_count': UserProfile.objects.filter(role='registrar', is_active=True).count(),
        'inactive_count': UserProfile.objects.filter(role='registrar', is_active=False).count(),
    })


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def registrar_create(request):
    """Create a school's default registrar account; the admin only picks the school."""
    form = RegistrarCreationForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        school = form.cleaned_data['school']
        password = secrets.token_urlsafe(9)
        user, school = _create_school_staff({
            'username': form.account,
            'email': form.account,
            'password': password,
            'first_name': school.short_name,
            'last_name': 'Registrar',
            'school': school,
            'designation': 'School Registrar',
        }, 'registrar', 'Registrar', 'School Registrar')
        messages.success(
            request,
            f'Registrar account created for {school.school_name}. '
            f'Username: {user.username} — Temporary password: {password} '
            '(shown only once; copy it now).'
        )
        return redirect('admin_panel:registrar_list')
    _form_errors_to_messages(request, form)

    taken = set(User.objects.values_list('username', flat=True))
    schools = list(School.objects.filter(is_active=True))
    for school in schools:
        school.registrar_account = default_registrar_account(school)
        school.registrar_exists = school.registrar_account in taken
    return render(request, 'admin/registrar_create.html', {'form': form, 'schools': schools})


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def principal_detail(request, principal_id):
    principal = get_object_or_404(UserProfile.objects.select_related('user', 'school'), id=principal_id, role='schoolhead')
    school = principal.school
    registrars = get_school_registrars(school) if school else UserProfile.objects.none()
    teachers = get_school_teachers(school) if school else UserProfile.objects.none()
    context = {'principal': principal, 'registrars': registrars, 'teachers': teachers}
    return render(request, 'admin/principal_detail.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def principal_toggle_status(request, principal_id):
    principal = get_object_or_404(UserProfile, id=principal_id, role='schoolhead')
    if request.method == 'POST':
        principal.is_active = not principal.is_active
        principal.user.is_active = principal.is_active
        principal.user.save()
        principal.save()
        status = "activated" if principal.is_active else "deactivated"
        messages.success(request, f'Principal "{principal.full_name}" {status}.')
    return redirect('admin_panel:principal_list')


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def principal_reset_password(request, principal_id):
    principal = get_object_or_404(UserProfile, id=principal_id, role='schoolhead')
    if request.method == 'POST':
        new_password = request.POST.get('new_password')
        if new_password and len(new_password) >= 8:
            principal.user.set_password(new_password)
            principal.user.save()
            principal.must_change_password = True
            principal.save(update_fields=['must_change_password', 'updated_at'])
            messages.success(request, f'Password reset for "{principal.full_name}".')
        else:
            messages.error(request, 'Password must be at least 8 characters.')
    return redirect('admin_panel:principal_detail', principal_id=principal.id)


# =============================================================================
# GRADE LEVEL MANAGEMENT (FIXED: No is_active field)
# =============================================================================

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
@remember_filters('admin-grade_level_list', ['school'])
def grade_level_list(request):
    grade_levels = GradeLevel.objects.select_related('school').all().order_by('school__school_name', 'grade_number')

    school_id = request.GET.get('school', '')
    if school_id:
        grade_levels = grade_levels.filter(school_id=school_id)

    paginator = Paginator(grade_levels, 20)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'grade_levels': page_obj,
        'schools': School.objects.filter(is_active=True),
        'selected_school': school_id,
        'active_count': GradeLevel.objects.all().count(),  # ✅ All grade levels
    }
    return render(request, 'admin/grade_level_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def grade_level_create(request):
    """Add one or more grade levels (Grades 7-12) to a school."""
    form = GradeLevelForm(request.POST or None, initial={'school': request.GET.get('school')})
    if request.method == 'POST' and form.is_valid():
        school = form.cleaned_data['school']
        created = 0
        with transaction.atomic():
            for number in form.cleaned_data['grades']:
                # level_category / is_senior_high are set by GradeLevel.save()
                _, was_created = GradeLevel.objects.get_or_create(
                    school=school,
                    grade_code=f'G{number}',
                    defaults={
                        'grade_name': f'Grade {number}',
                        'grade_number': number,
                        'sort_order': number,
                    },
                )
                created += was_created
        skipped = len(form.cleaned_data['grades']) - created
        if created:
            note = f' ({skipped} already existed)' if skipped else ''
            messages.success(request, f'{created} grade level(s) added to {school.school_name}.{note}')
        else:
            messages.info(request, f'Those grade levels already exist for {school.school_name}.')
        return redirect(f"{reverse('admin_panel:grade_level_list')}?school={school.id}")
    _form_errors_to_messages(request, form)

    existing = {}
    for school_id, number in GradeLevel.objects.values_list('school_id', 'grade_number'):
        existing.setdefault(school_id, []).append(number)
    return render(request, 'admin/grade_level_create.html', {
        'form': form,
        'schools': School.objects.filter(is_active=True),
        'grade_numbers': GRADE_NUMBERS,
        'existing_grades': existing,
        'selected_school': request.POST.get('school') or request.GET.get('school', ''),
    })


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def grade_level_delete(request, grade_level_id):
    if request.method == 'POST':
        grade_level = get_object_or_404(GradeLevel, id=grade_level_id)
        try:
            grade_level.delete()
            messages.success(request, f'{grade_level.grade_name} removed.')
        except ProtectedError:
            messages.error(request, f'{grade_level.grade_name} is already in use (sections, subjects or enrollments) and cannot be removed.')
    return redirect('admin_panel:grade_level_list')


# =============================================================================
# SCHOOL YEAR & QUARTER MANAGEMENT
# =============================================================================

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
@remember_filters('admin-school_year_manage', ['school'])
def school_year_manage(request):
    """Manage school years"""
    form = SchoolYearForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        sy = form.save()
        if form.cleaned_data['auto_create_periods']:
            created, _ = _generate_periods(sy)
            plural = period_config(sy.school)['plural'].lower()
            messages.success(request, f'School Year {sy.year_label} created for {sy.school.school_name} with {created} {plural}.')
        else:
            messages.success(request, f'School Year {sy.year_label} created for {sy.school.school_name}.')
        return redirect('admin_panel:school_year_manage')
    _form_errors_to_messages(request, form)

    school_years = SchoolYear.objects.select_related('school').prefetch_related('quarters').order_by('-date_start')
    school_filter = request.GET.get('school', '')
    if school_filter:
        school_years = school_years.filter(school_id=school_filter)

    schools_with_sy = SchoolYear.objects.values_list('school_id', flat=True).distinct()
    schools_without_sy = School.objects.filter(is_active=True).exclude(id__in=schools_with_sy)

    context = {
        'form': form,
        'school_years': _with_period_info(school_years),
        'schools': School.objects.filter(is_active=True),
        'selected_school': school_filter,
        'schools_without_sy': schools_without_sy,
        'current_school_years': school_years.filter(is_current=True),
        'period_config': PERIOD_CONFIG,
    }
    return render(request, 'admin/school_year_manage.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_year_set_current(request, sy_id):
    if request.method == 'POST':
        sy = get_object_or_404(SchoolYear, id=sy_id)
        sy.is_current = True
        sy.status = 'Active'
        sy.save()
        messages.success(request, f'{sy.year_label} set as the current school year of {sy.school.school_name}.')
    return redirect('admin_panel:school_year_manage')


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_year_delete(request, sy_id):
    if request.method == 'POST':
        sy = get_object_or_404(SchoolYear, id=sy_id)
        try:
            sy.delete()
            messages.success(request, 'School year deleted.')
        except ProtectedError:
            messages.error(request, f'{sy.year_label} already has records attached and cannot be deleted.')
    return redirect('admin_panel:school_year_manage')


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
@remember_filters('admin-quarter_manage', ['school', 'school_year'])
def quarter_manage(request):
    """Manage grading periods (quarters / trimesters / semesters, by school period type)."""
    form = QuarterForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        period = form.save(commit=False)
        period.grade_encoding_deadline, period.grade_validation_deadline = _period_deadlines(period.date_end)
        period.save()
        messages.success(request, f'{period.quarter_label} created for {period.school_year}.')
        return redirect(f"{reverse('admin_panel:quarter_manage')}?school_year={period.school_year_id}")
    _form_errors_to_messages(request, form)

    all_school_years = SchoolYear.objects.select_related('school').order_by('-date_start')
    school_years = all_school_years.prefetch_related('quarters')

    sy_filter = request.GET.get('school_year', '')
    if sy_filter:
        school_years = school_years.filter(id=sy_filter)
    school_filter = request.GET.get('school', '')
    if school_filter:
        school_years = school_years.filter(school_id=school_filter)

    context = {
        'form': form,
        'grouped_school_years': _with_period_info(school_years),
        'school_years': _with_period_info(all_school_years.prefetch_related('quarters')),
        'schools': School.objects.filter(is_active=True),
        'selected_sy': sy_filter,
        'selected_school': school_filter,
    }
    return render(request, 'admin/quarter_manage.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def quarter_bulk_create(request, sy_id):
    """Create every missing grading period of a school year."""
    if request.method == 'POST':
        sy = get_object_or_404(SchoolYear.objects.select_related('school'), id=sy_id)
        created, skipped = _generate_periods(sy)
        plural = period_config(sy.school)['plural'].lower()
        if created:
            messages.success(request, f'{created} {plural} created for {sy.year_label} ({skipped} already existed).')
        else:
            messages.info(request, f'All {skipped} {plural} already exist for {sy.year_label}.')
    return redirect(request.POST.get('next') or 'admin_panel:quarter_manage')


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def quarter_update(request, quarter_id):
    """Adjust a grading period's dates, current flag and grade lock."""
    period = get_object_or_404(Quarter, id=quarter_id)
    if request.method == 'POST':
        was_locked = period.is_grades_locked
        form = QuarterUpdateForm(request.POST, instance=period)
        if form.is_valid():
            period = form.save(commit=False)
            if period.is_grades_locked and not was_locked:
                period.locked_by, period.locked_at = request.user, timezone.now()
            elif not period.is_grades_locked:
                period.locked_by, period.locked_at = None, None
            period.save()
            messages.success(request, f'{period.quarter_label} updated.')
        else:
            _form_errors_to_messages(request, form)
    return redirect(f"{reverse('admin_panel:quarter_manage')}?school_year={period.school_year_id}")


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def quarter_delete(request, quarter_id):
    if request.method == 'POST':
        period = get_object_or_404(Quarter, id=quarter_id)
        try:
            period.delete()
            messages.success(request, f'{period.quarter_label} deleted.')
        except ProtectedError:
            messages.error(request, f'{period.quarter_label} already has grades or records attached and cannot be deleted.')
    return redirect('admin_panel:quarter_manage')



@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def principal_edit(request, principal_id):
    principal = get_object_or_404(UserProfile.objects.select_related('user', 'school'), id=principal_id, role='schoolhead')
    user = principal.user
    form = PrincipalEditForm(request.POST or None, principal=principal, initial={
        'first_name': user.first_name,
        'last_name': user.last_name,
        'username': user.username,
        'email': user.email,
        'school': principal.school_id,
        'employee_id': principal.employee_number,
        'designation': principal.designation,
    })
    if request.method == 'POST' and form.is_valid():
        data = form.cleaned_data
        with transaction.atomic():
            user.first_name = data['first_name'].strip()
            user.last_name = data['last_name'].strip()
            user.username = data['username']
            user.email = data['email']
            user.save()
            principal.school = data['school']
            principal.employee_number = data['employee_id'] or None
            principal.designation = data['designation'] or 'Principal'
            principal.save()
        messages.success(request, f'Principal "{principal.full_name}" updated!')
        return redirect('admin_panel:principal_detail', principal_id=principal.id)
    _form_errors_to_messages(request, form)
    return render(request, 'admin/principal_edit.html', {'principal': principal, 'form': form})


# =============================================================================
# AJAX ENDPOINTS
# =============================================================================

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def get_school_details(request, school_id):
    school = get_object_or_404(School, id=school_id)
    principal = get_school_principals(school).first()
    return JsonResponse({'id': str(school.id), 'name': school.school_name, 'school_id': school.school_id, 'address': school.address, 'principal': principal.full_name if principal else 'Not assigned'})


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def get_grade_levels_for_school(request, school_id):
    gl = GradeLevel.objects.filter(school_id=school_id).values('id', 'grade_name', 'strand').order_by('grade_number')
    return JsonResponse(list(gl), safe=False)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def get_school_years_for_school(request, school_id):
    sy = SchoolYear.objects.filter(school_id=school_id).values('id', 'year_label', 'is_current').order_by('-date_start')
    return JsonResponse(list(sy), safe=False)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def check_school_id(request):
    return JsonResponse({'exists': School.objects.filter(school_id=request.GET.get('school_id', '')).exists()})


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def check_username(request):
    return JsonResponse({'exists': User.objects.filter(username=request.GET.get('username', '')).exists()})
