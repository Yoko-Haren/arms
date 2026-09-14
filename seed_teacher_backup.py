#!/usr/bin/env python
"""
Seed Data: 4 Teachers with unique students per section
- User.one@deped.gov.ph - Grade 12 ABM C (28 students)
- jen.takashie@deped.gov.ph - Grade 9 Camia (30 students)
- jeren.takashie@deped.gov.ph - Grade 10 Rizal (30 students)
- juan.delacruz.teach@deped.gov.ph - Grade 8 Orchid (30 students)
"""

import os
import random
from datetime import date, datetime, timedelta

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
# UNIQUE STUDENT NAMES (no duplicates across all sections)
# =============================================================================

# Grade 12 ABM C - 28 students (User One)
students_abm_c = [
    ("Adrian", "Mabini", "136456790021", "M", date(2007, 3, 15)),
    ("Beatrice", "Aguinaldo", "136456790022", "F", date(2007, 5, 20)),
    ("Cedric", "Bonifacio", "136456790023", "M", date(2007, 7, 10)),
    ("Dianne", "Rizal", "136456790024", "F", date(2007, 1, 25)),
    ("Eduardo", "Silang", "136456790025", "M", date(2007, 9, 12)),
    ("Felicity", "Luna", "136456790026", "F", date(2007, 11, 3)),
    ("Gregorio", "Del Pilar", "136456790027", "M", date(2007, 2, 18)),
    ("Helena", "Jacinto", "136456790028", "F", date(2007, 8, 22)),
    ("Ignacio", "Burgos", "136456790029", "M", date(2007, 4, 5)),
    ("Jasmine", "Zamora", "136456790030", "F", date(2007, 10, 30)),
    ("Kristoffer", "Gomez", "136456790031", "M", date(2007, 6, 14)),
    ("Lorena", "Lopez", "136456790032", "F", date(2007, 12, 1)),
    ("Mateo", "Rivera", "136456790033", "M", date(2007, 1, 9)),
    ("Natasha", "Torres", "136456790034", "F", date(2007, 3, 27)),
    ("Oscar", "Aquino", "136456790035", "M", date(2007, 9, 8)),
    ("Patricia", "Estrada", "136456790036", "F", date(2007, 5, 19)),
    ("Quentin", "Navarro", "136456790037", "M", date(2007, 11, 11)),
    ("Rosario", "Castro", "136456790038", "F", date(2007, 2, 28)),
    ("Stefano", "Morales", "136456790039", "M", date(2007, 7, 7)),
    ("Teresa", "Ortega", "136456790040", "F", date(2007, 10, 17)),
    ("Ulysses", "Domingo", "136456790041", "M", date(2007, 4, 22)),
    ("Victoria", "Pascual", "136456790042", "F", date(2007, 12, 14)),
    ("William", "Santiago", "136456790043", "M", date(2007, 1, 30)),
    ("Xenia", "Manalo", "136456790044", "F", date(2007, 8, 9)),
    ("Yves", "Galang", "136456790045", "M", date(2007, 6, 25)),
    ("Zenaida", "Herrera", "136456790046", "F", date(2007, 3, 3)),
    ("Aaron", "Ignacio", "136456790047", "M", date(2007, 9, 19)),
    ("Bella", "Javier", "136456790048", "F", date(2007, 11, 26)),
]

