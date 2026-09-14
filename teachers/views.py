import csv
import io
from datetime import date
from openpyxl import load_workbook

from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import JsonResponse, HttpResponse
from django.views.decorators.csrf import csrf_exempt
from django.utils import timezone
from django.db import transaction
from django.db.models import Max
import json
import random

from accounts.models import UserProfile
from scheduling.models import ClassAssignment
from enrollment.models import Enrollment
from grades.models import GradeComponent
from academics.models import Section, Subject, Quarter, SchoolYear
from academics.models import Assessment, AssessmentQuestion, AssessmentResponse, AssessmentAnswer
from students.models import Student


# =============================================================================
# DASHBOARD
# =============================================================================

@login_required
def dashboard(request):
    """Teacher Dashboard."""
    if not hasattr(request.user, 'profile') or request.user.profile.role != 'teacher':
        messages.error(request, 'Access denied. Teachers only.')
        return redirect('signin')
    
    teacher_profile = request.user.profile
    teacher_school = teacher_profile.school
    
    if not teacher_school:
        messages.error(request, 'You are not assigned to any school.')
        return redirect('signin')
    
    today = date.today()
    current_sy = SchoolYear.objects.filter(school=teacher_school, is_current=True).first()
    
    assignments = ClassAssignment.objects.filter(
        teacher=request.user, school_year=current_sy, is_active=True
    ).select_related('section', 'section__grade_level', 'subject')
    
    current_quarter = Quarter.objects.filter(
        school_year=current_sy, is_current_quarter=True
    ).first() if current_sy else None
    
    assignment_data = []
    total_students = 0
    total_sections = set()
    subject_breakdown = {}
    
    for assignment in assignments:
        student_count = Enrollment.objects.filter(
            section=assignment.section, school_year=current_sy,
            status__in=['Enrolled', 'Transferred_In']
        ).count()
        
        if current_quarter:
            grades_submitted = GradeComponent.objects.filter(
                enrollment__section=assignment.section, subject=assignment.subject,
                quarter=current_quarter, initial_grade__isnull=False
            ).count()
        else:
            grades_submitted = 0
        
        completion_pct = round((grades_submitted / student_count * 100), 1) if student_count > 0 else 0
        total_students += student_count
        total_sections.add(assignment.section_id)
        
        subj_code = assignment.subject.subject_code
        if subj_code not in subject_breakdown:
            subject_breakdown[subj_code] = {'students': 0, 'section_count': 0, 'completion': 0}
        subject_breakdown[subj_code]['students'] += student_count
        subject_breakdown[subj_code]['section_count'] += 1
        subject_breakdown[subj_code]['completion'] = completion_pct
        
        assignment_data.append({
            'assignment': assignment, 'section': assignment.section,
            'subject': assignment.subject, 'student_count': student_count,
            'grades_submitted': grades_submitted, 'completion_pct': completion_pct,
            'pending': student_count - grades_submitted,
        })
    
    total_pending = sum(a['pending'] for a in assignment_data)
    grade_completion = round(((total_students - total_pending) / total_students * 100), 1) if total_students > 0 else 0
    
    context = {
        'teacher': teacher_profile, 'school': teacher_school,
        'current_sy': current_sy, 'current_quarter': current_quarter,
        'assignments': assignment_data, 'total_students': total_students,
        'total_sections': len(total_sections), 'total_assignments': assignments.count(),
        'pending_grades': total_pending, 'grade_completion': grade_completion,
        'subject_breakdown': [
            {'subject_code': k, 'students': v['students'], 'section_count': v['section_count'], 'completion': v['completion']}
            for k, v in subject_breakdown.items()
        ],
        'today': today,
    }
    return render(request, 'teachers/dashboard.html', context)


# =============================================================================
# ASSESSMENTS (unchanged)
# =============================================================================

