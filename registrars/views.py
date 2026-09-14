from django.shortcuts import render, redirect
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.http import HttpResponse
from django.utils import timezone
from django.db import transaction
from datetime import date
import csv
import io

from accounts.models import UserProfile
from academics.models import School, SchoolYear, Quarter, Section, GradeLevel, Subject, Semester
from scheduling.models import ClassAssignment
from enrollment.models import Enrollment
from students.models import Student
from grades.models import GradeComponent


@login_required
def dashboard(request):
    """Registrar Dashboard."""
    if request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    school = request.user.profile.school
    current_sy = SchoolYear.objects.filter(school=school, is_current=True).first()
    
    # Stats
    total_students = Enrollment.objects.filter(
        school_year=current_sy,
        status__in=['Enrolled', 'Transferred_In'],
        section__school=school
    ).count() if current_sy else 0
    
    total_sections = Section.objects.filter(
        school=school, school_year=current_sy, is_active=True
    ).count() if current_sy else 0
    
    total_teachers = UserProfile.objects.filter(
        role='teacher', school=school, is_active=True
    ).count()
    
    total_subjects = Subject.objects.filter(school=school, is_active=True).count()
    
    # Recent uploads
    recent_enrollments = Enrollment.objects.filter(
        section__school=school,
        school_year=current_sy
    ).select_related('student', 'section').order_by('-created_at')[:10] if current_sy else []
    
    context = {
        'school': school,
        'current_sy': current_sy,
        'total_students': total_students,
        'total_sections': total_sections,
        'total_teachers': total_teachers,
        'total_subjects': total_subjects,
        'recent_enrollments': recent_enrollments,
        'today': date.today(),
    }
    return render(request, 'registrars/dashboard.html', context)


@login_required
def upload_class_list(request):
    """Upload class list CSV — Create or Update mode."""
    if request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    school = request.user.profile.school
    current_sy = SchoolYear.objects.filter(school=school, is_current=True).first()
    
    if not current_sy:
        messages.error(request, 'No active school year.')
        return redirect('registrars:dashboard')
    
    if request.method == 'POST':
        csv_file = request.FILES.get('csv_file')
        
        if not csv_file:
            messages.error(request, 'Please select a CSV file.')
            return redirect('registrars:upload_class_list')
        
        try:
            data = csv_file.read().decode('utf-8-sig')
            lines = data.split('\n')
            
            header_info = {}
            student_start_row = 0
            
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
            
            section_name = header_info.get('section_name', 'Default')
            year_level = header_info.get('year_level', '1st')
            
            grade_number = 1
            if year_level:
                digits = ''.join(filter(str.isdigit, year_level))
                if digits:
                    grade_number = int(digits)
            
            grade_name = f"Grade {grade_number}" if grade_number else year_level
            
            # ✅ Find or create Grade Level
            grade_level = GradeLevel.objects.filter(
                school=school,
                grade_number=grade_number,
            ).first()
            
            if not grade_level:
                max_sort = GradeLevel.objects.aggregate(Max('sort_order'))['sort_order__max'] or 0
                max_num = GradeLevel.objects.aggregate(Max('grade_number'))['grade_number__max'] or 0
                
                grade_level = GradeLevel.objects.create(
                    school=school,
                    grade_code=f"G{grade_number}",
                    grade_name=grade_name,
                    grade_number=grade_number if not GradeLevel.objects.filter(grade_number=grade_number).exists() else max_num + 1,
                    level_category='SHS' if grade_number <= 12 else 'COLLEGE',
                    is_senior_high=grade_number <= 12,
                    sort_order=max_sort + 1,
                )
            
            # ===== CREATE OR GET SUBJECT =====
            subject_code = header_info.get('subject_code', 'UNKNOWN')
            subject_name = header_info.get('subject_name', 'Unknown Subject')
            
            subject, _ = Subject.objects.get_or_create(
                subject_code=subject_code[:25],
                school=school,
                defaults={
                    'subject_name': subject_name[:200],
                    'grade_level': grade_level,
                    'is_active': True,
                }
            )
            
            # ===== CREATE OR UPDATE SECTION =====
            section = Section.objects.filter(
                section_name__iexact=section_name,
                school=school,
                school_year=current_sy,
                grade_level=grade_level,
            ).first()
            
            if section:
                action = 'updated'
            else:
                section = Section.objects.create(
                    section_name=section_name[:60],
                    school=school,
                    grade_level=grade_level,
                    school_year=current_sy,
                    is_active=True,
                )
                action = 'created'
            
            # ===== FIND/CREATE TEACHER =====
            instructor_name = header_info.get('instructor_name', '')
            teacher_user = None
            
            if instructor_name:
                name_parts = instructor_name.split()
                if len(name_parts) >= 2:
                    first = name_parts[0]
                    last = name_parts[-1]
                    profile = UserProfile.objects.filter(
                        role='teacher',
                        school=school,
                        user__first_name__icontains=first,
                        user__last_name__icontains=last,
                        is_active=True
                    ).first()
                    if profile:
                        teacher_user = profile.user
            
            if teacher_user:
                ClassAssignment.objects.get_or_create(
                    teacher=teacher_user,
                    section=section,
                    subject=subject,
                    school_year=current_sy,
                    defaults={'is_active': True}
                )
            
            # ===== PROCESS STUDENTS =====
            success_count = 0
            existing_count = 0
            error_rows = []
            
            with transaction.atomic():
                for i in range(student_start_row, len(lines)):
                    line = lines[i].strip()
                    if not line or ',' not in line:
                        continue
                    
                    parts = [p.strip().strip('"') for p in line.split(',')]
                    if len(parts) < 2:
                        continue
                    
                    student_id = parts[0].strip()
                    student_name = parts[1].strip() if len(parts) > 1 else ''
                    
                    if not student_id or not student_name:
                        continue
                    
                    try:
                        name_parts = student_name.split(',')
                        last_name = name_parts[0].strip() if name_parts else ''
                        first_name = name_parts[1].strip() if len(name_parts) > 1 else ''
                        
                        # ✅ Update or create student
                        student, _ = Student.objects.update_or_create(
                            lrn=student_id,
                            defaults={
                                'first_name': first_name[:100],
                                'last_name': last_name[:100],
                            }
                        )
                        
                        # ✅ Check if already enrolled in THIS section
                        existing_enrollment = Enrollment.objects.filter(
                            student=student,
                            section=section,
                            school_year=current_sy,
                        ).first()
                        
                        if existing_enrollment:
                            # Already in this section — skip
                            if existing_enrollment.status not in ['Enrolled', 'Transferred_In']:
                                existing_enrollment.status = 'Enrolled'
                                existing_enrollment.save()
                            existing_count += 1
                        else:
                            # New enrollment
                            Enrollment.objects.create(
                                student=student,
                                section=section,
                                school_year=current_sy,
                                status='Enrolled'
                            )
                            success_count += 1
                            
                    except Exception as e:
                        error_str = str(e)
                        # ✅ Treat duplicate enrollment as "existing" not error
                        if 'UNIQUE constraint' in error_str and 'enrollment' in error_str:
                            existing_count += 1
                        else:
                            error_rows.append(f'Student {student_id}: {error_str}')
            
            # Update section count
            section.current_enrollment_count = Enrollment.objects.filter(
                section=section, school_year=current_sy,
                status__in=['Enrolled', 'Transferred_In']
            ).count()
            section.save()
            
            # ✅ Clean success message
            msg_parts = [f'✅ Section "{section_name}" {action}!']
            if success_count > 0:
                msg_parts.append(f'{success_count} new')
            if existing_count > 0:
                msg_parts.append(f'{existing_count} existing')
            msg_parts.append(f'students in {subject_code}.')
            
            messages.success(request, ' '.join(msg_parts))
            
            if error_rows:
                error_detail = '; '.join(error_rows[:3])
                if len(error_rows) > 3:
                    error_detail += f' ... and {len(error_rows) - 3} more'
                messages.warning(request, f'⚠️ {len(error_rows)} errors: {error_detail}')
            
            return redirect('registrars:dashboard')
            
        except Exception as e:
            messages.error(request, f'Error processing file: {str(e)}')
    
    context = {'current_sy': current_sy}
    return render(request, 'registrars/class_list/upload.html', context)
    
