"""Forecast charts for the School Head pages: averages by grading period, and what comes next.

A chart is a set of series over one school year's grading periods. A series is a group of
learner-subjects (a learning area, a grade level, a section, one class); its value for a period is
the average of its members' quarterly grades. Its forecast is the average of the members' forecasts
from the grade forecaster (ml_engine.forecast), with a 90% likely range taken from how far averages
at that level were off on held-out periods; each past period also carries the forecast the model
made one period before, so readers can see how close it came. Without a trained model, the damped
trend of heads.insights projects each series instead, so the pages always show a projection.

The page draws the chart (static/heads/js/forecast-chart.js) from the spec built here.
"""
from statistics import mean

from core.periods import GRADE, HAS_GRADE
from enrollment.models import Enrollment
from grades.models import GradeComponent
from ml_engine import forecast as ml

from core import grading_policy as policy

from . import insights
from .insights import PASSING

# categorical slots in a fixed order, checked for color-vision deficiency on the white card surface;
# an entity keeps its slot whatever else is shown, and the overall line of a chart is drawn in ink
PALETTE = ('#2a78d6', '#eb6834', '#1baf7a', '#eda100', '#e87ba4', '#008300', '#6250d6', '#e34948')
INK = '#1a1a2e'
ACTIVE = ('Enrolled', 'Transferred_In')


def year_table(school, sy):
    """(learner-subject table, model metadata) for one school year, keyed by (enrollment_id, subject_id).

    Rows hold 'section', 'subject', 'actual' {period: grade}, 'future' and 'back' {period: forecast}.
    Only learners still enrolled count. Without a trained model the rows have grades only and the
    metadata is None.
    """
    if sy is None:
        return {}, None
    active = set(Enrollment.objects.filter(school_year=sy, status__in=ACTIVE, section__school=school).values_list('id', flat=True))
    result = ml.forecast_school_year(school.id, sy.id)
    if result:
        return {k: v for k, v in result['series'].items() if k[0] in active}, result['meta']
    table = {}
    for e, s, section, p, g in GradeComponent.objects.filter(
            HAS_GRADE, quarter__school_year=sy, enrollment__in=active).values_list(
            'enrollment_id', 'subject_id', 'enrollment__section_id', 'quarter__quarter_number', GRADE):
        row = table.setdefault((e, s), {'section': section, 'subject': s, 'actual': {}, 'future': {}, 'back': {}})
        row['actual'][p] = float(g)
    return table, None


def series_values(table, keys, periods, level, meta, step_sd):
    """(actual, future, back, last) for a group of learner-subjects, or None when it has no grades.

    actual: {period: (average, learners)}; future: {period: (forecast, low, high)} for the periods after
    the group's latest grades; back: {period: what the model forecast one period earlier}.
    """
    keys = [k for k in keys if k in table]
    actual = {}
    for p in periods:
        values = [table[k]['actual'][p] for k in keys if p in table[k]['actual']]
        if values:
            actual[p] = (mean(values), len(values))
    if not actual:
        return None
    last = max(actual)
    future, back = {}, {}
    if meta:
        for p in periods:
            if p > last:
                values = [table[k]['future'][p] for k in keys if p in table[k]['future']]
                if values:
                    value, half = mean(values), ml.interval(level, p - last, meta) or 0.0
                    future[p] = (value, value - half, value + half)
        for p, (_, n) in actual.items():
            values = [table[k]['back'][p] for k in keys if p in table[k]['back']]
            if values and len(values) >= max(3, n // 2):
                back[p] = mean(values)
    else:
        for f in insights.project_series([(p, a) for p, (a, _) in actual.items()], periods[-1], step_sd):
            future[f['period']] = (f['value'], f['low'], f['high'])
    return actual, future, back, last


def method_note(meta):
    """One line on where the forecast comes from and how far off it has been."""
    if not meta:
        return {'kind': 'trend', 'text': 'Forecast continues this school year\'s trend, damped so a short run of periods is not '
                                         'stretched too far. Train the grade model (python manage.py train_ml_models) for '
                                         'forecasts learned from the school\'s records.'}
    latest = meta['evaluation'][-1]
    class_range = ml.interval('class', 1, meta)
    return {'kind': 'model', 'version': meta['version'],
            'text': f'Forecast by the ARMS grade model (XGBoost), trained on {meta["samples"]:,} grade records. On the latest '
                    f'quarter it had not seen, a learner\'s grade was off by {latest["model"]["mae"]:.1f} points on average '
                    f'and class averages stayed within {class_range:.1f} points 9 times out of 10. Diamonds are its one-step '
                    'forecasts for periods that already have grades; it learned from those grades, so they look closer '
                    'than a forecast of a new period will be.'}


def chart(*, table, meta, periods, items, reference=None, level='group', step_sd=2.5, selected=None, period_name=str):
    """The spec of one forecast chart.

    periods: the school year's grading periods (Quarter rows); items: [{'key', 'name', 'keys', 'url'}] in their
    fixed order, which sets each one's color; reference: the overall line, same shape, or None.
    """
    numbers = [q.quarter_number for q in periods]
    entries = []
    for i, item in enumerate(items):
        values = series_values(table, item['keys'], numbers, item.get('level', level), meta, step_sd)
        if values:
            entries.append((i, item, values))
    if len(entries) > len(PALETTE):
        # more than eight in one chart (every discipline): a ninth repeats a slot, drawn with square points, so its
        # line differs by color and shape; the label at its end names it
        colors = [PALETTE[i % len(PALETTE)] for i, _, _ in entries]
    else:
        # an entity keeps its own slot; one past the eighth borrows a slot nobody in this chart uses
        free = [k for k in range(len(PALETTE)) if k not in {i for i, _, _ in entries}]
        colors = [PALETTE[i] if i < len(PALETTE) else PALETTE[free.pop(0)] for i, _, _ in entries]
    seen = set()
    series = []
    for (i, item, values), color in zip(entries, colors):
        series.append(dict(_series(item, values, color), marker='square' if color in seen else 'circle'))
        seen.add(color)
    if reference:
        values = series_values(table, reference['keys'], numbers, level if not items else 'group', meta, step_sd)
        if values:
            series.insert(0, dict(_series(reference, values, INK), reference=True))
    return {
        'periods': [{'p': q.quarter_number, 'label': q.quarter_label, 'name': period_name(q)} for q in periods],
        'series': series, 'selected': selected, 'threshold': PASSING,
        'levels': [{'key': lv['key'], 'name': lv['name'], 'short': lv['short'], 'letter': lv['letter'], 'min': lv['min']}
                   for lv in policy.levels()],
        'method': method_note(meta),
    }


def _series(item, values, color):
    actual, future, back, last = values
    return {
        'key': str(item['key']), 'name': item['name'], 'color': color, 'reference': False, 'url': item.get('url', ''),
        'learners': actual[last][1], 'last': last,
        'actual': {p: round(v, 1) for p, (v, _) in actual.items()},
        'future': {p: [round(v, 1), round(lo, 1), round(hi, 1)] for p, (v, lo, hi) in future.items()},
        'back': {p: round(v, 1) for p, v in back.items()},
    }
