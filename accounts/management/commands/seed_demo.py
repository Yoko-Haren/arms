"""Demo data for screenshots and design work: self-contained demo schools, one per grading system.

    python manage.py seed_demo            create the quarterly demo school (refuses if it already exists)
    python manage.py seed_demo --reset    remove it first, then create it again
    python manage.py seed_demo --remove   remove the demo school and everything that belongs to it
    python manage.py seed_demo --dry-run  do everything, show the totals, then undo it
    python manage.py seed_demo --spread-levels   move each discipline of an existing demo school onto its level
                                                 (its level targets), so the dashboard shows every level
    python manage.py seed_demo --trimestral ...  the same for the trimestral demo school (any option above)

Two schools, each with every role:
- ARMS Demo National High School (DEMO-ARMS, @demo.arms.edu.ph, learners 9999...): four quarters,
  DepEd Order No. 8, s. 2015 grading (the School Head may switch it to DO 015 on the School Year page).
- ARMS Demo Three-Term High School (DEMO-TERM, @term.demo.arms.edu.ph, learners 9998...): last school
  year in four quarters, this one in the three terms of DepEd Order No. 009, s. 2026, graded under
  DepEd Order No. 015, s. 2026. Grade 11 follows the Strengthened SHS curriculum (Academic and
  Technical-Professional tracks); Grade 12 finishes the earlier one.

Nothing outside the chosen demo school is read or changed. All demo accounts share one password, kept in
.env as DEMO_PASSWORD (never printed).
"""
import random
import secrets
from datetime import date, datetime, time, timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import Group, User
from django.core.management.base import BaseCommand, CommandError
from django.db import models, transaction
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

# ============================================================================= the quarterly demo school
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

FAMILIES = [
    # code, name, colour, icon, grade offset (how hard the discipline tends to be; see LEVEL_TARGETS)
    ('MATH', 'Mathematics', '#123499', 'fi fi-rr-calculator', -14.0),
    ('SCI', 'Science', '#1565C0', 'fi fi-rr-flask', 9.5),
    ('ENG', 'English', '#6A1B9A', 'fi fi-rr-book-alt', -7.0),
    ('FIL', 'Filipino', '#E65100', 'fi fi-rr-comment-alt', -1.8),
    ('AP', 'Araling Panlipunan', '#2D6AFF', 'fi fi-rr-globe', -0.6),
    ('MAPEH', 'MAPEH', '#C62828', 'fi fi-rr-music-alt', 8.2),
    ('TLE', 'Technology and Livelihood Education', '#4a6fd4', 'fi fi-rr-tools', 3.7),
    ('ESP', 'Edukasyon sa Pagpapakatao', '#764ba2', 'fi fi-rr-heart', 4.8),
    ('HUMSS', 'Humanities and Social Sciences', '#667eea', 'fi fi-rr-users-alt', -22.5),
]
# Each discipline's average in the current school year: at least one discipline on every level of both DepEd orders,
# so the School Head's dashboard and Poro's recommendations show the whole range.
#   DepEd Order No. 015, s. 2026: Emerging (HUMSS), Developing (Mathematics), Connecting (English),
#                                 Benchmarking (Filipino, AP, TLE, EsP), Advancing (MAPEH, Science)
#   DepEd Order No. 8, s. 2015:   Did Not Meet Expectations (HUMSS, Mathematics), Fairly Satisfactory (English),
#                                 Satisfactory (Filipino, AP), Very Satisfactory (TLE, EsP), Outstanding (MAPEH, Science)
# HUMSS is the lowest because only the HUMSS strand takes it, so the rest of the school can still reach honors.
LEVEL_TARGETS = {'HUMSS': 62.0, 'MATH': 70.5, 'ENG': 77.0, 'FIL': 82.0, 'AP': 83.0, 'TLE': 86.5, 'ESP': 88.0,
                 'MAPEH': 92.0, 'SCI': 94.0}
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
# Senior high: (code, name, family, grade, group, teacher, meetings/week). A section takes the subjects of its groups:
# None is the core every strand of the earlier curriculum takes, a strand code its specialized subjects.
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
# How far along each class is in the current (second) period, repeated over the classes: validated; submitted
# by the teacher and waiting for the registrar; complete but not submitted (drafts); encoding; returned; not started.
Q2_STATES = (['validated'] * 9 + ['submitted'] * 3 + ['ready'] + ['incomplete'] * 3 + ['returned'] + ['not_started'] * 3)

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

