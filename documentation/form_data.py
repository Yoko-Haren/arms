"""What the DepEd school forms are made of, read from ARMS.

One place gathers a section's learners in DepEd order (male, then female, alphabetical), their
register details, grades and attendance, and the school's personnel, so every form (SF1 to SF7,
the summary of final grades) states the same facts the same way.

Grades are the quarterly grades as recorded (GradeComponent: the transmuted grade, else the
initial grade), whatever their validation status; forms say how many are not validated yet. A
final grade exists only when every grading period of the class has a grade (DepEd Order No. 8,
s. 2015); the general average only when every learning area has a final grade.
"""
import calendar
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from core import periods as P
from core import school_header

ACTIVE = ('Enrolled', 'Transferred_In')
LEFT = ('Transferred_Out', 'Dropped')
PASSING = 75
# Grades 7 to 10: the learning areas in the order of the summary of final grades and SF10
JHS_AREAS = (('FILIPINO', 'Filipino'), ('ENGLISH', 'English'), ('MATH', 'Mathematics'), ('SCIENCE', 'Science'),
             ('AP', 'Araling Panlipunan'), ('TLE', 'TLE'), ('MAPEH', 'MAPEH'), ('ESP', 'EsP'))
AREA_SHORT = {'FILIPINO': 'Fil', 'ENGLISH': 'Eng', 'MATH': 'Math', 'SCIENCE': 'Sci', 'AP': 'AP', 'TLE': 'TLE',
              'MAPEH': 'MAPEH', 'ESP': 'EsP'}
DESCRIPTOR_BANDS = ((90, 'Outstanding'), (85, 'Very Satisfactory'), (80, 'Satisfactory'), (75, 'Fairly Satisfactory'),
                    (0, 'Did Not Meet Expectations'))


def round_half_up(value, places=0):
    return Decimal(str(value)).quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def first_friday_of_june(sy):
    d = date(sy.year_start, 6, 1)
    while d.weekday() != 4:
        d += timedelta(days=1)
    return d


def age_on(birth, on):
    if not birth:
        return None
    return on.year - birth.year - ((on.month, on.day) < (birth.month, birth.day))


def learner_name(last, first, middle='', ext=''):
    """DELA CRUZ, JUAN JR., SANTOS: the School Register's way (Last, First Name Extension, Middle Name)."""
    first_part = ' '.join(x for x in (first, ext) if x)
    return ', '.join(x for x in (last, first_part, middle) if x).upper()


def short_name(last, first, middle='', ext=''):
    """DELA CRUZ, JUAN JR. S. (class records, report lists)."""
    m = f' {middle.strip()[0]}.' if (middle or '').strip() else ''
    e = f' {ext}' if ext else ''
    return f'{last}, {first}{e}{m}'.upper()


def descriptor(grade):
    return next(name for low, name in DESCRIPTOR_BANDS if grade >= low)


def school_info(school, sy):
    """Header of every form: school, region, division, district, year, and who signs it."""
    from accounts.models import UserProfile
    place = school_header.get(school)
    heads = list(UserProfile.objects.filter(school=school, role='schoolhead', is_active=True).select_related('user').order_by('id'))
    head = next((h for h in heads if 'PRINCIPAL' in (h.position_title or '').upper() and 'ASSISTANT' not in (h.position_title or '').upper()),
                heads[0] if heads else None)
    return {
        'school_id': school.school_id, 'school_name': school.school_name.upper(), 'school_year': sy.year_label,
        'region': school_header.region_code(place['region']), 'region_label': school_header.region_label(place['region']),
        'division': place['division'], 'district': place['district'],
        'head': (head.user.get_full_name() or head.user.username).upper() if head else '',
    }


def person_name(user):
    return (user.get_full_name() or user.username).upper() if user else ''


# ---------------------------------------------------------------------------------------------
# a section's learners
# ---------------------------------------------------------------------------------------------

def _guardian_name(g):
    return learner_name(g.last_name, g.first_name if g.first_name != '-' else '', g.middle_name) if g else ''