# Grade 9 Camia - 30 students (Jen Takashie - English)
students_g9_camia = [
    ("Althea", "Cordero", "136456790049", "F", date(2009, 1, 12)),
    ("Benedict", "Macaraeg", "136456790050", "M", date(2009, 2, 20)),
    ("Catherine", "Ocampo", "136456790051", "F", date(2009, 3, 8)),
    ("Dominic", "Quinto", "136456790052", "M", date(2009, 4, 15)),
    ("Eliza", "Robles", "136456790053", "F", date(2009, 5, 22)),
    ("Fernando", "Salvador", "136456790054", "M", date(2009, 6, 3)),
    ("Gemma", "Tolentino", "136456790055", "F", date(2009, 7, 18)),
    ("Harold", "Ubaldo", "136456790056", "M", date(2009, 8, 25)),
    ("Irene", "Vergara", "136456790057", "F", date(2009, 9, 7)),
    ("Jerome", "Zarate", "136456790058", "M", date(2009, 10, 14)),
    ("Katrina", "Abella", "136456790059", "F", date(2009, 11, 21)),
    ("Lawrence", "Batungbakal", "136456790060", "M", date(2009, 12, 2)),
    ("Marian", "Cariño", "136456790061", "F", date(2009, 1, 30)),
    ("Nicholas", "Dalisay", "136456790062", "M", date(2009, 2, 16)),
    ("Olivia", "Esguerra", "136456790063", "F", date(2009, 3, 25)),
    ("Patrick", "Francisco", "136456790064", "M", date(2009, 4, 11)),
    ("Queenie", "Geronimo", "136456790065", "F", date(2009, 5, 28)),
    ("Raymond", "Hipolito", "136456790066", "M", date(2009, 6, 9)),
    ("Sabrina", "Inocencio", "136456790067", "F", date(2009, 7, 17)),
    ("Timothy", "Jocson", "136456790068", "M", date(2009, 8, 23)),
    ("Ursula", "Katigbak", "136456790069", "F", date(2009, 9, 5)),
    ("Victor", "Lacson", "136456790070", "M", date(2009, 10, 19)),
    ("Wendy", "Magpantay", "136456790071", "F", date(2009, 11, 13)),
    ("Xander", "Natividad", "136456790072", "M", date(2009, 12, 27)),
    ("Yasmin", "Oliva", "136456790073", "F", date(2009, 1, 8)),
    ("Zachary", "Padilla", "136456790074", "M", date(2009, 2, 22)),
    ("Amanda", "Quintos", "136456790075", "F", date(2009, 3, 14)),
    ("Brian", "Roxas", "136456790076", "M", date(2009, 4, 30)),
    ("Clarissa", "Sarmiento", "136456790077", "F", date(2009, 5, 19)),
    ("Dennis", "Tuazon", "136456790078", "M", date(2009, 6, 26)),
]

# Grade 10 Rizal - 30 students (Jeren Takashie - Science)
students_g10_rizal = [
    ("Aaron", "Valdez", "136456790079", "M", date(2008, 1, 15)),
    ("Bianca", "Yulo", "136456790080", "F", date(2008, 2, 20)),
    ("Christopher", "Abad", "136456790081", "M", date(2008, 3, 10)),
    ("Daniela", "Bautista", "136456790082", "F", date(2008, 4, 25)),
    ("Enrique", "Cruz", "136456790083", "M", date(2008, 5, 5)),
    ("Fatima", "De Leon", "136456790084", "F", date(2008, 6, 18)),
    ("Gabriel", "Evangelista", "136456790085", "M", date(2008, 7, 22)),
    ("Hannah", "Faustino", "136456790086", "F", date(2008, 8, 3)),
    ("Ivan", "Gonzales", "136456790087", "M", date(2008, 9, 17)),
    ("Julia", "Hernandez", "136456790088", "F", date(2008, 10, 28)),
    ("Kevin", "Imperial", "136456790089", "M", date(2008, 11, 9)),
    ("Louise", "Jimenez", "136456790090", "F", date(2008, 12, 14)),
    ("Marco", "Kalaw", "136456790091", "M", date(2008, 1, 31)),
    ("Nina", "Legaspi", "136456790092", "F", date(2008, 2, 16)),
    ("Oliver", "Magsaysay", "136456790093", "M", date(2008, 3, 24)),
    ("Paula", "Nolasco", "136456790094", "F", date(2008, 4, 8)),
    ("Ramon", "Ongpauco", "136456790095", "M", date(2008, 5, 21)),
    ("Sandra", "Perez", "136456790096", "F", date(2008, 6, 12)),
    ("Tomas", "Quiambao", "136456790097", "M", date(2008, 7, 30)),
    ("Vanessa", "Reyes", "136456790098", "F", date(2008, 8, 15)),
    ("Walter", "Santos", "136456790099", "M", date(2008, 9, 27)),
    ("Angel", "Tan", "136456790100", "F", date(2008, 10, 11)),
    ("Benjie", "Ungson", "136456790101", "M", date(2008, 11, 23)),
    ("Cecilia", "Velasco", "136456790102", "F", date(2008, 12, 5)),
    ("Daryl", "Wagan", "136456790103", "M", date(2008, 1, 19)),
    ("Elaine", "Xavier", "136456790104", "F", date(2008, 2, 28)),
    ("Francis", "Ysip", "136456790105", "M", date(2008, 3, 7)),
    ("Grace", "Zamora", "136456790106", "F", date(2008, 4, 14)),
    ("Henry", "Angeles", "136456790107", "M", date(2008, 5, 26)),
    ("Iris", "Barretto", "136456790108", "F", date(2008, 6, 30)),
]

