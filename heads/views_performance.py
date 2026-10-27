"""School Head: School Performance, the whole school's year-end picture for one grading period.

The Academic Dashboard holds the school's one status (its level and average), where each discipline stands and what to
decide for it. This page answers what the dashboard does not: who would be promoted if the year ended now, where the
whole school and each grade level are heading over the year (the school performance forecast), how each grade level
compares in promotion outlook, honors and attendance, how enrollment has moved over the years, and how this period
compares with the same period last school year. Grades are the quarterly grades the dashboard uses (core.periods.GRADE:
the transmuted grade), so the two pages agree.
"""
from collections import defaultdict
from datetime import date
from statistics import mean

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Sum
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode

from academics.models import GradeLevel, Quarter, SchoolYear, Section
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
    """Every quarterly grade of one grading period: (enrollment, section, section name, grade level, grade)."""
    if not (sy and period):
        return []
    qs = GradeComponent.objects.filter(HAS_GRADE, quarter=period, enrollment__school_year=sy, enrollment__status__in=ACTIVE,
                                       enrollment__section__school=school)
    if grade_level:
        qs = qs.filter(enrollment__section__grade_level=grade_level)
    return [(e, sec, sec_name, gl, float(g)) for e, sec, sec_name, gl, g in qs.values_list(
        'enrollment_id', 'enrollment__section_id', 'enrollment__section__section_name', 'enrollment__section__grade_level_id', GRADE)]


def _learners(rows, senior):
    """One entry per learner: quarterly average, learning areas below 75, promotion outlook and honors."""
    by = {}
    for e, sec, sec_name, gl, g in rows:
        learner = by.get(e)
        if learner is None:
            learner = by[e] = {'id': e, 'section_id': sec, 'section': sec_name, 'grade_level_id': gl, 'grades': [], 'failing': 0}
        learner['grades'].append(g)
        if g < PASSING:
            learner['failing'] += 1
    for learner in by.values():
        learner['average'] = mean(learner['grades'])
        learner['whole'] = int(learner['average'] + 0.5)          # reported as a whole number, rounded half up
        failing = learner['failing']
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

    status = None
    table, counts = [], {o['key']: 0 for o in OUTLOOK}
    if rows:
        average = mean(r[-1] for r in rows)
        prev = _summary(prev_rows, prev_learners)
        for learner in learners.values():
            counts[learner['outlook']] += 1
        honors = sum(1 for l in learners.values() if l['honor'])
        on_track = _pct(counts['on_track'], len(learners))
        status = {
            'average': round(average, 1),
            'passing_all': on_track, 'passing_delta': _r1(on_track - prev['passing_all']) if prev else None,
            'learners': len(learners), 'enrolled': enrolled, 'honors': honors, 'honors_rate': _pct(honors, len(learners)),
            'honors_by': [(name, sum(1 for l in learners.values() if l['honor'] == key)) for _, key, name in policy.current()['awards']['tiers']],
            'attendance': attendance,
        }

        # grade levels, or the sections of the chosen grade level
        prev_by = defaultdict(list)
        for r in prev_rows:
            prev_by[r[1] if grade else r[3]].append(r[-1])
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
                'average': round(avg, 1) if avg is not None else None, 'level': level_of(round(avg, 1)) if avg is not None else None,
                'delta': _r1(avg - mean(before)) if avg is not None and before else None,
                'outlook': outlook, 'outlook_pct': {k: _pct(v, len(group_learners)) or 0 for k, v in outlook.items()},
                'honors': sum(1 for l in group_learners if l['honor']), 'attendance': att,
                'senior': (not grade and senior.get(unit)) or (grade and grade.is_senior_high),
            })

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
        'status': status, 'table': table,
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
    outlook = {o['key']: o for o in d['outlook']}
    sh.figures([
        ('Passing every learning area', fmt(st['passing_all']), None),
        ('Remedial classes', str(outlook['remedial']['count']), 'warn' if outlook['remedial']['count'] else 'good'),
        ('At risk of retention', str(outlook['retention']['count']), 'risk' if outlook['retention']['count'] else 'good'),
        (policy.current()['awards']['label'], str(st['honors']), 'good' if st['honors'] else None),
        ('Attendance', fmt(st['attendance']), None),
        ('Learners graded', f'{st["learners"]} of {st["enrolled"]}', None),
    ], per_row=3)
    sh.paragraph(f'Promotion outlook if the year ended with {d["period_name"]} grades (DepEd Order No. 8, s. 2015). '
                 + policy.current()['awards']['period_rule'], color='4A5568', size=9)
    if d['last_year']:
        sh.heading(f'Compared with {d["last_year"]["name"]}')
        sh.table([{'title': 'Measure'}, {'title': 'Last year'}, {'title': 'This year'}, {'title': 'Change', 'format': 'delta'}],
                 [[r['name'], f'{r["then"]}{r["unit"]}' if r['then'] is not None else '—', f'{r["now"]}{r["unit"]}' if r['now'] is not None else '—',
                   r['change'] if r['change'] is not None else '—'] for r in d['last_year']['rows']])
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
    fc = d['forecast']
    if fc and fc['series']:
        labels = [p['label'] for p in fc['periods']]
        sh_fc = report.sheet('Forecast', [30] + [13] * len(labels), subtitle=d['scope_name'], meta=meta, title='School performance forecast')
        sh_fc.paragraph(fc['method']['text'], color='4A5568', size=9)
        cell = lambda s, p: (f'{s["actual"][p]:.1f}' if p in s['actual'] else
                             f'{s["future"][p][0]:.1f} (forecast, {s["future"][p][1]:.1f} to {s["future"][p][2]:.1f})' if p in s['future'] else '—')
        sh_fc.table([{'title': 'Series', 'wrap': True}] + [{'title': lab, 'wrap': True} for lab in labels],
                    [[s['name']] + [cell(s, p['p']) for p in fc['periods']] for s in fc['series']])
    if d['trend']:
        sh5 = report.sheet('Enrollment', [24, 16], subtitle=d['scope_name'], meta=meta, title='Enrollment by school year', landscape=False)
        sh5.table([{'title': 'School year'}, {'title': 'Learners enrolled', 'format': 'int'}],
                  [[f'SY {t["label"]}', t['count']] for t in d['trend']])
    name = safe_filename(school.short_name or 'school', 'school-performance', d['scope_name'], d['period'].quarter_label if d['period'] else '')
    return report.response(f'{name}.xlsx')
