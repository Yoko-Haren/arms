"""
Formify LIS — Complete Seed Data Script
Populates all lookup tables, academic structure, teacher assignments,
sample students, attendance, grades, and reference data.
"""

import os
import random
from datetime import date, time, timedelta, datetime
import re

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')
import django
django.setup()

from django.contrib.auth.models import User
from django.utils import timezone
from accounts.models import (
    UserProfile, SchoolProfile, SchoolForm, GradeTransmutationTable,
    GradeComponentWeight, CalendarEventType, GradeRemarksTemplate,
    DocumentType, NotificationTemplate, RpmsCriteriaTemplate,
    RolePermission, PermissionAssignment,
)
from academics.models import (
    SchoolYear, Quarter, Semester, GradeLevel, Track, Strand,
    Subject, CurriculumMapping, Room, Section, RpmsCycle,
)
from students.models import Student, Guardian, StudentAddress
from enrollment.models import Enrollment
from scheduling.models import ClassAssignment, ClassSchedule
from attendance.models import AttendanceRecord, AttendanceSummary
from grades.models import GradeComponent
from configuration.models import GradingPeriod, DepEdConfiguration

print("=" * 60)
print("FORMIFY LIS — SEED DATA SCRIPT")
print("=" * 60)

# =============================================================================
# PART 1: SCHOOL PROFILE
# =============================================================================
print("\n[1/12] Creating School Profile...")
school, _ = SchoolProfile.objects.get_or_create(
    school_id="304912",
    defaults={
        'school_name': 'Doppelgänger Academy of Sciences',
        'school_short_name': 'DAS',
        'school_type': 'Public',
        'region_code': 'Region XI',
        'division_code': 'Davao City',
        'district': 'Talomo',
        'complete_address': '123 Innovation Street, Barangay Matina, Davao City, 8000',
        'contact_number': '(082) 300-1234',
        'official_email': 'doppelganger.academy@deped.gov.ph',
        'school_head_name': 'Aron John Smith Valera',
        'school_head_position': 'Principal IV',
        'school_head_deped_email': 'valera.aronjohnsmith@deped.gov.ph',
        'current_school_year': '2025-2026',
    }
)
print(f"  ✓ {school.school_name}")

# =============================================================================
# PART 2: SCHOOL YEAR, QUARTERS, SEMESTERS
# =============================================================================
print("\n[2/12] Creating School Year 2025-2026...")
sy, _ = SchoolYear.objects.get_or_create(
    year_label='2025-2026',
    defaults={
        'year_start': 2025, 'year_end': 2026,
        'date_start': date(2025, 7, 29),
        'date_end': date(2026, 5, 15),
        'total_instructional_days': 203,
        'is_current': True,
        'status': 'Active',
        'enrollment_open_date': date(2025, 7, 1),
        'enrollment_close_date': date(2025, 8, 15),
    }
)
print(f"  ✓ {sy.year_label} (Current: {sy.is_current})")

quarters_data = [
    ('Q1', 1, date(2025, 7, 29), date(2025, 10, 24), date(2025, 10, 20), date(2025, 10, 27)),
    ('Q2', 2, date(2025, 10, 27), date(2026, 1, 16), date(2026, 1, 12), date(2026, 1, 19)),
    ('Q3', 3, date(2026, 1, 19), date(2026, 4, 15), date(2026, 4, 10), date(2026, 4, 17)),
    ('Q4', 4, date(2026, 4, 17), date(2026, 5, 15), date(2026, 5, 10), date(2026, 5, 15)),
]
quarters = {}
for label, num, start, end, enc_deadline, val_deadline in quarters_data:
    q, _ = Quarter.objects.get_or_create(
        school_year=sy, quarter_number=num,
        defaults={
            'quarter_label': label,
            'date_start': start, 'date_end': end,
            'grade_encoding_deadline': datetime.combine(enc_deadline, time(23, 59)),
            'grade_validation_deadline': datetime.combine(val_deadline, time(23, 59)),
            'is_current_quarter': (num == 3),
        }
    )
    quarters[num] = q
    print(f"  ✓ {label}: {start} – {end} {'(Current)' if num == 3 else ''}")

