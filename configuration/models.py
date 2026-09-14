# configuration/models.py
"""
Phase 14: System Configuration models for Formify LIS.
DepEd-specific operational configurations (LIS integration, BEIS reporting,
division settings) and grading period management linking quarters/semesters
to report card types with grade encoding workflow control.
THIS IS THE FINAL PHASE.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models import Q
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
GRADING_PERIOD_TYPE_CHOICES = [
    ('Quarter', 'Quarter (Q1-Q4) — JHS'),
    ('Semester', 'Semester (1st-2nd) — SHS'),
]

REPORT_CARD_TYPE_CHOICES = [
    ('SF9_JHS', 'SF9 — Junior High School Report Card'),
    ('SF9_SHS', 'SF9 — Senior High School Report Card'),
]


# =============================================================================
# 14.1 — DepEdConfiguration
# =============================================================================
class DepEdConfiguration(models.Model):
    CONFIG_TYPE_CHOICES = [
        ('String', 'String'),
        ('Integer', 'Integer'),
        ('Boolean', 'Boolean'),
        ('JSON', 'JSON'),
        ('URL', 'URL'),
    ]
    CATEGORY_CHOICES = [
        ('LIS_Integration', 'LIS Integration'),
        ('BEIS_Reporting', 'BEIS Reporting'),
        ('Division_Office', 'Division Office'),
        ('Dashboard', 'Dashboard'),
        ('Sync', 'Data Synchronization'),
        ('Security', 'Security'),
        ('Other', 'Other'),
    ]

    config_key = models.CharField(
        max_length=100,
        unique=True,
        help_text="e.g., 'LIS_API_ENDPOINT', 'BEIS_SCHOOL_ID', 'DIVISION_CODE', 'SYNC_FREQUENCY_HOURS'.",
    )
    config_value = models.TextField()
    config_type = models.CharField(
        max_length=20,
        choices=CONFIG_TYPE_CHOICES,
        default='String',
    )
    category = models.CharField(
        max_length=30,
        choices=CATEGORY_CHOICES,
        default='Other',
        db_index=True,
    )
    description = models.TextField(blank=True)
    is_required = models.BooleanField(
        default=False,
        help_text='Critical configurations that must be set for system operation.',
    )
    is_encrypted = models.BooleanField(
        default=False,
        help_text='Sensitive values stored encrypted at rest (API keys, tokens).',
    )
    validation_regex = models.CharField(
        max_length=255,
        blank=True,
        help_text='Optional regex for value validation. Applied server-side with timeout to prevent ReDoS.',
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_deped_configs',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['category', 'config_key']
        indexes = [
            models.Index(fields=['category']),
            models.Index(fields=['is_required']),
        ]
        verbose_name = 'DepEd Configuration'
        verbose_name_plural = 'DepEd Configurations'

    @property
    def typed_value(self):
        if self.config_type == 'Integer':
            try:
                return int(self.config_value)
            except (ValueError, TypeError):
                return self.config_value
        elif self.config_type == 'Boolean':
            return self.config_value.lower() in ('true', '1', 'yes')
        elif self.config_type == 'JSON':
            import json
            try:
                return json.loads(self.config_value)
            except (json.JSONDecodeError, TypeError):
                return self.config_value
        return self.config_value

    def clean(self):
        if self.validation_regex and self.config_value:
            import re
            import signal

            def handler(signum, frame):
                raise TimeoutError('Regex validation timed out.')

            try:
                signal.signal(signal.SIGALRM, handler)
                signal.alarm(1)  # 1 second timeout
                compiled = re.compile(self.validation_regex)
                if not compiled.match(self.config_value):
                    raise ValidationError({
                        'config_value': f'Value does not match the required pattern: {self.validation_regex}',
                    })
                signal.alarm(0)
            except TimeoutError:
                raise ValidationError({
                    'validation_regex': 'Regex validation timed out. The pattern may be vulnerable to ReDoS.',
                })
            except re.error:
                raise ValidationError({
                    'validation_regex': 'Invalid regular expression.',
                })
            finally:
                signal.alarm(0)

    def __str__(self):
        return f"{self.config_key} ({self.get_category_display()})"


# =============================================================================
# 14.2 — GradingPeriod
# =============================================================================
class GradingPeriod(models.Model):
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.PROTECT,
        related_name='grading_periods',
    )
    period_type = models.CharField(
        max_length=10,
        choices=GRADING_PERIOD_TYPE_CHOICES,
        db_index=True,
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grading_period_configs',
        help_text="Required if period_type='Quarter'.",
    )
    semester = models.ForeignKey(
        'academics.Semester',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grading_period_configs',
        help_text="Required if period_type='Semester'.",
    )
    report_card_type = models.CharField(
        max_length=10,
        choices=REPORT_CARD_TYPE_CHOICES,
    )
    is_grade_encoding_open = models.BooleanField(
        default=False,
        help_text='Can teachers encode grades for this period?',
    )
    grade_encoding_deadline = models.DateTimeField(null=True, blank=True)
    grade_validation_deadline = models.DateTimeField(null=True, blank=True)
    is_grades_locked = models.BooleanField(
        default=False,
        help_text='Locked periods prevent any grade modification.',
    )
    weight_in_final_grade = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        null=True,
        blank=True,
        help_text='Weight in final grade: Q1-Q4 each = 0.2500. S1-S2 each = 0.5000.',
    )
    order = models.PositiveSmallIntegerField(
        help_text='Display/processing order: 1=Q1/S1, 2=Q2/S2, 3=Q3, 4=Q4.',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['school_year', 'order']
        indexes = [
            models.Index(fields=['is_grade_encoding_open']),
            models.Index(fields=['is_grades_locked']),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=['school_year', 'quarter'],
                condition=Q(quarter__isnull=False),
                name='unique_quarter_per_school_year',
            ),
            models.UniqueConstraint(
                fields=['school_year', 'semester'],
                condition=Q(semester__isnull=False),
                name='unique_semester_per_school_year',
            ),
        ]
        verbose_name = 'Grading Period'
        verbose_name_plural = 'Grading Periods'

    @property
    def period_name(self):
        if self.quarter:
            return self.quarter.quarter_label
        if self.semester:
            return self.semester.semester_label
        return 'Unknown'

    @property
    def is_jhs(self):
        return self.period_type == 'Quarter'

    @property
    def is_shs(self):
        return self.period_type == 'Semester'

    def clean(self):
        if self.period_type == 'Quarter':
            if not self.quarter:
                raise ValidationError({
                    'quarter': 'Quarter is required when period type is "Quarter".',
                })
            if self.semester:
                raise ValidationError({
                    'semester': 'Semester must be NULL when period type is "Quarter".',
                })
        elif self.period_type == 'Semester':
            if not self.semester:
                raise ValidationError({
                    'semester': 'Semester is required when period type is "Semester".',
                })
            if self.quarter:
                raise ValidationError({
                    'quarter': 'Quarter must be NULL when period type is "Semester".',
                })

        if self.weight_in_final_grade is not None:
            weight = float(self.weight_in_final_grade)
            if weight < 0 or weight > 1:
                raise ValidationError({
                    'weight_in_final_grade': 'Weight must be between 0.0000 and 1.0000.',
                })

        if self.is_grades_locked and self.is_grade_encoding_open:
            raise ValidationError({
                'is_grade_encoding_open': 'Grade encoding cannot be open when grades are locked.',
            })

    def __str__(self):
        status = 'Open' if self.is_grade_encoding_open else 'Closed'
        lock = ' 🔒' if self.is_grades_locked else ''
        return (
            f"{self.school_year.year_label} — {self.period_name} "
            f"({self.get_period_type_display()}) — {status}{lock}"
        )