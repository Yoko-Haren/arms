"""School Head: Academic Dashboard, Poro AI's recommendations, report download and live updates."""
import hashlib
from collections import defaultdict
from statistics import mean

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.cache import caches
from django.db.models import Avg, Count, F, Max, Q, Sum
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme, urlencode

from academics.models import GradeLevel, Quarter, SchoolYear, Section, Subject, SubjectFamily
from communication.models import Notification
from core import grading_policy as policy
from core.caching import cache_page_for_user, data_version, remember_filters
from core.periods import GRADE, HAS_GRADE
from core.xlsx import Report, safe_filename
from grades.models import GradeComponent

from . import forecasts, insights, poro
from .insights import PASSING, level_of
from .notify import subject_view_url

ACTIVE = ['Enrolled', 'Transferred_In']
VALIDATED = ('Validated', 'Finalized')
PERIOD_WORD = {'Q': 'Quarter', 'T': 'Term', 'S': 'Semester'}
GRADE_SCOPES = {'jhs': 'All Junior High', 'shs': 'All Senior High'}
LADDER_ROWS = 3            # each level on the status card lists at most this many items; "Show all" opens every one


def period_name(q):
    return f'{PERIOD_WORD.get((q.quarter_label or "Q")[:1].upper(), "Quarter")} {q.quarter_number}' if q else ''


def _head_school(request):
    profile = getattr(request.user, 'profile', None)
    if not profile or profile.role != 'schoolhead':
        return None
    policy.activate(profile.school)          # the school's DepEd rules for levels and awards, for this request
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


