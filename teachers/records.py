"""Teacher class records: progress per grading period, uploads (preview, then confirm) and submission.

Grades enter ARMS from the teacher's DepEd e-class record (or a CSV keyed by LRN). An upload never
writes straight away: the file is read and checked (grades.ecr), the teacher reviews every row and
settles anything uncertain, and only the confirmed rows are saved, as drafts. The teacher then
submits a complete class to the registrar, who validates or returns it; only after that do the
grades count as validated for the School Head.
"""
import csv
import io
import re
import secrets
from collections import defaultdict
from decimal import Decimal

from django.core.cache import caches
from django.db import transaction
from django.utils import timezone

from core import periods as P
from enrollment.models import Enrollment
from grades import ecr
from grades.models import GradeChangeLog, GradeComponent
from grades.review import class_state, is_mapeh, mapeh_remark

ACTIVE = ('Enrolled', 'Transferred_In')
LOCKED_STATUSES = ('Validated', 'Finalized')
PREVIEW_SECONDS = 30 * 60

STATE_INFO = {
    'not_started': ('Not started', 'muted', 'No grades yet.'),
    'encoding': ('In progress', 'warn', 'Some learners still have no grade.'),
    'ready': ('Ready to submit', 'info', 'Every learner has a grade. Submit it to the registrar.'),
    'submitted': ('Submitted', 'info', 'Waiting for the registrar to validate.'),
    'returned': ('Returned', 'risk', 'The registrar returned the grades for correction.'),
    'validated': ('Validated', 'good', 'The registrar validated these grades.'),
    'locked': ('Locked', 'good', 'The period is locked; the grades are final.'),
}


def roster(assignment, include_inactive=True):
    """Learners of the class for matching: active ones, and those who left (so a stray row is explained)."""
    qs = Enrollment.objects.filter(section=assignment.section, school_year=assignment.school_year).select_related('student')
    if not include_inactive:
        qs = qs.filter(status__in=ACTIVE)
    people = []
    for e in qs.order_by('student__last_name', 'student__first_name'):
        st = e.student
        people.append({'id': e.id, 'lrn': st.lrn or '', 'first': st.first_name, 'middle': st.middle_name, 'last': st.last_name,
                       'ext': getattr(st, 'name_extension', '') or '', 'sex': st.sex, 'active': e.status in ACTIVE,
                       'status': e.status})
    return people


def display_name(p):
    middle = f' {p["middle"][0]}.' if p.get('middle') else ''
    ext = f' {p["ext"]}' if p.get('ext') else ''
    return f'{p["last"]}, {p["first"]}{ext}{middle}'


# ---------------------------------------------------------------------------------------------
# progress of every class
# ---------------------------------------------------------------------------------------------

def overview(assignments, periods, current):
    """Per class: learners, per-period progress and averages, and the current period's state."""
    assignments = list(assignments)
    sections = {a.section_id for a in assignments}
    enrolled = defaultdict(int)
    for section_id, status in Enrollment.objects.filter(section_id__in=sections, school_year__in={a.school_year_id for a in assignments},
                                                        status__in=ACTIVE).values_list('section_id', 'status'):
        enrolled[section_id] += 1
    stats = defaultdict(lambda: {'statuses': defaultdict(int), 'grades': []})
    for section_id, subject_id, quarter_id, status, transmuted, initial in GradeComponent.objects.filter(
            enrollment__section_id__in=sections, enrollment__status__in=ACTIVE, quarter__in=periods,
            subject_id__in={a.subject_id for a in assignments}).values_list(
            'enrollment__section_id', 'subject_id', 'quarter_id', 'validation_status', 'transmuted_grade', 'initial_grade'):
        bucket = stats[(section_id, subject_id, quarter_id)]
        bucket['statuses'][status] += 1
        value = P.grade_value(transmuted, initial)
        if value is not None:
            bucket['grades'].append(value)

    rows = []
    for a in assignments:
        own = P.for_class(a, periods)
        total = enrolled.get(a.section_id, 0)
        cells = []
        for p in own:
            b = stats.get((a.section_id, a.subject_id, p.id), {'statuses': {}, 'grades': []})
            graded = sum(b['statuses'].values())
            cells.append({
                'period': p, 'label': p.quarter_label, 'graded': graded, 'total': total,
                'percent': min(100, round(graded * 100 / total)) if total else 0,
                'average': round(sum(b['grades']) / len(b['grades']), 1) if b['grades'] else None,
                'below': sum(1 for g in b['grades'] if g < 75),
                'state': class_state(total, b['statuses'], p.is_grades_locked),
                'is_current': current is not None and p.id == current.id,
            })
        now = next((c for c in cells if c['is_current']), None)
        rows.append({'assignment': a, 'section': a.section, 'subject': a.subject, 'learners': total, 'cells': cells,
                     'current': now, 'state': now['state'] if now else 'not_started'})
    return rows


