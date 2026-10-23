"""School Head: Academic Dashboard, section brief (Poro AI), report downloads and live updates."""
import hashlib
from collections import defaultdict
from statistics import mean

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import caches
from django.db.models import Avg, Count, Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from academics.models import GradeLevel, Quarter, SchoolYear, Section, Subject, SubjectFamily
from communication.models import Notification
from core.caching import cache_page_for_user, data_version, remember_filters
from core.periods import GRADE, HAS_GRADE
from core.xlsx import Report, safe_filename
from enrollment.models import Enrollment
from grades.models import GradeComponent
from scheduling.models import ClassAssignment

from . import forecasts, insights
from .insights import LEVELS, PASSING, level_of

ACTIVE = ['Enrolled', 'Transferred_In']
LEVEL_HEX = {'beginning': '#C62828', 'developing': '#E65100', 'approaching': '#1565C0', 'proficient': '#123499', 'advanced': '#2E7D32'}
VALIDATED = ('Validated', 'Finalized')
PERIOD_WORD = {'Q': 'Quarter', 'T': 'Trimester', 'S': 'Semester'}
GRADE_SCOPES = {'jhs': 'All Junior High', 'shs': 'All Senior High'}


def period_name(q):
    return f'{PERIOD_WORD.get((q.quarter_label or "Q")[:1].upper(), "Quarter")} {q.quarter_number}' if q else ''


