"""Analysis behind the School Head's Academic Dashboard and the section brief (Poro AI).

Everything a report states is computed here from the grades, with rules a person can check:

- Levels and remediation follow the DepEd order the school chose (core/grading_policy.py): the
  descriptors of DepEd Order No. 8, s. 2015 (Outstanding to Did Not Meet Expectations) or of DepEd
  Order No. 015, s. 2026 (Advancing to Emerging). Below 75 a learner needs remediation under either.
- Support tiers: a multi-tiered system of supports (core for everyone, targeted, intensive). When
  more than about 1 in 5 learners need extra help, the whole-class (core) instruction is reviewed.
- Projections: damped trend (Gardner & McKenzie) over this school year's quarters. The likely range
  comes from how much section averages in this school usually move from one quarter to the next.

Poro AI (heads/poro.py) writes the words of each part from these facts; its text is shown only when every
number, name and level in it checks out against the data.
"""
import hashlib
import math
import re
from collections import defaultdict
from statistics import mean, pstdev

from django.core.cache import caches
from django.db.models import Avg, Count

from core import grading_policy as policy
from core.caching import data_version
from core.grading_policy import PASSING, level_of

NEAR_PASSING = 77          # 75 up to (not including) 77: one weak assessment from falling below 75
PHI_SECTION = 0.8          # damping of a class trend per quarter
PHI_LEARNER = 0.7          # damping of a learner's own trend
Z90 = 1.645                # 90% range

# The five levels come from the school's DepEd order (core/grading_policy.py). Their slot keys, lowest
# 'beginning' to highest 'advanced', are the same under every order, so steps and ranks are written once.
LEVEL_RANK = {'beginning': 1, 'developing': 2, 'approaching': 3, 'proficient': 4, 'advanced': 5}
NEXT_LEVEL = {'beginning': 'developing', 'developing': 'approaching', 'approaching': 'proficient', 'proficient': 'advanced'}


def _next_level(lv):
    return policy.level_by_key().get(NEXT_LEVEL.get(lv['key'], ''))


def _clamp(value, low=50.0, high=100.0):
    return max(low, min(high, value))


def _s(n, word='learner'):
    return f'{n} {word}' + ('' if n == 1 else 's')


def _verb(n):
    return 'is' if n == 1 else 'are'


def _pct(value):
    return f'{value:.1f}%'


def _a(value):
    """'an' before numbers read with a vowel sound (eighty..., eleven, eighteen), otherwise 'a'."""
    text = f'{value:.1f}'
    return 'an' if text.startswith('8') or text.startswith(('11.', '18.')) else 'a'


def _share(part, whole):
    return f'{round(100 * part / whole)}%' if whole else '0%'


# --------------------------------------------------------------------------------------------
# Projections
# --------------------------------------------------------------------------------------------

def slope(points):
    """Least-squares slope of (x, y) points; 0 with fewer than two points."""
    n = len(points)
    if n < 2:
        return 0.0
    mx = sum(x for x, _ in points) / n
    my = sum(y for _, y in points) / n
    sxx = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / sxx if sxx else 0.0


def project_series(points, last_period, step_sd, phi=PHI_SECTION):
    """Project a class average for the periods after the last one with data.

    points: [(period_number, average)]. Starts from the latest average and adds a damped share of
    the trend, so a short run of quarters cannot be stretched into a runaway line. The range widens
    with each step ahead and is wider when fewer quarters are known.
    """
    if not points:
        return []
    points = sorted(points)
    x_last, y_last = points[-1]
    b = slope(points)
    widen = 1.0 if len(points) >= 3 else (1.25 if len(points) == 2 else 1.6)
    out, damp = [], 0.0
    for h in range(1, last_period - x_last + 1):
        damp += phi ** h
        value = _clamp(y_last + b * damp)
        half = Z90 * step_sd * math.sqrt(h) * widen
        out.append({'period': x_last + h, 'value': round(value, 1),
                    'low': round(_clamp(value - half), 1), 'high': round(_clamp(value + half), 1)})
    return out


