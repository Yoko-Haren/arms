"""Where a class stands with its grades in one period, and the checks the registrar sees before validating.

Teacher, registrar and principal pages describe a class's grades with the same states:

    not_started   no learner has a grade yet
    encoding      some learners still have no grade
    ready         every learner has a grade, but the teacher has not submitted them (drafts)
    submitted     the teacher submitted every grade; the registrar can validate them
    returned      the registrar sent the grades back for correction
    validated     the registrar validated every grade
    locked        the period is locked and its grades are final

review_classes() runs the automatic checks: every enrolled learner graded and submitted, every grade a
valid quarterly grade that follows from its own scores, saved by the class teacher, and no change from
the previous period big enough to suggest scores typed into another learner's row.
"""
import re
from collections import defaultdict
from decimal import Decimal
from statistics import mean

from django.utils import timezone

from academics.models import Quarter
from core import periods as P
from enrollment.models import Enrollment
from grades import ecr
from grades.models import GradeChangeLog, GradeComponent

ACTIVE = ('Enrolled', 'Transferred_In')
BIG_CHANGE = 15            # points between two periods that call for a second look
MANY_BELOW = 0.30          # share of a class below passing that calls for a second look
MAPEH_NAMES = (('MUSIC', 'Music'), ('ARTS', 'Arts'), ('PE', 'PE'), ('HEALTH', 'Health'))
_MAPEH_PART = re.compile(r'\b(Music|Arts|PE|Physical Education|Health) (\d{2,3})\b', re.IGNORECASE)
LEFT_WORDS = {'Transferred_Out': 'transferred out', 'Dropped': 'dropped', 'Graduated': 'graduated',
              'Inactive': 'inactive', 'Deceased': 'deceased'}


def class_state(enrolled, statuses, locked=False):
    """One word for where a class stands in a period. statuses: {validation_status: count} of its enrolled learners."""
    graded = sum(statuses.values())
    if locked and graded:
        return 'locked'
    if statuses.get('Returned'):
        return 'returned'
    if not graded:
        return 'not_started'
    if graded < enrolled:
        return 'encoding'
    if statuses.get('Draft'):
        return 'ready'
    if statuses.get('Submitted'):
        return 'submitted'
    return 'validated'


def is_mapeh(assignment):
    """A combined MAPEH class (Grades 7 to 10): its grade is the rounded average of Music, Arts, PE and Health."""
    if assignment.section.grade_level.is_senior_high:
        return False
    s = assignment.subject
    family = s.subject_family.family_name if s.subject_family_id else ''
    return any(re.search(r'\bMAPEH\b', (text or '').upper()) for text in (s.subject_name, family, s.subject_code))


def mapeh_remark(parts):
    """'Music 85, Arts 88, PE 90, Health 87' from [(component, grade)], kept with a MAPEH grade for later checks."""
    names = dict(MAPEH_NAMES)
    return ', '.join(f'{names.get(ecr.mapeh_part(component) or "", component.title())} {grade}' for component, grade in parts)


def mapeh_parts(remarks):
    """The four component grades written by mapeh_remark(), or None when they are not all there."""
    found = {ecr.mapeh_part(name): int(grade) for name, grade in _MAPEH_PART.findall(remarks or '')}
    if not all(key in found for key, _ in MAPEH_NAMES):
        return None
    return [found[key] for key, _ in MAPEH_NAMES]


def recompute(g, mapeh=False):
    """(quarterly grade, initial grade) that a record's own numbers give, or None when they cannot be recomputed.

    A grade saved from an e-class record keeps its weighted scores and initial grade: the initial grade is the
    sum of the weighted scores and the quarterly grade its transmutation (DepEd Order No. 8, s. 2015). A MAPEH
    grade is the rounded average of its four components. A record whose initial grade equals its quarterly
    grade was entered as a quarterly grade only, so there is nothing to recompute.
    """
    quarterly, initial = g['transmuted_grade'], g['initial_grade']
    if mapeh:
        parts = mapeh_parts(g.get('remarks'))
        return (int(ecr.xround(Decimal(sum(parts)) / 4, 0)), None) if parts else None
    if quarterly is None or initial is None or Decimal(initial) == Decimal(quarterly):
        return None
    weighted = [g.get(f) for f in ('written_work_weighted', 'performance_task_weighted', 'quarterly_assessment_weighted')]
    if any(w is not None for w in weighted):
        initial = ecr.xround(sum((Decimal(w) for w in weighted if w is not None), Decimal(0)))
    return ecr.transmute(Decimal(initial)), Decimal(initial)