semesters = {}
for label, num, start, end in [
    ('1st', 1, date(2025, 7, 29), date(2026, 1, 16)),
    ('2nd', 2, date(2026, 1, 19), date(2026, 5, 15)),
]:
    s, _ = Semester.objects.get_or_create(
        school_year=sy, semester_number=num,
        defaults={
            'semester_label': label,
            'date_start': start, 'date_end': end,
            'grade_encoding_deadline': datetime.combine(end - timedelta(days=5), time(23, 59)),
            'grade_validation_deadline': datetime.combine(end - timedelta(days=2), time(23, 59)),
        }
    )
    semesters[num] = s
    print(f"  ✓ {label} Semester: {start} – {end}")

# =============================================================================
# PART 3: GRADE LEVELS
# =============================================================================
print("\n[3/12] Creating Grade Levels...")
grade_levels = {}
for code, name, num in [
    ('G7', 'Grade 7', 7), ('G8', 'Grade 8', 8), ('G9', 'Grade 9', 9),
    ('G10', 'Grade 10', 10), ('G11', 'Grade 11', 11), ('G12', 'Grade 12', 12),
]:
    gl, _ = GradeLevel.objects.get_or_create(
        grade_code=code,
        defaults={
            'grade_name': name, 'grade_number': num,
            'sort_order': num,
        }
    )
    grade_levels[num] = gl
    print(f"  ✓ {name} ({'SHS' if gl.is_senior_high else 'JHS'})")

# =============================================================================
# PART 4: TRACKS & STRANDS
# =============================================================================
print("\n[4/12] Creating Tracks & Strands...")
academic_track, _ = Track.objects.get_or_create(
    track_code='ACADEMIC', defaults={'track_name': 'Academic Track'}
)
tvl_track, _ = Track.objects.get_or_create(
    track_code='TVL', defaults={'track_name': 'Technical-Vocational-Livelihood'}
)
sports_track, _ = Track.objects.get_or_create(
    track_code='SPORTS', defaults={'track_name': 'Sports Track'}
)
arts_track, _ = Track.objects.get_or_create(
    track_code='ARTS_DESIGN', defaults={'track_name': 'Arts & Design Track'}
)

strands_data = [
    ('STEM', 'Science, Technology, Engineering and Mathematics', academic_track),
    ('HUMSS', 'Humanities and Social Sciences', academic_track),
    ('ABM', 'Accountancy, Business and Management', academic_track),
    ('GAS', 'General Academic Strand', academic_track),
    ('ICT', 'Information and Communications Technology', tvl_track),
    ('HE', 'Home Economics', tvl_track),
    ('IA', 'Industrial Arts', tvl_track),
]
strands = {}
for code, name, track in strands_data:
    s, _ = Strand.objects.get_or_create(
        strand_code=code, defaults={'strand_name': name, 'track': track}
    )
    strands[code] = s
    print(f"  ✓ {code} — {name}")

# =============================================================================
# PART 5: SUBJECTS
# =============================================================================
print("\n[5/12] Creating Subjects...")

jhs_subjects = [
    ('ENG7', 'English 7', 'Core'), ('ENG8', 'English 8', 'Core'),
    ('ENG9', 'English 9', 'Core'), ('ENG10', 'English 10', 'Core'),
    ('MATH7', 'Mathematics 7', 'Core'), ('MATH8', 'Mathematics 8', 'Core'),
    ('MATH9', 'Mathematics 9', 'Core'), ('MATH10', 'Mathematics 10', 'Core'),
    ('SCI7', 'Science 7', 'Core'), ('SCI8', 'Science 8', 'Core'),
    ('SCI9', 'Science 9', 'Core'), ('SCI10', 'Science 10', 'Core'),
    ('FIL7', 'Filipino 7', 'Core'), ('FIL8', 'Filipino 8', 'Core'),
    ('FIL9', 'Filipino 9', 'Core'), ('FIL10', 'Filipino 10', 'Core'),
    ('AP7', 'Araling Panlipunan 7', 'Core'), ('AP8', 'Araling Panlipunan 8', 'Core'),
    ('AP9', 'Araling Panlipunan 9', 'Core'), ('AP10', 'Araling Panlipunan 10', 'Core'),
    ('MAPEH7', 'MAPEH 7', 'Core'), ('MAPEH8', 'MAPEH 8', 'Core'),
    ('MAPEH9', 'MAPEH 9', 'Core'), ('MAPEH10', 'MAPEH 10', 'Core'),
    ('TLE7', 'TLE 7', 'Core'), ('TLE8', 'TLE 8', 'Core'),
    ('TLE9', 'TLE 9', 'Core'), ('TLE10', 'TLE 10', 'Core'),
    ('VAL7', 'Values Education 7', 'Core'), ('VAL8', 'Values Education 8', 'Core'),
    ('VAL9', 'Values Education 9', 'Core'), ('VAL10', 'Values Education 10', 'Core'),
]

