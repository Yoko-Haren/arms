"""
Phase 13: Audit Trail & Blockchain models for Formify LIS.
Immutable activity logs with cryptographic blockchain verification
(SHA-256 chained hashes), anomaly detection events with AI model
confidence scoring and investigation workflow, and formal data
correction requests with approval tracking.
"""

import hashlib
import json

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# =============================================================================
# B.1 — ActivityLog
# =============================================================================
class ActivityLog(models.Model):
    timestamp = models.DateTimeField(default=timezone.now, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
        help_text='NULL for system-generated actions.',
    )
    user_name = models.CharField(
        max_length=150,
        help_text="Denormalized — user's full name at time of action.",
    )
    user_role = models.CharField(
        max_length=30,
        help_text="Denormalized — user's role at time of action.",
    )
    action_type = models.CharField(
        max_length=50,
        db_index=True,
        help_text="e.g., 'CREATE_STUDENT', 'UPDATE_GRADE', 'DELETE_ENROLLMENT', 'LOGIN_SUCCESS', 'EXPORT_DATA'.",
    )
    resource_type = models.CharField(
        max_length=100,
        help_text="Model/table affected: 'Student', 'GradeComponent', 'Enrollment'.",
    )
    resource_id = models.CharField(max_length=50, blank=True)
    affected_student = models.ForeignKey(
        'students.Student',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
    )
    affected_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs_as_teacher',
    )
    details_json = models.JSONField(
        null=True,
        blank=True,
        help_text="Full change details: {'field': 'status', 'old': 'Enrolled', 'new': 'Transferred Out'}.",
    )
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    session = models.ForeignKey(
        'accounts.SessionLog',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='activity_logs',
    )
    blockchain_hash = models.CharField(
        max_length=66,
        unique=True,
        help_text='SHA-256 hash of this entry.',
    )
    prev_blockchain_hash = models.CharField(
        max_length=66,
        help_text='Hash of the previous activity log entry — forms the chain.',
    )
    blockchain_verified = models.BooleanField(
        default=True,
        help_text='Set False if tampering detected.',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['action_type', 'timestamp']),
            models.Index(fields=['resource_type', 'resource_id']),
            models.Index(fields=['affected_student', 'timestamp']),
            models.Index(fields=['blockchain_verified']),
        ]
        verbose_name = 'Activity Log'
        verbose_name_plural = 'Activity Logs'
        default_permissions = ('view',)

    @property
    def is_system_action(self):
        return self.user is None

    def save(self, *args, **kwargs):
        if not self.pk:  # Only on creation
            # Get the previous hash
            if not self.prev_blockchain_hash:
                last_log = ActivityLog.objects.order_by('-timestamp', '-pk').first()
                if last_log:
                    self.prev_blockchain_hash = last_log.blockchain_hash
                else:
                    self.prev_blockchain_hash = '0' * 64

            # Build the raw string for hashing
            raw = (
                f"{self.prev_blockchain_hash}"
                f"{self.timestamp.isoformat()}"
                f"{self.user_id or ''}"
                f"{self.action_type}"
                f"{self.resource_id or ''}"
                f"{json.dumps(self.details_json or {}, sort_keys=True)}"
            )
            self.blockchain_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()

        super().save(*args, **kwargs)

    def __str__(self):
        return (
            f"Log #{self.pk}: {self.action_type} — {self.resource_type} "
            f"#{self.resource_id} — {self.timestamp.strftime('%Y-%m-%d %H:%M:%S')}"
        )


# =============================================================================
# B.2 — BlockchainBlock
# =============================================================================
class BlockchainBlock(models.Model):
    block_index = models.PositiveIntegerField(
        unique=True,
        help_text='Sequential block number (0 = genesis block).',
    )
    previous_hash = models.CharField(max_length=66)
    current_hash = models.CharField(
        max_length=66,
        unique=True,
        help_text="SHA-256 hash of this block's contents.",
    )
    merkle_root = models.CharField(
        max_length=66,
        help_text='Merkle tree root hash of all activity log IDs in this block.',
    )
    log_count = models.PositiveIntegerField()
    log_ids = models.JSONField(
        help_text='Array of activity_log IDs included in this block (in order).',
    )
    nonce = models.BigIntegerField(
        help_text='Proof-of-work nonce.',
    )
    mined_at = models.DateTimeField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['block_index']
        verbose_name = 'Blockchain Block'
        verbose_name_plural = 'Blockchain Blocks'
        default_permissions = ('view',)

    @property
    def is_genesis(self):
        return self.block_index == 0

    def save(self, *args, **kwargs):
        if not self.pk:
            raw = (
                f"{self.block_index}"
                f"{self.previous_hash}"
                f"{self.merkle_root}"
                f"{self.log_count}"
                f"{self.nonce}"
            )
            self.current_hash = hashlib.sha256(raw.encode('utf-8')).hexdigest()

            # Validate proof-of-work: hash must start with '0000'
            if not self.current_hash.startswith('0000'):
                raise ValidationError(
                    'Block hash does not meet the difficulty target (must start with 0000). '
                    'Adjust the nonce and try again.'
                )

        super().save(*args, **kwargs)

    def __str__(self):
        return f"Block #{self.block_index} — {self.log_count} logs — {self.current_hash[:16]}..."