def project_learners(histories, phi=PHI_LEARNER):
    """Next-period grade for each learner of one class, if nothing changes.

    histories: {key: [(period_number, grade), ...]}. Each learner's own quarter-to-quarter change is
    trusted more the more changes we have seen (weight k/(k+3)); the rest comes from the class's
    average change. The result is damped (phi) because grades drift back toward the learner's usual level.
    """
    per, all_changes = {}, []
    for key, h in histories.items():
        h = sorted(h)
        changes = [g2 - g1 for (p1, g1), (p2, g2) in zip(h, h[1:])]
        per[key] = (h, changes)
        all_changes.extend(changes)
    class_change = mean(all_changes) if all_changes else 0.0
    projected = {}
    for key, (h, changes) in per.items():
        w = len(changes) / (len(changes) + 3)
        own = mean(changes) if changes else 0.0
        projected[key] = round(_clamp(h[-1][1] + phi * (w * own + (1 - w) * class_change)), 1)
    return projected, class_change


def typical_step_sd(school_id):
    """How much a section's average in one subject usually moves from one quarter to the next (SD).

    Measured on this school's own records (all school years), cached until data changes.
    """
    from core.periods import GRADE, HAS_GRADE
    from grades.models import GradeComponent

    key = f'insights:step-sd:{school_id}:{data_version()}'
    cache = caches['default']
    cached = cache.get(key)
    if cached is not None:
        return cached
    rows = (GradeComponent.objects
            .filter(HAS_GRADE, enrollment__section__school_id=school_id)
            .values('enrollment__section_id', 'subject_id', 'quarter__school_year_id', 'quarter__quarter_number')
            .annotate(avg=Avg(GRADE), n=Count('id')))
    series = defaultdict(dict)
    for r in rows:
        if r['n'] >= 5:
            series[(r['enrollment__section_id'], r['subject_id'], r['quarter__school_year_id'])][r['quarter__quarter_number']] = float(r['avg'])
    changes = []
    for s in series.values():
        nums = sorted(s)
        changes += [s[b] - s[a] for a, b in zip(nums, nums[1:]) if b == a + 1]
    sd = pstdev(changes) if len(changes) >= 10 else 2.5
    sd = round(min(max(sd, 1.0), 6.0), 2)
    cache.set(key, sd, 6 * 3600)
    return sd


# --------------------------------------------------------------------------------------------
# Section brief
# --------------------------------------------------------------------------------------------

def support_tier(grade, projected=None, previous=None):
    """Which kind of support a learner needs now: intensive, targeted, enrichment or core."""
    if grade < 70 or (projected is not None and projected < 70) or (previous is not None and grade - previous <= -8 and grade < 80):
        return 'intensive'
    if grade < NEAR_PASSING or (projected is not None and projected < PASSING):
        return 'targeted'
    if grade >= 90:
        return 'enrichment'
    return 'core'


TIER_INFO = {
    'intensive': {'name': 'Intensive support', 'hint': 'One-on-one or very small group remediation, checked every week.'},
    'targeted': {'name': 'Targeted support', 'hint': 'Small-group remediation or early check-ins before the next assessment.'},
    'enrichment': {'name': 'Ready for enrichment', 'hint': 'Harder tasks or peer-tutor roles.'},
    'core': {'name': 'On track', 'hint': 'Regular class instruction.'},
}

def components():
    """(key, how a sentence names it) for the three grade components of the school's DepEd order."""
    names = {key: name.lower() for key, name, _ in policy.components()}
    return (('ww', names['ww']), ('pt', names['pt']), ('qa', 'the ' + names['qa']))


def component_tip(key):
    """What lifts one grade component."""
    if key == 'qa':
        if policy.current()['key'] == policy.DO15_2026:
            return 'practice for the summative tests and the term examination, and a review of the least-mastered competencies before them'
        return 'practice in the quarterly assessment format and a review of the least-mastered competencies before the exam'
    return {'ww': 'short quizzes and seatwork with quick feedback, and a retake of missed items',
            'pt': 'performance tasks broken into steps, with the rubric shared at the start and feedback on a draft'}[key]


