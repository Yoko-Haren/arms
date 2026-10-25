"""School Head: School Performance, the whole school across every learning area and grade level.

The Academic Dashboard looks at one discipline or subject at a time; this page answers the wider
questions for one grading period: how the school is doing overall, which learning areas and grade
levels need attention, who is on track for promotion, how enrollment has moved over the years, and
how this period compares with the same period last school year. Grades are the quarterly grades the
dashboard uses (core.periods.GRADE: the transmuted grade), so the two pages agree.
"""
from collections import defaultdict
from datetime import date
from statistics import mean

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode

from academics.models import GradeLevel, Quarter, SchoolYear, Section, Subject
from attendance.models import AttendanceSummary
from core import grading_policy as policy
from core.caching import cache_page_for_user, remember_filters
from core.periods import GRADE, HAS_GRADE
from core.xlsx import Report, safe_filename
from enrollment.models import Enrollment
from grades.models import GradeComponent

from . import forecasts, insights
from .insights import PASSING, level_of
from .views_academic import ACTIVE, _default_period, _denied, _head_school, _person, _r1, period_name, school_fingerprint

# Honors follow the school's DepEd order (core/grading_policy.py): DepEd Order No. 36, s. 2016 (a quarterly average of 90 or
# more, a whole number, with every learning area passed) or the Academic Excellence Award of DepEd Order No. 015, s. 2026
# (90 or more with no grade below 80; counted here as on track, since the award is given at the end of the school year).
# DepEd Order No. 8, s. 2015: below 75 in one or two learning areas means remedial classes; three or more, retention (Grades 4 to 10).
# Senior High learners below 75 in a subject take remedial classes or retake it, so they are never counted for retention.
OUTLOOK = (
    {'key': 'on_track', 'name': 'On track', 'hint': 'No grade below 75', 'tone': 'good'},
    {'key': 'remedial', 'name': 'Remedial classes', 'hint': 'Below 75 in one or two learning areas, or in any Senior High subject', 'tone': 'warn'},
    {'key': 'retention', 'name': 'At risk of retention', 'hint': 'Below 75 in three or more learning areas (Grades 7 to 10)', 'tone': 'risk'},
)


def _pct(part, whole):
    return round(100 * part / whole, 1) if whole else None


def _months(period):
    """Calendar months that belong to a grading period: those whose 15th falls inside it."""
    if not period:
        return []
    months, y, m = [], period.date_start.year, period.date_start.month
    while (y, m) <= (period.date_end.year, period.date_end.month):
        if period.date_start <= date(y, m, 15) <= period.date_end:
            months.append(m)
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return months or [period.date_start.month]


def _grades(school, sy, period, grade_level=None):
    """Every quarterly grade of one grading period: (enrollment, last, first, section, section name, grade level, subject, grade)."""
    if not (sy and period):
        return []
    qs = GradeComponent.objects.filter(HAS_GRADE, quarter=period, enrollment__school_year=sy, enrollment__status__in=ACTIVE,
                                       enrollment__section__school=school)
    if grade_level:
        qs = qs.filter(enrollment__section__grade_level=grade_level)
    return [(e, last, first, sec, sec_name, gl, subj, float(g)) for e, last, first, sec, sec_name, gl, subj, g in qs.values_list(
        'enrollment_id', 'enrollment__student__last_name', 'enrollment__student__first_name', 'enrollment__section_id',
        'enrollment__section__section_name', 'enrollment__section__grade_level_id', 'subject_id', GRADE)]


