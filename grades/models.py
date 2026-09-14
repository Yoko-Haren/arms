# grades/models.py
"""
Phase 7: Grade Encoding models for Formify LIS.
DepEd Order 8, s. 2015 compliant grading with WW/PT/QA components,
transmutation, quarterly grades, final grades, honor records
(combined current + history), and immutable change logs.
"""

from builtins import getattr, round

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone

from accounts.models import GradeTransmutationTable, GradeComponentWeight


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
VALIDATION_STATUS_CHOICES = [
    ('Draft', 'Draft — Teacher still encoding'),
    ('Submitted', 'Submitted for Validation'),
    ('Validated', 'Validated by Registrar'),
    ('Returned', 'Returned for Correction'),
    ('Finalized', 'Finalized — Locked'),
]

GRADE_DESCRIPTOR_CHOICES = [
    ('Outstanding', 'Outstanding (90-100)'),
    ('Very_Satisfactory', 'Very Satisfactory (85-89)'),
    ('Satisfactory', 'Satisfactory (80-84)'),
    ('Fairly_Satisfactory', 'Fairly Satisfactory (75-79)'),
    ('Did_Not_Meet_Expectations', 'Did Not Meet Expectations (Below 75)'),
]

FINAL_GRADE_STATUS_CHOICES = [
    ('Passed', 'Passed (≥75)'),
    ('Failed', 'Failed (<75)'),
    ('Incomplete', 'Incomplete — Missing one or more quarters'),
]

HONOR_LEVEL_CHOICES = [
    ('With_Honors', 'With Honors (90-94)'),
    ('With_High_Honors', 'With High Honors (95-97)'),
    ('With_Highest_Honors', 'With Highest Honors (98-100)'),
]

AWARD_TYPE_CHOICES = [
    ('Quarterly', 'Quarterly Honors'),
    ('End_of_Year', 'End of School Year Honors'),
]

# Fields tracked for grade change audit
GRADE_AUDIT_FIELDS = [
    'written_work_raw', 'written_work_max',
    'performance_task_raw', 'performance_task_max',
    'quarterly_assessment_raw', 'quarterly_assessment_max',
    'transmuted_grade', 'initial_grade',
]


# =============================================================================
# 7.1 — GradeComponent
# =============================================================================
# grades/models.py (updated GradeComponent section only)