def learners(section, sy, *, include_left=True):
    """Every learner of the section this school year, male then female, alphabetical (DepEd order).

    Each: enrollment, student, lrn, name (register style), short (class record style), last, first,
    middle, ext, sex, birth_date, age (as of the first Friday of June), birth_place, mother_tongue,
    ip, religion, street, barangay, city, province, father, mother, guardian, relationship,
    contact, status, active, codes (REMARKS indicators) and remarks (the text for the form).
    """
    from enrollment.models import Enrollment
    from enrollment.sf1 import indicators
    from students.models import Guardian, GuardianContact, StudentAddress
    qs = Enrollment.objects.filter(section=section, school_year=sy).select_related('student')
    if not include_left:
        qs = qs.filter(status__in=ACTIVE)
    enrollments = list(qs)
    ids = [e.student_id for e in enrollments]
    address = {}                                           # the current address, else the primary one
    for a in StudentAddress.objects.filter(student_id__in=ids).order_by('-is_primary', 'id'):
        kept = address.get(a.student_id)
        if kept is None or (a.address_type == 'Current' and kept.address_type != 'Current'):
            address[a.student_id] = a
    guardians = defaultdict(list)
    for g in Guardian.objects.filter(student_id__in=ids).order_by('id'):
        guardians[g.student_id].append(g)
    contacts = defaultdict(list)
    for c in GuardianContact.objects.filter(guardian__student_id__in=ids).order_by('-is_primary', 'id'):
        contacts[c.guardian_id].append(c.contact_value)
    cutoff = first_friday_of_june(sy)
    out = []
    for e in enrollments:
        st = e.student
        gs = guardians.get(st.id, [])
        father = next((g for g in gs if g.relationship == 'Father'), None)
        mother = next((g for g in gs if g.relationship == 'Mother'), None)
        guardian = next((g for g in gs if g.is_primary_guardian and g.relationship not in ('Father', 'Mother')), None)
        contact = next((c for g in ([guardian] if guardian else []) + [mother, father] + gs if g for c in contacts.get(g.id, [])), '')
        a = address.get(st.id)
        codes = list(indicators(e.remarks or ''))
        for code, yes in (('T/O', e.status == 'Transferred_Out'), ('DRP', e.status == 'Dropped'),
                          ('T/I', e.status == 'Transferred_In' or e.enrollment_type == 'Transferred_In'),
                          ('B/A', e.is_balik_aral or e.enrollment_type == 'Balik_Aral'),
                          ('CCT', e.is_4ps or st.is_4ps), ('LWD', st.has_disability)):
            if yes and code not in codes:
                codes.append(code)
        remarks = (e.remarks or '').strip()
        if not remarks and codes:
            parts = []
            for code in codes:
                if code == 'LWD' and st.disability_type:
                    parts.append(f'LWD - {st.disability_type}')
                elif code == 'T/I' and e.previous_school_name:
                    parts.append(f'T/I - {e.previous_school_name}')
                elif code in ('T/O', 'DRP') and e.status_date:
                    parts.append(f'{code} - {e.status_date:%m/%d/%Y}')
                else:
                    parts.append(code)
            remarks = '; '.join(parts)
        out.append({
            'enrollment': e, 'student': st, 'lrn': st.lrn or '', 'last': st.last_name, 'first': st.first_name,
            'middle': st.middle_name or '', 'ext': st.name_extension or '',
            'name': learner_name(st.last_name, st.first_name, st.middle_name, st.name_extension),
            'short': short_name(st.last_name, st.first_name, st.middle_name, st.name_extension),
            'sex': st.sex, 'birth_date': st.birth_date, 'age': age_on(st.birth_date, cutoff),
            'birth_place': st.birth_place or '', 'mother_tongue': st.mother_tongue or '',
            'ip': st.ethnicity if st.is_ip else '', 'religion': st.religion or '',
            'street': (a.house_number_street or a.sitio_purok or '') if a else '', 'barangay': a.barangay if a else '',
            'city': a.city_municipality if a else '', 'province': a.province if a else '',
            'father': _guardian_name(father), 'mother': _guardian_name(mother),
            'guardian': _guardian_name(guardian), 'relationship': guardian.relationship if guardian else '',
            'contact': contact, 'status': e.status, 'active': e.status in ACTIVE, 'codes': codes, 'remarks': remarks,
            'late': 'LE' in codes,
        })
    out.sort(key=lambda p: (p['sex'] != 'M', p['last'].upper(), p['first'].upper(), p['middle'].upper()))
    return out


def split_sex(people):
    return [p for p in people if p['sex'] == 'M'], [p for p in people if p['sex'] != 'M']


def adviser_of(section):
    return person_name(section.adviser) if section.adviser_id else ''


# ---------------------------------------------------------------------------------------------
# grades
# ---------------------------------------------------------------------------------------------

def class_assignments(section, sy):
    from scheduling.models import ClassAssignment
    return list(ClassAssignment.objects.filter(section=section, school_year=sy, is_active=True)
                .select_related('subject', 'subject__subject_family', 'teacher', 'semester').order_by('subject__subject_code'))