# Grade 8 Orchid - 30 students (Juan Dela Cruz - Filipino/AP)
students_g8_orchid = [
    ("Alfred", "Quirino", "136456790109", "M", date(2010, 1, 8)),
    ("Bernadette", "Roces", "136456790110", "F", date(2010, 2, 19)),
    ("Carlo", "Soriano", "136456790111", "M", date(2010, 3, 14)),
    ("Denise", "Tagle", "136456790112", "F", date(2010, 4, 22)),
    ("Erwin", "Umali", "136456790113", "M", date(2010, 5, 3)),
    ("Florence", "Villegas", "136456790114", "F", date(2010, 6, 17)),
    ("Gilbert", "Yaptangco", "136456790115", "M", date(2010, 7, 25)),
    ("Heidi", "Aguirre", "136456790116", "F", date(2010, 8, 9)),
    ("Iñigo", "Belmonte", "136456790117", "M", date(2010, 9, 13)),
    ("Janice", "Corpuz", "136456790118", "F", date(2010, 10, 27)),
    ("Kenneth", "Datu", "136456790119", "M", date(2010, 11, 5)),
    ("Lara", "Enriquez", "136456790120", "F", date(2010, 12, 18)),
    ("Martin", "Flores", "136456790121", "M", date(2010, 1, 24)),
    ("Nancy", "Gatmaitan", "136456790122", "F", date(2010, 2, 11)),
    ("Omar", "Hidalgo", "136456790123", "M", date(2010, 3, 29)),
    ("Priscilla", "Ilagan", "136456790124", "F", date(2010, 4, 7)),
    ("Raul", "Jalandoni", "136456790125", "M", date(2010, 5, 16)),
    ("Shirley", "Kanapi", "136456790126", "F", date(2010, 6, 22)),
    ("Teddy", "Lansang", "136456790127", "M", date(2010, 7, 4)),
    ("Vanessa", "Mendoza", "136456790128", "F", date(2010, 8, 19)),
    ("Warren", "Nepomuceno", "136456790129", "M", date(2010, 9, 28)),
    ("Yolanda", "Osmeña", "136456790130", "F", date(2010, 10, 10)),
    ("Zandro", "Pangilinan", "136456790131", "M", date(2010, 11, 21)),
    ("Alice", "Quezon", "136456790132", "F", date(2010, 12, 3)),
    ("Bernard", "Ramos", "136456790133", "M", date(2010, 1, 15)),
    ("Carolina", "Sison", "136456790134", "F", date(2010, 2, 26)),
    ("Dexter", "Trinidad", "136456790135", "M", date(2010, 3, 12)),
    ("Evelyn", "Urbano", "136456790136", "F", date(2010, 4, 20)),
    ("Felix", "Villanueva", "136456790137", "M", date(2010, 5, 8)),
    ("Gloria", "Ysmael", "136456790138", "F", date(2010, 6, 24)),
]