class GradeComponent(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='grade_components',
        help_text='The enrollment record for this school year.',
    )
    subject = models.ForeignKey(
        'academics.Subject',
        on_delete=models.PROTECT,
        related_name='grade_components',
        help_text='The subject being graded.',
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.PROTECT,
        related_name='grade_components',
        help_text='Grading quarter (Q1-Q4).',
    )
    semester = models.ForeignKey(
        'academics.Semester',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='grade_components',
        help_text='For SHS: the semester this grade belongs to. NULL for JHS year-long subjects.',
    )
    
    # --- GRADE COMPONENTS (REQUIRED - NO NULLS) ---
    written_work_raw = models.DecimalField(
        max_digits=6, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Sum of all written work scores (quizzes, long tests, essays, homework). Must be 0-100.',
    )
    written_work_max = models.DecimalField(
        max_digits=6, decimal_places=2,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Maximum possible written work total. Must be between 1-100.',
    )
    written_work_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
        help_text='(written_work_raw / written_work_max) * 100. Auto-computed.',
    )
    written_work_weighted = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
        help_text='written_work_percent * WW weight (e.g., 30% for JHS core). Auto-computed.',
    )
    
    performance_task_raw = models.DecimalField(
        max_digits=6, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Sum of all performance task scores (projects, presentations, lab work). Must be 0-100.',
    )
    performance_task_max = models.DecimalField(
        max_digits=6, decimal_places=2,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Maximum possible performance task total. Must be between 1-100.',
    )
    performance_task_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
    )
    performance_task_weighted = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
    )
    
    quarterly_assessment_raw = models.DecimalField(
        max_digits=6, decimal_places=2,
        validators=[MinValueValidator(0), MaxValueValidator(100)],
        help_text='Periodical examination score. Must be 0-100.',
    )
    quarterly_assessment_max = models.DecimalField(
        max_digits=6, decimal_places=2,
        validators=[MinValueValidator(1), MaxValueValidator(100)],
        help_text='Maximum possible quarterly assessment total. Must be between 1-100.',
    )
    quarterly_assessment_percent = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
    )
    quarterly_assessment_weighted = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
    )
    
    initial_grade = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True, editable=False,
        help_text='Sum of all three weighted scores. Auto-computed.',
    )
    transmuted_grade = models.PositiveSmallIntegerField(
        null=True, blank=True,
        help_text='Quarterly grade after applying DepEd transmutation table (60-100). Auto-computed.',
    )
    descriptor = models.CharField(
        max_length=30, blank=True, choices=GRADE_DESCRIPTOR_CHOICES,
        help_text='Grade descriptor per DepEd Order 8, s. 2015.',
    )
    
    # --- METADATA (REQUIRED FIELDS) ---
    encoded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,  # Changed from PROTECT to SET_NULL
        null=True,  # Keep null=True for now
        blank=True,
        related_name='encoded_grades',
        help_text='Subject teacher who encoded these grades.',
    )
    encoding_date = models.DateTimeField(auto_now_add=True)  # Auto-set, not null
    
    validation_status = models.CharField(
        max_length=20, choices=VALIDATION_STATUS_CHOICES,
        default='Draft', db_index=True,
    )
    validated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='validated_grades',
    )
    validation_date = models.DateTimeField(null=True, blank=True)
    validation_notes = models.TextField(
        blank=True,
        help_text="Registrar's notes during validation.",
    )
    is_locked = models.BooleanField(
        default=False, db_index=True,
    )
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='locked_grades',
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    remarks = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['enrollment', 'subject', 'quarter']]
        ordering = ['quarter', 'subject__subject_name']
        indexes = [
            models.Index(fields=['validation_status']),
            models.Index(fields=['enrollment', 'quarter']),
            models.Index(fields=['is_locked']),
        ]
        verbose_name = 'Grade Component'
        verbose_name_plural = 'Grade Components'

    def clean(self):
        """Validation that ensures all required fields are present."""
        
        # --- ENFORCE NO NULLS FOR REQUIRED GRADE FIELDS ---
        required_fields = [
            'written_work_raw', 'written_work_max',
            'performance_task_raw', 'performance_task_max',
            'quarterly_assessment_raw', 'quarterly_assessment_max'
        ]
        
        for field in required_fields:
            value = getattr(self, field)
            if value is None:
                raise ValidationError({
                    field: f'{field} cannot be null. All grade components must be filled.'
                })
            if value == '':
                raise ValidationError({
                    field: f'{field} cannot be empty. All grade components must be filled.'
                })
        
        # Ensure raw scores don't exceed max scores
        if self.written_work_raw > self.written_work_max:
            raise ValidationError({
                'written_work_raw': f'Raw score ({self.written_work_raw}) cannot exceed maximum ({self.written_work_max}).'
            })
        if self.performance_task_raw > self.performance_task_max:
            raise ValidationError({
                'performance_task_raw': f'Raw score ({self.performance_task_raw}) cannot exceed maximum ({self.performance_task_max}).'
            })
        if self.quarterly_assessment_raw > self.quarterly_assessment_max:
            raise ValidationError({
                'quarterly_assessment_raw': f'Raw score ({self.quarterly_assessment_raw}) cannot exceed maximum ({self.quarterly_assessment_max}).'
            })
        
        # Ensure max values are greater than 0
        if self.written_work_max <= 0:
            raise ValidationError({'written_work_max': 'Maximum value must be greater than 0.'})
        if self.performance_task_max <= 0:
            raise ValidationError({'performance_task_max': 'Maximum value must be greater than 0.'})
        if self.quarterly_assessment_max <= 0:
            raise ValidationError({'quarterly_assessment_max': 'Maximum value must be greater than 0.'})
        
        # Ensure encoded_by is set (no null)
        if self.encoded_by is None:
            raise ValidationError({
                'encoded_by': 'Teacher who encoded the grades must be specified.'
            })
        
        # Rest of your existing clean() validation...
        if self.validation_status == 'Finalized' and not self.is_locked:
            raise ValidationError({
                'is_locked': 'Grades must be locked when status is Finalized.',
            })
        
        if self.semester and self.enrollment and self.enrollment.section:
            if not self.enrollment.section.grade_level.is_senior_high:
                raise ValidationError({
                    'semester': 'Semester should not be set for Junior High School subjects.',
                })
        
        if self.transmuted_grade is not None:
            if self.transmuted_grade < 60 or self.transmuted_grade > 100:
                raise ValidationError({
                    'transmuted_grade': 'Transmuted grade must be between 60 and 100.',
                })
    