def plan_step(lv):
    """What to do for one level, and how soon: remediation below 75, then one step up from each passing level."""
    order = policy.levels()                                            # highest first
    passing = [x for x in order if x['passing']]
    failing = [x for x in order if not x['passing']]
    if not lv['passing']:
        if lv['key'] == failing[-1]['key']:
            return policy.current()['remediation_lead'] + ': small-group or one-on-one sessions every week', 'This week'
        return 'Remediation in small groups twice a week, aimed at the passing mark of 75', 'This week'
    if lv['key'] == passing[-1]['key']:
        return 'Targeted practice in small groups twice a week', 'Within 2 weeks'
    if lv['key'] == passing[0]['key']:
        return f'Extension work for these learners, and roles as peer tutors to classmates at {passing[-1]["name"]}', 'This quarter'
    if lv['key'] == passing[1]['key']:
        return 'Enrichment: harder problems, projects and independent work', 'This quarter'
    return 'Tasks that apply the lesson to new situations, with feedback on each attempt', 'This quarter'


def level_plan(learners, *, teacher, teacher_name, adviser_name, next_period_name):
    """One step up for every level present in a class, the lowest first.

    Each step names its learners, how many points they need, the grade component that holds the group back most
    (against the class's own average for it), what to do, who does it, by when, and how success is measured. With
    the grade forecaster, it also counts who is forecast to reach the next level and who may slip below 75.
    """
    class_parts = {}
    for key, _ in components():
        values = [l[key] for l in learners if l.get(key) is not None]
        if values:
            class_parts[key] = mean(values)
    plan = []
    for lv in reversed(policy.levels()):
        group = [l for l in learners if l['level']['key'] == lv['key']]
        if not group:
            continue
        target = _next_level(lv)
        parts = []
        for key, label in components():
            values = [l[key] for l in group if l.get(key) is not None]
            if values and key in class_parts:
                parts.append({'key': key, 'label': label, 'average': round(mean(values), 1), 'class': round(class_parts[key], 1),
                              'gap': mean(values) - class_parts[key]})
        weak = None
        if parts:
            # the component furthest below the class average; when the group is the class itself, its lowest component
            weak = min(parts, key=lambda p: p['gap']) if max(abs(p['gap']) for p in parts) >= 1 else min(parts, key=lambda p: p['average'])
        how, when = plan_step(lv)
        if weak and target:
            how += f', focused on {weak["label"]}: {component_tip(weak["key"])}'
        gaps = [target['min'] - l['grade'] for l in group] if target else []
        half = math.ceil(len(group) / 2)
        both = adviser_name and adviser_name != teacher_name
        plan.append({
            'level': lv, 'target': target, 'count': len(group), 'how': how + '.', 'when': when, 'weak': weak,
            'who': f'{teacher} with the adviser{", " + adviser_name if both else ""}' if not lv['passing'] else teacher,
            # below 75: the lowest first (most urgent); every other level: the nearest to the next level first
            'learners': sorted(group, key=lambda l: l['grade'] if not lv['passing'] else -l['grade']),
            'gap': (round(max(min(gaps), 0.1), 1), round(max(gaps), 1)) if gaps else None,
            'measure': (f'{half} of the {len(group)} at {target["min"]} or above by {next_period_name or "the end of the quarter"}'
                        if target else 'They stay at 90 or above'),
            'likely_up': sum(1 for l in group if target and l.get('projected') is not None and l['projected'] >= target['min']),
            'may_slip': sum(1 for l in group if lv['passing'] and (l.get('chance') or 0) >= 0.5),
        })
    return plan


def learner_reason(learner):
    """A short, specific reason for a learner's tier."""
    g, p, prev = learner['grade'], learner.get('projected'), learner.get('previous')
    parts = [f'{g:.1f} now']
    if prev is not None and abs(g - prev) >= 0.5:
        parts.append(f'{"up" if g > prev else "down"} {abs(g - prev):.1f} since last quarter')
    if p is not None:
        parts.append(f'projected {p:.1f}')
    return ', '.join(parts)


