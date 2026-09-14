# communication/models.py
"""
Phase 11: Communication models for Formify LIS.
Announcements with targeted delivery and view tracking, threaded
messaging, and system-wide notifications with 19 notification types.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
ANNOUNCEMENT_PRIORITY_CHOICES = [
    ('Low', 'Low'),
    ('Normal', 'Normal'),
    ('High', 'High'),
    ('Urgent', 'Urgent'),
]

ANNOUNCEMENT_CATEGORY_CHOICES = [
    ('General', 'General'),
    ('Academic', 'Academic'),
    ('Administrative', 'Administrative'),
    ('Event', 'Event'),
    ('Emergency', 'Emergency'),
    ('Deadline', 'Deadline'),
]

TARGET_TYPE_CHOICES = [
    ('All', 'All Users'),
    ('Role', 'By Role'),
    ('Section', 'By Section'),
    ('Grade_Level', 'By Grade Level'),
    ('Individual', 'Individual User'),
]

TARGET_ROLE_CHOICES = [
    ('admin', 'System Administrator'),
    ('schoolhead', 'School Head / Principal'),
    ('registrar', 'School Registrar'),
    ('teacher', 'Teacher'),
]

NOTIFICATION_PRIORITY_CHOICES = [
    ('Low', 'Low'),
    ('Normal', 'Normal'),
    ('High', 'High'),
    ('Urgent', 'Urgent'),
]

NOTIFICATION_TYPE_CHOICES = [
    ('GRADE_RETURNED', 'Registrar returned grades for correction'),
    ('GRADE_VALIDATED', 'Registrar validated submitted grades'),
    ('GRADE_DEADLINE_REMINDER', 'Approaching grade encoding deadline'),
    ('FORM_SUBMISSION_DEADLINE', 'SF1/SF2/SF9 submission due soon'),
    ('FORM_RETURNED', 'Submitted form returned for revision'),
    ('FORM_APPROVED', 'Form approved by registrar/head'),
    ('ANNOUNCEMENT_POSTED', 'New announcement posted'),
    ('ANNOUNCEMENT_URGENT', 'Urgent announcement'),
    ('TRANSFER_REQUEST', 'New transfer request needs action'),
    ('TRANSFER_APPROVED', 'Transfer approved'),
    ('TRANSFER_DOCUMENTS_READY', 'SF9/SF10 ready for pickup'),
    ('MESSAGE_RECEIVED', 'New message received'),
    ('ATTENDANCE_ALERT', 'Student reached 20% absence threshold'),
    ('ENROLLMENT_CONFIRMATION', 'Student enrollment processed'),
    ('PROMOTION_REVIEW_NEEDED', 'Promotion recommendations ready for review'),
    ('EVALUATION_SCHEDULED', 'RPMS observation scheduled'),
    ('EVALUATION_COMPLETED', 'Evaluation results available'),
    ('SYSTEM_MAINTENANCE', 'Scheduled system downtime'),
    ('SYSTEM_UPDATE', 'New feature or update available'),
]


# =============================================================================
# 11.1 — Announcement
# =============================================================================
class Announcement(models.Model):
    posted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='announcements_posted',
    )
    title = models.CharField(max_length=255)
    body = models.TextField()
    priority = models.CharField(
        max_length=10,
        choices=ANNOUNCEMENT_PRIORITY_CHOICES,
        default='Normal',
    )
    category = models.CharField(
        max_length=20,
        blank=True,
        choices=ANNOUNCEMENT_CATEGORY_CHOICES,
    )
    is_published = models.BooleanField(default=True, db_index=True)
    published_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    is_archived = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['is_published']),
            models.Index(fields=['priority']),
            models.Index(fields=['category']),
        ]
        verbose_name = 'Announcement'
        verbose_name_plural = 'Announcements'

    @property
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    @property
    def poster_name(self):
        return self.posted_by.get_full_name() or self.posted_by.username

    def clean(self):
        if self.is_published and not self.published_at:
            self.published_at = timezone.now()

    def __str__(self):
        status = 'Published' if self.is_published else 'Draft'
        return f"{self.title} — {self.get_priority_display()} ({status})"


# =============================================================================
# 11.2 — AnnouncementTarget
# =============================================================================
class AnnouncementTarget(models.Model):
    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name='targets',
    )
    target_type = models.CharField(
        max_length=20,
        choices=TARGET_TYPE_CHOICES,
    )
    target_role = models.CharField(
        max_length=20,
        blank=True,
        choices=TARGET_ROLE_CHOICES,
        help_text="Required if target_type='Role'.",
    )
    target_section = models.ForeignKey(
        'academics.Section',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='announcement_targets',
    )
    target_grade_level = models.ForeignKey(
        'academics.GradeLevel',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='announcement_targets',
    )
    target_user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='announcement_targets',
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['announcement', 'target_type']
        verbose_name = 'Announcement Target'
        verbose_name_plural = 'Announcement Targets'

    def clean(self):
        if self.target_type == 'Role' and not self.target_role:
            raise ValidationError({
                'target_role': 'Target role is required when target type is "Role".',
            })
        if self.target_type == 'Section' and not self.target_section:
            raise ValidationError({
                'target_section': 'Target section is required when target type is "Section".',
            })
        if self.target_type == 'Grade_Level' and not self.target_grade_level:
            raise ValidationError({
                'target_grade_level': 'Target grade level is required when target type is "Grade_Level".',
            })
        if self.target_type == 'Individual' and not self.target_user:
            raise ValidationError({
                'target_user': 'Target user is required when target type is "Individual".',
            })

    def __str__(self):
        return f"Target: {self.get_target_type_display()} — Announcement #{self.announcement_id}"


# =============================================================================
# 11.3 — AnnouncementView
# =============================================================================
class AnnouncementView(models.Model):
    announcement = models.ForeignKey(
        Announcement,
        on_delete=models.CASCADE,
        related_name='views',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='announcement_views',
    )
    viewed_at = models.DateTimeField(default=timezone.now)

    class Meta:
        unique_together = [['announcement', 'user']]
        ordering = ['announcement', '-viewed_at']
        verbose_name = 'Announcement View'
        verbose_name_plural = 'Announcement Views'

    def __str__(self):
        return f"View: {self.user.get_full_name()} — Announcement #{self.announcement_id}"


# =============================================================================
# 11.4 — MessageThread
# =============================================================================
class MessageThread(models.Model):
    subject = models.CharField(max_length=255)
    initiator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='initiated_threads',
    )
    participants = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        related_name='message_threads',
    )
    last_message_at = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-last_message_at', '-created_at']
        verbose_name = 'Message Thread'
        verbose_name_plural = 'Message Threads'

    @property
    def message_count(self):
        return self.messages.count()

    @property
    def last_message_preview(self):
        last = self.messages.order_by('-created_at').first()
        if last:
            return last.body[:100]
        return None

    def __str__(self):
        return f"Thread: {self.subject} ({self.participants.count()} participants)"


# =============================================================================
# 11.5 — Message
# =============================================================================
class Message(models.Model):
    thread = models.ForeignKey(
        MessageThread,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    sender = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='sent_messages',
    )
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name='received_messages',
        help_text='NULL if message to all thread participants.',
    )
    body = models.TextField()
    attachment = models.FileField(
        upload_to='communication/attachments/%Y/%m/',
        null=True,
        blank=True,
    )
    attachment_name = models.CharField(max_length=255, blank=True)
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['thread', 'created_at']
        indexes = [
            models.Index(fields=['thread', 'created_at']),
            models.Index(fields=['sender', 'created_at']),
            models.Index(fields=['is_read']),
        ]
        verbose_name = 'Message'
        verbose_name_plural = 'Messages'

    @property
    def sender_name(self):
        return self.sender.get_full_name() or self.sender.username

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        # Update thread's last_message_at
        MessageThread.objects.filter(pk=self.thread_id).update(
            last_message_at=self.created_at,
        )

    def __str__(self):
        return f"Msg: {self.sender.get_full_name()} — {self.body[:50]}..."


# =============================================================================
# 11.6 — Notification
# =============================================================================
class Notification(models.Model):
    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='notifications',
    )
    notification_type = models.CharField(
        max_length=50,
        choices=NOTIFICATION_TYPE_CHOICES,
        db_index=True,
    )
    title = models.CharField(max_length=255)
    message = models.TextField()
    priority = models.CharField(
        max_length=10,
        choices=NOTIFICATION_PRIORITY_CHOICES,
        default='Normal',
    )
    is_read = models.BooleanField(default=False, db_index=True)
    read_at = models.DateTimeField(null=True, blank=True)
    related_entity_type = models.CharField(max_length=50, blank=True)
    related_entity_id = models.PositiveIntegerField(null=True, blank=True)
    action_url = models.CharField(max_length=255, blank=True)
    is_dismissed = models.BooleanField(default=False)
    expires_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['recipient', 'is_read']),
            models.Index(fields=['recipient', 'created_at']),
            models.Index(fields=['notification_type']),
        ]
        verbose_name = 'Notification'
        verbose_name_plural = 'Notifications'

    @property
    def is_expired(self):
        if self.expires_at:
            return timezone.now() > self.expires_at
        return False

    def __str__(self):
        status = 'Read' if self.is_read else 'Unread'
        return f"Notif: {self.title} — To: {self.recipient.get_full_name()} ({status})"