def save(self, *args, **kwargs):
    # Skip audit logging for bulk operations
    if getattr(self, '_skip_audit', False):
        super().save(*args, **kwargs)
        return

    # Skip validation for bulk operations
    if not getattr(self, '_skip_validation', False):
        self.full_clean()
    
    is_new = self.pk is None
    changed_by = getattr(self, '_changed_by', None)

    # --- AUDIT TRAIL (only if not skipping) ---
    if not is_new and not getattr(self, '_skip_audit', False):
        try:
            old_instance = GradeComponent.objects.get(pk=self.pk)
            for field in GRADE_AUDIT_FIELDS:
                old_val = getattr(old_instance, field)
                new_val = getattr(self, field)
                if old_val != new_val:
                    GradeChangeLog.objects.create(
                        grade_component=self,
                        field_changed=field,
                        old_value=str(old_val) if old_val is not None else None,
                        new_value=str(new_val) if new_val is not None else None,
                        changed_by=changed_by,
                    )
        except GradeComponent.DoesNotExist:
            pass

    # --- COMPUTE PERCENTAGES ---
    self.written_work_percent = round((self.written_work_raw / self.written_work_max) * 100, 2)
    self.performance_task_percent = round((self.performance_task_raw / self.performance_task_max) * 100, 2)
    self.quarterly_assessment_percent = round((self.quarterly_assessment_raw / self.quarterly_assessment_max) * 100, 2)

    # --- FETCH COMPONENT WEIGHTS ---
    ww_weight = 0.30
    pt_weight = 0.50
    qa_weight = 0.20

    if self.enrollment and self.enrollment.section:
        is_shs = self.enrollment.section.grade_level.is_senior_high
        grade_cat = 'SHS' if is_shs else 'JHS'
        subj_cat = self.subject.subject_category

        try:
            ww_row = GradeComponentWeight.objects.filter(
                grade_level_category=grade_cat,
                subject_category=subj_cat,
                component_type='Written_Work',
                is_active=True,
            ).first()
            pt_row = GradeComponentWeight.objects.filter(
                grade_level_category=grade_cat,
                subject_category=subj_cat,
                component_type='Performance_Task',
                is_active=True,
            ).first()
            qa_row = GradeComponentWeight.objects.filter(
                grade_level_category=grade_cat,
                subject_category=subj_cat,
                component_type='Quarterly_Assessment',
                is_active=True,
            ).first()
            
            if ww_row:
                ww_weight = float(ww_row.percentage_weight) / 100.0
            if pt_row:
                pt_weight = float(pt_row.percentage_weight) / 100.0
            if qa_row:
                qa_weight = float(qa_row.percentage_weight) / 100.0
        except Exception:
            pass

    # Apply weights
    self.written_work_weighted = round(float(self.written_work_percent) * ww_weight, 2)
    self.performance_task_weighted = round(float(self.performance_task_percent) * pt_weight, 2)
    self.quarterly_assessment_weighted = round(float(self.quarterly_assessment_percent) * qa_weight, 2)

    # --- COMPUTE INITIAL GRADE ---
    self.initial_grade = round(
        self.written_work_weighted + self.performance_task_weighted + self.quarterly_assessment_weighted, 2
    )

    # --- APPLY TRANSMUTATION ---
    if self.initial_grade is not None and self.enrollment and self.enrollment.section:
        is_shs = self.enrollment.section.grade_level.is_senior_high
        grade_cat = 'SHS' if is_shs else 'JHS'
        subj_cat = self.subject.subject_category

        transmuted = GradeTransmutationTable.objects.filter(
            grade_level_category__in=[grade_cat, 'All'],
            subject_category__in=[subj_cat, 'All'],
            initial_grade_min__lte=self.initial_grade,
            initial_grade_max__gte=self.initial_grade,
            is_active=True,
        ).order_by('grade_level_category', 'subject_category').first()

        if transmuted:
            self.transmuted_grade = int(transmuted.transmuted_grade)
            if self.transmuted_grade >= 90:
                self.descriptor = 'Outstanding'
            elif self.transmuted_grade >= 85:
                self.descriptor = 'Very_Satisfactory'
            elif self.transmuted_grade >= 80:
                self.descriptor = 'Satisfactory'
            elif self.transmuted_grade >= 75:
                self.descriptor = 'Fairly_Satisfactory'
            else:
                self.descriptor = 'Did_Not_Meet_Expectations'

    super().save(*args, **kwargs)


def __str__(self):
    return (
        f"{self.enrollment.student.lrn} — {self.subject.subject_code} — "
        f"{self.quarter.quarter_label}: {self.transmuted_grade or 'N/A'}"
    )

    