# =============================================================================
# HELPER: Create students for a section
# =============================================================================
def create_students_for_section(students_data, section, teacher_user, school_year, all_subjects):
    """Create students with attendance and grades for a given section."""
    students = []
    
    quarter_3 = Quarter.objects.get(school_year=school_year, quarter_number=3)
    quarter_4 = Quarter.objects.get(school_year=school_year, quarter_number=4)
    
    room = Room.objects.filter(room_code__icontains="BLDG1").first()
    
    from decimal import Decimal, ROUND_HALF_UP
    
    for idx, (first_name, last_name, lrn, sex, birth_date) in enumerate(students_data):
        # Create Student
        student, _ = Student.objects.update_or_create(
            lrn=lrn,
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "birth_date": birth_date,
                "birth_place": "Davao City",
                "sex": sex,
                "nationality": "Filipino",
                "is_active": True,
                "is_verified": True,
                "created_by_id": teacher_user.id,
            }
        )
        students.append(student)
        print(f"  👨‍🎓 {first_name} {last_name}")
        
        # Create Guardian
        Guardian.objects.update_or_create(
            student=student,
            is_primary_guardian=True,
            defaults={
                "first_name": f"Parent_{first_name}",
                "last_name": last_name,
                "relationship": "Mother" if sex == "F" else "Father",
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
                "created_by_id": teacher_user.id,
            }
        )
        
        # Create Q3 Attendance (Jan 19 - Apr 15, 2026)
        q3_start = date(2026, 1, 19)
        q3_end = date(2026, 4, 15)
        
        current_date = q3_start
        while current_date <= q3_end:
            if current_date.weekday() < 5:
                status = random.choices(
                    ["Present", "Present", "Present", "Late", "Absent"],
                    weights=[50, 30, 10, 5, 5]
                )[0]
                
                AttendanceRecord.objects.get_or_create(
                    enrollment=enrollment,
                    date=current_date,
                    defaults={
                        "status": status,
                        "marked_by_id": teacher_user.id,
                    }
                )
                
            current_date += timedelta(days=1)
        
        # Create Q4 Attendance (Apr 17 - May 15, 2026)
        q4_start = date(2026, 4, 17)
        q4_end = date(2026, 5, 15)
        
        current_date = q4_start
        while current_date <= q4_end:
            if current_date.weekday() < 5:
                status = random.choices(
                    ["Present", "Present", "Present", "Late"],
                    weights=[60, 25, 10, 5]
                )[0]
                
                AttendanceRecord.objects.get_or_create(
                    enrollment=enrollment,
                    date=current_date,
                    defaults={
                        "status": status,
                        "marked_by_id": teacher_user.id,
                    }
                )
                
            current_date += timedelta(days=1)
        
        # Helper function to create precise decimal grades
        def make_grade(min_val, max_val):
            """Generate a random grade with exactly 2 decimal places."""
            value = Decimal(str(random.uniform(min_val, max_val))).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            return value
        
        # Max values for all grade components
        MAX_SCORE = Decimal('100.00')
        
        # Create Grades for Q3
        for subject in all_subjects[:6]:
            written = make_grade(75, 95)
            performance = make_grade(78, 96)
            quarterly = make_grade(72, 92)
            
            # Calculate weighted grade with precise decimals
            weighted = (
                written * Decimal('0.25') + 
                performance * Decimal('0.50') + 
                quarterly * Decimal('0.25')
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            validation_status = random.choice(["Submitted", "Validated"])
            
            GradeComponent.objects.get_or_create(
                enrollment=enrollment,
                subject=subject,
                quarter=quarter_3,
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
                    "encoded_by_id": teacher_user.id,
                    "encoding_date": timezone.now(),
                    "validation_status": validation_status,
                    "is_locked": validation_status == "Validated",
                }
            )
        
        # Create Grades for Q4
        for subject in all_subjects[:6]:
            written = make_grade(76, 96)
            performance = make_grade(79, 97)
            quarterly = make_grade(73, 93)
            
            weighted = (
                written * Decimal('0.25') + 
                performance * Decimal('0.50') + 
                quarterly * Decimal('0.25')
            ).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)
            
            GradeComponent.objects.get_or_create(
                enrollment=enrollment,
                subject=subject,
                quarter=quarter_4,
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
                    "encoded_by_id": teacher_user.id,
                    "encoding_date": timezone.now(),
                    "validation_status": "Draft",
                    "is_locked": False,
                }
            )
    
    return students