shs_core = [
    ('CORE-EAPP', 'English for Academic and Professional Purposes', 'Core'),
    ('CORE-PRACTICAL1', 'Practical Research 1', 'Core'),
    ('CORE-PRACTICAL2', 'Practical Research 2', 'Core'),
    ('CORE-PHILO', 'Introduction to the Philosophy of the Human Person', 'Core'),
    ('CORE-PEH1', 'Physical Education and Health 1', 'Core'),
    ('CORE-PEH2', 'Physical Education and Health 2', 'Core'),
    ('CORE-PEH3', 'Physical Education and Health 3', 'Core'),
    ('CORE-PEH4', 'Physical Education and Health 4', 'Core'),
    ('CORE-MIL', 'Media and Information Literacy', 'Core'),
    ('CORE-UCSP', 'Understanding Culture, Society and Politics', 'Core'),
    ('CORE-PAGBASA', 'Pagbasa at Pagsusuri ng Iba\'t Ibang Teksto', 'Core'),
    ('CORE-ENTREP', 'Entrepreneurship', 'Core'),
    ('CORE-CONTEMPO', 'Contemporary Philippine Arts from the Regions', 'Core'),
    ('CORE-STATS', 'Statistics and Probability', 'Core'),
    ('CORE-GENMATH', 'General Mathematics', 'Core'),
]

stem_specialized = [
    ('SP-STEM-PRECALC', 'Pre-Calculus', 'Specialized'),
    ('SP-STEM-BASCALC', 'Basic Calculus', 'Specialized'),
    ('SP-STEM-GENBIO1', 'General Biology 1', 'Specialized'),
    ('SP-STEM-GENBIO2', 'General Biology 2', 'Specialized'),
    ('SP-STEM-GENCHEM1', 'General Chemistry 1', 'Specialized'),
    ('SP-STEM-GENCHEM2', 'General Chemistry 2', 'Specialized'),
    ('SP-STEM-GENPHY1', 'General Physics 1', 'Specialized'),
    ('SP-STEM-GENPHY2', 'General Physics 2', 'Specialized'),
]

abm_specialized = [
    ('SP-ABM-BUSMATH', 'Business Mathematics', 'Specialized'),
    ('SP-ABM-FABM1', 'Fundamentals of Accountancy, Business and Management 1', 'Specialized'),
    ('SP-ABM-FABM2', 'Fundamentals of Accountancy, Business and Management 2', 'Specialized'),
    ('SP-ABM-BUSFIN', 'Business Finance', 'Specialized'),
    ('SP-ABM-ORG', 'Organization and Management', 'Specialized'),
    ('SP-ABM-MARKETING', 'Principles of Marketing', 'Specialized'),
]

all_subjects = {}
for code, name, cat in jhs_subjects:
    match = re.search(r'(\d+)$', code)
    grade_num = int(match.group(1)) if match else None
    gl = grade_levels.get(grade_num) if grade_num in grade_levels else None
    if gl is None:
        print(f"  ⚠ Could not determine grade level for {code}, skipping")
        continue
    sub, _ = Subject.objects.get_or_create(
        subject_code=code,
        defaults={
            'subject_name': name, 'subject_category': cat,
            'grade_level': gl, 'hours_per_week': 4.00, 'is_active': True,
        }
    )
    all_subjects[code] = sub