@login_required
def assessment_list(request):
    if request.user.profile.role != 'teacher':
        return redirect('signin')
    assessments = Assessment.objects.filter(teacher=request.user).select_related('subject', 'section').order_by('-created_at')
    return render(request, 'teachers/assessments/list.html', {
        'assessments': assessments,
        'subjects': Subject.objects.filter(school=request.user.profile.school, is_active=True),
        'sections': Section.objects.filter(school=request.user.profile.school, is_active=True),
    })

@login_required
@csrf_exempt
def assessment_create(request):
    if request.method != 'POST':
        return JsonResponse({'success': False, 'error': 'POST required'}, status=405)
    try:
        data = json.loads(request.body)
        with transaction.atomic():
            assessment = Assessment.objects.create(
                teacher=request.user, subject_id=data['subject_id'], section_id=data['section_id'],
                school_year_id=data['school_year_id'], quarter_id=data.get('quarter_id'),
                title=data['title'], description=data.get('description', ''),
                total_items=data['total_items'], points_per_item=data.get('points_per_item', 1),
                passing_score=data.get('passing_score', 60),
                time_limit_minutes=data.get('time_limit_minutes'), status='draft',
            )
            for i, q_data in enumerate(data['questions']):
                choices = q_data['choices']
                random.shuffle(choices)
                AssessmentQuestion.objects.create(
                    assessment=assessment, question_text=q_data['question_text'],
                    order_number=i+1, num_choices=len(choices),
                    correct_answer_index=q_data['correct_index'], choices=choices,
                )
            assessment.shuffle_questions()
            assessment.status = 'published'
            assessment.save()
        return JsonResponse({'success': True, 'assessment_id': assessment.id,
            'access_code': assessment.access_code, 'share_url': assessment.get_share_url()})
    except Exception as e:
        return JsonResponse({'success': False, 'error': str(e)}, status=500)

@login_required
def assessment_detail(request, assessment_id):
    assessment = get_object_or_404(Assessment, id=assessment_id, teacher=request.user)
    questions = assessment.questions.all().order_by('order_number')
    responses = assessment.responses.all().order_by('-submitted_at')
    total_responses = responses.count()
    passed_count = responses.filter(passed=True).count()
    return render(request, 'teachers/assessments/detail.html', {
        'assessment': assessment, 'questions': questions, 'responses': responses,
        'total_responses': total_responses, 'passed_count': passed_count,
        'failed_count': total_responses - passed_count,
        'passing_rate': round((passed_count/total_responses*100),1) if total_responses > 0 else 0,
    })


# =============================================================================
# CLASS RECORDS
# =============================================================================

@login_required
def class_record_list(request):
    """Teacher sees their class records with expandable student lists."""
    if request.user.profile.role != 'teacher':
        return redirect('signin')
    
    school = request.user.profile.school
    current_sy = SchoolYear.objects.filter(school=school, is_current=True).first()
    quarters = Quarter.objects.filter(school_year=current_sy).order_by('quarter_number') if current_sy else []
    
    assignments = ClassAssignment.objects.filter(
        teacher=request.user, school_year=current_sy, is_active=True
    ).select_related('section', 'section__grade_level', 'subject')
    
    assignment_data = []
    total_students = 0
    
    for a in assignments:
        enrollments = Enrollment.objects.filter(
            section=a.section, school_year=current_sy,
            status__in=['Enrolled', 'Transferred_In']
        ).select_related('student').order_by('student__last_name', 'student__first_name')
        
        student_count = enrollments.count()
        total_students += student_count
        
        quarter_stats = []
        for q in quarters:
            grades_done = GradeComponent.objects.filter(
                enrollment__section=a.section, subject=a.subject,
                quarter=q, initial_grade__isnull=False
            ).count()
            quarter_stats.append({
                'quarter': q.quarter_label, 'done': grades_done, 'total': student_count,
                'complete': grades_done == student_count and student_count > 0,
            })
        
        students_data = []
        for e in enrollments:
            quarter_grades = []
            final_sum = 0
            final_count = 0
            for q in quarters:
                grade = GradeComponent.objects.filter(enrollment=e, subject=a.subject, quarter=q).first()
                if grade and grade.initial_grade is not None:
                    qg = int(float(grade.initial_grade))
                    quarter_grades.append(qg)
                    final_sum += qg
                    final_count += 1
                else:
                    quarter_grades.append(None)
            final_grade = round(final_sum / final_count) if final_count > 0 else None
            students_data.append({
                'last_name': e.student.last_name, 'first_name': e.student.first_name,
                'lrn': e.student.lrn, 'quarter_grades': quarter_grades, 'final_grade': final_grade,
            })
        
        assignment_data.append({
            'section': a.section, 'subject': a.subject, 'student_count': student_count,
            'quarter_stats': quarter_stats, 'students': students_data,
        })
    
    return render(request, 'teachers/class_records/list.html', {
        'assignments': assignment_data, 'current_sy': current_sy,
        'quarters': quarters, 'total_students': total_students,
    })


