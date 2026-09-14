#!/usr/bin/env python
"""
WORKING Seed Data: Complete Q1-Q4 grades for all sections
"""

import os
import random
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from accounts.models import UserProfile
from academics.models import (
    GradeLevel, SchoolYear, Section, Strand, Subject, 
    Quarter, Semester, Room, School
)
from students.models import Student, Guardian
from enrollment.models import Enrollment
from attendance.models import AttendanceRecord, AttendanceSummary
from grades.models import GradeComponent

# ========== GET SCHOOL ==========
school = School.objects.first()
print(f"Using school: {school}")

if not school:
    print("❌ No school found! Please create a school first.")
    exit()

# ========== TEACHER CONFIGURATIONS ==========
TEACHER_CONFIGS = [
    {
        'email': 'teacher.g7.daisy@deped.gov.ph',
        'first_name': 'Maria',
        'last_name': 'Santos',
        'grade_level': 7,
        'section_name': 'Daisy',
        'teaching_area': 'Mathematics',
        'students_count': 35,
        'grade_pattern': 'stable'
    },
    {
        'email': 'teacher.g8.orchid@deped.gov.ph',
        'first_name': 'John',
        'last_name': 'Reyes',
        'grade_level': 8,
        'section_name': 'Orchid',
        'teaching_area': 'English',
        'students_count': 35,
        'grade_pattern': 'improving'
    },
    {
        'email': 'teacher.g9.camia@deped.gov.ph',
        'first_name': 'Jen',
        'last_name': 'Takashie',
        'grade_level': 9,
        'section_name': 'Camia',
        'teaching_area': 'Science',
        'students_count': 35,
        'grade_pattern': 'declining'
    },
    {
        'email': 'teacher.g10.rizal@deped.gov.ph',
        'first_name': 'Jeren',
        'last_name': 'Takashie',
        'grade_level': 10,
        'section_name': 'Rizal',
        'teaching_area': 'Filipino',
        'students_count': 35,
        'grade_pattern': 'erratic'
    },
]

# ========== HELPER FUNCTIONS ==========
def generate_grade_pattern(pattern_type, base_min=75, base_max=95):
    if pattern_type == 'excellent':
        return [round(random.uniform(88, 98), 1) for _ in range(4)]
    elif pattern_type == 'improving':
        start = random.uniform(70, 78)
        return [round(start + i * random.uniform(2, 4), 1) for i in range(4)]
    elif pattern_type == 'declining':
        start = random.uniform(85, 92)
        return [round(start - i * random.uniform(2, 4), 1) for i in range(4)]
    elif pattern_type == 'erratic':
        base = random.uniform(75, 85)
        return [
            round(base + random.uniform(-8, 8), 1),
            round(base + random.uniform(-5, 10), 1),
            round(base + random.uniform(-10, 5), 1),
            round(base + random.uniform(-5, 5), 1)
        ]
    else:
        base = random.uniform(78, 86)
        return [round(base + random.uniform(-3, 3), 1) for _ in range(4)]

def create_student_names(prefix, count):
    first_names = ["James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda"]
    last_names = ["Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis"]
    
    students = []
    for i in range(count):
        first = first_names[i % len(first_names)]
        last = last_names[i % len(last_names)]
        lrn = f"13645679{1000 + i + prefix * 100:04d}"
        sex = "M" if i % 2 == 0 else "F"
        birth_year = random.choice([2007, 2008, 2009, 2010])
        students.append({
            'first_name': first,
            'last_name': last,
            'lrn': lrn,
            'sex': sex,
            'birth_date': date(birth_year, random.randint(1, 12), random.randint(1, 28))
        })
    return students

