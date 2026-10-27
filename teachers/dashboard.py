"""Teacher dashboard: what needs the teacher now, how each class is doing, who may need help, and assessments.

Grades are the quarterly (transmuted) grades of the school year's periods. Each class is shown for the
current period, or for its latest earlier period when the current one has no grades yet.
"""
from collections import defaultdict
from datetime import timedelta
from statistics import mean

from django.urls import reverse
from django.utils import timezone

from assessments import quizzes as Q
from core import grading_policy as policy
from core import periods as P
from grades.models import GradeComponent

from . import records as R

# one color per level slot, lowest to highest, whatever the school's DepEd order names the level (as on the School Head pages)
LEVEL_COLORS = {'advanced': '#2E7D32', 'proficient': '#123499', 'approaching': '#1565C0', 'developing': '#E65100', 'beginning': '#C62828'}
DROP = 5        # points down from the previous period that are worth a look even when the grade still passes


def descriptors():
    """The descriptors of the school's DepEd order (core/grading_policy.py), highest first: (key, name, lowest grade, color)."""
    return [(lv['key'], lv['name'], lv['min'], LEVEL_COLORS[lv['key']]) for lv in policy.levels()]


def descriptor(grade):
    return policy.level_of(grade)['key']


def _where(a):
    return f'{a.section.grade_level.grade_name} {a.section.section_name} · {a.subject.subject_code}'


def _class_url(a):
    return f'{reverse("teachers:class_record_list")}#class-{a.id}'


def build(user, school, periods, current, assignments):
    passing = float(getattr(school, 'passing_grade', None) or 75)
    overview = R.overview(assignments, periods, current) if assignments else []
    keys = {(a.section_id, a.subject_id) for a in assignments}
    grades, people = defaultdict(lambda: defaultdict(dict)), {}
    if assignments:
        for e_id, sec, subj, q_id, transmuted, initial, last, first in GradeComponent.objects.filter(
                P.HAS_GRADE, enrollment__section_id__in={a.section_id for a in assignments}, enrollment__status__in=R.ACTIVE,
                subject_id__in={a.subject_id for a in assignments}, quarter__in=periods).values_list(
                'enrollment_id', 'enrollment__section_id', 'subject_id', 'quarter_id', 'transmuted_grade', 'initial_grade',
                'enrollment__student__last_name', 'enrollment__student__first_name'):
            if (sec, subj) in keys:
                grades[(sec, subj)][q_id][e_id] = P.grade_value(transmuted, initial)
                people[e_id] = f'{last}, {first}'

    classes, support = [], []
    for row in overview:
        a, cur = row['assignment'], row['current']
        own = P.for_class(a, periods)
        g = grades.get((a.section_id, a.subject_id), {})
        upto = [p for p in own if not current or p.quarter_number <= current.quarter_number]
        graded = [p for p in upto if g.get(p.id)]
        focus = graded[-1] if graded else None
        before = graded[-2] if len(graded) > 1 else None
        values = list(g[focus.id].values()) if focus else []
        avg = mean(values) if values else None
        prev_avg = mean(g[before.id].values()) if before else None
        label, tone, hint = R.STATE_INFO[row['state']]
        classes.append({
            'id': a.id, 'name': f'{a.section.grade_level.grade_name} {a.section.section_name}', 'subject': a.subject.subject_name,
            'code': a.subject.subject_code, 'learners': row['learners'], 'url': _class_url(a),
            'focus': P.name(focus) if focus else '', 'focus_is_current': bool(focus and current and focus.id == current.id),
            'average': round(avg, 1) if avg is not None else None,
            'change': round(avg - prev_avg, 1) if avg is not None and prev_avg is not None else None, 'before': P.short(before),
            'below': sum(1 for v in values if v < passing), 'graded': cur['graded'] if cur else 0, 'total': cur['total'] if cur else row['learners'],
            'state': row['state'], 'state_label': label, 'state_tone': tone, 'state_hint': hint,
            'levels': [{'key': key, 'label': name, 'color': color, 'count': n, 'percent': round(n * 100 / len(values), 1) if values else 0}
                       for key, name, low, color in descriptors() for n in [sum(1 for v in values if descriptor(v) == key)]],
        })
        for e_id, value in (g[focus.id].items() if focus else []):
            prev = g[before.id].get(e_id) if before else None
            change = round(value - prev, 1) if prev is not None else None
            if value < passing or (change is not None and change <= -DROP):
                support.append({'name': people.get(e_id, ''), 'class': _where(a), 'section': a.section.section_name, 'code': a.subject.subject_code,
                                'period': P.short(focus), 'grade': round(value, 2), 'previous': prev, 'change': change, 'url': _class_url(a),
                                'reason': f'Below {passing:g}' if value < passing else f'Down {abs(change):g} points since {P.short(before)}'})
    support.sort(key=lambda s: (s['grade'], s['change'] if s['change'] is not None else 0, s['name']))

    assessments = Q.list_rows(user)
    now = timezone.now()
    open_rows = sorted((r for r in assessments if r['state'] == 'open'), key=lambda r: r['deadline_sort'])
    recent = sorted((r for r in assessments if r['state'] == 'closed' and r['assessment'].closes_at
                     and r['assessment'].closes_at >= now - timedelta(days=30)),
                    key=lambda r: r['assessment'].closes_at, reverse=True)[:3]

    todo = _todo(overview, current, assessments, now)
    learners = sum({c['assignment'].section_id: c['learners'] for c in overview}.values())
    graded = sum(c['current']['graded'] for c in overview if c['current'])
    expected = sum(c['current']['total'] for c in overview if c['current'])
    days_left, overdue = P.deadline_info(current) if current else (None, False)
    return {
        'classes': classes, 'support': support, 'todo': todo[:8], 'todo_more': max(0, len(todo) - 8),
        'open_assessments': open_rows[:5], 'open_count': len(open_rows), 'recent_assessments': recent,
        'closing_soon': sum(1 for r in open_rows if r['assessment'].closes_at and r['assessment'].closes_at - now <= timedelta(hours=48)),
        'draft_count': sum(1 for r in assessments if r['state'] == 'draft'),
        'learners': learners, 'graded': graded, 'expected': expected,
        'graded_percent': round(graded * 100 / expected) if expected else 0,
        'submitted_classes': sum(1 for c in overview if c['state'] in ('submitted', 'validated', 'locked')),
        'class_count': len(overview), 'days_left': days_left, 'overdue': overdue,
        'deadline': current.grade_encoding_deadline if current else None, 'current_name': P.name(current),
        'descriptors': [{'label': lv['name'], 'color': LEVEL_COLORS[lv['key']], 'range': lv['range'].replace(' to ', '–')}
                        for lv in policy.levels()],
        'passing': passing,
    }