@login_required
def upload_class_record(request):
    """Teacher uploads grades via CSV or DepEd E-Class Record Excel.
    Excel: Auto-detects section by matching student names (≥3 matches).
    CSV: Requires subject, section, and quarter selection."""
    if request.user.profile.role != 'teacher':
        return redirect('signin')
    
    school = request.user.profile.school
    current_sy = SchoolYear.objects.filter(school=school, is_current=True).first()
    
    if not current_sy:
        messages.error(request, 'No active school year.')
        return redirect('teachers:class_record_list')
    
    # Download CSV template
    if 'download_template' in request.GET:
        response = HttpResponse(content_type='text/csv')
        response['Content-Disposition'] = 'attachment; filename="quarterly_grades_template.csv"'
        writer = csv.writer(response)
        writer.writerow(['student_lrn', 'student_name', 'subject_code', 'section_name', 'quarter', 'grade'])
        writer.writerow(['2024-A001', 'Miguel Aguilar', 'SP-STEM-PRECALC-G11', 'STEM A', 'Q1', '88'])
        writer.writerow(['2024-A002', 'Katrina Bernardo', 'SP-STEM-PRECALC-G11', 'STEM A', 'Q1', '92'])
        return response
    
    if request.method == 'POST':
        uploaded_file = request.FILES.get('csv_file')
        
        if not uploaded_file:
            messages.error(request, 'Please select a file.')
            return redirect('teachers:upload_class_record')
        
        filename = uploaded_file.name.lower()
        is_excel = filename.endswith('.xlsx') or filename.endswith('.xls')
        is_csv = filename.endswith('.csv')
        
        if not is_excel and not is_csv:
            messages.error(request, 'Unsupported file type. Use CSV or Excel (.xlsx).')
            return redirect('teachers:upload_class_record')
        
        # ✅ PREVIEW MODE — Auto-detect section from Excel
        if request.POST.get('preview_only') == 'true' and is_excel:
            try:
                wb = load_workbook(uploaded_file, data_only=True)
                summary_sheet = None
                for name in wb.sheetnames:
                    if 'SUMMARY' in name.upper():
                        summary_sheet = wb[name]
                        break
                
                if not summary_sheet:
                    return JsonResponse({'error': 'Summary sheet not found'}, status=400)
                
                excel_names = []
                for row in summary_sheet.iter_rows(min_row=12, max_row=summary_sheet.max_row):
                    name = str(row[1].value or '').strip() if len(row) > 1 else ''
                    if len(name) > 2 and name.upper() not in ['MALE', 'FEMALE', "LEARNERS' NAMES", 'TOTAL', 'AVERAGE']:
                        excel_names.append(name)
                
                best_section = None
                best_subject = None
                best_match = 0
                best_total = 0
                
                teacher_assignments = ClassAssignment.objects.filter(
                    teacher=request.user, school_year=current_sy, is_active=True
                ).select_related('section', 'subject')
                
                for assignment in teacher_assignments:
                    enrolled_names = list(Enrollment.objects.filter(
                        section=assignment.section, school_year=current_sy,
                        status__in=['Enrolled', 'Transferred_In']
                    ).values_list('student__first_name', flat=True))
                    
                    matches = 0
                    for excel_name in excel_names:
                        excel_lower = excel_name.lower()
                        for enrolled_name in enrolled_names:
                            if enrolled_name and excel_lower == enrolled_name.lower():
                                matches += 1
                                break
                    
                    if matches >= 3 and matches > best_match:
                        best_match = matches
                        best_total = len(enrolled_names)
                        best_section = assignment.section.section_name
                        best_subject = assignment.subject.subject_code
                
                quarter_counts = {}
                QUARTER_COLS = {'Q1': 5, 'Q2': 8, 'Q3': 11, 'Q4': 14}
                
                for row in summary_sheet.iter_rows(min_row=12, max_row=summary_sheet.max_row):
                    for q_label, col_idx in QUARTER_COLS.items():
                        val = row[col_idx].value if len(row) > col_idx else None
                        if val is not None:
                            try:
                                int(float(str(val)))
                                quarter_counts[q_label] = quarter_counts.get(q_label, 0) + 1
                            except (ValueError, TypeError):
                                pass
                
                return JsonResponse({
                    'subject': best_subject or 'Not detected',
                    'section': best_section or 'Not detected',
                    'matched': best_match,
                    'total': best_total,
                    'grades_found': sum(quarter_counts.values()),
                    'quarters': list(quarter_counts.keys()),
                    'q1_count': quarter_counts.get('Q1', 0),
                    'q2_count': quarter_counts.get('Q2', 0),
                    'q3_count': quarter_counts.get('Q3', 0),
                    'q4_count': quarter_counts.get('Q4', 0),
                })
                
            except Exception as e:
                return JsonResponse({'error': str(e)}, status=500)
        
        # ✅ ACTUAL IMPORT
        subject_code = request.POST.get('subject_code', '').strip()
        section_name = request.POST.get('section_name', '').strip()
        
        if is_csv:
            if not subject_code or not section_name:
                messages.error(request, 'Please select subject and section for CSV upload.')
                return redirect('teachers:upload_class_record')
            grades_data = parse_csv_grades(uploaded_file)
        else:
            # Excel — auto-detect if needed
            if not subject_code or not section_name:
                wb = load_workbook(uploaded_file, data_only=True)
                summary_sheet = None
                for name in wb.sheetnames:
                    if 'SUMMARY' in name.upper():
                        summary_sheet = wb[name]
                        break
                
                if summary_sheet:
                    excel_names = []
                    for row in summary_sheet.iter_rows(min_row=12, max_row=summary_sheet.max_row):
                        name = str(row[1].value or '').strip() if len(row) > 1 else ''
                        if len(name) > 2 and name.upper() not in ['MALE', 'FEMALE']:
                            excel_names.append(name)
                    
                    best_section = None
                    best_subject = None
                    best_match = 0
                    
                    for assignment in ClassAssignment.objects.filter(
                        teacher=request.user, school_year=current_sy, is_active=True
                    ):
                        enrolled_names = list(Enrollment.objects.filter(
                            section=assignment.section, school_year=current_sy,
                            status__in=['Enrolled', 'Transferred_In']
                        ).values_list('student__first_name', flat=True))
                        
                        matches = 0
                        for excel_name in excel_names:
                            excel_lower = excel_name.lower()
                            for enrolled_name in enrolled_names:
                                if enrolled_name and excel_lower == enrolled_name.lower():
                                    matches += 1
                                    break
                        
                        if matches >= 3 and matches > best_match:
                            best_match = matches
                            best_section = assignment.section.section_name
                            best_subject = assignment.subject.subject_code
                    
                    if best_section and best_subject:
                        subject_code = best_subject
                        section_name = best_section
                        print(f"✅ AUTO-DETECTED: {section_name} / {subject_code} (matched {best_match} students)")
                    else:
                        print(f"❌ AUTO-DETECT FAILED: best_match={best_match}")
                        messages.error(request, 'Could not auto-detect section. Please use CSV format.')
                        return redirect('teachers:upload_class_record')
                else:
                    messages.error(request, 'Summary sheet not found.')
                    return redirect('teachers:upload_class_record')
            
            grades_data = parse_excel_all_quarters(uploaded_file, subject_code, section_name)
        
        # ✅ DEBUG
        print(f"\n=== IMPORTING GRADES ===")
        print(f"Subject: {subject_code}")
        print(f"Section: {section_name}")
        print(f"Grades found: {len(grades_data) if grades_data else 0}")
        if grades_data:
            for g in grades_data[:3]:
                print(f"  {g['student_name']} | {g['quarter']} | grade={g['grade']}")
        
        if not grades_data:
            messages.error(request, 'No valid grades found in file.')
            return redirect('teachers:upload_class_record')
        
        # ✅ PROCESS
        success, updated, errors = process_all_grades(grades_data, request.user, school, current_sy)
        
        print(f"✅ Result: {success} new, {updated} updated, {len(errors) if errors else 0} errors")
        if errors:
            for e in errors[:5]:
                print(f"  Error: {e}")
        
        if success > 0 or updated > 0:
            messages.success(request, f'✅ {success} new, {updated} updated — {section_name} ({subject_code})!')
        if errors:
            messages.warning(request, f'⚠️ {len(errors)} errors: {"; ".join(errors[:3])}')
        
        return redirect('teachers:class_record_list')
    
    quarters = Quarter.objects.filter(school_year=current_sy).order_by('quarter_number') if current_sy else []
    return render(request, 'teachers/class_records/upload.html', {
        'subjects': Subject.objects.filter(school=school, is_active=True),
        'sections': Section.objects.filter(school=school, is_active=True),
        'quarters': quarters,
    })

