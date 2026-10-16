"""Demo data for screenshots and design work: one self-contained demo school.

    python manage.py seed_demo            create the demo school (refuses if it already exists)
    python manage.py seed_demo --reset    remove it first, then create it again
    python manage.py seed_demo --remove   remove the demo school and everything that belongs to it
    python manage.py seed_demo --dry-run  do everything, show the totals, then undo it

Nothing outside the demo school is read or changed. Demo records are recognisable by:
school ID DEMO-ARMS, usernames ending in @demo.arms.edu.ph, and student numbers starting 9999.
All demo accounts share one password, kept in .env as DEMO_PASSWORD (never printed).
"""
import random
import secrets
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from academics.models import (
    Assessment, AssessmentQuestion, AssessmentResponse, GradeLevel, Quarter, School, SchoolYear,
    Section, Strand, Subject, SubjectFamily, Track,
)
from accounts.models import PasswordReset, UserProfile
from attendance.models import AttendanceSummary
from enrollment.models import Enrollment
from grades.models import GradeComponent
from promotion.models import PromotionRecommendation
from scheduling.models import ClassAssignment
from students.models import Guardian, Student

SCHOOL_ID = 'DEMO-ARMS'
DOMAIN = 'demo.arms.edu.ph'
LRN_PREFIX = '9999'
ACTIVE = ['Enrolled', 'Transferred_In']

# ----------------------------------------------------------------------------- people
HEADS = [
    # first, last, designation, showcase account?
    ('Antonio', 'Fernandez', 'Principal III', True),
    ('Lourdes', 'Gonzales', 'Assistant Principal', False),
]
REGISTRARS = [
    ('Elena', 'Ramirez', 'School Registrar', True),
    ('Miguel', 'Torres', 'Registrar I', False),
]
# key, first, last, position, teaching area, showcase account?
TEACHERS = [
    ('math_a', 'Maria', 'Santos', 'Teacher III', 'Mathematics', True),
    ('math_b', 'Ramon', 'Villanueva', 'Master Teacher I', 'Mathematics', False),
    ('sci_a', 'Liza', 'Mercado', 'Teacher II', 'Science', False),
    ('sci_b', 'Carlo', 'Bautista', 'Teacher III', 'Science', False),
    ('eng_a', 'Angelica', 'Reyes', 'Teacher II', 'English', False),
    ('eng_b', 'Paolo', 'Garcia', 'Teacher I', 'English', False),
    ('fil_a', 'Rosalinda', 'Dizon', 'Teacher III', 'Filipino', False),
    ('fil_b', 'Emmanuel', 'Cruz', 'Teacher II', 'Filipino', False),
    ('ap', 'Teresita', 'Aquino', 'Head Teacher I', 'Araling Panlipunan', False),
    ('mapeh', 'Joselito', 'Ramos', 'Teacher II', 'MAPEH', False),
    ('tle', 'Marites', 'Flores', 'Teacher I', 'TLE', False),
    ('esp', 'Cristina', 'Navarro', 'Teacher I', 'Edukasyon sa Pagpapakatao', False),
    ('shs_math', 'Roberto', 'Mendoza', 'Master Teacher II', 'Mathematics (SHS)', True),
    ('shs_sci', 'Jennifer', 'Tan', 'Teacher III', 'Science (SHS)', False),
    ('shs_eng', 'Katrina', 'Lopez', 'Teacher II', 'English (SHS)', False),
    ('shs_fil', 'Benjamin', 'Castillo', 'Teacher III', 'Filipino and Social Science (SHS)', False),
    ('shs_hum', 'Danilo', 'Pascual', 'Teacher II', 'Humanities and PE (SHS)', False),
]
NEW_TEACHER = ('Sofia', 'Marquez', 'Teacher I', 'Science')            # no classes yet, temporary password
INACTIVE_TEACHER = ('Gregorio', 'Salazar', 'Teacher III', 'Mathematics')  # deactivated account