shs_core_gls = [grade_levels[11], grade_levels[12]]
for code, name, cat in shs_core:
    for gl in shs_core_gls:
        full_code = f"{code}-G{gl.grade_number}"
        sub, _ = Subject.objects.get_or_create(
            subject_code=full_code,
            defaults={
                'subject_name': name, 'subject_category': cat,
                'grade_level': gl, 'hours_per_semester': 80, 'is_active': True,
            }
        )
        all_subjects[full_code] = sub

for code, name, cat in stem_specialized:
    for gl in shs_core_gls:
        full_code = f"{code}-G{gl.grade_number}"
        sub, _ = Subject.objects.get_or_create(
            subject_code=full_code,
            defaults={
                'subject_name': name, 'subject_category': cat,
                'grade_level': gl, 'strand': strands['STEM'],
                'hours_per_semester': 80, 'is_active': True,
            }
        )
        all_subjects[full_code] = sub

for code, name, cat in abm_specialized:
    for gl in shs_core_gls:
        full_code = f"{code}-G{gl.grade_number}"
        sub, _ = Subject.objects.get_or_create(
            subject_code=full_code,
            defaults={
                'subject_name': name, 'subject_category': cat,
                'grade_level': gl, 'strand': strands['ABM'],
                'hours_per_semester': 80, 'is_active': True,
            }
        )
        all_subjects[full_code] = sub

print(f"  ✓ {len(all_subjects)} subjects created")

# =============================================================================
# PART 6: ROOMS & SECTIONS
# =============================================================================
print("\n[6/12] Creating Rooms & Sections...")

rooms_data = [
    ('BLDG1-101', 'Room 101', 'Classroom', 'Building 1', '1st Floor', 50),
    ('BLDG1-102', 'Room 102', 'Classroom', 'Building 1', '1st Floor', 50),
    ('BLDG1-201', 'Room 201', 'Classroom', 'Building 1', '2nd Floor', 45),
    ('BLDG1-202', 'Room 202', 'Classroom', 'Building 1', '2nd Floor', 45),
    ('BLDG2-301', 'Science Lab A', 'Science Lab', 'Building 2', '3rd Floor', 40),
    ('BLDG2-302', 'Computer Lab', 'Computer Lab', 'Building 2', '3rd Floor', 40),
    ('BLDG3-AV', 'AV Hall', 'Auditorium', 'Building 3', 'Ground Floor', 200),
]
rooms = {}
for code, name, rtype, bldg, floor, cap in rooms_data:
    r, _ = Room.objects.get_or_create(
        room_code=code,
        defaults={
            'room_name': name, 'room_type': rtype,
            'building': bldg, 'floor': floor, 'capacity': cap,
        }
    )
    rooms[code] = r

section_names = {
    7: ['Rose', 'Lily', 'Daisy'],
    8: ['Jasmine', 'Orchid', 'Sunflower'],
    9: ['Sampaguita', 'Camia', 'Ilang-Ilang'],
    10: ['Rizal', 'Bonifacio', 'Mabini'],
    11: {'STEM': ['STEM A', 'STEM B'], 'ABM': ['ABM A'], 'HUMSS': ['HUMSS A']},
    12: {'STEM': ['STEM A'], 'ABM': ['ABM A'], 'HUMSS': ['HUMSS A']},
}

all_sections = []
for grade_num, sections_info in section_names.items():
    gl = grade_levels[grade_num]
    if grade_num <= 10:
        for sec_name in sections_info:
            sec, _ = Section.objects.get_or_create(
                section_name=sec_name, grade_level=gl, school_year=sy,
                defaults={'max_capacity': 50, 'is_active': True}
            )
            all_sections.append(sec)
            print(f"  ✓ {gl.grade_name} - {sec_name}")
    else:
        for strand_code, sec_list in sections_info.items():
            for sec_name in sec_list:
                sec, _ = Section.objects.get_or_create(
                    section_name=sec_name, grade_level=gl, school_year=sy,
                    strand=strands[strand_code],
                    defaults={'max_capacity': 45, 'is_active': True}
                )
                all_sections.append(sec)
                print(f"  ✓ {gl.grade_name} {strand_code} - {sec_name}")

# =============================================================================
# PART 7: TEACHER ASSIGNMENTS (4 Teachers)
# =============================================================================
print("\n[7/12] Creating Teacher Accounts & Assignments...")