# =============================================================================
# 7.2 — GradeChangeLog
# =============================================================================
class GradeChangeLog(models.Model):
    grade_component = models.ForeignKey(
        GradeComponent,
        on_delete=models.CASCADE,
        related_name='change_logs',
    )
    field_changed = models.CharField(
        max_length=50,
        help_text="Name of the field that was modified: 'written_work_raw', 'transmuted_grade', etc.",
    )
    old_value = models.CharField(
        max_length=50, null=True, blank=True,
        help_text='Previous value as string. NULL if field was previously empty.',
    )
    new_value = models.CharField(
        max_length=50,
        help_text='New value as string.',
    )
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='grade_changes',
        help_text='User who made the change.',
    )
    change_reason = models.TextField(
        blank=True,
        help_text='Required for audit compliance — why was this grade changed?',
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['grade_component', '-created_at']
        indexes = [
            models.Index(fields=['grade_component', 'created_at']),
            models.Index(fields=['changed_by', 'created_at']),
        ]
        verbose_name = 'Grade Change Log'
        verbose_name_plural = 'Grade Change Logs'
        default_permissions = ('view',)

    def __str__(self):
        return (
            f"Change: {self.grade_component} — {self.field_changed}: "
            f"{self.old_value} → {self.new_value}"
        )


# =============================================================================
# 7.3 — QuarterlyGrade
# =============================================================================
class QuarterlyGrade(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='quarterly_grades',
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.PROTECT,
        related_name='quarterly_grades',
    )
    general_average = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Average of all transmuted subject grades for this quarter.',
    )
    total_subjects = models.PositiveSmallIntegerField(default=0)
    subjects_passed = models.PositiveSmallIntegerField(
        default=0,
        help_text='Subjects with transmuted grade ≥ 75.',
    )
    subjects_failed = models.PositiveSmallIntegerField(
        default=0,
        help_text='Subjects with transmuted grade < 75.',
    )
    has_failing_grade = models.BooleanField(
        default=False,
        help_text='True if any subject grade is below 75. Disqualifies from honors.',
    )
    has_grade_below_85 = models.BooleanField(
        default=False,
        help_text='True if any subject is below 85. Disqualifies from With High/Highest Honors.',
    )
    honor_eligible = models.BooleanField(
        default=False, db_index=True,
        help_text='Meets all criteria for quarterly honors per DepEd Order.',
    )
    honor_level = models.CharField(
        max_length=30, blank=True, choices=HONOR_LEVEL_CHOICES,
    )
    is_complete = models.BooleanField(
        default=False,
        help_text='All subject grades for this quarter have been submitted and validated.',
    )
    computed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['enrollment', 'quarter']]
        ordering = ['quarter', 'enrollment__student__last_name']
        indexes = [
            models.Index(fields=['honor_eligible']),
        ]
        verbose_name = 'Quarterly Grade'
        verbose_name_plural = 'Quarterly Grades'

    @property
    def student(self):
        return self.enrollment.student

    @property
    def student_name(self):
        return self.enrollment.student.full_name

    def __str__(self):
        base = f"{self.enrollment.student.lrn} — {self.quarter.quarter_label}: GA {self.general_average or 'N/A'}"
        if self.honor_eligible:
            base += f" — {self.get_honor_level_display()}"
        return base


# =============================================================================
# 7.4 — FinalGrade
# =============================================================================
class FinalGrade(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='final_grades',
    )
    subject = models.ForeignKey(
        'academics.Subject',
        on_delete=models.PROTECT,
        null=True, blank=True,
        related_name='final_grades',
        help_text='NULL if this is the General Average record. Set for per-subject final grades.',
    )
    q1_grade = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    q2_grade = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    q3_grade = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    q4_grade = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
    )
    final_grade = models.DecimalField(
        max_digits=5, decimal_places=2, null=True, blank=True,
        help_text='Average of all non-null quarter grades.',
    )
    status = models.CharField(
        max_length=20, choices=FINAL_GRADE_STATUS_CHOICES, null=True, blank=True,
    )
    is_general_average = models.BooleanField(
        default=False, db_index=True,
        help_text='True if this record is the General Average (subject=NULL). False if per-subject final grade.',
    )
    computed_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['enrollment', 'subject']]
        ordering = ['enrollment__student__last_name', 'subject__subject_name']
        indexes = [
            models.Index(fields=['is_general_average']),
            models.Index(fields=['status']),
        ]
        verbose_name = 'Final Grade'
        verbose_name_plural = 'Final Grades'

    @property
    def student(self):
        return self.enrollment.student

    @property
    def student_name(self):
        return self.enrollment.student.full_name

    def clean(self):
        if self.is_general_average and self.subject is not None:
            raise ValidationError({
                'subject': 'General Average record must have subject=NULL.',
            })
        if not self.is_general_average and self.subject is None:
            raise ValidationError({
                'subject': 'Per-subject final grade must have a subject set.',
            })
        # Auto-compute final grade from quarters
        grades = [self.q1_grade, self.q2_grade, self.q3_grade, self.q4_grade]
        valid = [g for g in grades if g is not None]
        if valid:
            self.final_grade = round(sum(valid) / len(valid), 2)
            if self.final_grade >= 75:
                self.status = 'Passed'
            elif len(valid) == 4:
                self.status = 'Failed'
            else:
                self.status = 'Incomplete'

    def __str__(self):
        label = self.subject.subject_name if self.subject else 'General Average'
        return (
            f"{self.enrollment.student.lrn} — {label}: "
            f"{self.final_grade or 'N/A'} — {self.get_status_display() or 'N/A'}"
        )


