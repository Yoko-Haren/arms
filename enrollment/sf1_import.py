"""Enrolling a section from its SF1: what the import would do (preview), then doing it (apply).

preview() changes nothing. apply() creates what is missing (the grade level, the Senior High track
and strand, the section), adds or updates every learner from the register (personal details,
current address, parents, guardian and the contact number) and enrolls them in the section for the
current school year. A value already in ARMS is only replaced by a value the register actually
has: an empty cell never erases anything. Learners already enrolled in another section this year
stay there unless the registrar chooses to move them.
"""
import re

from django.db import transaction
from django.db.models import Max

from academics.models import GradeLevel, Section, Strand, Track
from core import school_header
from enrollment.models import Enrollment
from students.models import Guardian, GuardianContact, Student, StudentAddress

from . import sf1

ACTIVE = ('Enrolled', 'Transferred_In')
STRAND_NAMES = {
    'STEM': 'Science, Technology, Engineering and Mathematics', 'HUMSS': 'Humanities and Social Sciences',
    'ABM': 'Accountancy, Business and Management', 'GAS': 'General Academic Strand',
    'ICT': 'Information and Communications Technology', 'HE': 'Home Economics', 'IA': 'Industrial Arts',
    'AFA': 'Agri-Fishery Arts', 'SPORTS': 'Sports', 'ARTS': 'Arts and Design',
}
TRACK_NAMES = {'ACADEMIC': 'Academic', 'TVL': 'Technical-Vocational-Livelihood', 'SPORTS': 'Sports', 'ARTS': 'Arts and Design'}
_RELATIONSHIPS = {r.upper(): r for r in ('Father', 'Mother', 'Stepfather', 'Stepmother', 'Grandfather', 'Grandmother',
                                          'Aunt', 'Uncle', 'Sibling', 'Legal Guardian', 'Foster Parent', 'Other Relative')}
_RELATIONSHIP_WORDS = {'LOLA': 'Grandmother', 'LOLO': 'Grandfather', 'TITA': 'Aunt', 'TITO': 'Uncle', 'BROTHER': 'Sibling',
                       'SISTER': 'Sibling', 'GRANDPARENT': 'Grandmother', 'GUARDIAN': 'Legal Guardian', 'COUSIN': 'Other Relative'}


def _years(text):
    return set(re.findall(r'\d{4}', text or ''))


def _same_school(file_id, school):
    a, b = re.sub(r'[^0-9A-Z]', '', (file_id or '').upper()), re.sub(r'[^0-9A-Z]', '', (school.school_id or '').upper())
    return not a or a == b


def enrollment_status(codes):
    """The enrollment status an SF1 REMARKS indicator gives (T/O, DRP leave; T/I came in)."""
    if 'T/O' in codes:
        return 'Transferred_Out'
    if 'DRP' in codes:
        return 'Dropped'
    if 'T/I' in codes:
        return 'Transferred_In'
    return 'Enrolled'


def enrollment_type(codes, known_before):
    if 'T/I' in codes:
        return 'Transferred_In'
    if 'B/A' in codes:
        return 'Balik_Aral'
    return 'Continuing' if known_before else 'New'


