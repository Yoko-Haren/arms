"""Teacher: My Advisory, every subject's grades for the section the teacher advises.

Subject teachers upload the grades of their own classes; the adviser follows the whole section here: each learner's
grade in every subject for one grading period, who is below 75 and in how many learning areas, which subjects still
have no grades, and each learner's record for the school year (every subject and period, the grade components and the
general average). Only the section's adviser can open it. The School Head reviews the school by discipline on the
Academic Dashboard; following each learner is the adviser's. Levels follow the school's DepEd order (core/grading_policy.py).
"""
from collections import defaultdict
from statistics import mean

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from academics.models import Section
from core import grading_policy as policy
from core import periods as P
from enrollment.models import Enrollment
from grades.models import GradeComponent
from scheduling.models import ClassAssignment

from . import records as R
from .views_records import _denied, _teacher, teacher_context


def _num(value):
    return round(float(value), 1) if value is not None else None


@login_required
def advisory(request):
    if not _teacher(request):
        return _denied(request)
    school, sy, periods, current, _ = teacher_context(request)
    sections = list(Section.objects.filter(school_year=sy, school=school, adviser=request.user, is_active=True)
                    .select_related('grade_level', 'strand').order_by('grade_level__sort_order', 'section_name')) if sy else []
    section = next((s for s in sections if str(s.id) == request.GET.get('section')), None) or (sections[0] if sections else None)
    context = {'school': school, 'sy': sy, 'sections': sections, 'section': section}
    if section is None:
        return render(request, 'teachers/advisory.html', context)

    enrollments = list(Enrollment.objects.filter(section=section, school_year=sy, status__in=R.ACTIVE).select_related('student')
                       .order_by('student__last_name', 'student__first_name'))
    assignments = list(ClassAssignment.objects.filter(section=section, school_year=sy, is_active=True)
                       .select_related('section', 'section__grade_level', 'subject', 'teacher', 'semester', 'school_year')
                       .order_by('subject__subject_code'))
    records = defaultdict(dict)          # enrollment -> (subject, period) -> (grade, ww, pt, qa)
    for e_id, subject_id, period_id, transmuted, initial, ww, pt, qa in GradeComponent.objects.filter(
            P.HAS_GRADE, enrollment__in=enrollments, quarter__in=periods).values_list(
            'enrollment_id', 'subject_id', 'quarter_id', 'transmuted_grade', 'initial_grade', 'written_work_percent',
            'performance_task_percent', 'quarterly_assessment_percent'):
        records[e_id][(subject_id, period_id)] = (P.grade_value(transmuted, initial), _num(ww), _num(pt), _num(qa))

    # the period shown: the one asked for, else the current one when it has grades, else the latest with grades
    with_grades = {period_id for r in records.values() for _, period_id in r}
    period = next((p for p in periods if str(p.id) == request.GET.get('period')), None) or \
        (current if current and current.id in with_grades else next((p for p in reversed(periods) if p.id in with_grades), current))
    own = {a.id: P.for_class(a, periods) for a in assignments}
    subjects = [a for a in assignments if period and period in own[a.id]]
    progress = {row['assignment'].id: row['current'] for row in R.overview(subjects, periods, period)} if subjects else {}
    columns = []
    for a in subjects:
        cell = progress.get(a.id) or {}
        label = R.STATE_INFO[cell.get('state', 'not_started')]
        columns.append({'code': a.subject.subject_code, 'name': a.subject.subject_name, 'teacher': a.teacher.get_full_name() if a.teacher else '',
                        'graded': cell.get('graded', 0), 'total': cell.get('total', len(enrollments)), 'average': cell.get('average'),
                        'below': cell.get('below', 0), 'state': cell.get('state', 'not_started'), 'state_label': label[0], 'tone': label[1]})

    # one row per learner for the period, and each learner's record for the school year (the dialog)
    senior = section.grade_level.is_senior_high
    learners, record = [], []
    for e in enrollments:
        st, mine = e.student, records.get(e.id, {})
        grades = [mine.get((a.subject_id, period.id), (None,))[0] for a in subjects]
        present = [g for g in grades if g is not None]
        below = [a.subject.subject_code for a, g in zip(subjects, grades) if g is not None and g < policy.PASSING]
        average = round(mean(present), 1) if present else None
        learners.append({
            'name': f'{st.last_name}, {st.first_name}' + (f' {st.middle_name[0]}.' if st.middle_name else ''), 'lrn': st.lrn or '',
            'sex': st.sex, 'grades': grades, 'average': average, 'level': policy.level_of(average) if average is not None else None,
            'graded': len(present), 'below': below,
            # DepEd Order No. 8, s. 2015: below 75 in one or two learning areas, remedial classes; three or more, retention (Grades 7 to 10)
            'outlook': '' if not below else ('remedial' if senior or len(below) <= 2 else 'retention'),
        })
        rows = []
        for a in assignments:
            values = [mine.get((a.subject_id, p.id), (None,))[0] if p in own[a.id] else None for p in periods]
            parts = mine.get((a.subject_id, period.id)) if period else None
            rows.append({'code': a.subject.subject_code, 'name': a.subject.subject_name, 'grades': values,
                         'final': P.final_grade([v for v, p in zip(values, periods) if p in own[a.id]], len(own[a.id])),
                         'parts': list(parts[1:]) if parts else None})
        averages = []
        for i in range(len(periods)):
            values = [r['grades'][i] for r in rows if r['grades'][i] is not None]
            averages.append(round(mean(values), 1) if values else None)
        record.append({'rows': rows, 'averages': averages})

    graded = [l for l in learners if l['average'] is not None]
    average = round(mean(l['average'] for l in graded), 1) if graded else None
    needs = sorted((dict(l, index=i) for i, l in enumerate(learners) if l['below']),
                   key=lambda l: (-len(l['below']), l['average'] if l['average'] is not None else 100, l['name']))
    context.update({
        'periods': periods, 'period': period, 'current': current, 'period_name': P.name(period),
        'columns': columns, 'learners': learners, 'needs': needs, 'average': average,
        'level': policy.level_of(average) if average is not None else None,
        'below_count': len(needs), 'retention': sum(1 for l in needs if l['outlook'] == 'retention'),
        'uploaded': sum(1 for c in columns if c['graded']), 'complete': sum(1 for c in columns if c['total'] and c['graded'] >= c['total']),
        'senior': senior, 'components': policy.components(),
        'record': {'periods': [{'label': p.quarter_label, 'name': P.name(p)} for p in periods],
                   'period': period.quarter_label if period else '', 'learners': record,
                   'people': [{'name': l['name'], 'lrn': l['lrn'], 'sex': l['sex']} for l in learners]},
    })
    return render(request, 'teachers/advisory.html', context)