def learners_table(assignment, periods):
    """Every active learner of a class with a grade per period and the final grade (when all periods have one)."""
    own = P.for_class(assignment, periods)
    enrollments = list(Enrollment.objects.filter(section=assignment.section, school_year=assignment.school_year,
                                                 status__in=ACTIVE).select_related('student')
                       .order_by('student__last_name', 'student__first_name'))
    grade_of = {}
    for e_id, q_id, transmuted, initial, status in GradeComponent.objects.filter(
            enrollment__in=enrollments, subject=assignment.subject, quarter__in=own).values_list(
            'enrollment_id', 'quarter_id', 'transmuted_grade', 'initial_grade', 'validation_status'):
        grade_of[(e_id, q_id)] = (P.grade_value(transmuted, initial), status)
    out = []
    for e in enrollments:
        values = [grade_of.get((e.id, p.id), (None, None)) for p in own]
        st = e.student
        out.append({'lrn': st.lrn, 'name': f'{st.last_name}, {st.first_name}' + (f' {st.middle_name[0]}.' if st.middle_name else ''),
                    'sex': st.sex, 'grades': [v for v, _ in values], 'statuses': [s for _, s in values],
                    'final': P.final_grade([v for v, _ in values], len(own))})
    return own, out


# ---------------------------------------------------------------------------------------------
# uploads: read, check, keep for review
# ---------------------------------------------------------------------------------------------