def _learners(rows, senior):
    """One entry per learner: quarterly average, subjects below 75, promotion outlook and honors."""
    by = {}
    for e, last, first, sec, sec_name, gl, subj, g in rows:
        learner = by.get(e)
        if learner is None:
            learner = by[e] = {'id': e, 'name': f'{last}, {first}', 'section_id': sec, 'section': sec_name, 'grade_level_id': gl,
                               'grades': [], 'failing': []}
        learner['grades'].append(g)
        if g < PASSING:
            learner['failing'].append((subj, g))
    for learner in by.values():
        learner['average'] = mean(learner['grades'])
        learner['whole'] = int(learner['average'] + 0.5)          # reported as a whole number, rounded half up
        failing = len(learner['failing'])
        learner['outlook'] = 'on_track' if not failing else ('remedial' if senior.get(learner['grade_level_id']) or failing <= 2 else 'retention')
        award = policy.award_of(learner['whole'], policy.whole(min(learner['grades'])))
        learner['honor'] = award[0] if award else None
    return by


def _summary(rows, learners):
    """Average, passing-all rate and honors rate of one grading period, for comparisons."""
    if not rows:
        return None
    n = len(learners)
    return {
        'average': mean(r[-1] for r in rows),
        'passing_all': _pct(sum(1 for l in learners.values() if l['outlook'] == 'on_track'), n),
        'honors': _pct(sum(1 for l in learners.values() if l['honor']), n),
    }


def _attendance(school, sy, period, grade_level=None):
    """Days present over school days for the period's months: overall, by grade level and by section."""
    if not (sy and period):
        return None, {}, {}
    qs = AttendanceSummary.objects.filter(school_year=sy, month__in=_months(period), enrollment__status__in=ACTIVE,
                                          enrollment__section__school=school)
    if grade_level:
        qs = qs.filter(enrollment__section__grade_level=grade_level)
    by_level, by_section, present, days = defaultdict(lambda: [0, 0]), {}, 0, 0
    for r in qs.values('enrollment__section_id', 'enrollment__section__grade_level_id').annotate(p=Sum('days_present'), t=Sum('total_school_days')):
        p, t = r['p'] or 0, r['t'] or 0
        present, days = present + p, days + t
        by_level[r['enrollment__section__grade_level_id']][0] += p
        by_level[r['enrollment__section__grade_level_id']][1] += t
        by_section[r['enrollment__section_id']] = _pct(p, t)
    return _pct(present, days), {k: _pct(p, t) for k, (p, t) in by_level.items()}, by_section


def _plot_rows(groups, prev_means, link):
    """Rows for a one-row-per-item plot: average, lowest and highest class, learners below 75, change."""
    out = []
    for key, g in groups.items():
        avg = mean(g['grades'])
        classes = [mean(v) for v in g['classes'].values()]
        before = prev_means.get(key)
        level = level_of(avg)
        out.append({
            'id': key, 'name': g['name'], 'detail': g.get('detail', ''), 'order': g.get('order', 0),
            'average': round(avg, 1), 'low': round(min(classes), 1), 'high': round(max(classes), 1), 'classes': len(classes),
            'below': len(g['below']), 'learners': len(g['learners']), 'level': level['key'], 'level_name': level['name'],
            'delta': _r1(avg - before) if before is not None else None, 'url': link(key),
        })
    out.sort(key=lambda r: (r['average'], r['order']))
    return out