# DepEd Order No. 8, s. 2015: written work, performance tasks, quarterly assessment (the demo uses the languages' split)
DO8_WEIGHTS = (Decimal('0.30'), Decimal('0.50'), Decimal('0.20'))
# DepEd Order No. 015, s. 2026, Grades 4 to 10 and Senior High core: written/oral works, product/performance tasks,
# examinations; MAPEH and EPP/TLE (and TechPro electives, close enough for a demo) weigh performance more
DO15_WEIGHTS = (Decimal('0.20'), Decimal('0.50'), Decimal('0.30'))
DO15_WEIGHTS_MAPEH_TLE = (Decimal('0.20'), Decimal('0.60'), Decimal('0.20'))


class Profile:
    """Everything that makes one demo school: its people, curriculum, calendar and grading system."""

    def __init__(self, **values):
        self.__dict__.update(values)

    def weights(self, family):
        if self.grading_policy == 'DO15_2026':
            return DO15_WEIGHTS_MAPEH_TLE if family in ('MAPEH', 'TLE') else DO15_WEIGHTS
        return DO8_WEIGHTS

    def groups(self, grade, strand, current):
        """The subject groups a Senior High section takes in a school year."""
        return self.shs_groups(grade, strand, current) if self.shs_groups else (None, strand)


def _quarters(*spans):
    return [(start, end, current, locked) for start, end, current, locked in spans]


QUARTERLY = Profile(
    key='quarterly', school_id=SCHOOL_ID, domain=DOMAIN, lrn_prefix=LRN_PREFIX, seed=20261009,
    school_name='ARMS Demo National High School', short_name='ADNHS', address='Demo Avenue, Davao City',
    contact='(082) 555-0100', period_type='QUARTERLY', grading_policy=None,
    heads=HEADS, registrars=REGISTRARS, teachers=TEACHERS, new_teacher=NEW_TEACHER, inactive_teacher=INACTIVE_TEACHER,
    families=FAMILIES, level_targets=LEVEL_TARGETS, jhs_subjects=JHS_SUBJECTS, shs_subjects=SHS_SUBJECTS,
    sections=SECTIONS, shs_groups=None,
    tracks={'ACADEMIC': 'Academic Track'},
    strands={'STEM': ('ACADEMIC', 'Science, Technology, Engineering and Mathematics'),
             'HUMSS': ('ACADEMIC', 'Humanities and Social Sciences')},
    years=[
        ('2025-2026', date(2025, 6, 16), date(2026, 3, 31), False, 'Q', _quarters(
            (date(2025, 6, 16), date(2025, 8, 22), False, True), (date(2025, 8, 25), date(2025, 10, 31), False, True),
            (date(2025, 11, 3), date(2026, 1, 23), False, True), (date(2026, 1, 26), date(2026, 3, 31), False, True))),
        ('2026-2027', date(2026, 6, 8), date(2027, 4, 8), True, 'Q', _quarters(
            (date(2026, 6, 8), date(2026, 8, 21), False, True), (date(2026, 8, 24), date(2026, 11, 6), True, False),
            (date(2026, 11, 9), date(2027, 1, 29), False, False), (date(2027, 2, 1), date(2027, 4, 8), False, False))),
    ],
    states=Q2_STATES, months_now=[(6, 17), (7, 23), (8, 21), (9, 22)],
    quiz_teacher='math_a', quiz_subject='MATH7',
)

# ============================================================================= the trimestral demo school
TERM_HEADS = [('Victoria', 'Salcedo', 'Principal II', True)]
TERM_REGISTRARS = [('Ramon', 'Jacinto', 'School Registrar', True)]
TERM_TEACHERS = [
    ('math', 'Grace', 'Manalo', 'Teacher III', 'Mathematics', True),
    ('sci', 'Noel', 'Sarmiento', 'Teacher II', 'Science', False),
    ('eng', 'Lorna', 'Bernardo', 'Teacher II', 'English', False),
    ('fil', 'Dante', 'Lacsamana', 'Teacher III', 'Filipino', False),
    ('ap', 'Mylene', 'Cortez', 'Teacher I', 'Araling Panlipunan and Values Education', False),
    ('mapeh', 'Rommel', 'Ilagan', 'Teacher II', 'MAPEH and TLE', False),
    ('shs', 'Arnel', 'Pineda', 'Master Teacher I', 'Mathematics and Science (SHS)', True),
    ('shs_lang', 'Cecilia', 'Montero', 'Teacher III', 'Languages and Humanities (SHS)', False),
    ('shs_tech', 'Edgardo', 'Villamor', 'Teacher II', 'TechPro and PE (SHS)', False),
]
# where each discipline of this school lands this year: every level of DepEd Order No. 015, s. 2026, arranged
# differently from the quarterly demo
TERM_LEVEL_TARGETS = {'HUMSS': 63.0, 'MATH': 71.5, 'FIL': 77.5, 'ENG': 82.0, 'SCI': 84.5, 'AP': 86.0, 'ESP': 87.5,
                      'MAPEH': 91.0, 'TLE': 93.0}
