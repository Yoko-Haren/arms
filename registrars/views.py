from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib.auth.models import User, Group
from django.contrib import messages
from django.http import HttpResponse, JsonResponse
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.db import transaction
from django.db.models import Max, Count
from datetime import date
from functools import wraps
import csv
import io
import json
import secrets

from accounts.models import UserProfile
from academics.models import School, SchoolYear, Quarter, Section, GradeLevel, Subject, Semester
from scheduling.models import ClassAssignment, ClassSchedule
from enrollment.models import Enrollment
from students.models import Student
from grades.models import GradeComponent

from core.caching import cache_page_for_user, remember_filters

from .forms import TeacherAccountForm, school_email_domain, suggest_teacher_email

ACTIVE_ENROLLMENT = ['Enrolled', 'Transferred_In']
MAX_UPLOAD_BYTES = 1024 * 1024  # class lists and teacher lists are small text files


# =============================================================================
# SHARED HELPERS
# =============================================================================

def registrar_required(view):
    """Only signed-in registrars may open the registrar portal."""
    @login_required
    @wraps(view)
    def wrapper(request, *args, **kwargs):
        profile = getattr(request.user, 'profile', None)
        if not profile or profile.role != 'registrar':
            messages.error(request, 'Access denied.')
            return redirect('signin')
        return view(request, *args, **kwargs)
    return wrapper


def _current_school_year(school):
    return SchoolYear.objects.filter(school=school, is_current=True).first()


def _log(request, action_type, resource_id, description, resource_type='UserProfile'):
    try:
        from audit.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user,
            user_name=request.user.get_full_name() or request.user.username,
            user_role='registrar', action_type=action_type,
            resource_type=resource_type, resource_id=str(resource_id),
            details_json={'description': description},
            ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
    except Exception:
        pass


def _read_upload(request, field='csv_file'):
    """Text of an uploaded CSV, or (None, error)."""
    upload = request.FILES.get(field)
    if not upload:
        return None, 'Please select a CSV file.'
    if upload.size > MAX_UPLOAD_BYTES:
        return None, 'That file is too large. CSV files here should be under 1 MB.'
    try:
        return upload.read().decode('utf-8-sig'), None
    except UnicodeDecodeError:
        return None, 'That file is not a readable CSV. Save it as "CSV UTF-8" and try again.'


def _teacher_options(school, current_sy):
    """Active teachers of the school with their weekly load, lightest first.

    Load uses the class schedule when one exists, otherwise the assignment's
    meetings per week x minutes per meeting.
    """
    teachers = list(
        UserProfile.objects.filter(role='teacher', school=school, is_active=True, user__is_active=True)
        .select_related('user')
    )
    load = {t.user_id: {'classes': 0, 'minutes': 0} for t in teachers}
    if current_sy:
        scheduled_minutes = {}
        for row in ClassSchedule.objects.filter(
            class_assignment__school_year=current_sy, class_assignment__section__school=school,
            class_assignment__is_active=True, is_active=True,
        ).values('class_assignment_id', 'duration_minutes'):
            scheduled_minutes[row['class_assignment_id']] = (
                scheduled_minutes.get(row['class_assignment_id'], 0) + (row['duration_minutes'] or 0)
            )
        for a in ClassAssignment.objects.filter(school_year=current_sy, section__school=school, is_active=True):
            if a.teacher_id not in load:
                continue
            load[a.teacher_id]['classes'] += 1
            load[a.teacher_id]['minutes'] += scheduled_minutes.get(a.id) or (a.minutes_per_meeting * a.meetings_per_week)

    options = []
    for t in teachers:
        info = load[t.user_id]
        hours = round(info['minutes'] / 60, 1)
        options.append({
            'user_id': t.user_id,
            'name': t.full_name,
            'classes': info['classes'],
            'hours': int(hours) if hours == int(hours) else hours,
            'minutes': info['minutes'],
        })
    options.sort(key=lambda o: (o['minutes'], o['classes'], o['name'].lower()))
    for i, option in enumerate(options):
        option['most_available'] = i == 0 and len(options) > 1
    return options


def _school_teacher_user(school, user_id):
    """An active teacher account of this school, by auth user id."""
    if not str(user_id).isdigit():
        return None
    profile = UserProfile.objects.filter(
        user_id=user_id, role='teacher', school=school, is_active=True, user__is_active=True
    ).select_related('user').first()
    return profile.user if profile else None


def _assign_class(section, subject, teacher, current_sy, created_by=None):
    """Give a class (section + subject) to a teacher; whoever had it before is released."""
    with transaction.atomic():
        ClassAssignment.objects.filter(
            section=section, subject=subject, school_year=current_sy, is_active=True
        ).exclude(teacher=teacher).update(is_active=False)
        assignment = ClassAssignment.objects.filter(
            teacher=teacher, section=section, subject=subject, school_year=current_sy
        ).first()
        if not assignment:
            assignment = ClassAssignment.objects.create(
                teacher=teacher, section=section, subject=subject, school_year=current_sy,
                is_active=True, created_by=created_by,
            )
        elif not assignment.is_active:
            assignment.is_active = True
            assignment.save(update_fields=['is_active', 'updated_at'])
    return assignment


# =============================================================================
# DASHBOARD
# =============================================================================