def build_section_brief(*, section_name, grade_label, subject_name, period_name, next_period_name,
                        prev_period_name, teacher_name, adviser_name, learners, enrolled, validated,
                        grade_level_avg, rank, rank_of, prev_avg, forecast, quarters_with_data, method=''):
    """The full brief for one class in one period.

    learners: [{'name', 'grade', 'previous', 'projected', 'chance' (of ending below 75), 'ww', 'pt', 'qa'
    (component percents)}] for learners with a grade; any of the last five may be None.
    forecast: {'value', 'low', 'high'} for the next period, or None. method: where the forecast comes from.
    """
    n = len(learners)
    if not n:
        return None
    grades = [l['grade'] for l in learners]
    avg = mean(grades)
    level = level_of(avg)
    below = [l for l in learners if l['grade'] < PASSING]
    near = [l for l in learners if PASSING <= l['grade'] < NEAR_PASSING]
    advanced = [l for l in learners if l['grade'] >= 90]
    slipping = [l for l in learners if l['grade'] >= PASSING and l.get('projected') is not None and l['projected'] < PASSING]
    projected_below = [l for l in learners if l.get('projected') is not None and l['projected'] < PASSING]
    spread = pstdev(grades) if n > 1 else 0.0
    delta = avg - prev_avg if prev_avg is not None else None
    diff = avg - grade_level_avg if grade_level_avg is not None and rank_of and rank_of >= 2 else None
    teacher = teacher_name or 'the subject teacher'
    rules = policy.current()
    top = policy.levels()[0]
    with_prev = [l for l in learners if l.get('previous') is not None]
    rose = sum(1 for l in with_prev if LEVEL_RANK[level_of(l['grade'])['key']] > LEVEL_RANK[level_of(l['previous'])['key']])
    dropped = sum(1 for l in with_prev if LEVEL_RANK[level_of(l['grade'])['key']] < LEVEL_RANK[level_of(l['previous'])['key']])

    for l in learners:
        l['tier'] = support_tier(l['grade'], l.get('projected'), l.get('previous'))
        l['level'] = level_of(l['grade'])
        l['reason'] = learner_reason(l)
    tiers = {key: sorted([l for l in learners if l['tier'] == key], key=lambda l: l['grade'] if key != 'enrichment' else -l['grade'])
             for key in ('intensive', 'targeted', 'enrichment')}
    needing = len(tiers['intensive']) + len(tiers['targeted'])
    share_needing = needing / n

    # ---- findings: every candidate gets a weight; the three heaviest are shown ----
    findings = []

    def finding(title, detail, tone, weight):
        findings.append({'title': title, 'detail': detail, 'tone': tone, 'weight': weight})

    if below:
        lowest = min(below, key=lambda l: l['grade'])
        finding(f'{_s(len(below))} below 75',
                f'{len(below)} of {n} learners ({_share(len(below), n)}) are below 75 in {period_name}. '
                f'The lowest grade is {lowest["grade"]:.1f}.', 'risk', 90 + 5 * len(below))
    if near:
        finding(f'{_s(len(near))} just above 75',
                f'{len(near)} {_verb(len(near))} between 75 and 77, so one weak assessment could put '
                f'{"them" if len(near) > 1 else "this learner"} below the passing mark.', 'warn', 50 + 5 * len(near))
    if delta is not None and abs(delta) >= 0.5:
        detail = f'The average went from {prev_avg:.1f}% to {avg:.1f}%.'
        if with_prev:
            detail += f' {rose} moved up a level and {dropped} moved down.'
        tone = 'risk' if delta <= -2 else ('warn' if delta < 0 else 'good')
        finding(f'Average {"up" if delta > 0 else "down"} {abs(delta):.1f} points since {prev_period_name}', detail,
                tone, (60 + 8 * abs(delta)) if delta < 0 else (35 + 5 * delta))
    if diff is not None and abs(diff) >= 0.5:
        finding(f'{abs(diff):.1f} points {"above" if diff > 0 else "below"} the {grade_label} average',
                f'The {grade_label} average in {subject_name} is {grade_level_avg:.1f}%. '
                f'{section_name} ranks {rank} of {rank_of} sections.',
                'warn' if diff <= -2 else ('good' if diff >= 2 else 'info'), 40 + 6 * abs(diff))
    if forecast:
        detail = f'Likely between {forecast["low"]:.1f}% and {forecast["high"]:.1f}% if nothing changes.'
        if slipping:
            detail += f' {_s(len(slipping))} who pass now {_verb(len(slipping))} projected to fall below 75.'
        tone = 'risk' if slipping or forecast['value'] < PASSING else ('warn' if forecast['value'] < avg - 1 else 'info')
        finding(f'{next_period_name} projected at {forecast["value"]:.1f}%', detail, tone, (70 + 10 * len(slipping)) if slipping else 45)
    if share_needing > 0.2 and n >= 10:
        finding(f'{_share(needing, n)} of learners need extra support',
                'When more than about 1 in 5 learners need extra help, the cause is usually in whole-class '
                '(core) instruction, not only in individual learners.', 'risk', 85)
    if spread >= 7 and n >= 10:
        finding('Wide range of grades',
                f'Grades run from {min(grades):.1f} to {max(grades):.1f}. Tasks at more than one level of '
                'difficulty will reach both ends of the class.', 'info', 38)
    if len(advanced) / n >= 0.25:
        finding(f'{_s(len(advanced))} at {top["name"]}',
                f'{_share(len(advanced), n)} of the class is at 90 or above, ready for enrichment or peer-tutor roles.', 'good', 36)
    if enrolled and n < enrolled:
        finding('Grades still coming in', f'{n} of {enrolled} enrolled learners have a {period_name} grade so far.',
                'warn', 80 if n < 0.9 * enrolled else 34)
    elif validated < n:
        finding('Not all grades validated', f'{validated} of {n} grades are validated by the registrar.', 'info', 32)
    if not below and not near and not slipping:
        finding('Every learner is passing', f'No learner is below 75 or within 2 points of it in {period_name}.', 'good', 30)
    findings.sort(key=lambda f: -f['weight'])
    findings = findings[:3]

    # ---- actions for the School Head, most urgent first ----
    actions = []
    if below:
        actions.append({
            'title': f'Start remediation for the {_s(len(below))} below 75',
            'why': rules['remediation'],
            'who': f'{teacher} (subject teacher)', 'when': 'This week',
            'measure': f'At least {math.ceil(len(below) / 2)} of them at 75 or above by {next_period_name or "the end of the quarter"}',
        })
    if delta is not None and delta <= -2:
        actions.append({
            'title': f'Talk through the {abs(delta):.1f}-point drop with {teacher}',
            'why': 'A short data conference finds the topic or assessment that pulled the average down before it becomes a learning gap.',
            'who': 'School Head with the subject teacher', 'when': 'Within 5 school days',
            'measure': f'Average back to {prev_avg:.1f}% or higher in {next_period_name or "the next quarter"}',
        })
    if share_needing > 0.2 and n >= 10:
        actions.append({
            'title': f'Observe one {subject_name} lesson and agree on a re-teaching focus',
            'why': f'{_share(needing, n)} of learners need extra support, more than individual help alone can cover.',
            'who': 'School Head or the department head', 'when': 'Within 2 weeks',
            'measure': 'Fewer than 1 in 5 learners needing extra support next quarter',
        })
    watch = slipping + [l for l in near if l not in slipping]
    if len(watch) >= 2 or slipping:
        actions.append({
            'title': f'Check in early with the {_s(len(watch))} close to 75',
            'why': 'They pass now but could fall below 75 after the next assessment.',
            'who': f'{teacher}' + (f' with the adviser, {adviser_name}' if adviser_name and adviser_name != teacher_name else ''),
            'when': f'Before the {next_period_name or "next"} assessment' if next_period_name else 'Before the quarterly assessment',
            'measure': 'None of them falls below 75',
        })
    if validated < n:
        actions.append({
            'title': f'Ask the registrar to validate the {period_name} grades',
            'why': f'{n - validated} of {n} grades are not validated yet, and decisions should rest on validated grades.',
            'who': 'Registrar', 'when': 'Before the grade deadline', 'measure': 'All grades validated',
        })
    if len(advanced) >= 3 or len(advanced) / n >= 0.2:
        actions.append({
            'title': f'Give the {_s(len(advanced))} at {top["name"]} enrichment or peer-tutor roles',
            'why': 'It keeps strong learners challenged and gives classmates who struggle extra help.',
            'who': teacher, 'when': 'This quarter', 'measure': 'They stay at 90 or above',
        })
    if level['key'] in ('advanced', 'proficient') and not below and (delta is None or delta >= 0):
        actions.append({
            'title': f'Share what works in {section_name} at the next LAC session',
            'why': 'Learning Action Cells (DepEd Order No. 35, s. 2016) are the school\'s way of spreading effective practice.',
            'who': teacher, 'when': 'Next LAC session', 'measure': 'Practice written up and tried in one more section',
        })
    actions = actions[:3]

    # ---- level-up plan: one step up for every level present ----
    plan = level_plan(learners, teacher=teacher, teacher_name=teacher_name, adviser_name=adviser_name, next_period_name=next_period_name)
    near_next = [l for l in learners if l['level']['key'] in ('developing', 'approaching', 'proficient')
                 and _next_level(l['level'])['min'] - l['grade'] <= 2]

    # ---- headline and summary: where the class stands, how its learners spread over the levels, where it heads ----
    nxt = next_period_name or 'the next quarter'
    if below and slipping:
        headline = f'{_s(len(below))} {_verb(len(below))} below 75 and {len(slipping)} more may slip in {nxt}. Remediation should start this week.'
    elif below:
        headline = f'{_s(len(below))} {_verb(len(below))} below 75. Remediation should start this week' + (
            f', and {len(near_next)} more {_verb(len(near_next))} within 2 points of the next level.' if near_next else '.')
    elif slipping:
        headline = f'Everyone passes now, but {_s(len(slipping))} may fall below 75 in {nxt}. Check in early.'
    elif delta is not None and delta <= -2:
        headline = f'The average fell {abs(delta):.1f} points since {prev_period_name}. A short data conference is worth it.'
    elif near_next:
        headline = f'{section_name} is at the {level["name"]} level in {subject_name}, and {_s(len(near_next))} {_verb(len(near_next))} within 2 points of the next level.'
    elif level['key'] in ('advanced', 'proficient'):
        headline = f'{section_name} is {level["name"]} in {subject_name}. Keep it going and stretch the top learners.'
    else:
        headline = f'{section_name} is at the {level["name"]} level in {subject_name} with no learner below 75.'

    s1 = f'{section_name} is at the {level["name"]} level in {subject_name} with {_a(avg)} {_pct(avg)} average'
    if delta is not None and abs(delta) >= 0.1:
        s1 += f', {abs(delta):.1f} points {"higher" if delta > 0 else "lower"} than in {prev_period_name}'
    if diff is not None and abs(diff) >= 0.1:
        s1 += f', and {abs(diff):.1f} points {"above" if diff > 0 else "below"} the {grade_label} average of {_pct(grade_level_avg)}'
    summary = [s1 + '.']
    present = [(lv, sum(1 for l in learners if l['level']['key'] == lv['key'])) for lv in policy.levels()]
    present = [(lv, count) for lv, count in present if count]
    parts = [f'{count} at {lv["name"]}' for lv, count in present]
    summary.append('By level: ' + (', '.join(parts[:-1]) + ' and ' + parts[-1] if len(parts) > 1 else parts[0]) + '.')
    if forecast:
        summary.append(f'If nothing changes, {next_period_name} is forecast at {_pct(forecast["value"])}'
                       + (f', with {_s(len(projected_below))} below 75.' if projected_below else '.'))
    summary = ' '.join(summary)
    keep_words = [level['name'], section_name, subject_name] + [lv['name'] for lv, _ in present]

    # ---- targets for the next period ----
    targets = []
    if next_period_name:
        target_avg = max(avg, grade_level_avg or 0)
        targets.append(f'Average at {math.ceil(target_avg)}% or higher in {next_period_name}')
        if below:
            keep = len(below) - math.ceil(len(below) / 2)
            targets.append(f'No more than {_s(keep)} below 75' if keep else 'Every learner at 75 or above')
        else:
            targets.append('Every learner stays at 75 or above')
        if slipping:
            targets.append(f'None of the {_s(len(slipping))} projected to slip falls below 75')

    # ---- how sure we are ----
    graded_share = n / enrolled if enrolled else 1
    validated_share = validated / n
    if quarters_with_data >= 3 and graded_share >= 0.9 and validated_share >= 0.9:
        confidence = {'level': 'High', 'tone': 'good'}
    elif quarters_with_data >= 2 and graded_share >= 0.7:
        confidence = {'level': 'Medium', 'tone': 'info'}
    else:
        confidence = {'level': 'Low', 'tone': 'warn'}
    confidence['reason'] = (f'{_s(quarters_with_data, "quarter")} of grades this school year, {n} of {enrolled or n} '
                            f'learners graded, {validated} validated.')

    notes = [
        f'Based on {n} of {enrolled or n} enrolled learners with a {period_name} grade; {validated} of them validated by the registrar.',
        f'Levels follow {rules["levels_order"]}. {rules["remediation"]}',
    ]
    if forecast:
        notes.append((method + ' ' if method else f'Projections continue this school year\'s trend ({_s(quarters_with_data, "quarter")}) '
                      'with damping, and the range reflects how much section averages in this school usually move between quarters. ')
                     + 'Forecasts show where things are heading if nothing changes, not what any learner will get.')
    else:
        notes.append('No projection: this is the last grading period of the school year, or later periods already have grades.')
    ww, pt, qa = (label for _, label in components())
    notes.append(f'The level-up plan compares each group\'s scores in {ww}, {pt} and {qa} with the class average for each, '
                 'and names the one furthest behind.')

    return {
        'headline': headline, 'summary': summary,
        'level': level, 'average': round(avg, 1), 'delta': round(delta, 1) + 0.0 if delta is not None else None,
        'passing_rate': round(100 * (n - len(below)) / n, 1), 'below': len(below), 'near': len(near),
        'advanced': len(advanced), 'slipping': len(slipping), 'projected_below': len(projected_below),
        'graded': n, 'enrolled': enrolled, 'validated': validated,
        'findings': findings, 'actions': actions, 'targets': targets, 'notes': notes,
        'confidence': confidence, 'forecast': forecast,
        'tiers': [{'key': key, 'name': TIER_INFO[key]['name'], 'hint': TIER_INFO[key]['hint'], 'learners': tiers[key]}
                  for key in ('intensive', 'targeted', 'enrichment') if tiers[key]],
        'share_needing': round(100 * share_needing), 'plan': plan, 'near_next': len(near_next), 'keep': keep_words,
    }


