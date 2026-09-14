from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.db.models import Count, Q, Avg, Sum
from django.http import JsonResponse, HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from datetime import date, timedelta, datetime
import json
from io import BytesIO
from openpyxl import load_workbook
from datetime import date, datetime, timedelta
from calendar import monthrange
import decimal
from decimal import Decimal
from django.utils.safestring import mark_safe
from django.db import connection



# Models
from scheduling.models import ClassAssignment, ClassSchedule
from enrollment.models import Enrollment
from grades.models import GradeComponent
from attendance.models import AttendanceRecord, AttendanceSummary
from academics.models import SchoolYear, Quarter, Section, Subject, GradeLevel, Strand
from documentation.models import FormSubmission, FormCompliance, SF10History
from accounts.models import SchoolForm
from promotion.models import PromotionRecommendation
from students.models import Guardian, Student
from audit.models import DataCorrectionRequest
from communication.models import Notification

from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, Image
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.enums import TA_CENTER, TA_LEFT
import io

# ============================================================
# DASHBOARD (unchanged)
# ============================================================
@login_required
def dashboard(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')

    teacher = request.user
    today = date.today()
    current_day_name = today.strftime('%A')

    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher, is_active=True
    ).select_related(
        'section', 'section__grade_level', 'subject', 'default_room', 'school_year'
    ).prefetch_related('schedules')

    has_data = class_assignments.exists()
    total_classes = class_assignments.count()
    total_students = 0
    if has_data:
        section_ids = class_assignments.values_list('section_id', flat=True).distinct()
        total_students = Enrollment.objects.filter(
            section_id__in=section_ids, status='Enrolled'
        ).count()

    today_schedules = []
    if has_data:
        today_schedules = ClassSchedule.objects.filter(
            class_assignment__in=class_assignments, day_of_week=current_day_name, is_active=True
        ).select_related('class_assignment__subject', 'class_assignment__section', 'room').order_by('time_start')

    pending_grades = 0
    completion_rate = 0
    if has_data:
        section_ids = class_assignments.values_list('section_id', flat=True).distinct()
        subject_ids = class_assignments.values_list('subject_id', flat=True).distinct()
        total_possible = GradeComponent.objects.filter(
            enrollment__section_id__in=section_ids, subject_id__in=subject_ids
        ).count()
        pending_grades = GradeComponent.objects.filter(
            enrollment__section_id__in=section_ids, subject_id__in=subject_ids,
            validation_status__in=['Draft', 'Returned']
        ).count()
        if total_possible > 0:
            completion_rate = round(((total_possible - pending_grades) / total_possible) * 100)

    class_progress = []
    if has_data:
        for ca in class_assignments:
            section_id = ca.section_id
            subject_id = ca.subject_id
            total = GradeComponent.objects.filter(
                enrollment__section_id=section_id, subject_id=subject_id
            ).count()
            submitted = GradeComponent.objects.filter(
                enrollment__section_id=section_id, subject_id=subject_id,
                validation_status__in=['Submitted', 'Validated', 'Finalized']
            ).count()
            pct = round((submitted / total) * 100) if total > 0 else 0
            class_progress.append({
                'name': str(ca.section), 'subject': ca.subject.subject_name, 'pct': pct,
            })

    classes_data = []
    seen_sections = set()
    if has_data:
        for ca in class_assignments:
            section_key = ca.section_id
            if section_key not in seen_sections:
                seen_sections.add(section_key)
                student_count = Enrollment.objects.filter(
                    section_id=section_key, status='Enrolled'
                ).count()
                classes_data.append({
                    'name': str(ca.section), 'subject': ca.subject.subject_name,
                    'is_advisory': ca.is_advisory, 'student_count': student_count,
                })

    grade_dist = {'90-100': 0, '80-89': 0, '75-79': 0, 'Below 75': 0}
    if has_data:
        section_ids = class_assignments.values_list('section_id', flat=True).distinct()
        subject_ids = class_assignments.values_list('subject_id', flat=True).distinct()
        grades = GradeComponent.objects.filter(
            enrollment__section_id__in=section_ids, subject_id__in=subject_ids,
            transmuted_grade__isnull=False
        ).values_list('transmuted_grade', flat=True)
        for g in grades:
            if g >= 90: grade_dist['90-100'] += 1
            elif g >= 80: grade_dist['80-89'] += 1
            elif g >= 75: grade_dist['75-79'] += 1
            else: grade_dist['Below 75'] += 1

    attendance_stats = {'present_pct': 0, 'absent_pct': 0, 'late_pct': 0}
    if has_data:
        thirty_days_ago = today - timedelta(days=30)
        section_ids = class_assignments.values_list('section_id', flat=True).distinct()
        enrollments = Enrollment.objects.filter(section_id__in=section_ids, status='Enrolled')
        att_records = AttendanceRecord.objects.filter(
            enrollment__in=enrollments, date__gte=thirty_days_ago, date__lte=today
        )
        total_att = att_records.count()
        if total_att > 0:
            attendance_stats['present_pct'] = round(att_records.filter(status='Present').count() / total_att * 100)
            attendance_stats['absent_pct'] = round(att_records.filter(status='Absent').count() / total_att * 100)
            attendance_stats['late_pct'] = round(att_records.filter(status='Late').count() / total_att * 100)

    weekly_labels = []
    weekly_data = []
    if has_data:
        section_ids = class_assignments.values_list('section_id', flat=True).distinct()
        subject_ids = class_assignments.values_list('subject_id', flat=True).distinct()
        for week_offset in range(3, -1, -1):
            week_start = today - timedelta(days=today.weekday() + 7 * week_offset)
            week_end = week_start + timedelta(days=6)
            weekly_labels.append(week_start.strftime('%b %d'))
            week_grades = GradeComponent.objects.filter(
                enrollment__section_id__in=section_ids, subject_id__in=subject_ids,
                transmuted_grade__isnull=False,
                updated_at__date__gte=week_start, updated_at__date__lte=week_end
            ).aggregate(avg=Avg('transmuted_grade'))
            weekly_data.append(round(week_grades['avg'], 1) if week_grades['avg'] else 0)

    context = {
        'has_data': has_data, 'total_classes': total_classes, 'total_students': total_students,
        'pending_grades': pending_grades, 'completion_rate': completion_rate,
        'today_schedules': today_schedules, 'current_day': current_day_name,
        'class_progress': class_progress, 'classes_data': classes_data,
        'grade_dist': grade_dist, 'attendance_stats': attendance_stats,
        'weekly_labels': weekly_labels, 'weekly_data': weekly_data,
    }
    return render(request, 'teachers/dashboard/index.html', context)


# ============================================================
# CLASS LIST (unchanged)
# ============================================================
@login_required
def class_list(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')

    teacher = request.user
    today = date.today()
    current_day_name = today.strftime('%A')

    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher, is_active=True
    ).select_related(
        'section', 'section__grade_level', 'subject', 'default_room', 'school_year'
    ).prefetch_related('schedules')

    has_data = class_assignments.exists()
    
    unique_sections = {}
    for ca in class_assignments:
        if ca.section_id not in unique_sections:
            unique_sections[ca.section_id] = {
                'section': ca.section,
                'is_advisory': ca.is_advisory,
                'assignments': []
            }
        unique_sections[ca.section_id]['assignments'].append(ca)
    
    total_classes = len(unique_sections)
    
    total_students = 0
    pending_grades = 0
    completion_rate = 0

    if has_data:
        section_ids = list(unique_sections.keys())
        total_students = Enrollment.objects.filter(section_id__in=section_ids, status='Enrolled').count()
        subject_ids = class_assignments.values_list('subject_id', flat=True).distinct()
        total_possible = GradeComponent.objects.filter(
            enrollment__section_id__in=section_ids, subject_id__in=subject_ids
        ).count()
        pending = GradeComponent.objects.filter(
            enrollment__section_id__in=section_ids, subject_id__in=subject_ids,
            validation_status__in=['Draft', 'Returned']
        ).count()
        pending_grades = pending
        if total_possible > 0:
            completion_rate = round(((total_possible - pending) / total_possible) * 100)

    schedule_data = []
    if has_data:
        all_schedules = ClassSchedule.objects.filter(
            class_assignment__in=class_assignments, is_active=True
        ).select_related('class_assignment__subject', 'class_assignment__section', 'room').order_by('day_number', 'time_start')
        for s in all_schedules:
            ca = s.class_assignment
            sc = ca.subject.subject_code.upper()
            if 'MATH' in sc or 'PRECALC' in sc or 'BUSMATH' in sc or 'STATS' in sc: color = 'math'
            elif 'SCI' in sc or 'BIO' in sc or 'CHEM' in sc: color = 'science'
            elif 'ENG' in sc or 'EAPP' in sc: color = 'english'
            elif 'PHY' in sc: color = 'physics'
            elif 'BUS' in sc or 'ABM' in sc or 'FABM' in sc: color = 'business'
            else: color = 'math'
            student_count = Enrollment.objects.filter(section=ca.section, status='Enrolled').count()
            schedule_data.append({
                'startHour': s.time_start.hour, 'startMinute': s.time_start.minute,
                'endHour': s.time_end.hour, 'endMinute': s.time_end.minute,
                'subject': ca.subject.subject_name, 'section': str(ca.section),
                'color': color, 'students': student_count,
                'day': s.day_of_week, 'dayNumber': s.day_number,
            })

    today_count = sum(1 for s in schedule_data if s['day'] == current_day_name)

    classes_data = []
    advisory_classes = []
    subject_classes = []
    
    if has_data:
        for section_id, section_info in unique_sections.items():
            sec = section_info['section']
            enrollments = Enrollment.objects.filter(section=sec, status='Enrolled').select_related('student')
            student_count = enrollments.count()
            male_count = enrollments.filter(student__sex='M').count()
            female_count = student_count - male_count
            
            advisory_assignment = None
            subject_assignments = []
            for ca in section_info['assignments']:
                if ca.is_advisory:
                    advisory_assignment = ca
                else:
                    subject_assignments.append(ca)
            
            if advisory_assignment:
                student_list = []
                for enr in enrollments.order_by('student__last_name', 'student__first_name'):
                    st = enr.student
                    student_list.append({
                        'name': f"{st.last_name}, {st.first_name} {st.middle_name or ''}".strip(),
                        'lrn': st.lrn if hasattr(st, 'lrn') else '', 'sex': st.sex or '',
                    })
                
                total_grades = GradeComponent.objects.filter(enrollment__section=sec, subject=advisory_assignment.subject).count()
                submitted_grades = GradeComponent.objects.filter(
                    enrollment__section=sec, subject=advisory_assignment.subject,
                    validation_status__in=['Submitted', 'Validated', 'Finalized']
                ).count()
                progress = round((submitted_grades / total_grades) * 100) if total_grades > 0 else 0
                
                class_card = {
                    'name': f"{sec.grade_level.grade_name} - {sec.section_name}",
                    'section_str': str(sec),
                    'role': 'Adviser',
                    'subject': advisory_assignment.subject.subject_name,
                    'students': student_count,
                    'boys': male_count,
                    'girls': female_count,
                    'progress': progress,
                    'is_advisory': True,
                    'ca_id': advisory_assignment.id,
                    'student_list': student_list,
                }
                advisory_classes.append(class_card)
            else:
                for ca in subject_assignments:
                    student_list = []
                    for enr in enrollments.order_by('student__last_name', 'student__first_name'):
                        st = enr.student
                        student_list.append({
                            'name': f"{st.last_name}, {st.first_name} {st.middle_name or ''}".strip(),
                            'lrn': st.lrn if hasattr(st, 'lrn') else '', 'sex': st.sex or '',
                        })
                    
                    total_grades = GradeComponent.objects.filter(enrollment__section=sec, subject=ca.subject).count()
                    submitted_grades = GradeComponent.objects.filter(
                        enrollment__section=sec, subject=ca.subject,
                        validation_status__in=['Submitted', 'Validated', 'Finalized']
                    ).count()
                    progress = round((submitted_grades / total_grades) * 100) if total_grades > 0 else 0
                    
                    class_card = {
                        'name': f"{sec.grade_level.grade_name} - {sec.section_name}",
                        'section_str': str(sec),
                        'role': 'Subject Teacher',
                        'subject': ca.subject.subject_name,
                        'students': student_count,
                        'boys': male_count,
                        'girls': female_count,
                        'progress': progress,
                        'is_advisory': False,
                        'ca_id': ca.id,
                        'student_list': student_list,
                    }
                    subject_classes.append(class_card)
        
        classes_data = advisory_classes + subject_classes

    context = {
        'has_data': has_data,
        'total_classes': len(classes_data),
        'total_students': total_students,
        'pending_grades': pending_grades,
        'completion_rate': completion_rate,
        'schedule_data': json.dumps(schedule_data),
        'classes_data': classes_data,
        'classes_data_json': json.dumps(classes_data),
        'current_day': current_day_name,
        'today_count': today_count,
        'today': today,
    }
    return render(request, 'teachers/classes/class_list.html', context)


# ============================================================
# ✅ GRADE ENCODING - FIXED for dynamic quarter display
# ============================================================
import json
from django.utils.safestring import mark_safe

@login_required
def grade_encoding(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    teacher = request.user
    quarter_label = request.GET.get('quarter', 'Q3')
    class_id = request.GET.get('class_id')
    subject_id = request.GET.get('subject_id')

    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher, is_active=True
    ).select_related('section__grade_level', 'subject')

    if not class_assignments.exists():
        return render(request, 'teachers/grades/grades_encoding.html', {
            'has_data': False,
            'classes_data': [],
            'classes_data_json': mark_safe('[]'),
            'grade_sheet_data': [],
            'grade_sheet_json': mark_safe('[]'),
            'total_students': 0,
            'completed_count': 0,
            'pending_count': 0,
            'failing_count': 0,
            'completion_rate': 0,
            'quarter_label': quarter_label,
            'first_quarter_label': 'Q1' if int(quarter_label[1]) <= 2 else 'Q3',
            'second_quarter_label': 'Q2' if int(quarter_label[1]) <= 2 else 'Q4',
            'semester_label': '',
            'selected_section': '—',
            'selected_subject': '—',
            'selected_section_id': None,
            'selected_subject_id': None,
            'selected_quarter_id': None,
        })

    classes_data = []
    unique_sections = {}

    for ca in class_assignments:
        if ca.section_id not in unique_sections:
            unique_sections[ca.section_id] = {
                'section': ca.section,
                'is_advisory': ca.is_advisory,
                'subjects': []
            }
        unique_sections[ca.section_id]['subjects'].append({
            'subject_id': ca.subject_id,
            'subject_name': ca.subject.subject_name,
        })

    for sec_id, sec_info in unique_sections.items():
        classes_data.append({
            'section_id': sec_info['section'].id,
            'section_name': sec_info['section'].section_name,
            'grade_name': sec_info['section'].grade_level.grade_name,
            'is_advisory': bool(sec_info['is_advisory']),
            'subjects': list(sec_info['subjects'])
        })

    selected_section = None
    if class_id:
        selected_section = Section.objects.filter(id=class_id).first()
    if not selected_section and classes_data:
        selected_section = Section.objects.filter(id=classes_data[0]['section_id']).first()

    selected_subject = None
    if subject_id:
        selected_subject = Subject.objects.filter(id=subject_id).first()
    elif selected_section:
        first_ca = class_assignments.filter(section=selected_section).first()
        if first_ca:
            selected_subject = first_ca.subject

    current_sy = SchoolYear.objects.filter(is_current=True).first()

    quarter_num = int(quarter_label[1])

    if quarter_num <= 2:
        first_quarter = Quarter.objects.filter(school_year=current_sy, quarter_label='Q1').first()
        second_quarter = Quarter.objects.filter(school_year=current_sy, quarter_label='Q2').first()
        first_label = 'Q1'
        second_label = 'Q2'
        semester_label = '1st Semester'
    else:
        first_quarter = Quarter.objects.filter(school_year=current_sy, quarter_label='Q3').first()
        second_quarter = Quarter.objects.filter(school_year=current_sy, quarter_label='Q4').first()
        first_label = 'Q3'
        second_label = 'Q4'
        semester_label = '2nd Semester'

    selected_quarter = Quarter.objects.filter(
        school_year=current_sy, quarter_label=quarter_label
    ).first() if current_sy else None

    enrollments = Enrollment.objects.filter(
        section=selected_section, status='Enrolled'
    ).select_related('student').order_by('student__last_name') if selected_section else []

    grade_sheet_data = []
    completed = 0
    pending = 0
    failing = 0
    avatar_colors = ['#5EA173', '#123499', '#9b59b6', '#e74c3c', '#f39c12', '#1abc9c', '#e67e22', '#2980b9']

    for i, enr in enumerate(enrollments):
        st = enr.student

        gc_first = GradeComponent.objects.filter(
            enrollment=enr, subject=selected_subject, quarter=first_quarter
        ).first() if selected_subject and first_quarter else None

        gc_second = GradeComponent.objects.filter(
            enrollment=enr, subject=selected_subject, quarter=second_quarter
        ).first() if selected_subject and second_quarter else None

        first_grade = float(gc_first.transmuted_grade) if gc_first and gc_first.transmuted_grade is not None else None
        second_grade = float(gc_second.transmuted_grade) if gc_second and gc_second.transmuted_grade is not None else None

        final_grade = None
        if first_grade is not None and second_grade is not None:
            final_grade = round((first_grade + second_grade) / 2, 2)

        status_class = 'incomplete'
        status_text = 'Incomplete'

        if final_grade is not None:
            completed += 1
            if final_grade >= 75:
                status_class = 'passed'
                status_text = 'Passed'
            else:
                status_class = 'failed'
                status_text = 'Failed'
                failing += 1
        else:
            pending += 1

        name = f"{st.last_name}, {st.first_name} {st.middle_name or ''}".strip()
        initials = name.split(',')[0][0] + (name.split(',')[1].strip()[0] if ',' in name else name[0])

        grade_sheet_data.append({
            'enrollment_id': enr.id,
            'lrn': st.lrn or '',
            'name': name,
            'initials': initials.upper(),
            'first_grade': first_grade if first_grade is not None else '',
            'second_grade': second_grade if second_grade is not None else '',
            'final_grade': final_grade if final_grade is not None else '',
            'transmuted_grade': final_grade,
            'status_text': status_text,
            'status_class': status_class,
            'color': avatar_colors[i % len(avatar_colors)],
        })

    total_students = len(grade_sheet_data)
    completion_rate = round((completed / total_students) * 100) if total_students > 0 else 0

    try:
        classes_data_json = mark_safe(json.dumps(classes_data))
        grade_sheet_json = mark_safe(json.dumps(grade_sheet_data))
    except Exception as e:
        classes_data_json = mark_safe('[]')
        grade_sheet_json = mark_safe('[]')

    context = {
        'has_data': True,
        'classes_data': classes_data,
        'classes_data_json': classes_data_json,
        'grade_sheet_data': grade_sheet_data,
        'grade_sheet_json': grade_sheet_json,
        'selected_section': str(selected_section) if selected_section else '—',
        'selected_section_id': selected_section.id if selected_section else None,
        'selected_subject': selected_subject.subject_name if selected_subject else '—',
        'selected_subject_id': selected_subject.id if selected_subject else None,
        'selected_quarter_id': selected_quarter.id if selected_quarter else None,
        'total_students': total_students,
        'completed_count': completed,
        'pending_count': pending,
        'failing_count': failing,
        'completion_rate': completion_rate,
        'quarter_label': quarter_label,
        'first_quarter_label': first_label,
        'second_quarter_label': second_label,
        'semester_label': semester_label,
    }
    return render(request, 'teachers/grades/grades_encoding.html', context)