TERM_FAMILIES = [(code, name, colour, icon, TERM_LEVEL_TARGETS[code] - 83.5) for code, name, colour, icon, _ in FAMILIES]
# MATATAG Junior High: Values Education in place of EsP, MAPEH graded as Music and Arts with PE and Health
TERM_JHS_SUBJECTS = [
    ('FIL', 'Filipino', 'FIL', ('fil', 'fil'), 4),
    ('ENG', 'English', 'ENG', ('eng', 'eng'), 4),
    ('MATH', 'Mathematics', 'MATH', ('math', 'math'), 4),
    ('SCI', 'Science', 'SCI', ('sci', 'sci'), 4),
    ('AP', 'Araling Panlipunan', 'AP', ('ap', 'ap'), 3),
    ('MAPEH', 'MAPEH', 'MAPEH', ('mapeh', 'mapeh'), 4),
    ('TLE', 'Technology and Livelihood Education', 'TLE', ('mapeh', 'mapeh'), 4),
    ('VE', 'Values Education', 'ESP', ('ap', 'ap'), 2),
]
TERM_SHS_SUBJECTS = [
    # Grade 11, Strengthened SHS curriculum: five core subjects all year ('SSHS'), then the track electives
    ('EFFCOM11', 'Effective Communication', 'ENG', 11, 'SSHS', 'shs_lang', 4),
    ('MABKOM11', 'Mabisang Komunikasyon', 'FIL', 11, 'SSHS', 'shs_lang', 4),
    ('GENMATH11', 'General Mathematics', 'MATH', 11, 'SSHS', 'shs', 4),
    ('GENSCI11', 'General Science', 'SCI', 11, 'SSHS', 'shs', 4),
    ('PKLP11', 'Pag-aaral ng Kasaysayan at Lipunang Pilipino', 'AP', 11, 'SSHS', 'shs_lang', 3),
    ('LCS11', 'Life and Career Skills', 'ESP', 11, 'SSHS', 'shs_tech', 2),
    ('PRECAL11', 'Pre-Calculus', 'MATH', 11, 'ACAD', 'shs', 4),
    ('BIO11', 'Biology 1', 'SCI', 11, 'ACAD', 'shs', 4),
    ('CSS11', 'Computer Systems Servicing (CSS) NC II', 'TLE', 11, 'TECHPRO', 'shs_tech', 4),
    ('EIM11', 'Electrical Installation and Maintenance (EIM) NC II', 'TLE', 11, 'TECHPRO', 'shs_tech', 4),
    # Grade 11 of the earlier curriculum, taken last school year by this year's Grade 12
    ('ORALCOM11', 'Oral Communication', 'ENG', 11, None, 'shs_lang', 4),
    ('KOMPAN11', 'Komunikasyon at Pananaliksik', 'FIL', 11, None, 'shs_lang', 4),
    ('GMATH11', 'General Mathematics (2016 curriculum)', 'MATH', 11, None, 'shs', 4),
    ('ELS11', 'Earth and Life Science', 'SCI', 11, None, 'shs', 4),
    ('PEH11', 'Physical Education and Health 1', 'MAPEH', 11, None, 'shs_tech', 2),
    ('PERDEV11', 'Personal Development', 'ESP', 11, None, 'shs_tech', 2),
    ('GENBIO11', 'General Biology 1', 'SCI', 11, 'STEM', 'shs', 4),
    ('DISS11', 'Disciplines and Ideas in the Social Sciences', 'HUMSS', 11, 'HUMSS', 'shs_lang', 4),
    # Grade 12, finishing the earlier curriculum in the three-term calendar
    ('LIT12', '21st Century Literature', 'ENG', 12, None, 'shs_lang', 4),
    ('STAT12', 'Statistics and Probability', 'MATH', 12, None, 'shs', 4),
    ('PHYSCI12', 'Physical Science', 'SCI', 12, None, 'shs', 4),
    ('PEH12', 'Physical Education and Health 3', 'MAPEH', 12, None, 'shs_tech', 2),
    ('UCSP12', 'Understanding Culture, Society and Politics', 'AP', 12, None, 'shs_lang', 4),
    ('BASCAL12', 'Basic Calculus', 'MATH', 12, 'STEM', 'shs', 4),
    ('CREWRI12', 'Creative Writing', 'HUMSS', 12, 'HUMSS', 'shs_lang', 4),
    ('PPG12', 'Philippine Politics and Governance', 'HUMSS', 12, 'HUMSS', 'shs_lang', 4),
]
TERM_SECTIONS = [
    (7, 'Amihan', None, 'math', 30, 1.5), (8, 'Habagat', None, 'sci', 29, -1.0),
    (9, 'Bagwis', None, 'eng', 28, 1.0), (10, 'Dalisay', None, 'fil', 30, -1.5),
    (11, 'Academic-A', 'ACAD', 'shs', 26, 2.5), (11, 'TechPro-A', 'TECHPRO', 'shs_tech', 24, -0.5),
    (12, 'STEM-A', 'STEM', 'shs_lang', 25, 3.0), (12, 'HUMSS-A', 'HUMSS', 'ap', 23, 0.0),
]