def _todo(overview, current, assessments, now):
    """What needs the teacher, most urgent first: (tone, icon, title, detail, url)."""
    items = []
    days_left, overdue = P.deadline_info(current) if current else (None, False)
    due = P.due_text(current).strip() if current else ''
    for row in overview:
        a, cur = row['assignment'], row['current']
        if row['state'] == 'returned':
            items.append((0, 'risk', 'fi-rr-undo', f'Correct and resubmit {_where(a)}', 'The registrar returned these grades for correction.', _class_url(a)))
        elif row['state'] in ('not_started', 'encoding') and cur and cur['total']:
            missing = cur['total'] - cur['graded']
            urgent = overdue or (days_left is not None and days_left <= 7)
            items.append((1 if urgent else 3, 'warn' if urgent else 'info', 'fi-rr-time-quarter-past',
                          f'Enter grades for {missing} learner{"s" if missing != 1 else ""}: {_where(a)}',
                          f'{missing} of {cur["total"]} still have no {P.name(current)} grade. {due}'.strip(), _class_url(a)))
        elif row['state'] == 'ready':
            items.append((2, 'info', 'fi-rr-paper-plane', f'Submit {_where(a)} to the registrar',
                          f'Every learner has a {P.name(current)} grade. {due}'.strip(), _class_url(a)))
    for r in assessments:
        a = r['assessment']
        url = reverse('assessments:detail', args=[a.id])
        if r['state'] == 'open' and a.closes_at and a.closes_at - now <= timedelta(hours=48) and r['missing']:
            when = timezone.localtime(a.closes_at).strftime('%b %d, %I:%M %p').replace(' 0', ' ')
            items.append((2, 'warn', 'fi-rr-alarm-clock', f'"{a.title}" closes {when}', f'{r["submitted"]} of {r["enrolled"]} learners in {r["section"]} have answered.', url))
        elif r['state'] == 'draft':
            items.append((4, 'muted', 'fi-rr-edit', f'Finish "{a.title}"', f'It is still a draft, so {r["section"]} cannot answer it yet.', url))
    items.sort(key=lambda i: i[0])
    return [{'tone': tone, 'icon': icon, 'title': title, 'detail': detail, 'url': url} for _, tone, icon, title, detail, url in items]
