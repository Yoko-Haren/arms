#!/usr/bin/env python
"""
ENHANCED Seed Data: Complete Q1-Q4 grades for all sections
- Generates Q1, Q2, Q3, Q4 grades for all subjects
- Creates more realistic grade patterns (improving/declining/stable)
- Adds more teachers and sections for comprehensive training data
"""

import os
import random
from datetime import date, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP

# ===== DJANGO SETUP - MUST BE FIRST =====
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()
# ========================================

from django.contrib.auth.models import User
from django.utils import timezone
from accounts.models import UserProfile
from academics.models import (
    GradeLevel, SchoolYear, Section, Strand, Subject, 
    Quarter, Semester, Room
)
from students.models import Student, Guardian
from enrollment.models import Enrollment
from attendance.models import AttendanceRecord, AttendanceSummary
from grades.models import GradeComponent
from scheduling.models import ClassAssignment, ClassSchedule


# =============================================================================
# TEACHER AND SECTION CONFIGURATION
# =============================================================================

TEACHER_CONFIGS = [
    {
        'email': 'teacher.g7.daisy@deped.gov.ph',
        'first_name': 'Maria',
        'last_name': 'Santos',
        'grade_level': 7,
        'section_name': 'Daisy',
        'teaching_area': 'Mathematics',
        'students_count': 35,
        'grade_pattern': 'stable'  # Consistent grades
    },
    {
        'email': 'teacher.g8.orchid@deped.gov.ph',
        'first_name': 'John',
        'last_name': 'Reyes',
        'grade_level': 8,
        'section_name': 'Orchid',
        'teaching_area': 'English',
        'students_count': 35,
        'grade_pattern': 'improving'  # Grades go up over time
    },
    {
        'email': 'teacher.g9.camia@deped.gov.ph',
        'first_name': 'Jen',
        'last_name': 'Takashie',
        'grade_level': 9,
        'section_name': 'Camia',
        'teaching_area': 'Science',
        'students_count': 35,
        'grade_pattern': 'declining'  # Grades go down over time
    },
    {
        'email': 'teacher.g10.rizal@deped.gov.ph',
        'first_name': 'Jeren',
        'last_name': 'Takashie',
        'grade_level': 10,
        'section_name': 'Rizal',
        'teaching_area': 'Filipino',
        'students_count': 35,
        'grade_pattern': 'erratic'  # Up and down
    },
    {
        'email': 'teacher.g11.stem.a@deped.gov.ph',
        'first_name': 'Robert',
        'last_name': 'Mendoza',
        'grade_level': 11,
        'section_name': 'STEM A',
        'strand_code': 'STEM',
        'teaching_area': 'Mathematics',
        'students_count': 30,
        'grade_pattern': 'excellent'  # Very high grades
    },
    {
        'email': 'teacher.g12.abm.c@deped.gov.ph',
        'first_name': 'User',
        'last_name': 'One',
        'grade_level': 12,
        'section_name': 'ABM C',
        'strand_code': 'ABM',
        'teaching_area': 'Accountancy',
        'students_count': 28,
        'grade_pattern': 'average'  # Mixed performance
    },
]

# =============================================================================
# HELPER: Generate realistic grade patterns
# =============================================================================