def _s(n, many='s', one=''):
    return one if n == 1 else many


def _num(value):
    if value is None:
        return '—'
    value = float(value)
    return str(int(value)) if value == int(value) else f'{value:.2f}'


def _learner(e):
    return f"{e['student__last_name']}, {e['student__first_name']}"


def _person(first, last, username):
    return f'{first} {last}'.strip() or username or 'someone'


def review_classes(assignments, period, passing=75):
    """The state and automatic checks of each class's grades in one period, in a few queries: {assignment id: review}."""
    assignments = list(assignments)
    if not assignments or period is None:
        return {}
    sections = {a.section_id for a in assignments}
    subjects = {a.subject_id for a in assignments}
    pairs = {(a.section_id, a.subject_id) for a in assignments}

    people, roster = {}, defaultdict(list)
    for e in Enrollment.objects.filter(section_id__in=sections, school_year_id=period.school_year_id).values(
            'id', 'section_id', 'status', 'student__last_name', 'student__first_name', 'student__lrn') \
            .order_by('student__last_name', 'student__first_name'):
        people[e['id']] = e
        if e['status'] in ACTIVE:
            roster[e['section_id']].append(e['id'])

    grades = defaultdict(list)
    for g in GradeComponent.objects.filter(quarter=period, enrollment__section_id__in=sections, subject_id__in=subjects).values(
            'id', 'enrollment_id', 'enrollment__section_id', 'subject_id', 'validation_status', 'validation_notes',
            'transmuted_grade', 'initial_grade', 'written_work_percent', 'performance_task_percent',
            'quarterly_assessment_percent', 'written_work_weighted', 'performance_task_weighted',
            'quarterly_assessment_weighted', 'encoded_by_id', 'encoded_by__first_name', 'encoded_by__last_name',
            'encoded_by__username', 'remarks', 'updated_at'):
        key = (g['enrollment__section_id'], g['subject_id'])
        if key in pairs:
            grades[key].append(g)

    previous_period = Quarter.objects.filter(school_year_id=period.school_year_id, quarter_number__lt=period.quarter_number) \
        .order_by('-quarter_number').first()
    previous = {}
    if previous_period:
        for r in GradeComponent.objects.filter(quarter=previous_period, enrollment__section_id__in=sections,
                                               subject_id__in=subjects).values('enrollment_id', 'subject_id', 'transmuted_grade', 'initial_grade'):
            previous[(r['enrollment_id'], r['subject_id'])] = P.grade_value(r['transmuted_grade'], r['initial_grade'])

    edits = defaultdict(list)
    for c in GradeChangeLog.objects.filter(grade_component__quarter=period, grade_component__enrollment__section_id__in=sections,
                                           grade_component__subject_id__in=subjects, field_changed='transmuted_grade') \
            .values('grade_component_id', 'old_value', 'new_value', 'created_at', 'changed_by__first_name',
                    'changed_by__last_name', 'changed_by__username').order_by('created_at'):
        edits[c['grade_component_id']].append(c)

    return {a.id: _review(a, period, previous_period, people, roster[a.section_id], grades.get((a.section_id, a.subject_id), []),
                          previous, edits, passing) for a in assignments}