def preview(parsed, school, sy):
    """What importing this SF1 into the school's current year would do. Nothing is written."""
    meta, rows = parsed['meta'], parsed['rows']
    checks = [('warn', w) for w in parsed.get('warnings', [])]
    number = meta.get('grade_number')
    section_name = re.sub(r'\s+', ' ', (meta.get('section') or '').strip())
    if not number:
        checks.insert(0, ('error', 'The SF1 does not say the grade level (the GRADE LEVEL box), so ARMS cannot tell which section it is.'))
    if not section_name:
        checks.insert(0, ('error', 'The SF1 does not name the section (the SECTION box at the top of the form).'))
    if meta.get('school_year') and _years(meta['school_year']) and not _years(meta['school_year']) <= _years(sy.year_label):
        checks.insert(0, ('error', f'This SF1 is for SY {meta["school_year"]}. ARMS enrolls learners into the current school year, '
                                   f'{sy.year_label}. Export this school year\'s SF1 from LIS.'))
    if not _same_school(meta.get('school_id'), school):
        checks.append(('warn', f'The SF1 is for School ID {meta["school_id"]}, but this school is {school.school_id}. '
                               'Make sure it is your school\'s register.'))

    grade_level = GradeLevel.objects.filter(school=school, grade_number=number).first() if number else None
    strand, strand_new = None, None
    if parsed['kind'] == 'SHS':
        track_code, strand_code = meta.get('track'), meta.get('strand')
        if strand_code:
            strand = Strand.objects.filter(track__school=school, strand_code__iexact=strand_code).first()
            if not strand:
                strand_new = (track_code or 'ACADEMIC', strand_code)
        else:
            checks.append(('warn', 'The TRACK AND STRAND box is empty or not recognised, so the section gets no strand.'))
    section = Section.objects.filter(school=school, school_year=sy, grade_level=grade_level,
                                     section_name__iexact=section_name).select_related('adviser').first() if grade_level and section_name else None

    lrns = [r['lrn'] for r in rows if r['lrn']]
    students = {s.lrn: s for s in Student.objects.filter(lrn__in=lrns)}
    enrolled = {e.student.lrn: e for e in Enrollment.objects.filter(student__lrn__in=lrns, school_year=sy)
                .select_related('student', 'section', 'section__grade_level')}
    counts = {'new': 0, 'enroll': 0, 'existing': 0, 'elsewhere': 0, 'duplicate': 0, 'invalid': 0}
    seen = set()
    for r in rows:
        r['status'] = enrollment_status(r['codes'])
        if r['errors']:
            r['state'], r['note'] = 'invalid', ' '.join(r['errors'])
        elif r['lrn'] in seen:
            r['state'], r['note'] = 'duplicate', 'This LRN is listed twice in the file; only the first row is used.'
        else:
            e, st = enrolled.get(r['lrn']), students.get(r['lrn'])
            if e and section and e.section_id == section.id:
                r['state'], r['note'] = 'existing', 'Already in this section. Details are updated from the SF1.'
            elif e:
                r['state'] = 'elsewhere'
                r['note'] = f'Enrolled in {e.section.grade_level.grade_name} {e.section.section_name} this school year.'
                r['current_section'] = f'{e.section.grade_level.grade_name} {e.section.section_name}'
            elif st:
                r['state'], r['note'] = 'enroll', 'Already in ARMS from an earlier year; enrolled in this section.'
            else:
                r['state'], r['note'] = 'new', 'New learner.'
            if st and (st.last_name.upper() != r['last'].upper() or st.first_name.upper() != r['first'].upper()):
                r['warnings'].append(f'ARMS has this LRN as {st.last_name}, {st.first_name}. The SF1 spelling will be used.')
            if st and st.sex and st.sex != r['sex']:
                r['warnings'].append(f'ARMS records this learner as {"male" if st.sex == "M" else "female"}; the SF1 says '
                                     f'{"male" if r["sex"] == "M" else "female"}. The SF1 will be used.')
        seen.add(r['lrn'])
        counts[r['state']] += 1

    not_in_file = []
    if section:
        not_in_file = [f'{e.student.last_name}, {e.student.first_name}' for e in Enrollment.objects.filter(
            section=section, school_year=sy, status__in=ACTIVE).exclude(student__lrn__in=lrns).select_related('student')
            .order_by('student__last_name', 'student__first_name')]
    importable = counts['new'] + counts['enroll'] + counts['existing'] + counts['elsewhere']
    if not importable:
        checks.insert(0, ('error', 'No learner row of this SF1 can be imported. Fix the rows marked below in the file and upload it again.'))
    return {
        'kind': parsed['kind'], 'meta': meta, 'checks': checks, 'rows': rows, 'counts': counts,
        'grade_level': grade_level, 'grade_number': number, 'section_name': section_name, 'section': section,
        'strand': strand, 'strand_new': strand_new, 'not_in_file': not_in_file,
        'males': sum(1 for r in rows if r['sex'] == 'M' and r['state'] != 'invalid'),
        'females': sum(1 for r in rows if r['sex'] == 'F' and r['state'] != 'invalid'),
        'can_import': not any(level == 'error' for level, _ in checks),
    }


# ---------------------------------------------------------------------------------------------
# applying an import
# ---------------------------------------------------------------------------------------------

