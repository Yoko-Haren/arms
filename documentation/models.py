# documentation/models.py || forms/models.py
"""
Phase 9: School Forms & Documentation models for Formify LIS.
Form submissions and compliance tracking (SF1-SF10), SF10 permanent
record history (Form 137-A), SF9 report card history, and document
request management with tracking and release workflow.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
from django.utils.crypto import get_random_string


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
SUBMISSION_STATUS_CHOICES = [
    ('Draft', 'Draft'),
    ('Submitted', 'Submitted'),
    ('Reviewed', 'Reviewed by Registrar'),
    ('Returned', 'Returned for Revision'),
    ('Approved', 'Approved'),
    ('Archived', 'Archived'),
]

COMPLIANCE_STATUS_CHOICES = [
    ('Not_Started', 'Not Started'),
    ('In_Progress', 'In Progress'),
    ('Completed', 'Completed'),
    ('Overdue', 'Overdue'),
]

SF10_REMARKS_CHOICES = [
    ('Promoted', 'Promoted'),
    ('Conditionally_Promoted', 'Conditionally Promoted'),
    ('Retained', 'Retained'),
    ('Transferred', 'Transferred'),
    ('Graduated', 'Graduated'),
]

DOCUMENT_REQUEST_STATUS_CHOICES = [
    ('Pending', 'Pending'),
    ('Processing', 'Processing'),
    ('Generated', 'Generated'),
    ('Released', 'Released'),
    ('Received', 'Received'),
    ('Cancelled', 'Cancelled'),
]

DOCUMENT_RELEASE_STATUS_CHOICES = [
    ('Unreleased', 'Unreleased'),
    ('Released', 'Released'),
    ('Claimed', 'Claimed by Requestor'),
    ('Returned', 'Returned Undelivered'),
]


# =============================================================================
# 9.1 — FormSubmission
# =============================================================================
class FormSubmission(models.Model):
    school_form = models.ForeignKey(
        'accounts.SchoolForm',
        on_delete=models.PROTECT,
        related_name='submissions',
    )
    section = models.ForeignKey(
        'academics.Section',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='form_submissions',
        help_text='NULL for school-wide forms.',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.PROTECT,
        related_name='form_submissions',
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='form_submissions',
        help_text='NULL for annual forms.',
    )
    submitted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='submitted_forms',
    )
    submitted_date = models.DateTimeField(null=True, blank=True)
    status = models.CharField(
        max_length=20,
        choices=SUBMISSION_STATUS_CHOICES,
        default='Draft',
        db_index=True,
    )
    file = models.FileField(
        upload_to='forms/submissions/%Y/%m/',
        null=True,
        blank=True,
    )
    file_name = models.CharField(max_length=255, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='reviewed_forms',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    is_locked = models.BooleanField(default=False)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school_form', 'section', 'school_year', 'quarter']]
        ordering = ['-school_year__year_start', 'school_form__form_code']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['school_year', 'school_form']),
        ]
        verbose_name = 'Form Submission'
        verbose_name_plural = 'Form Submissions'

    def clean(self):
        if self.quarter is None:
            existing = FormSubmission.objects.filter(
                school_form=self.school_form,
                section=self.section,
                school_year=self.school_year,
                quarter__isnull=True,
            )
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({
                    'quarter': 'An annual submission for this form, section, and school year already exists.',
                })

    def __str__(self):
        section_str = str(self.section) if self.section else 'School-wide'
        return (
            f"{self.school_form.form_code} — {section_str} — "
            f"{self.school_year.year_label} — {self.get_status_display()}"
        )


# =============================================================================
# 9.2 — FormCompliance
# =============================================================================
class FormCompliance(models.Model):
    school_form = models.ForeignKey(
        'accounts.SchoolForm',
        on_delete=models.PROTECT,
        related_name='compliance_records',
    )
    section = models.ForeignKey(
        'academics.Section',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='form_compliance_records',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.PROTECT,
        related_name='form_compliance_records',
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='form_compliance_records',
    )
    completion_percent = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
    )
    status = models.CharField(
        max_length=20,
        choices=COMPLIANCE_STATUS_CHOICES,
        default='Not_Started',
        db_index=True,
    )
    due_date = models.DateField(null=True, blank=True)
    last_updated = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['school_form', 'section', 'school_year', 'quarter']]
        ordering = ['school_year', 'school_form__form_code']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['due_date']),
        ]
        verbose_name = 'Form Compliance Record'
        verbose_name_plural = 'Form Compliance Records'

    def __str__(self):
        section_str = str(self.section) if self.section else 'All'
        return (
            f"{self.school_form.form_code} — {section_str} — "
            f"{self.get_status_display()} ({self.completion_percent}%)"
        )


# =============================================================================
# 9.3 — SF10History
# =============================================================================
class SF10History(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='sf10_history',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.PROTECT,
        related_name='sf10_records',
    )
    grade_level = models.ForeignKey(
        'academics.GradeLevel',
        on_delete=models.PROTECT,
        related_name='sf10_records',
    )
    section_name = models.CharField(max_length=100, blank=True)
    general_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    days_present = models.PositiveSmallIntegerField(null=True, blank=True)
    days_absent = models.PositiveSmallIntegerField(null=True, blank=True)
    remarks = models.CharField(
        max_length=25,
        blank=True,
        choices=SF10_REMARKS_CHOICES,
    )
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_sf10',
    )
    generated_date = models.DateTimeField(default=timezone.now)
    is_certified = models.BooleanField(default=False)
    certified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='certified_sf10',
    )
    certified_at = models.DateTimeField(null=True, blank=True)
    is_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_sf10',
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['student', 'school_year']]
        ordering = ['student__last_name', '-school_year__year_start']
        indexes = [
            models.Index(fields=['student', 'school_year']),
            models.Index(fields=['is_certified']),
            models.Index(fields=['remarks']),
        ]
        verbose_name = 'SF10 History (Form 137-A)'
        verbose_name_plural = 'SF10 History (Form 137-A)'

    @property
    def student_name(self):
        return self.student.full_name

    @property
    def lrn(self):
        return self.student.lrn

    def clean(self):
        if self.is_certified:
            if not self.certified_by:
                raise ValidationError({
                    'certified_by': 'Certifier is required when record is certified.',
                })
            if not self.certified_at:
                raise ValidationError({
                    'certified_at': 'Certification date is required when record is certified.',
                })
        if self.is_locked and not self.is_certified:
            raise ValidationError({
                'is_locked': 'Record must be certified before it can be locked.',
            })

    def __str__(self):
        return (
            f"SF10: {self.student.lrn} — {self.school_year.year_label} — "
            f"Grade {self.grade_level.grade_name} — {self.get_remarks_display() or 'N/A'}"
        )


# =============================================================================
# 9.4 — SF9History
# =============================================================================
class SF9History(models.Model):
    enrollment = models.ForeignKey(
        'enrollment.Enrollment',
        on_delete=models.PROTECT,
        related_name='sf9_history',
    )
    quarter = models.ForeignKey(
        'academics.Quarter',
        on_delete=models.PROTECT,
        related_name='sf9_records',
    )
    general_average = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
    )
    honors = models.CharField(max_length=50, blank=True)
    generated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='generated_sf9',
    )
    generated_date = models.DateTimeField(default=timezone.now)
    file = models.FileField(
        upload_to='forms/sf9/%Y/%m/',
        null=True,
        blank=True,
    )
    is_issued = models.BooleanField(default=False)
    issued_date = models.DateField(null=True, blank=True)
    issued_to = models.CharField(max_length=255, blank=True)
    parent_signature = models.ImageField(
        upload_to='forms/sf9/signatures/%Y/',
        null=True,
        blank=True,
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['enrollment', 'quarter']]
        ordering = ['enrollment__student__last_name', 'quarter__quarter_number']
        indexes = [
            models.Index(fields=['is_issued']),
        ]
        verbose_name = 'SF9 History (Report Card)'
        verbose_name_plural = 'SF9 History (Report Cards)'

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

    def __str__(self):
        issued = ' — Issued' if self.is_issued else ''
        return (
            f"SF9: {self.enrollment.student.lrn} — {self.quarter.quarter_label} — "
            f"GA: {self.general_average or 'N/A'}{issued}"
        )


# =============================================================================
# 9.5 — DocumentRequest
# =============================================================================
class DocumentRequest(models.Model):
    PRIORITY_CHOICES = [
        ('Normal', 'Normal'),
        ('Urgent', 'Urgent'),
        ('Expedited', 'Expedited'),
    ]

    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='document_requests',
    )
    school_form = models.ForeignKey(
        'accounts.SchoolForm',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='document_requests',
    )
    document_description = models.CharField(
        max_length=255,
        blank=True,
        help_text='Description for non-form documents.',
    )
    requested_by_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='document_requests_made',
    )
    requested_by_external_name = models.CharField(max_length=255, blank=True)
    requested_by_external_school = models.CharField(max_length=255, blank=True)
    requested_by_external_school_id = models.CharField(max_length=20, blank=True)
    purpose = models.TextField(blank=True)
    request_date = models.DateTimeField(default=timezone.now, db_index=True)
    status = models.CharField(
        max_length=20,
        choices=DOCUMENT_REQUEST_STATUS_CHOICES,
        default='Pending',
        db_index=True,
    )
    priority = models.CharField(
        max_length=15,
        choices=PRIORITY_CHOICES,
        default='Normal',
    )
    tracking_number = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
    )
    file = models.FileField(
        upload_to='forms/document_requests/%Y/%m/',
        null=True,
        blank=True,
    )
    processed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='processed_document_requests',
    )
    processed_at = models.DateTimeField(null=True, blank=True)
    processing_notes = models.TextField(blank=True)
    release_status = models.CharField(
        max_length=20,
        choices=DOCUMENT_RELEASE_STATUS_CHOICES,
        default='Unreleased',
    )
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='released_documents',
    )
    released_at = models.DateTimeField(null=True, blank=True)
    released_to = models.CharField(max_length=255, blank=True)
    release_notes = models.TextField(blank=True)
    payment_amount = models.DecimalField(
        max_digits=8,
        decimal_places=2,
        null=True,
        blank=True,
    )
    payment_received = models.BooleanField(default=False)
    payment_reference = models.CharField(max_length=100, blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-request_date']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['release_status']),
            models.Index(fields=['tracking_number']),
        ]
        verbose_name = 'Document Request'
        verbose_name_plural = 'Document Requests'

    @property
    def student_name(self):
        return self.student.full_name

    @property
    def lrn(self):
        return self.student.lrn

    @property
    def document_name(self):
        if self.school_form:
            return f"{self.school_form.form_code} — {self.school_form.form_name}"
        return self.document_description or 'Unspecified Document'

    @property
    def is_external_request(self):
        return bool(self.requested_by_external_name or self.requested_by_external_school)

    def save(self, *args, **kwargs):
        if self.is_external_request and not self.tracking_number:
            self.tracking_number = f"DOC-{timezone.now().year}-{get_random_string(6, '0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ')}"
        super().save(*args, **kwargs)

    def clean(self):
        if not self.school_form and not self.document_description:
            raise ValidationError({
                'document_description': 'Either a school form or a document description is required.',
            })
        if self.status == 'Released':
            if not self.released_by:
                raise ValidationError({
                    'released_by': 'Released by is required when status is "Released".',
                })
            if not self.released_at:
                raise ValidationError({
                    'released_at': 'Release date/time is required when status is "Released".',
                })
        if self.release_status == 'Claimed' and not self.released_to:
            raise ValidationError({
                'released_to': 'Recipient name is required when document is claimed.',
            })

    def __str__(self):
        return (
            f"Request: {self.student.lrn} — {self.document_name} — "
            f"{self.get_status_display()} ({self.request_date.strftime('%Y-%m-%d')})"
        )