# ─────────────────────────────────────────────────────
# TEACHER 1: Yocoharen Takashie (Mathematics - Grade 11 STEM)
# ─────────────────────────────────────────────────────
print("\n  Creating Yocoharen Takashie (Mathematics)...")
try:
    yoco_user = User.objects.get(username='takashie.yocoharen@deped.gov.ph')
    yoco_profile = yoco_user.profile
    print(f"  ✓ Existing account: {yoco_user.get_full_name()}")
except User.DoesNotExist:
    yoco_user = User.objects.create_user(
        username='takashie.yocoharen@deped.gov.ph',
        email='takashie.yocoharen@deped.gov.ph',
        password='teacherpass',
        first_name='Yocoharen',
        last_name='Takashie',
        is_active=True,
    )
    yoco_profile = yoco_user.profile
    yoco_profile.role = 'teacher'
    yoco_profile.deped_email = 'takashie.yocoharen@deped.gov.ph'
    yoco_profile.teaching_area = 'Mathematics'
    yoco_profile.position_title = 'Teacher III'
    yoco_profile.designation = 'Mathematics Teacher - Grade 11 STEM Adviser'
    yoco_profile.employment_status = 'Regular_Permanent'
    yoco_profile.date_hired = date(2023, 6, 15)
    yoco_profile.employee_number = 'DEPED-MATH-2023-0015'
    yoco_profile.is_active = True
    yoco_profile.save()
    print(f"  ✓ Created: {yoco_user.get_full_name()}")

# Yocoharen assignments (SHS Math)
yoco_assignments = [
    ('STEM A', 'CORE-GENMATH-G11', True, 11),
    ('STEM B', 'CORE-GENMATH-G11', False, 11),
    ('STEM A', 'SP-STEM-PRECALC-G11', False, 11),
    ('STEM B', 'SP-STEM-PRECALC-G11', False, 11),
    ('ABM A', 'SP-ABM-BUSMATH-G11', False, 11),
    ('STEM A', 'CORE-STATS-G12', False, 12),
]
class_assignments = []
for sec_name, subj_code, is_adv, gl_num in yoco_assignments:
    try:
        section = Section.objects.get(
            section_name=sec_name, school_year=sy,
            grade_level__grade_number=gl_num
        )
        subject = all_subjects.get(subj_code)
        if not subject:
            print(f"  ⚠ Subject {subj_code} not found, skipping")
            continue
        ca, _ = ClassAssignment.objects.get_or_create(
            teacher=yoco_user, section=section, subject=subject,
            school_year=sy,
            defaults={
                'semester': semesters[1] if gl_num >= 11 else None,
                'is_advisory': is_adv,
                'default_room': rooms.get('BLDG1-201'),
                'is_active': True,
            }
        )
        class_assignments.append(ca)
        role = 'Adviser' if is_adv else 'Subject'
        print(f"  ✓ [Yocoharen] {sec_name} — {subject.subject_name} ({role})")
        if is_adv:
            section.adviser = yoco_user
            section.save()
            yoco_profile.is_homeroom_adviser = True
            yoco_profile.save()
    except Section.DoesNotExist:
        print(f"  ⚠ Section {sec_name} (G{gl_num}) not found")

# ─────────────────────────────────────────────────────
# TEACHER 2: Jen Takashie (English - Grade 9)
# ─────────────────────────────────────────────────────
print("\n  Creating Jen Takashie (English)...")
try:
    jen_user = User.objects.get(username='jen.takashie@deped.gov.ph')
    jen_profile = jen_user.profile
    print(f"  ✓ Existing account: {jen_user.get_full_name()}")
except User.DoesNotExist:
    jen_user = User.objects.create_user(
        username='jen.takashie@deped.gov.ph',
        email='jen.takashie@deped.gov.ph',
        password='teacherpass123',
        first_name='Jen',
        last_name='Takashie',
        is_active=True,
    )
    jen_profile = jen_user.profile
    jen_profile.role = 'teacher'
    jen_profile.deped_email = 'jen.takashie@deped.gov.ph'
    jen_profile.teaching_area = 'English'
    jen_profile.position_title = 'Teacher II'
    jen_profile.designation = 'English Teacher - Grade 9 Camia Adviser'
    jen_profile.employment_status = 'Regular_Permanent'
    jen_profile.date_hired = date(2022, 6, 13)
    jen_profile.employee_number = 'DEPED-ENG-2022-0042'
    jen_profile.is_active = True
    jen_profile.save()
    print(f"  ✓ Created: {jen_user.get_full_name()}")