# --------------------------------------------------------------------------------------------
# Dashboard insight
# --------------------------------------------------------------------------------------------

def dashboard_insight(*, scope_name, period_name, prev_period_name, average, delta, below, items, item_word, upcoming=None,
                      over_periods=False):
    """Up to four short sentences for the top of the dashboard: where the selection stands, the quickest step up a
    level, the forecast, and who needs remediation. over_periods: the average spans several grading periods.
    Returns (text, the items it names)."""
    level = level_of(average)
    s1 = f'{scope_name} is at the {level["name"]} level with {_a(average)} {_pct(average)} average {"over" if over_periods else "in"} {period_name}'
    if delta is not None and abs(delta) >= 0.1:
        s1 += f', {abs(delta):.1f} points {"higher" if delta > 0 else "lower"} than in {prev_period_name}'
    out, named = [s1 + '.'], []
    # the quickest step up: the items nearest the next level (within 2 points)
    steps = sorted(((_next_level(i['level'])['min'] - i['average'], i) for i in items
                    if i['level']['key'] in NEXT_LEVEL), key=lambda s: s[0])
    close = [(gap, i) for gap, i in steps if gap <= 2][:2]
    if close and len(items) > 1:
        out.append(f'Closest to the next level: ' + ' and '.join(
            f'{i["name"]} ({_pct(i["average"])}, {gap:.1f} points from {_next_level(i["level"])["name"]})'
            for gap, i in close) + '.')
        named += [i for _, i in close]
    lowest = min(items, key=lambda i: i['average']) if len(items) > 1 else None
    if lowest and lowest['level']['key'] in ('beginning', 'developing') and lowest not in named:
        out.append(f'Needs the most support: {lowest["name"]} ({_pct(lowest["average"])}).')
        named.append(lowest)
    if upcoming:
        out.append(f'{upcoming["name"]} is forecast at {_pct(upcoming["value"])}.')
    out.append(f'{_s(below)} {_verb(below)} below 75 and need remediation.' if below else 'No learner is below 75.')
    return ' '.join(out), named