# =============================================================================
# PARSERS
# =============================================================================

def parse_csv_grades(uploaded_file):
    """Parse CSV: student_lrn, student_name, subject_code, section_name, quarter, grade"""
    data = uploaded_file.read().decode('utf-8-sig')
    reader = csv.DictReader(io.StringIO(data))
    grades = []
    for row in reader:
        grades.append({
            'student_lrn': row.get('student_lrn', '').strip(),
            'student_name': row.get('student_name', '').strip(),
            'subject_code': row.get('subject_code', '').strip(),
            'section_name': row.get('section_name', '').strip(),
            'quarter': row.get('quarter', 'Q1').strip(),
            'grade': row.get('grade', '').strip(),
        })
    return grades


def parse_excel_all_quarters(uploaded_file, subject_code, section_name):
    """
    Parse DepEd E-Class Record — reads ALL quarters at once from Summary sheet.
    Column B (1) = Student Name
    Column F (5) = Q1, Column I (8) = Q2, Column L (11) = Q3, Column O (14) = Q4
    """
    wb = load_workbook(uploaded_file, data_only=True)
    
    # Find SUMMARY sheet
    summary_sheet = None
    for name in wb.sheetnames:
        if 'SUMMARY' in name.upper():
            summary_sheet = wb[name]
            break
    
    if not summary_sheet:
        return []
    
    print(f"📊 Reading: {summary_sheet.title}")
    
    NAME_COL = 1
    QUARTER_COLS = {'Q1': 5, 'Q2': 8, 'Q3': 11, 'Q4': 14}
    
    all_grades = []
    
    for row in summary_sheet.iter_rows(min_row=12, max_row=summary_sheet.max_row):
        name_cell = row[NAME_COL].value if len(row) > NAME_COL else None
        
        if not name_cell:
            continue
        
        student_name = str(name_cell).strip()
        
        # Skip non-student rows
        if len(student_name) < 3:
            continue
        if student_name.upper() in ['MALE', 'FEMALE', "LEARNERS' NAMES", 'TOTAL', 'AVERAGE']:
            continue
        if 'QUARTER' in student_name.upper() or 'GRADE' in student_name.upper():
            continue
        if student_name.replace('.', '').replace(',', '').strip().isdigit():
            continue
        
        # ✅ Read ALL quarters for this student
        for q_label, col_idx in QUARTER_COLS.items():
            grade_cell = row[col_idx].value if len(row) > col_idx else None
            
            if grade_cell is not None:
                try:
                    grade = int(float(str(grade_cell)))
                    if 0 <= grade <= 100:
                        all_grades.append({
                            'student_lrn': '',
                            'student_name': student_name,
                            'subject_code': subject_code,
                            'section_name': section_name,
                            'quarter': q_label,
                            'grade': str(grade),
                        })
                except (ValueError, TypeError):
                    pass
    
    # Count per quarter for logging
    for q in ['Q1', 'Q2', 'Q3', 'Q4']:
        count = sum(1 for g in all_grades if g['quarter'] == q)
        print(f"   {q}: {count} grades")
    
    print(f"   ✅ Total: {len(all_grades)} grades extracted")
    return all_grades