jen_assignments = [
    ('Sampaguita', 'ENG9', False, 9),
    ('Camia', 'ENG9', True, 9),
    ('Ilang-Ilang', 'ENG9', False, 9),
    ('Rizal', 'ENG10', False, 10),
    ('Bonifacio', 'ENG10', False, 10),
    ('Mabini', 'ENG10', False, 10),
]
for sec_name, subj_code, is_adv, gl_num in jen_assignments:
    try:
        section = Section.objects.get(
            section_name=sec_name, school_year=sy,
            grade_level__grade_number=gl_num
        )
        subject = all_subjects.get(subj_code)
        if not subject: continue
        ClassAssignment.objects.get_or_create(
            teacher=jen_user, section=section, subject=subject,
            school_year=sy,
            defaults={
                'semester': None, 'is_advisory': is_adv,
                'default_room': rooms.get('BLDG1-102'), 'is_active': True,
            }
        )
        role = 'Adviser' if is_adv else 'Subject'
        print(f"  ✓ [Jen] {sec_name} — {subject.subject_name} ({role})")
        if is_adv:
            section.adviser = jen_user
            section.save()
            jen_profile.is_homeroom_adviser = True
            jen_profile.save()
    except Section.DoesNotExist:
        print(f"  ⚠ Section {sec_name} (G{gl_num}) not found")

# ─────────────────────────────────────────────────────
# TEACHER 3: Jeren Takashie (Science - Grade 10)
# ─────────────────────────────────────────────────────
print("\n  Creating Jeren Takashie (Science)...")
try:
    jeren_user = User.objects.get(username='jeren.takashie@deped.gov.ph')
    jeren_profile = jeren_user.profile
    print(f"  ✓ Existing account: {jeren_user.get_full_name()}")
except User.DoesNotExist:
    jeren_user = User.objects.create_user(
        username='jeren.takashie@deped.gov.ph',
        email='jeren.takashie@deped.gov.ph',
        password='teacherpass123',
        first_name='Jeren',
        last_name='Takashie',
        is_active=True,
    )
    jeren_profile = jeren_user.profile
    jeren_profile.role = 'teacher'
    jeren_profile.deped_email = 'jeren.takashie@deped.gov.ph'
    jeren_profile.teaching_area = 'Science'
    jeren_profile.position_title = 'Teacher III'
    jeren_profile.designation = 'Science Teacher - Grade 10 Rizal Adviser'
    jeren_profile.employment_status = 'Regular_Permanent'
    jeren_profile.date_hired = date(2021, 5, 24)
    jeren_profile.employee_number = 'DEPED-SCI-2021-0031'
    jeren_profile.is_active = True
    jeren_profile.save()
    print(f"  ✓ Created: {jeren_user.get_full_name()}")

jeren_assignments = [
    ('Sampaguita', 'SCI9', False, 9),
    ('Camia', 'SCI9', False, 9),
    ('Ilang-Ilang', 'SCI9', False, 9),
    ('Rizal', 'SCI10', True, 10),
    ('Bonifacio', 'SCI10', False, 10),
    ('Mabini', 'SCI10', False, 10),
]
for sec_name, subj_code, is_adv, gl_num in jeren_assignments:
    try:
        section = Section.objects.get(
            section_name=sec_name, school_year=sy,
            grade_level__grade_number=gl_num
        )
        subject = all_subjects.get(subj_code)
        if not subject: continue
        ClassAssignment.objects.get_or_create(
            teacher=jeren_user, section=section, subject=subject,
            school_year=sy,
            defaults={
                'semester': None, 'is_advisory': is_adv,
                'default_room': rooms.get('BLDG1-201'), 'is_active': True,
            }
        )
        role = 'Adviser' if is_adv else 'Subject'
        print(f"  ✓ [Jeren] {sec_name} — {subject.subject_name} ({role})")
        if is_adv:
            section.adviser = jeren_user
            section.save()
            jeren_profile.is_homeroom_adviser = True
            jeren_profile.save()
    except Section.DoesNotExist:
        print(f"  ⚠ Section {sec_name} (G{gl_num}) not found")