# ============================================================
# ATTENDANCE (unchanged)
# ============================================================
@login_required
def attendance(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    teacher = request.user
    today = date.today()
    attendance_date_str = request.GET.get('date', today.isoformat())
    attendance_date = date.fromisoformat(attendance_date_str) if attendance_date_str else today
    class_id = request.GET.get('class_id')

    # ============================================================
    # HANDLE POST REQUEST (SAVE ATTENDANCE)
    # ============================================================
    if request.method == 'POST':
        try:
            # Parse JSON data from request body
            data = json.loads(request.body) if request.body else {}
            
            section_id = data.get('section_id') or class_id
            date_str = data.get('date') or attendance_date_str
            attendance_items = data.get('attendance', [])
            
            save_date = date.fromisoformat(date_str)
            
            # Prevent marking future dates
            if save_date > today:
                return JsonResponse({
                    'success': False, 
                    'error': 'Cannot mark attendance for future dates'
                }, status=400)
            
            saved_count = 0
            errors = []
            updated_summaries = set()
            
            for item in attendance_items:
                enrollment_id = item.get('enrollment_id')
                status = item.get('status', 'Present')
                remarks = item.get('remarks', '')
                excuse_type = item.get('excuse_type', '')
                minutes_late = item.get('minutes_late', 0)
                time_in_str = item.get('time_in', None)
                
                if not enrollment_id:
                    continue
                
                try:
                    enrollment = Enrollment.objects.get(id=enrollment_id, section_id=section_id)
                    
                    # Parse time_in if provided
                    time_in = None
                    if time_in_str:
                        try:
                            time_in = datetime.strptime(time_in_str, '%H:%M').time()
                        except ValueError:
                            pass
                    
                    # Check if record exists
                    record, created = AttendanceRecord.objects.get_or_create(
                        enrollment=enrollment,
                        date=save_date,
                        defaults={
                            'status': status,
                            'remarks': remarks,
                            'excuse_type': excuse_type if status == 'Excused' else '',
                            'minutes_late': minutes_late,
                            'time_in': time_in if status == 'Late' else None,
                            'marked_by': request.user,
                            'marked_at': timezone.now(),
                        }
                    )
                    
                    if not created:
                        record.status = status
                        record.remarks = remarks
                        record.excuse_type = excuse_type if status == 'Excused' else ''
                        record.minutes_late = minutes_late
                        record.time_in = time_in if status == 'Late' else None
                        record.updated_by = request.user
                        record.save()
                    
                    saved_count += 1
                    updated_summaries.add(enrollment.id)
                    
                except Enrollment.DoesNotExist:
                    errors.append(f'Enrollment {enrollment_id} not found')
                except Exception as e:
                    errors.append(str(e))
            
            # Update attendance summaries for affected students
            for enrollment_id in updated_summaries:
                enrollment = Enrollment.objects.filter(id=enrollment_id).first()
                if enrollment:
                    update_attendance_summary_for_month(enrollment, save_date)
            
            # Also update summaries for the entire section if batch save
            if saved_count > 0 and len(updated_summaries) > 0:
                # Trigger section-level summary update
                update_section_attendance_summary(section_id, save_date.year, save_date.month)
            
            return JsonResponse({
                'success': True,
                'saved_count': saved_count,
                'errors': errors if errors else None,
                'message': f'Successfully saved attendance for {saved_count} student(s)'
            })
            
        except json.JSONDecodeError:
            return JsonResponse({'success': False, 'error': 'Invalid JSON data'}, status=400)
        except Exception as e:
            import traceback
            traceback.print_exc()
            return JsonResponse({'success': False, 'error': str(e)}, status=500)

    # ============================================================
    # GET REQUEST - DISPLAY ATTENDANCE FORM
    # ============================================================
    
    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher, is_active=True
    ).select_related('section__grade_level', 'subject')

    if not class_assignments.exists():
        return render(request, 'teachers/attendance/class_attendance.html', {
            'has_data': False, 'classes_data': [], 'attendance_data': [],
            'attendance_date': attendance_date, 'selected_section': '—',
            'selected_section_id': None, 'selected_section_name': '—',
            'total_students': 0, 'present_count': 0, 'absent_count': 0, 'late_count': 0,
            'detected_section_name': None, 'detected_section_id': None,
        })

    classes_data = []
    for ca in class_assignments:
        classes_data.append({
            'section_name': ca.section.section_name, 
            'grade_name': ca.section.grade_level.grade_name,
            'section_id': ca.section_id,
            'student_count': Enrollment.objects.filter(section=ca.section, status='Enrolled').count(),
        })

    # Detect current section based on schedule
    now = datetime.now()
    current_time = now.strftime('%H:%M')
    detected_section_id = None
    today_schedules = ClassSchedule.objects.filter(
        class_assignment__in=class_assignments, day_of_week=today.strftime('%A'), is_active=True
    ).select_related('class_assignment__section')
    
    for sched in today_schedules:
        if str(sched.time_start) <= current_time <= str(sched.time_end):
            detected_section_id = sched.class_assignment.section_id
            break

    detected_class = None
    detected_section_name = None
    if detected_section_id:
        detected_class = class_assignments.filter(section_id=detected_section_id).first()
        if detected_class:
            detected_section_name = str(detected_class.section)

    selected = class_assignments.first()
    if class_id:
        selected = class_assignments.filter(section_id=class_id).first() or selected
    elif detected_class:
        selected = detected_class

    enrollments = Enrollment.objects.filter(
        section=selected.section, status='Enrolled'
    ).select_related('student').order_by('student__last_name')

    existing_records = AttendanceRecord.objects.filter(
        enrollment__section=selected.section, date=attendance_date
    ).values('enrollment_id', 'status', 'remarks', 'excuse_type', 'minutes_late', 'time_in')
    record_map = {r['enrollment_id']: r for r in existing_records}

    avatar_colors = ['#5EA173','#123499','#9b59b6','#e74c3c','#f39c12','#1abc9c','#e67e22','#2980b9']
    attendance_data = []
    present = absent = late = 0

    for i, enr in enumerate(enrollments):
        st = enr.student
        record = record_map.get(enr.id, {})
        status = record.get('status', 'Present')
        remarks = record.get('remarks', '')
        excuse_type = record.get('excuse_type', '')
        minutes_late = record.get('minutes_late', 0)
        time_in = record.get('time_in')
        
        if status == 'Present': 
            present += 1
        elif status == 'Absent': 
            absent += 1
        else: 
            late += 1
            
        name = f"{st.last_name}, {st.first_name} {st.middle_name or ''}".strip()
        initials = name.split(',')[0][0] + (name.split(',')[1].strip()[0] if ',' in name else name[0])
        
        attendance_data.append({
            'lrn': st.lrn, 
            'name': name, 
            'initials': initials.upper(),
            'color': avatar_colors[i % len(avatar_colors)],
            'enrollment_id': enr.id, 
            'status': status, 
            'remarks': remarks,
            'excuse_type': excuse_type,
            'minutes_late': minutes_late,
            'time_in': time_in.strftime('%H:%M') if time_in else '',
            'sex': st.sex,
        })

    # Get school start time for late calculation (customize as needed)
    school_start_time = "07:30"  # Default, can be moved to settings

    context = {
        'has_data': True, 
        'classes_data': classes_data, 
        'attendance_data': attendance_data,
        'attendance_date': attendance_date, 
        'selected_section': str(selected.section),
        'selected_section_id': selected.section_id, 
        'selected_section_name': selected.section.section_name,
        'total_students': len(attendance_data), 
        'present_count': present,
        'absent_count': absent, 
        'late_count': late,
        'detected_section_name': detected_section_name, 
        'detected_section_id': detected_section_id,
        'school_start_time': school_start_time,
    }
    return render(request, 'teachers/attendance/class_attendance.html', context)


# ============================================================
# HELPER FUNCTIONS FOR ATTENDANCE
# ============================================================

def update_attendance_summary_for_month(enrollment, attendance_date):
    """Update or create monthly attendance summary for an enrollment."""
    from calendar import monthrange
    from datetime import date as date_class  # Import with alias to avoid confusion
    
    school_year = enrollment.school_year
    month = attendance_date.month
    year = attendance_date.year
    
    # Get or create summary for this month
    summary, created = AttendanceSummary.objects.get_or_create(
        enrollment=enrollment,
        school_year=school_year,
        month=month,
        defaults={
            'total_school_days': 0,
            'days_present': 0,
            'days_absent': 0,
            'days_late': 0,
            'days_excused': 0,
            'days_cutting': 0,
            'days_suspended': 0,
        }
    )
    
    # Get first and last day of month - USE date_class instead of date
    first_day = date_class(year, month, 1)
    last_day = date_class(year, month, monthrange(year, month)[1])
    
    # Get all records for this month
    records = AttendanceRecord.objects.filter(
        enrollment=enrollment,
        date__gte=first_day,
        date__lte=last_day
    )
    
    # Calculate totals
    summary.days_present = records.filter(status='Present').count()
    summary.days_absent = records.filter(status='Absent').count()
    summary.days_late = records.filter(status='Late').count()
    summary.days_excused = records.filter(status='Excused').count()
    summary.days_cutting = records.filter(status='Cutting').count()
    summary.days_suspended = records.filter(status='Suspended').count()
    summary.total_school_days = records.count()
    
    # Calculate absence rate
    if summary.total_school_days > 0:
        summary.absence_rate_percent = round(
            (summary.days_absent / summary.total_school_days) * 100, 2
        )
        # DepEd: ≥20% absence rate = at risk
        summary.is_at_risk = summary.absence_rate_percent >= 20
    
    # Calculate consecutive absences (max streak)
    absent_dates = list(records.filter(status='Absent').dates('date', 'day'))
    max_streak = 0
    current_streak = 0
    last_date = None
    
    for d in absent_dates:
        if last_date and (d - last_date).days == 1:
            current_streak += 1
        else:
            current_streak = 1
        max_streak = max(max_streak, current_streak)
        last_date = d
    
    summary.consecutive_absences = max_streak
    summary.save()
    
    return summary


def update_section_attendance_summary(section_id, year, month):
    """Update attendance summaries for all students in a section for a given month."""
    from calendar import monthrange
    from datetime import date as date_class
    
    enrollments = Enrollment.objects.filter(
        section_id=section_id, 
        status='Enrolled'
    ).select_related('student')
    
    # Create a date object for the month
    last_day = monthrange(year, month)[1]
    sample_date = date_class(year, month, last_day)
    
    for enrollment in enrollments:
        update_attendance_summary_for_month(enrollment, sample_date)
    
    return enrollments.count()

# ============================================================
# AJAX ENDPOINT FOR SINGLE STUDENT ATTENDANCE
# ============================================================