def section_subjects(section, sy, enrollment_ids):
    """[(subject, class assignment or None)]: the section's classes this year, then any other subject its
    learners have grades in (a finished school year may keep grades without its class assignments)."""
    from academics.models import Subject
    from grades.models import GradeComponent
    classes = class_assignments(section, sy)
    seen = {a.subject_id for a in classes}
    graded = Subject.objects.filter(id__in=GradeComponent.objects.filter(enrollment_id__in=enrollment_ids).values('subject_id')
                                    ).exclude(id__in=seen).select_related('subject_family').order_by('subject_code')
    return [(a.subject, a) for a in classes] + [(subject, None) for subject in graded]


def jhs_area(subject):
    """FILIPINO, ENGLISH, MATH, ... for a Grades 7 to 10 subject (by its name, then its family)."""
    from grades import ecr
    family = subject.subject_family.family_name if subject.subject_family_id else ''
    return ecr.subject_key(subject.subject_name) or ecr.subject_key(family)


def quarter_grades(enrollment_ids, subject_ids, periods):
    """{(enrollment id, subject id, period id): grade} for the given periods."""
    from grades.models import GradeComponent
    out = {}
    for e, s, q, t, i in GradeComponent.objects.filter(enrollment_id__in=enrollment_ids, subject_id__in=subject_ids,
                                                          quarter__in=periods).values_list(
            'enrollment_id', 'subject_id', 'quarter_id', 'transmuted_grade', 'initial_grade'):
        value = P.grade_value(t, i)
        if value is not None:
            out[(e, s, q)] = int(round_half_up(value))
    return out


def unvalidated_count(enrollment_ids, periods):
    from grades.models import GradeComponent
    return GradeComponent.objects.filter(enrollment_id__in=enrollment_ids, quarter__in=periods).exclude(
        validation_status__in=('Validated', 'Finalized')).count()


def jhs_record(section, sy, people=None):
    """Per learner the quarter and final grade of every learning area, the general average and the
    action taken (DepEd Order No. 8, s. 2015): promoted (all areas 75 or higher), conditional (did not
    meet expectations in one or two areas), retained (three or more). Missing grades leave it open.
    """
    from academics.models import Quarter
    people = people if people is not None else learners(section, sy)
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number'))
    ids = [p['enrollment'].id for p in people]
    by_area = {}
    for subject, a in section_subjects(section, sy, ids):
        key = jhs_area(subject)
        if key and key not in by_area:
            by_area[key] = (subject, a)
    grades = quarter_grades(ids, [subject.id for subject, _ in by_area.values()], periods)
    for p in people:
        p['areas'] = {}
        for key, _ in JHS_AREAS:
            subject, a = by_area.get(key, (None, None))
            own = P.for_class(a, periods) if a else periods
            quarters = [grades.get((p['enrollment'].id, subject.id, q.id)) if subject else None for q in own]
            p['areas'][key] = {'quarters': quarters, 'final': P.final_grade(quarters, len(own)) if subject else None}
        finals = [p['areas'][k]['final'] for k, _ in JHS_AREAS if k in by_area]
        complete = by_area and all(f is not None for f in finals)
        p['general_average'] = int(round_half_up(sum(finals) / len(finals))) if complete else None
        p['general_average_exact'] = round_half_up(sum(finals) / len(finals), 3) if complete else None
        failed_keys = [key for key, _ in JHS_AREAS if key in by_area and p['areas'][key]['final'] is not None
                       and p['areas'][key]['final'] < PASSING]
        failed = [label for key, label in JHS_AREAS if key in failed_keys]
        p['failed_areas'], p['failed_keys'] = failed, failed_keys
        if not complete:
            p['action'] = ''
        elif not failed:
            p['action'] = 'PROMOTED'
        elif len(failed) <= 2:
            p['action'] = 'CONDITIONAL'
        else:
            p['action'] = 'RETAINED'
    return {'people': people, 'periods': periods, 'areas': by_area,
            'unvalidated': unvalidated_count([p['enrollment'].id for p in people], periods)}


def semester_periods(semester, periods):
    inside = [p for p in periods if p.date_start <= semester.date_end and p.date_end >= semester.date_start]
    return inside