@registrar_required
@cache_page_for_user()
def dashboard(request):
    """Registrar Dashboard."""
    school = request.user.profile.school
    current_sy = _current_school_year(school)

    total_students = Enrollment.objects.filter(
        school_year=current_sy, status__in=ACTIVE_ENROLLMENT, section__school=school
    ).count() if current_sy else 0
    total_sections = Section.objects.filter(
        school=school, school_year=current_sy, is_active=True
    ).count() if current_sy else 0
    total_teachers = UserProfile.objects.filter(role='teacher', school=school, is_active=True).count()
    total_subjects = Subject.objects.filter(school=school, is_active=True).count()

    # Teachers who cannot see any class yet (no active assignment this school year)
    assigned_teacher_ids = ClassAssignment.objects.filter(
        school_year=current_sy, section__school=school, is_active=True
    ).values_list('teacher_id', flat=True) if current_sy else []
    teachers_without_classes = UserProfile.objects.filter(
        role='teacher', school=school, is_active=True
    ).exclude(user_id__in=assigned_teacher_ids).count()

    recent_enrollments = Enrollment.objects.filter(
        section__school=school, school_year=current_sy
    ).select_related('student', 'section').order_by('-created_at')[:10] if current_sy else []

    current_period = Quarter.objects.filter(school_year=current_sy, is_current_quarter=True).first() if current_sy else None

    context = {
        'school': school,
        'current_sy': current_sy,
        'current_period': current_period,
        'total_students': total_students,
        'total_sections': total_sections,
        'total_teachers': total_teachers,
        'total_subjects': total_subjects,
        'teachers_without_classes': teachers_without_classes,
        'recent_enrollments': recent_enrollments,
        'today': date.today(),
    }
    return render(request, 'registrars/dashboard.html', context)


# =============================================================================
# CLASS LIST UPLOAD  (upload -> preview -> confirm)
# =============================================================================

def _parse_class_list(text):
    """Read the registrar's class list CSV into header details and student rows."""
    lines = text.replace('\r\n', '\n').split('\n')
    header_info = {}
    student_start_row = None

    for i, line in enumerate(lines):
        line = line.strip()
        if not line:
            continue

        if 'LIST OF STUDENTS' in line.upper():
            parts = [p.strip().strip('"') for p in line.split(',')]
            if len(parts) >= 2 and parts[1]:
                header_info['semester'] = parts[1]
            if len(parts) >= 3 and parts[2]:
                header_info['school_year'] = parts[2]
            continue

        if 'Student No.' in line:
            student_start_row = i + 1
            break

        parts = [p.strip().strip('"') for p in line.split(',')]
        parts_clean = [p for p in parts if p]

        if len(parts_clean) >= 2:
            for j, part in enumerate(parts_clean):
                if part == 'Program' and j + 1 < len(parts_clean):
                    header_info['program'] = parts_clean[j + 1]
                elif part == 'Subject Code' and j + 1 < len(parts_clean):
                    header_info['subject_code'] = parts_clean[j + 1]
                elif part == 'Year' and j + 1 < len(parts_clean):
                    header_info['year_level'] = parts_clean[j + 1]
                elif part == 'Section' and j + 1 < len(parts_clean):
                    header_info['section_name'] = parts_clean[j + 1]
                elif part == 'Subject Title' and j + 1 < len(parts_clean):
                    header_info['subject_name'] = parts_clean[j + 1]
                elif part == 'Instructor' and j + 1 < len(parts_clean):
                    header_info['instructor_name'] = parts_clean[j + 1]
                elif part == 'Time and Days' and j + 1 < len(parts_clean):
                    header_info['schedule'] = parts_clean[j + 1]
                elif 'Semester' in part and j + 1 < len(parts_clean):
                    header_info['semester'] = parts_clean[j + 1]
                elif 'Hours' in part and j + 1 < len(parts_clean):
                    header_info['hours_per_week'] = parts_clean[j + 1]

    students = []
    if student_start_row is not None:
        for row in csv.reader(lines[student_start_row:]):
            if len(row) < 2:
                continue
            student_id, student_name = row[0].strip(), row[1].strip()
            if not student_id or not student_name:
                continue
            name_parts = student_name.split(',')
            students.append({
                'student_id': student_id,
                'last_name': name_parts[0].strip(),
                'first_name': name_parts[1].strip() if len(name_parts) > 1 else '',
            })

    year_level = header_info.get('year_level', '1st')
    digits = ''.join(filter(str.isdigit, year_level))
    grade_number = int(digits) if digits else 1

    return {
        'header': header_info,
        'students': students,
        'has_student_header': student_start_row is not None,
        'section_name': header_info.get('section_name', 'Default'),
        'subject_code': header_info.get('subject_code', 'UNKNOWN')[:25],
        'subject_name': header_info.get('subject_name', 'Unknown Subject')[:200],
        'instructor_name': header_info.get('instructor_name', ''),
        'grade_number': grade_number,
        'grade_name': f'Grade {grade_number}',
    }


def _match_instructor(school, instructor_name):
    """Teacher account whose first and last name appear in the CSV instructor name."""
    name_parts = instructor_name.split()
    if len(name_parts) < 2:
        return None
    profile = UserProfile.objects.filter(
        role='teacher', school=school, is_active=True,
        user__first_name__icontains=name_parts[0],
        user__last_name__icontains=name_parts[-1],
    ).select_related('user').first()
    return profile.user if profile else None


def _find_class_records(school, current_sy, parsed):
    """What the class list refers to that already exists (nothing is written)."""
    grade_level = GradeLevel.objects.filter(school=school, grade_number=parsed['grade_number']).first()
    subject = Subject.objects.filter(subject_code=parsed['subject_code'], school=school).first()
    section = Section.objects.filter(
        section_name__iexact=parsed['section_name'], school=school,
        school_year=current_sy, grade_level=grade_level,
    ).first() if grade_level else None
    return grade_level, subject, section


