"""Grade forecasts learned from the school's own records: the model behind every ARMS projection.

For one learner in one subject, the model reads what is known at the end of a grading period and
predicts the quarterly grade 1 to 3 periods later:
  - that period's quarterly grade and its written work, performance task and quarterly assessment scores,
  - the earlier grades of the school year (their level, trend and number),
  - the learner's average across all subjects, the class average and how it moved,
  - last school year's final grade in the same learning area, when the learner was enrolled,
  - attendance in that period, the grade level, the learning area, the period and how far ahead.

It is a gradient-boosted tree regressor (XGBoost) that learns the change from the current grade.
`python manage.py train_ml_models --model forecast` builds one sample for every learner, subject,
starting period and horizon in the records, tunes the model on a time split (it learns from earlier
periods and is scored on the latest ones, the way the pages use it), compares it with the simple
rules it replaces, and saves the model with the error it showed on the held-out periods. That error
sets the likely ranges (90%) and the chance of falling below 75 that the pages show.

Without a trained model, callers fall back to the damped trend in heads/insights.py.
"""
import json
import math
import random
import time
from collections import Counter, defaultdict
from datetime import date, datetime
from pathlib import Path
from statistics import mean

MODEL_DIR = Path(__file__).resolve().parent / 'saved_models'
MODEL_FILE = MODEL_DIR / 'grade_forecaster.pkl'          # git-ignored like every *.pkl; rebuild with the command
META_FILE = MODEL_DIR / 'grade_forecaster.json'
PASSING = 75
LOWEST, HIGHEST = 60.0, 100.0                             # DepEd transmuted grades run from 60 to 100
MAX_HORIZON = 3
NAN = float('nan')

AREAS = ('MATH', 'SCIENCE', 'ENGLISH', 'FILIPINO', 'AP', 'MAPEH', 'TLE', 'ESP', 'OTHER')
_AREA_WORDS = (                                           # checked in order: MAPEH before SCIENCE ("Physical Education")
    ('MAPEH', ('MAPEH', 'MUSIC', 'ARTS', 'PHYSICAL EDUCATION', 'HEALTH')),
    ('TLE', ('TECHNOLOGY AND LIVELIHOOD', 'TLE', 'LIVELIHOOD')),
    ('ESP', ('PAGPAPAKATAO', 'ESP', 'VALUES')),
    ('AP', ('ARALING PANLIPUNAN',)),
    ('MATH', ('MATH', 'CALCULUS', 'STATISTICS')),
    ('SCIENCE', ('SCIENCE', 'BIOLOGY', 'CHEMISTRY', 'PHYSICS')),
    ('ENGLISH', ('ENGLISH',)),
    ('FILIPINO', ('FILIPINO',)),
)
FEATURES = ('grade', 'prev1', 'prev2', 'hist_mean', 'hist_slope', 'n_hist', 'written_work', 'performance_task',
            'quarterly_assessment', 'learner_avg', 'learner_gap', 'class_avg', 'class_change', 'class_gap',
            'last_year', 'attendance', 'grade_level', 'senior', 'period', 'horizon', 'periods_in_year') + \
           tuple(f'area_{a.lower()}' for a in AREAS)

# hyperparameters tried when training (a seeded random sample of this grid)
SEARCH_SPACE = {
    'max_depth': [3, 4, 5, 6], 'learning_rate': [0.03, 0.05, 0.08], 'n_estimators': [250, 450, 700],
    'subsample': [0.8, 1.0], 'colsample_bytree': [0.7, 0.85, 1.0], 'min_child_weight': [1, 4, 10], 'reg_lambda': [1.0, 5.0],
}
SEARCH_TRIALS = 30


def area_of(name):
    """The DepEd learning area of a subject or discipline name ('OTHER' for Senior High specialized subjects)."""
    text = (name or '').upper()
    if 'SOCIAL SCIENCE' in text:                          # "Humanities and Social Sciences" is not Science
        return 'OTHER'
    for area, words in _AREA_WORDS:
        if any(word in text for word in words):
            return area
    return 'OTHER'