def shs_semester(section, sy, semester, people=None):
    """Senior High status at the end of a semester (SHSF-5A): each subject's semester grade (the rounded
    average of its quarters in the semester), the back subjects (below 75), Complete or Incomplete.
    """
    from academics.models import Quarter
    from grades.models import GradeComponent
    people = people if people is not None else learners(section, sy)
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number'))
    sem_periods = semester_periods(semester, periods) if semester else periods
    ids = [p['enrollment'].id for p in people]
    graded_here = set(GradeComponent.objects.filter(enrollment_id__in=ids, quarter__in=sem_periods).values_list('subject_id', flat=True))
    sem_id = getattr(semester, 'id', None)

    def belongs(subject, a):
        if a is None:                                      # graded, but no class this year: by its grades
            return subject.id in graded_here
        if a.semester_id is None:                          # a whole-year class
            return True
        return a.semester_id == sem_id if sem_id else subject.id in graded_here
    classes = [(subject, a) for subject, a in section_subjects(section, sy, ids) if belongs(subject, a)]
    grades = quarter_grades(ids, [subject.id for subject, _ in classes], sem_periods)
    for p in people:
        subjects = []
        for subject, a in classes:
            own = [q for q in (P.for_class(a, periods) if a else periods) if q in sem_periods] or sem_periods
            values = [grades.get((p['enrollment'].id, subject.id, q.id)) for q in own]
            subjects.append({'subject': subject, 'grade': P.final_grade(values, len(own))})
        p['subjects'] = subjects
        p['back_subjects'] = [s['subject'].subject_name for s in subjects if s['grade'] is not None and s['grade'] < PASSING]
        p['missing'] = [s['subject'].subject_name for s in subjects if s['grade'] is None]
        p['semester_complete'] = bool(subjects) and not p['back_subjects'] and not p['missing']
        if p['back_subjects']:
            p['semester_status'] = 'Incomplete'
        elif subjects and not p['missing']:
            p['semester_status'] = 'Complete'
        else:
            p['semester_status'] = ''                      # grades still missing: not decided yet
    return {'people': people, 'classes': classes, 'periods': sem_periods,
            'unvalidated': unvalidated_count([p['enrollment'].id for p in people], sem_periods)}


# ---------------------------------------------------------------------------------------------
# attendance
# ---------------------------------------------------------------------------------------------

def month_days(year, month, sy=None):
    """The school days of a month: Monday to Friday (Saturday too when asked), inside the school year."""
    days = []
    for day in range(1, calendar.monthrange(year, month)[1] + 1):
        d = date(year, month, day)
        if d.weekday() < 5 and (sy is None or sy.date_start <= d <= sy.date_end):
            days.append(d)
    return days


def months_of(sy):
    """[(month number, 'June 2026')] of the school year, first month first."""
    out, d = [], date(sy.date_start.year, sy.date_start.month, 1)
    while d <= sy.date_end and len(out) < 13:
        out.append((d.month, f'{calendar.month_name[d.month]} {d.year}'))
        d = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
    return out


def default_month(sy):
    """This month while the year runs, else its last (or first) month."""
    today = date.today()
    months = months_of(sy)
    if sy.date_start <= today <= sy.date_end:
        return today.month
    return months[-1][0] if months and today > sy.date_end else (months[0][0] if months else today.month)


def month_of(sy, month):
    """(year, month) of a month number inside the school year (June 2026 ... March 2027)."""
    year = sy.year_start if month >= sy.date_start.month else sy.year_end
    return year, month


def attendance(enrollment_ids, sy, month):
    """{enrollment id: AttendanceSummary} of the month, and {enrollment id: {date: status}} of daily marks."""
    from attendance.models import AttendanceRecord, AttendanceSummary
    year, _ = month_of(sy, month)
    summaries = {s.enrollment_id: s for s in AttendanceSummary.objects.filter(enrollment_id__in=enrollment_ids, school_year=sy,
                                                                              month=month)}
    daily = defaultdict(dict)
    for e, d, status in AttendanceRecord.objects.filter(enrollment_id__in=enrollment_ids, date__year=year,
                                                         date__month=month).values_list('enrollment_id', 'date', 'status'):
        daily[e][d] = status
    return summaries, daily


def month_movement(enrollments, year, month):
    """Learners who dropped out, transferred out or in before and during a month (from status dates)."""
    start = date(year, month, 1)
    end = date(year, month, calendar.monthrange(year, month)[1])

    def bucket(d):
        if d is None:
            return 1 if date.today() >= start else None
        if d < start:
            return 0
        return 1 if d <= end else None
    by_sex = {k: [[0, 0], [0, 0]] for k in ('drp', 'to', 'ti')}   # [M, F] x [before the month, in the month]
    for e in enrollments:
        sex = 0 if e.student.sex == 'M' else 1
        if e.status == 'Dropped':
            b = bucket(e.status_date)
            if b is not None:
                by_sex['drp'][sex][b] += 1
        elif e.status == 'Transferred_Out':
            b = bucket(e.status_date)
            if b is not None:
                by_sex['to'][sex][b] += 1
        if e.status == 'Transferred_In' or e.enrollment_type == 'Transferred_In':
            b = bucket(e.enrollment_date)
            if b is not None:
                by_sex['ti'][sex][b] += 1
    return by_sex


