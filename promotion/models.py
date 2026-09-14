# promotion/models.py
"""
Phase 8: Promotion & Graduation models for Formify LIS.
Promotion recommendations with remedial tracking (consolidates
promotion_decisions and summer_remedial_records), retention records
with intervention tracking, and graduation records with diploma
and honors management.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
RECOMMENDATION_CHOICES = [
    ('Promoted', 'Promoted — All subjects passed'),
    ('Conditionally_Promoted', 'Conditionally Promoted — Failed 1-2 subjects, must pass remedial classes'),
    ('Retained', 'Retained — Failed >2 subjects or failed remedial'),
]

RECOMMENDATION_STATUS_CHOICES = [
    ('Draft', 'Draft — Adviser preparing'),
    ('Submitted', 'Submitted to Registrar'),
    ('Reviewed', 'Reviewed by Registrar'),
    ('Approved', 'Approved by School Head'),
    ('Finalized', 'Finalized — Recorded in SF10'),
]

RETENTION_REASON_CHOICES = [
    ('Academic_Failure', 'Academic Failure — Failed >2 subjects'),
    ('Failed_Remedial', 'Failed Remedial — Did not pass summer/remedial classes'),
    ('Excessive_Absences', 'Excessive Absences — ≥20% of school days missed'),
    ('Parental_Request', 'Parental/Guardian Request'),
    ('Health', 'Health Reasons — Extended illness'),
    ('Other', 'Other'),
]

GRADUATION_TYPE_CHOICES = [
    ('JHS_Completion', 'Junior High School Completion'),
    ('SHS_Graduation', 'Senior High School Graduation'),
]

GRADUATION_HONORS_CHOICES = [
    ('', 'No Honors'),
    ('With_Honors', 'With Honors'),
    ('With_High_Honors', 'With High Honors'),
    ('With_Highest_Honors', 'With Highest Honors'),
]


# =============================================================================
# 8.1 — PromotionRecommendation
# =============================================================================
class PromotionRecommendation(models.Model):
    enrollment = models.OneToOneField(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='promotion_recommendation',
        help_text='The enrollment record this promotion decision applies to.',
    )
    recommendation = models.CharField(
        max_length=25,
        choices=RECOMMENDATION_CHOICES,
        help_text="Adviser's initial promotion recommendation.",
    )
    recommended_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='promotion_recommendations_made',
        help_text='Class adviser who made the recommendation.',
    )
    recommendation_date = models.DateField(null=True, blank=True)
    total_subjects = models.PositiveSmallIntegerField(
        default=0,
        help_text='Total subjects taken this school year.',
    )
    subjects_passed = models.PositiveSmallIntegerField(default=0)
    subjects_failed = models.PositiveSmallIntegerField(default=0)
    failed_subjects_list = models.TextField(
        blank=True,
        help_text="Names of failed subjects, e.g., 'Mathematics 10, Science 10'.",
    )
    general_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Final General Average from FinalGrade.',
    )
    remedial_required = models.BooleanField(
        default=False,
        help_text='True if conditionally promoted — must pass remedial classes.',
    )
    remedial_subjects = models.TextField(
        blank=True,
        help_text='Subjects the student must take remedial classes for.',
    )
    remedial_deadline = models.DateField(
        null=True,
        blank=True,
        help_text='Deadline to complete remedial classes (typically before next SY starts).',
    )
    remedial_completed = models.BooleanField(
        default=False,
        help_text='Did the student pass the remedial classes?',
    )
    remedial_completed_date = models.DateField(null=True, blank=True)
    final_decision = models.CharField(
        max_length=25,
        choices=RECOMMENDATION_CHOICES,
        null=True,
        blank=True,
        help_text='Final decision after review and remedial results. Set by Registrar. Overrides initial recommendation if different.',
    )
    status = models.CharField(
        max_length=20,
        choices=RECOMMENDATION_STATUS_CHOICES,
        default='Draft',
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promotion_recommendations_reviewed',
        help_text='Registrar who reviewed the recommendation.',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(
        blank=True,
        help_text="Registrar's notes during review.",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='promotion_recommendations_approved',
        help_text='School Head who gave final approval.',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sf10_updated = models.BooleanField(
        default=False,
        help_text='Has the SF10 permanent record been updated with this promotion decision?',
    )
    sf10_updated_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['enrollment__student__last_name']
        indexes = [
            models.Index(fields=['recommendation']),
            models.Index(fields=['final_decision']),
            models.Index(fields=['status']),
            models.Index(fields=['remedial_required']),
        ]
        verbose_name = 'Promotion Recommendation'
        verbose_name_plural = 'Promotion Recommendations'

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
    def grade_level(self):
        return self.enrollment.section.grade_level

    @property
    def school_year(self):
        return self.enrollment.school_year

    @property
    def next_grade_level(self):
        from academics.models import GradeLevel
        effective = self.effective_decision
        if effective in ('Promoted', 'Conditionally_Promoted'):
            next_number = self.grade_level.grade_number + 1
            return GradeLevel.objects.filter(grade_number=next_number).first()
        return self.grade_level

    @property
    def effective_decision(self):
        return self.final_decision or self.recommendation

    def clean(self):
        if self.remedial_required and not self.remedial_subjects:
            raise ValidationError({
                'remedial_subjects': 'Remedial subjects must be listed when remedial is required.',
            })
        if self.remedial_completed and not self.remedial_completed_date:
            raise ValidationError({
                'remedial_completed_date': 'Completion date is required when remedial is marked completed.',
            })
        if self.final_decision and self.status not in ['Reviewed', 'Approved', 'Finalized']:
            raise ValidationError({
                'status': 'Status must be at least "Reviewed" when a final decision is set.',
            })
        if self.status == 'Finalized' and not self.final_decision:
            raise ValidationError({
                'final_decision': 'Final decision is required when status is "Finalized".',
            })

    def __str__(self):
        return (
            f"{self.enrollment.student.lrn} — {self.get_effective_decision()} "
            f"({self.school_year.year_label})"
        )


# =============================================================================
# 8.2 — RetentionRecord
# =============================================================================
class RetentionRecord(models.Model):
    enrollment = models.OneToOneField(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='retention_record',
        help_text='The enrollment for the school year the student is being retained.',
    )
    reason = models.CharField(
        max_length=25,
        choices=RETENTION_REASON_CHOICES,
        help_text='Primary reason for retention.',
    )
    reason_details = models.TextField(
        blank=True,
        help_text='Detailed explanation of why the student is being retained.',
    )
    retained_grade_level = models.ForeignKey(
        'academics.GradeLevel',
        on_delete=models.PROTECT,
        related_name='retained_students',
        help_text='Grade level the student will repeat (same as current grade level).',
    )
    next_school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.PROTECT,
        related_name='retained_students',
        help_text='School year the student will repeat the grade level.',
    )
    intervention_attempted = models.BooleanField(
        default=False,
        help_text='Were interventions attempted before retention? (Tutoring, counseling, parent conference, home visit).',
    )
    intervention_details = models.TextField(
        blank=True,
        help_text='Description of interventions attempted and their outcomes.',
    )
    parent_notified = models.BooleanField(
        default=False,
        help_text='Was the parent/guardian formally notified of the retention decision?',
    )
    parent_notification_date = models.DateField(null=True, blank=True)
    parent_response = models.TextField(
        blank=True,
        help_text="Parent/guardian's acknowledgment or response to the retention.",
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_retentions',
        help_text='School Head who approved the retention.',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recorded_retentions',
        help_text='Registrar who recorded this retention.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['enrollment__student__last_name']
        indexes = [
            models.Index(fields=['reason']),
            models.Index(fields=['next_school_year']),
        ]
        verbose_name = 'Retention Record'
        verbose_name_plural = 'Retention Records'

    @property
    def student(self):
        return self.enrollment.student

    @property
    def student_name(self):
        return self.enrollment.student.full_name

    @property
    def lrn(self):
        return self.enrollment.student.lrn

    def clean(self):
        try:
            rec = self.enrollment.promotion_recommendation
            if rec.effective_decision != 'Retained':
                raise ValidationError({
                    'enrollment': 'Retention record can only be created for students whose promotion decision is "Retained".',
                })
        except PromotionRecommendation.DoesNotExist:
            raise ValidationError({
                'enrollment': 'A PromotionRecommendation must exist before creating a RetentionRecord.',
            })
        if self.next_school_year and self.enrollment.school_year:
            if self.next_school_year.year_start != self.enrollment.school_year.year_end:
                raise ValidationError({
                    'next_school_year': 'The next school year must immediately follow the current school year.',
                })
        if self.retained_grade_level and self.enrollment.section:
            if self.retained_grade_level != self.enrollment.section.grade_level:
                raise ValidationError({
                    'retained_grade_level': 'The retained grade level must match the student\'s current grade level.',
                })
        if self.parent_notified and not self.parent_notification_date:
            raise ValidationError({
                'parent_notification_date': 'Notification date is required when parent has been notified.',
            })

    def __str__(self):
        return (
            f"Retained: {self.enrollment.student.lrn} — {self.get_reason_display()} — "
            f"Repeating {self.retained_grade_level.grade_name} ({self.next_school_year.year_label})"
        )


# =============================================================================
# 8.3 — GraduationRecord
# =============================================================================
class GraduationRecord(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='graduation_records',
        help_text='The student who graduated/completed.',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.PROTECT,
        related_name='graduation_records',
        help_text='School year of graduation.',
    )
    grade_level_completed = models.ForeignKey(
        'academics.GradeLevel',
        on_delete=models.PROTECT,
        related_name='graduation_records',
        help_text='Grade level completed: Grade 10 (JHS Completion) or Grade 12 (SHS Graduation).',
    )
    graduation_date = models.DateField(
        help_text='Date of the graduation/recognition ceremony.',
    )
    graduation_type = models.CharField(
        max_length=20,
        choices=GRADUATION_TYPE_CHOICES,
        db_index=True,
        help_text='JHS Completion or SHS Graduation.',
    )
    diploma_number = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text='Unique diploma/certificate serial number.',
    )
    honors_at_graduation = models.CharField(
        max_length=30,
        blank=True,
        choices=GRADUATION_HONORS_CHOICES,
        help_text='Honors earned at graduation.',
    )
    general_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Final General Average used for honors determination.',
    )
    strand_completed = models.ForeignKey(
        'academics.Strand',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='graduation_records',
        help_text='Strand completed — SHS only.',
    )
    track_completed = models.ForeignKey(
        'academics.Track',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='graduation_records',
        help_text='Track completed — SHS only.',
    )
    certificate_issued = models.BooleanField(
        default=False,
        help_text='Has the diploma/certificate been issued to the student?',
    )
    certificate_issued_date = models.DateField(null=True, blank=True)
    certificate_file = models.FileField(
        upload_to='promotion/graduation/certificates/%Y/',
        null=True,
        blank=True,
        help_text='Scanned copy of the issued certificate.',
    )
    is_verified = models.BooleanField(
        default=False,
        help_text='Graduation verified by Registrar and School Head.',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_graduations',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    sf10_updated = models.BooleanField(
        default=False,
        help_text='Has SF10 (Form 137) been updated with this graduation information?',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-graduation_date', 'student__last_name']
        indexes = [
            models.Index(fields=['graduation_type']),
            models.Index(fields=['graduation_date']),
            models.Index(fields=['diploma_number']),
        ]
        verbose_name = 'Graduation Record'
        verbose_name_plural = 'Graduation Records'

    @property
    def student_name(self):
        return self.student.full_name

    @property
    def lrn(self):
        return self.student.lrn

    @property
    def is_jhs_completion(self):
        return self.graduation_type == 'JHS_Completion'

    @property
    def is_shs_graduation(self):
        return self.graduation_type == 'SHS_Graduation'

    def clean(self):
        if self.grade_level_completed:
            grade_num = self.grade_level_completed.grade_number
            if grade_num == 10 and self.graduation_type != 'JHS_Completion':
                raise ValidationError({
                    'graduation_type': 'Grade 10 completion must use "JHS_Completion" graduation type.',
                })
            if grade_num == 12 and self.graduation_type != 'SHS_Graduation':
                raise ValidationError({
                    'graduation_type': 'Grade 12 graduation must use "SHS_Graduation" graduation type.',
                })
            if grade_num not in [10, 12]:
                raise ValidationError({
                    'grade_level_completed': 'Graduation is only applicable for Grade 10 (JHS Completion) and Grade 12 (SHS Graduation).',
                })
        if self.honors_at_graduation and self.general_average is not None:
            ga = float(self.general_average)
            if self.honors_at_graduation == 'With_Honors' and (ga < 90 or ga >= 95):
                raise ValidationError({
                    'general_average': 'With Honors requires GA between 90.00 and 94.99.',
                })
            if self.honors_at_graduation == 'With_High_Honors' and (ga < 95 or ga >= 98):
                raise ValidationError({
                    'general_average': 'With High Honors requires GA between 95.00 and 97.99.',
                })
            if self.honors_at_graduation == 'With_Highest_Honors' and (ga < 98 or ga > 100):
                raise ValidationError({
                    'general_average': 'With Highest Honors requires GA between 98.00 and 100.00.',
                })

    def __str__(self):
        base = (
            f"{self.student.lrn} — {self.get_graduation_type_display()} — {self.graduation_date}"
        )
        if self.honors_at_graduation:
            base += f" — {self.get_honors_at_graduation_display()}"
        return base