def performance_insight(*, scope_name, period_name, prev_period_name, average, delta, learners, areas, remedial, retention, honors,
                        honors_phrase=('qualifies for academic honors this quarter', 'qualify for academic honors this quarter')):
    """Plain sentences for the top of School Performance: overall level, weakest learning areas, promotion outlook, honors."""
    level = level_of(average)
    s1 = f'{scope_name} is at the {level["name"]} level with {_a(average)} {_pct(average)} average across {_s(learners)} in {period_name}'
    if delta is not None and abs(delta) >= 0.1:
        s1 += f', {abs(delta):.1f} points {"higher" if delta > 0 else "lower"} than in {prev_period_name}'
    out = [s1 + '.']
    weakest = sorted(areas, key=lambda a: a['average'])[:2]
    if len(areas) > 2 and weakest:
        out.append('Lowest learning areas: ' + ' and '.join(f'{a["name"]} ({_pct(a["average"])})' for a in weakest) + '.')
    if retention:
        out.append(f'{_s(retention)} {_verb(retention)} below 75 in three or more learning areas and at risk of retention.')
    if remedial:
        out.append(f'{_s(remedial)} {"needs" if remedial == 1 else "need"} remedial classes.')
    if not retention and not remedial:
        out.append('No learner is below 75 in any learning area.')
    if honors:
        out.append(f'{_s(honors)} {honors_phrase[0] if honors == 1 else honors_phrase[1]}.')
    return ' '.join(out)