def _preview_class_list(school, current_sy, parsed):
    """Describe what importing the class list would do."""
    grade_level, subject, section = _find_class_records(school, current_sy, parsed)

    ids = [s['student_id'] for s in parsed['students']]
    known = set(Student.objects.filter(lrn__in=ids).values_list('lrn', flat=True))
    enrolled = {
        e.student.lrn: e for e in Enrollment.objects.filter(
            student__lrn__in=ids, school_year=current_sy
        ).select_related('student', 'section')
    }
    counts = {'new': 0, 'existing': 0, 'elsewhere': 0, 'duplicate': 0}
    seen = set()
    rows = []
    for s in parsed['students']:
        enrollment = enrolled.get(s['student_id'])
        if s['student_id'] in seen:
            state, note = 'duplicate', 'Listed twice in this file'
        elif enrollment and section and enrollment.section_id == section.id:
            state, note = 'existing', 'Already in this section'
        elif enrollment:
            state, note = 'elsewhere', f'Already enrolled in {enrollment.section.section_name} — stays there'
        elif s['student_id'] in known:
            state, note = 'new', 'Existing student — will be enrolled'
        else:
            state, note = 'new', 'New student — will be created and enrolled'
        seen.add(s['student_id'])
        counts[state] += 1
        rows.append({**s, 'state': state, 'note': note})

    return {
        'grade_level': grade_level,
        'subject': subject,
        'section': section,
        'rows': rows,
        'counts': counts,
        'matched_teacher': _match_instructor(school, parsed['instructor_name']) if parsed['instructor_name'] else None,
    }


def _import_class_list(request, school, current_sy, parsed, teacher_user):
    """Create/update the section, subject, class assignment and enrollments."""
    grade_level, subject, section = _find_class_records(school, current_sy, parsed)
    grade_number = parsed['grade_number']

    with transaction.atomic():
        if not grade_level:
            max_sort = GradeLevel.objects.aggregate(Max('sort_order'))['sort_order__max'] or 0
            max_num = GradeLevel.objects.aggregate(Max('grade_number'))['grade_number__max'] or 0
            grade_level = GradeLevel.objects.create(
                school=school,
                grade_code=f"G{grade_number}",
                grade_name=parsed['grade_name'],
                grade_number=grade_number if not GradeLevel.objects.filter(grade_number=grade_number).exists() else max_num + 1,
                level_category='SHS' if grade_number <= 12 else 'COLLEGE',
                is_senior_high=grade_number <= 12,
                sort_order=max_sort + 1,
            )

        if not subject:
            subject = Subject.objects.create(
                subject_code=parsed['subject_code'], school=school,
                subject_name=parsed['subject_name'], grade_level=grade_level, is_active=True,
            )

        action = 'updated'
        if not section:
            section = Section.objects.create(
                section_name=parsed['section_name'][:60], school=school,
                grade_level=grade_level, school_year=current_sy, is_active=True,
            )
            action = 'created'

        if teacher_user:
            _assign_class(section, subject, teacher_user, current_sy, created_by=request.user)

        new_count = existing_count = elsewhere_count = 0
        error_rows = []
        seen = set()
        for s in parsed['students']:
            if s['student_id'] in seen:
                continue
            seen.add(s['student_id'])
            try:
                with transaction.atomic():
                    student, _ = Student.objects.update_or_create(
                        lrn=s['student_id'],
                        defaults={'first_name': s['first_name'][:100], 'last_name': s['last_name'][:100]},
                    )
                    # A student has one enrollment per school year
                    enrollment = Enrollment.objects.filter(student=student, school_year=current_sy).first()
                    if enrollment and enrollment.section_id == section.id:
                        if enrollment.status not in ACTIVE_ENROLLMENT:
                            enrollment.status = 'Enrolled'
                            enrollment.save()
                        existing_count += 1
                    elif enrollment:
                        elsewhere_count += 1
                    else:
                        Enrollment.objects.create(
                            student=student, section=section, school_year=current_sy,
                            status='Enrolled', created_by=request.user,
                        )
                        new_count += 1
            except Exception as e:
                error_rows.append(f"Student {s['student_id']}: {e}")

        section.current_enrollment_count = Enrollment.objects.filter(
            section=section, school_year=current_sy, status__in=ACTIVE_ENROLLMENT
        ).count()
        section.save()

    return {
        'section': section, 'subject': subject, 'action': action,
        'new': new_count, 'existing': existing_count, 'elsewhere': elsewhere_count, 'errors': error_rows,
    }


