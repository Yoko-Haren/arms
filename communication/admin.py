# communication/admin.py
from django.contrib import admin
from .models import (
    Announcement,
    AnnouncementTarget,
    AnnouncementView,
    MessageThread,
    Message,
    Notification,
)


class AnnouncementTargetInline(admin.TabularInline):
    model = AnnouncementTarget
    extra = 1
    fields = ['target_type', 'target_role', 'target_section', 'target_grade_level', 'target_user']


@admin.register(Announcement)
class AnnouncementAdmin(admin.ModelAdmin):
    list_display = [
        'title', 'posted_by', 'priority', 'category',
        'is_published', 'created_at',
    ]
    list_filter = ['is_published', 'priority', 'category', 'created_at']
    search_fields = ['title', 'body']
    raw_id_fields = ['posted_by']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [AnnouncementTargetInline]


@admin.register(AnnouncementTarget)
class AnnouncementTargetAdmin(admin.ModelAdmin):
    list_display = [
        'announcement', 'target_type', 'target_role',
        'target_section', 'target_grade_level', 'target_user',
    ]
    list_filter = ['target_type']
    raw_id_fields = ['announcement', 'target_section', 'target_grade_level', 'target_user']


@admin.register(AnnouncementView)
class AnnouncementViewAdmin(admin.ModelAdmin):
    list_display = ['announcement', 'user', 'viewed_at']
    list_filter = ['viewed_at']
    raw_id_fields = ['announcement', 'user']
    readonly_fields = ['announcement', 'user', 'viewed_at']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(MessageThread)
class MessageThreadAdmin(admin.ModelAdmin):
    list_display = [
        'subject', 'initiator', 'participant_count',
        'last_message_at', 'is_active',
    ]
    search_fields = ['subject']
    raw_id_fields = ['initiator']
    filter_horizontal = ['participants']
    readonly_fields = ['created_at', 'updated_at']

    def participant_count(self, obj):
        return obj.participants.count()
    participant_count.short_description = 'Participants'


@admin.register(Message)
class MessageAdmin(admin.ModelAdmin):
    list_display = [
        'thread', 'sender', 'recipient', 'body_preview',
        'is_read', 'created_at',
    ]
    list_filter = ['is_read', 'created_at']
    search_fields = ['body']
    raw_id_fields = ['thread', 'sender', 'recipient']

    def body_preview(self, obj):
        return obj.body[:80]
    body_preview.short_description = 'Message'


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = [
        'recipient', 'notification_type', 'title', 'priority',
        'is_read', 'created_at',
    ]
    list_filter = ['notification_type', 'priority', 'is_read', 'created_at']
    search_fields = ['title', 'message']
    raw_id_fields = ['recipient']