@csrf_exempt
@login_required
def mark_attendance_ajax(request):
    """AJAX endpoint to mark attendance for a single student."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        data = json.loads(request.body)
        enrollment_id = data.get('enrollment_id')
        status = data.get('status')
        date_str = data.get('date')
        remarks = data.get('remarks', '')
        excuse_type = data.get('excuse_type', '')
        minutes_late = data.get('minutes_late', 0)
        time_in = data.get('time_in', None)
        
        if not enrollment_id or not status:
            return JsonResponse({'success': False, 'error': 'Missing required fields'}, status=400)
        
        attendance_date = date.fromisoformat(date_str) if date_str else date.today()
        
        # Prevent future dates
        if attendance_date > date.today():
            return JsonResponse({'success': False, 'error': 'Cannot mark future dates'}, status=400)
        
        enrollment = Enrollment.objects.get(id=enrollment_id)
        
        # Parse time_in if provided
        time_in_obj = None
        if time_in:
            try:
                time_in_obj = datetime.strptime(time_in, '%H:%M').time()
            except ValueError:
                pass
        
        record, created = AttendanceRecord.objects.get_or_create(
            enrollment=enrollment,
            date=attendance_date,
            defaults={
                'status': status,
                'remarks': remarks,
                'excuse_type': excuse_type if status == 'Excused' else '',
                'minutes_late': minutes_late,
                'time_in': time_in_obj if status == 'Late' else None,
                'marked_by': request.user,
                'marked_at': timezone.now(),
            }
        )
        
        if not created:
            record.status = status
            record.remarks = remarks
            record.excuse_type = excuse_type if status == 'Excused' else ''
            record.minutes_late = minutes_late
            record.time_in = time_in_obj if status == 'Late' else None
            record.updated_by = request.user
            record.save()
        
        # Update summary
        update_attendance_summary_for_month(enrollment, attendance_date)
        
        # Check if student is now at risk
        summary = AttendanceSummary.objects.filter(
            enrollment=enrollment,
            school_year=enrollment.school_year,
            month=attendance_date.month
        ).first()
        
        is_at_risk = summary.is_at_risk if summary else False
        
        return JsonResponse({
            'success': True,
            'message': f'Attendance marked as {status}',
            'is_at_risk': is_at_risk,
            'record_id': record.id
        })
        
    except Enrollment.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Student not found'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================
# AJAX ENDPOINT TO GET ATTENDANCE STATISTICS
# ============================================================

@login_required
def attendance_stats_api(request):
    """API endpoint to get attendance statistics for a section."""
    if request.method != 'GET':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    section_id = request.GET.get('section_id')
    month = request.GET.get('month')
    year = request.GET.get('year')
    
    if not section_id:
        return JsonResponse({'success': False, 'error': 'Section ID required'}, status=400)
    
    try:
        current_year = date.today().year
        current_month = date.today().month
        target_year = int(year) if year else current_year
        target_month = int(month) if month else current_month
        
        # Get all enrollments for this section
        enrollments = Enrollment.objects.filter(
            section_id=section_id, 
            status='Enrolled'
        ).select_related('student')
        
        stats = []
        total_present = 0
        total_absent = 0
        total_late = 0
        total_excused = 0
        at_risk_count = 0
        
        for enrollment in enrollments:
            # Get summary for the month
            summary = AttendanceSummary.objects.filter(
                enrollment=enrollment,
                school_year=enrollment.school_year,
                month=target_month
            ).first()
            
            if summary:
                total_present += summary.days_present
                total_absent += summary.days_absent
                total_late += summary.days_late
                total_excused += summary.days_excused
                if summary.is_at_risk:
                    at_risk_count += 1
                
                stats.append({
                    'student_name': enrollment.student.full_name,
                    'lrn': enrollment.student.lrn,
                    'present': summary.days_present,
                    'absent': summary.days_absent,
                    'late': summary.days_late,
                    'excused': summary.days_excused,
                    'total_days': summary.total_school_days,
                    'absence_rate': float(summary.absence_rate_percent) if summary.absence_rate_percent else 0,
                    'is_at_risk': summary.is_at_risk,
                    'consecutive_absences': summary.consecutive_absences
                })
        
        total_students = enrollments.count()
        
        return JsonResponse({
            'success': True,
            'stats': stats,
            'totals': {
                'total_present': total_present,
                'total_absent': total_absent,
                'total_late': total_late,
                'total_excused': total_excused,
                'at_risk_count': at_risk_count,
                'total_students': total_students
            },
            'month': target_month,
            'year': target_year
        })
        
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


@csrf_exempt
@login_required
def import_attendance_excel(request):
    """Import attendance records from Excel file."""
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            return JsonResponse({'success': False, 'error': 'No file uploaded'})
        
        section_id = request.POST.get('section_id')
        attendance_date_str = request.POST.get('date')
        
        if not section_id or not attendance_date_str:
            return JsonResponse({'success': False, 'error': 'Missing section or date'}, status=400)
        
        attendance_date = date.fromisoformat(attendance_date_str)
        
        # Prevent future dates
        if attendance_date > date.today():
            return JsonResponse({'success': False, 'error': 'Cannot mark future dates'}, status=400)
        
        file_content = excel_file.read()
        
        try:
            wb = load_workbook(BytesIO(file_content))
            sheet = wb.active
        except Exception as e:
            return JsonResponse({
                'success': False, 
                'error': f'Could not read the Excel file: {str(e)}'
            })
        
        # Get enrollments for this section
        enrollments = Enrollment.objects.filter(
            section_id=section_id, 
            status='Enrolled'
        ).select_related('student')
        
        # Build student lookup by name
        student_map = {}
        for enrollment in enrollments:
            student = enrollment.student
            full_name = f"{student.last_name}, {student.first_name}".lower()
            first_last = f"{student.first_name} {student.last_name}".lower()
            student_map[full_name] = enrollment
            student_map[first_last] = enrollment
            student_map[student.lrn] = enrollment
        
        # Parse file - assume columns: Name/LRN, Status, Remarks
        name_col = 1
        status_col = 2
        remarks_col = 3
        
        # Try to detect column headers
        for row_num in range(1, min(6, sheet.max_row + 1)):
            for col_num in range(1, min(6, sheet.max_column + 1)):
                cell_val = sheet.cell(row=row_num, column=col_num).value
                if cell_val:
                    cell_str = str(cell_val).strip().upper()
                    if 'NAME' in cell_str or 'LRN' in cell_str:
                        name_col = col_num
                    elif 'STATUS' in cell_str:
                        status_col = col_num
                    elif 'REMARK' in cell_str or 'NOTE' in cell_str:
                        remarks_col = col_num
        
        saved_count = 0
        errors = []
        
        for row_num in range(2, sheet.max_row + 1):
            name_value = sheet.cell(row=row_num, column=name_col).value
            if not name_value:
                continue
            
            name_str = str(name_value).strip()
            
            # Find student
            enrollment = None
            for key in student_map:
                if key in name_str.lower():
                    enrollment = student_map[key]
                    break
            
            if not enrollment:
                errors.append(f'Student not found: {name_str}')
                continue
            
            # Get status
            status_value = sheet.cell(row=row_num, column=status_col).value
            status = str(status_value).strip().capitalize() if status_value else 'Present'
            
            # Validate status
            valid_statuses = ['Present', 'Absent', 'Late', 'Excused', 'Cutting', 'Suspended']
            if status not in valid_statuses:
                status = 'Present'
            
            # Get remarks
            remarks = sheet.cell(row=row_num, column=remarks_col).value or ''
            
            # Save record
            record, created = AttendanceRecord.objects.get_or_create(
                enrollment=enrollment,
                date=attendance_date,
                defaults={
                    'status': status,
                    'remarks': str(remarks),
                    'marked_by': request.user,
                    'marked_at': timezone.now(),
                }
            )
            
            if not created:
                record.status = status
                record.remarks = str(remarks)
                record.updated_by = request.user
                record.save()
            
            saved_count += 1
            
            # Update summary
            update_attendance_summary_for_month(enrollment, attendance_date)
        
        return JsonResponse({
            'success': True,
            'imported_count': saved_count,
            'errors': errors if errors else None,
            'message': f'Successfully imported attendance for {saved_count} students'
        })
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================
# EXPORT ATTENDANCE SUMMARY TO EXCEL
# ============================================================

# ============================================================
# EXPORT ATTENDANCE SUMMARY TO EXCEL - FIXED
# ============================================================

# ============================================================
# EXPORT ATTENDANCE SUMMARY TO EXCEL - FULLY FIXED
# ============================================================

@login_required
def export_attendance_summary(request):
    """Export attendance summary for a section and date range to Excel."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter
    from django.http import HttpResponse
    import traceback
    
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied.')
        return redirect('teachers-attendance')
    
    teacher = request.user
    section_id = request.GET.get('class_id')
    export_type = request.GET.get('type', 'daily')
    date_from = request.GET.get('date_from')
    quarter_label = request.GET.get('quarter', 'Q3')
    
    print(f"Export requested: section_id={section_id}, type={export_type}, date_from={date_from}, quarter={quarter_label}")
    
    if not section_id:
        messages.error(request, 'No section selected.')
        return redirect('teachers-attendance')
    
    try:
        section = Section.objects.get(id=section_id)
    except Section.DoesNotExist:
        messages.error(request, f'Section with ID {section_id} not found.')
        return redirect('teachers-attendance')
    
    school_year = SchoolYear.objects.filter(is_current=True).first()
    if not school_year:
        school_year = SchoolYear.objects.first()
    
    if not school_year:
        messages.error(request, 'No school year found.')
        return redirect('teachers-attendance')
    
    enrollments = Enrollment.objects.filter(
        section=section, 
        status='Enrolled'
    ).select_related('student').order_by('student__last_name')
    
    if not enrollments.exists():
        messages.warning(request, f'No students found in section {section.section_name}.')
        return redirect('teachers-attendance')
    
    # Determine date range
    start_date = None
    end_date = None
    period_label = ""
    
    if export_type == 'daily' and date_from:
        start_date = date.fromisoformat(date_from)
        end_date = start_date
        period_label = start_date.strftime('%B %d, %Y')
    elif export_type == 'monthly' and date_from:
        start_date = date.fromisoformat(date_from)
        end_date = start_date.replace(day=monthrange(start_date.year, start_date.month)[1])
        period_label = start_date.strftime('%B %Y')
    elif export_type == 'quarterly':
        quarter = Quarter.objects.filter(school_year=school_year, quarter_label=quarter_label).first()
        if quarter:
            start_date = quarter.date_start
            end_date = quarter.date_end
            period_label = f"{quarter.quarter_label} - {quarter.date_start.strftime('%b %d')} to {quarter.date_end.strftime('%b %d, %Y')}"
        else:
            start_date = school_year.date_start
            end_date = school_year.date_end
            period_label = f"Quarter {quarter_label} (Not found, using school year)"
    else:  # yearly/school year
        start_date = school_year.date_start
        end_date = school_year.date_end
        period_label = f"School Year {school_year.year_label}"
    
    if not start_date or not end_date:
        messages.error(request, 'Invalid date range.')
        return redirect('teachers-attendance')
    
    # Get all unique dates in range
    if export_type == 'daily':
        all_dates = [start_date]
    else:
        delta = end_date - start_date
        all_dates = [start_date + timedelta(days=i) for i in range(delta.days + 1)]
    
    # Collect attendance data
    attendance_data = []
    summary_stats = {
        'total_students': enrollments.count(),
        'total_present': 0,
        'total_absent': 0,
        'total_late': 0,
        'total_excused': 0,
        'total_days': len(all_dates),
    }
    
    for enrollment in enrollments:
        student = enrollment.student
        records = AttendanceRecord.objects.filter(
            enrollment=enrollment,
            date__gte=start_date,
            date__lte=end_date
        )
        record_dict = {r.date: r for r in records}
        
        daily_statuses = []
        for d in all_dates:
            record = record_dict.get(d)
            if record:
                status = record.status
                daily_statuses.append({
                    'status': status,
                    'time_in': record.time_in.strftime('%H:%M') if record.time_in else '',
                    'minutes_late': record.minutes_late,
                    'remarks': record.remarks
                })
            else:
                daily_statuses.append({'status': 'Not Recorded', 'time_in': '', 'minutes_late': 0, 'remarks': ''})
        
        student_present = sum(1 for r in daily_statuses if r['status'] == 'Present')
        student_absent = sum(1 for r in daily_statuses if r['status'] == 'Absent')
        student_late = sum(1 for r in daily_statuses if r['status'] == 'Late')
        student_excused = sum(1 for r in daily_statuses if r['status'] == 'Excused')
        student_attendance_rate = round((student_present / len(all_dates)) * 100, 2) if len(all_dates) > 0 else 0
        
        summary_stats['total_present'] += student_present
        summary_stats['total_absent'] += student_absent
        summary_stats['total_late'] += student_late
        summary_stats['total_excused'] += student_excused
        
        attendance_data.append({
            'lrn': student.lrn or '',
            'name': f"{student.last_name}, {student.first_name} {student.middle_name or ''}".strip(),
            'sex': student.sex or 'N/A',
            'daily_statuses': daily_statuses,
            'present': student_present,
            'absent': student_absent,
            'late': student_late,
            'excused': student_excused,
            'attendance_rate': student_attendance_rate,
        })
    
    # Create Excel workbook
    wb = Workbook()
    
    # Styles
    header_font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
    header_fill = PatternFill(start_color='5EA173', end_color='5EA173', fill_type='solid')
    present_fill = PatternFill(start_color='D4EDDA', end_color='D4EDDA', fill_type='solid')
    absent_fill = PatternFill(start_color='F8D7DA', end_color='F8D7DA', fill_type='solid')
    late_fill = PatternFill(start_color='FFF3CD', end_color='FFF3CD', fill_type='solid')
    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    
    # ============================================================
    # SHEET 1: ATTENDANCE DETAIL
    # ============================================================
    ws_detail = wb.active
    ws_detail.title = "Attendance Details"
    
    num_date_columns = len(all_dates)
    total_columns = 4 + num_date_columns + 5  # LRN, Name, Sex + dates + Present, Absent, Late, Excused, Rate
    
    # Title row
    ws_detail.merge_cells(start_row=1, start_column=1, end_row=1, end_column=total_columns)
    title_cell = ws_detail.cell(row=1, column=1, value=f"ATTENDANCE REPORT - {section.section_name} ({section.grade_level.grade_name})")
    title_cell.font = Font(name='Calibri', size=14, bold=True)
    title_cell.alignment = Alignment(horizontal='center')
    
    # School year and period
    ws_detail.cell(row=2, column=1, value=f"School Year: {school_year.year_label}").font = Font(bold=True)
    ws_detail.cell(row=2, column=2, value=f"Period: {period_label}")
    ws_detail.cell(row=2, column=3, value=f"Total Days: {summary_stats['total_days']}")
    ws_detail.cell(row=2, column=4, value=f"Generated: {date.today().strftime('%Y-%m-%d %H:%M')}")
    
    # Header row
    row = 4
    headers = ['LRN', 'Student Name', 'Sex']
    for d in all_dates:
        headers.append(d.strftime('%a\n%b %d'))
    headers.extend(['Present', 'Absent', 'Late', 'Excused', 'Attendance %'])
    
    for col, header in enumerate(headers, 1):
        cell = ws_detail.cell(row=row, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
        cell.border = thin_border
    
    # Data rows
    for data_row in attendance_data:
        row += 1
        ws_detail.cell(row=row, column=1, value=data_row['lrn']).border = thin_border
        ws_detail.cell(row=row, column=2, value=data_row['name']).border = thin_border
        ws_detail.cell(row=row, column=3, value=data_row['sex']).border = thin_border
        
        col = 4
        for daily in data_row['daily_statuses']:
            cell = ws_detail.cell(row=row, column=col, value=daily['status'])
            cell.border = thin_border
            cell.alignment = Alignment(horizontal='center')
            
            if daily['status'] == 'Present':
                cell.fill = present_fill
            elif daily['status'] == 'Absent':
                cell.fill = absent_fill
            elif daily['status'] == 'Late':
                cell.fill = late_fill
            
            if daily['minutes_late'] > 0 and daily['status'] == 'Late':
                cell.value = f"Late\n({daily['minutes_late']} min)"
                cell.alignment = Alignment(horizontal='center', wrap_text=True)
            
            col += 1
        
        ws_detail.cell(row=row, column=col, value=data_row['present']).border = thin_border
        ws_detail.cell(row=row, column=col, value=data_row['present']).alignment = Alignment(horizontal='center')
        ws_detail.cell(row=row, column=col+1, value=data_row['absent']).border = thin_border
        ws_detail.cell(row=row, column=col+1, value=data_row['absent']).alignment = Alignment(horizontal='center')
        ws_detail.cell(row=row, column=col+2, value=data_row['late']).border = thin_border
        ws_detail.cell(row=row, column=col+2, value=data_row['late']).alignment = Alignment(horizontal='center')
        ws_detail.cell(row=row, column=col+3, value=data_row['excused']).border = thin_border
        ws_detail.cell(row=row, column=col+3, value=data_row['excused']).alignment = Alignment(horizontal='center')
        
        rate_cell = ws_detail.cell(row=row, column=col+4, value=data_row['attendance_rate'])
        rate_cell.border = thin_border
        rate_cell.alignment = Alignment(horizontal='center')
        if data_row['attendance_rate'] < 80:
            rate_cell.fill = absent_fill
        elif data_row['attendance_rate'] < 90:
            rate_cell.fill = late_fill
        else:
            rate_cell.fill = present_fill
    
    # Add total row
    row += 1
    ws_detail.cell(row=row, column=2, value="TOTAL").font = Font(bold=True)
    ws_detail.cell(row=row, column=col, value=summary_stats['total_present']).font = Font(bold=True)
    ws_detail.cell(row=row, column=col+1, value=summary_stats['total_absent']).font = Font(bold=True)
    ws_detail.cell(row=row, column=col+2, value=summary_stats['total_late']).font = Font(bold=True)
    ws_detail.cell(row=row, column=col+3, value=summary_stats['total_excused']).font = Font(bold=True)
    
    total_possible = summary_stats['total_students'] * summary_stats['total_days']
    avg_rate = round((summary_stats['total_present'] / total_possible) * 100, 2) if total_possible > 0 else 0
    ws_detail.cell(row=row, column=col+4, value=f"Avg: {avg_rate}%").font = Font(bold=True)
    
    # Set column widths using get_column_letter (FIXED)
    ws_detail.column_dimensions['A'].width = 18
    ws_detail.column_dimensions['B'].width = 35
    ws_detail.column_dimensions['C'].width = 8
    for i in range(num_date_columns):
        col_letter = get_column_letter(4 + i)
        ws_detail.column_dimensions[col_letter].width = 12
    for i in range(5):
        col_letter = get_column_letter(4 + num_date_columns + i)
        ws_detail.column_dimensions[col_letter].width = 12
    
    # ============================================================
    # SHEET 2: STUDENT SUMMARY
    # ============================================================
    ws_summary = wb.create_sheet("Student Summary")
    
    summary_headers = ['LRN', 'Student Name', 'Sex', 'Present', 'Absent', 'Late', 'Excused', 'Total Days', 'Attendance %', 'Status']
    for col, header in enumerate(summary_headers, 1):
        cell = ws_summary.cell(row=1, column=col, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal='center')
        cell.border = thin_border
    
    for row_idx, data_row in enumerate(attendance_data, 2):
        ws_summary.cell(row=row_idx, column=1, value=data_row['lrn']).border = thin_border
        ws_summary.cell(row=row_idx, column=2, value=data_row['name']).border = thin_border
        ws_summary.cell(row=row_idx, column=3, value=data_row['sex']).border = thin_border
        ws_summary.cell(row=row_idx, column=4, value=data_row['present']).border = thin_border
        ws_summary.cell(row=row_idx, column=5, value=data_row['absent']).border = thin_border
        ws_summary.cell(row=row_idx, column=6, value=data_row['late']).border = thin_border
        ws_summary.cell(row=row_idx, column=7, value=data_row['excused']).border = thin_border
        ws_summary.cell(row=row_idx, column=8, value=summary_stats['total_days']).border = thin_border
        
        rate_cell = ws_summary.cell(row=row_idx, column=9, value=data_row['attendance_rate'])
        rate_cell.border = thin_border
        rate_cell.alignment = Alignment(horizontal='center')
        
        status = 'Good Standing' if data_row['attendance_rate'] >= 90 else ('At Risk' if data_row['attendance_rate'] < 80 else 'Needs Improvement')
        status_cell = ws_summary.cell(row=row_idx, column=10, value=status)
        status_cell.border = thin_border
        status_cell.alignment = Alignment(horizontal='center')
        
        if data_row['attendance_rate'] >= 90:
            status_cell.fill = present_fill
            rate_cell.fill = present_fill
        elif data_row['attendance_rate'] >= 80:
            status_cell.fill = late_fill
            rate_cell.fill = late_fill
        else:
            status_cell.fill = absent_fill
            rate_cell.fill = absent_fill
    
    # Set column widths for summary sheet
    summary_widths = [18, 35, 8, 10, 10, 10, 10, 12, 14, 18]
    for col, width in enumerate(summary_widths, 1):
        ws_summary.column_dimensions[get_column_letter(col)].width = width
    
    # ============================================================
    # SHEET 3: MONTHLY SUMMARY (if multiple months)
    # ============================================================
    if export_type != 'daily' and len(all_dates) > 31:
        ws_monthly = wb.create_sheet("Monthly Summary")
        
        months_in_range = {}
        current = start_date
        while current <= end_date:
            month_key = current.strftime('%Y-%m')
            if month_key not in months_in_range:
                months_in_range[month_key] = {
                    'name': current.strftime('%B %Y'),
                    'present': 0,
                    'absent': 0,
                    'late': 0,
                    'excused': 0,
                    'count': 0
                }
            current += timedelta(days=1)
        
        for enrollment in enrollments:
            records = AttendanceRecord.objects.filter(
                enrollment=enrollment,
                date__gte=start_date,
                date__lte=end_date
            )
            for record in records:
                month_key = record.date.strftime('%Y-%m')
                if month_key in months_in_range:
                    months_in_range[month_key]['count'] += 1
                    if record.status == 'Present':
                        months_in_range[month_key]['present'] += 1
                    elif record.status == 'Absent':
                        months_in_range[month_key]['absent'] += 1
                    elif record.status == 'Late':
                        months_in_range[month_key]['late'] += 1
                    elif record.status == 'Excused':
                        months_in_range[month_key]['excused'] += 1
        
        monthly_headers = ['Month', 'Days Recorded', 'Present', 'Absent', 'Late', 'Excused', 'Attendance %']
        for col, header in enumerate(monthly_headers, 1):
            cell = ws_monthly.cell(row=1, column=col, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = Alignment(horizontal='center')
            cell.border = thin_border
        
        for row_idx, (month_key, data) in enumerate(months_in_range.items(), 2):
            ws_monthly.cell(row=row_idx, column=1, value=data['name']).border = thin_border
            ws_monthly.cell(row=row_idx, column=2, value=data['count']).border = thin_border
            ws_monthly.cell(row=row_idx, column=3, value=data['present']).border = thin_border
            ws_monthly.cell(row=row_idx, column=4, value=data['absent']).border = thin_border
            ws_monthly.cell(row=row_idx, column=5, value=data['late']).border = thin_border
            ws_monthly.cell(row=row_idx, column=6, value=data['excused']).border = thin_border
            
            rate = round((data['present'] / data['count']) * 100, 2) if data['count'] > 0 else 0
            rate_cell = ws_monthly.cell(row=row_idx, column=7, value=rate)
            rate_cell.border = thin_border
            if rate < 80:
                rate_cell.fill = absent_fill
            elif rate < 90:
                rate_cell.fill = late_fill
            else:
                rate_cell.fill = present_fill
        
        for col in range(1, 8):
            ws_monthly.column_dimensions[get_column_letter(col)].width = 15
    
    # Prepare response
    output = BytesIO()
    wb.save(output)
    output.seek(0)
    
    filename = f"Attendance_Report_{section.section_name}_{period_label.replace(' ', '_').replace('/', '-')}.xlsx"
    
    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    
    return response

# ============================================================
# SCHOOL FORMS (unchanged)
# ============================================================
@login_required
def school_forms(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')

    teacher = request.user
    today = date.today()
    section_id = request.GET.get('section_id')
    quarter_label = request.GET.get('quarter', 'Q3')
    sy_id = request.GET.get('school_year')

    FORM_ICONS = {
        'SF1': 'fi-rr-users', 'SF2': 'fi-rr-calendar-check',
        'SF3': 'fi-rr-book', 'SF4': 'fi-rr-chart-line-up',
        'SF5': 'fi-rr-graduation-cap', 'SF9': 'fi-rr-id-card',
        'SF10': 'fi-rr-archive',
    }
    TEACHER_VISIBLE = ['SF1', 'SF2', 'SF3', 'SF4', 'SF5', 'SF9', 'SF10']

    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher, is_active=True
    ).select_related('section__grade_level', 'section__strand', 'subject', 'school_year')
    has_data = class_assignments.exists()

    classes_data = []
    seen = set()
    advisory_section = None
    for ca in class_assignments:
        if ca.section_id not in seen:
            seen.add(ca.section_id)
            sc = Enrollment.objects.filter(section_id=ca.section_id, status='Enrolled').count()
            classes_data.append({
                'section_id': ca.section_id, 'section_name': str(ca.section),
                'grade_name': ca.section.grade_level.grade_name,
                'student_count': sc, 'is_advisory': ca.is_advisory,
            })
            if ca.is_advisory and advisory_section is None:
                advisory_section = ca.section

    current_sy_obj = None
    if sy_id:
        try:
            current_sy_obj = SchoolYear.objects.get(id=sy_id)
        except SchoolYear.DoesNotExist:
            pass
    if not current_sy_obj:
        current_sy_obj = SchoolYear.objects.filter(is_current=True).first()

    available_sy = [{'id': sy.id, 'label': str(sy)} for sy in SchoolYear.objects.filter(
        id__in=class_assignments.values_list('school_year_id', flat=True)
    ).order_by('-year_start')]
    current_sy = str(current_sy_obj) if current_sy_obj else '—'
    current_sy_id = current_sy_obj.id if current_sy_obj else None

    selected_section_obj = None
    if section_id:
        selected_section_obj = Section.objects.filter(
            id=section_id, class_assignments__in=class_assignments
        ).distinct().first()
    if not selected_section_obj:
        selected_section_obj = advisory_section or (class_assignments.first().section if has_data else None)
    selected_section = str(selected_section_obj) if selected_section_obj else '—'
    selected_section_id = selected_section_obj.id if selected_section_obj else None

    quarter_obj = None
    quarter_options = []
    if current_sy_obj:
        for q in Quarter.objects.filter(school_year=current_sy_obj).order_by('quarter_number'):
            quarter_options.append({
                'label': q.quarter_label, 'name': f'Quarter {q.quarter_number}',
                'is_current': q.is_current_quarter, 'is_locked': q.is_grades_locked,
            })
        quarter_obj = Quarter.objects.filter(
            school_year=current_sy_obj, quarter_label=quarter_label
        ).first()

    quarter_name = f'Quarter {quarter_obj.quarter_number}' if quarter_obj else '—'
    is_quarter_locked = quarter_obj.is_grades_locked if quarter_obj else False

    forms_status = []
    total_completed = 0
    readiness = {}
    data_source_stats = {}
    enrolled_count = 0
    total_grades = 0
    finalized_grades = 0
    lrn_complete = 0
    att_days = 0

    if selected_section_obj and current_sy_obj:
        enrolled = Enrollment.objects.filter(section=selected_section_obj, status='Enrolled')
        enrolled_count = enrolled.count()
        lrn_complete = enrolled.exclude(student__lrn__isnull=True).exclude(student__lrn='').count()

        if quarter_obj:
            total_grades = GradeComponent.objects.filter(
                enrollment__section=selected_section_obj, quarter=quarter_obj
            ).count()
            finalized_grades = GradeComponent.objects.filter(
                enrollment__section=selected_section_obj, quarter=quarter_obj,
                validation_status='Finalized'
            ).count()
            att_days = AttendanceRecord.objects.filter(
                enrollment__section=selected_section_obj,
                date__gte=quarter_obj.date_start, date__lte=quarter_obj.date_end
            ).values('date').distinct().count()

        readiness = {
            'students': {'total': enrolled_count, 'complete': enrolled_count,
                         'status': 'complete' if enrolled_count > 0 else 'error'},
            'lrn': {'total': enrolled_count, 'complete': lrn_complete,
                    'missing': enrolled_count - lrn_complete,
                    'status': 'complete' if lrn_complete == enrolled_count else 'warning'},
            'grades': {'total': total_grades, 'complete': finalized_grades,
                       'missing': total_grades - finalized_grades,
                       'status': 'complete' if finalized_grades == total_grades and total_grades > 0
                       else ('warning' if finalized_grades > 0 else 'error')},
            'attendance': {'days_recorded': att_days,
                           'status': 'complete' if att_days > 0 else 'warning'},
        }

        guardian_count = Guardian.objects.filter(
            student__enrollments__section=selected_section_obj,
            student__enrollments__status='Enrolled',
            student__enrollments__school_year=current_sy_obj,
            is_primary_guardian=True
        ).count()
        promo_count = PromotionRecommendation.objects.filter(
            enrollment__section=selected_section_obj,
            enrollment__school_year=current_sy_obj
        ).count()
        total_att_records = 0
        if quarter_obj:
            total_att_records = AttendanceRecord.objects.filter(
                enrollment__section=selected_section_obj,
                date__gte=quarter_obj.date_start, date__lte=quarter_obj.date_end
            ).count()
        expected_att = enrolled_count * att_days if att_days > 0 else 0

        def _status(c, t):
            if t == 0: return 'missing'
            if c >= t: return 'complete'
            return 'partial'

        data_source_stats = {
            'enrollment_status': _status(enrolled_count, enrolled_count),
            'enrollment_count': f'{enrolled_count}/{enrolled_count}',
            'enrollment_note': 'All students verified' if enrolled_count > 0 else 'No enrollment data',
            'lrn_status': _status(lrn_complete, enrolled_count),
            'lrn_count': f'{lrn_complete}/{enrolled_count}',
            'lrn_note': 'All LRNs complete' if lrn_complete == enrolled_count else f'{enrolled_count - lrn_complete} missing',
            'guardian_status': _status(guardian_count, enrolled_count),
            'guardian_count': f'{guardian_count}/{enrolled_count}',
            'guardian_note': 'All guardians on file' if guardian_count == enrolled_count else f'{enrolled_count - guardian_count} missing',
            'attendance_status': _status(total_att_records, expected_att) if expected_att > 0 else 'missing',
            'attendance_count': f'{total_att_records}/{expected_att}' if expected_att > 0 else '0/0',
            'attendance_note': f'{att_days} days recorded' if att_days > 0 else 'No attendance data',
            'grades_status': _status(finalized_grades, total_grades) if total_grades > 0 else 'missing',
            'grades_count': f'{finalized_grades}/{total_grades}' if total_grades > 0 else '0/0',
            'grades_note': 'All grades finalized' if finalized_grades >= total_grades and total_grades > 0 else f'{total_grades - finalized_grades} pending',
            'promo_status': _status(promo_count, enrolled_count) if enrolled_count > 0 else 'missing',
            'promo_count': f'{promo_count}/{enrolled_count}',
            'promo_note': 'Ready for review' if promo_count > 0 else 'Not yet started',
        }

        all_forms = SchoolForm.objects.filter(is_active=True, form_code__in=TEACHER_VISIBLE).order_by('form_code')
        for form in all_forms:
            sub_q = {'school_form': form, 'section': selected_section_obj, 'school_year': current_sy_obj}
            if form.form_code in ['SF2', 'SF9']:
                sub_q['quarter'] = quarter_obj
            submission = FormSubmission.objects.filter(**sub_q).first()

            status = 'not_started'
            status_text = 'Not Started'
            status_class = 'pending'
            msg = ''

            is_form_locked = FormCompliance.objects.filter(
                school_form=form, school_year=current_sy_obj,
                status__in=['Locked', 'Closed']
            ).exists()

            if form.form_code == 'SF10' or is_form_locked:
                status = 'locked'
                status_text = 'Registrar Only' if form.form_code == 'SF10' else 'Locked by Registrar'
                status_class = 'locked'
            elif submission and submission.status == 'Approved':
                status = 'completed'; status_text = 'Approved'; status_class = 'completed'
                total_completed += 1
            elif submission and submission.status in ['Submitted', 'Reviewed']:
                status = 'submitted'; status_text = 'Under Review'; status_class = 'submitted'
            elif submission and submission.status == 'Returned':
                status = 'returned'; status_text = 'Returned — Fix & Resubmit'; status_class = 'returned'
            elif submission and submission.status == 'Rejected':
                status = 'returned'; status_text = 'Rejected — Fix & Resubmit'; status_class = 'returned'
            else:
                if form.form_code == 'SF1':
                    if enrolled_count > 0:
                        status = 'ready'; status_text = 'Ready to Review'; status_class = 'ready'
                        if enrolled_count - lrn_complete > 0:
                            msg = f'{enrolled_count - lrn_complete} students missing LRN'
                elif form.form_code == 'SF2':
                    if att_days > 0:
                        status = 'ready'; status_text = 'Ready to Generate'; status_class = 'ready'
                    else:
                        msg = 'No attendance data yet'
                elif form.form_code == 'SF5':
                    if promo_count > 0:
                        status = 'ready'; status_text = f'{promo_count} recommendations ready'; status_class = 'ready'
                    else:
                        msg = 'Requires final grades first'
                elif form.form_code == 'SF9':
                    if total_grades > 0:
                        pct = round((finalized_grades / total_grades) * 100) if total_grades > 0 else 0
                        if finalized_grades == total_grades:
                            status = 'ready'; status_text = 'Ready to Generate'; status_class = 'ready'
                        else:
                            status = 'partial'; status_text = f'{pct}% grades finalized'; status_class = 'partial'
                    else:
                        msg = 'No grades encoded yet'
                else:
                    status = 'ready'; status_text = 'Available'; status_class = 'ready'

            forms_status.append({
                'id': form.id, 'code': form.form_code, 'name': form.form_name,
                'short': form.form_code, 'icon': FORM_ICONS.get(form.form_code, 'fi-rr-document'),
                'status': status, 'status_text': status_text, 'status_class': status_class,
                'status_message': msg,
                'submission_id': submission.id if submission else None,
                'is_locked': status in ['locked'],
            })

    total_forms = len(forms_status)

    recent_submissions = []
    if has_data:
        teacher_sections = class_assignments.values_list('section_id', flat=True)
        for sub in FormSubmission.objects.filter(
            submitted_by=teacher, section_id__in=teacher_sections
        ).select_related('school_form', 'section', 'quarter').order_by('-updated_at')[:10]:
            recent_submissions.append({
                'form_code': sub.school_form.form_code,
                'form_name': sub.school_form.form_name,
                'section': str(sub.section) if sub.section else 'N/A',
                'quarter': sub.quarter.quarter_label if sub.quarter else 'Annual',
                'date': sub.updated_at.strftime('%b %d, %Y'),
                'status': sub.get_status_display(),
                'status_class': 'completed' if sub.status == 'Approved'
                else ('submitted' if sub.status in ['Submitted', 'Reviewed']
                      else ('returned' if sub.status == 'Returned' else 'pending')),
            })

    pending_corrections = []
    for corr in DataCorrectionRequest.objects.filter(
        requested_by=teacher, status='Pending'
    ).order_by('-created_at')[:5]:
        pending_corrections.append({
            'id': corr.id, 'entity_type': corr.entity_type,
            'field': corr.field_to_correct, 'current': corr.current_value,
            'proposed': corr.proposed_value, 'date': corr.created_at.strftime('%b %d'),
        })

    form_notifications = list(Notification.objects.filter(
        recipient=teacher,
        notification_type__in=[
            'FORM_SUBMISSION_DEADLINE', 'FORM_RETURNED', 'FORM_APPROVED',
            'GRADE_RETURNED', 'GRADE_VALIDATED', 'GRADE_DEADLINE_REMINDER',
            'PROMOTION_REVIEW_NEEDED'
        ],
        is_read=False,
    ).order_by('-created_at')[:5])

    section_students = []
    if selected_section_obj:
        for enr in Enrollment.objects.filter(
            section=selected_section_obj, status='Enrolled'
        ).select_related('student').order_by('student__last_name'):
            st = enr.student
            g = Guardian.objects.filter(student=st, is_primary_guardian=True).first()
            section_students.append({
                'lrn': st.lrn,
                'name': f"{st.last_name}, {st.first_name}",
                'sex': st.sex,
                'birth_date': str(st.birth_date) if st.birth_date else '',
                'guardian': f"{g.last_name}, {g.first_name}" if g else 'Not recorded',
            })

    context = {
        'has_data': has_data, 'classes_data': classes_data,
        'selected_section': selected_section, 'selected_section_id': selected_section_id,
        'current_sy': current_sy, 'current_sy_id': current_sy_id,
        'available_sy': available_sy, 'quarter_label': quarter_label,
        'quarter_name': quarter_name, 'quarter_options': quarter_options,
        'is_quarter_locked': is_quarter_locked, 'forms_status': forms_status,
        'total_forms': total_forms, 'total_completed': total_completed,
        'readiness': readiness, 'data_source_stats_json': json.dumps(data_source_stats),
        'recent_submissions': recent_submissions, 'pending_corrections': pending_corrections,
        'form_notifications': form_notifications, 'section_students': section_students,
        'today': today,
    }
    return render(request, 'teachers/forms/forms.html', context)


# ============================================================
# CERTIFY FORM (unchanged)
# ============================================================
@login_required
def certify_form(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied.')
        return redirect('signin')

    if request.method != 'POST':
        return redirect('teachers-forms')

    form_id = request.POST.get('form_id')
    section_id = request.POST.get('section_id')
    sy_id = request.POST.get('school_year', '')
    quarter_label = request.POST.get('quarter', 'Q3')
    certify_all_sf9 = request.POST.get('certify_all_sf9') == 'true'

    form = get_object_or_404(SchoolForm, id=form_id)
    section = get_object_or_404(Section, id=section_id)
    
    school_year = None
    if sy_id:
        try:
            school_year = SchoolYear.objects.get(id=sy_id)
        except (SchoolYear.DoesNotExist, ValueError):
            school_year = SchoolYear.objects.filter(is_current=True).first()
    else:
        school_year = SchoolYear.objects.filter(is_current=True).first()
    
    if not school_year:
        messages.error(request, 'No active school year found.')
        return redirect('teachers-forms')

    quarter = Quarter.objects.filter(
        school_year=school_year, quarter_label=quarter_label
    ).first() if quarter_label else None

    if certify_all_sf9 and form.form_code == 'SF9':
        enrolled = Enrollment.objects.filter(
            section=section, status='Enrolled'
        ).select_related('student')
        
        count = 0
        for enr in enrolled:
            submission, created = FormSubmission.objects.get_or_create(
                school_form=form,
                section=section,
                school_year=school_year,
                quarter=quarter,
                submitted_by=request.user,
                defaults={
                    'status': 'Submitted',
                    'submitted_date': timezone.now(),
                }
            )
            if created or submission.status in ['Draft', 'Returned', 'Rejected']:
                if not created:
                    submission.status = 'Submitted'
                    submission.submitted_date = timezone.now()
                    submission.save()
                count += 1

        messages.success(request, f'{count} SF9 report cards submitted to Registrar for review.')
        return redirect(request.META.get('HTTP_REFERER', 'teachers-forms'))

    filter_q = {'school_form': form, 'section': section, 'school_year': school_year}
    if form.form_code in ['SF2', 'SF9']:
        filter_q['quarter'] = quarter

    submission, created = FormSubmission.objects.get_or_create(
        **filter_q,
        defaults={'submitted_by': request.user, 'status': 'Submitted', 'submitted_date': timezone.now()}
    )

    if not created:
        if submission.status in ['Draft', 'Returned', 'Rejected']:
            submission.status = 'Submitted'
            submission.submitted_by = request.user
            submission.submitted_date = timezone.now()
            submission.save()
        else:
            messages.warning(request, f'{form.form_code} is already {submission.get_status_display()}.')
            return redirect(request.META.get('HTTP_REFERER', 'teachers-forms'))

    messages.success(request, f'{form.form_code} submitted to Registrar for review.')
    return redirect(request.META.get('HTTP_REFERER', 'teachers-forms'))


# ============================================================
# SUBMIT CORRECTION (unchanged)
# ============================================================
@login_required
def submit_correction(request):
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)
    try:
        data = json.loads(request.body)
        DataCorrectionRequest.objects.create(
            requested_by=request.user,
            entity_type='Student',
            entity_id=data.get('student_lrn', ''),
            field_to_correct=data.get('field', ''),
            current_value=data.get('current_value', ''),
            proposed_value=data.get('proposed_value', ''),
            justification=data.get('justification', ''),
            status='Pending',
        )
        return JsonResponse({'success': True})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================
# SF9 GRADES API (unchanged)
# ============================================================
@login_required
def sf9_grades_api(request):
    if request.method != 'POST':
        return JsonResponse({'success': False}, status=405)
    try:
        data = json.loads(request.body)
        lrn = data.get('lrn', '')
        student = Student.objects.filter(lrn=lrn).first()
        if not student:
            return JsonResponse({'success': False, 'error': 'Student not found'})
        enrollment = Enrollment.objects.filter(
            student=student, status='Enrolled'
        ).select_related('section').first()
        if not enrollment:
            return JsonResponse({'success': False, 'error': 'Not enrolled'})
        quarter_label = request.GET.get('quarter', 'Q3')
        sy = SchoolYear.objects.filter(is_current=True).first()
        quarter = Quarter.objects.filter(school_year=sy, quarter_label=quarter_label).first() if sy else None
        subjects = []
        total = 0
        count = 0
        if quarter:
            grades = GradeComponent.objects.filter(
                enrollment=enrollment, quarter=quarter
            ).select_related('subject')
            for gc in grades:
                g = gc.transmuted_grade or 0
                subjects.append({'name': gc.subject.subject_name, 'grade': g})
                total += g
                count += 1
        avg = round(total / count) if count > 0 else 0
        passed = avg >= 75
        return JsonResponse({'success': True, 'subjects': subjects, 'average': avg, 'passed': passed})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def transmute_grade(initial_grade):
    """Transmute initial grade using DepEd table"""
    if initial_grade >= 100:
        return 100
    elif initial_grade >= 98.4:
        return 99
    elif initial_grade >= 96.8:
        return 98
    elif initial_grade >= 95.2:
        return 97
    elif initial_grade >= 93.6:
        return 96
    elif initial_grade >= 92:
        return 95
    elif initial_grade >= 90.4:
        return 94
    elif initial_grade >= 88.8:
        return 93
    elif initial_grade >= 87.2:
        return 92
    elif initial_grade >= 85.6:
        return 91
    elif initial_grade >= 84:
        return 90
    elif initial_grade >= 82.4:
        return 89
    elif initial_grade >= 80.8:
        return 88
    elif initial_grade >= 79.2:
        return 87
    elif initial_grade >= 77.6:
        return 86
    elif initial_grade >= 76:
        return 85
    elif initial_grade >= 74.4:
        return 84
    elif initial_grade >= 72.8:
        return 83
    elif initial_grade >= 71.2:
        return 82
    elif initial_grade >= 69.6:
        return 81
    elif initial_grade >= 68:
        return 80
    elif initial_grade >= 66.4:
        return 79
    elif initial_grade >= 64.8:
        return 78
    elif initial_grade >= 63.2:
        return 77
    elif initial_grade >= 61.6:
        return 76
    elif initial_grade >= 60:
        return 75
    else:
        return 60


# ============================================================
# SAVE GRADE CELL (AJAX) - unchanged
# ============================================================

@csrf_exempt
@login_required
def save_grade_cell(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    try:
        data = json.loads(request.body)
        enrollment_id = data.get('enrollment_id')
        subject_id = data.get('subject_id')
        quarter_id = data.get('quarter_id')
        component = data.get('component')
        value = data.get('value')

        if value == '' or value is None:
            value = None
        else:
            value = float(value)
            if value < 0 or value > 100:
                return JsonResponse({'success': False, 'error': 'Grade must be between 0 and 100'})

        enrollment = Enrollment.objects.get(id=enrollment_id)
        subject = Subject.objects.get(id=subject_id)
        quarter = Quarter.objects.get(id=quarter_id)

        gc, created = GradeComponent.objects.get_or_create(
            enrollment=enrollment,
            subject=subject,
            quarter=quarter,
            defaults={
                'encoded_by_id': request.user.id,
                'encoding_date': timezone.now(),
            }
        )

        WW_WEIGHT = 0.25
        PT_WEIGHT = 0.45
        QA_WEIGHT = 0.30

        if component == 'ww':
            gc.written_work_raw = value
            gc.written_work_weighted = round(value * WW_WEIGHT, 2) if value is not None else None
        elif component == 'pt':
            gc.performance_task_raw = value
            gc.performance_task_weighted = round(value * PT_WEIGHT, 2) if value is not None else None
        elif component == 'qa':
            gc.quarterly_assessment_raw = value
            gc.quarterly_assessment_weighted = round(value * QA_WEIGHT, 2) if value is not None else None

        ww = gc.written_work_raw
        pt = gc.performance_task_raw
        qa = gc.quarterly_assessment_raw

        if ww is not None and pt is not None and qa is not None:
            gc.initial_grade = (ww * WW_WEIGHT) + (pt * PT_WEIGHT) + (qa * QA_WEIGHT)
            gc.initial_grade = round(gc.initial_grade, 2)
            gc.transmuted_grade = transmute_grade(gc.initial_grade)
        else:
            gc.initial_grade = None
            gc.transmuted_grade = None

        gc.encoding_date = timezone.now()
        gc.encoded_by_id = request.user.id
        gc.save()

        return JsonResponse({
            'success': True,
            'initial_grade': gc.initial_grade,
            'transmuted_grade': gc.transmuted_grade,
        })
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ============================================================
# ✅ IMPORT EXCEL GRADES - FIXED for dynamic quarters
# ============================================================

# ============================================================
# IMPORT EXCEL GRADES
# ============================================================

@csrf_exempt
@login_required
def import_excel_grades(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    try:
        content_type = request.content_type or ''

        # ── BRANCH 1: JSON from preview modal ────────────────────────────────
        if 'application/json' in content_type:
            data = json.loads(request.body)
            section_id = data.get('section_id')
            subject_id = data.get('subject_id')
            rows = data.get('rows', [])

            if not rows:
                return JsonResponse({'success': False, 'error': 'No rows to import'})

            subject = Subject.objects.get(id=subject_id)
            current_sy = SchoolYear.objects.filter(is_current=True).first()
            if not current_sy:
                return JsonResponse({'success': False, 'error': 'No active school year found'})

            saved_count = 0
            errors = []

            for row in rows:
                enrollment_id = row.get('enrollment_id')
                if not enrollment_id:
                    continue

                try:
                    enrollment = Enrollment.objects.get(id=enrollment_id)
                    quarters_saved = 0

                    for key, value in row.items():
                        if not key.endswith('_grade') or key == 'final_grade':
                            continue
                        if value is None or value == '':
                            continue

                        quarter_label = key.replace('_grade', '').upper()

                        try:
                            grade_quarter = Quarter.objects.get(
                                school_year=current_sy,
                                quarter_label=quarter_label
                            )

                            grade_value = round(float(value), 2)
                            transmuted_value = int(round(grade_value))
                            transmuted_value = max(60, min(100, transmuted_value))

                            if transmuted_value >= 90:
                                descriptor = 'Outstanding'
                            elif transmuted_value >= 85:
                                descriptor = 'Very_Satisfactory'
                            elif transmuted_value >= 80:
                                descriptor = 'Satisfactory'
                            elif transmuted_value >= 75:
                                descriptor = 'Fairly_Satisfactory'
                            else:
                                descriptor = 'Did_Not_Meet_Expectations'

                            _upsert_grade(
                                enrollment, subject, grade_quarter,
                                transmuted_value, grade_value, descriptor, request.user
                            )
                            quarters_saved += 1

                        except Quarter.DoesNotExist:
                            errors.append('Quarter {} not found'.format(quarter_label))
                        except (ValueError, TypeError) as e:
                            errors.append('Invalid grade for {}: {} — {}'.format(quarter_label, value, str(e)))
                        except Exception as e:
                            errors.append('Error saving {} for enrollment {}: {}'.format(
                                quarter_label, enrollment_id, str(e)))

                    if quarters_saved > 0:
                        saved_count += 1
                    else:
                        errors.append('No valid quarter grades for enrollment {}'.format(enrollment_id))

                except Enrollment.DoesNotExist:
                    errors.append('Enrollment ID {} not found'.format(enrollment_id))
                except Exception as e:
                    errors.append('Row error (enrollment {}): {}'.format(enrollment_id, str(e)))

            response_data = {
                'success': True,
                'imported_count': saved_count,
                'message': 'Successfully imported grades for {} students'.format(saved_count),
            }
            if errors:
                response_data['warnings'] = errors[:20]
                response_data['message'] += ' ({} warnings)'.format(len(errors))

            return JsonResponse(response_data)

        # ── BRANCH 2: Direct file upload ─────────────────────────────────────
        else:
            excel_file = request.FILES.get('excel_file')
            if not excel_file:
                return JsonResponse({'success': False, 'error': 'No file uploaded'})

            section_id = request.POST.get('section_id')
            subject_id = request.POST.get('subject_id')

            if not section_id or not subject_id:
                return JsonResponse({'success': False, 'error': 'Missing section_id or subject_id'})

            file_content = excel_file.read()
            wb = load_workbook(BytesIO(file_content))
            sheet = wb.active

            enrollments = Enrollment.objects.filter(
                section_id=section_id, status='Enrolled'
            ).select_related('student').order_by('student__last_name')

            if not enrollments.exists():
                return JsonResponse({'success': False, 'error': 'No enrolled students found'})

            subject = Subject.objects.get(id=subject_id)
            current_sy = SchoolYear.objects.filter(is_current=True).first()
            if not current_sy:
                return JsonResponse({'success': False, 'error': 'No active school year found'})

            student_map, name_variants = _build_student_maps(enrollments)

            name_col, quarter_columns, _ = _detect_columns(sheet)

            if not quarter_columns:
                quarter_columns = {'Q3': 4}

            import re
            start_row = _find_section_start(sheet, name_col, 'MALE')

            row, saved_count, warnings = _process_sheet_rows(
                sheet, start_row, name_col, quarter_columns,
                student_map, name_variants, subject, current_sy, request.user, stop_at='FEMALE'
            )

            female_start = _find_section_start(sheet, name_col, 'FEMALE', after_row=row)
            if female_start:
                _, saved2, warn2 = _process_sheet_rows(
                    sheet, female_start, name_col, quarter_columns,
                    student_map, name_variants, subject, current_sy, request.user, stop_at=None
                )
                saved_count += saved2
                warnings.extend(warn2)

            response_data = {
                'success': True,
                'imported_count': saved_count,
                'warnings': warnings[:50] if warnings else [],
                'message': 'Successfully imported grades for {} students'.format(saved_count),
                'quarters_detected': list(quarter_columns.keys()),
            }
            if warnings:
                response_data['message'] += ' ({} warnings)'.format(len(warnings))

            return JsonResponse(response_data)

    except Subject.DoesNotExist:
        return JsonResponse({'success': False, 'error': 'Subject not found'}, status=404)
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)
            
# ============================================================
# EXPORT EXCEL TEMPLATE (unchanged)
# ============================================================

@login_required
def export_excel_template(request):
    section_id = request.GET.get('section_id')
    subject_id = request.GET.get('subject_id')
    quarter_label = request.GET.get('quarter', 'Q3')
    template_type = request.GET.get('type', 'semestral')

    section = get_object_or_404(Section, id=section_id)
    subject = get_object_or_404(Subject, id=subject_id)

    enrollments = Enrollment.objects.filter(
        section=section, status='Enrolled'
    ).select_related('student').order_by('student__sex', 'student__last_name', 'student__first_name')

    male_students = [e for e in enrollments if e.student.sex == 'M']
    female_students = [e for e in enrollments if e.student.sex == 'F']

    quarter_num = int(quarter_label[1])
    semester_num = 1 if quarter_num <= 2 else 2
    quarter_name_map = {1: 'FIRST QUARTER', 2: 'SECOND QUARTER', 3: 'THIRD QUARTER', 4: 'FOURTH QUARTER'}

    if template_type == 'quarterly':
        return _generate_quarterly_xlsx(section, subject, quarter_label, quarter_name_map[quarter_num], male_students, female_students)
    else:
        return _generate_semestral_xlsx(section, subject, semester_num, male_students, female_students)


def _generate_semestral_xlsx(section, subject, semester_num, male_students, female_students):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill

    wb = Workbook()
    ws = wb.active
    ws.title = "Semestral Grade"

    semester_text = f"{semester_num}ST" if semester_num == 1 else f"{semester_num}ND"
    q1_name = "FIRST QUARTER" if semester_num == 1 else "THIRD QUARTER"
    q2_name = "SECOND QUARTER" if semester_num == 1 else "FOURTH QUARTER"
    grade_section = f"{section.grade_level.grade_name} - {section.section_name}" if section.grade_level else section.section_name
    subject_name = subject.subject_name if subject else ""
    school_year = SchoolYear.objects.filter(is_current=True).first()
    sy_label = str(school_year) if school_year else "2026-2027"

    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    header_fill = PatternFill(start_color='D9EAD3', end_color='D9EAD3', fill_type='solid')
    col_header_fill = PatternFill(start_color='E8F0FE', end_color='E8F0FE', fill_type='solid')
    male_fill = PatternFill(start_color='CFE2F3', end_color='CFE2F3', fill_type='solid')
    female_fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')

    ws.column_dimensions['A'].width = 30
    ws.column_dimensions['B'].width = 18
    ws.column_dimensions['C'].width = 18
    ws.column_dimensions['D'].width = 24
    ws.column_dimensions['E'].width = 14

    row = 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    cell = ws.cell(row=row, column=1, value="FINAL SEMESTRAL GRADES")
    cell.font = Font(name='Calibri', size=14, bold=True)
    cell.fill = header_fill
    cell.alignment = Alignment(horizontal='center', vertical='center')
    for c in range(1, 6):
        ws.cell(row=row, column=c).border = thin_border
        ws.cell(row=row, column=c).fill = header_fill
    row += 1

    info_rows = [
        [("REGION", "XI"), ("DIVISION", "Panabo City"), ("SCHOOL ID", "123456789")],
        [("SCHOOL NAME", "Panabo City Senior High School"), ("SCHOOL YEAR", sy_label)],
        [("GRADE & SECTION:", grade_section), ("SEMESTER:", semester_text)],
        [("TEACHER:", "Juan Dela Cruz"), ("SUBJECT:", subject_name)],
        [("TRACK:", "Academic Track (except Immersion)")],
    ]

    for info_row in info_rows:
        col = 1
        for label, value in info_row:
            if label:
                cell = ws.cell(row=row, column=col, value=label)
                cell.font = Font(name='Calibri', size=9, bold=True)
                cell.alignment = Alignment(horizontal='left', vertical='center')
                col += 1
            if value:
                ws.merge_cells(start_row=row, start_column=col, end_row=row, end_column=col + (1 if col <= 3 else 0))
                cell = ws.cell(row=row, column=col, value=value)
                cell.font = Font(name='Calibri', size=9)
                cell.alignment = Alignment(horizontal='left', vertical='center')
                col += 2
        row += 1

    row += 1

    headers = ["LEARNERS' NAMES", q1_name, q2_name, "FIRST SEMESTER FINAL GRADES", "REMARK"]
    for i, h in enumerate(headers):
        col = i + 1
        cell = ws.cell(row=row, column=col, value=h)
        cell.font = Font(name='Calibri', size=10, bold=True)
        cell.fill = col_header_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    cell = ws.cell(row=row, column=1, value="MALE")
    cell.font = Font(name='Calibri', size=10, bold=True)
    cell.fill = male_fill
    for c in range(1, 6):
        ws.cell(row=row, column=c).border = thin_border
        ws.cell(row=row, column=c).fill = male_fill
    row += 1

    for i in range(1, 51):
        name = ""
        if i <= len(male_students):
            student = male_students[i-1].student
            name = f"{student.last_name}, {student.first_name}"
            if student.middle_name:
                name += f" {student.middle_name[0]}."
        
        ws.cell(row=row, column=1, value=f"{i} {name}").font = Font(name='Calibri', size=9)
        for c in range(1, 6):
            ws.cell(row=row, column=c).border = thin_border
            ws.cell(row=row, column=c).alignment = Alignment(horizontal='center' if c > 1 else 'left', vertical='center')
        row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)
    cell = ws.cell(row=row, column=1, value="FEMALE")
    cell.font = Font(name='Calibri', size=10, bold=True)
    cell.fill = female_fill
    for c in range(1, 6):
        ws.cell(row=row, column=c).border = thin_border
        ws.cell(row=row, column=c).fill = female_fill
    row += 1

    for i in range(1, 51):
        name = ""
        if i <= len(female_students):
            student = female_students[i-1].student
            name = f"{student.last_name}, {student.first_name}"
            if student.middle_name:
                name += f" {student.middle_name[0]}."
        
        ws.cell(row=row, column=1, value=f"{i} {name}").font = Font(name='Calibri', size=9)
        for c in range(1, 6):
            ws.cell(row=row, column=c).border = thin_border
            ws.cell(row=row, column=c).alignment = Alignment(horizontal='center' if c > 1 else 'left', vertical='center')
        row += 1

    row += 1
    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=5)

    ws.freeze_panes = 'A8'

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="Semestral_Grade_{section.section_name}_{semester_text}_Semester.xlsx"'
    return response


def _generate_quarterly_xlsx(section, subject, quarter_label, quarter_name, male_students, female_students):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, Border, Side, PatternFill
    from openpyxl.utils import get_column_letter

    wb = Workbook()
    ws = wb.active
    ws.title = "Class Record"

    max_rows = max(len(male_students), len(female_students), 50)
    grade_section = f"{section.grade_level.grade_name} - {section.section_name}" if section.grade_level else section.section_name
    subject_name = subject.subject_name if subject else ""

    thin_border = Border(
        left=Side(style='thin'), right=Side(style='thin'),
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    ww_fill = PatternFill(start_color='D9EAD3', end_color='D9EAD3', fill_type='solid')
    pt_fill = PatternFill(start_color='CFE2F3', end_color='CFE2F3', fill_type='solid')
    qa_fill = PatternFill(start_color='FCE4EC', end_color='FCE4EC', fill_type='solid')
    male_fill = PatternFill(start_color='B7D9F0', end_color='B7D9F0', fill_type='solid')
    female_fill = PatternFill(start_color='F8C8D8', end_color='F8C8D8', fill_type='solid')
    hps_fill = PatternFill(start_color='FFF2CC', end_color='FFF2CC', fill_type='solid')
    title_fill = PatternFill(start_color='D9EAD3', end_color='D9EAD3', fill_type='solid')

    ws.column_dimensions['A'].width = 22
    for col_idx in range(2, 32):
        ws.column_dimensions[get_column_letter(col_idx)].width = 7

    row = 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=31)
    cell = ws.cell(row=row, column=1, value=f"{quarter_name} CLASS RECORD")
    cell.font = Font(name='Calibri', size=12, bold=True)
    cell.fill = title_fill
    cell.alignment = Alignment(horizontal='center', vertical='center')
    for c in range(1, 32):
        ws.cell(row=row, column=c).border = thin_border
        ws.cell(row=row, column=c).fill = title_fill
    row += 1

    ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=8)
    ws.cell(row=row, column=1, value="TEACHER: _________________").font = Font(name='Calibri', size=9, bold=True)
    ws.merge_cells(start_row=row, start_column=9, end_row=row, end_column=20)
    ws.cell(row=row, column=9, value=f"GRADE & SECTION: {grade_section}").font = Font(name='Calibri', size=9, bold=True)
    ws.merge_cells(start_row=row, start_column=21, end_row=row, end_column=31)
    ws.cell(row=row, column=21, value=f"QUARTER: {quarter_label}").font = Font(name='Calibri', size=9, bold=True)
    row += 1

    ws.merge_cells(start_row=row, start_column=9, end_row=row, end_column=20)
    ws.cell(row=row, column=9, value=f"SUBJECT: {subject_name}").font = Font(name='Calibri', size=9, bold=True)
    ws.merge_cells(start_row=row, start_column=21, end_row=row, end_column=31)
    ws.cell(row=row, column=21, value="TRACK: Academic Track (except Immersion)").font = Font(name='Calibri', size=9, bold=True)
    row += 2

    ws.merge_cells(start_row=row, start_column=1, end_row=row+1, end_column=1)
    cell = ws.cell(row=row, column=1, value="LEARNERS' NAMES")
    cell.font = Font(name='Calibri', size=8, bold=True)
    cell.alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell.border = thin_border

    ws.merge_cells(start_row=row, start_column=2, end_row=row, end_column=14)
    cell = ws.cell(row=row, column=2, value="WRITTEN WORK (25%)")
    cell.font = Font(name='Calibri', size=8, bold=True)
    cell.fill = ww_fill
    cell.alignment = Alignment(horizontal='center', vertical='center')
    for c in range(2, 15):
        ws.cell(row=row, column=c).border = thin_border
        ws.cell(row=row, column=c).fill = ww_fill

    ws.merge_cells(start_row=row, start_column=15, end_row=row, end_column=27)
    cell = ws.cell(row=row, column=15, value="PERFORMANCE TASKS (45%)")
    cell.font = Font(name='Calibri', size=8, bold=True)
    cell.fill = pt_fill
    cell.alignment = Alignment(horizontal='center', vertical='center')
    for c in range(15, 28):
        ws.cell(row=row, column=c).border = thin_border
        ws.cell(row=row, column=c).fill = pt_fill

    ws.merge_cells(start_row=row, start_column=28, end_row=row, end_column=31)
    cell = ws.cell(row=row, column=28, value="QUARTERLY ASSESSMENT (30%)")
    cell.font = Font(name='Calibri', size=8, bold=True)
    cell.fill = qa_fill
    cell.alignment = Alignment(horizontal='center', vertical='center')
    for c in range(28, 32):
        ws.cell(row=row, column=c).border = thin_border
        ws.cell(row=row, column=c).fill = qa_fill
    row += 1

    for i in range(1, 11):
        cell = ws.cell(row=row, column=i+1, value=i)
        cell.font = Font(name='Calibri', size=7, bold=True)
        cell.fill = ww_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')
    for label, col in [("Total", 12), ("PS", 13), ("WS", 14)]:
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = Font(name='Calibri', size=7, bold=True)
        cell.fill = ww_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')

    for i in range(1, 11):
        cell = ws.cell(row=row, column=i+14, value=i)
        cell.font = Font(name='Calibri', size=7, bold=True)
        cell.fill = pt_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')
    for label, col in [("Total", 25), ("PS", 26), ("WS", 27)]:
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = Font(name='Calibri', size=7, bold=True)
        cell.fill = pt_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center')

    for label, col in [(1, 28), ("PS", 29), ("WS", 30), ("Initial\nGrade", 31)]:
        cell = ws.cell(row=row, column=col, value=label)
        cell.font = Font(name='Calibri', size=7, bold=True)
        cell.fill = qa_fill
        cell.border = thin_border
        cell.alignment = Alignment(horizontal='center', wrap_text=True)
    row += 1

    ws.cell(row=row, column=1, value="HIGHEST POSSIBLE SCORE").font = Font(name='Calibri', size=7, bold=True)
    ws.cell(row=row, column=1).fill = hps_fill
    ws.cell(row=row, column=1).border = thin_border
    for c in range(2, 12):
        ws.cell(row=row, column=c).fill = hps_fill
        ws.cell(row=row, column=c).border = thin_border
    for c, val in [(12, 100), (13, 100), (14, "25%")]:
        ws.cell(row=row, column=c, value=val).font = Font(name='Calibri', size=7, bold=True, color='CC0000' if val == "25%" else '000000')
        ws.cell(row=row, column=c).fill = hps_fill
        ws.cell(row=row, column=c).border = thin_border

    for c in range(15, 25):
        ws.cell(row=row, column=c).fill = hps_fill
        ws.cell(row=row, column=c).border = thin_border
    for c, val in [(25, 200), (26, 100), (27, "45%")]:
        ws.cell(row=row, column=c, value=val).font = Font(name='Calibri', size=7, bold=True, color='CC0000' if val == "45%" else '000000')
        ws.cell(row=row, column=c).fill = hps_fill
        ws.cell(row=row, column=c).border = thin_border

    ws.cell(row=row, column=28).fill = hps_fill
    ws.cell(row=row, column=28).border = thin_border
    for c, val in [(29, 100), (30, "30%"), (31, 100)]:
        ws.cell(row=row, column=c, value=val).font = Font(name='Calibri', size=7, bold=True, color='CC0000' if val == "30%" else '000000')
        ws.cell(row=row, column=c).fill = hps_fill
        ws.cell(row=row, column=c).border = thin_border
    row += 1

    def write_students(students, max_r, sex_label, fill):
        nonlocal row
        ws.merge_cells(start_row=row, start_column=1, end_row=row, end_column=31)
        cell = ws.cell(row=row, column=1, value=sex_label)
        cell.font = Font(name='Calibri', size=9, bold=True)
        cell.fill = fill
        for c in range(1, 32):
            ws.cell(row=row, column=c).border = thin_border
            ws.cell(row=row, column=c).fill = fill
        row += 1

        for i in range(max_r):
            if i < len(students):
                student = students[i].student
                name = f"{student.last_name}, {student.first_name} {student.middle_name or ''}".strip()
                ws.cell(row=row, column=1, value=f"{i+1}. {name}").font = Font(name='Calibri', size=7)
            else:
                ws.cell(row=row, column=1, value=f"{i+1}.").font = Font(name='Calibri', size=7)
            
            for c in range(1, 32):
                ws.cell(row=row, column=c).border = thin_border
                ws.cell(row=row, column=c).alignment = Alignment(horizontal='center' if c > 1 else 'left', vertical='center')
            row += 1

    write_students(male_students, max_rows, "MALE", male_fill)
    write_students(female_students, max_rows, "FEMALE", female_fill)

    ws.freeze_panes = 'B8'

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    response = HttpResponse(
        output.read(),
        content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
    )
    response['Content-Disposition'] = f'attachment; filename="Class_Record_{section.section_name}_{quarter_label}.xlsx"'
    return response