# ----------------------------------------------------------------------------- curriculum
FAMILIES = [
    # code, name, colour, icon, grade offset (how hard the discipline tends to be)
    ('MATH', 'Mathematics', '#123499', 'fi fi-rr-calculator', -2.5),
    ('SCI', 'Science', '#1565C0', 'fi fi-rr-flask', -1.5),
    ('ENG', 'English', '#6A1B9A', 'fi fi-rr-book-alt', -0.5),
    ('FIL', 'Filipino', '#E65100', 'fi fi-rr-comment-alt', 0.5),
    ('AP', 'Araling Panlipunan', '#2D6AFF', 'fi fi-rr-globe', 0.5),
    ('MAPEH', 'MAPEH', '#C62828', 'fi fi-rr-music-alt', 2.5),
    ('TLE', 'Technology and Livelihood Education', '#4a6fd4', 'fi fi-rr-tools', 2.0),
    ('ESP', 'Edukasyon sa Pagpapakatao', '#764ba2', 'fi fi-rr-heart', 3.0),
    ('HUMSS', 'Humanities and Social Sciences', '#667eea', 'fi fi-rr-users-alt', -0.5),
]
# Junior high: the same eight learning areas every year. (suffix, name, family, teacher by grade band, meetings/week)
JHS_SUBJECTS = [
    ('FIL', 'Filipino', 'FIL', ('fil_a', 'fil_b'), 5),
    ('ENG', 'English', 'ENG', ('eng_a', 'eng_b'), 5),
    ('MATH', 'Mathematics', 'MATH', ('math_a', 'math_b'), 5),
    ('SCI', 'Science', 'SCI', ('sci_a', 'sci_b'), 5),
    ('AP', 'Araling Panlipunan', 'AP', ('ap', 'ap'), 3),
    ('MAPEH', 'MAPEH', 'MAPEH', ('mapeh', 'mapeh'), 4),
    ('TLE', 'Technology and Livelihood Education', 'TLE', ('tle', 'tle'), 4),
    ('ESP', 'Edukasyon sa Pagpapakatao', 'ESP', ('esp', 'esp'), 2),
]
# Senior high: (code, name, family, grade, strand or None for core, teacher, meetings/week)
SHS_SUBJECTS = [
    ('ORALCOM11', 'Oral Communication', 'ENG', 11, None, 'shs_eng', 4),
    ('KOMPAN11', 'Komunikasyon at Pananaliksik', 'FIL', 11, None, 'shs_fil', 4),
    ('GENMATH11', 'General Mathematics', 'MATH', 11, None, 'shs_math', 4),
    ('ELS11', 'Earth and Life Science', 'SCI', 11, None, 'shs_sci', 4),
    ('PEH11', 'Physical Education and Health 1', 'MAPEH', 11, None, 'shs_hum', 2),
    ('PERDEV11', 'Personal Development', 'ESP', 11, None, 'shs_hum', 2),
    ('PRECAL11', 'Pre-Calculus', 'MATH', 11, 'STEM', 'shs_math', 4),
    ('GENBIO11', 'General Biology 1', 'SCI', 11, 'STEM', 'shs_sci', 4),
    ('DISS11', 'Disciplines and Ideas in the Social Sciences', 'HUMSS', 11, 'HUMSS', 'shs_hum', 4),
    ('PHILO11', 'Introduction to the Philosophy of the Human Person', 'HUMSS', 11, 'HUMSS', 'shs_hum', 4),
    ('LIT12', '21st Century Literature', 'ENG', 12, None, 'shs_eng', 4),
    ('FILPIL12', 'Pagbasa at Pagsusuri ng Iba\'t Ibang Teksto', 'FIL', 12, None, 'shs_fil', 4),
    ('STAT12', 'Statistics and Probability', 'MATH', 12, None, 'shs_math', 4),
    ('PHYSCI12', 'Physical Science', 'SCI', 12, None, 'shs_sci', 4),
    ('PEH12', 'Physical Education and Health 3', 'MAPEH', 12, None, 'shs_hum', 2),
    ('UCSP12', 'Understanding Culture, Society and Politics', 'AP', 12, None, 'shs_fil', 4),
    ('BASCAL12', 'Basic Calculus', 'MATH', 12, 'STEM', 'shs_math', 4),
    ('GENPHY12', 'General Physics 1', 'SCI', 12, 'STEM', 'shs_sci', 4),
    ('CREWRI12', 'Creative Writing', 'HUMSS', 12, 'HUMSS', 'shs_eng', 4),
    ('PPG12', 'Philippine Politics and Governance', 'HUMSS', 12, 'HUMSS', 'shs_hum', 4),
]
# grade, section name, strand, adviser key, class size, section offset
SECTIONS = [
    (7, 'Sampaguita', None, 'math_a', 32, 2.0), (7, 'Rosal', None, 'sci_a', 30, -1.5),
    (8, 'Narra', None, 'eng_a', 31, 1.5), (8, 'Molave', None, 'fil_a', 29, -2.0),
    (9, 'Rizal', None, 'math_b', 30, 2.5), (9, 'Bonifacio', None, 'sci_b', 28, -1.0),
    (10, 'Mabini', None, 'eng_b', 29, 1.0), (10, 'Luna', None, 'fil_b', 27, -2.5),
    (11, 'STEM-A', 'STEM', 'shs_math', 26, 3.0), (11, 'HUMSS-A', 'HUMSS', 'shs_hum', 24, -0.5),
    (12, 'STEM-A', 'STEM', 'shs_sci', 25, 3.5), (12, 'HUMSS-A', 'HUMSS', 'shs_eng', 23, 0.0),
]
# How far along each class is in the current (second) quarter, repeated over the classes.
Q2_STATES = (['validated'] * 9 + ['ready'] * 4 + ['incomplete'] * 3 + ['returned'] + ['not_started'] * 3)

FIRST_M = ['Juan', 'Jose', 'Miguel', 'Gabriel', 'Rafael', 'Andres', 'Carlos', 'Daniel', 'Joshua', 'Mark', 'John Paul',
           'Christian', 'Angelo', 'Kenneth', 'Jerome', 'Francis', 'Vincent', 'Adrian', 'Nathaniel', 'Elijah', 'Marco',
           'Paolo', 'Renz', 'Jericho', 'Kyle', 'Ivan', 'Lance', 'Xander', 'Emman', 'Rico']