@registrar_required
def upload_class_list(request):
    """Upload a class list CSV, review what it will do, then confirm the import."""
    school = request.user.profile.school
    current_sy = _current_school_year(school)

    if not current_sy:
        messages.error(request, 'No active school year.')
        return redirect('registrars:dashboard')

    if request.method == 'POST':
        confirming = request.POST.get('action') == 'confirm'
        if confirming:
            text, error = request.POST.get('payload', ''), None
            if not text.strip() or len(text.encode('utf-8')) > MAX_UPLOAD_BYTES:
                error = 'The class list could not be read again. Please upload it once more.'
        else:
            text, error = _read_upload(request)

        parsed = _parse_class_list(text) if not error else None
        if parsed and not parsed['has_student_header']:
            error = 'This file has no "Student No." header row, so the student list could not be found.'
        elif parsed and not parsed['students']:
            error = 'No students were found under the "Student No." header.'
        elif parsed and 'section_name' not in parsed['header']:
            error = 'The file does not name a Section. Check the "Year, …, Section, …" row.'
        elif parsed and 'subject_code' not in parsed['header']:
            error = 'The file does not name a Subject Code. Check the "Program, …, Subject Code, …" row.'

        if error:
            messages.error(request, error)
            return redirect('registrars:upload_class_list')

        if not confirming:
            preview = _preview_class_list(school, current_sy, parsed)
            return render(request, 'registrars/class_list/preview.html', {
                'current_sy': current_sy,
                'parsed': parsed,
                'preview': preview,
                'payload': text,
                'teacher_options': _teacher_options(school, current_sy),
                'file_name': request.FILES['csv_file'].name,
            })

        # ----- confirmed: import -----
        choice = request.POST.get('teacher', '')
        teacher_user = _school_teacher_user(school, choice)
        try:
            result = _import_class_list(request, school, current_sy, parsed, teacher_user)
        except Exception as e:
            messages.error(request, f'Error processing file: {e}')
            return redirect('registrars:upload_class_list')

        section, subject = result['section'], result['subject']
        summary = (
            f'Section "{section.section_name}" {result["action"]} for {subject.subject_code}: '
            f'{result["new"]} enrolled, {result["existing"]} already in the section'
        )
        if result['elsewhere']:
            summary += f', {result["elsewhere"]} left in their current section'
        summary += '.'
        if teacher_user:
            summary += f' Assigned to {teacher_user.get_full_name() or teacher_user.username}.'
        messages.success(request, summary)
        _log(request, 'IMPORT', section.id, f'Class list import: {subject.subject_code} — {section.section_name}', 'Section')

        if result['errors']:
            detail = '; '.join(result['errors'][:3])
            if len(result['errors']) > 3:
                detail += f' ... and {len(result["errors"]) - 3} more'
            messages.warning(request, f'{len(result["errors"])} row(s) could not be imported: {detail}')

        if choice == 'new':
            # Create the instructor's account next; it is assigned to this class on save.
            first, last = _split_instructor_name(parsed['instructor_name'])
            query = urlencode({'first_name': first, 'last_name': last, 'section': section.id, 'subject': subject.id})
            return redirect(f"{reverse('registrars:teacher_create')}?{query}")
        if not teacher_user:
            messages.warning(request, f'{subject.subject_code} in {section.section_name} has no teacher yet. Assign one below.')
        return redirect('registrars:section_detail', section_id=section.id)

    return render(request, 'registrars/class_list/upload.html', {'current_sy': current_sy})


# =============================================================================
# SECTIONS
# =============================================================================

@registrar_required
@cache_page_for_user()
def section_list(request):
    """View all sections with enrollment counts and teacher assignments."""
    school = request.user.profile.school
    current_sy = _current_school_year(school)

    sections = Section.objects.filter(
        school=school, school_year=current_sy,
    ).select_related('grade_level').order_by('grade_level__sort_order', 'section_name')

    enrolled = dict(
        Enrollment.objects.filter(section__in=sections, school_year=current_sy, status__in=ACTIVE_ENROLLMENT)
        .values_list('section_id').annotate(total=Count('id'))
    )
    by_section = {}
    for a in ClassAssignment.objects.filter(
        section__in=sections, school_year=current_sy, is_active=True
    ).select_related('teacher', 'subject'):
        by_section.setdefault(a.section_id, []).append(a)

    section_data = []
    for s in sections:
        enrolled_count = enrolled.get(s.id, 0)
        teachers_list, subjects_list, seen_teachers = [], [], set()
        for a in by_section.get(s.id, []):
            if a.teacher_id not in seen_teachers:
                teachers_list.append({'name': a.teacher.get_full_name() or a.teacher.username, 'email': a.teacher.email})
                seen_teachers.add(a.teacher_id)
            subjects_list.append({'code': a.subject.subject_code, 'name': a.subject.subject_name})

        section_data.append({
            'section': s,
            'enrolled_count': enrolled_count,
            'max_capacity': s.max_capacity,
            'teachers': teachers_list,
            'subjects': subjects_list,
            'is_full': enrolled_count >= s.max_capacity if s.max_capacity > 0 else False,
            'is_empty': enrolled_count == 0,
        })

    total_sections = len(section_data)
    sections_with_students = sum(1 for s in section_data if s['enrolled_count'] > 0)
    context = {
        'sections': section_data,
        'current_sy': current_sy,
        'total_sections': total_sections,
        'sections_with_students': sections_with_students,
        'sections_empty': total_sections - sections_with_students,
        'total_enrolled': sum(s['enrolled_count'] for s in section_data),
        'sections_without_teacher': sum(1 for s in section_data if not s['teachers']),
    }
    return render(request, 'registrars/sections/list.html', context)


def _school_section(request, section_id):
    return get_object_or_404(
        Section.objects.select_related('grade_level', 'school_year', 'adviser'),
        id=section_id, school=request.user.profile.school,
    )


