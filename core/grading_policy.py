"""The DepEd rules a school follows for grade descriptors and academic awards.

Private schools may keep the rules of DepEd Order No. 8, s. 2015 or adopt DepEd Order No. 015, s. 2026,
which replaced it in public schools from SY 2026-2027 (private schools are encouraged, not required, to
adopt it). Each school records its choice in School.grading_policy, and the School Head can change it.

- DO8_2015: the descriptors of DepEd Order No. 8, s. 2015 (Outstanding 90-100 down to Did Not Meet
  Expectations below 75) and the honors of DepEd Order No. 36, s. 2016: With Honors 90-94, With High
  Honors 95-97 and With Highest Honors 98-100 for a learner who passed every learning area.
- DO15_2026: the descriptors of DepEd Order No. 015, s. 2026 (Advancing 90-100, Benchmarking 80-89,
  Connecting 75-79, Developing 65-74, Emerging below 65) and its single Academic Excellence Award: a
  general average of at least 90, no final grade below 80, and no derogatory record in the school year.

Both have five levels. Every level keeps one of five slot keys, 'beginning' (lowest) to 'advanced'
(highest), so colors, level-up plans and Excel styles work the same under either policy; only the names,
letters and cut-offs change. The slot keys are internal and never shown.

The head portal activates a school's policy once per request (heads.views_academic._head_school); the
helpers below read the active one, and DO8_2015 when none is active.
"""
from contextvars import ContextVar

PASSING = 75

DO8_2015 = 'DO8_2015'
DO15_2026 = 'DO15_2026'
CHOICES = [
    (DO8_2015, 'DepEd Order No. 8, s. 2015 with the honors of DepEd Order No. 36, s. 2016'),
    (DO15_2026, 'DepEd Order No. 015, s. 2026'),
]
DEFAULT = DO8_2015


def _level(key, name, short, letter, low, high, passing, order):
    span = f'{low} to {high}' if low else f'below {high + 1}'
    return {'key': key, 'name': name, 'short': short, 'letter': letter, 'min': low, 'range': span, 'passing': passing,
            'remark': 'Passed' if passing else 'Failed',
            'meaning': f'Final grade {span}. Remark: {"Passed" if passing else "Failed"} ({order}).'}