FIRST_F = ['Maria', 'Angela', 'Kristine', 'Jasmine', 'Nicole', 'Camille', 'Patricia', 'Andrea', 'Bianca', 'Isabel',
           'Sophia', 'Althea', 'Princess', 'Jessa', 'Hannah', 'Erika', 'Trisha', 'Danica', 'Samantha', 'Clarisse',
           'Joanna', 'Katrina', 'Louise', 'Mikaela', 'Rhea', 'Shaira', 'Vanessa', 'Yna', 'Zoe', 'Aira']
LASTS = ['Abad', 'Agustin', 'Alvarez', 'Bautista', 'Belmonte', 'Cabrera', 'Castro', 'Corpuz', 'De Leon', 'Dela Cruz',
         'Del Rosario', 'Domingo', 'Espinosa', 'Estrada', 'Ferrer', 'Francisco', 'Gomez', 'Guevarra', 'Hernandez',
         'Ignacio', 'Javier', 'Lacson', 'Lim', 'Magno', 'Manalo', 'Marasigan', 'Mendoza', 'Morales', 'Natividad',
         'Ocampo', 'Padilla', 'Pangilinan', 'Perez', 'Quiambao', 'Rivera', 'Robles', 'Salvador', 'Samonte',
         'San Jose', 'Santiago', 'Soriano', 'Tolentino', 'Umali', 'Valdez', 'Velasco', 'Yap', 'Zamora']
MIDDLES = ['A.', 'B.', 'C.', 'D.', 'E.', 'G.', 'L.', 'M.', 'P.', 'R.', 'S.', 'T.', 'V.']


def _aware(d, hour=17):
    dt = datetime.combine(d, time(hour, 0))
    return timezone.make_aware(dt) if settings.USE_TZ else dt


def _descriptor(grade):
    if grade >= 90:
        return 'Outstanding'
    if grade >= 85:
        return 'Very_Satisfactory'
    if grade >= 80:
        return 'Satisfactory'
    if grade >= 75:
        return 'Fairly_Satisfactory'
    return 'Did_Not_Meet_Expectations'


def demo_password():
    """The shared demo password from .env; created and saved there the first time."""
    import os
    password = os.environ.get('DEMO_PASSWORD', '').strip()
    if password:
        return password, False
    password = 'Demo-' + secrets.token_urlsafe(9)
    env_path = settings.BASE_DIR / '.env'
    with open(env_path, 'a', encoding='utf-8') as handle:
        handle.write('\n# Password shared by the demo accounts created by `python manage.py seed_demo`\n'
                     f'DEMO_PASSWORD={password}\n')
    os.environ['DEMO_PASSWORD'] = password
    return password, True


# ============================================================================= removal
def remove_demo():
    """Delete the demo school and every record that belongs to it. Returns what was removed."""
    removed = {}
    school = School.objects.filter(school_id=SCHOOL_ID).first()
    users = User.objects.filter(username__endswith='@' + DOMAIN)
    if school:
        removed['grades'] = GradeComponent.objects.filter(enrollment__section__school=school).delete()[0]
        Assessment.objects.filter(school_year__school=school).delete()
        removed['enrollments'] = Enrollment.objects.filter(section__school=school).count()
        Enrollment.objects.filter(section__school=school).delete()        # attendance, promotions, history go with it
        ClassAssignment.objects.filter(section__school=school).delete()
        Section.objects.filter(school=school).delete()
        Subject.objects.filter(school=school).delete()
    removed['students'] = Student.objects.filter(lrn__startswith=LRN_PREFIX).count()
    Student.objects.filter(lrn__startswith=LRN_PREFIX).delete()
    PasswordReset.objects.filter(user__in=users).delete()
    removed['accounts'] = users.count()
    users.delete()
    if school:
        school.delete()                                                    # school years, quarters, grade levels, tracks
        removed['school'] = 1
    return removed