@login_required
def section_list(request):
    """View all sections with enrollment counts and teacher assignments."""
    if request.user.profile.role != 'registrar':
        messages.error(request, 'Access denied.')
        return redirect('signin')
    
    school = request.user.profile.school
    current_sy = SchoolYear.objects.filter(school=school, is_current=True).first()
    
    # Get ALL sections (even empty ones)
    sections = Section.objects.filter(
        school=school,
        school_year=current_sy,
    ).select_related('grade_level').order_by('grade_level__sort_order', 'section_name')
    
    # Enrich with data
    section_data = []
    for s in sections:
        # Student count
        enrolled_count = Enrollment.objects.filter(
            section=s,
            school_year=current_sy,
            status__in=['Enrolled', 'Transferred_In']
        ).count()
        
        # Teacher assignments
        assignments = ClassAssignment.objects.filter(
            section=s,
            school_year=current_sy,
            is_active=True
        ).select_related('teacher', 'teacher__profile', 'subject')
        
        # Get unique teachers and subjects
        teachers_list = []
        subjects_list = []
        seen_teachers = set()
        
        for a in assignments:
            if a.teacher_id not in seen_teachers:
                teachers_list.append({
                    'name': a.teacher.get_full_name() or a.teacher.username,
                    'email': a.teacher.email,
                })
                seen_teachers.add(a.teacher_id)
            
            subjects_list.append({
                'code': a.subject.subject_code,
                'name': a.subject.subject_name,
            })
        
        section_data.append({
            'section': s,
            'enrolled_count': enrolled_count,
            'max_capacity': s.max_capacity,
            'teachers': teachers_list,
            'subjects': subjects_list,
            'is_full': enrolled_count >= s.max_capacity if s.max_capacity > 0 else False,
            'is_empty': enrolled_count == 0,
        })
    
    # Summary stats
    total_sections = len(section_data)
    sections_with_students = sum(1 for s in section_data if s['enrolled_count'] > 0)
    sections_empty = total_sections - sections_with_students
    total_enrolled = sum(s['enrolled_count'] for s in section_data)
    
    context = {
        'sections': section_data,
        'current_sy': current_sy,
        'total_sections': total_sections,
        'sections_with_students': sections_with_students,
        'sections_empty': sections_empty,
        'total_enrolled': total_enrolled,
    }
    return render(request, 'registrars/sections/list.html', context)
