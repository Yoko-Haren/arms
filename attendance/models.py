# attendance/models.py
"""
Phase 6: Attendance models for Formify LIS.
Daily attendance records, monthly summaries, DepEd-mandated
interventions, and SF2 reporting.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
ATTENDANCE_STATUS_CHOICES = [
    ('Present', 'Present'),
    ('Absent', 'Absent'),
    ('Late', 'Late / Tardy'),
    ('Excused', 'Excused Absence'),
    ('Cutting', 'Cutting Classes'),
    ('Suspended', 'Suspended'),
]

EXCUSE_TYPE_CHOICES = [
    ('', 'Not Applicable'),
    ('Sick', 'Sick / Illness'),
    ('Family_Emergency', 'Family Emergency'),
    ('Official_Business', 'Official School Business'),
    ('Calamity', 'Natural Calamity / Weather'),
    ('Religious', 'Religious Observance'),
    ('Bereavement', 'Bereavement / Death in Family'),
    ('Other', 'Other'),
]

INTERVENTION_TYPE_CHOICES = [
    ('Parent_Contact', 'Parent Contact (Phone/Message)'),
    ('Parent_Conference', 'Parent-Teacher Conference'),
    ('Home_Visit', 'Home Visit'),
    ('Counseling', 'Guidance Counseling'),
    ('Referral_Barangay', 'Referral to Barangay'),
    ('Referral_DSWD', 'Referral to DSWD'),
    ('Other', 'Other'),
]

INTERVENTION_STATUS_CHOICES = [
    ('Open', 'Open — Ongoing'),
    ('Resolved', 'Resolved — Learner returned'),
    ('Escalated', 'Escalated — Referred to higher authority'),
    ('Closed', 'Closed — No further action'),
]

SF2_STATUS_CHOICES = [
    ('Draft', 'Draft'),
    ('Submitted', 'Submitted to Registrar'),
    ('Reviewed', 'Reviewed'),
    ('Approved', 'Approved'),
    ('Returned', 'Returned for Revision'),
]


# =============================================================================
# 6.1 — AttendanceRecord
# =============================================================================
class AttendanceRecord(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='attendance_records',
        help_text='The enrollment record for this school year.',
    )
    date = models.DateField(
        db_index=True,
        help_text='Date of attendance.',
    )
    status = models.CharField(
        max_length=15,
        choices=ATTENDANCE_STATUS_CHOICES,
        default='Present',
        db_index=True,
    )
    time_in = models.TimeField(
        null=True,
        blank=True,
        help_text="Time student arrived. Required if status is 'Late'.",
    )
    minutes_late = models.PositiveSmallIntegerField(
        default=0,
        help_text='Calculated minutes late. Auto-computed from time_in vs official start time.',
    )
    excuse_type = models.CharField(
        max_length=30,
        blank=True,
        choices=EXCUSE_TYPE_CHOICES,
        help_text="Required if status is 'Excused'.",
    )
    excuse_note = models.TextField(
        blank=True,
        help_text='Explanation for absence or lateness.',
    )
    excuse_validated = models.BooleanField(
        default=False,
        help_text='Has the excuse been verified by the class adviser?',
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='validated_attendance',
    )
    validated_at = models.DateTimeField(null=True, blank=True)
    marked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='marked_attendance',
        help_text='Teacher who recorded this attendance.',
    )
    marked_at = models.DateTimeField(auto_now_add=True)
    is_holiday = models.BooleanField(
        default=False,
        help_text='Was this day a holiday? Attendance not required.',
    )
    remarks = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_attendance',
    )

    class Meta:
        unique_together = [['enrollment', 'date']]
        ordering = ['-date', 'enrollment__student__last_name']
        indexes = [
            models.Index(fields=['date', 'status']),
            models.Index(fields=['enrollment', 'date']),
            models.Index(fields=['status', 'date']),
        ]
        verbose_name = 'Attendance Record'
        verbose_name_plural = 'Attendance Records'

    @property
    def student(self):
        return self.enrollment.student

    @property
    def student_name(self):
        return self.enrollment.student.full_name

    @property
    def lrn(self):
        return self.enrollment.student.lrn

    @property
    def section(self):
        return self.enrollment.section

    def clean(self):
        if self.status == 'Late' and not self.time_in:
            # Warning only — not a hard error
            pass
        if self.status == 'Excused' and not self.excuse_type:
            raise ValidationError({
                'excuse_type': 'Excuse type is required when status is "Excused".',
            })
        if self.date and self.date > timezone.now().date():
            raise ValidationError({
                'date': 'Attendance date cannot be in the future.',
            })

    def __str__(self):
        return f"{self.enrollment.student.lrn} — {self.date} — {self.get_status_display()}"


# =============================================================================
# 6.2 — AttendanceSummary
# =============================================================================
class AttendanceSummary(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='attendance_summaries',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='attendance_summaries',
    )
    month = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
        help_text='Month number: 1=June, 2=July, ..., 12=May.',
    )
    total_school_days = models.PositiveSmallIntegerField(default=0)
    days_present = models.PositiveSmallIntegerField(default=0)
    days_absent = models.PositiveSmallIntegerField(default=0)
    days_late = models.PositiveSmallIntegerField(default=0)
    days_excused = models.PositiveSmallIntegerField(default=0)
    days_cutting = models.PositiveSmallIntegerField(default=0)
    days_suspended = models.PositiveSmallIntegerField(default=0)
    absence_rate_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='(days_absent / total_school_days) * 100.',
    )
    is_at_risk = models.BooleanField(
        default=False,
        db_index=True,
        help_text='≥20% absence rate triggers DepEd intervention.',
    )
    consecutive_absences = models.PositiveSmallIntegerField(
        default=0,
        help_text='Maximum consecutive days absent this month.',
    )
    last_calculated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['enrollment', 'month', 'school_year']]
        ordering = ['school_year', 'month', 'enrollment__student__last_name']
        indexes = [
            models.Index(fields=['is_at_risk']),
            models.Index(fields=['school_year', 'month']),
        ]
        verbose_name = 'Attendance Summary'
        verbose_name_plural = 'Attendance Summaries'

    @property
    def student(self):
        return self.enrollment.student

    @property
    def student_name(self):
        return self.enrollment.student.full_name

    def __str__(self):
        base = (
            f"{self.enrollment.student.lrn} — Month {self.month} "
            f"({self.school_year.year_label}): {self.days_absent} absences"
        )
        if self.is_at_risk:
            base += ' ⚠️ AT RISK'
        return base


# =============================================================================
# 6.3 — AttendanceIntervention
# =============================================================================
class AttendanceIntervention(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='attendance_interventions',
    )
    intervention_date = models.DateField(db_index=True)
    intervention_type = models.CharField(
        max_length=30,
        choices=INTERVENTION_TYPE_CHOICES,
    )
    conducted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='conducted_interventions',
    )
    description = models.TextField(
        help_text='What was done during the intervention?',
    )
    outcome = models.TextField(blank=True)
    follow_up_date = models.DateField(null=True, blank=True)
    follow_up_notes = models.TextField(blank=True)
    status = models.CharField(
        max_length=20,
        choices=INTERVENTION_STATUS_CHOICES,
        default='Open',
        db_index=True,
    )
    attachment = models.FileField(
        upload_to='attendance/interventions/%Y/%m/',
        null=True,
        blank=True,
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-intervention_date']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['enrollment', 'intervention_date']),
        ]
        verbose_name = 'Attendance Intervention'
        verbose_name_plural = 'Attendance Interventions'

    @property
    def student(self):
        return self.enrollment.student

    @property
    def student_name(self):
        return self.enrollment.student.full_name

    def clean(self):
        if self.follow_up_date and self.intervention_date:
            if self.follow_up_date < self.intervention_date:
                raise ValidationError({
                    'follow_up_date': 'Follow-up date must be on or after the intervention date.',
                })

    def __str__(self):
        return (
            f"Intervention: {self.enrollment.student.lrn} — "
            f"{self.get_intervention_type_display()} ({self.intervention_date})"
        )


# =============================================================================
# 6.4 — SF2AttendanceReport
# =============================================================================
class SF2AttendanceReport(models.Model):
    section = models.ForeignKey(
        'academics.Section',
        on_delete=models.CASCADE,
        related_name='sf2_reports',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='sf2_reports',
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sf2_reports',
        help_text='Grading quarter this report covers. Nullable per master schema.',
    )
    report_month = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(12)],
    )
    report_year = models.PositiveSmallIntegerField()
    total_enrollment = models.PositiveSmallIntegerField(
        default=0,
        help_text='Number of enrolled learners in this section.',
    )
    total_male = models.PositiveSmallIntegerField(default=0)
    total_female = models.PositiveSmallIntegerField(default=0)
    average_daily_attendance = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    average_attendance_rate = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    total_dropouts_this_month = models.PositiveSmallIntegerField(default=0)
    total_transferred_out_this_month = models.PositiveSmallIntegerField(default=0)
    total_transferred_in_this_month = models.PositiveSmallIntegerField(default=0)
    chronically_absent_count = models.PositiveSmallIntegerField(
        default=0,
        help_text='Learners with ≥20% absences.',
    )
    interventions_conducted = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=SF2_STATUS_CHOICES,
        default='Draft',
        db_index=True,
    )
    prepared_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='prepared_sf2_reports',
    )
    prepared_at = models.DateTimeField(null=True, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_sf2_reports',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    file = models.FileField(
        upload_to='attendance/sf2/%Y/%m/',
        null=True,
        blank=True,
    )
    is_submitted_to_division = models.BooleanField(default=False)
    division_submission_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['section', 'school_year', 'quarter', 'report_month']]
        ordering = ['-school_year__year_start', 'section__section_name', 'report_month']
        verbose_name = 'SF2 Attendance Report'
        verbose_name_plural = 'SF2 Attendance Reports'

    def clean(self):
        if self.quarter and self.report_month:
            q_start_month = self.quarter.date_start.month
            q_end_month = self.quarter.date_end.month
            if self.report_month < q_start_month or self.report_month > q_end_month:
                raise ValidationError({
                    'report_month': f'Report month must fall within the quarter ({self.quarter.quarter_label}: months {q_start_month}-{q_end_month}).',
                })

    def __str__(self):
        return (
            f"SF2: {self.section} — Month {self.report_month} "
            f"({self.school_year.year_label}) — {self.get_status_display()}"
        )