def _review(a, period, previous_period, people, active_ids, rows, previous, edits, passing):
    mapeh = is_mapeh(a)
    active = set(active_ids)
    mine = {g['enrollment_id']: g for g in rows if g['enrollment_id'] in active}
    left = [g for g in rows if g['enrollment_id'] not in active]
    statuses = defaultdict(int)
    for g in mine.values():
        statuses[g['validation_status']] += 1
    state = class_state(len(active_ids), statuses, period.is_grades_locked)
    word, n = P.name(period), len(active_ids)
    teacher = (a.teacher.get_full_name() or a.teacher.username) if a.teacher_id else ''
    checks, flags = [], defaultdict(list)

    def add(key, level, title, detail='', items=()):
        checks.append({'key': key, 'level': level, 'title': title, 'detail': detail, 'items': list(items)})

    def name(eid):
        return _learner(people[eid])

    # 1. every enrolled learner has a grade
    missing = [eid for eid in active_ids if eid not in mine]
    if not n:
        add('complete', 'error', 'No learners enrolled', 'This section has no enrolled learners, so there is nothing to validate.')
    elif missing:
        add('complete', 'error', f'{len(missing)} learner{_s(len(missing))} without a grade',
            f'Every enrolled learner needs a {word} grade before the class can be validated.', [name(e) for e in missing])
    else:
        add('complete', 'ok', 'Every learner has a grade', f'{n} of {n} enrolled learners.')

    # 2. the teacher submitted them
    if statuses.get('Returned'):
        note = next((g['validation_notes'] for g in mine.values() if g['validation_status'] == 'Returned' and g['validation_notes']), '')
        add('submitted', 'error', 'Returned to the teacher',
            'Waiting for the corrected grades.' + (f' Note sent: "{note}"' if note else ''))
    elif statuses.get('Draft'):
        d = statuses['Draft']
        add('submitted', 'error', 'Not submitted by the teacher',
            f'{d} grade{_s(d)} {_s(d, "are", "is")} still {_s(d, "drafts", "a draft")}. '
            'The teacher submits them from Class Records once they are final.')
    elif mine:
        add('submitted', 'ok', 'Submitted by the teacher', teacher)

    # 3. every grade is a quarterly grade from 60 to 100
    values, invalid = {}, []
    for eid, g in mine.items():
        q = g['transmuted_grade']
        if q is None:
            invalid.append(f'{name(eid)}: no quarterly grade (initial grade {_num(g["initial_grade"])})')
            flags[eid].append(('error', 'No quarterly grade'))
        elif not 60 <= q <= 100:
            invalid.append(f'{name(eid)}: {q}')
            flags[eid].append(('error', 'Outside 60 to 100'))
        value = P.grade_value(q, g['initial_grade'])
        if value is not None:
            values[eid] = value
    if invalid:
        add('range', 'error', f'{len(invalid)} grade{_s(len(invalid))} {_s(len(invalid), "are", "is")} not a valid quarterly grade',
            'A quarterly grade is a whole number from 60 to 100, after transmutation.', invalid)
    elif values:
        add('range', 'ok', 'Valid quarterly grades', f'Whole numbers from {_num(min(values.values()))} to {_num(max(values.values()))}.')

    # 4. each grade follows from its own scores
    checked, wrong = 0, []
    for eid, g in mine.items():
        result = recompute(g, mapeh)
        if result is None:
            continue
        checked += 1
        expected, initial = result
        if expected != g['transmuted_grade'] or (initial is not None and Decimal(initial) != Decimal(g['initial_grade'])):
            got = f'saved {_num(g["transmuted_grade"])}' + (f' (initial {_num(g["initial_grade"])})' if initial is not None else '')
            wrong.append(f'{name(eid)}: the scores give {_num(expected)}' + (f' (initial {_num(initial)})' if initial is not None else '') + f', {got}')
            flags[eid].append(('error', f'Scores give {_num(expected)}'))
    source = 'Music, Arts, PE and Health' if mapeh else 'the written work, performance task and quarterly assessment scores'
    if wrong:
        add('computed', 'error', f'{len(wrong)} grade{_s(len(wrong))} {_s(len(wrong), "do", "does")} not follow from the scores',
            'A MAPEH grade is the rounded average of Music, Arts, PE and Health.' if mapeh else
            'The quarterly grade is the transmuted initial grade, and the initial grade is the sum of the weighted scores '
            '(DepEd Order No. 8, s. 2015).', wrong)
    elif checked:
        add('computed', 'ok', 'Grades follow from the scores',
            f'ARMS recomputed {checked} of {len(mine)} grade{_s(len(mine))} from {source}; {_s(checked, "all match", "it matches")}.')
    elif mine:
        add('computed', 'info', 'Grades cannot be recomputed',
            'These grades were not saved from an e-class record with scores (for example, a CSV upload), so ARMS '
            'cannot recompute them. Compare them with the teacher\'s class record.')

    # 5. no change from the previous period big enough to suggest another learner's scores
    compared, moved = 0, []
    if previous_period:
        for eid, value in values.items():
            before = previous.get((eid, a.subject_id))
            if before is None:
                continue
            compared += 1
            change = value - before
            if abs(change) >= BIG_CHANGE:
                moved.append(f'{name(eid)}: {_num(before)} to {_num(value)} ({change:+.0f})')
                flags[eid].append(('warn', f'{change:+.0f} since {P.short(previous_period)}'))
        if moved:
            add('changes', 'warn', f'{len(moved)} big change{_s(len(moved))} since {P.name(previous_period)}',
                f'A change of {BIG_CHANGE} points or more can mean scores were typed into another learner\'s row. '
                'Compare these with the class record.', moved)
        elif compared:
            add('changes', 'ok', f'No big changes since {P.name(previous_period)}',
                f'No learner moved {BIG_CHANGE} points or more ({compared} compared).')

    # 6. saved by the class teacher
    others, unknown = defaultdict(int), 0
    for eid, g in mine.items():
        if g['encoded_by_id'] is None:
            unknown += 1
        elif g['encoded_by_id'] != a.teacher_id:
            who = _person(g['encoded_by__first_name'], g['encoded_by__last_name'], g['encoded_by__username'])
            others[who] += 1
            flags[eid].append(('warn', f'Saved by {who}'))
    if others or unknown:
        parts = [f'{k} by {who}' for who, k in others.items()]
        if unknown:
            parts.append(f'{unknown} with no record of who saved {_s(unknown, "them", "it")}')
        total = sum(others.values()) + unknown
        add('teacher', 'warn', f'{total} grade{_s(total)} not saved by the class teacher',
            (f'The class teacher is {teacher}. ' if teacher else 'The class has no teacher assigned. ') + '; '.join(parts) + '.')
    elif mine:
        add('teacher', 'ok', 'Saved by the class teacher', teacher)

    # 7. results that usually mean a slip
    grades_only = list(values.values())
    below = sum(1 for v in grades_only if v < passing)
    if len(grades_only) >= 5 and len(set(grades_only)) == 1:
        add('spread', 'warn', f'Every learner has the same grade ({_num(grades_only[0])})',
            'Identical grades usually mean a placeholder or a copied column.')
    elif len(grades_only) >= 5 and below / len(grades_only) >= MANY_BELOW:
        add('spread', 'warn', f'{below} of {len(grades_only)} learners below {_num(passing)}',
            'An unusually large share. Make sure the highest possible scores and answer keys are right before validating.')
    elif grades_only:
        add('spread', 'ok', 'Class results look usual',
            f'Average {mean(grades_only):.1f}; {below} of {len(grades_only)} below {_num(passing)}.')

    # 8. grades of learners who left (not counted, not validated)
    if left:
        add('left', 'info', f'{len(left)} grade{_s(len(left))} of learners who left the class',
            'They are not counted and are not validated with the class.',
            [f'{name(g["enrollment_id"])} ({LEFT_WORDS.get(people[g["enrollment_id"]]["status"], "not enrolled")})'
             for g in left if g['enrollment_id'] in people])

    # 9. grades changed after they were first saved
    changed = [(eid, edits[g['id']]) for eid, g in mine.items() if edits.get(g['id'])]
    if changed:
        items = []
        for eid, history in changed:
            last = history[-1]
            who = _person(last['changed_by__first_name'], last['changed_by__last_name'], last['changed_by__username'])
            items.append(f'{name(eid)}: {history[0]["old_value"]} to {last["new_value"]}, '
                         f'{len(history)} change{_s(len(history))}, last by {who} on {timezone.localtime(last["created_at"]):%b %d}')
        add('edits', 'info', f'{len(changed)} grade{_s(len(changed))} changed after first saved',
            'Every change is kept in the grade history.', items)

    errors = sum(1 for c in checks if c['level'] == 'error')
    warnings = sum(1 for c in checks if c['level'] == 'warn')
    learners = []
    for eid in active_ids:
        g = mine.get(eid)
        before = previous.get((eid, a.subject_id))
        value = values.get(eid)
        learners.append({
            'id': eid, 'name': name(eid), 'lrn': people[eid]['student__lrn'] or '', 'grade': value,
            'initial': g['initial_grade'] if g else None, 'status': g['validation_status'] if g else '',
            'ww': g['written_work_percent'] if g else None, 'pt': g['performance_task_percent'] if g else None,
            'qa': g['quarterly_assessment_percent'] if g else None, 'previous': before,
            'change': round(value - before, 2) if value is not None and before is not None else None,
            'flags': flags.get(eid, []), 'remarks': g['remarks'] if g else '',
        })
    return {
        'state': state, 'statuses': dict(statuses), 'enrolled': n, 'graded': len(mine), 'missing': len(missing),
        'checks': checks, 'errors': errors, 'warnings': warnings, 'mapeh': mapeh,
        'can_validate': state == 'submitted' and not errors,
        'average': round(mean(grades_only), 2) if grades_only else None, 'below': below, 'passed': len(grades_only) - below,
        'learners': learners, 'previous_period': previous_period, 'teacher': teacher,
        'note': next((g['validation_notes'] for g in mine.values() if g['validation_notes']), ''),
        'last_saved': max((g['updated_at'] for g in mine.values()), default=None),
    }
