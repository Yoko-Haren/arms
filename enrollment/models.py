# enrollment/models.py
"""
Phase 4: Enrollment models for Formify LIS.
The pivotal link between students and academic structure.
"""

from builtins import getattr, property, super

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
ENROLLMENT_STATUS_CHOICES = [
    ('Enrolled', 'Enrolled — Currently active'),
    ('Transferred_In', 'Transferred In — Recently moved in'),
    ('Transferred_Out', 'Transferred Out — Moved to another school'),
    ('Graduated', 'Graduated — Completed the grade level'),
    ('Dropped', 'Dropped — Officially dropped out'),
    ('Inactive', 'Inactive — Not currently attending'),
    ('Deceased', 'Deceased — Learner has passed away'),
]

ENROLLMENT_TYPE_CHOICES = [
    ('New', 'New Enrollee — First time in this school'),
    ('Continuing', 'Continuing — Previously enrolled last SY'),
    ('Transferred_In', 'Transferred In — From another school'),
    ('Balik_Aral', 'Balik-Aral — Returning after dropping out'),
    ('ALS_Passer', 'ALS Passer — Alternative Learning System completer'),
]

VOUCHER_PROGRAM_CHOICES = [
    ('', 'None'),
    ('SHS_VP', 'SHS Voucher Program'),
    ('ESC', 'Educational Service Contracting'),
    ('QVR', 'Qualified Voucher Recipient'),
    ('EVP', 'Education Voucher Program'),
]


# =============================================================================
# 4.1 — Enrollment
# =============================================================================
class Enrollment(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.CASCADE,
        related_name='enrollments',
    )
    section = models.ForeignKey(
        'academics.Section',
        on_delete=models.CASCADE,
        related_name='enrollments',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='enrollments',
    )
    grade_level_at_entry = models.ForeignKey(
        'academics.GradeLevel',
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='enrollments_at_this_level',
        help_text='Auto-set from section.grade_level in save().',
    )
    enrollment_date = models.DateField(default=timezone.now)
    enrollment_type = models.CharField(
        max_length=25,
        choices=ENROLLMENT_TYPE_CHOICES,
        db_index=True,
    )
    status = models.CharField(
        max_length=25,
        choices=ENROLLMENT_STATUS_CHOICES,
        default='Enrolled',
        db_index=True,
    )
    status_date = models.DateField(null=True, blank=True)
    previous_school_name = models.CharField(max_length=255, blank=True)
    previous_school_beis_id = models.CharField(max_length=20, blank=True)
    previous_school_address = models.CharField(max_length=255, blank=True)
    is_balik_aral = models.BooleanField(default=False)
    years_out_of_school = models.PositiveSmallIntegerField(null=True, blank=True)
    is_4ps = models.BooleanField(default=False)
    esc_grantee = models.BooleanField(default=False)
    voucher_program = models.CharField(
        max_length=50,
        blank=True,
        choices=VOUCHER_PROGRAM_CHOICES,
    )
    voucher_number = models.CharField(max_length=50, blank=True)
    remarks = models.TextField(blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='created_enrollments'
    )
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='updated_enrollments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['student', 'school_year']]
        ordering = ['school_year', 'section__grade_level__sort_order', 'student__last_name']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['school_year', 'status']),
            models.Index(fields=['student', 'school_year']),
        ]
        verbose_name = 'Enrollment'
        verbose_name_plural = 'Enrollments'

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._old_status = self.status if self.pk else None

    @property
    def student_name(self):
        return self.student.full_name

    @property
    def lrn(self):
        return self.student.lrn

    @property
    def grade_name(self):
        return self.section.grade_level.grade_name

    @property
    def section_name(self):
        return self.section.section_name

    def clean(self):
        if self.section_id and self.school_year_id:
            if self.section.school_year != self.school_year:
                raise ValidationError({
                    'section': 'The selected section does not belong to the chosen school year.',
                })
        if self.student_id and self.school_year_id:
            existing = Enrollment.objects.filter(
                student=self.student,
                school_year=self.school_year,
            )
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({
                    'student': 'This student already has an enrollment record for this school year.',
                })

    def save(self, *args, **kwargs):
        is_new = self.pk is None

        # Auto-set grade_level_at_entry from section
        if self.section_id and not self.grade_level_at_entry_id:
            self.grade_level_at_entry = self.section.grade_level

        # Track status changes
        if not is_new and self.status != self._old_status:
            self.status_date = timezone.now().date()
            old_status = self._old_status
            super().save(*args, **kwargs)
            EnrollmentHistory.objects.create(
                enrollment=self,
                previous_status=old_status,
                new_status=self.status,
                changed_by=getattr(self, '_changed_by', None),
                reason=getattr(self, '_status_change_reason', ''),
            )
            self._update_section_enrollment_count()
            self._old_status = self.status
            return

        super().save(*args, **kwargs)
        self._update_section_enrollment_count()
        self._old_status = self.status

    def set_status(self, new_status, changed_by=None, reason=''):
        self._changed_by = changed_by
        self._status_change_reason = reason
        self.status = new_status
        self.save()

    def _update_section_enrollment_count(self):
        from academics.models import Section
        count = Enrollment.objects.filter(
            section=self.section,
            status__in=['Enrolled', 'Transferred_In'],
        ).count()
        Section.objects.filter(pk=self.section_id).update(current_enrollment_count=count)

    def __str__(self):
        return f"{self.student.lrn} — {self.section} ({self.school_year.year_label}) — {self.get_status_display()}"