# ============================================================
# ✅ PARSE EXCEL PREVIEW - FIXED for dynamic quarters
# ============================================================

@csrf_exempt
@login_required
def parse_excel_preview(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'Invalid method'}, status=405)

    try:
        excel_file = request.FILES.get('excel_file')
        if not excel_file:
            return JsonResponse({'success': False, 'error': 'No file uploaded'})

        section_id = request.POST.get('section_id')

        file_content = excel_file.read()
        try:
            wb = load_workbook(BytesIO(file_content))
            sheet = wb.active
        except Exception as e:
            return JsonResponse({'success': False, 'error': 'Could not read Excel file: {}'.format(str(e))})

        enrollments = Enrollment.objects.filter(
            section_id=section_id, status='Enrolled'
        ).select_related('student').order_by('student__last_name')

        if not enrollments.exists():
            return JsonResponse({'success': False, 'error': 'No enrolled students found for this section.'})

        student_map, name_variants = _build_student_maps(enrollments)
        name_col, quarter_columns, final_col = _detect_columns(sheet)

        # Determine semester
        if 'Q1' in quarter_columns and 'Q2' in quarter_columns:
            detected_quarters = ['Q1', 'Q2']
            semester = '1st'
        elif 'Q3' in quarter_columns and 'Q4' in quarter_columns:
            detected_quarters = ['Q3', 'Q4']
            semester = '2nd'
        elif 'Q1' in quarter_columns:
            detected_quarters = ['Q1']
            semester = '1st'
        elif 'Q3' in quarter_columns:
            detected_quarters = ['Q3']
            semester = '2nd'
        else:
            detected_quarters = list(quarter_columns.keys())
            semester = 'unknown'

        import re

        rows = []
        matched_count = 0
        not_found_count = 0

        row_num = 1
        while row_num <= sheet.max_row:
            cell_val = sheet.cell(row=row_num, column=name_col).value
            cell_str = str(cell_val).strip() if cell_val is not None else ''
            cell_upper = cell_str.upper()

            # Skip section headers
            if cell_upper in ('MALE', 'FEMALE'):
                row_num += 1
                continue

            # Skip empty
            if not cell_str:
                row_num += 1
                continue

            # Strip leading row numbers: "1 Chan, Rafael" → "Chan, Rafael"
            clean_name = re.sub(r'^\d+[\.\s]*', '', cell_str).strip()

            # Skip blank template slots (number-only rows like "1 " → "")
            if not clean_name or not re.search(r'[A-Za-z]', clean_name):
                row_num += 1
                continue

            # Skip stray headers
            if clean_name.upper() in ("LEARNERS' NAMES", "LEARNER'S NAMES",
                                       "FIRST SEMESTER FINAL GRADES", "REMARK"):
                row_num += 1
                continue

            # Match to enrolled student
            enrollment_id = _match_name(clean_name, student_map, name_variants)

            # Read quarter grades from detected columns
            quarter_grades = {}
            for qlabel, col in quarter_columns.items():
                cv = sheet.cell(row=row_num, column=col).value
                if cv is not None:
                    try:
                        quarter_grades[qlabel] = round(float(cv), 2)
                    except (ValueError, TypeError):
                        quarter_grades[qlabel] = None
                else:
                    quarter_grades[qlabel] = None

            # Read final grade
            final_grade_val = None
            if final_col:
                cv = sheet.cell(row=row_num, column=final_col).value
                if cv is not None:
                    try:
                        final_grade_val = round(float(cv), 2)
                    except (ValueError, TypeError):
                        pass

            row_data = {
                'excel_name': clean_name,
                'matched': enrollment_id is not None,
                'enrollment_id': enrollment_id,
                'final_grade': final_grade_val,
            }
            row_data.update({'{}_grade'.format(q.lower()): g for q, g in quarter_grades.items()})

            rows.append(row_data)

            if enrollment_id:
                matched_count += 1
            else:
                not_found_count += 1

            row_num += 1

        return JsonResponse({
            'success': True,
            'rows': rows,
            'matched_count': matched_count,
            'not_found_count': not_found_count,
            'total_rows': len(rows),
            'template_type': 'semestral',
            'semester': semester,
            'detected_quarters': detected_quarters,
            'quarter_columns': quarter_columns,
            'has_final': final_col is not None,
        })

    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