def _grade_level(school, number):
    found = GradeLevel.objects.filter(school=school, grade_number=number).first()
    if found:
        return found
    code = f'G{number}'
    if GradeLevel.objects.filter(school=school, grade_code=code).exists():
        code = f'G{number}-{school.pk}'
    top = GradeLevel.objects.filter(school=school).aggregate(m=Max('sort_order'))['m'] or 0
    return GradeLevel.objects.create(school=school, grade_code=code, grade_name=f'Grade {number}', grade_number=number,
                                     level_category='SHS' if number >= 11 else 'JHS', is_senior_high=number >= 11,
                                     sort_order=max(top + 1, number))


def _strand(school, track_code, strand_code):
    track, _ = Track.objects.get_or_create(school=school, track_code=track_code,
                                           defaults={'track_name': TRACK_NAMES.get(track_code, track_code.title())})
    strand, _ = Strand.objects.get_or_create(track=track, strand_code=strand_code,
                                             defaults={'strand_name': STRAND_NAMES.get(strand_code, strand_code)})
    return strand


def _person(text):
    """'DELA CRUZ, JUAN, SANTOS' -> (last, first, middle) for a parent or guardian, or None when empty."""
    last, first, middle, _ = sf1.split_name(text)
    if not last:
        return None
    if not first:                                   # a name written without commas: First Middle Last
        words = last.split()
        if len(words) >= 2:
            first, last = ' '.join(words[:-1]), words[-1]
    return last[:100], first[:100] or '-', middle[:100]


def _relationship(text):
    t = sf1._norm(text)
    if t in _RELATIONSHIPS:
        return _RELATIONSHIPS[t]
    for word, rel in _RELATIONSHIP_WORDS.items():
        if word in t:
            return rel
    return 'Other Relative' if t else 'Legal Guardian'


def _update(obj, values):
    """Set the non-empty values that differ; returns the changed field names."""
    changed = []
    for field, value in values.items():
        if value in (None, ''):
            continue
        if getattr(obj, field) != value:
            setattr(obj, field, value)
            changed.append(field)
    return changed


def _save_learner(row, user, region):
    disabled = 'LWD' in row['codes'] or 'LWE' in row['codes']
    values = {
        'first_name': row['first'][:100], 'middle_name': row['middle'][:100], 'last_name': row['last'][:100],
        'name_extension': row['ext'], 'sex': row['sex'], 'birth_date': row['birth_date'],
        'birth_place': row['birth_place'][:255], 'mother_tongue': row['mother_tongue'][:100],
        'ethnicity': row['ethnic'][:100], 'religion': row['religion'][:100],
    }
    student = Student.objects.filter(lrn=row['lrn']).first()
    created = student is None
    if created:
        student = Student(lrn=row['lrn'], created_by=user)
        for field, value in values.items():
            setattr(student, field, value if value is not None else getattr(student, field))
        student.is_ip = bool(row['ethnic'])
        student.has_disability = disabled
        if disabled:
            student.disability_type = re.sub(r'(?i)\b(LWD|LWE)\b[:\s-]*', '', row['remarks']).strip()[:100]
        student.save()
    else:
        changed = _update(student, values)
        if row['ethnic'] and not student.is_ip:
            student.is_ip = True
            changed.append('is_ip')
        if disabled and not student.has_disability:
            student.has_disability = True
            student.disability_type = re.sub(r'(?i)\b(LWD|LWE)\b[:\s-]*', '', row['remarks']).strip()[:100]
            changed += ['has_disability', 'disability_type']
        if changed:
            student.updated_by = user
            student.save()

    if any(row[k] for k in ('street', 'barangay', 'city', 'province')):
        address = StudentAddress.objects.filter(student=student, address_type='Current').first() or \
            StudentAddress(student=student, address_type='Current', is_primary=True)
        _update(address, {'house_number_street': row['street'][:255], 'barangay': row['barangay'][:100],
                          'city_municipality': row['city'][:100], 'province': row['province'][:100], 'region': (region or '')[:50]})
        for field in ('house_number_street', 'barangay', 'city_municipality', 'province', 'region'):
            if getattr(address, field) is None:
                setattr(address, field, '')
        address.save()

    people = []
    for text, rel in ((row['father'], 'Father'), (row['mother'], 'Mother')):
        if _person(text):
            people.append((_person(text), rel, False))
    if _person(row['guardian']):
        people.append((_person(row['guardian']), _relationship(row['relationship']), True))
    primary = None
    for (last, first, middle), rel, is_guardian in people:
        g = Guardian.objects.filter(student=student, relationship=rel).first() or Guardian(student=student, relationship=rel)
        _update(g, {'last_name': last, 'first_name': first, 'middle_name': middle})
        if is_guardian:
            g.is_primary_guardian, g.is_living_with_student = True, True
        g.save()
        primary = g if is_guardian or primary is None or rel == 'Mother' else primary
    if primary and row['contact']:
        number = re.sub(r'[^\d+]', '', row['contact'])[:20] or row['contact'][:50]
        if not GuardianContact.objects.filter(guardian=primary, contact_value=number).exists():
            GuardianContact.objects.create(guardian=primary, contact_type='Mobile', contact_value=number,
                                           is_primary=not GuardianContact.objects.filter(guardian=primary).exists())
    return student, created