# =============================================================================
# MAIN SEED FUNCTION
# =============================================================================
def seed_all_teachers():
    """Seed all 4 teachers with their respective sections and students."""
    
    print("=" * 60)
    print("FORMIFY LIS — TEACHER SEED DATA SCRIPT")
    print("=" * 60)
    
    school_year = SchoolYear.objects.get(is_current=True)
    print(f"📅 School Year: {school_year.year_label}")
    
    # =========================================================================
    # TEACHER 1: User One - Grade 12 ABM C
    # =========================================================================
    print("\n[1/4] User One — Grade 12 ABM C...")
    
    teacher1, _ = User.objects.update_or_create(
        username="User.one@deped.gov.ph",
        defaults={
            "email": "User.one@deped.gov.ph",
            "first_name": "User",
            "last_name": "One",
            "is_active": True,
        }
    )
    teacher1.set_password("password123")
    teacher1.save()
    
    UserProfile.objects.update_or_create(
        user=teacher1,
        defaults={
            "role": "teacher",
            "is_homeroom_adviser": True,
            "position_title": "Teacher III",
            "teaching_area": "Accountancy, Business and Management",
            "employment_status": "Regular_Permanent",
        }
    )
    
    grade_12 = GradeLevel.objects.get(grade_number=12)
    abm_strand = Strand.objects.get(strand_code="ABM")
    
    section1, _ = Section.objects.update_or_create(
        school_year=school_year,
        grade_level=grade_12,
        strand=abm_strand,
        section_name="ABM C",
        defaults={
            "adviser_id": teacher1.id,
            "max_capacity": 45,
            "is_active": True,
        }
    )
    
    abm_subjects = Subject.objects.filter(grade_level=grade_12, strand=abm_strand, is_active=True)
    core_subjects = Subject.objects.filter(grade_level=grade_12, strand_id=None, is_active=True)[:4]
    subjects1 = list(core_subjects) + list(abm_subjects)
    
    students1 = create_students_for_section(students_abm_c, section1, teacher1, school_year, subjects1)
    section1.current_enrollment_count = len(students1)
    section1.save()
    print(f"  ✅ {len(students1)} students in ABM C")
    
    # =========================================================================
    # TEACHER 2: Jen Takashie - Grade 9 Camia
    # =========================================================================
    print("\n[2/4] Jen Takashie — Grade 9 Camia...")
    
    teacher2, _ = User.objects.update_or_create(
        username="jen.takashie@deped.gov.ph",
        defaults={
            "email": "jen.takashie@deped.gov.ph",
            "first_name": "Jen",
            "last_name": "Takashie",
            "is_active": True,
        }
    )
    teacher2.set_password("teacherpass123")
    teacher2.save()
    
    UserProfile.objects.update_or_create(
        user=teacher2,
        defaults={
            "role": "teacher",
            "deped_email": "jen.takashie@deped.gov.ph",
            "is_homeroom_adviser": True,
            "position_title": "Teacher II",
            "designation": "English Teacher - Grade 9 Camia Adviser",
            "teaching_area": "English",
            "employment_status": "Regular_Permanent",
            "date_hired": date(2022, 6, 13),
            "employee_number": "DEPED-ENG-2022-0042",
        }
    )
    
    grade_9 = GradeLevel.objects.get(grade_number=9)
    
    section2, _ = Section.objects.update_or_create(
        school_year=school_year,
        grade_level=grade_9,
        section_name="Camia",
        defaults={
            "adviser_id": teacher2.id,
            "max_capacity": 50,
            "is_active": True,
        }
    )
    
    subjects2 = Subject.objects.filter(grade_level=grade_9, is_active=True)
    
    students2 = create_students_for_section(students_g9_camia, section2, teacher2, school_year, subjects2)
    section2.current_enrollment_count = len(students2)
    section2.save()
    print(f"  ✅ {len(students2)} students in Camia")
    
    # =========================================================================
    # TEACHER 3: Jeren Takashie - Grade 10 Rizal
    # =========================================================================
    print("\n[3/4] Jeren Takashie — Grade 10 Rizal...")
    
    teacher3, _ = User.objects.update_or_create(
        username="jeren.takashie@deped.gov.ph",
        defaults={
            "email": "jeren.takashie@deped.gov.ph",
            "first_name": "Jeren",
            "last_name": "Takashie",
            "is_active": True,
        }
    )
    teacher3.set_password("teacherpass123")
    teacher3.save()
    
    UserProfile.objects.update_or_create(
        user=teacher3,
        defaults={
            "role": "teacher",
            "deped_email": "jeren.takashie@deped.gov.ph",
            "is_homeroom_adviser": True,
            "position_title": "Teacher III",
            "designation": "Science Teacher - Grade 10 Rizal Adviser",
            "teaching_area": "Science",
            "employment_status": "Regular_Permanent",
            "date_hired": date(2021, 5, 24),
            "employee_number": "DEPED-SCI-2021-0031",
        }
    )
    
    grade_10 = GradeLevel.objects.get(grade_number=10)
    
    section3, _ = Section.objects.update_or_create(
        school_year=school_year,
        grade_level=grade_10,
        section_name="Rizal",
        defaults={
            "adviser_id": teacher3.id,
            "max_capacity": 50,
            "is_active": True,
        }
    )
    
    subjects3 = Subject.objects.filter(grade_level=grade_10, is_active=True)
    
    students3 = create_students_for_section(students_g10_rizal, section3, teacher3, school_year, subjects3)
    section3.current_enrollment_count = len(students3)
    section3.save()
    print(f"  ✅ {len(students3)} students in Rizal")
    
    # =========================================================================
    # TEACHER 4: Juan Dela Cruz - Grade 8 Orchid
    # =========================================================================
    print("\n[4/4] Juan Dela Cruz — Grade 8 Orchid...")
    
    teacher4, _ = User.objects.update_or_create(
        username="juan.delacruz.teach@deped.gov.ph",
        defaults={
            "email": "juan.delacruz.teach@deped.gov.ph",
            "first_name": "Juan",
            "last_name": "Dela Cruz",
            "is_active": True,
        }
    )
    teacher4.set_password("teacherpass123")
    teacher4.save()
    
    UserProfile.objects.update_or_create(
        user=teacher4,
        defaults={
            "role": "teacher",
            "deped_email": "juan.delacruz.teach@deped.gov.ph",
            "is_homeroom_adviser": True,
            "position_title": "Teacher I",
            "designation": "Filipino & AP Teacher - Grade 8 Orchid Adviser",
            "teaching_area": "Filipino",
            "employment_status": "Probationary",
            "date_hired": date(2025, 1, 6),
            "employee_number": "DEPED-FIL-2025-0008",
        }
    )
    
    grade_8 = GradeLevel.objects.get(grade_number=8)
    
    section4, _ = Section.objects.update_or_create(
        school_year=school_year,
        grade_level=grade_8,
        section_name="Orchid",
        defaults={
            "adviser_id": teacher4.id,
            "max_capacity": 50,
            "is_active": True,
        }
    )
    
    subjects4 = Subject.objects.filter(grade_level=grade_8, is_active=True)
    
    students4 = create_students_for_section(students_g8_orchid, section4, teacher4, school_year, subjects4)
    section4.current_enrollment_count = len(students4)
    section4.save()
    print(f"  ✅ {len(students4)} students in Orchid")
    
    # =========================================================================
    # SUMMARY
    # =========================================================================
    print("\n" + "=" * 60)
    print("✅ ALL TEACHERS SEEDED SUCCESSFULLY!")
    print("=" * 60)
    print(f"""
  ┌─────────────────────────────────────────────────────────────┬──────────────────┬───────────────┬──────────┐
  │ Teacher Name                  │ Email                        │ Password      │ Section   │ Students │
  ├─────────────────────────────────────────────────────────────┼──────────────────┼───────────────┼──────────┤
  │ User One                      │ User.one@deped.gov.ph        │ password123   │ G12 ABM C │ {len(students1):>8} │
  │ Jen Takashie                  │ jen.takashie@deped.gov.ph    │ teacherpass123│ G9 Camia  │ {len(students2):>8} │
  │ Jeren Takashie                │ jeren.takashie@deped.gov.ph  │ teacherpass123│ G10 Rizal │ {len(students3):>8} │
  │ Juan Dela Cruz                │ juan.delacruz.teach@deped... │ teacherpass123│ G8 Orchid │ {len(students4):>8} │
  └─────────────────────────────────────────────────────────────┴──────────────────┴───────────────┴──────────┘
  
  All teachers can login at: http://127.0.0.1:8000/teachers/dashboard/
  """)
    
    return True


if __name__ == "__main__":
    seed_all_teachers()