def _clamp(value):
    return max(LOWEST, min(HIGHEST, value))


def _slope(points):
    if len(points) < 2:
        return 0.0
    mx, my = mean(x for x, _ in points), mean(y for _, y in points)
    sxx = sum((x - mx) ** 2 for x, _ in points)
    return sum((x - mx) * (y - my) for x, y in points) / sxx if sxx else 0.0


def _num(value):
    return NAN if value is None else float(value)


# =============================================================================================
# The records, arranged for features
# =============================================================================================

class Book:
    """Grades of one or more school years, arranged as learner-subject series plus their context."""

    def __init__(self, school_ids=None, school_year_ids=None):
        from django.db.models import Count

        from academics.models import Quarter
        from core.periods import GRADE, HAS_GRADE
        from grades.models import GradeComponent

        qs = GradeComponent.objects.filter(HAS_GRADE, quarter__isnull=False)
        if school_ids is not None:
            qs = qs.filter(enrollment__section__school_id__in=list(school_ids))
        if school_year_ids is not None:
            qs = qs.filter(quarter__school_year_id__in=list(school_year_ids))
        fields = ('enrollment_id', 'enrollment__student_id', 'enrollment__section_id', 'enrollment__section__school_id',
                  'quarter__school_year_id', 'quarter__school_year__year_start', 'quarter__quarter_number', 'subject_id',
                  'subject__subject_family__family_name', 'subject__subject_name',
                  'enrollment__section__grade_level__grade_number', 'enrollment__section__grade_level__is_senior_high',
                  'written_work_percent', 'performance_task_percent', 'quarterly_assessment_percent')
        self.series = {}
        for row in qs.values_list(*fields, GRADE):
            (enr, student, section, school, sy, year, period, subject, family, subject_name, level, senior,
             ww, pt, qa, grade) = row
            key = (enr, subject)
            s = self.series.get(key)
            if s is None:
                s = self.series[key] = {'student': student, 'section': section, 'school': school, 'sy': sy, 'year': year,
                                        'subject': subject, 'area': area_of(family or subject_name),
                                        'grade_level': level, 'senior': bool(senior), 'q': {}}
            s['q'][period] = (float(grade), _num(ww), _num(pt), _num(qa))

        by_learner, by_class = defaultdict(list), defaultdict(list)
        for (enr, subject), s in self.series.items():
            for period, values in s['q'].items():
                by_learner[(enr, period)].append(values[0])
                by_class[(s['section'], subject, period)].append(values[0])
        self.learner_avg = {k: mean(v) for k, v in by_learner.items()}
        self.class_avg = {k: mean(v) for k, v in by_class.items()}

        # last school year's final grade (average of its periods) per learner and learning area
        finals = defaultdict(list)
        for s in self.series.values():
            finals[(s['student'], s['area'], s['year'])].append(mean(v[0] for v in s['q'].values()))
        self.final = {k: mean(v) for k, v in finals.items()}

        years = {s['sy'] for s in self.series.values()}
        self.periods_in_year = {r['school_year_id']: r['n'] for r in
                                Quarter.objects.filter(school_year_id__in=years).values('school_year_id').annotate(n=Count('id'))}
        self.attendance = self._attendance(years)

    @staticmethod
    def _attendance(years):
        """Days present over school days, per enrollment and grading period (months whose 15th falls in the period)."""
        from academics.models import Quarter
        from attendance.models import AttendanceSummary

        month_period = {}
        for q in Quarter.objects.filter(school_year_id__in=years).values('school_year_id', 'quarter_number', 'date_start', 'date_end'):
            y, m = q['date_start'].year, q['date_start'].month
            while (y, m) <= (q['date_end'].year, q['date_end'].month):
                if q['date_start'] <= date(y, m, 15) <= q['date_end']:
                    month_period[(q['school_year_id'], m)] = q['quarter_number']
                y, m = (y + 1, 1) if m == 12 else (y, m + 1)
        totals = defaultdict(lambda: [0, 0])
        for enr, sy, month, present, days in AttendanceSummary.objects.filter(school_year_id__in=years).values_list(
                'enrollment_id', 'school_year_id', 'month', 'days_present', 'total_school_days'):
            period = month_period.get((sy, month))
            if period and days:
                totals[(enr, period)][0] += present
                totals[(enr, period)][1] += days
        return {k: present / days for k, (present, days) in totals.items() if days}

    def features(self, key, t, h):
        """The feature row for series `key`, known at the end of period t, predicting period t + h."""
        s = self.series[key]
        q = s['q']
        history = sorted(p for p in q if p <= t)
        grades = [q[p][0] for p in history]
        grade, ww, pt, qa = q[t]
        learner = self.learner_avg.get((key[0], t), grade)
        cls = self.class_avg.get((s['section'], s['subject'], t), grade)
        cls_prev = self.class_avg.get((s['section'], s['subject'], t - 1))
        last_year = self.final.get((s['student'], s['area'], s['year'] - 1), NAN)
        row = [grade, q[t - 1][0] if t - 1 in q else NAN, q[t - 2][0] if t - 2 in q else NAN, mean(grades),
               _slope(list(zip(history, grades))), len(history), ww, pt, qa, learner, grade - learner, cls,
               cls - cls_prev if cls_prev is not None else NAN, grade - cls, last_year,
               self.attendance.get((key[0], t), NAN), float(s['grade_level'] or 0) or NAN, 1.0 if s['senior'] else 0.0,
               float(t), float(h), float(self.periods_in_year.get(s['sy'], 4))]
        row += [1.0 if s['area'] == area else 0.0 for area in AREAS]
        return row