def analyse_upload(uploaded, assignment, period, school):
    """Read an e-class record (.xlsx) or a CSV for one class and period. Raises ecr.EcrError when unusable."""
    name = (uploaded.name or '').lower()
    people = roster(assignment)
    senior = assignment.section.grade_level.is_senior_high
    family = getattr(assignment.subject.subject_family, 'family_name', '') if assignment.subject.subject_family_id else ''
    if name.endswith('.csv'):
        result = _analyse_csv(uploaded, people)
        result['meta'] = {}
        result['source'] = 'csv'
    elif name.endswith(('.xlsx', '.xlsm')):
        parsed = ecr.read_workbook(uploaded)
        if senior and parsed['kind'] != 'SSHS':
            raise ecr.EcrError('This is the Grades 7 to 10 e-class record. Senior High classes use the SSHS e-class record: '
                               'download it for this class from Class records (the menu on the class).')
        if not senior and parsed['kind'] == 'SSHS':
            raise ecr.EcrError('This is the Senior High (SSHS) e-class record. Grades 7 to 10 classes use the e-class record '
                               'of their learning area: download it for this class from Class records.')
        from grades.ecr_template import sshs_subject_type
        result = ecr.analyse(parsed, period.quarter_number, subject_names=[assignment.subject.subject_name, family],
                             senior_high=senior, roster=people, mapeh=is_mapeh(assignment) and not senior,
                             subject_type=sshs_subject_type(assignment.subject) if senior else None)
        result['meta'] = parsed['meta']
        result['source'] = 'ecr'
        meta = parsed['meta']
        checks = result['checks']
        if not ecr.same_subject(meta['subject'], assignment.subject.subject_name, family, assignment.subject.subject_code,
                                junior=not senior):
            checks.insert(0, ('error', f'The file is for "{meta["subject"]}", not {assignment.subject.subject_name}.'))
        if not ecr.same_section(meta['section'], assignment.section.section_name, assignment.section.grade_level.grade_number):
            checks.insert(0, ('error', f'The file is for "{meta["section"]}", not {assignment.section.grade_level.grade_name} '
                                       f'{assignment.section.section_name}.'))
        elif not meta['section']:
            checks.append(('warn', 'The file does not say which grade and section it is for (INPUT DATA, GRADE & SECTION).'))
        years = re.findall(r'\d{4}', meta.get('school_year') or '')
        if years and assignment.school_year.year_label and not set(years) <= set(re.findall(r'\d{4}', assignment.school_year.year_label)):
            checks.append(('warn', f'The file says school year {meta["school_year"]}; this class is SY {assignment.school_year.year_label}.'))
    elif name.endswith('.xls'):
        raise ecr.EcrError('This is an old Excel file (.xls). Open it in Excel and save it as .xlsx, then upload it again.')
    else:
        raise ecr.EcrError('Upload the e-class record (.xlsx) or a CSV file.')

    # grades that may not change any more
    existing = {g['enrollment_id']: g for g in GradeComponent.objects.filter(
        enrollment__section=assignment.section, subject=assignment.subject, quarter=period).values(
        'enrollment_id', 'validation_status', 'is_locked', 'transmuted_grade', 'initial_grade')}
    if period.is_grades_locked:
        result['checks'].insert(0, ('error', f'{P.name(period)} is locked by the registrar. Its grades can no longer change.'))
    for row in result['rows']:
        old = existing.get(row.get('enrollment'))
        row['current'] = P.grade_value(old['transmuted_grade'], old['initial_grade']) if old else None
        row['frozen'] = bool(old and (old['is_locked'] or old['validation_status'] in LOCKED_STATUSES))
        row['current_status'] = old['validation_status'] if old else None
    people_by_id = {p['id']: p for p in people}
    for row in result['rows']:
        p = people_by_id.get(row.get('enrollment'))
        row['learner'] = {'id': p['id'], 'lrn': p['lrn'], 'name': display_name(p), 'sex': p['sex']} if p else None
        row['candidates'] = [dict(c, name=display_name(people_by_id[c['id']]), lrn=people_by_id[c['id']]['lrn'])
                             for c in row.get('candidates', []) if c['id'] in people_by_id]
    in_file = {row.get('enrollment') for row in result['rows'] if row.get('enrollment')}
    result['missing'] = [display_name(p) for p in people if p['active'] and p['id'] not in in_file]
    result['roster'] = [{'id': p['id'], 'name': display_name(p), 'lrn': p['lrn'], 'sex': p['sex']} for p in people if p['active']]
    return result