def _parts(group):
    """Average written work, performance task and quarterly assessment (or examination) scores of a group of grades,
    from the component percents of its uploaded class records; None where a component has no scores."""
    return {key: round(mean(group[key]), 1) if group[key] else None for key in ('ww', 'pt', 'qa')}


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
    """The five levels of the school's DepEd order, the lowest first, each listing the items whose average falls in it."""
    total = len(items) or 1
    ladder = []
    for lv in reversed(policy.levels()):
        mine = sorted([i for i in items if i['level']['key'] == lv['key']], key=lambda i: -i['average'])
        ladder.append({'level': lv, 'items': mine, 'count': len(mine), 'share': round(100 * len(mine) / total),
                       'more': max(len(mine) - LADDER_ROWS, 0)})
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
    ref_period = period or latest                                # the forecast and the decisions look ahead from a real period
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
    query = {'school_year': sy.id if sy else '', 'quarter': quarter_value}

    base = GradeComponent.objects.filter(HAS_GRADE, subject_id__in=ids, enrollment__school_year=sy, enrollment__status__in=ACTIVE,
                                         enrollment__section__school=school)
    fields = ('enrollment_id', 'enrollment__student_id', 'enrollment__section_id', 'enrollment__section__section_name',
              'enrollment__section__grade_level__grade_name', 'subject_id')
    rows = []
    if ids and (period or all_periods):
        found = list((base.filter(quarter__in=span) if all_periods else base.filter(quarter=period)).values(
            *fields, grade=GRADE, ww=F('written_work_percent'), pt=F('performance_task_percent'), qa=F('quarterly_assessment_percent')))
        if all_periods:
            merged = {}
            for r in found:
                m = merged.setdefault((r['enrollment_id'], r['subject_id']), dict(r, grades=[], parts={'ww': [], 'pt': [], 'qa': []}))
                m['grades'].append(float(r['grade']))
                for key in ('ww', 'pt', 'qa'):
                    if r[key] is not None:
                        m['parts'][key].append(float(r[key]))
            rows = [dict(m, grade=mean(m['grades']), **{k: mean(v) if v else None for k, v in m['parts'].items()})
                    for m in merged.values()]
        else:
            rows = found
    prev_avg = base.filter(quarter=prev_period).aggregate(avg=Avg(GRADE))['avg'] if ids and prev_period else None

    # where each item stands (the status card's levels) and what to decide for it: disciplines, subjects or sections
    if all_families:
        item_word, family_of, names = 'discipline', {s.id: s.subject_family_id for s in scope}, {f.id: f.family_name for f in families}
        key_of, name_of = (lambda r: family_of.get(r['subject_id'])), (lambda k: names.get(k, 'Other subjects'))
        link = lambda k: '?' + urlencode({'view_mode': 'family', 'subject_family': k, 'grade_level': grade_key, **query}) if k else ''
    elif mode == 'family' and len({r['subject_id'] for r in rows}) > 1:
        item_word = 'subject'
        key_of, name_of = (lambda r: r['subject_id']), (lambda k: subject_by_id[k].subject_name)
        link = lambda k: '?' + urlencode({'view_mode': 'subject', 'subject': k, **query})
    else:
        item_word = 'section'
        names = {r['enrollment__section_id']: (f'{r["enrollment__section__grade_level__grade_name"] or ""} ' if mode == 'family' else '')
                 + r['enrollment__section__section_name'] for r in rows}
        key_of, name_of, link = (lambda r: r['enrollment__section_id']), names.get, (lambda k: '')
    groups, whole = defaultdict(lambda: {'grades': [], 'ww': [], 'pt': [], 'qa': []}), {'grades': [], 'ww': [], 'pt': [], 'qa': []}
    for r in rows:
        for g in (groups[key_of(r)], whole):
            g['grades'].append(float(r['grade']))
            for part in ('ww', 'pt', 'qa'):
                if r[part] is not None:
                    g[part].append(float(r[part]))
    overall = _parts(whole)
    items = []
    for k, g in groups.items():
        avg, parts = round(mean(g['grades']), 1), _parts(g)
        weak = insights.weakest(parts)
        items.append({'name': name_of(k), 'average': avg, 'level': level_of(avg), 'grades': len(g['grades']), **parts,
                      'below': 100 * sum(1 for x in g['grades'] if x < PASSING) / len(g['grades']),
                      'weak': weak, 'parts': insights.part_scores(parts, weak), 'url': link(k)})
    ladder = _ladder(items) if items else []

    grades = whole['grades']
    status = None
    if grades:
        average = mean(grades)
        status = {
            'level': level_of(round(average, 1)), 'average': round(average, 1),
            'delta': _r1(average - float(prev_avg)) if prev_avg is not None else None,
            'delta_abs': _r1(abs(average - float(prev_avg))) if prev_avg is not None else None,
            'learners': len({r['enrollment__student_id'] for r in rows}),
            'classes': len({(r['enrollment__section_id'], r['subject_id']) for r in rows}),
            'sections': len({r['enrollment__section_id'] for r in rows}),
            'passing_rate': round(100 * sum(1 for g in grades if g >= PASSING) / len(grades), 1),
            'below': len({r['enrollment__student_id'] for r in rows if float(r['grade']) < PASSING}),
        }

    # what the School Head should decide: first for the selection's own level (its status), then for every other level
    # that has items on it, the lowest first, looking ahead to the next grading period
    decisions, main = [], None
    if items:
        after = next((q for q in periods if ref_period and q.quarter_number == ref_period.quarter_number + 1), None)
        decisions = insights.school_decisions(
            items, next_period_name=period_name(after), item_word=item_word,
            topic=subject_by_id[rows[0]['subject_id']].subject_name if item_word == 'section' else '')
        if all_families:
            scope_words = 'The school' if not grade_set else grade_label.replace('All ', '', 1)
        else:
            scope_words = scope_name + (f' in {grade_label}' if mode == 'family' and grade_set else '')
        main, decisions = insights.main_decision(decisions, scope=scope_words, average=status['average'] if status else None,
                                                 overall=overall, next_period_name=period_name(after))

    # the forecast chart: disciplines, grade levels or sections over the school year, with what comes next
    forecast_spec = None
    table_, meta = forecasts.year_table(school, sy) if ids else ({}, None)
    if ids and periods and table_:
        in_scope = {k for k, v in table_.items() if v['subject'] in set(ids)}
        if all_families:
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
            section_names = dict(Section.objects.filter(id__in={table_[k]['section'] for k in in_scope}).values_list('id', 'section_name'))
            items_fc = [{'key': f'section-{sid}', 'name': section_names.get(sid, 'Section'), 'url': '',
                         'keys': [k for k in in_scope if table_[k]['section'] == sid]} for sid in sorted(section_names, key=lambda i: section_names[i])]
            level, fc_word = 'class', 'section'
        forecast_spec = forecasts.chart(
            table=table_, meta=meta, periods=periods, items=items_fc, level=level, step_sd=insights.typical_step_sd(school.id),
            reference={'key': 'all', 'name': scope_name if mode == 'subject' or all_families or not grade_set else f'{scope_name}, {grade_label}',
                       'keys': list(in_scope)},
            selected=None if all_periods else (period.quarter_number if period else None), period_name=period_name)
        forecast_spec['word'] = fc_word

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
        'scope_name': scope_name, 'scope_detail': scope_detail,
        'status': status, 'levels': policy.levels(), 'items': items, 'main': main, 'decisions': decisions,
        'ladder': ladder, 'ladder_word': item_word if items else '', 'ladder_rows': LADDER_ROWS, 'forecast': forecast_spec,
    }


