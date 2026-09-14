from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth import authenticate, login, logout
from django.contrib.auth.decorators import login_required, user_passes_test
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.db.models import Count, Q, Sum, Avg
from django.core.paginator import Paginator, EmptyPage, PageNotAnInteger
from django.db import transaction
from django.http import JsonResponse
from django.urls import reverse
from django.utils import timezone
from datetime import datetime, timedelta

# ===== USE THE REAL MODELS =====
from academics.models import School, GradeLevel, SchoolYear, Quarter, GradingSchema
from accounts.models import UserProfile
from enrollment.models import Enrollment

from .forms import (
    AdminLoginForm, SchoolForm, PrincipalCreationForm,
    GradeLevelForm, SchoolYearForm, QuarterForm, BulkGradeLevelForm
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
        'form': form, 'edit_mode': False,
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
    else:
        form = SchoolForm(instance=school)
    return render(request, 'admin/school_create.html', {'form': form, 'school': school, 'edit_mode': True, 'title': f'Edit: {school.school_name}', 'submit_text': 'Update School'})


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
def principal_list(request):
    principals = UserProfile.objects.filter(role='schoolhead').select_related('user', 'school').order_by('user__last_name')

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

    paginator = Paginator(principals, 10)
    page_obj = paginator.get_page(request.GET.get('page', 1))

    context = {
        'principals': page_obj,
        'search': search, 'school_filter': school_filter, 'status': status,
        'schools': School.objects.filter(is_active=True),
        'active_count': UserProfile.objects.filter(role='schoolhead', is_active=True).count(),
        'inactive_count': UserProfile.objects.filter(role='schoolhead', is_active=False).count(),
    }
    return render(request, 'admin/principal_list.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def principal_create(request):
    schools = School.objects.filter(is_active=True)
    if request.method == 'POST':
        first_name = request.POST.get('first_name', '').strip()
        last_name = request.POST.get('last_name', '').strip()
        email = request.POST.get('email', '').strip().lower()
        username = request.POST.get('username', '').strip().lower()
        password = request.POST.get('password', '')
        school_id = request.POST.get('school', '')
        employee_id = request.POST.get('employee_id', '').strip()

        errors = []
        if not all([first_name, last_name, email, username, password, school_id]):
            errors.append('All required fields must be filled.')
        if User.objects.filter(username=username).exists():
            errors.append(f'Username "{username}" is taken.')
        if User.objects.filter(email=email).exists():
            errors.append(f'Email "{email}" is in use.')
        if employee_id and UserProfile.objects.filter(employee_number=employee_id).exists():
            errors.append(f'Employee ID "{employee_id}" is already assigned.')
        if len(password) < 6:
            errors.append('Password must be at least 6 characters.')

        if errors:
            for error in errors:
                messages.error(request, error)
        else:
            try:
                with transaction.atomic():
                    user = User.objects.create_user(username=username, email=email, password=password, first_name=first_name, last_name=last_name, is_active=True, is_staff=True)
                    school = School.objects.get(id=school_id)
                    profile = user.profile
                    profile.role = 'schoolhead'
                    profile.school = school
                    profile.employee_number = employee_id or None
                    profile.designation = request.POST.get('designation', 'Principal')
                    profile.position_title = 'School Principal'
                    profile.employment_status = 'Regular_Permanent'
                    profile.save()
                    principal_group, _ = Group.objects.get_or_create(name='Principal')
                    user.groups.add(principal_group)
                    messages.success(request, f'✅ Principal "{user.get_full_name()}" created for {school.school_name}!')
                    return redirect('admin_panel:principal_list')
            except School.DoesNotExist:
                messages.error(request, 'School does not exist.')
            except Exception as e:
                messages.error(request, f'Error: {str(e)}')
    return render(request, 'admin/principal_create.html', {'schools': schools})


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
            messages.success(request, f'Password reset for "{principal.full_name}".')
        else:
            messages.error(request, 'Password must be at least 8 characters.')
    return redirect('admin_panel:principal_detail', principal_id=principal.id)


# =============================================================================
# GRADE LEVEL MANAGEMENT (FIXED: No is_active field)
# =============================================================================

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
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
    """Create grade levels (single or bulk)"""
    schools = School.objects.filter(is_active=True)
    
    if request.method == 'POST':
        if 'bulk_create' in request.POST:
            bulk_form = BulkGradeLevelForm(request.POST)
            if bulk_form.is_valid():
                school = bulk_form.cleaned_data['school']
                school_type = bulk_form.cleaned_data['school_type']

                grade_configs = {
                    'JHS': [(7, 'Grade 7', 'G7', 'JHS'),
                            (8, 'Grade 8', 'G8', 'JHS'),
                            (9, 'Grade 9', 'G9', 'JHS'),
                            (10, 'Grade 10', 'G10', 'JHS')],
                    'ELEMENTARY': [(i, f'Grade {i}', f'G{i}', 'ELEMENTARY') for i in range(1, 7)],
                    'SHS': [(11, 'Grade 11', 'G11', 'SHS'),
                            (12, 'Grade 12', 'G12', 'SHS')],
                    'INTEGRATED': [
                        (7, 'Grade 7', 'G7', 'JHS'),
                        (8, 'Grade 8', 'G8', 'JHS'),
                        (9, 'Grade 9', 'G9', 'JHS'),
                        (10, 'Grade 10', 'G10', 'JHS'),
                        (11, 'Grade 11', 'G11', 'SHS'),
                        (12, 'Grade 12', 'G12', 'SHS'),
                    ],
                }

                grades_list = grade_configs.get(school_type, [])
                if not grades_list:
                    messages.error(request, f'No grade configuration found for type: {school_type}')
                    return redirect('admin_panel:grade_level_create')

                created, skipped = 0, 0
                with transaction.atomic():
                    for grade_num, grade_name, grade_code, level_category in grades_list:
                        _, c = GradeLevel.objects.get_or_create(
                            school=school,
                            grade_name=grade_name,
                            grade_number=grade_num,
                            defaults={
                                'grade_code': grade_code,
                                'level_category': level_category,
                                'is_senior_high': (level_category == 'SHS'),
                            }
                        )
                        if c:
                            created += 1
                        else:
                            skipped += 1

                if created > 0:
                    messages.success(request, f'✅ {created} grade levels created for {school.school_name}! ({skipped} already existed)')
                else:
                    messages.info(request, f'All {skipped} grade levels already exist for {school.school_name}.')
                return redirect('admin_panel:grade_level_list')
            else:
                # Show bulk form errors
                for field, errors in bulk_form.errors.items():
                    for error in errors:
                        messages.error(request, f'Bulk form — {field}: {error}')
        else:
            # Single grade level creation
            form = GradeLevelForm(request.POST)
            if form.is_valid():
                grade_level = form.save()
                messages.success(request, f'Grade level "{grade_level.grade_name}" created for {grade_level.school.school_name}!')
                return redirect('admin_panel:grade_level_list')
            else:
                for field, errors in form.errors.items():
                    for error in errors:
                        messages.error(request, f'Single form — {field}: {error}')
    else:
        form = GradeLevelForm()
        bulk_form = BulkGradeLevelForm()

    return render(request, 'admin/grade_level_create.html', {
        'form': form,
        'bulk_form': bulk_form,
        'schools': schools,
    })

# ✅ REMOVED grade_level_toggle_status — GradeLevel has no is_active field


# =============================================================================
# SCHOOL YEAR & QUARTER MANAGEMENT
# =============================================================================

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_year_manage(request):
    """Manage school years"""
    if request.method == 'POST':
        form = SchoolYearForm(request.POST)
        if form.is_valid():
            sy = form.save()
            
            # Auto-create quarters if checked
            if request.POST.get('auto_create_quarters'):
                total_days = (sy.date_end - sy.date_start).days  # ✅ date_end, not end_date
                q_len = total_days // 4
                
                for i, label in enumerate(['Q1', 'Q2', 'Q3', 'Q4']):
                    start = sy.date_start + timedelta(days=q_len * i + (1 if i > 0 else 0))  # ✅
                    end = sy.date_end if i == 3 else sy.date_start + timedelta(days=q_len * (i + 1))  # ✅
                    Quarter.objects.get_or_create(
                        school_year=sy,
                        quarter_label=label,
                        defaults={
                            'date_start': start,  # ✅
                            'date_end': min(end, sy.date_end),  # ✅
                        }
                    )
                messages.success(request, f'School Year {sy.year_label} with 4 quarters created!')
            else:
                messages.success(request, f'School Year {sy.year_label} created for {sy.school.school_name}!')
            return redirect('admin_panel:school_year_manage')
        else:
            for field, errors in form.errors.items():
                for error in errors:
                    messages.error(request, f'{field}: {error}')
    else:
        form = SchoolYearForm()

    # Get all school years
    school_years = SchoolYear.objects.select_related('school').annotate(
        quarter_count=Count('quarters'),
    ).order_by('-date_start')  # ✅ date_start

    # Filter by school
    school_filter = request.GET.get('school', '')
    if school_filter:
        school_years = school_years.filter(school_id=school_filter)

    # Schools without any school year
    schools_with_sy = SchoolYear.objects.values_list('school_id', flat=True).distinct()
    schools_without_sy = School.objects.filter(is_active=True).exclude(id__in=schools_with_sy)

    context = {
        'form': form,
        'school_years': school_years,
        'schools': School.objects.filter(is_active=True),
        'selected_school': school_filter,
        'schools_without_sy': schools_without_sy,
        'current_school_years': school_years.filter(is_current=True),
    }
    return render(request, 'admin/school_year_manage.html', context)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_year_set_current(request, sy_id):
    sy = get_object_or_404(SchoolYear, id=sy_id)
    sy.is_current = True
    sy.save()
    messages.success(request, f'✅ {sy.year_label} set as current.')
    return redirect('admin_panel:school_year_manage')


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def school_year_delete(request, sy_id):
    if request.method == 'POST':
        get_object_or_404(SchoolYear, id=sy_id).delete()
        messages.success(request, 'School year deleted.')
    return redirect('admin_panel:school_year_manage')


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def quarter_manage(request):
    """Manage quarters"""
    if request.method == 'POST':
        form = QuarterForm(request.POST)
        if form.is_valid():
            q = form.save()
            messages.success(request, f'{q.get_quarter_label_display()} created!')
            return redirect('admin_panel:quarter_manage')
    else:
        form = QuarterForm()

    quarters = Quarter.objects.select_related('school_year__school').all().order_by('-school_year__date_start', 'quarter_label')

    # Filter by school year
    sy_filter = request.GET.get('school_year', '')
    if sy_filter:
        quarters = quarters.filter(school_year_id=sy_filter)

    # Filter by school
    school_filter = request.GET.get('school', '')
    if school_filter:
        quarters = quarters.filter(school_year__school_id=school_filter)

    # Incomplete school years
    incomplete_sy = SchoolYear.objects.select_related('school').annotate(
        q_count=Count('quarters')
    ).filter(q_count__lt=4, is_current=True)

    context = {
        'form': form,
        'quarters': quarters,
        'school_years': SchoolYear.objects.select_related('school').all().order_by('-date_start'),
        'schools': School.objects.filter(is_active=True),  # ✅ ADDED
        'selected_sy': sy_filter,
        'selected_school': school_filter,
        'incomplete_sy': incomplete_sy,
    }
    return render(request, 'admin/quarter_manage.html', context)

@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def quarter_bulk_create(request, sy_id):
    """Bulk create all 4 quarters for a school year"""
    sy = get_object_or_404(SchoolYear, id=sy_id)

    total_days = (sy.date_end - sy.date_start).days  # ✅
    q_len = total_days // 4

    created, skipped = 0, 0
    with transaction.atomic():
        for i, label in enumerate(['Q1', 'Q2', 'Q3', 'Q4']):
            start = sy.date_start + timedelta(days=q_len * i + (1 if i > 0 else 0))  # ✅
            end = sy.date_end if i == 3 else sy.date_start + timedelta(days=q_len * (i + 1))  # ✅
            _, c = Quarter.objects.get_or_create(
                school_year=sy,
                quarter_label=label,
                defaults={
                    'date_start': start,  # ✅
                    'date_end': min(end, sy.date_end),  # ✅
                }
            )
            if c:
                created += 1
            else:
                skipped += 1

    if created > 0:
        messages.success(request, f'✅ {created} quarters created for {sy.year_label}! ({skipped} already existed)')
    else:
        messages.info(request, f'All 4 quarters already exist for {sy.year_label}.')

    return redirect('admin_panel:quarter_manage')


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def quarter_delete(request, quarter_id):
    if request.method == 'POST':
        get_object_or_404(Quarter, id=quarter_id).delete()
        messages.success(request, 'Quarter deleted.')
    return redirect('admin_panel:quarter_manage')



@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def principal_edit(request, principal_id):
    principal = get_object_or_404(UserProfile, id=principal_id, role='schoolhead')
    if request.method == 'POST':
        principal.user.first_name = request.POST.get('first_name', principal.user.first_name)
        principal.user.last_name = request.POST.get('last_name', principal.user.last_name)
        principal.user.email = request.POST.get('email', principal.user.email)
        principal.employee_number = request.POST.get('employee_id', principal.employee_number)
        principal.designation = request.POST.get('designation', principal.designation)
        new_school_id = request.POST.get('school')
        if new_school_id:
            try:
                principal.school = School.objects.get(id=new_school_id)
            except School.DoesNotExist:
                pass
        principal.user.save()
        principal.save()
        messages.success(request, f'Principal "{principal.full_name}" updated!')
        return redirect('admin_panel:principal_detail', principal_id=principal.id)
    return render(request, 'admin/principal_edit.html', {
        'principal': principal,
        'schools': School.objects.filter(is_active=True),
    })


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
    sy = SchoolYear.objects.filter(school_id=school_id).values('id', 'year_label', 'is_current').order_by('-start_date')
    return JsonResponse(list(sy), safe=False)


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def check_school_id(request):
    return JsonResponse({'exists': School.objects.filter(school_id=request.GET.get('school_id', '')).exists()})


@login_required
@user_passes_test(is_admin, login_url='admin_panel:login')
def check_username(request):
    return JsonResponse({'exists': User.objects.filter(username=request.GET.get('username', '')).exists()})