def _performance_data(params, school):
    school_years = list(SchoolYear.objects.filter(school=school).order_by('-year_start'))
    sy = next((s for s in school_years if str(s.id) == str(params.get('school_year'))), None) or \
        next((s for s in school_years if s.is_current), None) or (school_years[0] if school_years else None)
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number')) if sy else []
    wanted = params.get('quarter')
    period = next((q for q in periods if wanted and (q.quarter_label == wanted or str(q.id) == wanted)), None) \
        or _default_period(periods, school)
    earlier = [q for q in periods if period and q.quarter_number < period.quarter_number]
    prev_period = earlier[-1] if earlier else None
    grade_levels = list(GradeLevel.objects.filter(school=school).order_by('sort_order'))
    grade = next((g for g in grade_levels if str(g.id) == str(params.get('grade_level'))), None)
    senior = {g.id: g.is_senior_high for g in grade_levels}
    level_name = {g.id: g.grade_name for g in grade_levels}
    level_number = {g.id: g.grade_number for g in grade_levels}
    subjects = {s.id: s for s in Subject.objects.filter(school=school).select_related('subject_family', 'grade_level')}

    rows = _grades(school, sy, period, grade)
    learners = _learners(rows, senior)
    prev_rows = _grades(school, sy, prev_period, grade)
    prev_learners = _learners(prev_rows, senior)

    # the same grading period last school year
    older = [s for s in school_years if sy and s.year_start < sy.year_start]
    last_sy = older[0] if older else None
    last_period = Quarter.objects.filter(school_year=last_sy, quarter_number=period.quarter_number).first() if last_sy and period else None
    last_rows = _grades(school, last_sy, last_period, grade)
    last_learners = _learners(last_rows, senior)

    # enrollment: every school year (the trend) and this one by section
    enrollments = Enrollment.objects.filter(school_year__school=school, status__in=ACTIVE)
    if grade:
        enrollments = enrollments.filter(section__grade_level=grade)
    per_year, per_year_level = defaultdict(int), defaultdict(dict)
    for r in enrollments.values('school_year_id', 'section__grade_level_id').annotate(n=Count('id')):
        per_year[r['school_year_id']] += r['n']
        per_year_level[r['school_year_id']][level_name.get(r['section__grade_level_id'], 'Other')] = r['n']
    per_section = {r['section_id']: r for r in enrollments.filter(school_year=sy).values(
        'section_id', 'section__section_name', 'section__grade_level_id').annotate(n=Count('id'))} if sy else {}
    enrolled = per_year.get(sy.id, 0) if sy else 0
    trend = [{'id': s.id, 'label': s.year_label, 'count': per_year[s.id], 'selected': s.id == sy.id, 'by_level': per_year_level[s.id]}
             for s in sorted(school_years, key=lambda s: s.year_start) if s.id in per_year and sy and s.year_start <= sy.year_start]

    attendance, attendance_by_level, attendance_by_section = _attendance(school, sy, period, grade)
    last_attendance = _attendance(school, last_sy, last_period, grade)[0] if last_period else None

    scope_name = grade.grade_name if grade else 'All grade levels'
    query = {'quarter': period.quarter_label if period else '', 'school_year': sy.id if sy else ''}

    status = areas = subject_rows = None
    table, needs, counts = [], [], {o['key']: 0 for o in OUTLOOK}
    if rows:
        average = mean(r[-1] for r in rows)
        prev = _summary(prev_rows, prev_learners)
        for learner in learners.values():
            counts[learner['outlook']] += 1
        honors = sum(1 for l in learners.values() if l['honor'])
        on_track = _pct(counts['on_track'], len(learners))
        status = {
            'level': level_of(average), 'average': round(average, 1),
            'delta': _r1(average - prev['average']) if prev else None,
            'passing_all': on_track, 'passing_delta': _r1(on_track - prev['passing_all']) if prev else None,
            'learners': len(learners), 'enrolled': enrolled, 'honors': honors, 'honors_rate': _pct(honors, len(learners)),
            'honors_by': [(name, sum(1 for l in learners.values() if l['honor'] == key)) for _, key, name in policy.current()['awards']['tiers']],
            'attendance': attendance, 'classes': len({(r[3], r[6]) for r in rows}),
        }

        # learning areas (disciplines) and subjects
        def group(rows_, key_of):
            groups = defaultdict(lambda: {'grades': [], 'classes': defaultdict(list), 'below': set(), 'learners': set()})
            for e, last, first, sec, sec_name, gl, subj, g in rows_:
                key = key_of(subj)
                bucket = groups[key]
                bucket['grades'].append(g)
                bucket['classes'][(sec, subj)].append(g)
                bucket['learners'].add(e)
                if g < PASSING:
                    bucket['below'].add(e)
            return groups

        family_of = lambda subj: subjects[subj].subject_family_id if subj in subjects and subjects[subj].subject_family_id else 0
        area_groups = group(rows, family_of)
        for key, g in area_groups.items():
            fam = next((subjects[s].subject_family for s in subjects if subjects[s].subject_family_id == key), None) if key else None
            g['name'] = fam.family_name if fam else 'Other subjects'
            g['order'] = fam.sort_order if fam else 999
            numbers = sorted({level_number.get(r[5]) for r in rows if family_of(r[6]) == key and level_number.get(r[5]) is not None})
            span = (f'Grades {numbers[0]}\u2013{numbers[-1]}' if len(numbers) > 1 else f'Grade {numbers[0]}') if numbers else ''
            count = len({r[6] for r in rows if family_of(r[6]) == key})
            g['detail'] = f'{count} subject{"" if count == 1 else "s"}' + (f' \u00b7 {span}' if span else '')
        prev_area = {k: mean(v['grades']) for k, v in group(prev_rows, family_of).items()}
        areas = _plot_rows(area_groups, prev_area, lambda key: reverse('heads-ai-dashboard') + '?' + urlencode(
            {'view_mode': 'family', 'subject_family': key, 'grade_level': grade.id if grade else 'all', **query}) if key else '')

        subject_groups = group(rows, lambda subj: subj)
        for key, g in subject_groups.items():
            s = subjects.get(key)
            g['name'] = s.subject_name if s else f'Subject {key}'
            g['detail'] = ' \u00b7 '.join(p for p in [s.grade_level.grade_name if s and s.grade_level_id else '', s.subject_code if s else '',
                                                  f'{len(g["classes"])} class{"" if len(g["classes"]) == 1 else "es"}'] if p)
            g['order'] = (s.grade_level.sort_order if s and s.grade_level_id else 0) * 1000 + (s.id if s else 0) % 1000
        prev_subject = {k: mean(v['grades']) for k, v in group(prev_rows, lambda subj: subj).items()}
        subject_rows = _plot_rows(subject_groups, prev_subject, lambda key: reverse('heads-ai-dashboard') + '?' + urlencode(
            {'view_mode': 'subject', 'subject': key, **query}))

        # grade levels, or the sections of the chosen grade level
        prev_by = defaultdict(list)
        for r in prev_rows:
            prev_by[r[3] if grade else r[5]].append(r[-1])
        keyed = defaultdict(list)
        for learner in learners.values():
            keyed[learner['section_id'] if grade else learner['grade_level_id']].append(learner)
        if grade:
            units = sorted({k for k in keyed} | {k for k, v in per_section.items() if v['section__grade_level_id'] == grade.id},
                           key=lambda k: (per_section.get(k, {}).get('section__section_name') or next((l['section'] for l in keyed[k]), '')))
        else:
            units = [g.id for g in grade_levels if g.id in keyed or any(v['section__grade_level_id'] == g.id for v in per_section.values())]
        for unit in units:
            group_learners = keyed.get(unit, [])
            grades = [g for l in group_learners for g in l['grades']]
            if grade:
                name = per_section[unit]['section__section_name'] if unit in per_section else group_learners[0]['section']
                unit_enrolled = per_section.get(unit, {}).get('n', len(group_learners))
                att = attendance_by_section.get(unit)
                url = ''
            else:
                name = level_name.get(unit, '')
                unit_enrolled = sum(v['n'] for v in per_section.values() if v['section__grade_level_id'] == unit)
                att = attendance_by_level.get(unit)
                url = reverse('heads-school-performance') + '?' + urlencode({'grade_level': unit, **query})
            outlook = {o['key']: sum(1 for l in group_learners if l['outlook'] == o['key']) for o in OUTLOOK}
            avg = mean(grades) if grades else None
            before = prev_by.get(unit)
            table.append({
                'name': name, 'url': url, 'enrolled': unit_enrolled, 'graded': len(group_learners),
                'average': round(avg, 1) if avg is not None else None, 'level': level_of(avg),
                'delta': _r1(avg - mean(before)) if avg is not None and before else None,
                'outlook': outlook, 'outlook_pct': {k: _pct(v, len(group_learners)) or 0 for k, v in outlook.items()},
                'honors': sum(1 for l in group_learners if l['honor']), 'attendance': att,
                'senior': (not grade and senior.get(unit)) or (grade and grade.is_senior_high),
            })

        # learners who need support, most urgent first
        for learner in learners.values():
            if learner['outlook'] == 'on_track':
                continue
            items = sorted(learner['failing'], key=lambda f: f[1])
            needs.append({
                'name': learner['name'], 'section': learner['section'], 'grade_level': level_name.get(learner['grade_level_id'], ''),
                'grade_level_id': learner['grade_level_id'], 'outlook': learner['outlook'], 'average': round(learner['average'], 1),
                'lowest': items[0][1], 'count': len(items),
                'items': [{'code': subjects[s].subject_code if s in subjects else str(s), 'grade': g} for s, g in items],
            })
        needs.sort(key=lambda n: (n['outlook'] != 'retention', -n['count'], n['lowest'], n['name']))

        status['insight'] = insights.performance_insight(
            scope_name='The school' if not grade else grade.grade_name, period_name=period_name(period),
            prev_period_name=period_name(prev_period), average=average, delta=status['delta'], learners=len(learners),
            areas=areas, remedial=counts['remedial'], retention=counts['retention'], honors=honors,
            honors_phrase=policy.current()['awards']['phrase'])

    last_year = None
    if last_rows:
        last = _summary(last_rows, last_learners)
        last_year = {
            'name': f'{period_name(last_period)}, SY {last_sy.year_label}',
            'rows': [
                {'name': 'Average grade', 'icon': 'fi-rr-chart-line-up', 'unit': '%', 'then': round(last['average'], 1),
                 'now': status['average'] if status else None},
                {'name': 'Passing all subjects', 'icon': 'fi-rr-check-circle', 'unit': '%', 'then': last['passing_all'],
                 'now': status['passing_all'] if status else None},
                {'name': policy.current()['awards']['label'], 'icon': 'fi-rr-trophy', 'unit': '%', 'then': last['honors'],
                 'now': status['honors_rate'] if status else None},
                {'name': 'Attendance', 'icon': 'fi-rr-calendar-check', 'unit': '%', 'then': last_attendance, 'now': attendance},
                {'name': 'Learners enrolled', 'icon': 'fi-rr-users-alt', 'unit': '', 'then': per_year.get(last_sy.id), 'now': enrolled},
            ],
        }
        for row in last_year['rows']:
            row['change'] = _r1(row['now'] - row['then']) if row['now'] is not None and row['then'] is not None else None

    # school performance forecast: each grade level (or each section of the chosen one) across every learning area
    forecast_spec = None
    table_, meta = forecasts.year_table(school, sy)
    if table_ and periods:
        section_grade = dict(Section.objects.filter(school_year=sy, school=school).values_list('id', 'grade_level_id'))
        if grade:
            names = dict(Section.objects.filter(school_year=sy, school=school, grade_level=grade).values_list('id', 'section_name'))
            items = [{'key': f'section-{sid}', 'name': names[sid], 'keys': [k for k, v in table_.items() if v['section'] == sid], 'level': 'class'}
                     for sid in sorted(names, key=names.get)]
            reference_keys, word = [k for k, v in table_.items() if section_grade.get(v['section']) == grade.id], 'section'
        else:
            items = [{'key': f'grade-{g.id}', 'name': g.grade_name, 'keys': [k for k, v in table_.items() if section_grade.get(v['section']) == g.id],
                      'url': reverse('heads-school-performance') + '?' + urlencode({'grade_level': g.id, **query})} for g in grade_levels]
            reference_keys, word = list(table_), 'grade level'
        forecast_spec = forecasts.chart(
            table=table_, meta=meta, periods=periods, items=items, level='group', step_sd=insights.typical_step_sd(school.id),
            reference={'key': 'all', 'name': grade.grade_name if grade else 'Whole school', 'keys': reference_keys},
            selected=period.quarter_number if period else None, period_name=period_name)
        forecast_spec['word'] = word

    return {
        'school_years': school_years, 'sy': sy, 'periods': periods, 'period': period, 'prev_period': prev_period,
        'period_name': period_name(period), 'prev_period_name': period_name(prev_period),
        'period_options': [{'value': q.quarter_label, 'name': period_name(q), 'current': q.is_current_quarter} for q in periods],
        'forecast': forecast_spec,
        'grade_levels': grade_levels, 'grade': grade, 'grade_id': str(grade.id) if grade else 'all', 'scope_name': scope_name,
        'status': status, 'areas': areas or [], 'subjects': subject_rows or [], 'table': table, 'needs': needs,
        'outlook': [dict(o, count=counts[o['key']], share=_pct(counts[o['key']], len(learners)) or 0) for o in OUTLOOK],
        'honors_legend': policy.current()['awards']['tiers'], 'awards': policy.current()['awards'], 'trend': trend, 'trend_levels': [g.grade_name for g in grade_levels if not grade or g.id == grade.id],
        'enrolled': enrolled, 'last_year': last_year,
    }