# =============================================================================
# GRADE PROCESSOR
# =============================================================================

def process_all_grades(grades_data, teacher_user, school, current_sy):
    """Save ALL grades to database. Handles multiple quarters at once."""
    success_count = 0
    updated_count = 0
    error_rows = []
    
    with transaction.atomic():
        for i, row in enumerate(grades_data):
            try:
                student_lrn = row.get('student_lrn', '').strip()
                student_name = row.get('student_name', '').strip()
                subject_code = row.get('subject_code', '').strip()
                section_name = row.get('section_name', '').strip()
                quarter_label = row.get('quarter', 'Q1').strip()
                grade_str = row.get('grade', '').strip()
                
                if not grade_str:
                    continue
                
                grade = int(float(grade_str))
                if grade < 0 or grade > 100:
                    continue
                
                # Find student
                student = None
                if student_lrn:
                    student = Student.objects.filter(lrn=student_lrn).first()
                if not student and student_name:
                    student = Student.objects.filter(first_name__iexact=student_name).first()
                if not student:
                    error_rows.append(f'{student_name or student_lrn} not found')
                    continue
                
                # Find enrollment
                enrollment = Enrollment.objects.filter(
                    student=student, section__section_name__iexact=section_name,
                    section__school=school, school_year=current_sy,
                    status__in=['Enrolled', 'Transferred_In']
                ).first()
                
                if not enrollment:
                    error_rows.append(f'{student_name} not enrolled in {section_name}')
                    continue
                
                # Find subject
                subject = Subject.objects.filter(
                    subject_code__iexact=subject_code, school=school, is_active=True
                ).first()
                if not subject:
                    error_rows.append(f'Subject {subject_code} not found')
                    continue
                
                # Find quarter
                quarter = Quarter.objects.filter(
                    school_year=current_sy, quarter_label__iexact=quarter_label
                ).first()
                if not quarter:
                    error_rows.append(f'Quarter {quarter_label} not found')
                    continue
                
                # ✅ SAVE with ALL required fields
                _, created = GradeComponent.objects.update_or_create(
                    enrollment=enrollment,
                    subject=subject,
                    quarter=quarter,
                    defaults={
                        'initial_grade': grade,
                        'written_work_raw': 0,
                        'written_work_max': 100,
                        'performance_task_raw': 0,
                        'performance_task_max': 100,
                        'quarterly_assessment_raw': 0,
                        'quarterly_assessment_max': 100,
                        'validation_status': 'Draft',
                        'is_locked': False,
                    }
                )
                
                if created:
                    success_count += 1
                else:
                    updated_count += 1
                    
            except Exception as e:
                error_rows.append(f'{row.get("student_name", "?")}: {str(e)}')
    
    return success_count, updated_count, error_rows