@registrar_required
def section_detail(request, section_id):
    """Roster, classes and teacher assignment for one section."""
    school = request.user.profile.school
    section = _school_section(request, section_id)
    sy = section.school_year

    if request.method == 'POST':
        action = request.POST.get('action')

        if action in ('assign_teacher', 'add_class'):
            teacher = _school_teacher_user(school, request.POST.get('teacher'))
            subject_id = request.POST.get('subject', '')
            subject = Subject.objects.filter(id=subject_id, school=school).first() if subject_id.isdigit() else None
            if not teacher:
                messages.error(request, 'Choose an active teacher of your school.')
            elif not subject:
                messages.error(request, 'Choose a subject.')
            else:
                _assign_class(section, subject, teacher, sy, created_by=request.user)
                _log(request, 'ASSIGN_TEACHER', section.id,
                     f'{teacher.username} -> {subject.subject_code} — {section.section_name}', 'Section')
                messages.success(request, f'{subject.subject_code} is now handled by {teacher.get_full_name() or teacher.username}.')

        elif action == 'remove_class':
            assignment_id = request.POST.get('assignment', '')
            assignment = ClassAssignment.objects.filter(
                id=assignment_id, section=section, school_year=sy, is_active=True
            ).select_related('subject').first() if assignment_id.isdigit() else None
            if assignment:
                assignment.is_active = False
                assignment.save(update_fields=['is_active', 'updated_at'])
                messages.success(request, f"{assignment.subject.subject_code} removed from this section's classes.")

        elif action == 'set_adviser':
            adviser_id = request.POST.get('teacher')
            adviser = _school_teacher_user(school, adviser_id) if adviser_id else None
            if adviser_id and not adviser:
                messages.error(request, 'Choose an active teacher of your school.')
            else:
                section.adviser = adviser
                section.save(update_fields=['adviser'])
                messages.success(request, f'Adviser set to {adviser.get_full_name()}.' if adviser else 'Adviser cleared.')

        elif action in ('move_student', 'drop_student', 'restore_student'):
            enrollment_id = request.POST.get('enrollment', '')
            enrollment = Enrollment.objects.filter(
                id=enrollment_id, section=section, school_year=sy
            ).select_related('student').first() if enrollment_id.isdigit() else None
            if not enrollment:
                messages.error(request, 'That student is not in this section.')
            elif action == 'move_student':
                target_id = request.POST.get('target', '')
                target = Section.objects.filter(
                    id=target_id, school=school, school_year=sy
                ).exclude(id=section.id).first() if target_id.isdigit() else None
                if not target:
                    messages.error(request, 'Choose a section to move the student to.')
                else:
                    enrollment.section = target
                    enrollment.updated_by = request.user
                    enrollment.save()
                    # Enrollment.save() only refreshes the count of the new section
                    Section.objects.filter(id=section.id).update(current_enrollment_count=Enrollment.objects.filter(
                        section=section, status__in=ACTIVE_ENROLLMENT).count())
                    _log(request, 'MOVE_STUDENT', enrollment.id,
                         f'{enrollment.student.lrn}: {section.section_name} -> {target.section_name}', 'Enrollment')
                    messages.success(request, f'{enrollment.student.last_name}, {enrollment.student.first_name} moved to {target.section_name}.')
            else:
                new_status = 'Dropped' if action == 'drop_student' else 'Enrolled'
                enrollment.updated_by = request.user
                enrollment.set_status(new_status, changed_by=request.user, reason=request.POST.get('reason', '').strip()[:255])
                _log(request, 'UPDATE_ENROLLMENT', enrollment.id, f'{enrollment.student.lrn} -> {new_status}', 'Enrollment')
                verb = 'dropped from' if new_status == 'Dropped' else 'restored to'
                messages.success(request, f'{enrollment.student.last_name}, {enrollment.student.first_name} {verb} {section.section_name}.')

        return redirect('registrars:section_detail', section_id=section.id)

    enrollments = list(
        Enrollment.objects.filter(section=section, school_year=sy)
        .select_related('student').order_by('student__last_name', 'student__first_name')
    )
    assignments = list(
        ClassAssignment.objects.filter(section=section, school_year=sy, is_active=True)
        .select_related('teacher', 'subject').order_by('subject__subject_code')
    )
    teacher_options = _teacher_options(school, sy)
    load = {o['user_id']: o for o in teacher_options}
    for a in assignments:
        a.teacher_load = load.get(a.teacher_id)

    assigned_subject_ids = {a.subject_id for a in assignments}
    active_count = sum(1 for e in enrollments if e.status in ACTIVE_ENROLLMENT)
    return render(request, 'registrars/sections/detail.html', {
        'section': section,
        'current_sy': sy,
        'enrollments': enrollments,
        'active_count': active_count,
        'inactive_count': len(enrollments) - active_count,
        'assignments': assignments,
        'teacher_options': teacher_options,
        'available_subjects': Subject.objects.filter(school=school, is_active=True)
            .exclude(id__in=assigned_subject_ids).order_by('subject_code'),
        'other_sections': Section.objects.filter(school=school, school_year=sy, is_active=True)
            .exclude(id=section.id).order_by('grade_level__sort_order', 'section_name'),
    })


# =============================================================================
# TEACHER ACCOUNTS
# =============================================================================

def _split_instructor_name(full_name):
    """'Gertrude Grace M Tampus' -> ('Gertrude Grace', 'Tampus'); middle initials are dropped."""
    parts = full_name.replace(',', ' ').split()
    if len(parts) < 2:
        return full_name.strip(), ''
    given = [p for p in parts[:-1] if len(p.strip('.')) > 1] or parts[:1]
    return ' '.join(given), parts[-1]


def _school_teacher(request, profile_id):
    return get_object_or_404(
        UserProfile.objects.select_related('user'),
        id=profile_id, role='teacher', school=request.user.profile.school,
    )


def _pending_class(request, school, current_sy):
    """Section + subject a new teacher should be assigned to (set by the class list upload)."""
    data = request.POST if request.method == 'POST' else request.GET
    section_id, subject_id = data.get('section'), data.get('subject')
    if not (current_sy and str(section_id).isdigit() and str(subject_id).isdigit()):
        return None
    section = Section.objects.filter(id=section_id, school=school, school_year=current_sy).first()
    subject = Subject.objects.filter(id=subject_id, school=school).first()
    return {'section': section, 'subject': subject} if section and subject else None


def _create_teacher(school, data):
    """Create a teacher account from cleaned TeacherAccountForm data.

    Returns (user, profile, temporary password). The teacher must replace the
    temporary password at first sign-in.
    """
    password = secrets.token_urlsafe(9)
    with transaction.atomic():
        user = User.objects.create_user(
            username=data['email'], email=data['email'], password=password,
            first_name=data['first_name'], last_name=data['last_name'],
        )
        profile = user.profile  # created by the post_save signal
        profile.role = 'teacher'
        profile.school = school
        profile.employee_number = data['employee_number'] or None
        profile.designation = data['designation'] or 'Teacher'
        profile.position_title = data['designation'] or 'Teacher'
        profile.teaching_area = data['teaching_area']
        profile.employment_status = 'Regular_Permanent'
        profile.institutional_email = data['email']
        profile.must_change_password = True
        if data['email'].endswith('@deped.gov.ph'):
            profile.deped_email = data['email']
        profile.save()
        user.groups.add(Group.objects.get_or_create(name='Teacher')[0])
    return user, profile, password