def _term_groups(grade, strand, current):
    """This year's Grade 11 takes the strengthened core and its track's electives; everyone else the earlier curriculum."""
    return ('SSHS', strand) if grade == 11 and current else (None, strand)


TERMS = Profile(
    key='trimestral', school_id='DEMO-TERM', domain='term.demo.arms.edu.ph', lrn_prefix='9998', seed=20261028,
    school_name='ARMS Demo Three-Term High School', short_name='ADTHS', address='Demo Avenue, Panabo City',
    contact='(084) 555-0130', period_type='TRIMESTRAL', grading_policy='DO15_2026',
    heads=TERM_HEADS, registrars=TERM_REGISTRARS, teachers=TERM_TEACHERS, new_teacher=None, inactive_teacher=None,
    families=TERM_FAMILIES, level_targets=TERM_LEVEL_TARGETS, jhs_subjects=TERM_JHS_SUBJECTS, shs_subjects=TERM_SHS_SUBJECTS,
    sections=TERM_SECTIONS, shs_groups=_term_groups,
    tracks={'ACADEMIC': 'Academic Track', 'TECHPRO': 'Technical-Professional Track'},
    strands={'STEM': ('ACADEMIC', 'Science, Technology, Engineering and Mathematics'),
             'HUMSS': ('ACADEMIC', 'Humanities and Social Sciences'),
             'ACAD': ('ACADEMIC', 'Academic Track (Strengthened SHS)'),
             'TECHPRO': ('TECHPRO', 'Technical-Professional Track (Strengthened SHS)')},
    years=[
        # last school year in four quarters; this one in the three terms of DepEd Order No. 009, s. 2026
        ('2025-2026', date(2025, 6, 16), date(2026, 3, 31), False, 'Q', _quarters(
            (date(2025, 6, 16), date(2025, 8, 22), False, True), (date(2025, 8, 25), date(2025, 10, 31), False, True),
            (date(2025, 11, 3), date(2026, 1, 23), False, True), (date(2026, 1, 26), date(2026, 3, 31), False, True))),
        ('2026-2027', date(2026, 6, 8), date(2027, 4, 8), True, 'T', _quarters(
            (date(2026, 6, 8), date(2026, 9, 15), False, True), (date(2026, 9, 16), date(2026, 12, 18), True, False),
            (date(2027, 1, 4), date(2027, 4, 8), False, False))),
    ],
    states=Q2_STATES, months_now=[(6, 17), (7, 23), (8, 21), (9, 22), (10, 20)],
    quiz_teacher='math', quiz_subject='MATH7',
)
PROFILES = {'quarterly': QUARTERLY, 'trimestral': TERMS}


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
def remove_demo(profile=QUARTERLY):
    """Delete one demo school and every record that belongs to it. Returns what was removed."""
    removed = {}
    school = School.objects.filter(school_id=profile.school_id).first()
    users = User.objects.filter(username__endswith='@' + profile.domain)
    if school:
        removed['grades'] = GradeComponent.objects.filter(enrollment__section__school=school).delete()[0]
        Assessment.objects.filter(school_year__school=school).delete()
        removed['enrollments'] = Enrollment.objects.filter(section__school=school).count()
        Enrollment.objects.filter(section__school=school).delete()        # attendance, promotions, history go with it
        ClassAssignment.objects.filter(section__school=school).delete()
        Section.objects.filter(school=school).delete()
        Subject.objects.filter(school=school).delete()
    removed['students'] = Student.objects.filter(lrn__startswith=profile.lrn_prefix).count()
    Student.objects.filter(lrn__startswith=profile.lrn_prefix).delete()
    PasswordReset.objects.filter(user__in=users).delete()
    removed['accounts'] = users.count()
    users.delete()
    if school:
        school.delete()                                                    # school years, quarters, grade levels, tracks
        removed['school'] = 1
    return removed