# ============================================================
# REPORTS - TOP STUDENTS & CERTIFICATE OF RECOGNITION (FIXED)
# ============================================================
@login_required
def reports(request):
    """Generate reports for top students and certificates of recognition"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')

    teacher = request.user
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    if not current_sy:
        messages.warning(request, 'No active school year found.')
        context = {
            'students_data': '[]',
            'sections_data': '[]',
            'grade_levels_data': '[]',
            'subjects_data': '[]',
            'school_years_data': '[]',
            'current_school_year': '',
            'current_school_year_id': None,
            'teacher_name': request.user.get_full_name(),
            'has_data': False
        }
        return render(request, 'teachers/reports/reports.html', context)
    
    # Get all sections the teacher handles
    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher, is_active=True, school_year=current_sy
    ).select_related('section', 'section__grade_level', 'subject')
    
    if not class_assignments.exists():
        context = {
            'students_data': '[]',
            'sections_data': '[]',
            'grade_levels_data': '[]',
            'subjects_data': '[]',
            'school_years_data': '[]',
            'current_school_year': str(current_sy),
            'current_school_year_id': current_sy.id,
            'teacher_name': request.user.get_full_name(),
            'has_data': False
        }
        return render(request, 'teachers/reports/reports.html', context)
    
    # Get unique sections and subjects
    sections_data = []
    subjects_data = []
    seen_sections = set()
    seen_subjects = set()
    
    for ca in class_assignments:
        if ca.section_id not in seen_sections:
            seen_sections.add(ca.section_id)
            sections_data.append({
                'id': ca.section.id,
                'name': str(ca.section),
                'section_name': ca.section.section_name,
                'grade_level_id': ca.section.grade_level.id if ca.section.grade_level else None,
                'grade_level_name': ca.section.grade_level.grade_name if ca.section.grade_level else '',
                'strand': ca.section.strand.strand_code if ca.section.strand else None
            })
        
        if ca.subject_id not in seen_subjects:
            seen_subjects.add(ca.subject_id)
            subjects_data.append({
                'id': ca.subject.id,
                'name': ca.subject.subject_name,
                'code': ca.subject.subject_code
            })
    
    # Sort sections and subjects
    sections_data.sort(key=lambda x: x['name'])
    subjects_data.sort(key=lambda x: x['name'])
    
    # Get all grade levels
    grade_levels = GradeLevel.objects.all().order_by('grade_number')
    
    # Get school years
    school_years = SchoolYear.objects.all().order_by('-year_start')
    
    # Get students with grades for both semesters
    students_data = []
    
    # Get all quarters for current school year
    quarters = Quarter.objects.filter(school_year=current_sy).order_by('quarter_number')
    q1 = quarters.filter(quarter_label='Q1').first()
    q2 = quarters.filter(quarter_label='Q2').first()
    q3 = quarters.filter(quarter_label='Q3').first()
    q4 = quarters.filter(quarter_label='Q4').first()
    
    # Get enrollments for teacher's sections
    teacher_section_ids = list(set([ca.section_id for ca in class_assignments]))
    teacher_subject_ids = list(set([ca.subject_id for ca in class_assignments]))
    
    enrollments = Enrollment.objects.filter(
        section_id__in=teacher_section_ids,
        status='Enrolled',
        school_year=current_sy
    ).select_related('student', 'section', 'section__grade_level', 'section__strand')
    
    for enrollment in enrollments:
        student = enrollment.student
        section = enrollment.section
        
        # Calculate 1st semester final grade (Q1 + Q2)
        sem1_final = None
        if q1 and q2:
            q1_grade = _get_quarter_grade(enrollment, q1, teacher_subject_ids)
            q2_grade = _get_quarter_grade(enrollment, q2, teacher_subject_ids)
            if q1_grade is not None and q2_grade is not None:
                sem1_final = round((q1_grade + q2_grade) / 2, 2)
        
        # Calculate 2nd semester final grade (Q3 + Q4)
        sem2_final = None
        if q3 and q4:
            q3_grade = _get_quarter_grade(enrollment, q3, teacher_subject_ids)
            q4_grade = _get_quarter_grade(enrollment, q4, teacher_subject_ids)
            if q3_grade is not None and q4_grade is not None:
                sem2_final = round((q3_grade + q4_grade) / 2, 2)
        
        # Overall final average (average of both semesters if available)
        overall_final = None
        if sem1_final is not None and sem2_final is not None:
            overall_final = round((sem1_final + sem2_final) / 2, 2)
        elif sem1_final is not None:
            overall_final = sem1_final
        elif sem2_final is not None:
            overall_final = sem2_final
        
        # Determine honor category
        honor = 'none'
        if overall_final is not None and isinstance(overall_final, (int, float)):
            if overall_final >= 98:
                honor = 'highest'
            elif overall_final >= 95:
                honor = 'high'
            elif overall_final >= 90:
                honor = 'with'
        
        # Only include students with honor (90+)
        if honor != 'none':
            students_data.append({
                'id': student.id,
                'enrollment_id': enrollment.id,
                'lrn': student.lrn or '',
                'first_name': student.first_name,
                'last_name': student.last_name,
                'middle_name': student.middle_name or '',
                'sex': student.sex or '',
                'section_id': section.id,
                'section_name': section.section_name,
                'grade_level_id': section.grade_level.id if section.grade_level else None,
                'grade_level_name': section.grade_level.grade_name if section.grade_level else '',
                'strand': section.strand.strand_code if section.strand else None,
                'q1_grade': q1_grade,
                'q2_grade': q2_grade,
                'q3_grade': q3_grade,
                'q4_grade': q4_grade,
                'sem1_final': sem1_final,
                'sem2_final': sem2_final,
                'final_average': overall_final,
                'honor': honor
            })
    
    # Sort by final average descending
    students_data.sort(key=lambda x: x.get('final_average') if x.get('final_average') is not None else 0, reverse=True)
    
    # Prepare data for template
    import json as json_lib
    
    class DecimalEncoder(json_lib.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, decimal.Decimal):
                return float(obj)
            return super().default(obj)
    
    # Prepare JSON data
    grade_levels_json = []
    for gl in grade_levels:
        grade_levels_json.append({
            'id': gl.id,
            'name': gl.grade_name,
            'grade_number': gl.grade_number
        })
    
    school_years_json = []
    for sy in school_years:
        school_years_json.append({
            'id': sy.id,
            'label': sy.year_label if hasattr(sy, 'year_label') else str(sy),
            'is_current': sy.is_current if hasattr(sy, 'is_current') else False
        })
    
    context = {
        'students_data': json_lib.dumps(students_data, cls=DecimalEncoder),
        'sections_data': json_lib.dumps(sections_data),
        'grade_levels_data': json_lib.dumps(grade_levels_json),
        'subjects_data': json_lib.dumps(subjects_data),
        'school_years_data': json_lib.dumps(school_years_json),
        'current_school_year': str(current_sy) if current_sy else '',
        'current_school_year_id': current_sy.id if current_sy else None,
        'teacher_name': request.user.get_full_name(),
        'has_data': len(students_data) > 0
    }
    
    return render(request, 'teachers/reports/reports.html', context)


def _get_quarter_grade(enrollment, quarter, subject_ids):
    """Get average grade for a quarter across all teacher's subjects"""
    grades = GradeComponent.objects.filter(
        enrollment=enrollment,
        quarter=quarter,
        subject_id__in=subject_ids,
        transmuted_grade__isnull=False
    ).values_list('transmuted_grade', flat=True)
    
    if not grades:
        return None
    
    total = 0
    count = 0
    for g in grades:
        try:
            val = float(g)
            total += val
            count += 1
        except (ValueError, TypeError):
            continue
    
    return round(total / count, 2) if count > 0 else None