@registrar_required
@cache_page_for_user()
def teacher_list(request):
    """Teacher accounts of the registrar's school with their classes this school year."""
    school = request.user.profile.school
    current_sy = _current_school_year(school)

    teachers = list(
        UserProfile.objects.filter(role='teacher', school=school)
        .select_related('user').order_by('-is_active', 'user__last_name', 'user__first_name')
    )
    classes = {}
    if current_sy:
        assignments = ClassAssignment.objects.filter(
            school_year=current_sy, section__school=school, is_active=True
        ).select_related('section', 'subject')
        for a in assignments:
            classes.setdefault(a.teacher_id, []).append(f'{a.subject.subject_code} — {a.section.section_name}')
    load = {o['user_id']: o for o in _teacher_options(school, current_sy)}
    for t in teachers:
        t.classes = classes.get(t.user_id, [])
        t.account_active = t.is_active and t.user.is_active
        t.load = load.get(t.user_id)

    active = [t for t in teachers if t.account_active]
    return render(request, 'registrars/teachers/list.html', {
        'teachers': teachers,
        'current_sy': current_sy,
        'total_teachers': len(teachers),
        'active_teachers': len(active),
        'inactive_teachers': len(teachers) - len(active),
        'without_classes': sum(1 for t in active if not t.classes),
        'pending_password': sum(1 for t in active if t.must_change_password),
    })


@registrar_required
def teacher_create(request):
    """Create a teacher account for the registrar's own school."""
    school = request.user.profile.school
    current_sy = _current_school_year(school)
    pending = _pending_class(request, school, current_sy)

    form = TeacherAccountForm(request.POST or None, school=school, initial={
        'first_name': request.GET.get('first_name', ''),
        'last_name': request.GET.get('last_name', ''),
        'designation': 'Teacher',
    })
    if request.method == 'POST' and form.is_valid():
        user, profile, password = _create_teacher(school, form.cleaned_data)
        assigned = ''
        if pending:
            _assign_class(pending['section'], pending['subject'], user, current_sy, created_by=request.user)
            assigned = f" and assigned to {pending['subject'].subject_code} in {pending['section'].section_name}"

        _log(request, 'CREATE_USER', profile.id, f'Created teacher account {user.username}{assigned}')
        messages.success(
            request,
            f'Teacher account created for {user.get_full_name()}{assigned}. '
            f'Username: {user.username} — Temporary password: {password} '
            '(shown only once; the teacher sets their own password at first sign-in).'
        )
        if pending:
            return redirect('registrars:section_detail', section_id=pending['section'].id)
        return redirect('registrars:teacher_list')

    return render(request, 'registrars/teachers/create.html', {
        'form': form,
        'school': school,
        'email_domain': school_email_domain(school),
        'pending': pending,
    })


TEACHER_IMPORT_COLUMNS = ['first_name', 'last_name', 'email', 'employee_number', 'position', 'teaching_area']


def _teacher_import_rows(school, raw_rows):
    """Validate teacher rows as one batch (addresses and employee numbers must not collide)."""
    reserved, seen_employee, results = set(), set(), []
    for raw in raw_rows:
        data = {
            'first_name': raw.get('first_name', ''),
            'last_name': raw.get('last_name', ''),
            'email': raw.get('email', ''),
            'employee_number': raw.get('employee_number', ''),
            'designation': raw.get('position', '') or raw.get('designation', ''),
            'teaching_area': raw.get('teaching_area', ''),
        }
        data = {k: str(v or '').strip() for k, v in data.items()}
        form = TeacherAccountForm(data, school=school, reserved=reserved)
        errors = []
        if form.is_valid():
            cleaned = form.cleaned_data
            if cleaned['employee_number'] and cleaned['employee_number'] in seen_employee:
                errors.append('Employee number repeated in this file.')
            else:
                reserved.add(cleaned['email'])
                if cleaned['employee_number']:
                    seen_employee.add(cleaned['employee_number'])
        else:
            for field, field_errors in form.errors.items():
                label = '' if field == '__all__' else f'{field.replace("_", " ").capitalize()}: '
                errors.extend(f'{label}{e}' for e in field_errors)
        results.append({
            'data': data,
            'cleaned': form.cleaned_data if not errors else None,
            'email': form.cleaned_data.get('email', '') if not errors else data['email'],
            'generated': not errors and not data['email'],
            'errors': errors,
        })
    return results


