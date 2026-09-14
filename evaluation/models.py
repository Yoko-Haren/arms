# evaluation/models.py
"""
Phase 12: Teacher Evaluation (RPMS) models for Formify LIS.
Classroom observations with per-criteria scoring on 1-5 scale,
self-assessments, supervisor assessments, peer reviews, and IPCRF
record management with three-signature workflow.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
EVALUATION_TYPE_CHOICES = [
    ('Classroom_Observation', 'Classroom Observation'),
    ('Self_Assessment', 'Self-Assessment'),
    ('Supervisor_Assessment', 'Supervisor Assessment'),
    ('Peer_Review', 'Peer Review'),
]

ADJECTIVAL_RATING_CHOICES = [
    ('Outstanding', 'Outstanding (4.50-5.00)'),
    ('Very_Satisfactory', 'Very Satisfactory (3.50-4.49)'),
    ('Satisfactory', 'Satisfactory (2.50-3.49)'),
    ('Unsatisfactory', 'Unsatisfactory (1.50-2.49)'),
    ('Poor', 'Poor (Below 1.50)'),
]

EVALUATION_STATUS_CHOICES = [
    ('Draft', 'Draft'),
    ('Submitted', 'Submitted by Evaluator'),
    ('Acknowledged', 'Acknowledged by Teacher'),
    ('Finalized', 'Finalized'),
]

QUALITY_OF_EVIDENCE_CHOICES = [
    ('Very_Evident', 'Very Evident'),
    ('Evident', 'Evident'),
    ('Somewhat_Evident', 'Somewhat Evident'),
    ('Not_Evident', 'Not Evident'),
]

IPCRF_STATUS_CHOICES = [
    ('Draft', 'Draft'),
    ('Signed_by_Teacher', 'Signed by Teacher'),
    ('Signed_by_Rater', 'Signed by Rater'),
    ('Signed_by_Approving_Authority', 'Signed by Approving Authority'),
    ('Finalized', 'Finalized'),
]


# =============================================================================
# 12.1 — TeacherEvaluation
# =============================================================================
class TeacherEvaluation(models.Model):
    rpms_cycle = models.ForeignKey(
        'academics.RpmsCycle',
        on_delete=models.PROTECT,
        related_name='evaluations',
    )
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='evaluations_as_teacher',
    )
    evaluator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='evaluations_as_evaluator',
    )
    evaluation_type = models.CharField(
        max_length=30,
        choices=EVALUATION_TYPE_CHOICES,
        db_index=True,
    )
    observation_date = models.DateField(null=True, blank=True)
    time_in = models.TimeField(null=True, blank=True)
    time_out = models.TimeField(null=True, blank=True)
    subject_observed = models.ForeignKey(
        'academics.Subject',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evaluations',
    )
    section_observed = models.ForeignKey(
        'academics.Section',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evaluations',
    )
    overall_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Overall numerical rating (1.00-5.00 scale).',
    )
    adjectival_rating = models.CharField(
        max_length=30,
        blank=True,
        choices=ADJECTIVAL_RATING_CHOICES,
    )
    strengths = models.TextField(blank=True)
    areas_for_improvement = models.TextField(blank=True)
    teacher_comments = models.TextField(blank=True)
    attachment = models.FileField(
        upload_to='evaluation/attachments/%Y/%m/',
        null=True,
        blank=True,
    )
    attachment_name = models.CharField(max_length=255, blank=True)
    status = models.CharField(
        max_length=20,
        choices=EVALUATION_STATUS_CHOICES,
        default='Draft',
        db_index=True,
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    acknowledged_at = models.DateTimeField(null=True, blank=True)
    finalized_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-observation_date', 'teacher__last_name']
        indexes = [
            models.Index(fields=['teacher', 'rpms_cycle']),
            models.Index(fields=['evaluator', 'rpms_cycle']),
            models.Index(fields=['status']),
        ]
        verbose_name = 'Teacher Evaluation'
        verbose_name_plural = 'Teacher Evaluations'

    @property
    def teacher_name(self):
        return self.teacher.get_full_name() or self.teacher.username

    @property
    def evaluator_name(self):
        return self.evaluator.get_full_name() or self.evaluator.username

    @property
    def cycle_name(self):
        return self.rpms_cycle.cycle_label

    def clean(self):
        if self.teacher == self.evaluator:
            raise ValidationError({
                'evaluator': 'The evaluator cannot be the same person as the teacher.',
            })
        if self.status == 'Submitted' and not self.submitted_at:
            raise ValidationError({
                'submitted_at': 'Submission timestamp is required when status is "Submitted".',
            })
        if self.status == 'Acknowledged' and not self.acknowledged_at:
            raise ValidationError({
                'acknowledged_at': 'Acknowledgment timestamp is required when status is "Acknowledged".',
            })
        if self.status == 'Finalized' and not self.finalized_at:
            raise ValidationError({
                'finalized_at': 'Finalization timestamp is required when status is "Finalized".',
            })

    def __str__(self):
        return (
            f"Eval: {self.teacher.get_full_name()} — {self.get_evaluation_type_display()} "
            f"({self.observation_date or 'N/A'}) — {self.get_status_display()}"
        )


# =============================================================================
# 12.2 — EvaluationCriterion
# =============================================================================
class EvaluationCriterion(models.Model):
    evaluation = models.ForeignKey(
        TeacherEvaluation,
        on_delete=models.CASCADE,
        related_name='criteria',
    )
    criteria_template = models.ForeignKey(
        'accounts.RpmsCriteriaTemplate',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evaluation_criteria',
    )
    kra_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(5)],
    )
    objective_number = models.PositiveSmallIntegerField()
    indicator_name = models.CharField(max_length=255)
    score = models.DecimalField(
        max_digits=3,
        decimal_places=2,
        validators=[MinValueValidator(1.00), MaxValueValidator(5.00)],
    )
    quality_of_evidence = models.CharField(
        max_length=25,
        blank=True,
        choices=QUALITY_OF_EVIDENCE_CHOICES,
    )
    means_of_verification = models.TextField(blank=True)
    comments = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['evaluation', 'kra_number', 'objective_number']
        verbose_name = 'Evaluation Criterion'
        verbose_name_plural = 'Evaluation Criteria'

    def __str__(self):
        return f"KRA {self.kra_number}.{self.objective_number} — Score: {self.score} — Eval #{self.evaluation_id}"


# =============================================================================
# 12.3 — IpcrfRecord
# =============================================================================
class IpcrfRecord(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='ipcrf_records',
    )
    rpms_cycle = models.ForeignKey(
        'academics.RpmsCycle',
        on_delete=models.PROTECT,
        related_name='ipcrf_records',
    )
    final_overall_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
    )
    adjectival_rating = models.CharField(
        max_length=30,
        blank=True,
        choices=ADJECTIVAL_RATING_CHOICES,
    )
    file = models.FileField(
        upload_to='evaluation/ipcrf/%Y/',
        null=True,
        blank=True,
    )
    status = models.CharField(
        max_length=30,
        choices=IPCRF_STATUS_CHOICES,
        default='Draft',
        db_index=True,
    )
    teacher_signed_at = models.DateTimeField(null=True, blank=True)
    rater_signed_at = models.DateTimeField(null=True, blank=True)
    approving_authority_signed_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['teacher', 'rpms_cycle']]
        ordering = ['-rpms_cycle__school_year__year_start', 'teacher__last_name']
        verbose_name = 'IPCRF Record'
        verbose_name_plural = 'IPCRF Records'

    @property
    def teacher_name(self):
        return self.teacher.get_full_name() or self.teacher.username

    @property
    def cycle_name(self):
        return self.rpms_cycle.cycle_label

    @property
    def is_fully_signed(self):
        return self.status == 'Finalized'

    def clean(self):
        status_order = ['Draft', 'Signed_by_Teacher', 'Signed_by_Rater',
                        'Signed_by_Approving_Authority', 'Finalized']
        current_index = status_order.index(self.status) if self.status in status_order else 0

        if current_index >= status_order.index('Signed_by_Teacher') and not self.teacher_signed_at:
            raise ValidationError({
                'teacher_signed_at': 'Teacher signature timestamp is required for this status.',
            })
        if current_index >= status_order.index('Signed_by_Rater') and not self.rater_signed_at:
            raise ValidationError({
                'rater_signed_at': 'Rater signature timestamp is required for this status.',
            })
        if current_index >= status_order.index('Signed_by_Approving_Authority') and not self.approving_authority_signed_at:
            raise ValidationError({
                'approving_authority_signed_at': 'Approving authority signature timestamp is required for this status.',
            })

    def __str__(self):
        return f"IPCRF: {self.teacher.get_full_name()} — {self.rpms_cycle.cycle_name} — {self.get_status_display()}"