# =============================================================================
# B.3 — AnomalyDetectionEvent
# =============================================================================
class AnomalyDetectionEvent(models.Model):
    ANOMALY_TYPE_CHOICES = [
        ('Unusual_Grade_Change', 'Unusual Grade Change'),
        ('Suspicious_Login', 'Suspicious Login'),
        ('Data_Tampering', 'Data Tampering'),
        ('Bulk_Delete', 'Bulk Delete'),
        ('Unauthorized_Access', 'Unauthorized Access'),
        ('Pattern_Deviation', 'Pattern Deviation'),
        ('Fraud_Indicator', 'Fraud Indicator'),
    ]
    SEVERITY_CHOICES = [
        ('Low', 'Low'),
        ('Medium', 'Medium'),
        ('High', 'High'),
        ('Critical', 'Critical'),
    ]
    INVESTIGATION_RESULT_CHOICES = [
        ('Confirmed_Anomaly', 'Confirmed Anomaly'),
        ('False_Positive', 'False Positive'),
        ('Inconclusive', 'Inconclusive'),
    ]

    triggering_log = models.ForeignKey(
        ActivityLog,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='anomaly_events',
    )
    anomaly_type = models.CharField(
        max_length=40,
        choices=ANOMALY_TYPE_CHOICES,
        db_index=True,
    )
    severity = models.CharField(
        max_length=15,
        choices=SEVERITY_CHOICES,
        db_index=True,
    )
    confidence_score = models.DecimalField(
        max_digits=5,
        decimal_places=4,
        help_text='AI model confidence: 0.0000 (none) to 1.0000 (absolute certainty).',
    )
    model_version = models.CharField(
        max_length=20,
        help_text="Version of AI model that flagged this: 'v1.0.0', 'v2.1.3'.",
    )
    details_json = models.JSONField(
        null=True,
        blank=True,
        help_text='Full anomaly details: features analyzed, threshold exceeded, pattern matched.',
    )
    is_investigated = models.BooleanField(default=False, db_index=True)
    investigated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='anomaly_investigations',
    )
    investigated_at = models.DateTimeField(null=True, blank=True)
    investigation_result = models.CharField(
        max_length=30,
        blank=True,
        choices=INVESTIGATION_RESULT_CHOICES,
    )
    resolution_notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['anomaly_type', 'severity']),
            models.Index(fields=['is_investigated']),
            models.Index(fields=['confidence_score']),
        ]
        verbose_name = 'Anomaly Detection Event'
        verbose_name_plural = 'Anomaly Detection Events'

    @property
    def is_resolved(self):
        return bool(self.investigation_result)

    @property
    def is_critical(self):
        return self.severity == 'Critical'

    def clean(self):
        if self.is_investigated:
            if not self.investigated_by:
                raise ValidationError({
                    'investigated_by': 'Investigator is required when marked as investigated.',
                })
            if not self.investigated_at:
                raise ValidationError({
                    'investigated_at': 'Investigation timestamp is required when marked as investigated.',
                })
        if self.investigation_result and not self.is_investigated:
            raise ValidationError({
                'is_investigated': 'Must be marked as investigated when an investigation result is set.',
            })

    def __str__(self):
        base = (
            f"Anomaly #{self.pk}: {self.get_anomaly_type_display()} — "
            f"{self.get_severity_display()} (Confidence: {self.confidence_score})"
        )
        if self.is_investigated:
            base += ' — Investigated'
        return base


# =============================================================================
# B.4 — DataCorrectionRequest
# =============================================================================
class DataCorrectionRequest(models.Model):
    STATUS_CHOICES = [
        ('Pending', 'Pending Review'),
        ('Approved', 'Approved — Correction Applied'),
        ('Denied', 'Denied'),
        ('Executed', 'Executed — Data Updated'),
    ]

    requested_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='correction_requests_made',
    )
    entity_type = models.CharField(
        max_length=50,
        help_text="Model/table: 'Student', 'GradeComponent', 'Enrollment', 'AttendanceRecord'.",
    )
    entity_id = models.PositiveIntegerField(
        help_text='ID of the record to correct.',
    )
    field_to_correct = models.CharField(max_length=100)
    current_value = models.TextField()
    proposed_value = models.TextField()
    justification = models.TextField(
        help_text='Detailed reason for correction. Required for audit compliance.',
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Pending',
        db_index=True,
    )
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='correction_requests_reviewed',
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_notes = models.TextField(blank=True)
    executed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='correction_requests_executed',
        help_text='User who actually applied the correction to the database.',
    )
    executed_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['status']),
            models.Index(fields=['entity_type', 'entity_id']),
        ]
        verbose_name = 'Data Correction Request'
        verbose_name_plural = 'Data Correction Requests'

    @property
    def is_resolved(self):
        return self.status in ['Approved', 'Denied', 'Executed']

    def clean(self):
        if self.status in ['Approved', 'Executed']:
            if not self.reviewed_by:
                raise ValidationError({
                    'reviewed_by': 'Reviewer is required when status is Approved or Executed.',
                })
            if not self.reviewed_at:
                raise ValidationError({
                    'reviewed_at': 'Review timestamp is required when status is Approved or Executed.',
                })
        if self.status == 'Executed':
            if not self.executed_by:
                raise ValidationError({
                    'executed_by': 'Executor is required when status is Executed.',
                })
            if not self.executed_at:
                raise ValidationError({
                    'executed_at': 'Execution timestamp is required when status is Executed.',
                })

    def __str__(self):
        return (
            f"Correction #{self.pk}: {self.entity_type} #{self.entity_id} — "
            f"{self.field_to_correct}: '{self.current_value}' → "
            f"'{self.proposed_value}' — {self.get_status_display()}"
        )