# =============================================================================
# 4.2 — EnrollmentHistory
# =============================================================================
class EnrollmentHistory(models.Model):
    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name='status_history',
    )
    previous_status = models.CharField(
        max_length=25,
        null=True,
        blank=True,
        choices=ENROLLMENT_STATUS_CHOICES,
    )
    new_status = models.CharField(
        max_length=25,
        choices=ENROLLMENT_STATUS_CHOICES,
    )
    change_date = models.DateTimeField(default=timezone.now, db_index=True)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='enrollment_status_changes',
    )
    reason = models.TextField(blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['enrollment', '-change_date']
        verbose_name = 'Enrollment History Record'
        verbose_name_plural = 'Enrollment History Records'
        default_permissions = ('view',)

    def __str__(self):
        prev = self.previous_status or 'None'
        return f"Enrollment #{self.enrollment_id}: {prev} → {self.new_status}"


# =============================================================================
# 4.3 — EnrollmentDocument
# =============================================================================
class EnrollmentDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('PSA_Birth_Certificate', 'PSA Birth Certificate'),
        ('SF9_Previous', 'SF9 — Previous Report Card'),
        ('SF10_Form137', 'SF10 — Form 137'),
        ('Good_Moral', 'Certificate of Good Moral Character'),
        ('Medical_Certificate', 'Medical Certificate'),
        ('Barangay_Clearance', 'Barangay Clearance'),
        ('ID_Photo', 'ID Photo'),
        ('ESC_Certificate', 'ESC Certificate'),
        ('Immunization_Record', 'Immunization Record'),
        ('Other', 'Other'),
    ]

    enrollment = models.ForeignKey(
        Enrollment,
        on_delete=models.CASCADE,
        related_name='enrollment_documents',
    )
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    is_submitted = models.BooleanField(default=False)
    submission_date = models.DateField(null=True, blank=True)
    file = models.FileField(
        upload_to='enrollment/documents/%Y/%m/%d/',
        null=True,
        blank=True,
    )
    file_name = models.CharField(max_length=255, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_enrollment_docs',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['enrollment', 'document_type']]
        ordering = ['enrollment', 'document_type']
        verbose_name = 'Enrollment Document'
        verbose_name_plural = 'Enrollment Documents'

    def __str__(self):
        return f"Enrollment #{self.enrollment_id} — {self.get_document_type_display()}"


# =============================================================================
# 4.4 — BalikAralDetails
# =============================================================================
class BalikAralDetails(models.Model):
    LEARNING_MODALITY_CHOICES = [
        ('Face_to_Face', 'Face-to-Face'),
        ('Blended', 'Blended Learning'),
        ('Modular_Print', 'Modular (Print)'),
        ('Modular_Digital', 'Modular (Digital)'),
        ('Online', 'Online Distance Learning'),
        ('Homeschooling', 'Homeschooling'),
        ('ALS', 'Alternative Learning System'),
    ]

    enrollment = models.OneToOneField(
        Enrollment,
        on_delete=models.CASCADE,
        related_name='balik_aral_details',
    )
    last_school_year_attended = models.CharField(max_length=9, blank=True)
    last_grade_level_completed = models.CharField(max_length=50, blank=True)
    last_school_attended_name = models.CharField(max_length=255, blank=True)
    reason_for_leaving = models.TextField(blank=True)
    years_out_of_school = models.PositiveSmallIntegerField(null=True, blank=True)
    assessment_test_date = models.DateField(null=True, blank=True)
    assessment_test_score = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    recommended_grade_level = models.ForeignKey(
        'academics.GradeLevel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='recommended_balik_aral',
    )
    interview_conducted_by = models.CharField(max_length=255, blank=True)
    interview_date = models.DateField(null=True, blank=True)
    interview_notes = models.TextField(blank=True)
    learning_modality_preference = models.CharField(
        max_length=50,
        blank=True,
        choices=LEARNING_MODALITY_CHOICES,
    )
    support_services_needed = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Balik-Aral Details'
        verbose_name_plural = 'Balik-Aral Details'

    def clean(self):
        if self.enrollment_id and self.enrollment.enrollment_type != 'Balik_Aral':
            raise ValidationError({
                'enrollment': 'Balik-Aral details can only be attached to enrollments of type "Balik-Aral".',
            })

    def __str__(self):
        return f"Balik-Aral: {self.enrollment.student.lrn} ({self.enrollment.school_year.year_label})"


# =============================================================================
# 4.5 — DroppedStudentDetails
# =============================================================================
class DroppedStudentDetails(models.Model):
    DROPOUT_REASON_CHOICES = [
        ('Financial', 'Financial Difficulty'),
        ('Employment', 'Found Employment'),
        ('Family_Responsibility', 'Family Responsibility / Caregiving'),
        ('Health', 'Health Reasons'),
        ('Distance', 'Distance / Accessibility of School'),
        ('Academic_Difficulty', 'Academic Difficulty'),
        ('Disinterest', 'Lack of Interest / Motivation'),
        ('Bullying', 'Bullying / Peer Issues'),
        ('Early_Marriage', 'Early Marriage / Pregnancy'),
        ('Relocation', 'Family Relocation'),
        ('Discipline', 'Disciplinary Action / Expulsion'),
        ('Natural_Disaster', 'Natural Disaster / Calamity'),
        ('Conflict', 'Armed Conflict / Insurgency'),
        ('Death', 'Death of Learner'),
        ('Other', 'Other'),
    ]

    INTERVENTION_TYPE_CHOICES = [
        ('Home_Visit', 'Home Visit'),
        ('Parent_Conference', 'Parent-Teacher Conference'),
        ('Counseling', 'Guidance Counseling'),
        ('Remedial', 'Remedial Classes'),
        ('Financial_Assistance', 'Financial Assistance Referral'),
        ('Barangay_Referral', 'Barangay Referral'),
        ('Multiple', 'Multiple Interventions'),
    ]

    enrollment = models.OneToOneField(
        Enrollment,
        on_delete=models.CASCADE,
        related_name='dropped_details',
    )
    dropout_date = models.DateField()
    dropout_reason = models.CharField(max_length=50, choices=DROPOUT_REASON_CHOICES)
    reason_details = models.TextField(blank=True)
    last_attendance_date = models.DateField(null=True, blank=True)
    intervention_attempted = models.BooleanField(default=False)
    intervention_type = models.CharField(
        max_length=50,
        blank=True,
        choices=INTERVENTION_TYPE_CHOICES,
    )
    intervention_date = models.DateField(null=True, blank=True)
    intervention_outcome = models.TextField(blank=True)
    guardian_notified = models.BooleanField(default=False)
    guardian_notification_date = models.DateField(null=True, blank=True)
    guardian_response = models.TextField(blank=True)
    is_reported_to_division = models.BooleanField(default=False)
    division_report_date = models.DateField(null=True, blank=True)
    expected_return_sy = models.CharField(
        max_length=9,
        blank=True,
        help_text="School year the student is expected to return, e.g., '2026-2027'.",
    )
    recorded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='recorded_dropouts',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_dropouts',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Dropped Student Details'
        verbose_name_plural = 'Dropped Student Details'
        indexes = [
            models.Index(fields=['dropout_reason']),
            models.Index(fields=['dropout_date']),
        ]

    def clean(self):
        if self.enrollment_id and self.enrollment.status != 'Dropped':
            raise ValidationError({
                'enrollment': 'Dropped student details can only be attached to enrollments with status "Dropped".',
            })

    def __str__(self):
        return f"Dropped: {self.enrollment.student.lrn} — {self.get_dropout_reason_display()} ({self.dropout_date})"