# ============================================================================= seeding
class Seeder:
    def __init__(self, password, out):
        self.rng = random.Random(20261009)
        self.password_hash = make_password(password)
        self.out = out
        self.staff = {}          # key -> User
        self.totals = {}

    # ---------------------------------------------------------------- accounts
    def _account(self, first, last, role, designation, area='', linked=False, temporary=False, active=True, number=''):
        username = f'{first}.{last}'.lower().replace(' ', '') + '@' + DOMAIN
        user = User.objects.create(
            username=username, email=username, first_name=first, last_name=last,
            password=self.password_hash, is_active=active,
            last_login=timezone.now() - timedelta(days=self.rng.randint(0, 9), hours=self.rng.randint(1, 20)) if (active and not temporary) else None,
        )
        profile = user.profile                      # created by the post_save signal
        profile.role = role
        profile.school = self.school
        profile.employee_number = number
        profile.designation = designation
        profile.position_title = designation
        profile.teaching_area = area
        profile.employment_status = 'Regular_Permanent'
        profile.institutional_email = username
        profile.date_hired = date(self.rng.randint(2008, 2023), self.rng.randint(1, 12), 15)
        profile.is_active = active
        profile.must_change_password = temporary
        if linked:
            # Marked as already linked so the demo account is not stopped at "Link your Google account".
            profile.google_sub = f'demo-{username}'
            profile.google_email = username
            profile.google_linked_at = timezone.now() - timedelta(days=self.rng.randint(3, 40))
        profile.save()
        user.groups.add(self.groups[role])
        return user

    def accounts(self):
        self.groups = {
            'schoolhead': Group.objects.get_or_create(name='Principal')[0],
            'registrar': Group.objects.get_or_create(name='Registrar')[0],
            'teacher': Group.objects.get_or_create(name='Teacher')[0],
        }
        self.showcase = []
        for i, (first, last, designation, show) in enumerate(HEADS, 1):
            user = self._account(first, last, 'schoolhead', designation, 'Administration', linked=True, number=f'DEMO-H-{i:03d}')
            self.staff[f'head{i}'] = user
            if show:
                self.showcase.append(('School Head', user))
        for i, (first, last, designation, show) in enumerate(REGISTRARS, 1):
            user = self._account(first, last, 'registrar', designation, 'Records', linked=show, temporary=not show, number=f'DEMO-R-{i:03d}')
            self.staff[f'registrar{i}'] = user
            if show:
                self.showcase.append(('Registrar', user))
        for i, (key, first, last, position, area, show) in enumerate(TEACHERS, 1):
            linked = show or i % 3 != 0            # most teachers linked, some still password-only
            user = self._account(first, last, 'teacher', position, area, linked=linked, number=f'DEMO-T-{i:03d}')
            self.staff[key] = user
            if show:
                self.showcase.append(('Teacher', user))
        first, last, position, area = NEW_TEACHER
        self.staff['new'] = self._account(first, last, 'teacher', position, area, temporary=True, number='DEMO-T-098')
        first, last, position, area = INACTIVE_TEACHER
        self.staff['inactive'] = self._account(first, last, 'teacher', position, area, linked=True, active=False, number='DEMO-T-099')
        self.registrar = self.staff['registrar1']
        self.totals['accounts'] = len(self.staff)

    # ---------------------------------------------------------------- school structure
    def structure(self):
        from admin_panel.forms import SchoolForm

        self.school = School.objects.create(
            school_id=SCHOOL_ID, school_name='ARMS Demo National High School', short_name='ADNHS',
            address='Demo Avenue, Davao City', contact_number='(082) 555-0100', email_domain='@' + DOMAIN,
            grading_scale='PERCENTAGE', passing_grade=75.0, period_type='QUARTERLY', quarters_count=4,
        )
        SchoolForm._create_default_schema(None, self.school, 'DEPED_INTEGRATED')

        self.levels = {}
        for n in range(7, 13):
            self.levels[n] = GradeLevel.objects.create(
                school=self.school, grade_code=f'G{n}', grade_name=f'Grade {n}', grade_number=n,
                level_category='SHS' if n >= 11 else 'JHS', is_senior_high=n >= 11, sort_order=n,
            )

        track = Track.objects.create(school=self.school, track_code='ACADEMIC', track_name='Academic Track')
        self.strands = {
            'STEM': Strand.objects.create(track=track, strand_code='STEM', strand_name='Science, Technology, Engineering and Mathematics'),
            'HUMSS': Strand.objects.create(track=track, strand_code='HUMSS', strand_name='Humanities and Social Sciences'),
        }

        self.family_offset = {}
        families = {}
        for order, (code, name, colour, icon, offset) in enumerate(FAMILIES, 1):
            families[code] = SubjectFamily.objects.create(
                school=self.school, family_code=code, family_name=name, color_hex=colour, icon_class=icon, sort_order=order,
            )
            self.family_offset[code] = offset

        # subjects, with who teaches them and how often they meet
        self.subjects = {}          # code -> Subject
        self.subject_meta = {}      # code -> (family, teacher key(s), meetings/week, strand)
        for n in range(7, 11):
            for suffix, name, family, teachers, meetings in JHS_SUBJECTS:
                code = f'{suffix}{n}'
                self.subjects[code] = Subject.objects.create(
                    school=self.school, subject_code=code, subject_name=f'{name} {n}', subject_category='Core',
                    grade_level=self.levels[n], subject_family=families[family], hours_per_week=Decimal(meetings),
                )
                self.subject_meta[code] = (family, teachers[0] if n <= 8 else teachers[1], meetings, None)
        for code, name, family, grade, strand, teacher, meetings in SHS_SUBJECTS:
            self.subjects[code] = Subject.objects.create(
                school=self.school, subject_code=code, subject_name=name,
                subject_category='Specialized' if strand else 'Core', grade_level=self.levels[grade],
                subject_family=families[family], strand=self.strands.get(strand), hours_per_week=Decimal(meetings),
            )
            self.subject_meta[code] = (family, teacher, meetings, strand)
        self.totals['subjects'] = len(self.subjects)

    def section_subjects(self, grade, strand):
        """Subject codes a section takes."""
        if grade <= 10:
            return [f'{suffix}{grade}' for suffix, *_ in JHS_SUBJECTS]
        return [code for code, _, _, g, s, _, _ in SHS_SUBJECTS if g == grade and s in (None, strand)]

    def calendar(self):
        def make_year(label, start, end, current, quarters):
            sy = SchoolYear.objects.create(
                school=self.school, year_label=label, year_start=start.year, year_end=start.year + 1,
                date_start=start, date_end=end, is_current=current, status='Active' if current else 'Completed',
                enrollment_open_date=start - timedelta(days=45), enrollment_close_date=start - timedelta(days=3),
            )
            created = []
            for number, (q_start, q_end, is_current, locked) in enumerate(quarters, 1):
                created.append(Quarter.objects.create(
                    school_year=sy, quarter_label=f'Q{number}', quarter_number=number, date_start=q_start, date_end=q_end,
                    grade_encoding_deadline=_aware(q_end + timedelta(days=7)),
                    grade_validation_deadline=_aware(q_end + timedelta(days=14)),
                    card_distribution_date=q_end + timedelta(days=21),
                    is_current_quarter=is_current, is_grades_locked=locked,
                    locked_by=self.registrar if locked else None,
                    locked_at=_aware(q_end + timedelta(days=15)) if locked else None,
                ))
            return sy, created

        self.prev_sy, self.prev_quarters = make_year('2025-2026', date(2025, 6, 16), date(2026, 3, 31), False, [
            (date(2025, 6, 16), date(2025, 8, 22), False, True), (date(2025, 8, 25), date(2025, 10, 31), False, True),
            (date(2025, 11, 3), date(2026, 1, 23), False, True), (date(2026, 1, 26), date(2026, 3, 31), False, True),
        ])
        self.sy, self.quarters = make_year('2026-2027', date(2026, 6, 8), date(2027, 4, 8), True, [
            (date(2026, 6, 8), date(2026, 8, 21), False, True), (date(2026, 8, 24), date(2026, 11, 6), True, False),
            (date(2026, 11, 9), date(2027, 1, 29), False, False), (date(2027, 2, 1), date(2027, 4, 8), False, False),
        ])

    # ---------------------------------------------------------------- sections, students, enrolment
    def people(self):
        rng = self.rng
        self.sections = []        # dicts for the current year
        self.prev_sections = []   # dicts for last year
        used_names = set()
        students, guardians = [], []
        serial = 0

        for grade, name, strand, adviser, size, offset in SECTIONS:
            section = Section.objects.create(
                school=self.school, grade_level=self.levels[grade], school_year=self.sy, section_name=name,
                strand=self.strands.get(strand), adviser=self.staff[adviser], max_capacity=35, is_homeroom=True,
            )
            members = []
            for _ in range(size):
                while True:
                    sex = rng.choice('MF')
                    first = rng.choice(FIRST_M if sex == 'M' else FIRST_F)
                    last = rng.choice(LASTS)
                    if (first, last) not in used_names:
                        used_names.add((first, last))
                        break
                serial += 1
                student = Student(
                    lrn=f'{LRN_PREFIX}{serial:08d}', first_name=first, last_name=last, middle_name=rng.choice(MIDDLES),
                    sex=sex, birth_date=date(2026 - grade - 5, rng.randint(1, 12), rng.randint(1, 28)),
                    birth_place='Davao City', nationality='Filipino', mother_tongue='Cebuano',
                    is_4ps=rng.random() < 0.18, is_active=True, is_verified=True, created_by=self.registrar,
                )
                students.append(student)
                members.append({'student': student, 'ability': max(66.0, min(97.0, rng.gauss(83.5, 6.2)))})
            self.sections.append({'section': section, 'grade': grade, 'strand': strand, 'offset': offset,
                                  'members': members, 'subjects': self.section_subjects(grade, strand)})
            UserProfile.objects.filter(user=self.staff[adviser]).update(is_homeroom_adviser=True)

        Student.objects.bulk_create(students, batch_size=500)
        for student in students:
            guardians.append(Guardian(
                student=student, first_name=rng.choice(FIRST_F if rng.random() < 0.7 else FIRST_M), last_name=student.last_name,
                relationship='Mother' if rng.random() < 0.7 else 'Father', is_primary_guardian=True,
            ))
        Guardian.objects.bulk_create(guardians, batch_size=500)
        self.totals['students'] = len(students)

        # ---- this year's enrolment (a few transferees and drop-outs for realistic rosters)
        enrollments = []
        for entry in self.sections:
            for i, member in enumerate(entry['members']):
                status, kind = 'Enrolled', 'New' if entry['grade'] in (7, 11) else 'Continuing'
                if i == 5 and entry['grade'] in (8, 9, 12):
                    status, kind = 'Transferred_In', 'Transferred_In'
                if i == 11 and entry['grade'] in (7, 10):
                    status = 'Dropped'
                member['status'] = status
                member['enrollment'] = Enrollment(
                    student=member['student'], section=entry['section'], school_year=self.sy,
                    grade_level_at_entry=self.levels[entry['grade']], enrollment_date=date(2026, 5, rng.randint(18, 29)),
                    enrollment_type=kind, status=status, status_date=date(2026, 9, 14) if status == 'Dropped' else None,
                    is_4ps=member['student'].is_4ps, created_by=self.registrar,
                )
                enrollments.append(member['enrollment'])
        Enrollment.objects.bulk_create(enrollments, batch_size=500)
        for entry in self.sections:
            active = sum(1 for m in entry['members'] if m['status'] in ACTIVE)
            Section.objects.filter(pk=entry['section'].pk).update(current_enrollment_count=active)

        # ---- last year: today's Grade 8-12 students were one grade lower, in sections of the same names
        prev_enrollments = []
        for entry in self.sections:
            if entry['grade'] == 7:
                continue
            grade = entry['grade'] - 1
            template = SECTIONS[self.sections.index(entry) - 2]    # same position, one grade lower
            section = Section.objects.create(
                school=self.school, grade_level=self.levels[grade], school_year=self.prev_sy, section_name=template[1],
                strand=self.strands.get(template[2]), adviser=self.staff[template[3]], max_capacity=35, is_homeroom=True,
            )
            members = []
            for member in entry['members']:
                if member['status'] == 'Transferred_In':
                    continue                                   # was in another school last year
                previous = {'student': member['student'], 'ability': member['ability'] - rng.uniform(-1.0, 2.0), 'status': 'Enrolled'}
                previous['enrollment'] = Enrollment(
                    student=member['student'], section=section, school_year=self.prev_sy,
                    grade_level_at_entry=self.levels[grade], enrollment_date=date(2025, 5, rng.randint(19, 30)),
                    enrollment_type='New' if grade in (7, 11) else 'Continuing', status='Enrolled', created_by=self.registrar,
                )
                prev_enrollments.append(previous['enrollment'])
                members.append(previous)
            Section.objects.filter(pk=section.pk).update(current_enrollment_count=len(members))
            self.prev_sections.append({'section': section, 'grade': grade, 'strand': template[2], 'offset': entry['offset'],
                                       'members': members, 'subjects': self.section_subjects(grade, template[2])})
        Enrollment.objects.bulk_create(prev_enrollments, batch_size=500)
        self.totals['sections'] = f'{len(self.sections)} this year, {len(self.prev_sections)} last year'
        self.totals['enrolments'] = len(enrollments) + len(prev_enrollments)

    # ---------------------------------------------------------------- classes
    def classes(self):
        assignments = []
        self.class_of = {}        # (section pk, subject code) -> ClassAssignment
        for entry in self.sections:
            for code in entry['subjects']:
                _, teacher, meetings, _ = self.subject_meta[code]
                assignment = ClassAssignment(
                    teacher=self.staff[teacher], section=entry['section'], subject=self.subjects[code], school_year=self.sy,
                    is_advisory=entry['section'].adviser_id == self.staff[teacher].id, is_active=True,
                    max_students=35, minutes_per_meeting=60, meetings_per_week=meetings, created_by=self.registrar,
                )
                assignments.append(assignment)
                self.class_of[(entry['section'].pk, code)] = assignment
        ClassAssignment.objects.bulk_create(assignments, batch_size=500)
        self.totals['classes'] = len(assignments)

    # ---------------------------------------------------------------- grades
    def _grade(self, member, entry, code, quarter_number):
        family = self.subject_meta[code][0]
        value = (member['ability'] + entry['offset'] + self.family_offset[family]
                 + 0.4 * (quarter_number - 1) + self.rng.gauss(0, 2.4))
        return int(max(62, min(99, round(value))))

    def _component(self, member, code, quarter, grade, teacher, status, note='', when=None):
        rng = self.rng
        ww = max(50, min(100, grade + rng.randint(-4, 4)))
        pt = max(50, min(100, grade + rng.randint(-3, 5)))
        qa = max(50, min(100, grade + rng.randint(-6, 3)))
        locked = status == 'Finalized'
        checked = status in ('Validated', 'Finalized', 'Returned')
        return GradeComponent(
            enrollment=member['enrollment'], subject=self.subjects[code], quarter=quarter,
            written_work_raw=Decimal(ww), written_work_max=Decimal(100), written_work_percent=Decimal(ww),
            written_work_weighted=Decimal(ww) * Decimal('0.30'),
            performance_task_raw=Decimal(pt), performance_task_max=Decimal(100), performance_task_percent=Decimal(pt),
            performance_task_weighted=Decimal(pt) * Decimal('0.50'),
            quarterly_assessment_raw=Decimal(qa), quarterly_assessment_max=Decimal(100), quarterly_assessment_percent=Decimal(qa),
            quarterly_assessment_weighted=Decimal(qa) * Decimal('0.20'),
            initial_grade=Decimal(grade), transmuted_grade=grade, descriptor=_descriptor(grade),
            encoded_by=teacher, validation_status=status,
            validated_by=self.registrar if checked else None, validation_date=when if checked else None,
            validation_notes=note, is_locked=locked, locked_by=self.registrar if locked else None,
            locked_at=when if locked else None,
        )

    def grades(self):
        rows = []
        # last year: every quarter complete and finalised
        for entry in self.prev_sections:
            for code in entry['subjects']:
                teacher = self.staff[self.subject_meta[code][1]]
                for quarter in self.prev_quarters:
                    when = _aware(quarter.date_end + timedelta(days=12))
                    for member in entry['members']:
                        rows.append(self._component(member, code, quarter, self._grade(member, entry, code, quarter.quarter_number),
                                                    teacher, 'Finalized', when=when))
        # this year: first quarter finalised; second quarter in progress, class by class
        q1, q2 = self.quarters[0], self.quarters[1]
        self.q2_state = {}
        index = 0
        for entry in self.sections:
            active = [m for m in entry['members'] if m['status'] in ACTIVE]
            for code in entry['subjects']:
                teacher = self.staff[self.subject_meta[code][1]]
                when = _aware(q1.date_end + timedelta(days=11))
                for member in entry['members']:               # students who dropped later still have first-quarter grades
                    rows.append(self._component(member, code, q1, self._grade(member, entry, code, 1), teacher, 'Finalized', when=when))

                state = Q2_STATES[index % len(Q2_STATES)]
                index += 1
                self.q2_state[(entry['section'].pk, code)] = state
                if state == 'not_started':
                    continue
                graded = active if state != 'incomplete' else active[:max(3, int(len(active) * self.rng.uniform(0.45, 0.8)))]
                status = {'validated': 'Validated', 'ready': 'Draft', 'incomplete': 'Draft', 'returned': 'Returned'}[state]
                note = 'Two students have grades far below their first quarter. Please re-check the class record and re-upload.' if state == 'returned' else ''
                when = timezone.now() - timedelta(days=self.rng.randint(1, 6))
                for member in graded:
                    rows.append(self._component(member, code, q2, self._grade(member, entry, code, 2), teacher, status, note=note, when=when))
        GradeComponent.objects.bulk_create(rows, batch_size=1000)
        self.totals['grades'] = len(rows)

    # ---------------------------------------------------------------- attendance and promotion
    def attendance(self):
        rng = self.rng
        rows = []

        def add(entries, sy, months):
            for entry in entries:
                for member in entry['members']:
                    if member['status'] not in ACTIVE:
                        continue
                    careless = member['ability'] < 74                 # struggling students miss more days
                    for month, days in months:
                        absent = min(days, rng.choice([0, 0, 0, 1, 1, 2]) + (rng.randint(1, 4) if careless else 0))
                        rate = Decimal(absent * 100) / Decimal(days)
                        rows.append(AttendanceSummary(
                            enrollment=member['enrollment'], school_year=sy, month=month, total_school_days=days,
                            days_present=days - absent, days_absent=absent, days_late=rng.choice([0, 0, 1, 2]),
                            days_excused=min(absent, rng.choice([0, 0, 1])), absence_rate_percent=rate.quantize(Decimal('0.01')),
                            is_at_risk=rate >= 20, consecutive_absences=min(absent, 3) if careless else 0,
                        ))

        add(self.prev_sections, self.prev_sy, [(6, 11), (7, 23), (8, 20), (9, 22), (10, 22), (11, 19), (12, 14), (1, 20), (2, 20), (3, 21)])
        add(self.sections, self.sy, [(6, 17), (7, 23), (8, 21), (9, 22)])
        AttendanceSummary.objects.bulk_create(rows, batch_size=1000)
        self.totals['attendance months'] = len(rows)

    def promotions(self):
        rows = []
        for entry in self.prev_sections:
            for member in entry['members']:
                ability = member['ability'] + entry['offset']
                failed = 0 if ability >= 76 else (1 if ability >= 72 else 3)
                total = len(entry['subjects'])
                decision = 'Promoted' if failed == 0 else ('Conditionally_Promoted' if failed <= 2 else 'Retained')
                # everyone here did move up a grade, so a "Retained" case is recorded as conditionally promoted after remediation
                decision = 'Conditionally_Promoted' if decision == 'Retained' else decision
                rows.append(PromotionRecommendation(
                    enrollment=member['enrollment'], recommendation=decision, recommended_by=entry['section'].adviser,
                    recommendation_date=date(2026, 4, 6), total_subjects=total, subjects_passed=total - failed,
                    subjects_failed=failed, general_average=Decimal(str(round(max(70.0, min(98.0, ability)), 2))),
                    remedial_required=failed > 0, remedial_completed=failed > 0, final_decision=decision, status='Finalized',
                    reviewed_by=self.registrar, approved_by=self.staff['head1'],
                ))
        PromotionRecommendation.objects.bulk_create(rows, batch_size=500)
        self.totals['promotion records'] = len(rows)

    # ---------------------------------------------------------------- quizzes for the showcase teacher
    def assessments(self):
        teacher = self.staff['math_a']
        section = self.sections[0]
        samples = [
            ('Quiz 1: Integers and Absolute Value', 'closed', self.quarters[0], [
                ('What is the absolute value of -12?', ['-12', '0', '12', '24'], 2),
                ('Which is greater: -3 or -8?', ['-3', '-8', 'They are equal', 'Cannot be compared'], 0),
                ('Evaluate: -7 + 15', ['-22', '-8', '8', '22'], 2),
                ('Evaluate: (-4)(-6)', ['-24', '-10', '10', '24'], 3),
                ('Which number is an integer?', ['2.5', '-9', '1/2', '0.75'], 1),
            ]),
            ('Quiz 2: Algebraic Expressions', 'published', self.quarters[1], [
                ('Simplify: 3x + 5x', ['8x', '15x', '8x^2', '2x'], 0),
                ('What is the coefficient of 7y?', ['y', '7', '7y', '1'], 1),
                ('Evaluate 2a + 3 when a = 4', ['9', '10', '11', '14'], 2),
                ('Which is a like term of 4m?', ['4n', 'm^2', '-9m', '4'], 2),
                ('Translate: "five more than a number n"', ['5n', 'n - 5', 'n + 5', '5 - n'], 2),
            ]),
            ('Long Test: Linear Equations (draft)', 'draft', self.quarters[1], [
                ('Solve: x + 9 = 15', ['4', '6', '24', '-6'], 1),
                ('Solve: 3x = 27', ['9', '24', '30', '81'], 0),
                ('Solve: 2x - 5 = 11', ['3', '6', '8', '16'], 2),
            ]),
        ]
        made = 0
        for title, status, quarter, questions in samples:
            assessment = Assessment.objects.create(
                teacher=teacher, subject=self.subjects['MATH7'], section=section['section'], school_year=self.sy,
                quarter=quarter, title=title, description='Demo assessment.', total_items=len(questions),
                passing_score=Decimal('60'), time_limit_minutes=20, status=status,
                access_code='DM' + secrets.token_hex(3).upper(),
            )
            AssessmentQuestion.objects.bulk_create([
                AssessmentQuestion(assessment=assessment, question_text=text, order_number=n, correct_answer_index=answer,
                                   choices=choices, num_choices=len(choices))
                for n, (text, choices, answer) in enumerate(questions, 1)
            ])
            if status != 'draft':
                takers = section['members'] if status == 'closed' else section['members'][:19]
                responses = []
                for member in takers:
                    if member['status'] not in ACTIVE:
                        continue
                    correct = max(0, min(len(questions), round(len(questions) * (member['ability'] - 55) / 42 + self.rng.uniform(-0.8, 0.8))))
                    student = member['student']
                    responses.append(AssessmentResponse(
                        assessment=assessment, student=student, student_name=f'{student.first_name} {student.last_name}',
                        score=Decimal(correct), total_points=Decimal(len(questions)),
                        passed=correct * 100 >= len(questions) * 60, submitted_at=timezone.now() - timedelta(days=self.rng.randint(1, 30)),
                    ))
                AssessmentResponse.objects.bulk_create(responses)
            made += 1
        self.totals['quizzes'] = made

    def build(self):
        self.structure()
        self.accounts()
        self.calendar()
        self.people()
        self.classes()
        self.grades()
        self.attendance()
        self.promotions()
        self.assessments()


