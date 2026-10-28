"""School years and their grading periods: the rules shared by the System Administrator and the School Head.

A school grades by quarter, term or semester (School.period_type); a school year's periods are its
Quarter rows, labelled Q, T or S plus the number. The School Head chooses the grading system when
starting a school year (DepEd moved from four quarters to three terms in SY 2026-2027, DepEd Orders
No. 009 and 015, s. 2026), so each year keeps the system its periods were made with. Both the admin
panel and the School Head's School Year page create years and periods through these helpers, so the
two can never disagree.
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

PERIOD_CONFIG = {
    'QUARTERLY': {'key': 'QUARTERLY', 'count': 4, 'prefix': 'Q', 'noun': 'Quarter', 'plural': 'Quarters',
                  'name': 'Quarterly', 'basis': 'Four quarters, as in DepEd Order No. 8, s. 2015.'},
    'TRIMESTRAL': {'key': 'TRIMESTRAL', 'count': 3, 'prefix': 'T', 'noun': 'Term', 'plural': 'Terms',
                   'name': 'Trimestral', 'basis': 'Three terms, the school calendar of DepEd Order No. 009, s. 2026, graded '
                                                  'under DepEd Order No. 015, s. 2026.'},
    'SEMESTRAL': {'key': 'SEMESTRAL', 'count': 2, 'prefix': 'S', 'noun': 'Semester', 'plural': 'Semesters',
                  'name': 'Semestral', 'basis': 'Two semesters, as Senior High kept them before the three-term calendar.'},
}
PREFIX_TYPE = {cfg['prefix']: key for key, cfg in PERIOD_CONFIG.items()}


def period_config(school):
    """Grading-period settings (count, label prefix, wording) for a school."""
    return PERIOD_CONFIG.get(school.period_type, PERIOD_CONFIG['QUARTERLY'])


def year_config(sy, periods=None):
    """The grading system of one school year: the one its periods were made with, else the school's."""
    from .models import Quarter

    labels = [p.quarter_label for p in periods] if periods is not None else \
        list(Quarter.objects.filter(school_year=sy).values_list('quarter_label', flat=True)[:1])
    key = next((PREFIX_TYPE.get((label or '')[:1].upper()) for label in labels if label), None)
    return PERIOD_CONFIG[key] if key else period_config(sy.school)


def period_deadlines(date_end):
    """Default grade encoding / validation deadlines: 7 and 14 days after a period ends."""
    end = datetime.combine(date_end, time(23, 59))
    if settings.USE_TZ:
        end = timezone.make_aware(end)
    return end + timedelta(days=7), end + timedelta(days=14)


def generate_periods(sy, period_type=None):
    """Create the missing grading periods of a school year, split evenly over its dates.

    The number of periods and their labels follow period_type when given, else the year's own grading system.
    Returns (created, already_existing).
    """
    from .models import Quarter

    cfg = PERIOD_CONFIG.get(period_type) or year_config(sy)
    count = cfg['count']
    length = ((sy.date_end - sy.date_start).days + 1) // count
    created = 0
    with transaction.atomic():
        for i in range(count):
            start = sy.date_start + timedelta(days=length * i)
            end = sy.date_end if i == count - 1 else start + timedelta(days=length - 1)
            encoding, validation = period_deadlines(end)
            _, was_created = Quarter.objects.get_or_create(
                school_year=sy,
                quarter_number=i + 1,
                defaults={
                    'quarter_label': f'{cfg["prefix"]}{i + 1}',
                    'date_start': start,
                    'date_end': end,
                    'grade_encoding_deadline': encoding,
                    'grade_validation_deadline': validation,
                },
            )
            created += was_created
    return created, count - created


def has_records(sy):
    """Whether anything hangs on a school year (sections, enrollments, grades): such a year is never deleted."""
    from enrollment.models import Enrollment
    from grades.models import GradeComponent
    from .models import Section

    return (Section.objects.filter(school_year=sy).exists() or Enrollment.objects.filter(school_year=sy).exists()
            or GradeComponent.objects.filter(quarter__school_year=sy).exists())
