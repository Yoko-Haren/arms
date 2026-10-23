"""School years and their grading periods: the rules shared by the System Administrator and the School Head.

A school grades by quarter, trimester or semester (School.period_type); a school year's periods are
its Quarter rows, labelled Q, T or S plus the number. Both the admin panel and the School Head's
School Year page create years and periods through these helpers, so the two can never disagree.
"""
from datetime import datetime, time, timedelta

from django.conf import settings
from django.db import transaction
from django.utils import timezone

PERIOD_CONFIG = {
    'QUARTERLY': {'count': 4, 'prefix': 'Q', 'noun': 'Quarter', 'plural': 'Quarters'},
    'TRIMESTRAL': {'count': 3, 'prefix': 'T', 'noun': 'Trimester', 'plural': 'Trimesters'},
    'SEMESTRAL': {'count': 2, 'prefix': 'S', 'noun': 'Semester', 'plural': 'Semesters'},
}


def period_config(school):
    """Grading-period settings (count, label prefix, wording) for a school."""
    return PERIOD_CONFIG.get(school.period_type, PERIOD_CONFIG['QUARTERLY'])


def period_deadlines(date_end):
    """Default grade encoding / validation deadlines: 7 and 14 days after a period ends."""
    end = datetime.combine(date_end, time(23, 59))
    if settings.USE_TZ:
        end = timezone.make_aware(end)
    return end + timedelta(days=7), end + timedelta(days=14)


def generate_periods(sy):
    """Create the missing grading periods of a school year, split evenly over its dates.

    The number of periods and their labels follow the school's period type.
    Returns (created, already_existing).
    """
    from .models import Quarter

    cfg = period_config(sy.school)
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