def _poro_token(main, decisions):
    """The token Poro AI rewords the recommendations under (heads/poro.py), or '' when there are none."""
    fields = ({'main': main['text']} if main else {}) | {f'decision-{i}': d['text'] for i, d in enumerate(decisions)}
    if not fields:
        return ''
    return poro.register(fields, keep=[i['name'] for d in ([main] if main else []) + decisions for i in d['items']])


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
    data['poro_token'] = _poro_token(data['main'], data['decisions'])
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
    sh = report.sheet('Summary', [24, 24, 24, 24], subtitle=scope, meta=meta)
    st = d['status']
    if st:
        sh.figures([
            ('Status', f'{st["level"]["name"]} ({st["level"]["letter"]})', None),
            ('Average', f'{st["average"]:.1f}%', None),
            ('Passing (75 and above)', f'{st["passing_rate"]:.1f}%', None),
            ('Learners below 75', str(st['below']), 'risk' if st['below'] else 'good'),
        ])
        sh.paragraph(st['level']['meaning'], color='4A5568', size=10)
        if d['main'] or d['decisions']:
            sh.heading('Poro AI recommends')
            written = poro.written(_poro_token(d['main'], d['decisions']))
            parts_line = lambda parts: ' · '.join(f'{p["abbr"]} {p["value"]:.1f}' + (' (weakest)' if p['weak'] else '')
                                                  for p in parts if p['value'] is not None)
            if d['main']:
                m = d['main']
                sh.paragraph(f'Main recommendation, {m["level"]["name"]} ({m["level"]["letter"]}): {m["title"]}', bold=True)
                sh.paragraph(parts_line(m['parts']), color='4A5568', size=9.5, indent=1)
                sh.paragraph(written.get('main') or m['text'], indent=1)
            if d['decisions']:
                sh.paragraph('Other recommendations, the lowest level first', bold=True, color='4A5568')
            for i, dec in enumerate(d['decisions']):
                sh.paragraph(f'{dec["level"]["name"]} ({dec["level"]["letter"]}): {dec["title"]}', bold=True)
                sh.paragraph('; '.join(f'{i["name"]} {i["average"]:.1f} ({parts_line(i["parts"])})' for i in dec['items']),
                             color='4A5568', size=9.5, indent=1)
                sh.paragraph(written.get(f'decision-{i}') or dec['text'], indent=1)
            sh.paragraph('Decided from the grades by rules a person can check' + (
                '; worded by Poro AI, every number, name and level checked against the computed wording.' if written else '.'),
                color='4A5568', size=9)
        if d['ladder']:
            sh.heading(f'Where each {d["ladder_word"]} stands')
            for step in d['ladder']:
                names = ', '.join(f'{i["name"]} ({i["average"]:.1f})' for i in step['items']) or 'None'
                sh.paragraph(f'{step["level"]["name"]} ({step["level"]["letter"]}, {step["level"]["range"]}): {names}', size=10)
    else:
        sh.paragraph('No grades for this selection yet.')
    if d['items']:
        title = d['ladder_word'].capitalize() + 's'
        parts, weak_names = policy.components(), dict(insights.components())
        items = report.sheet(title, [36, 10, 9, 9, 9, 10, 26, 12, 30], subtitle=scope, meta=meta,
                             title=f'{title}: levels and grade components')
        items.paragraph(', '.join(f'{abbr} is the average {name.lower()} score' for _, name, abbr in parts)
                        + ' in percent, from the uploaded class records. The weakest part is the lowest of the three.',
                        color='4A5568', size=9)
        items.table([{'title': title[:-1], 'wrap': True}, {'title': 'Grades', 'format': 'int'}]
                    + [{'title': abbr, 'format': 'grade'} for _, _, abbr in parts]
                    + [{'title': 'Average', 'format': 'grade'}, {'title': 'Level'}, {'title': 'Below 75', 'format': 'percent'},
                       {'title': 'Weakest part', 'wrap': True}],
                    [[i['name'], i['grades']] + [i[key] if i[key] is not None else '—' for key, _, _ in parts]
                     + [i['average'], (f'{i["level"]["name"]} ({i["level"]["letter"]})', i['level']['key']), round(i['below'], 1),
                        weak_names.get(i['weak'], '—')] for i in sorted(d['items'], key=lambda i: i['average'])])
    fc = d['forecast']
    if fc and fc['series']:
        labels = [p['label'] for p in fc['periods']]
        sh_fc = report.sheet('Forecast', [30] + [13] * len(labels), subtitle=scope, meta=meta, title='Averages by grading period, with forecast')
        sh_fc.paragraph(fc['method']['text'], color='4A5568', size=9)
        cell = lambda s, p: (f'{s["actual"][p]:.1f}' if p in s['actual'] else
                             f'{s["future"][p][0]:.1f} (forecast, {s["future"][p][1]:.1f} to {s["future"][p][2]:.1f})' if p in s['future'] else '—')
        sh_fc.table([{'title': 'Series', 'wrap': True}] + [{'title': lab, 'wrap': True} for lab in labels],
                    [[s['name']] + [cell(s, p['p']) for p in fc['periods']] for s in fc['series']])
    name = safe_filename(school.short_name or 'school', 'academic-dashboard', d['scope_name'],
                         'all-periods' if d['all_periods'] else (d['period'].quarter_label if d['period'] else ''))
    return report.response(f'{name}.xlsx')


@login_required
def poro_status(request, token):
    """Poro AI's wording of the dashboard's recommendations: {'state': 'writing'} with the sentences that passed so
    far, then the result (heads/poro.py)."""
    if _head_school(request) is None:
        return JsonResponse({'error': 'Access denied'}, status=403)
    result = poro.status(token)
    if result is None:
        return JsonResponse({'error': 'Unknown recommendations'}, status=404)
    response = JsonResponse(result)
    response['Cache-Control'] = 'no-store'
    return response


@login_required
def section_moved(request, section_id, subject_id, quarter_id):
    """Old links to a section brief (notifications, bookmarks). A section's grades are its adviser's to follow now (the
    teacher portal's My Advisory), so the School Head lands on the dashboard for that subject and period."""
    school = _head_school(request)
    if school is None:
        return _denied(request)
    quarter = Quarter.objects.filter(id=quarter_id, school_year__school=school).first()
    if quarter is None or not Subject.objects.filter(id=subject_id, school=school).exists():
        return redirect('heads-ai-dashboard')
    return redirect(subject_view_url(subject_id, quarter))


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