@registrar_required
def teacher_import(request):
    """Create many teacher accounts from a CSV: upload -> preview -> confirm -> credentials."""
    school = request.user.profile.school

    if request.GET.get('template'):
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="teachers_template.csv"'
        writer = csv.writer(response)
        writer.writerow(TEACHER_IMPORT_COLUMNS)
        writer.writerow(['Maria Clara', 'Dela Cruz', '', 'EMP-0001', 'Teacher II', 'Mathematics'])
        writer.writerow(['Jose', 'Rizal', 'jose.rizal@example.com', '', 'Teacher I', 'Filipino'])
        return response

    if request.method == 'POST' and request.POST.get('action') == 'confirm':
        try:
            raw_rows = json.loads(request.POST.get('payload', '[]'))
            if not (isinstance(raw_rows, list) and all(isinstance(r, dict) for r in raw_rows)):
                raise ValueError
        except ValueError:
            messages.error(request, 'The teacher list could not be read again. Please upload it once more.')
            return redirect('registrars:teacher_import')

        created, skipped = [], []
        with transaction.atomic():
            for row in _teacher_import_rows(school, raw_rows[:500]):
                if row['errors']:
                    skipped.append(row)
                    continue
                user, profile, password = _create_teacher(school, row['cleaned'])
                created.append({'name': user.get_full_name(), 'username': user.username, 'password': password})
        if created:
            _log(request, 'CREATE_USER', '', f'Bulk import created {len(created)} teacher accounts')
        return render(request, 'registrars/teachers/import_result.html', {
            'created': created, 'skipped': skipped, 'school': school,
        })

    if request.method == 'POST':
        text, error = _read_upload(request)
        rows = []
        if not error:
            reader = csv.DictReader(io.StringIO(text))
            headers = [(h or '').strip().lower().replace(' ', '_') for h in (reader.fieldnames or [])]
            if 'first_name' not in headers or 'last_name' not in headers:
                error = 'The file needs first_name and last_name columns. Download the template to see the format.'
            else:
                reader.fieldnames = headers
                for row in reader:
                    clean = {k: (v or '').strip() for k, v in row.items() if k and isinstance(v, str)}
                    if any(clean.values()):
                        rows.append(clean)
                if not rows:
                    error = 'No teachers were found in the file.'
                elif len(rows) > 500:
                    error = 'Please import at most 500 teachers at a time.'
        if error:
            messages.error(request, error)
            return redirect('registrars:teacher_import')

        results = _teacher_import_rows(school, rows)
        return render(request, 'registrars/teachers/import_preview.html', {
            'results': results,
            'ready_count': sum(1 for r in results if not r['errors']),
            'error_count': sum(1 for r in results if r['errors']),
            'payload': json.dumps(rows),
            'file_name': request.FILES['csv_file'].name,
            'school': school,
        })

    return render(request, 'registrars/teachers/import.html', {
        'school': school, 'email_domain': school_email_domain(school), 'columns': TEACHER_IMPORT_COLUMNS,
    })


@registrar_required
def teacher_reset_password(request, profile_id):
    if request.method == 'POST':
        teacher = _school_teacher(request, profile_id)
        password = secrets.token_urlsafe(9)
        teacher.user.set_password(password)
        teacher.user.save()
        teacher.must_change_password = True
        teacher.save(update_fields=['must_change_password', 'updated_at'])
        _log(request, 'RESET_PASSWORD', teacher.id, f'Reset password of {teacher.user.username}')
        messages.success(
            request,
            f'Password reset for {teacher.full_name}. Username: {teacher.user.username} — '
            f'Temporary password: {password} (shown only once; they set their own at next sign-in).'
        )
    return redirect('registrars:teacher_list')


@registrar_required
def teacher_toggle_status(request, profile_id):
    if request.method == 'POST':
        teacher = _school_teacher(request, profile_id)
        teacher.is_active = not (teacher.is_active and teacher.user.is_active)
        teacher.user.is_active = teacher.is_active
        teacher.user.save()
        teacher.save()
        state = 'activated' if teacher.is_active else 'deactivated'
        _log(request, 'UPDATE_USER', teacher.id, f'{state.capitalize()} teacher account {teacher.user.username}')
        messages.success(request, f'{teacher.full_name} {state}.')
    return redirect('registrars:teacher_list')


@registrar_required
def teacher_email_preview(request):
    """Email the system would generate for a name (used by the create form)."""
    email = suggest_teacher_email(
        request.user.profile.school, request.GET.get('first_name', ''), request.GET.get('last_name', '')
    )
    return JsonResponse({'email': email or ''})


# =============================================================================
# GRADE VALIDATION & PERIOD LOCK
# =============================================================================

def _class_grades(section, subject, period):
    return GradeComponent.objects.filter(quarter=period, subject=subject, enrollment__section=section)


def _class_grade_state(enrolled, statuses):
    """One status word for a class in a period, from its students' grade rows."""
    encoded = sum(statuses.values())
    if not encoded:
        return 'not_started'
    if statuses.get('Returned'):
        return 'returned'
    if encoded < enrolled:
        return 'incomplete'
    if statuses.get('Draft') or statuses.get('Submitted'):
        return 'ready'
    return 'validated'


def _selected_period(request, current_sy):
    periods = list(Quarter.objects.filter(school_year=current_sy).order_by('quarter_number')) if current_sy else []
    chosen = request.GET.get('period') or request.POST.get('period')
    period = next((p for p in periods if str(p.id) == str(chosen)), None)
    if not period:
        period = next((p for p in periods if p.is_current_quarter), periods[0] if periods else None)
    return periods, period


def _grade_overview(school, current_sy, period):
    """Every active class of the school year with its grade progress in one period."""
    assignments = list(
        ClassAssignment.objects.filter(school_year=current_sy, section__school=school, is_active=True)
        .select_related('section', 'section__grade_level', 'subject', 'teacher')
        .order_by('section__grade_level__sort_order', 'section__section_name', 'subject__subject_code')
    )
    enrolled = dict(
        Enrollment.objects.filter(section__school=school, school_year=current_sy, status__in=ACTIVE_ENROLLMENT)
        .values_list('section_id').annotate(total=Count('id'))
    )
    status_counts = {}
    for section_id, subject_id, status, total in GradeComponent.objects.filter(
        quarter=period, enrollment__section__school=school, enrollment__status__in=ACTIVE_ENROLLMENT
    ).values_list('enrollment__section_id', 'subject_id', 'validation_status').annotate(total=Count('id')):
        status_counts.setdefault((section_id, subject_id), {})[status] = total

    rows = []
    for a in assignments:
        statuses = status_counts.get((a.section_id, a.subject_id), {})
        total = enrolled.get(a.section_id, 0)
        encoded = sum(statuses.values())
        rows.append({
            'assignment': a,
            'enrolled': total,
            'encoded': encoded,
            'percent': min(round(encoded * 100 / total), 100) if total else 0,
            'state': _class_grade_state(total, statuses),
        })
    return rows


