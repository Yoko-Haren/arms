# transfers/admin.py
from django.contrib import admin
from .models import Transfer, TransferDocument


class TransferDocumentInline(admin.TabularInline):
    model = TransferDocument
    extra = 1
    fields = [
        'document_type', 'is_submitted', 'submission_date',
        'file', 'is_verified',
    ]


@admin.register(Transfer)
class TransferAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'lrn', 'transfer_type', 'from_school_name',
        'to_school_name', 'status', 'transfer_date_requested',
    ]
    list_filter = ['transfer_type', 'status', 'transfer_date_requested']
    search_fields = [
        'student__lrn',
        'student__last_name',
        'student__first_name',
        'from_school_name',
        'to_school_name',
    ]
    raw_id_fields = ['student', 'grade_level_at_transfer', 'requested_by', 'approved_by']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [TransferDocumentInline]
    fieldsets = (
        ('Student & Transfer Type', {
            'fields': ('student', 'transfer_type', 'grade_level_at_transfer'),
        }),
        ('School Information', {
            'fields': (
                'from_school_name', 'from_school_beis_id', 'from_school_address',
                'to_school_name', 'to_school_beis_id', 'to_school_address',
            ),
        }),
        ('Dates & Reason', {
            'fields': (
                'transfer_date_requested', 'transfer_date_effective',
                'reason', 'reason_details',
            ),
        }),
        ('Status & Approval', {
            'fields': (
                'status', 'requested_by', 'approved_by', 'approved_at',
                'enrollment_updated',
            ),
        }),
        ('Document Release', {
            'fields': (
                'sf9_released', 'sf9_release_date',
                'sf10_released', 'sf10_release_date',
            ),
        }),
        ('Notes & Audit', {
            'fields': ('notes', 'created_at', 'updated_at'),
        }),
    )

    def student_name(self, obj):
        return obj.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'student__last_name'

    def lrn(self, obj):
        return obj.student.lrn
    lrn.short_description = 'LRN'


@admin.register(TransferDocument)
class TransferDocumentAdmin(admin.ModelAdmin):
    list_display = [
        'transfer', 'document_type', 'is_submitted',
        'submission_date', 'is_verified',
    ]
    list_filter = ['document_type', 'is_submitted', 'is_verified']
    search_fields = [
        'transfer__student__lrn',
        'transfer__student__last_name',
        'file_name',
    ]
    raw_id_fields = ['transfer', 'verified_by']
    readonly_fields = ['created_at', 'updated_at']