def _samples(book):
    """Every (series, start period, later period) pair with grades at both ends, up to MAX_HORIZON apart."""
    X, y, meta = [], [], []
    for key, s in book.series.items():
        periods = sorted(s['q'])
        for i, t in enumerate(periods[:-1]):
            for u in periods[i + 1:]:
                h = u - t
                if h > MAX_HORIZON:
                    break
                X.append(book.features(key, t, h))
                y.append(s['q'][u][0])
                meta.append({'key': key, 'section': s['section'], 'subject': s['subject'], 'year': s['year'], 'sy': s['sy'],
                             'origin': t, 'target': u, 'h': h, 'grade': s['q'][t][0]})
    return X, y, meta


# =============================================================================================
# Training
# =============================================================================================

def _baselines(book, meta):
    """What the rules this model replaces would have said: last grade, damped trend, the learner's own average."""
    last, damped, average = [], [], []
    for m in meta:
        s = book.series[m['key']]
        q, t, h = s['q'], m['origin'], m['h']
        history = sorted(p for p in q if p <= t)
        grades = [q[p][0] for p in history]
        changes = [b - a for a, b in zip(grades, grades[1:])]
        cls, cls_prev = book.class_avg.get((s['section'], s['subject'], t)), book.class_avg.get((s['section'], s['subject'], t - 1))
        class_change = cls - cls_prev if cls is not None and cls_prev is not None else 0.0
        w = len(changes) / (len(changes) + 3)                 # the learner's own change, trusted more with each change seen
        step = w * (mean(changes) if changes else 0.0) + (1 - w) * class_change
        last.append(grades[-1])
        damped.append(_clamp(grades[-1] + step * sum(0.7 ** i for i in range(1, h + 1))))
        average.append(mean(grades))
    return {'last grade': last, 'damped trend': damped, "learner's average": average}


def _scores(actual, predicted):
    errors = [p - a for a, p in zip(actual, predicted)]
    n = len(errors)
    below_true = [a < PASSING for a in actual]
    below_pred = [p < PASSING for p in predicted]
    hits = sum(1 for t, p in zip(below_true, below_pred) if t and p)
    flagged, real = sum(below_pred), sum(below_true)
    return {
        'n': n, 'mae': round(mean(abs(e) for e in errors), 3), 'rmse': round(math.sqrt(mean(e * e for e in errors)), 3),
        'within_2': round(100 * sum(1 for e in errors if abs(e) <= 2) / n, 1),
        'within_5': round(100 * sum(1 for e in errors if abs(e) <= 5) / n, 1),
        'below_75_recall': round(100 * hits / real, 1) if real else None,
        'below_75_precision': round(100 * hits / flagged, 1) if flagged else None,
    }