def generate_grade_pattern(pattern_type, base_min=75, base_max=95):
    """Generate Q1, Q2, Q3, Q4 grades with realistic patterns"""
    
    if pattern_type == 'stable':
        # Consistent grades across quarters
        base = random.uniform(base_min, base_max)
        return [
            Decimal(str(round(base + random.uniform(-3, 3), 1))),
            Decimal(str(round(base + random.uniform(-2, 2), 1))),
            Decimal(str(round(base + random.uniform(-2, 2), 1))),
            Decimal(str(round(base + random.uniform(-1, 1), 1))),
        ]
    
    elif pattern_type == 'improving':
        # Grades increase each quarter
        q1 = random.uniform(base_min, base_min + 5)
        q2 = q1 + random.uniform(2, 6)
        q3 = q2 + random.uniform(2, 5)
        q4 = q3 + random.uniform(1, 4)
        return [Decimal(str(round(g, 1))) for g in [q1, q2, q3, q4]]
    
    elif pattern_type == 'declining':
        # Grades decrease each quarter
        q1 = random.uniform(base_max - 5, base_max)
        q2 = q1 - random.uniform(2, 6)
        q3 = q2 - random.uniform(2, 5)
        q4 = q3 - random.uniform(1, 4)
        return [Decimal(str(round(g, 1))) for g in [q1, q2, q3, q4]]
    
    elif pattern_type == 'erratic':
        # Up and down pattern
        q1 = random.uniform(base_min, base_max)
        q2 = q1 + random.uniform(-10, 10)
        q3 = q2 + random.uniform(-10, 10)
        q4 = q3 + random.uniform(-8, 8)
        # Clamp to 60-100
        return [Decimal(str(round(max(60, min(100, g)), 1))) for g in [q1, q2, q3, q4]]
    
    elif pattern_type == 'excellent':
        # High grades (85-98)
        base = random.uniform(85, 95)
        return [
            Decimal(str(round(base + random.uniform(-2, 2), 1))),
            Decimal(str(round(base + random.uniform(-1, 3), 1))),
            Decimal(str(round(base + random.uniform(0, 4), 1))),
            Decimal(str(round(base + random.uniform(1, 5), 1))),
        ]
    
    else:  # 'average'
        # Mixed performance (65-88)
        return [
            Decimal(str(round(random.uniform(65, 88), 1))),
            Decimal(str(round(random.uniform(65, 88), 1))),
            Decimal(str(round(random.uniform(65, 88), 1))),
            Decimal(str(round(random.uniform(65, 88), 1))),
        ]


def create_student_names(prefix, count):
    """Generate unique student names for a section"""
    first_names = [
        "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda",
        "William", "Elizabeth", "David", "Susan", "Joseph", "Jessica", "Thomas", "Sarah",
        "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa", "Matthew", "Betty",
        "Anthony", "Margaret", "Donald", "Sandra", "Mark", "Ashley", "Paul", "Kimberly",
        "Steven", "Emily", "Andrew", "Donna", "Kenneth", "Michelle", "Joshua", "Carol",
        "Kevin", "Amanda", "Brian", "Melissa", "George", "Deborah", "Edward", "Stephanie"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis",
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson",
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson",
        "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker",
        "Young", "Allen", "King", "Wright", "Scott", "Torres", "Nguyen", "Hill", "Flores"
    ]
    
    students = []
    for i in range(count):
        first = first_names[i % len(first_names)]
        last = last_names[i % len(last_names)]
        lrn = f"13645679{1000 + i + prefix * 100:04d}"
        sex = "M" if i % 2 == 0 else "F"
        birth_year = random.choice([2007, 2008, 2009, 2010])
        birth_month = random.randint(1, 12)
        birth_day = random.randint(1, 28)
        
        students.append({
            'first_name': first,
            'last_name': last,
            'lrn': lrn,
            'sex': sex,
            'birth_date': date(birth_year, birth_month, birth_day)
        })
    
    return students


# =============================================================================
# HELPER: Create complete student record with all quarters
# =============================================================================

