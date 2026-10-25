"""The trained grade forecaster in plain words, for the Admin Portal's Grade Forecaster page."""
from collections import defaultdict
from datetime import datetime

from . import forecast as ml
from . import training

# what each input means to a reader; the learning-area flags are summed into one line
LABELS = {
    'grade': 'The latest grade in the subject',
    'prev1': 'The grade one period earlier',
    'prev2': 'The grade two periods earlier',
    'hist_mean': 'The average in the subject so far',
    'hist_slope': 'The trend in the subject so far',
    'n_hist': 'How many periods are graded so far',
    'written_work': 'The written work score',
    'performance_task': 'The performance task score',
    'quarterly_assessment': 'The quarterly assessment score',
    'learner_avg': "The learner's average across subjects",
    'learner_gap': "How far the subject sits from the learner's usual level",
    'class_avg': 'The class average',
    'class_change': "The class average's latest change",
    'class_gap': 'How far the learner sits from the class average',
    'last_year': "Last year's final grade in the same learning area",
    'attendance': 'Attendance',
    'grade_level': 'The grade level',
    'senior': 'Junior or Senior High',
    'period': 'Which grading period',
    'horizon': 'How many periods ahead',
    'periods_in_year': 'How many periods the school year has',
}


def _when(text):
    try:
        return datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None


def summary():
    """Facts about the saved model, or None when none is trained."""
    _, meta = ml.load()
    if not meta:
        return None
    lean = defaultdict(float)
    for name, share in meta.get('importance', []):
        lean['The learning area' if name.startswith('area_') else LABELS.get(name, name.replace('_', ' '))] += share
    total = sum(lean.values()) or 1
    evaluations = []
    for e in meta['evaluation']:
        rule_name, rule = min(e['rules'].items(), key=lambda kv: kv[1]['mae'])
        evaluations.append({'split': e['split'], 'n': e['model']['n'], 'mae': e['model']['mae'], 'within_2': e['model']['within_2'],
                            'within_5': e['model']['within_5'], 'precision': e['model']['below_75_precision'],
                            'recall': e['model']['below_75_recall'], 'rule': rule_name, 'rule_mae': rule['mae'],
                            'rule_precision': rule['below_75_precision']})
    return {
        'version': meta['version'], 'trained_at': _when(meta.get('trained_at')), 'algorithm': meta.get('algorithm', 'XGBoost'),
        'samples': meta['samples'], 'samples_text': f'{meta["samples"]:,}', 'learners': meta.get('learners'), 'series': meta.get('series'),
        'school_years': meta.get('school_years'), 'seconds': meta.get('seconds'),
        'evaluations': evaluations, 'latest': evaluations[-1] if evaluations else None,
        'class_range': ml.interval('class', 1, meta), 'learner_range': ml.interval('learner', 1, meta),
        'lean': [{'name': name, 'share': round(100 * share / total)} for name, share in sorted(lean.items(), key=lambda kv: -kv[1])[:6]],
    }


def run_status():
    """The latest background run, with times parsed for templates."""
    data = training.status()
    data['started'] = _when(data.get('started_at'))
    data['finished'] = _when(data.get('finished_at'))
    return data