# ============================================================
# REPORTS - TOP STUDENTS & CERTIFICATE OF RECOGNITION (FIXED)
# ============================================================
@login_required
def reports(request):
    """Generate reports for top students and certificates of recognition"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')

    teacher = request.user
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    if not current_sy:
        messages.warning(request, 'No active school year found.')
        context = {
            'students_data': '[]',
            'sections_data': '[]',
            'grade_levels_data': '[]',
            'subjects_data': '[]',
            'school_years_data': '[]',
            'current_school_year': '',
            'current_school_year_id': None,
            'teacher_name': request.user.get_full_name(),
            'has_data': False
        }
        return render(request, 'teachers/reports/reports.html', context)
    
    # Get all sections the teacher handles
    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher, is_active=True, school_year=current_sy
    ).select_related('section', 'section__grade_level', 'subject')
    
    if not class_assignments.exists():
        context = {
            'students_data': '[]',
            'sections_data': '[]',
            'grade_levels_data': '[]',
            'subjects_data': '[]',
            'school_years_data': '[]',
            'current_school_year': str(current_sy),
            'current_school_year_id': current_sy.id,
            'teacher_name': request.user.get_full_name(),
            'has_data': False
        }
        return render(request, 'teachers/reports/reports.html', context)
    
    # Get unique sections and subjects
    sections_data = []
    subjects_data = []
    seen_sections = set()
    seen_subjects = set()
    
    for ca in class_assignments:
        if ca.section_id not in seen_sections:
            seen_sections.add(ca.section_id)
            sections_data.append({
                'id': ca.section.id,
                'name': str(ca.section),
                'section_name': ca.section.section_name,
                'grade_level_id': ca.section.grade_level.id if ca.section.grade_level else None,
                'grade_level_name': ca.section.grade_level.grade_name if ca.section.grade_level else '',
                'strand': ca.section.strand.strand_code if ca.section.strand else None
            })
        
        if ca.subject_id not in seen_subjects:
            seen_subjects.add(ca.subject_id)
            subjects_data.append({
                'id': ca.subject.id,
                'name': ca.subject.subject_name,
                'code': ca.subject.subject_code
            })
    
    # Sort sections and subjects
    sections_data.sort(key=lambda x: x['name'])
    subjects_data.sort(key=lambda x: x['name'])
    
    # Get all grade levels
    grade_levels = GradeLevel.objects.all().order_by('grade_number')
    
    # Get school years
    school_years = SchoolYear.objects.all().order_by('-year_start')
    
    # Get students with grades for both semesters
    students_data = []
    
    # Get all quarters for current school year
    quarters = Quarter.objects.filter(school_year=current_sy).order_by('quarter_number')
    q1 = quarters.filter(quarter_label='Q1').first()
    q2 = quarters.filter(quarter_label='Q2').first()
    q3 = quarters.filter(quarter_label='Q3').first()
    q4 = quarters.filter(quarter_label='Q4').first()
    
    # Get enrollments for teacher's sections
    teacher_section_ids = list(set([ca.section_id for ca in class_assignments]))
    teacher_subject_ids = list(set([ca.subject_id for ca in class_assignments]))
    
    enrollments = Enrollment.objects.filter(
        section_id__in=teacher_section_ids,
        status='Enrolled',
        school_year=current_sy
    ).select_related('student', 'section', 'section__grade_level', 'section__strand')
    
    for enrollment in enrollments:
        student = enrollment.student
        section = enrollment.section
        
        # Calculate 1st semester final grade (Q1 + Q2)
        sem1_final = None
        if q1 and q2:
            q1_grade = _get_quarter_grade(enrollment, q1, teacher_subject_ids)
            q2_grade = _get_quarter_grade(enrollment, q2, teacher_subject_ids)
            if q1_grade is not None and q2_grade is not None:
                sem1_final = round((q1_grade + q2_grade) / 2, 2)
        
        # Calculate 2nd semester final grade (Q3 + Q4)
        sem2_final = None
        if q3 and q4:
            q3_grade = _get_quarter_grade(enrollment, q3, teacher_subject_ids)
            q4_grade = _get_quarter_grade(enrollment, q4, teacher_subject_ids)
            if q3_grade is not None and q4_grade is not None:
                sem2_final = round((q3_grade + q4_grade) / 2, 2)
        
        # Overall final average (average of both semesters if available)
        overall_final = None
        if sem1_final is not None and sem2_final is not None:
            overall_final = round((sem1_final + sem2_final) / 2, 2)
        elif sem1_final is not None:
            overall_final = sem1_final
        elif sem2_final is not None:
            overall_final = sem2_final
        
        # Determine honor category
        honor = 'none'
        if overall_final is not None and isinstance(overall_final, (int, float)):
            if overall_final >= 98:
                honor = 'highest'
            elif overall_final >= 95:
                honor = 'high'
            elif overall_final >= 90:
                honor = 'with'
        
        # Only include students with honor (90+)
        if honor != 'none':
            students_data.append({
                'id': student.id,
                'enrollment_id': enrollment.id,
                'lrn': student.lrn or '',
                'first_name': student.first_name,
                'last_name': student.last_name,
                'middle_name': student.middle_name or '',
                'sex': student.sex or '',
                'section_id': section.id,
                'section_name': section.section_name,
                'grade_level_id': section.grade_level.id if section.grade_level else None,
                'grade_level_name': section.grade_level.grade_name if section.grade_level else '',
                'strand': section.strand.strand_code if section.strand else None,
                'q1_grade': q1_grade,
                'q2_grade': q2_grade,
                'q3_grade': q3_grade,
                'q4_grade': q4_grade,
                'sem1_final': sem1_final,
                'sem2_final': sem2_final,
                'final_average': overall_final,
                'honor': honor
            })
    
    # Sort by final average descending
    students_data.sort(key=lambda x: x.get('final_average') if x.get('final_average') is not None else 0, reverse=True)
    
    # Prepare data for template
    import json as json_lib
    
    class DecimalEncoder(json_lib.JSONEncoder):
        def default(self, obj):
            if isinstance(obj, decimal.Decimal):
                return float(obj)
            return super().default(obj)
    
    # Prepare JSON data
    grade_levels_json = []
    for gl in grade_levels:
        grade_levels_json.append({
            'id': gl.id,
            'name': gl.grade_name,
            'grade_number': gl.grade_number
        })
    
    school_years_json = []
    for sy in school_years:
        school_years_json.append({
            'id': sy.id,
            'label': sy.year_label if hasattr(sy, 'year_label') else str(sy),
            'is_current': sy.is_current if hasattr(sy, 'is_current') else False
        })
    
    context = {
        'students_data': json_lib.dumps(students_data, cls=DecimalEncoder),
        'sections_data': json_lib.dumps(sections_data),
        'grade_levels_data': json_lib.dumps(grade_levels_json),
        'subjects_data': json_lib.dumps(subjects_data),
        'school_years_data': json_lib.dumps(school_years_json),
        'current_school_year': str(current_sy) if current_sy else '',
        'current_school_year_id': current_sy.id if current_sy else None,
        'teacher_name': request.user.get_full_name(),
        'has_data': len(students_data) > 0
    }
    
    return render(request, 'teachers/reports/reports.html', context)


def _get_quarter_grade(enrollment, quarter, subject_ids):
    """Get average grade for a quarter across all teacher's subjects"""
    grades = GradeComponent.objects.filter(
        enrollment=enrollment,
        quarter=quarter,
        subject_id__in=subject_ids,
        transmuted_grade__isnull=False
    ).values_list('transmuted_grade', flat=True)
    
    if not grades:
        return None
    
    total = 0
    count = 0
    for g in grades:
        try:
            val = float(g)
            total += val
            count += 1
        except (ValueError, TypeError):
            continue
    
    return round(total / count, 2) if count > 0 else None


