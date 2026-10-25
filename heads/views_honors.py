"""School Head: Honors Outlook, who is on track for an academic award this school year, and who is close.

The rules come from the DepEd order the school follows (core/grading_policy.py):
- DepEd Order No. 36, s. 2016 (with DO 8, s. 2015): With Honors 90-94, With High Honors 95-97 and With Highest
  Honors 98-100, for a general average with every learning area passed.
- DepEd Order No. 015, s. 2026: one Academic Excellence Award for a general average of at least 90 with no final
  grade below 80 and no derogatory record. ARMS keeps no discipline records, so that last condition stays with the
  school; awardees are listed alphabetically, as the order asks.

A learning area's final grade is the average of its grading-period grades and the general average the average of
the final grades, each rounded to a whole number as DepEd reports them. "Now" uses the periods with grades; the
year-end outlook adds the grade forecaster's prediction for every period still to come (ml_engine/forecast.py), so
it reads where the year ends if nothing changes. A school that gives Senior High awards per semester should read it
as the school year so far.
"""
from collections import defaultdict
from statistics import mean

from django.contrib.auth.decorators import login_required
from django.shortcuts import render
from django.urls import reverse
from django.utils.http import urlencode

from academics.models import GradeLevel, Quarter, SchoolYear, Subject
from core import grading_policy as policy
from core.caching import cache_page_for_user, remember_filters
from core.xlsx import Report, safe_filename
from enrollment.models import Enrollment

from . import forecasts
from .views_academic import ACTIVE, GRADE_SCOPES, _denied, _grade_scope, _head_school, _person, period_name

CLOSE = 2                 # points from the next award that count as close
PREVIEW = 10              # rows per list on the page; "Show all" opens the rest


def _award_name(award):
    return award[1] if award else ''


def _next_cut(ga, awards):
    """(cut, name) of the nearest award above a general average, or None at the top."""
    above = [(cut, name) for cut, _, name in awards['tiers'] if cut > ga]
    if not above:
        return None
    return min(above)


def _honors_data(params, school):
    school_years = list(SchoolYear.objects.filter(school=school).order_by('-year_start'))
    sy = next((s for s in school_years if str(s.id) == str(params.get('school_year'))), None) or \
        next((s for s in school_years if s.is_current), None) or (school_years[0] if school_years else None)
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number')) if sy else []
    grade_levels = list(GradeLevel.objects.filter(school=school).order_by('sort_order'))
    grade_set, grade_key, grade_label = _grade_scope(params.get('grade_level', 'all'), grade_levels)
    rules = policy.current()
    awards = rules['awards']
    table, meta = forecasts.year_table(school, sy) if sy else ({}, None)
    subjects = {s.id: s for s in Subject.objects.filter(school=school)}

    by_learner = defaultdict(list)
    for (enrollment_id, subject_id), row in table.items():
        if row['actual']:
            by_learner[enrollment_id].append((subject_id, row))
    enrollments = Enrollment.objects.filter(school_year=sy, status__in=ACTIVE, section__school=school) \
        .select_related('student', 'section__grade_level') if sy else Enrollment.objects.none()
    if grade_set:
        enrollments = enrollments.filter(section__grade_level__in=grade_set)
    graded_periods = sorted({p for rows in by_learner.values() for _, row in rows for p in row['actual']})
    to_come = [q for q in periods if graded_periods and q.quarter_number > graded_periods[-1]]
    forecasting = bool(meta) and bool(to_come)

    learners = []
    for e in enrollments:
        rows = by_learner.get(e.id)
        if not rows:
            continue
        finals, projected = {}, {}
        for subject_id, row in rows:
            finals[subject_id] = policy.whole(mean(row['actual'].values()))
            ahead = [v for p, v in row['future'].items() if p not in row['actual']] if forecasting else []
            projected[subject_id] = policy.whole(mean(list(row['actual'].values()) + ahead))
        ga_exact = mean(finals.values())
        ga, ga_projected = policy.whole(ga_exact), policy.whole(mean(projected.values()))
        lowest = sorted(finals.items(), key=lambda kv: kv[1])
        below_floor = [(subjects[s].subject_code if s in subjects else str(s), g) for s, g in lowest if g < awards['floor']]
        award = policy.award_of(ga, lowest[0][1])
        award_projected = policy.award_of(ga_projected, min(projected.values())) if forecasting else award
        nxt = _next_cut(ga, awards)
        learners.append({
            'id': e.id, 'name': f'{e.student.last_name}, {e.student.first_name}',
            'section': e.section.section_name, 'grade': e.section.grade_level.grade_name if e.section.grade_level_id else '',
            'grade_id': e.section.grade_level_id, 'ga': ga, 'ga_exact': round(ga_exact, 2), 'ga_projected': ga_projected,
            'award': award, 'award_name': _award_name(award), 'award_projected': award_projected,
            'award_projected_name': _award_name(award_projected), 'subjects': len(finals),
            'lowest': [(subjects[s].subject_code if s in subjects else str(s), g) for s, g in lowest[:2]],
            'below_floor': below_floor,
            # the nearest award above: how many points it takes (only when no learning area blocks it)
            'next': nxt[1] if nxt and not below_floor else '', 'gap': (nxt[0] - ga) if nxt and not below_floor else None,
        })

    on_track = [l for l in learners if l['award']]
    if awards['kind'] == 'single':
        on_track.sort(key=lambda l: l['name'])                      # DO 015: listed alphabetically, not ranked
    else:
        on_track.sort(key=lambda l: (-l['ga_exact'], l['name']))
    close = sorted([l for l in learners if l['gap'] is not None and 0 < l['gap'] <= CLOSE],
                   key=lambda l: (l['gap'], -l['ga_exact'], l['name']))
    held = sorted([l for l in learners if l['below_floor'] and l['ga'] >= awards['tiers'][-1][0]],
                  key=lambda l: (-l['ga_exact'], l['name']))
    projected_count = sum(1 for l in learners if l['award_projected'])

    tiers = [{'key': key, 'name': name, 'cut': cut, 'now': sum(1 for l in on_track if l['award'][0] == key),
              'projected': sum(1 for l in learners if l['award_projected'] and l['award_projected'][0] == key)}
             for cut, key, name in reversed(awards['tiers'])]
    by_grade = []
    for g in (grade_set or grade_levels):
        mine = [l for l in learners if l['grade_id'] == g.id]
        if not mine:
            continue
        by_grade.append({'name': g.grade_name, 'learners': len(mine), 'now': sum(1 for l in mine if l['award']),
                         'projected': sum(1 for l in mine if l['award_projected']),
                         'close': sum(1 for l in close if l['grade_id'] == g.id),
                         'held': sum(1 for l in held if l['grade_id'] == g.id),
                         'url': '?' + urlencode({'school_year': sy.id, 'grade_level': g.id})})
    return {
        'school_years': school_years, 'sy': sy, 'grade_levels': grade_levels, 'grade_id': grade_key, 'grade_label': grade_label,
        'grade_scopes': [{'value': k, 'name': _grade_scope(k, grade_levels)[2]} for k in GRADE_SCOPES
                         if any(bool(g.is_senior_high) == (k == 'shs') for g in grade_levels)],
        'rules': rules, 'awards': awards, 'learners': learners, 'on_track': on_track, 'close': close, 'held': held,
        'projected_count': projected_count, 'tiers': tiers, 'by_grade': by_grade, 'forecasting': forecasting,
        'graded_through': period_name(next((q for q in periods if graded_periods and q.quarter_number == graded_periods[-1]), None)),
        'year_end': period_name(periods[-1]) if periods else '', 'to_come': [period_name(q) for q in to_come],
        'method': forecasts.method_note(meta)['text'] if forecasting else '', 'close_points': CLOSE, 'preview': PREVIEW,
        'track_hint': ('Listed alphabetically, as DepEd Order No. 015, s. 2026 asks.' if awards['kind'] == 'single'
                       else 'Highest general average first.'),
    }