# --------------------------------------------------------------------------------------------
# Poro AI wording: the source a reworded status is checked against (the writing is in heads/poro.py)
# --------------------------------------------------------------------------------------------

def narrative_token(text, keep=()):
    """Remember a system-written summary so the browser can ask Poro to reword it by token.

    Only text the server wrote can be reworded, so the endpoint cannot be used as an open AI proxy.
    keep: names and level words the wording must carry unchanged; a small model once turned "Approaching
    Proficiency" into "on track to reach Proficiency", which keeps every number and changes the meaning.
    """
    keep = sorted({k for k in keep if k}, key=len, reverse=True)
    token = hashlib.sha1('|'.join([text] + keep).encode('utf-8')).hexdigest()[:24]
    caches['default'].set(f'poro:src:{token}', {'text': text, 'keep': keep}, 7 * 24 * 3600)
    return token


_PERIODS = re.compile(r'\b(?:quarter|trimester|semester|grade)\s*\d{1,2}\b|\b[qts][1-4]\b|\b(?:first|second|third|fourth)\s+(?:quarter|trimester|semester)\b', re.I)
_NUMBER = re.compile(r'\d+(?:\.\d+)?')


_WORDS = {w: i for i, w in enumerate('zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen '
                                     'fifteen sixteen seventeen eighteen nineteen'.split())}