def _analyse_csv(uploaded, people):
    """CSV: one row per learner with LRN, name and quarterly grade (60 to 100). The LRN decides who it is."""
    raw = uploaded.read()
    if len(raw) > ecr.MAX_UPLOAD_BYTES:
        raise ecr.EcrError('The CSV file is too large.')
    text = raw.decode('utf-8-sig', errors='replace')
    reader = csv.reader(io.StringIO(text))
    header = [h.strip().lower() for h in next(reader, [])]
    def col(*names):
        return next((i for i, h in enumerate(header) if any(n in h for n in names)), None)
    i_lrn, i_name, i_grade = col('lrn'), col('name', 'learner'), col('quarterly', 'grade')
    if i_lrn is None or i_grade is None:
        raise ecr.EcrError('The CSV needs an LRN column and a quarterly grade column. Download the CSV for this class to start from.')
    by_lrn = {p['lrn']: p for p in people if p['lrn']}
    rows, n = [], 0
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        n += 1
        get = lambda i: values[i].strip() if i is not None and i < len(values) else ''
        lrn, nm, grade_text = re.sub(r'\D', '', get(i_lrn)), get(i_name), get(i_grade)
        row = {'row': n + 1, 'sex': '', 'name': nm or lrn, 'lrn': lrn, 'errors': [], 'warnings': [], 'notes': [],
               'initial': None, 'quarterly': None, 'parts': [], 'has_scores': bool(grade_text), 'candidates': [], 'reasons': []}
        grade = ecr.dec(grade_text)
        if grade_text and (grade is None or grade != grade.to_integral_value() or not 60 <= grade <= 100):
            row['errors'].append(f'"{grade_text}" is not a quarterly grade (a whole number from 60 to 100).')
        elif grade is not None:
            row['quarterly'] = int(grade)
        person = by_lrn.get(lrn)
        if not person:
            row.update(status='unmatched', enrollment=None)
            row['reasons'].append('No learner of this class has this LRN.' if lrn else 'The LRN is missing.')
        else:
            row['enrollment'] = person['id']
            row['status'] = 'matched' if not nm or ecr.name_score(nm, person) >= 90 else 'check'
            if row['status'] == 'check':
                row['reasons'].append('The LRN belongs to a learner with a different name.')
            if not person['active']:
                row['status'] = 'check'
                row['reasons'].append('This learner is no longer enrolled in the class.')
        rows.append(row)
    claimed = defaultdict(list)
    for r in rows:
        if r.get('enrollment'):
            claimed[r['enrollment']].append(r)
    for twins in claimed.values():
        if len(twins) > 1:
            for r in twins:
                r['status'] = 'check'
                r['reasons'].append('The same LRN appears more than once.')
    return {'sheets': ['CSV'], 'checks': [], 'rows': rows, 'other_periods': []}


def remember(user, payload):
    token = secrets.token_urlsafe(16)
    caches['default'].set(f'upload:{user.pk}:{token}', payload, PREVIEW_SECONDS)
    return token


def recall(user, token):
    return caches['default'].get(f'upload:{user.pk}:{token}') if token else None


def forget(user, token):
    caches['default'].delete(f'upload:{user.pk}:{token}')


# ---------------------------------------------------------------------------------------------
# saving the confirmed rows
# ---------------------------------------------------------------------------------------------

def decide(result, choices):
    """Which learner each importable row goes to, after the teacher's choices.

    choices: {str(row number): enrollment id | 'skip'} for rows the teacher had to settle (and for
    any row the teacher chose to skip). Returns (plan, problems) where plan is [(row, enrollment_id)].
    """
    active = {p['id'] for p in result['roster']}
    plan, problems, taken = [], [], {}
    for row in result['rows']:
        if row['quarterly'] is None or row['errors'] or row.get('frozen'):
            continue
        choice = choices.get(str(row['row']))
        if choice == 'skip':
            continue
        if row['status'] == 'matched' and choice in (None, '', str(row['enrollment'])):
            target = row['enrollment']
        elif choice and str(choice).isdigit():
            target = int(choice)
        else:
            problems.append(f'Row {row["row"]} ({row["name"]}): choose the learner or skip the row.')
            continue
        if target not in active:
            problems.append(f'Row {row["row"]} ({row["name"]}): that learner is not in this class.')
            continue
        if target in taken:
            problems.append(f'Rows {taken[target]} and {row["row"]} both point to the same learner.')
            continue
        taken[target] = row['row']
        plan.append((row, target))
    return plan, problems