def _group_errors(meta, idx, predicted, by):
    """Errors of averaged forecasts: one per (group, start period, target period)."""
    groups = defaultdict(lambda: [[], []])
    for i, p in zip(idx, predicted):
        m = meta[i]
        g = groups[(by(m), m['origin'], m['target'])]
        g[0].append(m['actual'])
        g[1].append(p)
    return [(t - o, mean(p) - mean(a)) for (_, o, t), (a, p) in groups.items() if len(a) >= 5]


def _folds(meta):
    """Time splits: for each of the two most recent school years, its last period is scored on a model that
    learned only from earlier periods."""
    targets = defaultdict(set)
    for m in meta:
        targets[m['year']].add(m['target'])
    folds = []
    for year in sorted(targets)[-2:]:
        last = max(targets[year])
        test = [i for i, m in enumerate(meta) if m['year'] == year and m['target'] == last]
        train = [i for i, m in enumerate(meta) if (m['year'], m['target']) < (year, last)]
        if len(test) >= 50 and len(train) >= 200:
            folds.append({'name': f'SY {year}-{year + 1}, period {last}', 'train': train, 'test': test})
    return folds


def _fit(params, X, y):
    from xgboost import XGBRegressor
    model = XGBRegressor(objective='reg:squarederror', tree_method='hist', n_jobs=4, random_state=42, **params)
    model.fit(X, y)
    return model


def _quantile(values, q):
    values = sorted(values)
    if not values:
        return None
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos - lo)