# =============================================================================
# 7.5 — HonorRecord
# =============================================================================
class HonorRecord(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.CASCADE,
        related_name='honor_records',
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='honor_records',
        help_text='NULL for End-of-School-Year honors. Set for Quarterly honors.',
    )
    award_type = models.CharField(
        max_length=20, choices=AWARD_TYPE_CHOICES, default='Quarterly', db_index=True,
    )
    honor_level = models.CharField(
        max_length=30, choices=HONOR_LEVEL_CHOICES, db_index=True,
    )
    general_average = models.DecimalField(
        max_digits=5, decimal_places=2,
        help_text='General average that qualified for this honor.',
    )
    awarded_date = models.DateField(default=timezone.now)
    certificate_generated = models.BooleanField(default=False)
    certificate_file = models.FileField(
        upload_to='grades/honors/certificates/%Y/', null=True, blank=True,
    )
    is_withdrawn = models.BooleanField(
        default=False, db_index=True,
        help_text='Was the honor later withdrawn? Record is kept for audit history.',
    )
    withdrawn_reason = models.TextField(
        blank=True,
        help_text='Reason for withdrawal: disciplinary action, grade correction, etc.',
    )
    withdrawn_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True, blank=True,
        related_name='withdrawn_honors',
    )
    withdrawn_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = [
            '-enrollment__school_year__year_start',
            'quarter__quarter_number',
            'enrollment__student__last_name',
        ]
        indexes = [
            models.Index(fields=['award_type']),
            models.Index(fields=['honor_level']),
            models.Index(fields=['is_withdrawn']),
        ]
        verbose_name = 'Honor Record'
        verbose_name_plural = 'Honor Records'

    @property
    def student(self):
        return self.enrollment.student

    @property
    def student_name(self):
        return self.enrollment.student.full_name

    @property
    def is_active(self):
        return not self.is_withdrawn

    def clean(self):
        if self.award_type == 'Quarterly' and not self.quarter:
            raise ValidationError({
                'quarter': 'Quarter is required for Quarterly honors.',
            })
        if self.award_type == 'End_of_Year' and self.quarter:
            raise ValidationError({
                'quarter': 'Quarter should be NULL for End-of-School-Year honors.',
            })
        # Validate GA range matches honor level
        ga = float(self.general_average) if self.general_average else 0
        if self.honor_level == 'With_Honors' and (ga < 90 or ga >= 95):
            raise ValidationError({
                'general_average': 'With Honors requires GA between 90.00 and 94.99.',
            })
        if self.honor_level == 'With_High_Honors' and (ga < 95 or ga >= 98):
            raise ValidationError({
                'general_average': 'With High Honors requires GA between 95.00 and 97.99.',
            })
        if self.honor_level == 'With_Highest_Honors' and (ga < 98 or ga > 100):
            raise ValidationError({
                'general_average': 'With Highest Honors requires GA between 98.00 and 100.00.',
            })
        # Prevent duplicate honors
        if self.award_type == 'Quarterly' and self.quarter:
            existing = HonorRecord.objects.filter(
                enrollment=self.enrollment,
                quarter=self.quarter,
                award_type='Quarterly',
                is_withdrawn=False,
            )
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError('A quarterly honor already exists for this student and quarter.')
        if self.award_type == 'End_of_Year':
            existing = HonorRecord.objects.filter(
                enrollment=self.enrollment,
                award_type='End_of_Year',
                is_withdrawn=False,
            )
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError('An end-of-year honor already exists for this student.')

    def __str__(self):
        base = (
            f"{self.enrollment.student.lrn} — {self.get_honor_level_display()} "
            f"({self.get_award_type_display()}) — GA: {self.general_average}"
        )
        if self.is_withdrawn:
            base += ' [WITHDRAWN]'
        return base