@login_required
@remember_filters('heads-honors', ['school_year', 'grade_level'])
@cache_page_for_user()
def honors_outlook(request):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    data = _honors_data(request.GET, school)
    data['export_url'] = reverse('heads-honors-export') + ('?' + request.GET.urlencode() if request.GET else '')
    return render(request, 'heads/honors/index.html', data)


@login_required
def honors_export(request):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    d = _honors_data(request.GET, school)
    awards = d['awards']
    scope = d['grade_label']
    meta = [('Grade levels', scope), ('School year', f'SY {d["sy"].year_label}' if d['sy'] else ''),
            ('Grades through', d['graded_through'] or 'none yet'), ('Rules', awards['order'])]
    report = Report('Honors Outlook', school.school_name, _person(request.user))
    sh = report.sheet('On track', [30, 18, 14, 11, 13, 26, 26], subtitle=scope, meta=meta, title=f'On track for {awards["label"]}')
    sh.paragraph(awards['rule'], color='4A5568', size=9)
    if awards['kind'] == 'single':
        sh.paragraph('ARMS keeps no discipline records: confirm that each learner has no derogatory record or disciplinary case.',
                     color='4A5568', size=9)
    columns = [{'title': 'Learner', 'wrap': True}, {'title': 'Section'}, {'title': 'Grade level'},
               {'title': 'General average', 'format': 'grade'}, {'title': 'Whole number', 'format': 'int'},
               {'title': 'Award now', 'wrap': True}, {'title': f'At year end ({d["year_end"]})', 'wrap': True}]
    sh.table(columns, [[l['name'], l['section'], l['grade'], l['ga_exact'], l['ga'], l['award_name'],
                        l['award_projected_name'] or '—'] for l in d['on_track']])
    sh2 = report.sheet('Close', [30, 18, 14, 11, 12, 26, 30], subtitle=scope, meta=meta,
                       title=f'Within {d["close_points"]} points of an award')
    sh2.table([{'title': 'Learner', 'wrap': True}, {'title': 'Section'}, {'title': 'Grade level'},
               {'title': 'General average', 'format': 'grade'}, {'title': 'Points to go', 'format': 'int'},
               {'title': 'Next award', 'wrap': True}, {'title': 'Lowest learning areas', 'wrap': True}],
              [[l['name'], l['section'], l['grade'], l['ga_exact'], l['gap'], l['next'],
                ', '.join(f'{c} ({g})' for c, g in l['lowest'])] for l in d['close']])
    if d['held']:
        sh3 = report.sheet('Held back', [30, 18, 14, 11, 40], subtitle=scope, meta=meta,
                           title=f'An average of {awards["tiers"][-1][0]} or more, held back by a learning area')
        sh3.table([{'title': 'Learner', 'wrap': True}, {'title': 'Section'}, {'title': 'Grade level'},
                   {'title': 'General average', 'format': 'grade'}, {'title': f'Below {awards["floor"]}', 'wrap': True}],
                  [[l['name'], l['section'], l['grade'], l['ga_exact'], ', '.join(f'{c} ({g})' for c, g in l['below_floor'])]
                   for l in d['held']])
    name = safe_filename(school.short_name or 'school', 'honors-outlook', d['sy'].year_label if d['sy'] else '', scope)
    return report.response(f'{name}.xlsx')