def train(log=print, school_ids=None):
    """Build the samples, tune and score on time splits, fit on everything, save. Returns the metadata."""
    import joblib
    import numpy as np

    started = time.time()
    book = Book(school_ids=school_ids)
    X, y, meta = _samples(book)
    if len(X) < 500:
        raise ValueError(f'Only {len(X)} training samples; at least 500 are needed (two or more graded periods).')
    for m, target in zip(meta, y):
        m['actual'] = target
    X = np.array(X, dtype=float)
    y = np.array(y, dtype=float)
    base = X[:, FEATURES.index('grade')]
    delta = y - base
    learners = len({book.series[m['key']]['student'] for m in meta})
    log(f'Samples: {len(X):,} (learners {learners:,}, learner-subject series {len(book.series):,}, '
        f'horizons {dict(sorted(Counter(m["h"] for m in meta).items()))})')

    folds = _folds(meta)
    if not folds:
        raise ValueError('No time split has enough data to score the model.')
    for f in folds:
        log(f'  time split {f["name"]}: learns from {len(f["train"]):,} samples, scored on {len(f["test"]):,}')

    # tune: the same seeded sample of settings is scored on every split
    rng = random.Random(7)
    trials = [{k: rng.choice(v) for k, v in SEARCH_SPACE.items()} for _ in range(SEARCH_TRIALS)]
    best = None
    for n, params in enumerate(trials, start=1):
        maes = []
        for f in folds:
            model = _fit(params, X[f['train']], delta[f['train']])
            predicted = np.clip(base[f['test']] + model.predict(X[f['test']]), LOWEST, HIGHEST)
            maes.append(float(np.mean(np.abs(predicted - y[f['test']]))))
        score = mean(maes)
        if best is None or score < best[0]:
            best = (score, params)
            log(f'  setting {n:>2}/{len(trials)}: MAE {score:.3f}  <- best so far {params}')
    params = best[1]

    # score the chosen setting on each split, against the rules it replaces
    rules = _baselines(book, meta)
    evaluation, residuals, class_err, group_err = [], defaultdict(list), [], []
    for f in folds:
        model = _fit(params, X[f['train']], delta[f['train']])
        predicted = np.clip(base[f['test']] + model.predict(X[f['test']]), LOWEST, HIGHEST).tolist()
        actual = y[f['test']].tolist()
        row = {'split': f['name'], 'model': _scores(actual, predicted),
               'rules': {name: _scores(actual, [values[i] for i in f['test']]) for name, values in rules.items()},
               'by_horizon': {}}
        for h in sorted({meta[i]['h'] for i in f['test']}):
            pick = [j for j, i in enumerate(f['test']) if meta[i]['h'] == h]
            row['by_horizon'][h] = _scores([actual[j] for j in pick], [predicted[j] for j in pick])
        evaluation.append(row)
        for i, p, a in zip(f['test'], predicted, actual):
            residuals[meta[i]['h']].append(a - p)
        class_err += _group_errors(meta, f['test'], predicted, lambda m: (m['section'], m['subject']))
        group_err += _group_errors(meta, f['test'], predicted, lambda m: m['subject'])
        log(f'  {f["name"]}: model MAE {row["model"]["mae"]:.2f} (within 2 points: {row["model"]["within_2"]}%)  vs  ' +
            ', '.join(f'{name} {s["mae"]:.2f}' for name, s in row['rules'].items()))

    def ranges(errors, scale):
        """90% half-width per horizon; a horizon without enough errors grows from the nearest one with sqrt(h)."""
        by_h = defaultdict(list)
        for h, e in errors:
            by_h[h].append(abs(e))
        out = {}
        for h in range(1, MAX_HORIZON + 1):
            if len(by_h[h]) >= 20:
                out[h] = round(_quantile(by_h[h], 0.9), 2)
        known = sorted(out)
        for h in range(1, MAX_HORIZON + 1):
            if h not in out:
                ref = min(known, key=lambda k: abs(k - h)) if known else None
                out[h] = round(out[ref] * math.sqrt(h / ref), 2) if ref else scale * math.sqrt(h)
        return out

    intervals = {
        'learner': ranges([(h, e) for h, values in residuals.items() for e in values], 4.0),
        'class': ranges(class_err, 2.0),
        'group': ranges(group_err, 1.5),
    }
    residual_quantiles = {}
    for h in range(1, MAX_HORIZON + 1):
        values = residuals.get(h) or residuals.get(min(residuals, key=lambda k: abs(k - h)))
        residual_quantiles[h] = [round(_quantile(values, q / 100), 3) for q in range(1, 100)]

    final = _fit(params, X, delta)
    version = datetime.now().strftime('%Y%m%d-%H%M%S')
    MODEL_DIR.mkdir(parents=True, exist_ok=True)
    joblib.dump({'model': final, 'features': FEATURES, 'version': version}, MODEL_FILE)
    importance = sorted(zip(FEATURES, final.feature_importances_.tolist()), key=lambda kv: -kv[1])
    meta_out = {
        'version': version, 'trained_at': datetime.now().isoformat(timespec='seconds'), 'algorithm': 'XGBoost regressor (change from the current grade)',
        'samples': len(X), 'learners': learners, 'series': len(book.series), 'school_years': len({m['sy'] for m in meta}),
        'horizons': dict(sorted(Counter(m['h'] for m in meta).items())), 'features': list(FEATURES), 'params': params,
        'search': {'trials': len(trials), 'best_cv_mae': round(best[0], 3)},
        'evaluation': evaluation, 'intervals': intervals, 'residual_quantiles': residual_quantiles,
        'importance': [[name, round(v, 4)] for name, v in importance[:12]],
        'seconds': round(time.time() - started, 1),
    }
    META_FILE.write_text(json.dumps(meta_out, indent=2), encoding='utf-8')
    log(f'Saved {MODEL_FILE.name} (version {version}) in {meta_out["seconds"]}s')
    return meta_out


# =============================================================================================
# Using the model
# =============================================================================================

_loaded = {'mtime': None, 'model': None, 'meta': None}