def create_complete_student(student_info, section, teacher, school_year, subjects, grade_pattern):
    q1 = Quarter.objects.get(school_year=school_year, quarter_number=1)
    q2 = Quarter.objects.get(school_year=school_year, quarter_number=2)
    q3 = Quarter.objects.get(school_year=school_year, quarter_number=3)
    q4 = Quarter.objects.get(school_year=school_year, quarter_number=4)
    quarters = [q1, q2, q3, q4]
    
    student, _ = Student.objects.update_or_create(
        lrn=student_info['lrn'],
        defaults={
            "first_name": student_info['first_name'],
            "last_name": student_info['last_name'],
            "birth_date": student_info['birth_date'],
            "birth_place": "Davao City",
            "sex": student_info['sex'],
            "nationality": "Filipino",
            "is_active": True,
            "is_verified": True,
            "created_by_id": teacher.id,
        }
    )
    
    Guardian.objects.update_or_create(
        student=student,
        is_primary_guardian=True,
        defaults={
            "first_name": f"Parent_{student_info['first_name']}",
            "last_name": student_info['last_name'],
            "relationship": "Mother" if student_info['sex'] == "F" else "Father",
        }
    )
    
    enrollment, _ = Enrollment.objects.update_or_create(
        student=student,
        school_year=school_year,
        defaults={
            "section": section,
            "enrollment_date": date(2025, 7, 20),
            "enrollment_type": "Continuing",
            "status": "Enrolled",
            "created_by_id": teacher.id,
        }
    )
    
    subject_grades = {}
    for subject in subjects:
        grades = generate_grade_pattern(grade_pattern)
        subject_grades[subject.id] = grades
    
    MAX_SCORE = Decimal('100.00')
    
    for quarter_idx, quarter in enumerate(quarters):
        for subject in subjects:
            quarter_grade = subject_grades[subject.id][quarter_idx]
            
            written = quarter_grade * Decimal('0.3')
            performance = quarter_grade * Decimal('0.5')
            quarterly = quarter_grade * Decimal('0.2')
            
            written = written + Decimal(str(random.uniform(-2, 2))).quantize(Decimal('0.01'))
            performance = performance + Decimal(str(random.uniform(-2, 2))).quantize(Decimal('0.01'))
            quarterly = quarterly + Decimal(str(random.uniform(-2, 2))).quantize(Decimal('0.01'))
            
            written = max(Decimal('60.00'), min(Decimal('100.00'), written))
            performance = max(Decimal('60.00'), min(Decimal('100.00'), performance))
            quarterly = max(Decimal('60.00'), min(Decimal('100.00'), quarterly))
            
            weighted = (written * Decimal('0.3') + performance * Decimal('0.5') + quarterly * Decimal('0.2')).quantize(Decimal('0.01'))
            
            GradeComponent.objects.update_or_create(
                enrollment=enrollment,
                subject=subject,
                quarter=quarter,
                defaults={
                    "written_work_raw": written,
                    "written_work_max": MAX_SCORE,
                    "written_work_percent": written,
                    "written_work_weighted": (written * Decimal('0.3')).quantize(Decimal('0.01')),
                    "performance_task_raw": performance,
                    "performance_task_max": MAX_SCORE,
                    "performance_task_percent": performance,
                    "performance_task_weighted": (performance * Decimal('0.5')).quantize(Decimal('0.01')),
                    "quarterly_assessment_raw": quarterly,
                    "quarterly_assessment_max": MAX_SCORE,
                    "quarterly_assessment_percent": quarterly,
                    "quarterly_assessment_weighted": (quarterly * Decimal('0.2')).quantize(Decimal('0.01')),
                    "initial_grade": weighted,
                    "encoded_by_id": teacher.id,
                    "encoding_date": timezone.now(),
                    "validation_status": "Validated",
                    "is_locked": True,
                }
            )
    
    return student

# ========== MAIN SEED FUNCTION ==========
def seed_complete_data():
    print("=" * 70)
    print("COMPLETE GRADE DATA SEEDING")
    print("=" * 70)
    
    school_year = SchoolYear.objects.filter(is_current=True).first()
    if not school_year:
        print("❌ No current school year found!")
        return False
    
    print(f"📅 School Year: {school_year.year_label}")
    
    # Verify quarters exist
    for i in range(1, 5):
        if not Quarter.objects.filter(school_year=school_year, quarter_number=i).exists():
            print(f"❌ Quarter {i} not found!")
            return False
    print("✅ All quarters (Q1-Q4) found")
    
    total_students = 0
    
    for config in TEACHER_CONFIGS:
        print(f"\n{'='*60}")
        print(f"📚 Seeding: Grade {config['grade_level']} - {config['section_name']}")
        print(f"   Teacher: {config['first_name']} {config['last_name']}")
        print(f"   Pattern: {config['grade_pattern']}")
        print(f"   Students: {config['students_count']}")
        print('='*60)
        
        teacher, created = User.objects.update_or_create(
            username=config['email'],
            defaults={
                "email": config['email'],
                "first_name": config['first_name'],
                "last_name": config['last_name'],
                "is_active": True,
            }
        )
        teacher.set_password("teacherpass123")
        teacher.save()
        
        UserProfile.objects.update_or_create(
            user=teacher,
            defaults={
                "role": "teacher",
                "deped_email": config['email'],
                "is_homeroom_adviser": True,
                "position_title": "Teacher III",
                "teaching_area": config['teaching_area'],
                "employment_status": "Regular_Permanent",
            }
        )
        
        grade_level = GradeLevel.objects.get(grade_number=config['grade_level'], school=school)
        
        section, _ = Section.objects.update_or_create(
            school=school,
            school_year=school_year,
            grade_level=grade_level,
            section_name=config['section_name'],
            defaults={
                "adviser_id": teacher.id,
                "max_capacity": 50,
                "is_active": True,
            }
        )
        
        subjects = Subject.objects.filter(grade_level=grade_level, is_active=True)
        print(f"   📖 Subjects: {', '.join([s.subject_name for s in subjects[:5]])}...")
        
        students_data = create_student_names(config['grade_level'] * 100, config['students_count'])
        
        for idx, student_info in enumerate(students_data):
            create_complete_student(
                student_info, section, teacher, school_year, subjects, config['grade_pattern']
            )
            if (idx + 1) % 10 == 0:
                print(f"   👨‍🎓 Created {idx + 1}/{config['students_count']} students")
        
        section.current_enrollment_count = len(students_data)
        section.save()
        total_students += len(students_data)
        print(f"   ✅ Complete! {len(students_data)} students")
    
    print("\n" + "=" * 70)
    print(f"✅ SEEDING COMPLETE! Total students: {total_students}")
    print("=" * 70)
    return True

if __name__ == "__main__":
    seed_complete_data()
