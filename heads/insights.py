"""Analysis behind the School Head's Academic Dashboard and School Performance.

Everything a page states is computed here from the grades, with rules a person can check:

- Levels and remediation follow the DepEd order the school chose (core/grading_policy.py): the
  descriptors of DepEd Order No. 8, s. 2015 (Outstanding to Did Not Meet Expectations) or of DepEd
  Order No. 015, s. 2026 (Advancing to Emerging). Below 75 a learner needs remediation under either.
- Decisions: one for each level that has disciplines (or subjects, or sections) on it. Keep the top level
  there with contests and a LAC session, move each passing level up one, bring a failing level up with
  remediation, and act first on the lowest. Each decision aims at the grade component the item is weakest in.
- Projections: damped trend (Gardner & McKenzie) over this school year's quarters. The likely range
  comes from how much section averages in this school usually move from one quarter to the next.

Poro AI (heads/poro.py) rewords the decisions; its text is shown only when every number, name and level in it
checks out against the computed wording.
"""
import math
import re
from collections import defaultdict
from statistics import pstdev

from django.core.cache import caches
from django.db.models import Avg, Count

from core import grading_policy as policy
from core.caching import data_version
from core.grading_policy import PASSING, level_of  # noqa: F401 (the pages import level_of from here)

PHI_SECTION = 0.8          # damping of a class trend per quarter
Z90 = 1.645                # 90% range

# The five levels come from the school's DepEd order (core/grading_policy.py). Their slot keys, lowest
# 'beginning' to highest 'advanced', are the same under every order, so the steps up are written once.
NEXT_LEVEL = {'beginning': 'developing', 'developing': 'approaching', 'approaching': 'proficient', 'proficient': 'advanced'}


def _next_level(lv):
    return policy.level_by_key().get(NEXT_LEVEL.get(lv['key'], ''))


def _clamp(value, low=50.0, high=100.0):
    return max(low, min(high, value))


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
# The School Head's decisions: one for each level that has items on it
# --------------------------------------------------------------------------------------------

def components():
    """(key, how a sentence names it) for the three grade components of the school's DepEd order."""
    names = {key: name.lower() for key, name, _ in policy.components()}
    return (('ww', names['ww']), ('pt', names['pt']), ('qa', 'the ' + names['qa']))


def component_tip(key):
    """What lifts one grade component."""
    return {'ww': 'short quizzes, seatwork and reading drills with quick feedback',
            'pt': 'tasks broken into steps, with the rubric shared at the start',
            'qa': 'a review of the least-mastered competencies and practice in the test format'}[key]


def weakest(parts, overall):
    """The grade component an item is weakest in: the one furthest below the whole selection's average for it, or its
    lowest when none is a point apart. parts, overall: {'ww', 'pt', 'qa'} average percents, None where missing."""
    keys = [k for k in ('ww', 'pt', 'qa') if parts.get(k) is not None and overall.get(k) is not None]
    if not keys:
        return None
    gaps = {k: parts[k] - overall[k] for k in keys}
    if max(abs(g) for g in gaps.values()) >= 1:
        return min(keys, key=lambda k: gaps[k])
    return min(keys, key=lambda k: parts[k])


# what the strongest learners of a discipline or subject can be put forward for, by a word in its name (the first
# match counts, so "Social Sciences" is found before "science")
CONTESTS = (
    ('humanities', 'debates and essay contests'), ('social', 'debates and essay contests'),
    ('philosoph', 'debates and essay contests'), ('politic', 'debates and essay contests'),
    ('math', 'math challenges and quiz bees'), ('statistic', 'math challenges and quiz bees'),
    ('calculus', 'math challenges and quiz bees'), ('science', 'science fairs and quiz bees'),
    ('biology', 'science fairs and quiz bees'), ('chemistry', 'science fairs and quiz bees'),
    ('physics', 'science fairs and quiz bees'), ('research', 'research congresses'),
    ('english', 'spelling bees and oratorical contests'), ('oral comm', 'oratorical contests and debates'),
    ('reading', 'spelling bees and essay contests'), ('writing', 'essay and creative writing contests'),
    ('literature', 'literary and oratorical contests'), ('media', 'campus journalism contests'),
    ('filipino', 'declamation and sabayang pagbigkas contests'), ('komunikasyon', 'declamation and sabayang pagbigkas contests'),
    ('pagbasa', 'declamation and sabayang pagbigkas contests'), ('araling', 'quiz bees and history contests'),
    ('history', 'quiz bees and history contests'), ('mapeh', 'sports meets and arts festivals'),
    ('physical', 'sports meets'), ('music', 'music festivals'), ('arts', 'arts festivals'),
    ('technolog', 'skills contests'), ('livelihood', 'skills contests'),
    ('edukasyon', 'leadership and service awards'), ('personal', 'leadership and service awards'),
)


def _contests(name):
    lowered = name.lower()
    return next((what for word, what in CONTESTS if word in lowered), 'contests and quiz bees')


def _and(words):
    words = list(words)
    return words[0] if len(words) == 1 else ', '.join(words[:-1]) + ' and ' + words[-1]


def _each(values, fmt):
    """Up to three numbers one by one ("12.6 and 4.7"), more as their range ("1.6 to 6.5")."""
    values = list(values)
    if len(values) <= 3:
        return _and(fmt.format(v) for v in values)
    return f'{fmt.format(min(values))} to {fmt.format(max(values))}'