_TENS = {w: 10 * i for i, w in enumerate('twenty thirty forty fifty sixty seventy eighty ninety'.split(), start=2)}
_NUMBER_WORD = re.compile(r'\b(?:(' + '|'.join(_TENS) + r')(?:[- ](one|two|three|four|five|six|seven|eight|nine))?|('
                          + '|'.join(_WORDS) + r'))\b', re.I)


def _number_word(match):
    tens, unit, word = match.groups()
    if tens:
        return str(_TENS[tens.lower()] + (_WORDS[unit.lower()] if unit else 0))
    return str(_WORDS[word.lower()])


def _figures(text):
    """Numbers that carry meaning, with number words read as digits ("two" is 2, "twenty-nine" 29). Period names,
    grade levels and the passing mark (75) are left out because rewording may name them differently."""
    text = _NUMBER_WORD.sub(_number_word, _PERIODS.sub(' ', text))
    return [n for n in _NUMBER.findall(text) if n != '75']


# words that would change the meaning if the original did not use them
_DRIFT = ('maintain', 'remain', 'unchanged', 'stable', 'steady', 'majority', 'most of', 'half of', 'guarantee',
          'will definitely')


def check_rewrite(source, rewrite, keep=()):
    """True when the rewrite keeps every figure of the source in the same order, keeps the given names and level
    words, names no proficiency level the source did not, and adds no new claim."""
    if not rewrite or not 0.6 * len(source) <= len(rewrite) <= 1.6 * len(source):
        return False
    if _figures(rewrite) != _figures(source):
        return False
    low_src, low_new = source.lower(), rewrite.lower()
    if any(word in low_new and word not in low_src for word in _DRIFT):
        return False
    if any(k.lower() not in low_new for k in keep):
        return False
    if any(lv['name'].lower() in low_new and lv['name'].lower() not in low_src
           for rules in policy.POLICIES.values() for lv in rules['levels']):
        return False
    return not re.search(r'https?://|[*#`]|\bI\b|\bas an ai\b', rewrite, re.I)