# ─────────────────────────────────────────────────────
# TEACHER 4: Juan Dela Cruz (Filipino/AP - Grade 8)
# ─────────────────────────────────────────────────────
print("\n  Creating Juan Dela Cruz (Filipino/AP)...")
try:
    juan_user = User.objects.get(username='juan.delacruz.teach@deped.gov.ph')
    juan_profile = juan_user.profile
    print(f"  ✓ Existing account: {juan_user.get_full_name()}")
except User.DoesNotExist:
    juan_user = User.objects.create_user(
        username='juan.delacruz.teach@deped.gov.ph',
        email='juan.delacruz.teach@deped.gov.ph',
        password='teacherpass123',
        first_name='Juan',
        last_name='Dela Cruz',
        is_active=True,
    )
    juan_profile = juan_user.profile
    juan_profile.role = 'teacher'
    juan_profile.deped_email = 'juan.delacruz.teach@deped.gov.ph'
    juan_profile.teaching_area = 'Filipino'
    juan_profile.position_title = 'Teacher I'
    juan_profile.designation = 'Filipino & AP Teacher - Grade 8 Orchid Adviser'
    juan_profile.employment_status = 'Probationary'
    juan_profile.date_hired = date(2025, 1, 6)
    juan_profile.employee_number = 'DEPED-FIL-2025-0008'
    juan_profile.is_active = True
    juan_profile.save()
    print(f"  ✓ Created: {juan_user.get_full_name()}")

juan_assignments = [
    ('Rose', 'FIL7', False, 7),
    ('Lily', 'FIL7', False, 7),
    ('Jasmine', 'FIL8', False, 8),
    ('Orchid', 'FIL8', True, 8),
    ('Sunflower', 'FIL8', False, 8),
    ('Jasmine', 'AP8', False, 8),
    ('Orchid', 'AP8', False, 8),
    ('Sunflower', 'AP8', False, 8),
]
for sec_name, subj_code, is_adv, gl_num in juan_assignments:
    try:
        section = Section.objects.get(
            section_name=sec_name, school_year=sy,
            grade_level__grade_number=gl_num
        )
        subject = all_subjects.get(subj_code)
        if not subject: continue
        ClassAssignment.objects.get_or_create(
            teacher=juan_user, section=section, subject=subject,
            school_year=sy,
            defaults={
                'semester': None, 'is_advisory': is_adv,
                'default_room': rooms.get('BLDG1-101'), 'is_active': True,
            }
        )
        role = 'Adviser' if is_adv else 'Subject'
        print(f"  ✓ [Juan] {sec_name} — {subject.subject_name} ({role})")
        if is_adv:
            section.adviser = juan_user
            section.save()
            juan_profile.is_homeroom_adviser = True
            juan_profile.save()
    except Section.DoesNotExist:
        print(f"  ⚠ Section {sec_name} (G{gl_num}) not found")

print(f"""
  ✅ Teacher Accounts Created:
  ┌─────────────────────────────────────────────────────────────┬──────────────────┬───────────────┐
  │ Teacher Name                  │ Email                        │ Password      │ Advisory       │
  ├─────────────────────────────────────────────────────────────┼──────────────────┼───────────────┤
  │ Yocoharen Takashie            │ takashie.yocoharen@deped...  │ teacherpass   │ G11 STEM A     │
  │ Jen Takashie                  │ jen.takashie@deped.gov.ph    │ teacherpass123│ G9 Camia       │
  │ Jeren Takashie                │ jeren.takashie@deped.gov.ph  │ teacherpass123│ G10 Rizal      │
  │ Juan Dela Cruz                │ juan.delacruz.teach@deped... │ teacherpass123│ G8 Orchid      │
  └─────────────────────────────────────────────────────────────┴──────────────────┴───────────────┘
""")

# Continue with Part 8-12 from the original seed script...
# (Parts 8-12 remain the same as your original script)