# ============================================================
# EXPORT REPORTS TO EXCEL
# ============================================================
@login_required
def export_reports_excel(request):
    """Export top students report to Excel with professional formatting"""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        return JsonResponse({'success': False, 'error': 'Access denied'}, status=403)
    
    try:
        from openpyxl import Workbook
        from openpyxl.styles import Font, Alignment, Border, Side, PatternFill, numbers
        from openpyxl.utils import get_column_letter
        
        teacher = request.user
        current_sy = SchoolYear.objects.filter(is_current=True).first()
        
        if not current_sy:
            return JsonResponse({'success': False, 'error': 'No active school year'})
        
        # Get filter parameters
        section_id = request.GET.get('section_id')
        grade_level_id = request.GET.get('grade_level_id')
        subject_id = request.GET.get('subject_id')
        honor_filter = request.GET.get('honor', 'all')  # all, highest, high, with
        
        # Get teacher's class assignments
        class_assignments = ClassAssignment.objects.filter(
            teacher=teacher, is_active=True, school_year=current_sy
        ).select_related('section', 'subject')
        
        teacher_section_ids = list(set([ca.section_id for ca in class_assignments]))
        teacher_subject_ids = list(set([ca.subject_id for ca in class_assignments]))
        
        # Apply section filter
        if section_id and int(section_id) in teacher_section_ids:
            teacher_section_ids = [int(section_id)]
        
        # Get quarters
        q1 = Quarter.objects.filter(school_year=current_sy, quarter_label='Q1').first()
        q2 = Quarter.objects.filter(school_year=current_sy, quarter_label='Q2').first()
        q3 = Quarter.objects.filter(school_year=current_sy, quarter_label='Q3').first()
        q4 = Quarter.objects.filter(school_year=current_sy, quarter_label='Q4').first()
        
        # Get enrollments
        enrollments = Enrollment.objects.filter(
            section_id__in=teacher_section_ids,
            status='Enrolled',
            school_year=current_sy
        ).select_related('student', 'section', 'section__grade_level')
        
        # Apply grade level filter
        if grade_level_id:
            enrollments = enrollments.filter(section__grade_level_id=int(grade_level_id))
        
        # Build student data
        students_data = []
        for enrollment in enrollments:
            student = enrollment.student
            section = enrollment.section
            
            q1_grade = _get_quarter_grade(enrollment, q1, teacher_subject_ids) if q1 else None
            q2_grade = _get_quarter_grade(enrollment, q2, teacher_subject_ids) if q2 else None
            q3_grade = _get_quarter_grade(enrollment, q3, teacher_subject_ids) if q3 else None
            q4_grade = _get_quarter_grade(enrollment, q4, teacher_subject_ids) if q4 else None
            
            sem1_final = round((q1_grade + q2_grade) / 2, 2) if q1_grade and q2_grade else None
            sem2_final = round((q3_grade + q4_grade) / 2, 2) if q3_grade and q4_grade else None
            
            overall_final = None
            if sem1_final and sem2_final:
                overall_final = round((sem1_final + sem2_final) / 2, 2)
            elif sem1_final:
                overall_final = sem1_final
            elif sem2_final:
                overall_final = sem2_final
            
            honor = 'none'
            if overall_final and overall_final >= 90:
                if overall_final >= 98:
                    honor = 'highest'
                elif overall_final >= 95:
                    honor = 'high'
                else:
                    honor = 'with'
            
            # Apply honor filter
            if honor_filter != 'all' and honor != honor_filter:
                continue
            
            if honor != 'none':
                students_data.append({
                    'lrn': student.lrn or '',
                    'last_name': student.last_name,
                    'first_name': student.first_name,
                    'middle_name': student.middle_name or '',
                    'sex': student.sex or '',
                    'section': str(section),
                    'grade_level': section.grade_level.grade_name if section.grade_level else '',
                    'q1': q1_grade,
                    'q2': q2_grade,
                    'q3': q3_grade,
                    'q4': q4_grade,
                    'sem1_final': sem1_final,
                    'sem2_final': sem2_final,
                    'final_average': overall_final,
                    'honor': honor
                })
        
        # Sort by final average
        students_data.sort(key=lambda x: x.get('final_average') or 0, reverse=True)
        
        # Add ranks
        for idx, student in enumerate(students_data):
            student['rank'] = idx + 1
        
        # Create workbook
        wb = Workbook()
        ws = wb.active
        ws.title = "Top Students Report"
        
        # Styles
        title_font = Font(name='Calibri', size=16, bold=True, color='1B4332')
        subtitle_font = Font(name='Calibri', size=11, color='2D6A4F')
        header_font = Font(name='Calibri', size=10, bold=True, color='FFFFFF')
        header_fill = PatternFill(start_color='2D6A4F', end_color='2D6A4F', fill_type='solid')
        header_fill_gold = PatternFill(start_color='B8860B', end_color='B8860B', fill_type='solid')
        data_font = Font(name='Calibri', size=10)
        rank_font = Font(name='Calibri', size=11, bold=True)
        
        gold_fill = PatternFill(start_color='FFF8DC', end_color='FFF8DC', fill_type='solid')
        silver_fill = PatternFill(start_color='F5F5F5', end_color='F5F5F5', fill_type='solid')
        bronze_fill = PatternFill(start_color='FFF5EE', end_color='FFF5EE', fill_type='solid')
        white_fill = PatternFill(start_color='FFFFFF', end_color='FFFFFF', fill_type='solid')
        
        thin_border = Border(
            left=Side(style='thin', color='D4D4D4'),
            right=Side(style='thin', color='D4D4D4'),
            top=Side(style='thin', color='D4D4D4'),
            bottom=Side(style='thin', color='D4D4D4')
        )
        
        center_align = Alignment(horizontal='center', vertical='center')
        left_align = Alignment(horizontal='left', vertical='center')
        
        # Title section
        ws.merge_cells('A1:N1')
        title_cell = ws.cell(row=1, column=1, value=f"TOP PERFORMING STUDENTS REPORT")
        title_cell.font = title_font
        title_cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[1].height = 35
        
        ws.merge_cells('A2:N2')
        subtitle_cell = ws.cell(row=2, column=1, value=f"School Year: {current_sy.year_label} | Generated: {timezone.now().strftime('%B %d, %Y')} | Teacher: {teacher.get_full_name()}")
        subtitle_cell.font = subtitle_font
        subtitle_cell.alignment = Alignment(horizontal='center', vertical='center')
        ws.row_dimensions[2].height = 25
        
        # Filters applied
        filters_applied = []
        if section_id:
            section = Section.objects.filter(id=section_id).first()
            if section:
                filters_applied.append(f"Section: {section}")
        if grade_level_id:
            gl = GradeLevel.objects.filter(id=grade_level_id).first()
            if gl:
                filters_applied.append(f"Grade Level: {gl.grade_name}")
        if honor_filter != 'all':
            honor_names = {'highest': 'With Highest Honors', 'high': 'With High Honors', 'with': 'With Honors'}
            filters_applied.append(f"Honor: {honor_names.get(honor_filter, honor_filter)}")
        
        if filters_applied:
            ws.merge_cells('A3:N3')
            filter_cell = ws.cell(row=3, column=1, value="Filters: " + " | ".join(filters_applied))
            filter_cell.font = Font(name='Calibri', size=9, italic=True, color='666666')
            filter_cell.alignment = Alignment(horizontal='center', vertical='center')
            ws.row_dimensions[3].height = 20
            header_row = 5
        else:
            header_row = 4
        
        # Summary row
        total_students = len(students_data)
        highest_count = sum(1 for s in students_data if s['honor'] == 'highest')
        high_count = sum(1 for s in students_data if s['honor'] == 'high')
        with_count = sum(1 for s in students_data if s['honor'] == 'with')
        
        ws.merge_cells(f'A{header_row}:N{header_row}')
        summary_cell = ws.cell(row=header_row, column=1, 
                               value=f"Total Honor Students: {total_students} | Highest Honors: {highest_count} | High Honors: {high_count} | With Honors: {with_count}")
        summary_cell.font = Font(name='Calibri', size=10, bold=True, color='2D6A4F')
        summary_cell.alignment = Alignment(horizontal='center', vertical='center')
        summary_cell.fill = PatternFill(start_color='E8F5E9', end_color='E8F5E9', fill_type='solid')
        ws.row_dimensions[header_row].height = 25
        
        header_row += 1
        
        # Column Headers
        headers = [
            ('Rank', 6),
            ('LRN', 15),
            ('Last Name', 18),
            ('First Name', 18),
            ('Middle Name', 15),
            ('Sex', 8),
            ('Grade Level', 15),
            ('Section', 18),
            ('Q1 Grade', 12),
            ('Q2 Grade', 12),
            ('Q3 Grade', 12),
            ('Q4 Grade', 12),
            ('Final Average', 14),
            ('Honor', 20)
        ]
        
        for col_idx, (header, width) in enumerate(headers, 1):
            cell = ws.cell(row=header_row, column=col_idx, value=header)
            cell.font = header_font
            cell.fill = header_fill
            cell.alignment = center_align
            cell.border = thin_border
            ws.column_dimensions[get_column_letter(col_idx)].width = width
        
        ws.row_dimensions[header_row].height = 30
        
        # Data rows
        for row_idx, student in enumerate(students_data):
            data_row = header_row + 1 + row_idx
            
            # Determine row styling based on rank
            if student['rank'] == 1:
                row_fill = gold_fill
                rank_bg = PatternFill(start_color='FFD700', end_color='FFD700', fill_type='solid')
                rank_font_color = '8B6914'
            elif student['rank'] == 2:
                row_fill = silver_fill
                rank_bg = PatternFill(start_color='C0C0C0', end_color='C0C0C0', fill_type='solid')
                rank_font_color = '555555'
            elif student['rank'] == 3:
                row_fill = bronze_fill
                rank_bg = PatternFill(start_color='CD7F32', end_color='CD7F32', fill_type='solid')
                rank_font_color = 'FFFFFF'
            else:
                row_fill = white_fill
                rank_bg = PatternFill(start_color='2D6A4F', end_color='2D6A4F', fill_type='solid')
                rank_font_color = 'FFFFFF'
            
            values = [
                student['rank'],
                student['lrn'],
                student['last_name'].upper(),
                student['first_name'],
                student['middle_name'],
                student['sex'],
                student['grade_level'],
                student['section'],
                student['q1'],
                student['q2'],
                student['q3'],
                student['q4'],
                student['final_average'],
                get_honor_display(student['honor'])
            ]
            
            for col_idx, value in enumerate(values, 1):
                cell = ws.cell(row=data_row, column=col_idx, value=value)
                cell.font = data_font
                cell.border = thin_border
                cell.fill = row_fill
                
                # Rank column special styling
                if col_idx == 1:
                    cell.font = rank_font
                    cell.fill = rank_bg
                    cell.font = Font(name='Calibri', size=11, bold=True, color=rank_font_color)
                    cell.alignment = center_align
                elif col_idx in [9, 10, 11, 12, 13]:  # Grade columns
                    cell.alignment = center_align
                    if value is not None:
                        cell.number_format = '0.00'
                elif col_idx == 14:  # Honor column
                    cell.alignment = center_align
                    # Color code honor
                    if student['honor'] == 'highest':
                        cell.font = Font(name='Calibri', size=10, bold=True, color='B8860B')
                    elif student['honor'] == 'high':
                        cell.font = Font(name='Calibri', size=10, bold=True, color='696969')
                    else:
                        cell.font = Font(name='Calibri', size=10, bold=True, color='CD7F32')
                else:
                    cell.alignment = left_align
            
            ws.row_dimensions[data_row].height = 22
        
        # Add legend
        legend_start = header_row + len(students_data) + 3
        ws.merge_cells(f'A{legend_start}:N{legend_start}')
        ws.cell(row=legend_start, column=1, value="HONOR LEGEND").font = Font(name='Calibri', size=10, bold=True, color='2D6A4F')
        
        legend_data = [
            ('With Highest Honors', '98 - 100', 'FFD700'),
            ('With High Honors', '95 - 97', 'C0C0C0'),
            ('With Honors', '90 - 94', 'CD7F32')
        ]
        
        for i, (name, range_val, color) in enumerate(legend_data):
            row = legend_start + 1 + i
            color_fill = PatternFill(start_color=color, end_color=color, fill_type='solid')
            
            cell = ws.cell(row=row, column=1, value='')
            cell.fill = color_fill
            ws.merge_cells(f'A{row}:B{row}')
            
            ws.cell(row=row, column=3, value=name).font = Font(name='Calibri', size=9)
            ws.cell(row=row, column=4, value=range_val).font = Font(name='Calibri', size=9, color='666666')
        
        # Freeze panes
        ws.freeze_panes = f'A{header_row + 1}'
        
        # Auto-filter
        ws.auto_filter.ref = f'A{header_row}:N{header_row + len(students_data)}'
        
        # Prepare response
        output = BytesIO()
        wb.save(output)
        output.seek(0)
        
        filename = f"Top_Students_Report_{current_sy.year_label.replace(' ', '_')}.xlsx"
        
        response = HttpResponse(
            output.read(),
            content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'
        )
        response['Content-Disposition'] = f'attachment; filename="{filename}"'
        
        return response
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        return JsonResponse({'success': False, 'error': str(e)}, status=500)


def get_honor_display(honor):
    """Convert honor code to display text"""
    honor_map = {
        'highest': 'WITH HIGHEST HONORS',
        'high': 'WITH HIGH HONORS',
        'with': 'WITH HONORS',
        'none': 'NO HONORS'
    }
    return honor_map.get(honor, 'NO HONORS')
    