def registered_at(enrollments, day):
    """Learners registered in the section at the end of a day (not yet dropped or transferred out)."""
    count = [0, 0]
    for e in enrollments:
        if e.status in LEFT and e.status_date and e.status_date <= day:
            continue
        if e.status not in ACTIVE + LEFT:
            continue
        count[0 if e.student.sex == 'M' else 1] += 1
    return count


# ---------------------------------------------------------------------------------------------
# personnel
# ---------------------------------------------------------------------------------------------

_RANKS = ('PRINCIPAL', 'HEAD TEACHER', 'MASTER TEACHER IV', 'MASTER TEACHER III', 'MASTER TEACHER II', 'MASTER TEACHER I',
          'TEACHER III', 'TEACHER II', 'TEACHER I')


def personnel(school, sy, semester=None):
    """The school's personnel for SF7: teaching staff first (by position, highest first), then the rest."""
    from accounts.models import UserProfile
    from personnel.models import TeacherEducation
    from scheduling.models import ClassAssignment, ClassSchedule
    profiles = list(UserProfile.objects.filter(school=school, is_active=True).exclude(role='admin').select_related('user'))
    users = [p.user_id for p in profiles]
    education = {}
    for t in TeacherEducation.objects.filter(user_id__in=users).order_by('-is_highest_degree', '-year_graduated'):
        education.setdefault(t.user_id, t)
    classes = defaultdict(list)
    qs = ClassAssignment.objects.filter(school_year=sy, teacher_id__in=users, is_active=True).select_related(
        'subject', 'section', 'section__grade_level', 'semester')
    if semester is not None:
        qs = qs.filter(semester__in=[semester, None])
    for a in qs.order_by('section__grade_level__grade_number', 'section__section_name', 'subject__subject_code'):
        classes[a.teacher_id].append(a)
    schedules = defaultdict(list)
    for s in ClassSchedule.objects.filter(class_assignment__in=[a for v in classes.values() for a in v], is_active=True).select_related(
            'class_assignment').order_by('day_number', 'time_start'):
        schedules[s.class_assignment_id].append(s)
    from academics.models import Section
    advisory = {s.adviser_id: s for s in Section.objects.filter(school=school, school_year=sy, adviser_id__in=users).select_related('grade_level')}

    def rank(p):
        title = (p.position_title or p.designation or '').upper()
        if p.role == 'schoolhead':
            return 0, 0 if title.startswith('PRINCIPAL') else 1, title
        position = next((i for i, r in enumerate(_RANKS) if title.startswith(r)), len(_RANKS))
        return (1 if p.role == 'teacher' else 2), position, title
    out = []
    for p in sorted(profiles, key=lambda p: (rank(p), (p.user.last_name or p.user.username).upper())):
        u = p.user
        edu = education.get(u.id)
        teaching = []
        minutes = 0
        for a in classes.get(u.id, []):
            per_week = (a.minutes_per_meeting or 0) * (a.meetings_per_week or 0)
            minutes += per_week
            teaching.append({'assignment': a, 'label': f'{a.subject.subject_name} ({a.section.grade_level.grade_name} - {a.section.section_name})',
                             'minutes': per_week, 'schedules': schedules.get(a.id, [])})
        adv = advisory.get(u.id)
        out.append({
            'profile': p, 'employee_no': p.employee_number or '', 'name': learner_name(u.last_name or u.username, u.first_name),
            'teaching_role': p.role in ('teacher', 'schoolhead'),
            'position': p.position_title or p.designation or dict(p._meta.get_field('role').choices).get(p.role, ''),
            'appointment': p.get_employment_status_display() if p.employment_status else '',
            'fund': 'National' if p.role in ('teacher', 'schoolhead') else '',
            'degree': (edu.degree if edu else '') or (p.get_educational_attainment_display() if p.educational_attainment else ''),
            'major': (edu.major if edu else '') or p.specialization or p.teaching_area or '', 'minor': '',
            'classes': teaching, 'minutes_week': minutes,
            'advisory': f'{adv.grade_level.grade_name} - {adv.section_name}' if adv else '',
        })
    return out