def save(assignment, period, plan, user, source_label, ip=None):
    """Write the planned grades as drafts. Returns counts; validated or locked grades are never touched."""
    counts = {'created': 0, 'updated': 0, 'unchanged': 0, 'kept': 0}
    now = timezone.now()
    with transaction.atomic():
        current = {g.enrollment_id: g for g in GradeComponent.objects.select_for_update().filter(
            enrollment_id__in=[t for _, t in plan], subject=assignment.subject, quarter=period)}
        for row, enrollment_id in plan:
            g = current.get(enrollment_id)
            if g and (g.is_locked or g.validation_status in LOCKED_STATUSES):
                counts['kept'] += 1
                continue
            parts = [p['result'] for p in row.get('parts', []) if p and p.get('result')]
            fields = _fields(row, parts)
            fields.update(validation_status='Draft', validation_notes='', validated_by=None, validation_date=None,
                          encoded_by=user, semester=assignment.semester, remarks=_remarks(row, source_label))
            if g is None:
                GradeComponent.objects.create(enrollment_id=enrollment_id, subject=assignment.subject, quarter=period, **fields)
                counts['created'] += 1
                continue
            changed = [f for f in ('transmuted_grade', 'initial_grade') if _differs(getattr(g, f), fields[f])]
            if not changed and g.validation_status == 'Draft':
                counts['unchanged'] += 1
                continue
            for f in changed:
                GradeChangeLog.objects.create(grade_component=g, field_changed=f, old_value=str(getattr(g, f)),
                                              new_value=str(fields[f]), changed_by=user, ip_address=ip,
                                              change_reason=f'Re-uploaded from {source_label}')
            for k, v in fields.items():
                setattr(g, k, v)
            g.save()
            counts['updated'] += 1
    return counts


def _differs(a, b):
    if a is None or b is None:
        return a is not b
    return Decimal(str(a)) != Decimal(str(b))


def _fields(row, parts):
    """Model fields from a computed row. MAPEH keeps the sum of its four components' scores."""
    def total(part, key):
        values = [r[part][key] for r in parts if r[part][key] is not None]
        return sum(values) if values else None
    out = {}
    for part, prefix in (('ww', 'written_work'), ('pt', 'performance_task'), ('qa', 'quarterly_assessment')):
        raw, top = total(part, 'total'), total(part, 'hps')
        ps = [r[part]['ps'] for r in parts if r[part]['ps'] is not None]
        ws = [r[part]['ws'] for r in parts if r[part]['ws'] is not None]
        out[f'{prefix}_raw'] = raw if raw is not None else Decimal(0)
        out[f'{prefix}_max'] = top if top else Decimal(1)
        out[f'{prefix}_percent'] = ecr.xround(sum(ps) / len(ps)) if ps else None
        out[f'{prefix}_weighted'] = ecr.xround(sum(ws) / len(ws)) if ws else None
    out['initial_grade'] = row['initial'] if row['initial'] is not None else Decimal(row['quarterly'])
    out['transmuted_grade'] = row['quarterly']
    out['descriptor'] = ecr.descriptor(row['quarterly'])
    return out


def _remarks(row, source_label):
    text = f'From {source_label}'
    parts = [p for p in row.get('parts', []) if p and p.get('result') and p['result']['quarterly'] is not None]
    if len(parts) > 1:
        text += ' · ' + mapeh_remark([(p['component'], p['result']['quarterly']) for p in parts])
    return text


# ---------------------------------------------------------------------------------------------
# submitting a class to the registrar
# ---------------------------------------------------------------------------------------------

def submit(assignment, period, user):
    """Draft (or corrected) grades of a complete class go to the registrar. Returns (ok, message)."""
    if period.is_grades_locked:
        return False, f'{P.name(period)} is locked.'
    total = Enrollment.objects.filter(section=assignment.section, school_year=assignment.school_year, status__in=ACTIVE).count()
    grades = GradeComponent.objects.filter(enrollment__section=assignment.section, enrollment__status__in=ACTIVE,
                                           subject=assignment.subject, quarter=period)
    graded = grades.count()
    if graded < total:
        return False, f'{total - graded} learner{"s" if total - graded != 1 else ""} still {"have" if total - graded != 1 else "has"} no {P.name(period)} grade.'
    moved = grades.filter(validation_status__in=('Draft', 'Returned')).update(validation_status='Submitted', updated_at=timezone.now())
    if not moved:
        return False, 'There is nothing new to submit.'
    return True, f'{moved} grade{"s" if moved != 1 else ""} submitted to the registrar.'