class Command(BaseCommand):
    help = 'Create (or remove) the self-contained ARMS demo school used for screenshots and design work.'

    def add_arguments(self, parser):
        parser.add_argument('--remove', action='store_true', help='Remove the demo school and all of its data.')
        parser.add_argument('--reset', action='store_true', help='Remove the demo school first, then create it again.')
        parser.add_argument('--dry-run', action='store_true', help='Run everything, report, then undo it.')

    def handle(self, *args, **options):
        exists = School.objects.filter(school_id=SCHOOL_ID).exists()

        if options['remove']:
            with transaction.atomic():
                removed = remove_demo()
                if options['dry_run']:
                    transaction.set_rollback(True)
            self._refresh_caches()
            self.stdout.write(self.style.SUCCESS('Demo data removed: ' + (', '.join(f'{v} {k}' for k, v in removed.items() if v) or 'nothing was there')))
            return

        if exists and not options['reset']:
            raise CommandError('The demo school already exists. Use --reset to rebuild it or --remove to delete it.')

        password, created = demo_password()
        with transaction.atomic():
            if exists:
                remove_demo()
            seeder = Seeder(password, self.stdout)
            seeder.build()
            if options['dry_run']:
                transaction.set_rollback(True)
        self._refresh_caches()

        self.stdout.write(self.style.SUCCESS(
            ('DRY RUN (nothing was saved) — ' if options['dry_run'] else '') + 'ARMS Demo National High School is ready.'))
        for name, value in seeder.totals.items():
            self.stdout.write(f'  {name}: {value}')
        self.stdout.write('\nSign in with these demo accounts (they skip the Google-link step):')
        for role, user in seeder.showcase:
            self.stdout.write(f'  {role:<12} {user.username}')
        self.stdout.write('Password: the DEMO_PASSWORD value in your .env file'
                          + (' (just created there).' if created else '.'))
        self.stdout.write('Remove everything again with: python manage.py seed_demo --remove')

    @staticmethod
    def _refresh_caches():
        try:
            from core.caching import bump_data_version
            bump_data_version()
        except Exception:
            pass