# ============================================================================= levels of an existing demo school
def spread_levels(log=print, profile=QUARTERLY):
    """Move each discipline of an existing demo school so its current-year average lands on its level target.

    Every grade of the discipline (both school years) moves by the same whole number of points, so trends, the change
    since last period and each learner's place in the class stay as they were; the written work, performance task
    and assessment scores, the initial grade and the descriptor move with it. Only seeded learners change (LRNs
    <prefix>0000...), never a learner the user imported. Returns {family code: (average before, average after)}.
    """
    school = School.objects.get(school_id=profile.school_id)
    current = SchoolYear.objects.get(school=school, is_current=True)
    seeded = GradeComponent.objects.filter(enrollment__section__school=school, enrollment__student__lrn__startswith=profile.lrn_prefix + '0000',
                                           transmuted_grade__isnull=False)
    clip = lambda value, low, high: max(low, min(high, value))
    result = {}
    for code, target in profile.level_targets.items():
        family = seeded.filter(subject__subject_family__family_code=code)
        mean_now = lambda: family.filter(quarter__school_year=current).aggregate(a=models.Avg('transmuted_grade'))['a']
        before = mean_now()
        if before is None:
            continue
        weights = profile.weights(code)
        for _ in range(3):                                   # a grade that hits 60 or 100 stops moving: correct again
            step = round(target - mean_now())
            if not step:
                break
            rows = list(family)
            for g in rows:
                grade = clip(g.transmuted_grade + step, 60, 100)
                moved = grade - g.transmuted_grade
                for part, weight in zip(('written_work', 'performance_task', 'quarterly_assessment'), weights):
                    value = Decimal(clip(float(getattr(g, f'{part}_percent') or grade) + moved, 0, 100))
                    setattr(g, f'{part}_raw', value)
                    setattr(g, f'{part}_percent', value)
                    setattr(g, f'{part}_weighted', value * weight)
                g.transmuted_grade, g.initial_grade, g.descriptor = grade, Decimal(grade), _descriptor(grade)
            GradeComponent.objects.bulk_update(rows, [
                'written_work_raw', 'written_work_percent', 'written_work_weighted',
                'performance_task_raw', 'performance_task_percent', 'performance_task_weighted',
                'quarterly_assessment_raw', 'quarterly_assessment_percent', 'quarterly_assessment_weighted',
                'initial_grade', 'transmuted_grade', 'descriptor'], batch_size=500)
        result[code] = (float(before), float(mean_now()))
        log(f'  {code:6} {result[code][0]:5.1f} -> {result[code][1]:5.1f} (target {target})')
    return result