def _head_school(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'schoolhead':
        return None
    return profile.school


def _denied(request):
    messages.error(request, 'Access denied. School Heads only.')
    return redirect('signin')


def _person(user):
    return (user.get_full_name() or user.username) if user else ''


def _default_period(periods, school):
    """The current grading period when it has grades, otherwise the latest one that has grades."""
    if not periods:
        return None
    has = lambda q: GradeComponent.objects.filter(quarter=q, enrollment__section__school=school).exists()
    today = timezone.localdate()
    current = next((q for q in periods if q.is_current_quarter), None) or \
        next((q for q in periods if q.date_start <= today <= q.date_end), None)
    if current and has(current):
        return current
    for q in reversed(periods):
        if has(q):
            return q
    return current or periods[0]


def _r1(value):
    """Round to one decimal without ever showing -0.0."""
    return round(value, 1) + 0.0


def kpup(avg):
    """Knowledge, Process, Understanding and Product, estimated from a class average (DO 73, s. 2012 weights)."""
    return {'k': min(round(avg * 1.10, 1), 99.9), 'p': min(round(avg * 0.95, 1), 99.9),
            'u': min(round(avg * 0.85, 1), 99.9), 'pd': min(round(avg * 0.78, 1), 99.9)}


# =============================================================================================
# Academic Dashboard
# =============================================================================================

def _grade_scope(key, grade_levels):
    """The grade levels a selection covers: (levels, or None for every level; option value; label)."""
    if key in GRADE_SCOPES:
        chosen = [g for g in grade_levels if bool(g.is_senior_high) == (key == 'shs')]
        if chosen:
            numbers = sorted(g.grade_number for g in chosen)
            span = f'Grades {numbers[0]} to {numbers[-1]}' if len(numbers) > 1 else f'Grade {numbers[0]}'
            return chosen, key, f'{GRADE_SCOPES[key]} ({span})'
    one = next((g for g in grade_levels if str(g.id) == str(key)), None)
    if one:
        return [one], str(one.id), one.grade_name
    return None, 'all', 'All grade levels'


def _ladder(items):
    """The five proficiency levels, Beginning first, each listing the items whose average falls in it."""
    total = len(items) or 1
    ladder = []
    for lv in reversed(LEVELS):
        mine = sorted([i for i in items if i['level']['key'] == lv['key']], key=lambda i: -i['average'])
        ladder.append({'level': lv, 'items': mine, 'count': len(mine), 'share': round(100 * len(mine) / total)})
    return ladder


def _dashboard_data(params, school):
    school_years = list(SchoolYear.objects.filter(school=school).order_by('-year_start'))
    sy = next((s for s in school_years if str(s.id) == params.get('school_year')), None) or \
        next((s for s in school_years if s.is_current), None) or (school_years[0] if school_years else None)
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number')) if sy else []
    wanted = params.get('quarter')
    latest = _default_period(periods, school)
    # "All periods": each learner's grade in a subject is the average of its periods so far (the final grade once all are in)
    all_periods = wanted == 'all' and latest is not None
    period = None if all_periods else (next((q for q in periods if wanted and (q.quarter_label == wanted or str(q.id) == wanted)), None) or latest)
    ref_period = period or latest                                # links and the forecast point at a real grading period
    span = [q for q in periods if latest and q.quarter_number <= latest.quarter_number] if all_periods else []
    earlier = [q for q in periods if period and q.quarter_number < period.quarter_number]
    prev_period = earlier[-1] if earlier else None
    quarter_value = 'all' if all_periods else (period.quarter_label if period else '')
    shown_period = (f'{period_name(span[0])} to {period_name(span[-1])}' if len(span) > 1 else period_name(span[0])) \
        if all_periods else period_name(period)

    grade_levels = list(GradeLevel.objects.filter(school=school).order_by('sort_order'))
    families = list(SubjectFamily.objects.filter(school=school, is_active=True).order_by('sort_order', 'family_name'))
    subjects = list(Subject.objects.filter(school=school, is_active=True).select_related('grade_level')
                    .order_by('grade_level__sort_order', 'subject_code'))
    subject_by_id = {s.id: s for s in subjects}
    mode = 'subject' if params.get('view_mode') in ('subject', 'all') else 'family'
    grade_set, grade_key, grade_label = _grade_scope(params.get('grade_level', 'all'), grade_levels)
    family = subject = None
    all_families = False
    if mode == 'family':
        all_families = params.get('subject_family') == 'all'
        if not all_families:
            family = next((f for f in families if str(f.id) == params.get('subject_family')), None) or (families[0] if families else None)
        grade_ids = {g.id for g in grade_set} if grade_set else None
        scope = [s for s in subjects if (grade_ids is None or s.grade_level_id in grade_ids)
                 and (all_families or (family and s.subject_family_id == family.id))]
        scope_name = 'All disciplines' if all_families else (family.family_name if family else 'No discipline')
        scope_detail = grade_label
    else:
        grade_set, grade_key, grade_label = None, 'all', 'All grade levels'      # a subject belongs to one grade level
        subject = next((s for s in subjects if str(s.id) == params.get('subject')), None) or (subjects[0] if subjects else None)
        scope = [subject] if subject else []
        scope_name = subject.subject_name if subject else 'No subject'
        scope_detail = subject.grade_level.grade_name if subject and subject.grade_level_id else ''
    ids = [s.id for s in scope]
    sections_view = mode == 'family' and all_families                         # every discipline: one row per section
    query = {'school_year': sy.id if sy else '', 'quarter': quarter_value}
    brief = lambda section_id, subject_id: reverse('heads-ai-section-detail', args=[section_id, subject_id, ref_period.id]) if ref_period else ''

    base = GradeComponent.objects.filter(HAS_GRADE, subject_id__in=ids, enrollment__school_year=sy, enrollment__status__in=ACTIVE,
                                         enrollment__section__school=school)
    fields = ('enrollment_id', 'enrollment__student_id', 'enrollment__student__first_name', 'enrollment__student__last_name',
              'enrollment__section_id', 'enrollment__section__section_name', 'enrollment__section__grade_level__grade_name',
              'enrollment__section__grade_level__sort_order', 'subject_id', 'subject__subject_code', 'subject__subject_name')
    rows = []
    if ids and (period or all_periods):
        found = list((base.filter(quarter__in=span) if all_periods else base.filter(quarter=period)).values(*fields, grade=GRADE))
        if all_periods:
            merged = {}
            for r in found:
                merged.setdefault((r['enrollment_id'], r['subject_id']), dict(r, grades=[]))['grades'].append(float(r['grade']))
            rows = [dict(m, grade=mean(m['grades'])) for m in merged.values()]
        else:
            rows = found
    prev, prev_sum, prev_n = {}, 0.0, 0
    if ids and prev_period:
        for r in base.filter(quarter=prev_period).values('enrollment__section_id', 'subject_id').annotate(avg=Avg(GRADE), n=Count('id')):
            prev[(r['enrollment__section_id'], r['subject_id'])] = (float(r['avg']), r['n'])
            prev_sum += float(r['avg']) * r['n']
            prev_n += r['n']

    classes, failing = {}, {}
    for r in rows:
        grade = float(r['grade'])
        key = (r['enrollment__section_id'], r['subject_id'])
        c = classes.setdefault(key, {
            'section_id': key[0], 'subject_id': key[1], 'section_name': r['enrollment__section__section_name'],
            'grade_level': r['enrollment__section__grade_level__grade_name'] or '',
            'sort': r['enrollment__section__grade_level__sort_order'] or 0,
            'subject_code': r['subject__subject_code'], 'subject_name': r['subject__subject_name'], 'grades': [], 'students': set()})
        c['grades'].append(grade)
        c['students'].add(r['enrollment__student_id'])
        if grade < PASSING:
            sid = r['enrollment__student_id']
            f = failing.setdefault(sid, {'name': f"{r['enrollment__student__last_name']}, {r['enrollment__student__first_name']}",
                                         'section': r['enrollment__section__section_name'], 'section_id': key[0], 'items': []})
            f['items'].append({'subject': r['subject__subject_code'], 'grade': grade, 'url': brief(*key)})

    def class_row(c):
        avg = mean(c['grades'])
        before = prev.get((c['section_id'], c['subject_id']))
        return {
            'section_id': c['section_id'], 'subject_id': c['subject_id'], 'section_name': c['section_name'],
            'grade_level': c['grade_level'], 'subject_code': c['subject_code'], 'subject_name': c['subject_name'],
            'learners': len(c['grades']), 'overall': round(avg, 1), 'level': level_of(avg),
            'below': sum(1 for g in c['grades'] if g < PASSING),
            'delta': _r1(avg - before[0]) if before else None, 'delta_abs': _r1(abs(avg - before[0])) if before else None,
            'label': c['section_name'] if mode == 'subject' else f"{c['section_name']} ({c['subject_code']})",
            'url': brief(c['section_id'], c['subject_id']), **kpup(avg),
        }

    class_rows = [class_row(c) for c in sorted(classes.values(), key=lambda c: (c['sort'], c['section_name'], c['subject_code']))]
    if sections_view:
        grouped = {}
        for c, row in zip(sorted(classes.values(), key=lambda c: (c['sort'], c['section_name'], c['subject_code'])), class_rows):
            s = grouped.setdefault(c['section_id'], {'section_name': c['section_name'], 'grade_level': c['grade_level'],
                                                     'grades': [], 'students': set(), 'failing': set(), 'subjects': [], 'prev': []})
            s['grades'] += c['grades']
            s['students'] |= c['students']
            s['subjects'].append(row)
            before = prev.get((c['section_id'], c['subject_id']))
            if before:
                s['prev'].append(before)
        failing_by_section = defaultdict(set)
        for sid, f in failing.items():
            failing_by_section[f['section_id']].add(sid)
        table = []
        for section_id, s in grouped.items():
            avg = mean(s['grades'])
            before = sum(a * n for a, n in s['prev']) / sum(n for _, n in s['prev']) if s['prev'] else None
            s['subjects'].sort(key=lambda r: r['overall'])
            table.append({
                'section_id': section_id, 'subject_id': None, 'section_name': s['section_name'], 'grade_level': s['grade_level'],
                'subject_code': '', 'subject_name': f'{len(s["subjects"])} subjects', 'learners': len(s['students']),
                'overall': round(avg, 1), 'level': level_of(avg), 'below': len(failing_by_section[section_id]),
                'delta': _r1(avg - before) if before is not None else None,
                'delta_abs': _r1(abs(avg - before)) if before is not None else None,
                'label': s['section_name'], 'url': f'#section-{section_id}', 'subjects': s['subjects'], **kpup(avg),
            })
    else:
        table = class_rows

    at_risk = []
    for f in failing.values():
        f['items'].sort(key=lambda i: i['grade'])
        f['lowest'] = f['items'][0]['grade']
        f['url'] = f['items'][0]['url']
        at_risk.append(f)
    at_risk.sort(key=lambda f: (f['lowest'], f['name']))

    # where each item stands (the status card's level chart): disciplines, subjects or sections, by selection
    item_rows = defaultdict(list)
    if sections_view:
        item_word, family_of = 'discipline', {s.id: s.subject_family_id for s in scope}
        for r in rows:
            item_rows[family_of.get(r['subject_id'])].append(float(r['grade']))
        names = {f.id: f.family_name for f in families}
        link = lambda fid: '?' + urlencode({'view_mode': 'family', 'subject_family': fid, 'grade_level': grade_key, **query})
        items = [{'name': names.get(fid, 'Other subjects'), 'average': round(mean(g), 1), 'level': level_of(mean(g)),
                  'learners': len(g), 'url': link(fid) if fid else ''} for fid, g in item_rows.items()]
    elif mode == 'family' and len({r['subject_id'] for r in rows}) > 1:
        item_word = 'subject'
        for r in rows:
            item_rows[r['subject_id']].append(float(r['grade']))
        link = lambda sid: '?' + urlencode({'view_mode': 'subject', 'subject': sid, **query})
        items = [{'name': subject_by_id[sid].subject_name, 'average': round(mean(g), 1), 'level': level_of(mean(g)),
                  'learners': len(g), 'url': link(sid)} for sid, g in item_rows.items()]
    else:
        item_word = 'section'
        items = [{'name': f'{r["grade_level"]} {r["section_name"]}' if mode == 'family' else r['section_name'],
                  'average': r['overall'], 'level': r['level'], 'learners': r['learners'], 'url': r['url']} for r in class_rows]
    ladder = _ladder(items) if items else []

    grades = [float(r['grade']) for r in rows]
    status = None
    forecast_spec = None
    table_, meta = forecasts.year_table(school, sy) if ids else ({}, None)
    if grades:
        average = mean(grades)
        prev_avg = prev_sum / prev_n if prev_n else None
        status = {
            'level': level_of(average), 'average': round(average, 1),
            'delta': _r1(average - prev_avg) if prev_avg is not None else None,
            'delta_abs': _r1(abs(average - prev_avg)) if prev_avg is not None else None,
            'learners': len({r['enrollment__student_id'] for r in rows}), 'classes': len(class_rows),
            'sections': len({r['enrollment__section_id'] for r in rows}),
            'passing_rate': round(100 * sum(1 for g in grades if g >= PASSING) / len(grades), 1),
            'below': len(failing),
        }

    # the forecast chart: disciplines, grade levels or sections over the school year, with what comes next
    if ids and periods and table_:
        in_scope = {k for k, v in table_.items() if v['subject'] in set(ids)}
        if sections_view:
            fam = {s.id: s.subject_family_id for s in scope}
            items_fc = [{'key': f'family-{f.id}', 'name': f.family_name, 'keys': [k for k in in_scope if fam.get(table_[k]['subject']) == f.id],
                         'url': '?' + urlencode({'view_mode': 'family', 'subject_family': f.id, 'grade_level': grade_key, **query})}
                        for f in families]
            level, fc_word = 'group', 'learning area'
        elif mode == 'family':
            levels_in = grade_set or grade_levels
            items_fc = [{'key': f'grade-{g.id}', 'name': g.grade_name,
                         'keys': [k for k in in_scope if subject_by_id.get(table_[k]['subject']) and subject_by_id[table_[k]['subject']].grade_level_id == g.id],
                         'url': '?' + urlencode({'view_mode': 'family', 'subject_family': family.id if family else 'all', 'grade_level': g.id, **query})}
                        for g in levels_in]
            level, fc_word = 'group', 'grade level'
        else:
            names = dict(Section.objects.filter(id__in={table_[k]['section'] for k in in_scope}).values_list('id', 'section_name'))
            items_fc = [{'key': f'section-{sid}', 'name': names.get(sid, 'Section'), 'keys': [k for k in in_scope if table_[k]['section'] == sid],
                         'url': brief(sid, subject.id)} for sid in sorted(names, key=lambda i: names[i])]
            level, fc_word = 'class', 'section'
        forecast_spec = forecasts.chart(
            table=table_, meta=meta, periods=periods, items=items_fc, level=level, step_sd=insights.typical_step_sd(school.id),
            reference={'key': 'all', 'name': scope_name if mode == 'subject' or all_families or not grade_set else f'{scope_name}, {grade_label}',
                       'keys': list(in_scope)},
            selected=None if all_periods else (period.quarter_number if period else None), period_name=period_name)
        forecast_spec['word'] = fc_word

    if status:
        overall = next((s for s in (forecast_spec or {}).get('series', []) if s.get('reference')), None)
        upcoming = None
        if overall and overall['future'] and ref_period and ref_period.quarter_number == overall['last']:
            p = min(overall['future'])
            upcoming = {'name': period_name(next((q for q in periods if q.quarter_number == p), None)), 'value': overall['future'][p][0]}
        status['insight_scope'] = (grade_label.replace('All ', '', 1) if grade_set else 'The school') if all_families else \
            scope_name + (f' ({grade_label})' if mode == 'family' and grade_set else '')
        status['insight'], status['insight_names'] = insights.dashboard_insight(
            scope_name=status['insight_scope'],
            period_name=shown_period, prev_period_name=period_name(prev_period),
            average=mean(grades), delta=status['delta'], below=status['below'], items=items, item_word=item_word, upcoming=upcoming,
            over_periods=len(span) > 1)

    chart = [{'order': i, 'section': r['section_name'], 'grade': r['grade_level'], 'subject': r['subject_name'],
              'code': r['subject_code'], 'url': r['url'], 'level': r['level']['key'], 'level_name': r['level']['name'],
              'k': r['k'], 'p': r['p'], 'u': r['u'], 'pd': r['pd'], 'overall': r['overall'],
              'learners': r['learners'], 'below': r['below'], 'delta': r['delta']} for i, r in enumerate(table)]
    sections_json = {str(r['section_id']): {'name': f'{r["grade_level"]} {r["section_name"]}', 'overall': r['overall'],
                                           'level': r['level']['name'], 'subjects': [
                                               {'code': c['subject_code'], 'name': c['subject_name'], 'overall': c['overall'],
                                                'level': c['level']['key'], 'level_short': c['level']['short'], 'letter': c['level']['letter'],
                                                'below': c['below'], 'delta': c['delta'], 'url': c['url']} for c in r['subjects']]}
                     for r in table} if sections_view else None

    subject_groups = []
    for s in subjects:
        label = s.grade_level.grade_name if s.grade_level_id else 'Other'
        if not subject_groups or subject_groups[-1][0] != label:
            subject_groups.append((label, []))
        subject_groups[-1][1].append(s)

    return {
        'school_years': school_years, 'sy': sy, 'periods': periods, 'period': period, 'prev_period': prev_period,
        'all_periods': all_periods, 'ref_period': ref_period, 'quarter_value': quarter_value,
        'period_name': shown_period, 'prev_period_name': period_name(prev_period),
        'period_options': [{'value': q.quarter_label, 'name': period_name(q), 'current': q.is_current_quarter} for q in periods],
        'view_mode': mode, 'families': families, 'family': family, 'all_families': all_families, 'subject': subject,
        'subject_groups': subject_groups, 'grade_levels': grade_levels, 'grade_id': grade_key, 'grade_label': grade_label,
        'grade_scopes': [{'value': k, 'name': _grade_scope(k, grade_levels)[2]} for k in GRADE_SCOPES
                         if any(bool(g.is_senior_high) == (k == 'shs') for g in grade_levels)],
        'scope_name': scope_name, 'scope_detail': scope_detail, 'sections_view': sections_view,
        'status': status, 'table': table, 'at_risk': at_risk, 'chart': chart, 'levels': LEVELS,
        'ladder': ladder, 'ladder_word': item_word if items else '', 'forecast': forecast_spec, 'sections_json': sections_json,
    }


@login_required
@remember_filters('heads-ai', ['view_mode', 'subject_family', 'school_year', 'quarter', 'grade_level', 'subject'])
@cache_page_for_user()
def academic_dashboard(request):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    data = _dashboard_data(request.GET, school)
    data['export_url'] = reverse('heads-ai-dashboard-export') + ('?' + request.GET.urlencode() if request.GET else '')
    data['live_fingerprint'] = school_fingerprint(school)
    status = data['status']
    data['poro_token'] = insights.narrative_token(
        status['insight'], keep=[status['level']['name'], status['insight_scope']] + [i['name'] for i in status['insight_names']]) if status else ''
    return render(request, 'heads/ai_dashboard/index.html', data)


@login_required
def dashboard_export(request):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    d = _dashboard_data(request.GET, school)
    report = Report('Academic Dashboard Report', school.school_name, _person(request.user))
    scope = d['scope_name'] + (f' · {d["scope_detail"]}' if d['scope_detail'] else '')
    meta = [('Reviewing', scope), ('Period', f'{d["period_name"]}, SY {d["sy"].year_label if d["sy"] else ""}')]
    sh = report.sheet('Summary', [20, 26, 11, 9, 9, 9, 9, 11, 28, 13], subtitle=scope, meta=meta)
    st = d['status']
    if st:
        sh.figures([
            ('Status', f'{st["level"]["name"]} ({st["level"]["letter"]})', None),
            ('Average', f'{st["average"]:.1f}%', None),
            ('Passing (75 and above)', f'{st["passing_rate"]:.1f}%', None),
            ('Learners below 75', str(st['below']), 'risk' if st['below'] else 'good'),
        ])
        sh.heading('What Poro sees')
        sh.paragraph(st['insight'])
        sh.paragraph(st['level']['meaning'], color='4A5568', size=10)
        if d['ladder']:
            sh.heading(f'Where each {d["ladder_word"]} stands')
            for step in d['ladder']:
                names = ', '.join(f'{i["name"]} ({i["average"]:.1f})' for i in step['items']) or 'None'
                sh.paragraph(f'{step["level"]["name"]} ({step["level"]["letter"]}, {step["level"]["range"]}): {names}', size=10)
    else:
        sh.paragraph('No grades for this selection yet.')
    sh.heading('Sections' if d['sections_view'] else 'Classes')
    sh.paragraph('K, Pr, U and Pd (Knowledge, Process, Understanding, Product) are estimated from each class average '
                 'with the DepEd Order No. 73, s. 2012 weights; the average and level come from the actual grades.',
                 color='4A5568', size=9)
    columns = [{'title': 'Section', 'wrap': True}, {'title': 'Subject', 'wrap': True}, {'title': 'Learners', 'format': 'int'},
               {'title': 'K', 'format': 'grade'}, {'title': 'Pr', 'format': 'grade'}, {'title': 'U', 'format': 'grade'},
               {'title': 'Pd', 'format': 'grade'}, {'title': 'Average', 'format': 'grade'}, {'title': 'Level'},
               {'title': f'Change vs {d["prev_period_name"] or "previous"}', 'format': 'delta'}]
    line = lambda r: [f'{r["grade_level"]} {r["section_name"]}', r['subject_name'], r['learners'], r['k'], r['p'], r['u'], r['pd'],
                      r['overall'], (f'{r["level"]["name"]} ({r["level"]["letter"]})', r['level']['key']),
                      r['delta'] if r['delta'] is not None else '—']
    sh.table(columns, [line(r) for r in d['table']])
    if d['sections_view']:
        classes = report.sheet('Classes', [20, 26, 11, 9, 9, 9, 9, 11, 28, 13], subtitle=scope, meta=meta, title='Every class')
        classes.table(columns, [line(c) for r in d['table'] for c in r['subjects']])
    fc = d['forecast']
    if fc and fc['series']:
        labels = [p['label'] for p in fc['periods']]
        sh_fc = report.sheet('Forecast', [30] + [13] * len(labels), subtitle=scope, meta=meta, title='Averages by grading period, with forecast')
        sh_fc.paragraph(fc['method']['text'], color='4A5568', size=9)
        cell = lambda s, p: (f'{s["actual"][p]:.1f}' if p in s['actual'] else
                             f'{s["future"][p][0]:.1f} (forecast, {s["future"][p][1]:.1f} to {s["future"][p][2]:.1f})' if p in s['future'] else '—')
        sh_fc.table([{'title': 'Series', 'wrap': True}] + [{'title': lab, 'wrap': True} for lab in labels],
                    [[s['name']] + [cell(s, p['p']) for p in fc['periods']] for s in fc['series']])
    if d['at_risk']:
        sh2 = report.sheet('Learners below 75', [30, 22, 40, 14], subtitle=scope, meta=meta,
                           title='Learners below 75 (remediation required, DepEd Order No. 8, s. 2015)', landscape=False)
        sh2.table([{'title': 'Learner'}, {'title': 'Section'}, {'title': 'Subjects below 75', 'wrap': True},
                   {'title': 'Lowest grade', 'format': 'grade'}],
                  [[f['name'], f['section'], ', '.join(f'{i["subject"]} ({i["grade"]:.1f})' for i in f['items']),
                    (f['lowest'], 'beginning')] for f in d['at_risk']])
    name = safe_filename(school.short_name or 'school', 'academic-dashboard', d['scope_name'],
                         'all-periods' if d['all_periods'] else (d['period'].quarter_label if d['period'] else ''))
    return report.response(f'{name}.xlsx')


# =============================================================================================
# Section brief
# =============================================================================================

def support_text(row):
    tier = row.get('tier')
    if tier == 'intensive':
        return 'Intensive support: one-on-one remediation, checked weekly'
    if tier == 'targeted':
        if row['grade'] < PASSING:
            return 'Targeted support: small-group remediation'
        if row.get('projected') is not None and row['projected'] < PASSING:
            return 'Check in early: projected below 75'
        return 'Watch closely: just above 75'
    if tier == 'enrichment':
        return 'Enrichment or a peer-tutor role'
    if row.get('grade') is None:
        return 'No grade yet'
    return 'Regular class instruction'


def _section_data(school, section_id, subject_id, quarter_id):
    section = get_object_or_404(Section.objects.select_related('grade_level', 'adviser', 'school_year'), id=section_id, school=school)
    subject = get_object_or_404(Subject, id=subject_id, school=school)
    period = get_object_or_404(Quarter.objects.select_related('school_year'), id=quarter_id, school_year__school=school)
    sy = period.school_year
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number'))
    by_num = {q.quarter_number: q for q in periods}
    q = period.quarter_number
    prev_period, next_period = by_num.get(q - 1), by_num.get(q + 1)

    enrollments = list(Enrollment.objects.filter(section=section, school_year=sy, status__in=ACTIVE)
                       .select_related('student').order_by('student__last_name', 'student__first_name'))
    history, validated = defaultdict(dict), 0
    for r in GradeComponent.objects.filter(HAS_GRADE, enrollment_id__in=[e.id for e in enrollments], subject=subject,
                                           quarter__school_year=sy) \
            .values('enrollment_id', 'quarter__quarter_number', 'validation_status', grade=GRADE):
        history[r['enrollment_id']][r['quarter__quarter_number']] = float(r['grade'])
        if r['quarter__quarter_number'] == q and r['validation_status'] in VALIDATED:
            validated += 1
    class_means = {}
    for num in sorted({n for h in history.values() for n in h}):
        class_means[num] = mean(h[num] for h in history.values() if num in h)
    is_latest = bool(class_means) and q >= max(class_means) and q in class_means

    # forecasts: the grade model when it is trained (learner by learner), otherwise the damped trend
    table, meta = forecasts.year_table(school, sy)
    class_keys = [(e.id, subject.id) for e in enrollments]
    numbers = [p.quarter_number for p in periods]
    step_sd = insights.typical_step_sd(school.id)
    forecast_points, projected, chances = [], {}, {}
    if is_latest and periods and q < periods[-1].quarter_number:
        values = forecasts.series_values(table, class_keys, numbers, 'class', meta, step_sd) if meta else None
        if values and values[3] == q:
            forecast_points = [{'period': p, 'value': round(v, 1), 'low': round(lo, 1), 'high': round(hi, 1)}
                               for p, (v, lo, hi) in sorted(values[1].items())]
            for e in enrollments:
                nxt, chance = forecasts.learner_outlook(table, meta, (e.id, subject.id), q)
                if nxt is not None:
                    projected[e.id], chances[e.id] = nxt, chance
        else:
            forecast_points = insights.project_series([(n, v) for n, v in class_means.items() if n <= q], periods[-1].quarter_number, step_sd)
            projected, _ = insights.project_learners({eid: [(n, v) for n, v in h.items() if n <= q]
                                                      for eid, h in history.items() if q in h})
    forecast_next = next((f for f in forecast_points if f['period'] == q + 1), None)
    model_used = bool(meta) and bool(chances)
    parts = {e: (ww, pt, qa) for e, ww, pt, qa in GradeComponent.objects.filter(
        enrollment_id__in=[e.id for e in enrollments], subject=subject, quarter=period).values_list(
        'enrollment_id', 'written_work_percent', 'performance_task_percent', 'quarterly_assessment_percent')}

    level_grades = GradeComponent.objects.filter(
        HAS_GRADE, subject=subject, quarter__school_year=sy, enrollment__school_year=sy, enrollment__status__in=ACTIVE,
        enrollment__section__school=school, enrollment__section__grade_level_id=section.grade_level_id)
    level_means = {r['quarter__quarter_number']: float(r['avg'])
                   for r in level_grades.values('quarter__quarter_number').annotate(avg=Avg(GRADE))}
    section_avgs = [float(r['avg']) for r in level_grades.filter(quarter=period).values('enrollment__section_id').annotate(avg=Avg(GRADE))]
    my_avg = class_means.get(q)
    rank = (sum(1 for a in section_avgs if a > my_avg + 1e-9) + 1) if my_avg is not None else None

    assignment = ClassAssignment.objects.filter(section=section, subject=subject, school_year=sy, is_active=True) \
        .select_related('teacher').first()
    teacher = assignment.teacher if assignment else None

    learners, roster = [], []
    for e in enrollments:
        h, st = history.get(e.id, {}), e.student
        grade = h.get(q)
        ww, pt, qa = parts.get(e.id, (None, None, None))
        row = {'enrollment_id': e.id, 'lrn': st.lrn or '', 'name': f'{st.last_name}, {st.first_name}',
               'middle_initial': f'{st.middle_name[:1]}.' if st.middle_name else '',
               'grade': grade, 'previous': h.get(q - 1), 'projected': projected.get(e.id), 'chance': chances.get(e.id),
               'ww': float(ww) if ww is not None else None, 'pt': float(pt) if pt is not None else None,
               'qa': float(qa) if qa is not None else None}
        row['change'] = _r1(grade - row['previous']) if grade is not None and row['previous'] is not None else None
        if grade is not None:
            learners.append(row)
        roster.append(row)

    brief = None
    if learners:
        brief = insights.build_section_brief(
            section_name=section.section_name, grade_label=section.grade_level.grade_name if section.grade_level_id else 'grade level',
            subject_name=subject.subject_name, period_name=period_name(period),
            next_period_name=period_name(next_period) if forecast_next else '', prev_period_name=period_name(prev_period),
            teacher_name=_person(teacher), adviser_name=_person(section.adviser),
            learners=learners, enrolled=len(enrollments), validated=validated,
            grade_level_avg=level_means.get(q), rank=rank, rank_of=len(section_avgs),
            prev_avg=class_means.get(q - 1), forecast=forecast_next, quarters_with_data=len([n for n in class_means if n <= q]),
            method=forecasts.method_note(meta)['text'] if model_used else '')
    for row in roster:
        row['support'] = support_text(row)
        if row['grade'] is not None and 'level' not in row:
            row['level'] = level_of(row['grade'])
    roster.sort(key=lambda r: (r['grade'] is None, -(r['grade'] or 0), r['name']))

    distribution = [{'level': lv, 'count': sum(1 for l in learners if level_of(l['grade'])['key'] == lv['key'])}
                    for lv in reversed(LEVELS)]
    distribution_json = [{'name': d['level']['name'], 'letter': d['level']['letter'], 'count': d['count'],
                          'color': LEVEL_HEX[d['level']['key']]} for d in distribution]

    history_rows, last = [], None
    for num in sorted(class_means):
        vals = [h[num] for h in history.values() if num in h]
        history_rows.append({'name': period_name(by_num.get(num)) or f'Period {num}', 'average': round(class_means[num], 1),
                             'passing': round(100 * sum(1 for v in vals if v >= PASSING) / len(vals), 1),
                             'advanced': round(100 * sum(1 for v in vals if v >= 90) / len(vals), 1),
                             'below': sum(1 for v in vals if v < PASSING),
                             'change': _r1(class_means[num] - last) if last is not None else None, 'projected': False})
        last = class_means[num]
    for f in forecast_points:
        history_rows.append({'name': period_name(by_num.get(f['period'])), 'average': f['value'], 'low': f['low'],
                             'high': f['high'], 'projected': True})

    # the forecast chart: this section and its grade level's average, both with what comes next
    grade_name = section.grade_level.grade_name if section.grade_level_id else 'Grade level'
    same_grade = set(Section.objects.filter(school_year=sy, school=school, grade_level_id=section.grade_level_id).values_list('id', flat=True))
    grade_keys = [k for k, v in table.items() if v['subject'] == subject.id and v['section'] in same_grade]
    forecast_spec = forecasts.chart(table=table, meta=meta, periods=periods, step_sd=step_sd, selected=q, period_name=period_name, items=[
        {'key': 'section', 'name': section.section_name, 'keys': class_keys, 'level': 'class'},
        {'key': 'grade', 'name': f'{grade_name} average', 'keys': grade_keys, 'level': 'group'}])

    return {
        'section': section, 'subject': subject, 'quarter': period, 'school_year': sy, 'period_name': period_name(period),
        'prev_period_name': period_name(prev_period), 'next_period_name': period_name(next_period),
        'teacher': teacher, 'teacher_name': _person(teacher), 'adviser_name': _person(section.adviser),
        'brief': brief, 'roster': roster, 'graded': len(learners), 'enrolled': len(enrollments),
        'level': level_of(my_avg) if my_avg is not None else None, 'avg_grade': round(my_avg, 1) if my_avg is not None else None,
        'rank': rank, 'rank_of': len(section_avgs),
        'vs_grade_level': _r1(my_avg - level_means[q]) if my_avg is not None and q in level_means else None,
        'improvement': _r1(my_avg - class_means[q - 1]) if my_avg is not None and (q - 1) in class_means else None,
        'distribution': distribution, 'distribution_json': distribution_json, 'history_rows': history_rows,
        'forecast_next': forecast_next, 'prev_label': prev_period.quarter_label if prev_period else '',
        'forecast': forecast_spec, 'model_used': model_used,
        'is_latest': is_latest, 'has_grades': bool(learners), 'levels': LEVELS,
    }


@login_required
@cache_page_for_user()
def section_brief(request, section_id, subject_id, quarter_id):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    data = _section_data(school, section_id, subject_id, quarter_id)
    data['poro_token'] = insights.narrative_token(data['brief']['summary'], keep=data['brief']['keep']) if data['brief'] else ''
    data['export_url'] = reverse('heads-ai-section-export', args=[section_id, subject_id, quarter_id])
    data['live_fingerprint'] = school_fingerprint(school)
    return render(request, 'heads/ai_dashboard/section_detail.html', data)


@login_required
def section_export(request, section_id, subject_id, quarter_id):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    d = _section_data(school, section_id, subject_id, quarter_id)
    sec, subj, b = d['section'], d['subject'], d['brief']
    class_name = f'{sec.grade_level.grade_name if sec.grade_level_id else ""} {sec.section_name}'.strip()
    meta = [('Class', class_name), ('Subject', f'{subj.subject_name} ({subj.subject_code})'),
            ('Period', f'{d["period_name"]}, SY {d["school_year"].year_label}'),
            ('Subject teacher', d['teacher_name'] or 'Not assigned'), ('Adviser', d['adviser_name'] or 'Not assigned')]
    report = Report('Class Proficiency Report', school.school_name, _person(request.user))
    widths = [15, 26, 9, 28, 11, 11, 19, 34]

    sh = report.sheet('Report', [34, 40, 26, 18, 34], subtitle=f'{class_name} · {subj.subject_name} · {d["period_name"]}', meta=meta,
                      title='Class Proficiency Report and Poro AI Brief')
    if b:
        fc = b['forecast']
        sh.figures([
            ('Status', f'{b["level"]["name"]} ({b["level"]["letter"]})', None),
            ('Average', f'{b["average"]:.1f}%', None),
            ('Passing (75 and above)', f'{b["passing_rate"]:.1f}%', None),
            ('Below 75', str(b['below']), 'risk' if b['below'] else 'good'),
            ('Change vs ' + (d['prev_period_name'] or 'previous'), f'{b["delta"]:+.1f}' if b['delta'] is not None else '—',
             None if b['delta'] is None else ('good' if b['delta'] >= 0 else 'risk')),
            (f'Projected {d["next_period_name"]}' if fc else 'Projection', f'{fc["value"]:.1f}%' if fc else 'None', None),
            ('Projected range', f'{fc["low"]:.1f} to {fc["high"]:.1f}' if fc else '—', None),
            ('Confidence', b['confidence']['level'], b['confidence']['tone']),
        ])
        sh.heading('Summary')
        sh.paragraph(b['headline'], bold=True, color='00072D')
        sh.paragraph(b['summary'])
        sh.heading('Key findings')
        for i, f in enumerate(b['findings'], start=1):
            sh.paragraph(f'{i}. {f["title"]}', bold=True, color={'risk': 'C62828', 'warn': 'B45309', 'good': '2E7D32'}.get(f['tone'], '123499'))
            sh.paragraph(f['detail'], indent=2)
        if b['actions']:
            sh.page_break()
            sh.heading('Recommended actions for the School Head')
            sh.table([{'title': 'Action', 'wrap': True}, {'title': 'Why', 'wrap': True}, {'title': 'Who', 'wrap': True},
                      {'title': 'When', 'wrap': True}, {'title': 'Measure of success', 'wrap': True}],
                     [[a['title'], a['why'], a['who'], a['when'], a['measure']] for a in b['actions']])
        if b['plan']:
            plan = report.sheet('Level-up plan', [22, 10, 22, 14, 52, 26, 14, 30], subtitle=f'{class_name} · {subj.subject_name} · {d["period_name"]}',
                                meta=meta, title='Level-up plan: one step up for every level in the class')
            plan.paragraph('Each group\'s weakest grade component is the one furthest below the class average for it (DepEd Order No. 8, '
                           's. 2015 components). Levels follow DepEd Order No. 31, s. 2012.', color='4A5568', size=9)
            plan.table([{'title': 'Level', 'wrap': True}, {'title': 'Learners', 'format': 'int'}, {'title': 'Next level', 'wrap': True},
                        {'title': 'Points needed', 'wrap': True}, {'title': 'What to do', 'wrap': True}, {'title': 'Who', 'wrap': True},
                        {'title': 'When', 'wrap': True}, {'title': 'Measure of success', 'wrap': True}],
                       [[(f'{s["level"]["name"]} ({s["level"]["letter"]})', s['level']['key']), s['count'],
                         s['target']['name'] if s['target'] else 'Stay at Advanced',
                         f'{s["gap"][0]} to {s["gap"][1]}' if s['gap'] else '—', s['how'], s['who'], s['when'], s['measure']]
                        for s in b['plan']])
            for s in b['plan']:
                plan.paragraph(f'{s["level"]["name"]}: ' + ', '.join(f'{l["name"]} ({l["grade"]:.1f})' for l in s['learners']), size=9.5)
        if b['targets']:
            sh.heading(f'Targets for {d["next_period_name"]}' if d['next_period_name'] else 'Targets')
            for t in b['targets']:
                sh.paragraph(f'• {t}', indent=1)
        sh.heading('About this report')
        for note in b['notes'] + [f'Confidence {b["confidence"]["level"]}: {b["confidence"]["reason"]}']:
            sh.paragraph(note, color='4A5568', size=9.5)
    else:
        sh.paragraph('No grades for this class and period yet.')

    rows = d['roster']
    level_filter, search = request.GET.get('level', ''), (request.GET.get('q') or '').strip().lower()
    if level_filter:
        rows = [r for r in rows if r.get('level') and r['level']['key'] == level_filter]
    if search:
        rows = [r for r in rows if search in r['name'].lower() or search in r['lrn'].lower()]
    sh2 = report.sheet('Learners', widths, subtitle=f'{class_name} · {subj.subject_name} · {d["period_name"]}', meta=meta,
                       title='Learner Proficiency (DepEd Order No. 31, s. 2012)')
    sh2.table(
        [{'title': 'LRN'}, {'title': 'Learner'}, {'title': 'Grade', 'format': 'grade'}, {'title': 'Proficiency level'},
         {'title': f'Change vs {d["prev_period_name"]}' if d['prev_period_name'] else 'Change', 'format': 'delta'},
         {'title': f'Projected {d["next_period_name"]}' if d['next_period_name'] and b and b['forecast'] else 'Projected', 'format': 'grade'},
         {'title': 'Support tier', 'wrap': True}, {'title': 'Recommended support', 'wrap': True}],
        [[r['lrn'], f'{r["name"]} {r["middle_initial"]}'.strip(),
          r['grade'] if r['grade'] is not None else '—',
          (f'{r["level"]["name"]} ({r["level"]["letter"]})', r['level']['key']) if r.get('level') else 'No grade',
          r['change'] if r['change'] is not None else '—',
          r['projected'] if r['projected'] is not None else '—',
          insights.TIER_INFO[r['tier']]['name'] if r.get('tier') else '—', r['support']] for r in rows])
    sh2.heading('Proficiency levels')
    for lv in LEVELS:
        sh2.paragraph(f'{lv["name"]} ({lv["letter"]}), {lv["range"]}: {lv["meaning"]}', color='4A5568', size=9.5)

    if d['history_rows']:
        sh3 = report.sheet('Trend', [16, 12, 14, 14, 11, 11, 32], subtitle=f'{class_name} · {subj.subject_name}', meta=meta,
                           title='Trend and Projection', landscape=False)
        sh3.table([{'title': 'Period'}, {'title': 'Average', 'format': 'grade'}, {'title': 'Passing rate', 'format': 'percent'},
                   {'title': 'Advanced rate', 'format': 'percent'}, {'title': 'Below 75', 'format': 'int'},
                   {'title': 'Change', 'format': 'delta'}, {'title': 'Type'}],
                  [[h['name'], h['average'], h.get('passing', '—'), h.get('advanced', '—'), h.get('below', '—'),
                    h['change'] if h.get('change') is not None else '—',
                    f'Projected (range {h["low"]:.1f} to {h["high"]:.1f})' if h['projected'] else 'Actual'] for h in d['history_rows']])
    name = safe_filename(school.short_name or 'school', sec.section_name, subj.subject_code, d['quarter'].quarter_label)
    return report.response(f'{name}.xlsx')


@login_required
def poro_narrative(request, token):
    """Poro's reworded summary (or the computed wording when the model is not available)."""
    if _head_school(request) is None:
        return JsonResponse({'error': 'Access denied'}, status=403)
    result = insights.polish(token)
    if result is None:
        return JsonResponse({'error': 'Unknown summary'}, status=404)
    response = JsonResponse(result)
    response['Cache-Control'] = 'no-store'
    return response


# =============================================================================================
# Live updates and notifications
# =============================================================================================

def school_fingerprint(school):
    """Changes whenever a grade of the school is added, edited, validated or locked."""
    key = f'heads:fingerprint:{school.id}:{data_version()}'
    local = caches['local']
    value = local.get(key)
    if value is None:
        agg = GradeComponent.objects.filter(enrollment__section__school=school).aggregate(
            n=Count('id'), total=Sum(GRADE), last=Max('updated_at'),
            validated=Count('id', filter=Q(validation_status__in=VALIDATED)), locked=Count('id', filter=Q(is_locked=True)))
        value = hashlib.sha1(repr(sorted(agg.items())).encode()).hexdigest()[:16]
        local.set(key, value, 15)
    return value


ICONS = {'GRADE_VALIDATED': 'fi-rr-shield-check', 'GRADE_RETURNED': 'fi-rr-undo', 'ANNOUNCEMENT_POSTED': 'fi-rr-megaphone',
         'ANNOUNCEMENT_URGENT': 'fi-rr-megaphone', 'ATTENDANCE_ALERT': 'fi-rr-user-time', 'SYSTEM_UPDATE': 'fi-rr-info'}


@login_required
def live_updates(request):
    """Polled by the School Head's pages: data fingerprint and the latest notifications."""
    school = _head_school(request)
    if school is None:
        return JsonResponse({'error': 'Access denied'}, status=403)
    mine = Notification.objects.filter(recipient=request.user, is_dismissed=False)
    items = []
    for n in mine.order_by('-created_at')[:8]:
        items.append({'id': n.id, 'title': n.title, 'message': n.message, 'unread': not n.is_read,
                      'priority': n.priority, 'icon': ICONS.get(n.notification_type, 'fi-rr-bell'),
                      'when': timezone.localtime(n.created_at).strftime('%b %d, %I:%M %p').replace(' 0', ' '),
                      'url': reverse('heads-open-notification', args=[n.id]) if n.action_url else ''})
    response = JsonResponse({'fingerprint': school_fingerprint(school), 'unread': mine.filter(is_read=False).count(),
                             'notifications': items,
                             'checked_at': timezone.localtime().strftime('%I:%M %p').lstrip('0')})
    response['Cache-Control'] = 'no-store'
    return response


@login_required
def open_notification(request, notification_id):
    """Mark a notification read and go to the page it points to (only pages of this site)."""
    note = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not note.is_read:
        note.is_read, note.read_at = True, timezone.now()
        note.save(update_fields=['is_read', 'read_at'])
    target = note.action_url or reverse('heads-ai-dashboard')
    if not url_has_allowed_host_and_scheme(target, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        target = reverse('heads-ai-dashboard')
    return redirect(target)
