"""Grading periods and grades, the way each school counts them.

A school grades by quarter (Q1-Q4), term (T1-T3, trimestral) or semester (S1-S2) (School.period_type);
its periods are the Quarter rows of the school year. A school may change its grading system with a new
school year (DepEd moved from four quarters to three terms in SY 2026-2027), so a year's own period
labels decide how its periods are named. Every page, chart and report names and counts periods through
these helpers instead of assuming four quarters.

The grade that counts (report card, passing at 75, proficiency level) is the quarterly grade:
GradeComponent.transmuted_grade. Older records kept it in initial_grade only, so readers fall
back to that.
"""
from decimal import ROUND_HALF_UP, Decimal

from django.db.models import DecimalField, F, Q
from django.db.models.functions import Coalesce
from django.utils import timezone

# A trimestral school's periods are its three terms, as DepEd Orders No. 009 and 015, s. 2026 and their e-class records name them
PERIOD_WORDS = {'Q': ('Quarter', 'Quarters'), 'T': ('Term', 'Terms'), 'S': ('Semester', 'Semesters')}
TYPE_PREFIX = {'QUARTERLY': 'Q', 'TRIMESTRAL': 'T', 'SEMESTRAL': 'S'}
ORDINALS = {1: 'First', 2: 'Second', 3: 'Third', 4: 'Fourth'}

# the grade on the report card; use in .annotate()/.aggregate() instead of 'initial_grade'
GRADE = Coalesce(F('transmuted_grade'), F('initial_grade'), output_field=DecimalField(max_digits=5, decimal_places=2))
HAS_GRADE = Q(transmuted_grade__isnull=False) | Q(initial_grade__isnull=False)


def grade_value(transmuted, initial):
    """The quarterly grade of one record as a float (None when there is none)."""
    value = transmuted if transmuted is not None else initial
    return None if value is None else float(value)


def prefix(school=None, periods=()):
    """'Q', 'T' or 'S': the school year's own periods decide, else the school's setting."""
    for p in periods:
        if p.quarter_label and p.quarter_label[:1].upper() in PERIOD_WORDS:
            return p.quarter_label[:1].upper()
    if school is not None and getattr(school, 'period_type', None) in TYPE_PREFIX:
        return TYPE_PREFIX[school.period_type]
    return 'Q'


def word(school=None, periods=(), plural=False):
    """'Quarter', 'Term' or 'Semester' (or the plural)."""
    words = PERIOD_WORDS.get(prefix(school, periods), PERIOD_WORDS['Q'])
    return words[1] if plural else words[0]


def name(period):
    """'Quarter 2', 'Term 1', 'Semester 2'."""
    if not period:
        return ''
    w = PERIOD_WORDS.get((period.quarter_label or 'Q')[:1].upper(), PERIOD_WORDS['Q'])[0]
    return f'{w} {period.quarter_number}'


def long_name(period):
    """'Second Quarter' (the e-class record says it this way in cell A7)."""
    if not period:
        return ''
    w = PERIOD_WORDS.get((period.quarter_label or 'Q')[:1].upper(), PERIOD_WORDS['Q'])[0]
    return f'{ORDINALS.get(period.quarter_number, period.quarter_number)} {w}'


def short(period):
    """'Q2', 'T1', 'S2' as stored."""
    return period.quarter_label if period else ''


def current(periods, has_grades=None):
    """The period marked current, else the one today falls in, else (if has_grades) the latest with grades."""
    periods = list(periods)
    if not periods:
        return None
    today = timezone.localdate()
    found = next((p for p in periods if p.is_current_quarter), None) or \
        next((p for p in periods if p.date_start <= today <= p.date_end), None)
    if found:
        return found
    if has_grades:
        for p in reversed(periods):
            if has_grades(p):
                return p
    return periods[-1] if periods[-1].date_end < today else periods[0]


def for_class(assignment, periods):
    """The periods a class is graded in: all of them, or only its semester's for a Senior High subject."""
    periods = list(periods)
    semester = getattr(assignment, 'semester', None)
    if not semester:
        return periods
    inside = [p for p in periods if p.date_start <= semester.date_end and p.date_end >= semester.date_start]
    return inside or periods


def final_grade(values, periods_count):
    """Rounded average of the period grades, only when every period of the class has one (DepEd Order No. 8, s. 2015)."""
    present = [v for v in values if v is not None]
    if not periods_count or len(present) < periods_count:
        return None
    return int(_round_half_up(sum(present) / len(present)))


def _round_half_up(x):
    return Decimal(repr(float(x))).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def deadline_info(period, now=None, field='grade_encoding_deadline'):
    """(days left, overdue?) for a period's grade encoding (or validation) deadline, or (None, False) without one."""
    deadline = getattr(period, field, None)
    if not deadline:
        return None, False
    now = now or timezone.now()
    days = (timezone.localtime(deadline).date() - timezone.localtime(now).date()).days
    return days, deadline < now


def due_text(period, field='grade_encoding_deadline'):
    """' Due in 3 days.', ' Due today.', ' The deadline was Nov 13.' or '' (with a leading space)."""
    days, overdue = deadline_info(period, field=field)
    if days is None:
        return ''
    if overdue:
        return f' The deadline was {timezone.localtime(getattr(period, field)):%b %d}.'
    if days == 0:
        return ' Due today.'
    return f' Due in {days} day{"s" if days != 1 else ""}.'