# ============================================================================= seeding
class Seeder:
    def __init__(self, password, out, profile=QUARTERLY):
        self.p = profile
        self.rng = random.Random(profile.seed)
        self.password_hash = make_password(password)
        self.out = out
        self.staff = {}          # key -> User
        self.totals = {}

    # ---------------------------------------------------------------- accounts
    def _account(self, first, last, role, designation, area='', linked=False, temporary=False, active=True, number=''):
        username = f'{first}.{last}'.lower().replace(' ', '') + '@' + self.p.domain
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
        tag = 'DEMO' if self.p is QUARTERLY else 'DEMOT'
        self.groups = {
            'schoolhead': Group.objects.get_or_create(name='Principal')[0],
            'registrar': Group.objects.get_or_create(name='Registrar')[0],
            'teacher': Group.objects.get_or_create(name='Teacher')[0],
        }
        self.showcase = []
        for i, (first, last, designation, show) in enumerate(self.p.heads, 1):
            user = self._account(first, last, 'schoolhead', designation, 'Administration', linked=True, number=f'{tag}-H-{i:03d}')
            self.staff[f'head{i}'] = user
            if show:
                self.showcase.append(('School Head', user))
        for i, (first, last, designation, show) in enumerate(self.p.registrars, 1):
            user = self._account(first, last, 'registrar', designation, 'Records', linked=show, temporary=not show, number=f'{tag}-R-{i:03d}')
            self.staff[f'registrar{i}'] = user
            if show:
                self.showcase.append(('Registrar', user))
        for i, (key, first, last, position, area, show) in enumerate(self.p.teachers, 1):
            linked = show or i % 3 != 0            # most teachers linked, some still password-only
            user = self._account(first, last, 'teacher', position, area, linked=linked, number=f'{tag}-T-{i:03d}')
            self.staff[key] = user
            if show:
                self.showcase.append(('Teacher', user))
        if self.p.new_teacher:
            first, last, position, area = self.p.new_teacher
            self.staff['new'] = self._account(first, last, 'teacher', position, area, temporary=True, number=f'{tag}-T-098')
        if self.p.inactive_teacher:
            first, last, position, area = self.p.inactive_teacher
            self.staff['inactive'] = self._account(first, last, 'teacher', position, area, linked=True, active=False, number=f'{tag}-T-099')
        self.registrar = self.staff['registrar1']
        self.totals['accounts'] = len(self.staff)

    # ---------------------------------------------------------------- school structure
    def structure(self):
        from admin_panel.forms import SchoolForm
        from academics.school_years import PERIOD_CONFIG

        self.school = School.objects.create(
            school_id=self.p.school_id, school_name=self.p.school_name, short_name=self.p.short_name,
            address=self.p.address, contact_number=self.p.contact, email_domain='@' + self.p.domain,
            grading_scale='PERCENTAGE', passing_grade=75.0, period_type=self.p.period_type,
            quarters_count=PERIOD_CONFIG[self.p.period_type]['count'],
        )
        if self.p.grading_policy:
            School.objects.filter(pk=self.school.pk).update(grading_policy=self.p.grading_policy)
            self.school.grading_policy = self.p.grading_policy
        SchoolForm._create_default_schema(None, self.school, 'DEPED_INTEGRATED')

        self.levels = {}
        for n in range(7, 13):
            self.levels[n] = GradeLevel.objects.create(
                school=self.school, grade_code=f'G{n}', grade_name=f'Grade {n}', grade_number=n,
                level_category='SHS' if n >= 11 else 'JHS', is_senior_high=n >= 11, sort_order=n,
            )

        tracks = {code: Track.objects.create(school=self.school, track_code=code, track_name=name)
                  for code, name in self.p.tracks.items()}
        self.strands = {code: Strand.objects.create(track=tracks[track], strand_code=code, strand_name=name)
                        for code, (track, name) in self.p.strands.items()}

        self.family_offset = {}
        families = {}
        for order, (code, name, colour, icon, offset) in enumerate(self.p.families, 1):
            families[code] = SubjectFamily.objects.create(
                school=self.school, family_code=code, family_name=name, color_hex=colour, icon_class=icon, sort_order=order,
            )
            self.family_offset[code] = offset

        # subjects, with who teaches them and how often they meet
        self.subjects = {}          # code -> Subject
        self.subject_meta = {}      # code -> (family, teacher key(s), meetings/week, group)
        for n in range(7, 11):
            for suffix, name, family, teachers, meetings in self.p.jhs_subjects:
                code = f'{suffix}{n}'
                self.subjects[code] = Subject.objects.create(
                    school=self.school, subject_code=code, subject_name=f'{name} {n}', subject_category='Core',
                    grade_level=self.levels[n], subject_family=families[family], hours_per_week=Decimal(meetings),
                )
                self.subject_meta[code] = (family, teachers[0] if n <= 8 else teachers[1], meetings, None)
        for code, name, family, grade, group, teacher, meetings in self.p.shs_subjects:
            specialized = group not in (None, 'SSHS')
            self.subjects[code] = Subject.objects.create(
                school=self.school, subject_code=code, subject_name=name,
                subject_category='Specialized' if specialized else 'Core', grade_level=self.levels[grade],
                subject_family=families[family], strand=self.strands.get(group) if specialized else None,
                hours_per_week=Decimal(meetings),
            )
            self.subject_meta[code] = (family, teacher, meetings, group)
        self.totals['subjects'] = len(self.subjects)

    def section_subjects(self, grade, strand, current=True):
        """Subject codes a section takes."""
        if grade <= 10:
            return [f'{suffix}{grade}' for suffix, *_ in self.p.jhs_subjects]
        groups = self.p.groups(grade, strand, current)
        return [code for code, _, _, g, group, _, _ in self.p.shs_subjects if g == grade and group in groups]

    def calendar(self):
        def make_year(label, start, end, current, prefix, periods):
            sy = SchoolYear.objects.create(
                school=self.school, year_label=label, year_start=start.year, year_end=start.year + 1,
                date_start=start, date_end=end, is_current=current, status='Active' if current else 'Completed',
                enrollment_open_date=start - timedelta(days=45), enrollment_close_date=start - timedelta(days=3),
            )
            created = []
            for number, (q_start, q_end, is_current, locked) in enumerate(periods, 1):
                created.append(Quarter.objects.create(
                    school_year=sy, quarter_label=f'{prefix}{number}', quarter_number=number, date_start=q_start, date_end=q_end,
                    grade_encoding_deadline=_aware(q_end + timedelta(days=7)),
                    grade_validation_deadline=_aware(q_end + timedelta(days=14)),
                    card_distribution_date=q_end + timedelta(days=21),
                    is_current_quarter=is_current, is_grades_locked=locked,
                    locked_by=self.registrar if locked else None,
                    locked_at=_aware(q_end + timedelta(days=15)) if locked else None,
                ))
            return sy, created

        (self.prev_sy, self.prev_quarters), (self.sy, self.quarters) = [make_year(*year) for year in self.p.years]

    # ---------------------------------------------------------------- sections, students, enrolment
    def people(self):
        rng = self.rng
        self.sections = []        # dicts for the current year
        self.prev_sections = []   # dicts for last year
        used_names = set()
        students, guardians = [], []
        serial = 0

        for grade, name, strand, adviser, size, offset in self.p.sections:
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
                    lrn=f'{self.p.lrn_prefix}{serial:08d}', first_name=first, last_name=last, middle_name=rng.choice(MIDDLES),
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

        # ---- last year: today's Grade 8-12 learners were one grade lower. Junior High and this year's Grade 11 come
        # from the section in the same place one grade lower; Grade 12 from its own section name in Grade 11.
        prev_enrollments, made = [], {}
        current = self.p.sections
        for index, entry in enumerate(self.sections):
            if entry['grade'] == 7:
                continue
            grade = entry['grade'] - 1
            if entry['grade'] == 12:
                same = next((s for s in current if s[0] == 11 and s[1] == current[index][1]), None)
                name, strand, adviser = current[index][1], current[index][2], (same or current[index])[3]
            else:
                below = [s for s in current if s[0] == grade]
                same_grade = [s for s in current if s[0] == entry['grade']]
                template = below[min(same_grade.index(current[index]), len(below) - 1)]
                name, strand, adviser = template[1], template[2], template[3]
            if (grade, name) not in made:
                section = Section.objects.create(
                    school=self.school, grade_level=self.levels[grade], school_year=self.prev_sy, section_name=name,
                    strand=self.strands.get(strand), adviser=self.staff[adviser], max_capacity=35, is_homeroom=True,
                )
                made[(grade, name)] = {'section': section, 'grade': grade, 'strand': strand, 'offset': entry['offset'],
                                       'members': [], 'subjects': self.section_subjects(grade, strand, current=False)}
                self.prev_sections.append(made[(grade, name)])
            target = made[(grade, name)]
            for member in entry['members']:
                if member['status'] == 'Transferred_In':
                    continue                                   # was in another school last year
                previous = {'student': member['student'], 'ability': member['ability'] - rng.uniform(-1.0, 2.0), 'status': 'Enrolled'}
                previous['enrollment'] = Enrollment(
                    student=member['student'], section=target['section'], school_year=self.prev_sy,
                    grade_level_at_entry=self.levels[grade], enrollment_date=date(2025, 5, rng.randint(19, 30)),
                    enrollment_type='New' if grade in (7, 11) else 'Continuing', status='Enrolled', created_by=self.registrar,
                )
                prev_enrollments.append(previous['enrollment'])
                target['members'].append(previous)
        for entry in self.prev_sections:             # two of this year's sections may come from one of last year's
            Section.objects.filter(pk=entry['section'].pk).update(current_enrollment_count=len(entry['members']),
                                                                  max_capacity=max(35, len(entry['members'])))
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
        return int(max(60, min(100, round(value))))          # a transmuted grade is 60 to 100

    def _component(self, member, code, quarter, grade, teacher, status, note='', when=None):
        rng = self.rng
        ww = max(50, min(100, grade + rng.randint(-4, 4)))
        pt = max(50, min(100, grade + rng.randint(-3, 5)))
        qa = max(50, min(100, grade + rng.randint(-6, 3)))
        w_ww, w_pt, w_qa = self.p.weights(self.subject_meta[code][0]) if quarter.quarter_label.startswith('T') else DO8_WEIGHTS
        locked = status == 'Finalized'
        checked = status in ('Validated', 'Finalized', 'Returned')
        return GradeComponent(
            enrollment=member['enrollment'], subject=self.subjects[code], quarter=quarter,
            written_work_raw=Decimal(ww), written_work_max=Decimal(100), written_work_percent=Decimal(ww),
            written_work_weighted=Decimal(ww) * w_ww,
            performance_task_raw=Decimal(pt), performance_task_max=Decimal(100), performance_task_percent=Decimal(pt),
            performance_task_weighted=Decimal(pt) * w_pt,
            quarterly_assessment_raw=Decimal(qa), quarterly_assessment_max=Decimal(100), quarterly_assessment_percent=Decimal(qa),
            quarterly_assessment_weighted=Decimal(qa) * w_qa,
            initial_grade=Decimal(grade), transmuted_grade=grade, descriptor=_descriptor(grade),
            encoded_by=teacher, validation_status=status,
            validated_by=self.registrar if checked else None, validation_date=when if checked else None,
            validation_notes=note, is_locked=locked, locked_by=self.registrar if locked else None,
            locked_at=when if locked else None,
        )

    def grades(self):
        rows = []
        # last year: every period complete and finalised
        for entry in self.prev_sections:
            for code in entry['subjects']:
                teacher = self.staff[self.subject_meta[code][1]]
                for quarter in self.prev_quarters:
                    when = _aware(quarter.date_end + timedelta(days=12))
                    for member in entry['members']:
                        rows.append(self._component(member, code, quarter, self._grade(member, entry, code, quarter.quarter_number),
                                                    teacher, 'Finalized', when=when))
        # this year: the first period finalised; the second in progress, class by class
        q1, q2 = self.quarters[0], self.quarters[1]
        self.q2_state = {}
        index = 0
        for entry in self.sections:
            active = [m for m in entry['members'] if m['status'] in ACTIVE]
            for code in entry['subjects']:
                teacher = self.staff[self.subject_meta[code][1]]
                when = _aware(q1.date_end + timedelta(days=11))
                for member in entry['members']:               # learners who dropped later still have first-period grades
                    rows.append(self._component(member, code, q1, self._grade(member, entry, code, 1), teacher, 'Finalized', when=when))

                state = self.p.states[index % len(self.p.states)]
                index += 1
                self.q2_state[(entry['section'].pk, code)] = state
                if state == 'not_started':
                    continue
                graded = active if state != 'incomplete' else active[:max(3, int(len(active) * self.rng.uniform(0.45, 0.8)))]
                status = {'validated': 'Validated', 'submitted': 'Submitted', 'ready': 'Draft', 'incomplete': 'Draft', 'returned': 'Returned'}[state]
                note = 'Two learners have grades far below their first period. Please re-check the class record and re-upload.' if state == 'returned' else ''
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
                    careless = member['ability'] < 74                 # struggling learners miss more days
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
        add(self.sections, self.sy, self.p.months_now)
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
        teacher = self.staff[self.p.quiz_teacher]
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
                teacher=teacher, subject=self.subjects[self.p.quiz_subject], section=section['section'], school_year=self.sy,
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
    help = 'Create (or remove) a self-contained ARMS demo school: quarterly by default, or the trimestral one.'

    def add_arguments(self, parser):
        parser.add_argument('--trimestral', action='store_true',
                            help='Work on the trimestral demo school (three terms, DepEd Order No. 015, s. 2026).')
        parser.add_argument('--remove', action='store_true', help='Remove the demo school and all of its data.')
        parser.add_argument('--reset', action='store_true', help='Remove the demo school first, then create it again.')
        parser.add_argument('--dry-run', action='store_true', help='Run everything, report, then undo it.')
        parser.add_argument('--spread-levels', action='store_true',
                            help='Move each discipline of the existing demo school onto its level target.')

    def handle(self, *args, **options):
        profile = TERMS if options['trimestral'] else QUARTERLY
        exists = School.objects.filter(school_id=profile.school_id).exists()

        if options['spread_levels']:
            if not exists:
                raise CommandError('There is no such demo school yet. Create it with: python manage.py seed_demo'
                                   + (' --trimestral' if options['trimestral'] else ''))
            self.stdout.write('Average of each discipline this school year, before and after:')
            with transaction.atomic():
                spread_levels(self.stdout.write, profile)
                if options['dry_run']:
                    transaction.set_rollback(True)
            self._refresh_caches()
            self.stdout.write(self.style.SUCCESS(('DRY RUN (nothing was saved). ' if options['dry_run'] else '') +
                                                 'Retrain the forecaster next: python manage.py train_ml_models'))
            return

        if options['remove']:
            with transaction.atomic():
                removed = remove_demo(profile)
                if options['dry_run']:
                    transaction.set_rollback(True)
            self._refresh_caches()
            self.stdout.write(self.style.SUCCESS('Demo data removed: ' + (', '.join(f'{v} {k}' for k, v in removed.items() if v) or 'nothing was there')))
            return

        if exists and not options['reset']:
            raise CommandError('That demo school already exists. Use --reset to rebuild it or --remove to delete it.')

        password, created = demo_password()
        with transaction.atomic():
            if exists:
                remove_demo(profile)
            seeder = Seeder(password, self.stdout, profile)
            seeder.build()
            if profile is TERMS:                     # every level of DO 015 shows on the dashboard from the start
                spread_levels(lambda line: None, profile)
            if options['dry_run']:
                transaction.set_rollback(True)
        self._refresh_caches()

        self.stdout.write(self.style.SUCCESS(
            ('DRY RUN (nothing was saved) — ' if options['dry_run'] else '') + f'{profile.school_name} is ready.'))
        for name, value in seeder.totals.items():
            self.stdout.write(f'  {name}: {value}')
        self.stdout.write('\nSign in with these demo accounts (they skip the Google-link step):')
        for role, user in seeder.showcase:
            self.stdout.write(f'  {role:<12} {user.username}')
        self.stdout.write('Password: the DEMO_PASSWORD value in your .env file'
                          + (' (just created there).' if created else '.'))
        self.stdout.write('Retrain the forecaster next: python manage.py train_ml_models')
        self.stdout.write('Remove everything again with: python manage.py seed_demo --remove'
                          + (' --trimestral' if options['trimestral'] else ''))

    @staticmethod
    def _refresh_caches():
        try:
            from core.caching import bump_data_version
            bump_data_version()
        except Exception:
            pass