@login_required
@remember_filters('heads-performance', ['school_year', 'quarter', 'grade_level'])
@cache_page_for_user()
def school_performance(request, school_year_id=None):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    params = request.GET.copy()
    if school_year_id and not params.get('school_year'):
        params['school_year'] = str(school_year_id)
    data = _performance_data(params, school)
    data['export_url'] = reverse('heads-school-performance-export') + ('?' + request.GET.urlencode() if request.GET else '')
    data['live_fingerprint'] = school_fingerprint(school)
    return render(request, 'heads/performance/school_performance.html', data)


@login_required
def performance_export(request):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    d = _performance_data(request.GET, school)
    report = Report('School Performance Report', school.school_name, _person(request.user))
    period = f'{d["period_name"]}, SY {d["sy"].year_label if d["sy"] else ""}'
    meta = [('Reviewing', d['scope_name']), ('Period', period)]
    sh = report.sheet('Summary', [30, 14, 14, 16, 16, 14, 14], subtitle=d['scope_name'], meta=meta)
    st = d['status']
    if not st:
        sh.paragraph('No grades for this period yet.')
        return report.response(f'{safe_filename(school.short_name or "school", "school-performance")}.xlsx')
    fmt = lambda v, unit='%': '—' if v is None else f'{v:.1f}{unit}'
    sh.figures([
        ('Status', f'{st["level"]["name"]} ({st["level"]["letter"]})', None),
        ('Average grade', fmt(st['average']), None),
        ('Passing every learning area', fmt(st['passing_all']), None),
        ('Attendance', fmt(st['attendance']), None),
        ('Learners graded', f'{st["learners"]} of {st["enrolled"]}', None),
        (policy.current()['awards']['label'], str(st['honors']), 'good' if st['honors'] else None),
        ('Remedial classes', str(d['outlook'][1]['count']), 'warn' if d['outlook'][1]['count'] else 'good'),
        ('At risk of retention', str(d['outlook'][2]['count']), 'risk' if d['outlook'][2]['count'] else 'good'),
    ])
    sh.heading('What Poro sees')
    sh.paragraph(st['insight'])
    sh.heading('Learning areas')
    sh.table([{'title': 'Learning area', 'wrap': True}, {'title': 'Average', 'format': 'grade'}, {'title': 'Lowest class', 'format': 'grade'},
              {'title': 'Highest class', 'format': 'grade'}, {'title': 'Learners below 75', 'format': 'int'}, {'title': 'Level'},
              {'title': f'Change vs {d["prev_period_name"] or "previous"}', 'format': 'delta'}],
             [[a['name'], a['average'], a['low'], a['high'], a['below'], (a['level_name'], a['level']),
               a['delta'] if a['delta'] is not None else '—'] for a in d['areas']])
    unit = 'Section' if d['grade'] else 'Grade level'
    sh2 = report.sheet('Grade levels' if not d['grade'] else 'Sections', [22, 11, 11, 12, 13, 13, 13, 11, 12],
                       subtitle=d['scope_name'], meta=meta, title='Promotion outlook and honors')
    sh2.paragraph('Promotion outlook if the year ended with these grades (DepEd Order No. 8, s. 2015). '
                  + policy.current()['awards']['period_rule'], color='4A5568', size=9)
    sh2.table([{'title': unit}, {'title': 'Enrolled', 'format': 'int'}, {'title': 'Graded', 'format': 'int'}, {'title': 'Average', 'format': 'grade'},
               {'title': 'On track', 'format': 'int'}, {'title': 'Remedial', 'format': 'int'}, {'title': 'Retention risk', 'format': 'int'},
               {'title': 'Honors', 'format': 'int'}, {'title': 'Attendance', 'format': 'percent'}],
              [[r['name'], r['enrolled'], r['graded'], (r['average'], r['level']['key']) if r['average'] is not None else '—',
                r['outlook']['on_track'], r['outlook']['remedial'], r['outlook']['retention'], r['honors'],
                r['attendance'] if r['attendance'] is not None else '—'] for r in d['table']])
    sh3 = report.sheet('Subjects', [34, 18, 11, 12, 12, 13, 14], subtitle=d['scope_name'], meta=meta, title='Every subject')
    sh3.table([{'title': 'Subject', 'wrap': True}, {'title': 'Grade level'}, {'title': 'Average', 'format': 'grade'},
               {'title': 'Lowest class', 'format': 'grade'}, {'title': 'Highest class', 'format': 'grade'},
               {'title': 'Below 75', 'format': 'int'}, {'title': 'Change', 'format': 'delta'}],
              [[s['name'], s['detail'], (s['average'], s['level']), s['low'], s['high'], s['below'],
                s['delta'] if s['delta'] is not None else '—'] for s in sorted(d['subjects'], key=lambda s: s['order'])])
    if d['needs']:
        sh4 = report.sheet('Learners needing support', [30, 18, 12, 18, 40, 11], subtitle=d['scope_name'], meta=meta,
                           title='Learners below 75 (remedial classes or retention risk)')
        names = {o['key']: o['name'] for o in OUTLOOK}
        sh4.table([{'title': 'Learner'}, {'title': 'Section'}, {'title': 'Grade level'}, {'title': 'Outlook'},
                   {'title': 'Subjects below 75', 'wrap': True}, {'title': 'Average', 'format': 'grade'}],
                  [[n['name'], n['section'], n['grade_level'], (names[n['outlook']], 'beginning' if n['outlook'] == 'retention' else 'developing'),
                    ', '.join(f'{i["code"]} ({i["grade"]:.0f})' for i in n['items']), n['average']] for n in d['needs']])
    if d['trend']:
        sh5 = report.sheet('Enrollment', [24, 16], subtitle=d['scope_name'], meta=meta, title='Enrollment by school year', landscape=False)
        sh5.table([{'title': 'School year'}, {'title': 'Learners enrolled', 'format': 'int'}],
                  [[f'SY {t["label"]}', t['count']] for t in d['trend']])
    name = safe_filename(school.short_name or 'school', 'school-performance', d['scope_name'], d['period'].quarter_label if d['period'] else '')
    return report.response(f'{name}.xlsx')