def create_complete_student(student_info, section, teacher, school_year, subjects, grade_pattern):
    """Create student with complete Q1-Q4 grades for all subjects"""
    
    # Get quarters
    q1 = Quarter.objects.get(school_year=school_year, quarter_number=1)
    q2 = Quarter.objects.get(school_year=school_year, quarter_number=2)
    q3 = Quarter.objects.get(school_year=school_year, quarter_number=3)
    q4 = Quarter.objects.get(school_year=school_year, quarter_number=4)
    quarters = [q1, q2, q3, q4]
    
    # Create Student
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
    
    # Create Guardian
    Guardian.objects.update_or_create(
        student=student,
        is_primary_guardian=True,
        defaults={
            "first_name": f"Parent_{student_info['first_name']}",
            "last_name": student_info['last_name'],
            "relationship": "Mother" if student_info['sex'] == "F" else "Father",
        }
    )
    
    # Create Enrollment
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
    
    # Generate grade pattern for this student
    # Each subject can have slightly different variation
    subject_grades = {}
    
    for subject in subjects:
        # Generate base grades for this subject
        grades = generate_grade_pattern(grade_pattern, base_min=70, base_max=95)
        subject_grades[subject.id] = grades
    
    # Create GradeComponent for each quarter and subject
    MAX_SCORE = Decimal('100.00')
    
    for quarter_idx, quarter in enumerate(quarters):
        for subject in subjects:
            quarter_grade = subject_grades[subject.id][quarter_idx]
            
            # Calculate components based on quarter grade
            written = quarter_grade * Decimal('0.25')
            performance = quarter_grade * Decimal('0.50')
            quarterly = quarter_grade * Decimal('0.25')
            
            # Adjust slightly for realism
            written = written + Decimal(str(random.uniform(-2, 2))).quantize(Decimal('0.01'))
            performance = performance + Decimal(str(random.uniform(-2, 2))).quantize(Decimal('0.01'))
            quarterly = quarterly + Decimal(str(random.uniform(-2, 2))).quantize(Decimal('0.01'))
            
            # Ensure no negative values
            written = max(Decimal('60.00'), min(Decimal('100.00'), written))
            performance = max(Decimal('60.00'), min(Decimal('100.00'), performance))
            quarterly = max(Decimal('60.00'), min(Decimal('100.00'), quarterly))
            
            # Recalculate weighted grade
            weighted = (
                written * Decimal('0.25') + 
                performance * Decimal('0.50') + 
                quarterly * Decimal('0.25')
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            # Validation status: Q1-Q3 = Submitted/Validated, Q4 = Draft (for encoding)
            if quarter.quarter_number == 4:
                validation_status = "Draft"
                is_locked = False
            else:
                validation_status = random.choice(["Submitted", "Validated"])
                is_locked = validation_status == "Validated"
            
            GradeComponent.objects.update_or_create(
                enrollment=enrollment,
                subject=subject,
                quarter=quarter,
                defaults={
                    "written_work_raw": written,
                    "written_work_max": MAX_SCORE,
                    "written_work_percent": written,
                    "written_work_weighted": (written * Decimal('0.25')).quantize(Decimal('0.01')),
                    "performance_task_raw": performance,
                    "performance_task_max": MAX_SCORE,
                    "performance_task_percent": performance,
                    "performance_task_weighted": (performance * Decimal('0.50')).quantize(Decimal('0.01')),
                    "quarterly_assessment_raw": quarterly,
                    "quarterly_assessment_max": MAX_SCORE,
                    "quarterly_assessment_percent": quarterly,
                    "quarterly_assessment_weighted": (quarterly * Decimal('0.25')).quantize(Decimal('0.01')),
                    "initial_grade": weighted,
                    "encoded_by_id": teacher.id,
                    "encoding_date": timezone.now(),
                    "validation_status": validation_status,
                    "is_locked": is_locked,
                }
            )
    
    return student, enrollment


# =============================================================================
# MAIN SEED FUNCTION
# =============================================================================

def seed_complete_data():
    """Seed complete Q1-Q4 data for all configured teachers and sections"""
    
    print("=" * 70)
    print("COMPLETE GRADE DATA SEEDING (Q1, Q2, Q3, Q4)")
    print("=" * 70)
    
    school_year = SchoolYear.objects.filter(is_current=True).first()
    if not school_year:
        print("❌ No current school year found!")
        return False
    
    print(f"📅 School Year: {school_year.year_label}")
    
    # Verify quarters exist
    for i in range(1, 5):
        quarter = Quarter.objects.filter(school_year=school_year, quarter_number=i).first()
        if not quarter:
            print(f"❌ Quarter {i} not found! Please create quarters first.")
            return False
    print("✅ All quarters (Q1-Q4) found")
    
    all_sections = []
    total_students = 0
    
    for config in TEACHER_CONFIGS:
        print(f"\n{'='*60}")
        print(f"📚 Seeding: Grade {config['grade_level']} - {config['section_name']}")
        print(f"   Teacher: {config['first_name']} {config['last_name']}")
        print(f"   Pattern: {config['grade_pattern']}")
        print(f"   Students: {config['students_count']}")
        print('='*60)
        
        # Create or get user
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
        
        # Create profile
        UserProfile.objects.update_or_create(
            user=teacher,
            defaults={
                "role": "teacher",
                "deped_email": config['email'],
                "is_homeroom_adviser": True,
                "position_title": "Teacher III",
                "teaching_area": config['teaching_area'],
                "employment_status": "Regular_Permanent",
                "date_hired": date(2020, 6, 1),
            }
        )
        
        # Get grade level
        grade_level = GradeLevel.objects.get(grade_number=config['grade_level'])
        
        # Get strand if specified
        strand = None
        if config.get('strand_code'):
            strand = Strand.objects.filter(strand_code=config['strand_code']).first()
        
        # Create section
        section, _ = Section.objects.update_or_create(
            school_year=school_year,
            grade_level=grade_level,
            strand=strand,
            section_name=config['section_name'],
            defaults={
                "adviser_id": teacher.id,
                "max_capacity": 50,
                "is_active": True,
            }
        )
        
        # Get subjects for this grade level
        subjects = Subject.objects.filter(grade_level=grade_level, is_active=True)
        if strand:
            strand_subjects = Subject.objects.filter(grade_level=grade_level, strand=strand, is_active=True)
            subjects = subjects | strand_subjects
        subjects = subjects.distinct()
        
        print(f"   📖 Subjects: {', '.join([s.subject_name for s in subjects[:5]])}...")
        
        # Generate students
        students_data = create_student_names(config['grade_level'] * 100, config['students_count'])
        
        section_students = []
        for idx, student_info in enumerate(students_data):
            student, enrollment = create_complete_student(
                student_info, section, teacher, school_year, subjects, config['grade_pattern']
            )
            section_students.append(student)
            
            if (idx + 1) % 10 == 0:
                print(f"   👨‍🎓 Created {idx + 1}/{config['students_count']} students")
        
        # Update section enrollment count
        section.current_enrollment_count = len(section_students)
        section.save()
        
        all_sections.append({
            'section': section,
            'teacher': teacher,
            'students': len(section_students),
            'grade_level': config['grade_level']
        })
        total_students += len(section_students)
        
        print(f"   ✅ Complete! {len(section_students)} students with Q1-Q4 grades")
    
    # Summary
    print("\n" + "=" * 70)
    print("✅ SEEDING COMPLETE!")
    print("=" * 70)
    print(f"\n📊 Summary:")
    print(f"   Sections created: {len(all_sections)}")
    print(f"   Total students: {total_students}")
    print(f"   Total grades per student: 4 quarters × ~8 subjects = ~32 grades each")
    print(f"   Total GradeComponent records: ~{total_students * 32}")
    
    print("\n📋 Section Details:")
    for sec in all_sections:
        print(f"   Grade {sec['grade_level']} - {sec['section'].section_name}: {sec['students']} students")
    
    print("\n🔐 Teacher Login Credentials:")
    for config in TEACHER_CONFIGS:
        print(f"   {config['email']} / teacherpass123")
    
    return True


if __name__ == "__main__":
    seed_complete_data()