def _focus(group, who, item_word):
    """The sentence that aims a decision at the grade component its items are weakest in: the one they share, with
    what lifts it, or each one's own. It names the items, because Poro rewords each sentence on its own. Empty when no
    class record has component scores."""
    names = dict(components())
    weak = [(i['name'], i['weak']) for i in group if i.get('weak')]
    keys = [key for key in ('ww', 'pt', 'qa') if any(k == key for _, k in weak)]
    if not keys:
        return ''
    if len(keys) == 1:
        return f'Aim at {names[keys[0]]}, where {who} {"is" if len(group) == 1 else "are"} weakest: {component_tip(keys[0])}.'
    return (f"Aim at each {item_word}'s weakest part: "
            + '; '.join(f'{names[key]} for {_and(n for n, k in weak if k == key)}' for key in keys) + '.')


def school_decisions(items, *, next_period_name, item_word='discipline', topic=''):
    """What the School Head should decide for each level that has items on it, the lowest level first (act there first).

    items: [{'name', 'average', 'level', 'weak' (the grade component key it is weakest in, or None), 'below' (the share
    of its grades below 75, 0 to 100)}]: the disciplines, the subjects of one discipline, or the sections of one subject
    (item_word says which; topic is then the subject, for its contests). Each decision names the goal (stay at the top,
    one level up, or the passing mark of 75) and how far it is, the step that fits the level, and the grade component
    to aim at. Returns [{'level', 'items', 'title' (the goal and the step in a few words), 'text', 'urgent' (below 75)}].
    """
    by = defaultdict(list)
    for item in items:
        by[item['level']['key']].append(item)
    when = f'by the end of {next_period_name}' if next_period_name else 'by the next grading period'
    order = policy.levels()                                         # highest first
    top, lowest_passing = order[0], [lv for lv in order if lv['passing']][-1]
    out = []
    for lv in reversed(order):                                      # lowest first
        group = sorted(by.get(lv['key'], []), key=lambda i: i['average'])
        if not group:
            continue
        one = len(group) == 1
        # five or more are named in the card above the text, so the text counts them
        who = _and(i['name'] for i in group) if len(group) <= 4 else f'these {len(group)} {item_word}s'
        its, them = 'its' if one else 'their', 'it' if one else 'them'
        teachers = 'teacher' if item_word == 'section' and one else 'teachers'
        target = _next_level(lv)
        away = lambda goal: '(' + _each((max(goal - i['average'], 0.1) for i in group), '{:.1f}') + ' points away)'
        if lv['key'] == top['key']:                                 # the top level: keep it there
            if topic or one:
                contests = _contests(topic or group[0]['name'])
            elif len(group) <= 4:
                contests = 'contests: ' + '; '.join(f'{_contests(i["name"])} for {i["name"]}' for i in group)
            else:
                contests = 'the contests of each: ' + '; '.join(sorted({_contests(i['name']) for i in group}))
            margins = _each((i['average'] - lv['min'] for i in group), '{:.1f}')
            title = f'Stay at {lv["name"]}: contests and a LAC session'
            text = [f'Keep {who} at {lv["name"]} ({margins} points above {lv["min"]}): put the strongest learners forward '
                    f'for {contests}.', f'Let the {teachers} of {who} share what works at the next LAC session.']
        elif not lv['passing']:                                     # below 75: remediation, the lowest level first
            shares = _each((round(i['below']) for i in group), '{}%')
            text = [f'{"Act first" if not out else "Act"} on {who}: {shares} of {its} grades are below 75.']
            if lv['key'] == order[-1]['key']:
                title = f'Up to {target["name"]}: remediation this week'
                text.append(f'Start remediation classes in {who} this week and observe one of {its} classes, to lift {them} '
                            f'to {target["name"]} {away(target["min"])} {when}.')
            else:
                title = 'Up to 75: remediation twice a week'
                text.append(f'Hold remediation classes in {who} twice a week to bring {them} up to the passing mark of 75 '
                            f'{away(PASSING)} {when}.')
        elif lv['key'] == lowest_passing['key']:                    # just passing: one level up before anyone slips
            title = f'Up to {target["name"]}: practice in small groups'
            text = [f'Lift {who} to {target["name"]} {away(target["min"])} with targeted practice in small groups, '
                    'before learners slip below 75.']
        elif target['key'] == top['key']:                           # one below the top: enrichment
            title = f'Up to {target["name"]}: enrichment'
            text = [f'Push {who} up to {target["name"]} {away(target["min"])} with enrichment: harder problems, projects '
                    'and independent work.']
        else:                                                       # in between: one level up
            title = f'Up to {target["name"]}: targeted practice'
            text = [f'Move {who} up to {target["name"]} {away(target["min"])} with targeted practice and a short check '
                    'every two weeks.']
        focus = _focus(group, who, item_word) if lv['key'] != top['key'] else ''
        if focus:
            text.append(focus)
        out.append({'level': lv, 'items': group, 'title': title, 'text': ' '.join(text), 'urgent': not lv['passing']})
    return out


# --------------------------------------------------------------------------------------------
# Poro AI wording (heads/poro.py): the numbers a reworded sentence must keep, with period names and number words read
# --------------------------------------------------------------------------------------------

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