# ============================================================
# TEACHER SCHEDULE - DYNAMIC FROM DATABASE
# ============================================================

@login_required
def teacher_schedule(request):
    """Display teacher's class schedule from database (read-only)."""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')
    
    teacher = request.user
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    if not current_sy:
        messages.warning(request, 'No active school year found.')
        return render(request, 'teachers/schedule/schedule.html', {
            'has_schedule': False,
            'error_message': 'No active school year configured.'
        })
    
    # Get all active class assignments for this teacher
    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher,
        school_year=current_sy,
        is_active=True
    ).select_related('section', 'subject', 'default_room')
    
    if not class_assignments.exists():
        return render(request, 'teachers/schedule/schedule.html', {
            'has_schedule': False,
            'error_message': 'No class assignments found for this school year.'
        })
    
    # Get all schedules for these assignments
    schedules = ClassSchedule.objects.filter(
        class_assignment__in=class_assignments,
        is_active=True,
        effective_from__lte=date.today(),
        effective_until__isnull=True
    ).select_related(
        'class_assignment__section',
        'class_assignment__subject',
        'class_assignment__default_room',
        'room'
    ).order_by('day_number', 'time_start')
    
    # Build schedule data structure
    schedule_items = []
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    day_map = {day: idx for idx, day in enumerate(days_order, 1)}
    
    # Subject color mapping based on subject code
    def get_subject_color(subject_code):
        code = subject_code.upper()
        if 'MATH' in code or 'PRECALC' in code or 'BUSMATH' in code or 'STATS' in code:
            return 'math'
        elif 'SCI' in code or 'BIO' in code or 'CHEM' in code or 'PHY' in code:
            return 'science'
        elif 'ENG' in code or 'EAPP' in code or 'LIT' in code:
            return 'english'
        elif 'FIL' in code or 'PAGBASA' in code:
            return 'filipino'
        elif 'AP' in code or 'SOC' in code or 'PHILO' in code:
            return 'social'
        elif 'MAPEH' in code or 'PE' in code or 'HEALTH' in code:
            return 'mapeh'
        elif 'TLE' in code or 'ICT' in code or 'TVL' in code:
            return 'tle'
        elif 'ESP' in code or 'VALUES' in code or 'RELIGION' in code:
            return 'values'
        else:
            return 'others'
    
    for sched in schedules:
        ca = sched.class_assignment
        schedule_items.append({
            'id': sched.id,
            'day': sched.day_of_week,
            'day_number': sched.day_number,
            'start_time': sched.time_start.strftime('%I:%M %p'),
            'end_time': sched.time_end.strftime('%I:%M %p'),
            'start_raw': sched.time_start.strftime('%H:%M'),
            'end_raw': sched.time_end.strftime('%H:%M'),
            'subject_name': ca.subject.subject_name,
            'subject_code': ca.subject.subject_code,
            'section_name': str(ca.section),
            'room': sched.effective_room.room_code if sched.effective_room else ca.default_room.room_code if ca.default_room else 'TBA',
            'room_name': sched.effective_room.room_name if sched.effective_room else ca.default_room.room_name if ca.default_room else '',
            'color': get_subject_color(ca.subject.subject_code),
        })
    
    # Group by day for week view
    schedule_by_day = {day: [] for day in days_order}
    for item in schedule_items:
        if item['day'] in schedule_by_day:
            schedule_by_day[item['day']].append(item)
    
    # Sort each day by start time
    for day in schedule_by_day:
        schedule_by_day[day].sort(key=lambda x: x['start_raw'])
    
    # Generate time slots for week view (7:00 AM to 6:00 PM)
    time_slots = []
    for hour in range(7, 18):
        for minute in [0, 30]:
            if hour == 17 and minute == 30:
                continue
            time_slots.append(f"{hour:02d}:{minute:02d}")
    
    context = {
        'has_schedule': True,
        'schedule_items': schedule_items,
        'schedule_by_day': schedule_by_day,
        'time_slots': time_slots,
        'days': days_order,
        'current_sy': str(current_sy),
        'teacher_name': teacher.get_full_name(),
    }
    
    return render(request, 'teachers/schedule/schedule.html', context)

# ============================================================
# EXPORT SCHEDULE TO PDF
# ============================================================

# ============================================================
# EXPORT SCHEDULE TO PDF
# ============================================================

@login_required
def export_schedule_pdf(request):
    """Export teacher's schedule to PDF."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import landscape, letter
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib.enums import TA_CENTER
    import io
    
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    teacher = request.user
    current_sy = SchoolYear.objects.filter(is_current=True).first()
    
    if not current_sy:
        messages.warning(request, 'No active school year found.')
        return redirect('teachers-schedule')
    
    # Get schedules (same logic as teacher_schedule view)
    class_assignments = ClassAssignment.objects.filter(
        teacher=teacher,
        school_year=current_sy,
        is_active=True
    ).select_related('section', 'subject', 'default_room')
    
    schedules = ClassSchedule.objects.filter(
        class_assignment__in=class_assignments,
        is_active=True,
        effective_from__lte=date.today(),
        effective_until__isnull=True
    ).select_related(
        'class_assignment__section',
        'class_assignment__subject',
        'class_assignment__default_room',
        'room'
    ).order_by('day_number', 'time_start')
    
    # Build schedule data
    days_order = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    schedule_by_day = {day: [] for day in days_order}
    
    for sched in schedules:
        ca = sched.class_assignment
        schedule_by_day[sched.day_of_week].append({
            'start': sched.time_start.strftime('%I:%M %p'),
            'end': sched.time_end.strftime('%I:%M %p'),
            'subject': ca.subject.subject_name,
            'subject_code': ca.subject.subject_code,
            'section': str(ca.section),
            'room': sched.effective_room.room_code if sched.effective_room else ca.default_room.room_code if ca.default_room else 'TBA',
        })
    
    for day in schedule_by_day:
        schedule_by_day[day].sort(key=lambda x: x['start'])
    
    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="Schedule_{teacher.last_name}_{current_sy.year_label}.pdf"'
    
    doc = SimpleDocTemplate(response, pagesize=landscape(letter),
                           rightMargin=30, leftMargin=30,
                           topMargin=40, bottomMargin=30)
    
    styles = getSampleStyleSheet()
    story = []
    
    title_style = ParagraphStyle('CustomTitle', parent=styles['Heading1'],
                                 fontSize=16, alignment=TA_CENTER,
                                 spaceAfter=20, textColor=colors.HexColor('#00072D'))
    
    subtitle_style = ParagraphStyle('CustomSubtitle', parent=styles['Normal'],
                                    fontSize=10, alignment=TA_CENTER,
                                    textColor=colors.HexColor('#718096'), spaceAfter=30)
    
    cell_style = ParagraphStyle('CellStyle', parent=styles['Normal'],
                                fontSize=8, alignment=TA_CENTER, spaceAfter=0, spaceBefore=0)
    
    title = Paragraph(f"<b>{teacher.get_full_name()}</b> - Class Schedule", title_style)
    story.append(title)
    
    subtitle = Paragraph(f"School Year: {current_sy.year_label} | Generated: {date.today().strftime('%B %d, %Y')}", subtitle_style)
    story.append(subtitle)
    
    story.append(Spacer(1, 10))
    
    # Create table
    headers = ['Time', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday']
    table_data = [headers]
    
    time_slots = []
    for hour in range(7, 18):
        time_slots.append(f"{hour}:00 - {hour+1}:00")
    
    for slot in time_slots:
        row = [Paragraph(slot, cell_style)]
        for day in days_order:
            day_schedules = schedule_by_day[day]
            slot_schedules = []
            for sch in day_schedules:
                start_hour = int(sch['start'].split(':')[0])
                start_ampm = sch['start'].split(' ')[1]
                if start_ampm == 'PM' and start_hour != 12:
                    start_hour += 12
                elif start_ampm == 'AM' and start_hour == 12:
                    start_hour = 0
                slot_hour = int(slot.split(':')[0])
                if start_hour == slot_hour:
                    slot_schedules.append(sch)
            
            if slot_schedules:
                cell_content = "<br/>".join([
                    f"<b>{sch['subject_code']}</b><br/>{sch['section']}<br/>{sch['room']}<br/><font color='#718096' size='7'>{sch['start']}-{sch['end']}</font>"
                    for sch in slot_schedules
                ])
                row.append(Paragraph(cell_content, cell_style))
            else:
                row.append(Paragraph("—", cell_style))
        table_data.append(row)
    
    table = Table(table_data, repeatRows=1)
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#5EA173')),
        ('TEXTCOLOR', (0, 0), (-1, 0), colors.white),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
        ('FONTSIZE', (0, 0), (-1, 0), 9),
        ('GRID', (0, 0), (-1, -1), 0.5, colors.HexColor('#e9ecef')),
        ('BACKGROUND', (0, 1), (-1, -1), colors.white),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [colors.white, colors.HexColor('#f8f9fa')]),
        ('FONTSIZE', (0, 1), (-1, -1), 7),
        ('LEFTPADDING', (0, 0), (-1, -1), 4),
        ('RIGHTPADDING', (0, 0), (-1, -1), 4),
    ]))
    
    col_widths = [60] + [90] * 5
    table._argW = col_widths
    story.append(table)
    
    story.append(Spacer(1, 20))
    footer_style = ParagraphStyle('Footer', parent=styles['Normal'],
                                   fontSize=7, alignment=TA_CENTER,
                                   textColor=colors.HexColor('#718096'))
    footer = Paragraph("This schedule is automatically generated from the class assignments in the system.", footer_style)
    story.append(footer)
    
    doc.build(story)
    return response



    # ============================================================
# SHARED HELPER FUNCTIONS
# ============================================================

def _build_student_maps(enrollments):
    """Build name lookup dicts from an enrollment queryset."""
    student_map = {}
    name_variants = {}

    for enrollment in enrollments:
        student = enrollment.student
        full_name = '{}, {}'.format(student.last_name, student.first_name).lower()
        first_name = student.first_name.lower() if student.first_name else ''
        last_name = student.last_name.lower() if student.last_name else ''

        student_map[full_name] = {
            'enrollment_id': enrollment.id,
            'enrollment': enrollment,
            'first_name': first_name,
            'last_name': last_name,
        }

        if first_name not in name_variants:
            name_variants[first_name] = []
        name_variants[first_name].append({
            'full_name': full_name,
            'last_name': last_name,
            'enrollment_id': enrollment.id,
            'enrollment': enrollment,
        })

    return student_map, name_variants


def _detect_columns(sheet):
    """Scan header rows and return (name_col, quarter_columns dict, final_col)."""
    QUARTER_NAMES = {
        'FIRST QUARTER': 'Q1',
        'SECOND QUARTER': 'Q2',
        'THIRD QUARTER': 'Q3',
        'FOURTH QUARTER': 'Q4',
    }

    name_col = 1
    quarter_columns = {}
    final_col = None

    for row_num in range(1, min(15, sheet.max_row + 1)):
        for col_num in range(1, min(15, sheet.max_column + 1)):
            cell_val = sheet.cell(row=row_num, column=col_num).value
            if not cell_val:
                continue
            cell_str = str(cell_val).strip().upper()

            if 'LEARNER' in cell_str and 'NAME' in cell_str:
                name_col = col_num
            elif cell_str in QUARTER_NAMES:
                quarter_columns[QUARTER_NAMES[cell_str]] = col_num
            elif 'FINAL' in cell_str and 'GRADE' in cell_str:
                final_col = col_num

    return name_col, quarter_columns, final_col


def _find_section_start(sheet, name_col, marker, after_row=1):
    """Find the row after a MALE/FEMALE marker. Returns None if not found."""
    for row_num in range(after_row, min(sheet.max_row + 1, after_row + 200)):
        cell_val = sheet.cell(row=row_num, column=name_col).value
        if cell_val and str(cell_val).strip().upper() == marker:
            return row_num + 1
    return None


def _match_name(clean_name, student_map, name_variants):
    """Return enrollment_id for a name string, or None."""
    if not clean_name:
        return None

    parsed_first = parsed_last = None

    if ',' in clean_name:
        parts = clean_name.split(',', 1)
        parsed_last = parts[0].strip()
        first_parts = parts[1].strip().split()
        parsed_first = first_parts[0] if first_parts else ''
    else:
        name_parts = clean_name.split()
        if len(name_parts) >= 2:
            parsed_first = name_parts[0]
            parsed_last = name_parts[-1]
        elif len(name_parts) == 1:
            parsed_first = name_parts[0]

    if not parsed_first:
        return None

    # 1. Exact last, first
    if parsed_last:
        full_key = '{}, {}'.format(parsed_last, parsed_first).lower()
        if full_key in student_map:
            return student_map[full_key]['enrollment_id']

    # 2. First-name variants
    fn_lower = parsed_first.lower()
    if fn_lower in name_variants:
        candidates = name_variants[fn_lower]
        if len(candidates) == 1:
            return candidates[0]['enrollment_id']
        if parsed_last:
            ln_lower = parsed_last.lower()
            for cand in candidates:
                if cand['last_name'] == ln_lower:
                    return cand['enrollment_id']

    # 3. Fuzzy fallback
    if parsed_last:
        ln_lower = parsed_last.lower()
        fn_lower2 = parsed_first.lower()
        for full_name, data in student_map.items():
            if fn_lower2 in data['first_name'] or ln_lower in data['last_name']:
                return data['enrollment_id']

    return None


def _get_descriptor(transmuted_value):
    if transmuted_value >= 90:
        return 'Outstanding'
    elif transmuted_value >= 85:
        return 'Very_Satisfactory'
    elif transmuted_value >= 80:
        return 'Satisfactory'
    elif transmuted_value >= 75:
        return 'Fairly_Satisfactory'
    return 'Did_Not_Meet_Expectations'


def _upsert_grade(enrollment, subject, grade_quarter, transmuted_value, grade_value, descriptor, user):
    """
    Save a grade bypassing model save() to preserve the exact transmuted_value.
    Uses UPDATE first, then raw INSERT if no row exists.
    Both paths bypass full_clean() and model save() recomputation.
    """
    from django.db import connection
    from django.utils import timezone as tz

    now = tz.now().strftime('%Y-%m-%d %H:%M:%S')

    # Try UPDATE first
    updated = GradeComponent.objects.filter(
        enrollment=enrollment,
        subject=subject,
        quarter=grade_quarter,
    ).update(
        transmuted_grade=transmuted_value,
        initial_grade=grade_value,
        validation_status='Submitted',
        descriptor=descriptor,
        encoded_by_id=user.id,
        encoding_date=now,
        updated_at=now,
    )

    if not updated:
        # Raw INSERT — bypasses save() and full_clean() entirely
        with connection.cursor() as cursor:
            cursor.execute("""
                INSERT INTO grades_gradecomponent (
                    enrollment_id, subject_id, quarter_id,
                    transmuted_grade, initial_grade,
                    written_work_raw, written_work_max,
                    performance_task_raw, performance_task_max,
                    quarterly_assessment_raw, quarterly_assessment_max,
                    validation_status, descriptor,
                    encoded_by_id, encoding_date,
                    is_locked, validation_notes, remarks,
                    created_at, updated_at
                ) VALUES (
                    %s, %s, %s,
                    %s, %s,
                    %s, %s, %s, %s, %s, %s,
                    'Submitted', %s,
                    %s, %s,
                    0, '', '',
                    %s, %s
                )
            """, [
                enrollment.id, subject.id, grade_quarter.id,
                transmuted_value, grade_value,
                grade_value, 100,   # written_work placeholder
                grade_value, 100,   # performance_task placeholder
                grade_value, 100,   # quarterly_assessment placeholder
                descriptor,
                user.id, now,
                now, now,
            ])


def _process_sheet_rows(sheet, start_row, name_col, quarter_columns,
                        student_map, name_variants, subject, current_sy, user,
                        stop_at=None):
    """
    Walk rows from start_row, match names, save grades.
    Returns (last_row_processed, saved_count, warnings).
    """
    import re

    saved = 0
    warnings = []
    row = start_row if start_row else sheet.max_row + 1

    while row <= sheet.max_row:
        cell_val = sheet.cell(row=row, column=name_col).value
        cell_str = str(cell_val).strip() if cell_val is not None else ''
        cell_upper = cell_str.upper()

        # Stop at the next section marker if requested
        if stop_at and cell_upper == stop_at:
            break

        # Skip empty
        if not cell_str:
            row += 1
            continue

        # Strip leading row numbers
        clean_name = re.sub(r'^\d+[\.\s]*', '', cell_str).strip()

        # Skip blank template slots
        if not clean_name or not re.search(r'[A-Za-z]', clean_name):
            row += 1
            continue

        # Skip stray markers
        if clean_name.upper() in ('MALE', 'FEMALE'):
            row += 1
            continue

        enrollment_id = _match_name(clean_name, student_map, name_variants)

        if enrollment_id:
            enrollment = student_map.get(
                next((k for k in student_map if student_map[k]['enrollment_id'] == enrollment_id), None),
                {}
            ).get('enrollment')

            # Fallback enrollment lookup
            if not enrollment:
                try:
                    enrollment = Enrollment.objects.get(id=enrollment_id)
                except Enrollment.DoesNotExist:
                    row += 1
                    continue

            quarters_saved = 0
            for quarter_label, col_num in quarter_columns.items():
                grade_val = sheet.cell(row=row, column=col_num).value
                if grade_val is None:
                    continue

                try:
                    grade_value = round(float(grade_val), 2)
                    if grade_value < 0 or grade_value > 100:
                        warnings.append('Grade {} out of range for {} ({})'.format(
                            grade_value, clean_name, quarter_label))
                        continue

                    grade_quarter = Quarter.objects.get(
                        school_year=current_sy, quarter_label=quarter_label
                    )

                    transmuted_value = max(60, min(100, int(round(grade_value))))
                    descriptor = _get_descriptor(transmuted_value)

                    _upsert_grade(enrollment, subject, grade_quarter,
                                  transmuted_value, grade_value, descriptor, user)
                    quarters_saved += 1

                except Quarter.DoesNotExist:
                    warnings.append('Quarter {} not found'.format(quarter_label))
                except (ValueError, TypeError):
                    warnings.append('Invalid grade for {} ({}): {}'.format(
                        clean_name, quarter_label, grade_val))
                except Exception as e:
                    warnings.append('Error for {} ({}): {}'.format(clean_name, quarter_label, str(e)))

            if quarters_saved > 0:
                saved += 1
            else:
                warnings.append('No valid grades saved for: {}'.format(clean_name))
        else:
            warnings.append('Student not found: {}'.format(clean_name))

        row += 1

    return row, saved, warnings