def load():
    """(model, metadata) of the saved forecaster, or (None, None) when there is none. Reloads after retraining."""
    try:
        mtime = MODEL_FILE.stat().st_mtime
    except FileNotFoundError:
        return None, None
    if _loaded['mtime'] != mtime:
        try:
            import joblib
            bundle = joblib.load(MODEL_FILE)
            meta = json.loads(META_FILE.read_text(encoding='utf-8'))
            if tuple(bundle.get('features', ())) != FEATURES:
                return None, None                         # trained with other features: retrain
            _loaded.update(mtime=mtime, model=bundle['model'], meta=meta)
        except Exception:
            return None, None
    return _loaded['model'], _loaded['meta']


def _by_horizon(table, horizon):
    """A per-horizon entry of the metadata (JSON keys are strings, freshly trained ones are numbers)."""
    h = min(max(int(horizon), 1), MAX_HORIZON)
    return table.get(str(h), table.get(h))


def chance_below(predicted, horizon, meta=None):
    """Chance (0 to 1) that the actual grade ends below 75, read from the model's errors on held-out periods."""
    meta = meta or load()[1]
    quantiles = _by_horizon(meta['residual_quantiles'], horizon) if meta else None
    if not quantiles:
        return None
    gap = PASSING - predicted                             # below 75 when actual - predicted < gap
    return sum(1 for r in quantiles if r < gap) / (len(quantiles) + 1)


def interval(level, horizon, meta=None):
    """Half-width of the 90% likely range for an average at 'learner', 'class' or 'group' level."""
    meta = meta or load()[1]
    return _by_horizon(meta['intervals'].get(level, {}), horizon) if meta else None


def forecast_school_year(school_id, school_year_id):
    """Every learner-subject of one school year: grades so far, the forecast of each later period, and the
    one-step forecast the model would have made for each period that already has grades.

    {'series': {(enrollment_id, subject_id): {'section', 'subject', 'grade_level', 'area', 'actual': {p: grade},
                 'future': {p: grade}, 'back': {p: grade}, 'origin': p}},
     'periods': n, 'meta': model metadata}  -- or None without a trained model. Cached until grades change.
    """
    from django.core.cache import caches

    from academics.models import SchoolYear
    from core.caching import data_version

    model, meta = load()
    if model is None:
        return None
    key = f'forecast:{school_id}:{school_year_id}:{data_version()}:{meta["version"]}'
    cache = caches['default']
    cached = cache.get(key)
    if cached is not None:
        return cached
    import numpy as np

    sy = SchoolYear.objects.filter(id=school_year_id).first()
    if sy is None:
        return None
    years = [school_year_id] + list(SchoolYear.objects.filter(school_id=school_id, year_start=sy.year_start - 1)
                                    .values_list('id', flat=True))
    book = Book(school_ids=[school_id], school_year_ids=years)
    periods = book.periods_in_year.get(school_year_id, 4)
    rows, slots, out = [], [], {}
    for key_, s in book.series.items():
        if s['sy'] != school_year_id:
            continue
        have = sorted(s['q'])
        origin = have[-1]
        out[key_] = {'section': s['section'], 'subject': s['subject'], 'grade_level': s['grade_level'], 'area': s['area'],
                     'actual': {p: s['q'][p][0] for p in have}, 'future': {}, 'back': {}, 'origin': origin}
        for u in range(origin + 1, min(periods, origin + MAX_HORIZON) + 1):
            rows.append(book.features(key_, origin, u - origin))
            slots.append((key_, 'future', u, s['q'][origin][0]))
        for t, u in zip(have, have[1:]):
            if u - t == 1:
                rows.append(book.features(key_, t, 1))
                slots.append((key_, 'back', u, s['q'][t][0]))
    if rows:
        predicted = np.clip(np.array([g for *_, g in slots]) + model.predict(np.array(rows, dtype=float)), LOWEST, HIGHEST)
        for (key_, kind, period, _), value in zip(slots, predicted.tolist()):
            out[key_][kind][period] = round(value, 2)
    result = {'series': out, 'periods': periods, 'meta': meta}
    cache.set(key, result, 6 * 3600)
    return result
