# transfers/models.py
"""
Phase 10: Transfer Management models for Formify LIS.
Student transfers (incoming/outgoing) with document tracking,
SF9/SF10 release management, and approval workflow.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
TRANSFER_TYPE_CHOICES = [
    ('INCOMING', 'Incoming — Transferring into this school'),
    ('OUTGOING', 'Outgoing — Transferring to another school'),
]

TRANSFER_STATUS_CHOICES = [
    ('Pending', 'Pending — Request initiated'),
    ('Documents_Requested', 'Documents Requested'),
    ('Documents_Released', 'Documents Released'),
    ('Approved', 'Approved by Receiving School'),
    ('Completed', 'Completed — Learner enrolled/withdrawn'),
    ('Denied', 'Denied'),
    ('Cancelled', 'Cancelled'),
]

TRANSFER_REASON_CHOICES = [
    ('Change_of_Residence', 'Change of Residence'),
    ('Parent_Employment', 'Parent Employment / Relocation'),
    ('Academic', 'Academic Reasons'),
    ('Discipline', 'Disciplinary'),
    ('Financial', 'Financial Difficulties'),
    ('Health', 'Health Reasons'),
    ('Safety', 'Safety / Bullying / Emergency'),
    ('Proximity', 'Closer to Home'),
    ('Other', 'Other'),
]

TRANSFER_DOCUMENT_TYPE_CHOICES = [
    ('SF9', 'SF9 — Report Card'),
    ('SF10', 'SF10 — Form 137 (Permanent Record)'),
    ('Good_Moral', 'Certificate of Good Moral Character'),
    ('Birth_Certificate', 'PSA Birth Certificate'),
    ('Letter_of_Acceptance', 'Letter of Acceptance'),
    ('Other', 'Other'),
]


# =============================================================================
# 10.1 — Transfer
# =============================================================================
class Transfer(models.Model):
    student = models.ForeignKey(
        'students.Student',
        on_delete=models.PROTECT,
        related_name='transfers',
    )
    transfer_type = models.CharField(
        max_length=10,
        choices=TRANSFER_TYPE_CHOICES,
        db_index=True,
    )
    from_school_name = models.CharField(max_length=255, blank=True)
    from_school_beis_id = models.CharField(max_length=20, blank=True)
    from_school_address = models.CharField(max_length=255, blank=True)
    to_school_name = models.CharField(max_length=255, blank=True)
    to_school_beis_id = models.CharField(max_length=20, blank=True)
    to_school_address = models.CharField(max_length=255, blank=True)
    transfer_date_requested = models.DateField(db_index=True)
    transfer_date_effective = models.DateField(null=True, blank=True)
    grade_level_at_transfer = models.ForeignKey(
        'academics.GradeLevel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfers',
    )
    reason = models.CharField(
        max_length=30,
        blank=True,
        choices=TRANSFER_REASON_CHOICES,
    )
    reason_details = models.TextField(blank=True)
    status = models.CharField(
        max_length=25,
        choices=TRANSFER_STATUS_CHOICES,
        default='Pending',
        db_index=True,
    )
    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='transfer_requests_made',
    )
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='transfer_requests_approved',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    sf9_released = models.BooleanField(default=False)
    sf9_release_date = models.DateField(null=True, blank=True)
    sf10_released = models.BooleanField(default=False)
    sf10_release_date = models.DateField(null=True, blank=True)
    enrollment_updated = models.BooleanField(
        default=False,
        help_text='Has enrollment status been updated for this transfer?',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-transfer_date_requested', 'student__last_name']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['transfer_type', 'status']),
            models.Index(fields=['transfer_date_requested']),
        ]
        verbose_name = 'Transfer'
        verbose_name_plural = 'Transfers'

    @property
    def student_name(self):
        return self.student.full_name

    @property
    def lrn(self):
        return self.student.lrn

    @property
    def is_incoming(self):
        return self.transfer_type == 'INCOMING'

    @property
    def is_outgoing(self):
        return self.transfer_type == 'OUTGOING'

    @property
    def originating_school(self):
        if self.is_incoming:
            return self.from_school_name
        return None

    @property
    def receiving_school(self):
        if self.is_outgoing:
            return self.to_school_name
        return None

    @property
    def is_complete(self):
        return self.status == 'Completed'

    def clean(self):
        if self.transfer_type == 'INCOMING' and not self.from_school_name:
            raise ValidationError({
                'from_school_name': 'Originating school name is required for incoming transfers.',
            })
        if self.transfer_type == 'OUTGOING' and not self.to_school_name:
            raise ValidationError({
                'to_school_name': 'Receiving school name is required for outgoing transfers.',
            })
        if self.status == 'Completed' and not self.transfer_date_effective:
            raise ValidationError({
                'transfer_date_effective': 'Effective date is required when transfer is completed.',
            })
        if self.sf9_released and not self.sf9_release_date:
            raise ValidationError({
                'sf9_release_date': 'Release date is required when SF9 is marked as released.',
            })
        if self.sf10_released and not self.sf10_release_date:
            raise ValidationError({
                'sf10_release_date': 'Release date is required when SF10 is marked as released.',
            })
        if self.sf10_released and not self.sf9_released:
            raise ValidationError({
                'sf10_released': 'SF9 must be released before SF10 can be released.',
            })

    def __str__(self):
        return (
            f"{self.get_transfer_type_display()}: {self.student.lrn} — "
            f"{self.get_status_display()} ({self.transfer_date_requested})"
        )


# =============================================================================
# 10.2 — TransferDocument
# =============================================================================
class TransferDocument(models.Model):
    transfer = models.ForeignKey(
        Transfer,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    document_type = models.CharField(
        max_length=25,
        choices=TRANSFER_DOCUMENT_TYPE_CHOICES,
    )
    is_submitted = models.BooleanField(default=False)
    submission_date = models.DateField(null=True, blank=True)
    file = models.FileField(
        upload_to='transfers/documents/%Y/%m/',
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
        related_name='verified_transfer_docs',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['transfer', 'document_type']]
        ordering = ['transfer', 'document_type']
        verbose_name = 'Transfer Document'
        verbose_name_plural = 'Transfer Documents'

    def clean(self):
        if self.is_verified:
            if not self.verified_by:
                raise ValidationError({
                    'verified_by': 'Verifier is required when document is marked as verified.',
                })
            if not self.verified_at:
                raise ValidationError({
                    'verified_at': 'Verification date/time is required when document is marked as verified.',
                })

    def __str__(self):
        submitted = 'Submitted' if self.is_submitted else 'Pending'
        return (
            f"Doc: {self.get_document_type_display()} — "
            f"Transfer #{self.transfer_id} — {submitted}"
        )