POLICIES = {
    DO8_2015: {
        'key': DO8_2015,
        'name': 'DepEd Order No. 8, s. 2015',
        'short': 'DO 8, s. 2015',
        'summary': 'Descriptors Outstanding to Did Not Meet Expectations; With Honors, With High Honors and With Highest Honors '
                   '(DepEd Order No. 36, s. 2016).',
        'levels_order': 'DepEd Order No. 8, s. 2015',
        'levels': (
            _level('advanced', 'Outstanding', 'Outstanding', 'O', 90, 100, True, 'DepEd Order No. 8, s. 2015'),
            _level('proficient', 'Very Satisfactory', 'Very Satisfactory', 'VS', 85, 89, True, 'DepEd Order No. 8, s. 2015'),
            _level('approaching', 'Satisfactory', 'Satisfactory', 'S', 80, 84, True, 'DepEd Order No. 8, s. 2015'),
            _level('developing', 'Fairly Satisfactory', 'Fairly Satisfactory', 'FS', 75, 79, True, 'DepEd Order No. 8, s. 2015'),
            _level('beginning', 'Did Not Meet Expectations', 'Did Not Meet', 'DNME', 0, 74, False, 'DepEd Order No. 8, s. 2015'),
        ),
        'components': (('ww', 'Written Work', 'WW'), ('pt', 'Performance Tasks', 'PT'), ('qa', 'Quarterly Assessment', 'QA')),
        'remediation': 'A learner below 75 must be given remediation (DepEd Order No. 8, s. 2015).',
        'remediation_lead': 'Remediation, which DepEd Order No. 8, s. 2015 requires',
        'awards': {
            'kind': 'tiers', 'order': 'DepEd Order No. 36, s. 2016', 'floor': PASSING,
            'tiers': ((98, 'highest', 'With Highest Honors'), (95, 'high', 'With High Honors'), (90, 'honors', 'With Honors')),
            'rule': 'A general average of 90 or above with every learning area passed: With Honors 90 to 94, With High Honors '
                    '95 to 97, With Highest Honors 98 to 100 (DepEd Order No. 36, s. 2016).',
            'brief': 'General average of 90 or more, every learning area passed',
            'label': 'With honors',
            'phrase': ('qualifies for academic honors this quarter', 'qualify for academic honors this quarter'),
            'period_rule': 'Honors: a quarterly average of 90 or more with every learning area passed (DepEd Order No. 36, s. 2016).',
        },
    },
    DO15_2026: {
        'key': DO15_2026,
        'name': 'DepEd Order No. 015, s. 2026',
        'short': 'DO 015, s. 2026',
        'summary': 'Descriptors Advancing to Emerging; one Academic Excellence Award.',
        'levels_order': 'DepEd Order No. 015, s. 2026',
        'levels': (
            _level('advanced', 'Advancing', 'Advancing', 'A', 90, 100, True, 'DepEd Order No. 015, s. 2026'),
            _level('proficient', 'Benchmarking', 'Benchmarking', 'B', 80, 89, True, 'DepEd Order No. 015, s. 2026'),
            _level('approaching', 'Connecting', 'Connecting', 'C', 75, 79, True, 'DepEd Order No. 015, s. 2026'),
            _level('developing', 'Developing', 'Developing', 'D', 65, 74, False, 'DepEd Order No. 015, s. 2026'),
            _level('beginning', 'Emerging', 'Emerging', 'E', 0, 64, False, 'DepEd Order No. 015, s. 2026'),
        ),
        'components': (('ww', 'Written/Oral Works', 'WW'), ('pt', 'Product/Performance Tasks', 'PT'), ('qa', 'Examinations', 'EX')),
        'remediation': 'A final grade below 75 has not met the minimum standards (DepEd Order No. 015, s. 2026); the learner '
                       'needs remediation.',
        'remediation_lead': 'Remediation for a grade below the passing mark of 75',
        'awards': {
            'kind': 'single', 'order': 'DepEd Order No. 015, s. 2026', 'floor': 80, 'name': 'Academic Excellence Award',
            'tiers': ((90, 'excellence', 'Academic Excellence Award'),),
            'conduct': 'no derogatory record or disciplinary case in the school year',
            'rule': 'A general average of 90 or above, no final grade below 80 in any learning area, and no derogatory record '
                    'or disciplinary case in the school year (DepEd Order No. 015, s. 2026). Awardees are listed '
                    'alphabetically, not ranked.',
            'brief': 'General average of 90 or more, no final grade below 80',
            'label': 'Academic Excellence',
            'phrase': ('is on track for the Academic Excellence Award', 'are on track for the Academic Excellence Award'),
            'period_rule': 'Academic Excellence, on track: an average of 90 or more with no grade below 80 (DepEd Order No. 015, '
                           's. 2026, which gives the award at the end of the school year).',
        },
    },
}

_active = ContextVar('arms_grading_policy', default=DEFAULT)


def key_of(school):
    value = getattr(school, 'grading_policy', None) or DEFAULT
    return value if value in POLICIES else DEFAULT


def activate(school):
    """Use the school's rules for the rest of this request; returns the policy."""
    _active.set(key_of(school))
    return current()


def current():
    return POLICIES[_active.get()]


def for_school(school):
    return POLICIES[key_of(school)]


def levels():
    """The active policy's five levels, highest first."""
    return current()['levels']


def level_by_key():
    return {lv['key']: lv for lv in levels()}


def level_of(value):
    if value is None:
        return None
    for lv in levels():
        if value >= lv['min']:
            return lv
    return levels()[-1]


def components():
    """(key, name, abbreviation) of the three grade components under the active policy."""
    return current()['components']


def whole(value):
    """A grade as DepEd reports it: rounded to a whole number, halves up."""
    return int(value + 0.5) if value is not None else None


def award_of(general_average, lowest_final, policy=None):
    """(key, name) of the academic award a general average earns under the policy, or None.

    general_average and lowest_final are the learner's general average and lowest final grade, each
    rounded to a whole number first, as DepEd reports them.
    """
    rules = (policy or current())['awards']
    if general_average is None or lowest_final is None or lowest_final < rules['floor']:
        return None
    for cut, key, name in rules['tiers']:
        if general_average >= cut:
            return key, name
    return None


def context(request):
    """Templates read the active policy as {{ grading }}: its name, levels, components, remediation and awards."""
    return {'grading': current()}