@registrar_required
@remember_filters('registrar-grades', ['period'])
@cache_page_for_user()
def grade_validation(request):
    """Per grading period: which classes have grades in, validate them, lock the period."""
    school = request.user.profile.school
    current_sy = _current_school_year(school)
    periods, period = _selected_period(request, current_sy)

    if request.method == 'POST' and period:
        action = request.POST.get('action')
        period_grades = GradeComponent.objects.filter(quarter=period, enrollment__section__school=school)
        now = timezone.now()
        if action == 'lock':
            period.is_grades_locked, period.locked_by, period.locked_at = True, request.user, now
            period.save()
            period_grades.filter(validation_status='Validated').update(validation_status='Finalized')
            period_grades.update(is_locked=True, locked_by=request.user, locked_at=now)
            _log(request, 'LOCK_GRADES', period.id, f'Locked grades for {period.quarter_label} {current_sy.year_label}', 'Quarter')
            messages.success(request, f'{period.quarter_label} is locked. Teachers can no longer change its grades.')
        elif action == 'unlock':
            period.is_grades_locked, period.locked_by, period.locked_at = False, None, None
            period.save()
            period_grades.update(is_locked=False, locked_by=None, locked_at=None)
            period_grades.filter(validation_status='Finalized').update(validation_status='Validated')
            _log(request, 'UNLOCK_GRADES', period.id, f'Unlocked grades for {period.quarter_label} {current_sy.year_label}', 'Quarter')
            messages.success(request, f'{period.quarter_label} is unlocked.')
        elif action == 'validate_all':
            if period.is_grades_locked:
                messages.error(request, f'{period.quarter_label} is locked. Unlock it to change validation.')
            else:
                # only classes whose every enrolled student has a grade
                validated = 0
                for row in _grade_overview(school, current_sy, period):
                    if row['state'] == 'ready':
                        _class_grades(row['assignment'].section, row['assignment'].subject, period).update(
                            validation_status='Validated', validated_by=request.user, validation_date=now)
                        validated += 1
                if validated:
                    messages.success(request, f'{validated} complete class(es) validated for {period.quarter_label}.')
                else:
                    messages.info(request, 'No complete classes are waiting for validation.')
        return redirect(f"{reverse('registrars:grade_validation')}?period={period.id}")

    rows = _grade_overview(school, current_sy, period) if period else []
    counts = {}
    for row in rows:
        counts[row['state']] = counts.get(row['state'], 0) + 1
    return render(request, 'registrars/grades/validation.html', {
        'current_sy': current_sy,
        'periods': periods,
        'period': period,
        'rows': rows,
        'counts': counts,
        'pending_count': len(rows) - counts.get('validated', 0),
    })


@registrar_required
def grade_class_detail(request, assignment_id, period_id):
    """Review one class's grades for a period, then validate or return them."""
    school = request.user.profile.school
    assignment = get_object_or_404(
        ClassAssignment.objects.select_related('section', 'section__grade_level', 'subject', 'teacher', 'school_year'),
        id=assignment_id, section__school=school,
    )
    period = get_object_or_404(Quarter, id=period_id, school_year=assignment.school_year)
    grades = _class_grades(assignment.section, assignment.subject, period)

    if request.method == 'POST':
        action = request.POST.get('action')
        if period.is_grades_locked:
            messages.error(request, f'{period.quarter_label} is locked. Unlock it to change validation.')
        elif not grades.exists():
            messages.error(request, 'There are no grades to act on yet.')
        elif action == 'validate':
            grades.update(validation_status='Validated', validated_by=request.user,
                          validation_date=timezone.now(), validation_notes='')
            _log(request, 'VALIDATE_GRADES', assignment.id,
                 f'Validated {assignment.subject.subject_code} — {assignment.section.section_name} ({period.quarter_label})', 'ClassAssignment')
            messages.success(request, f'{assignment.subject.subject_code} — {assignment.section.section_name} validated for {period.quarter_label}.')
        elif action == 'return':
            note = request.POST.get('note', '').strip()
            if not note:
                messages.error(request, 'Tell the teacher what needs correcting before returning the grades.')
            else:
                grades.update(validation_status='Returned', validated_by=request.user,
                              validation_date=timezone.now(), validation_notes=note)
                _log(request, 'RETURN_GRADES', assignment.id,
                     f'Returned {assignment.subject.subject_code} — {assignment.section.section_name} ({period.quarter_label}): {note}', 'ClassAssignment')
                messages.success(request, 'Grades returned to the teacher for correction.')
        return redirect('registrars:grade_class_detail', assignment_id=assignment.id, period_id=period.id)

    by_enrollment = {g.enrollment_id: g for g in grades}
    students = []
    for e in Enrollment.objects.filter(
        section=assignment.section, school_year=assignment.school_year, status__in=ACTIVE_ENROLLMENT
    ).select_related('student').order_by('student__last_name', 'student__first_name'):
        g = by_enrollment.get(e.id)
        value = None
        if g:
            value = g.transmuted_grade if g.transmuted_grade is not None else g.initial_grade
        students.append({'enrollment': e, 'grade': g, 'value': value})

    values = [float(s['value']) for s in students if s['value'] is not None]
    passing = school.passing_grade
    statuses = {}
    for s in students:
        if s['grade']:
            statuses[s['grade'].validation_status] = statuses.get(s['grade'].validation_status, 0) + 1
    return render(request, 'registrars/grades/class_detail.html', {
        'assignment': assignment,
        'period': period,
        'students': students,
        'encoded': sum(statuses.values()),
        'missing': len(students) - sum(statuses.values()),
        'average': round(sum(values) / len(values), 2) if values else None,
        'passed': sum(1 for v in values if v >= passing),
        'failed': sum(1 for v in values if v < passing),
        'passing': passing,
        'state': _class_grade_state(len(students), statuses),
        'note': next((g.validation_notes for g in by_enrollment.values() if g.validation_notes), ''),
    })