def apply(parsed, school, sy, user, *, move_elsewhere=False, adviser=None):
    """Write the import. Returns what was done; raises sf1.SF1Error when the preview has errors."""
    plan = preview(parsed, school, sy)
    if not plan['can_import']:
        raise sf1.SF1Error(next(text for level, text in plan['checks'] if level == 'error'))
    meta = plan['meta']
    done = {'created_students': 0, 'enrolled': 0, 'updated': 0, 'moved': 0, 'left_elsewhere': 0, 'skipped': 0,
            'section_created': False, 'strand_created': bool(plan['strand_new'])}
    touched_sections = set()
    with transaction.atomic():
        grade_level = plan['grade_level'] or _grade_level(school, plan['grade_number'])
        strand = plan['strand'] or (_strand(school, *plan['strand_new']) if plan['strand_new'] else None)
        section = plan['section']
        if section is None:
            section = Section.objects.create(school=school, school_year=sy, grade_level=grade_level,
                                             section_name=plan['section_name'][:60], strand=strand if grade_level.is_senior_high else None,
                                             adviser=adviser, is_active=True)
            done['section_created'] = True
        else:
            changed = []
            if strand and grade_level.is_senior_high and section.strand_id != strand.id:
                section.strand = strand
                changed.append('strand')
            if adviser and section.adviser_id != adviser.id:
                section.adviser = adviser
                changed.append('adviser')
            if not section.is_active:
                section.is_active = True
                changed.append('is_active')
            if changed:
                section.save()
        touched_sections.add(section.id)
        school_header.remember(school, meta, user)        # region, division, district for the school forms

        for row in plan['rows']:
            if row['state'] in ('invalid', 'duplicate'):
                done['skipped'] += 1
                continue
            if row['state'] == 'elsewhere' and not move_elsewhere:
                done['left_elsewhere'] += 1
                continue
            known_before = Student.objects.filter(lrn=row['lrn']).exists()
            student, created = _save_learner(row, user, meta.get('region'))
            done['created_students'] += created
            e = Enrollment.objects.filter(student=student, school_year=sy).select_related('section').first()
            if e is None:
                Enrollment.objects.create(
                    student=student, section=section, school_year=sy, grade_level_at_entry=grade_level,
                    status=row['status'], enrollment_type=enrollment_type(row['codes'], known_before),
                    is_balik_aral='B/A' in row['codes'], remarks=row['remarks'][:1000], created_by=user)
                done['enrolled'] += 1
                continue
            if e.section_id != section.id:
                touched_sections.add(e.section_id)
                e.section = section
                e.grade_level_at_entry = grade_level
                done['moved'] += 1
            else:
                done['updated'] += 1
            e._changed_by = user
            if row['status'] != 'Enrolled' or e.status not in ACTIVE:
                e.status = row['status']
            if row['remarks']:
                e.remarks = row['remarks'][:1000]
            e.updated_by = user
            e.save()

        for sid in touched_sections:
            s = Section.objects.get(pk=sid)
            s.current_enrollment_count = Enrollment.objects.filter(section=s, school_year=sy, status__in=ACTIVE).count()
            s.save(update_fields=['current_enrollment_count'])
    done['section'] = section
    return done
