# documentation/admin.py || forms/admin.py
from django.contrib import admin
from .models import (
    FormSubmission,
    FormCompliance,
    SF10History,
    SF9History,
    DocumentRequest,
)


@admin.register(FormSubmission)
class FormSubmissionAdmin(admin.ModelAdmin):
    list_display = [
        'school_form', 'section', 'school_year', 'quarter',
        'submitted_by', 'status', 'submitted_date',
    ]
    list_filter = ['status', 'school_year', 'school_form']
    search_fields = [
        'school_form__form_code',
        'school_form__form_name',
        'section__section_name',
        'submitted_by__first_name',
        'submitted_by__last_name',
    ]
    raw_id_fields = ['school_form', 'section', 'school_year', 'quarter', 'submitted_by', 'reviewed_by']
    readonly_fields = ['created_at', 'updated_at']


@admin.register(FormCompliance)
class FormComplianceAdmin(admin.ModelAdmin):
    list_display = [
        'school_form', 'section', 'school_year', 'quarter',
        'status', 'completion_percent', 'due_date',
    ]
    list_filter = ['status', 'school_year', 'school_form']
    search_fields = [
        'school_form__form_code',
        'school_form__form_name',
        'section__section_name',
    ]
    raw_id_fields = ['school_form', 'section', 'school_year', 'quarter']


@admin.register(SF10History)
class SF10HistoryAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'lrn', 'school_year', 'grade_level',
        'general_average', 'remarks', 'is_certified', 'is_locked',
    ]
    list_filter = ['is_certified', 'is_locked', 'remarks', 'school_year']
    search_fields = [
        'student__lrn',
        'student__last_name',
        'student__first_name',
    ]
    raw_id_fields = ['student', 'grade_level', 'school_year', 'generated_by', 'certified_by', 'locked_by']
    readonly_fields = ['created_at', 'updated_at']

    def student_name(self, obj):
        return obj.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'student__last_name'

    def lrn(self, obj):
        return obj.student.lrn
    lrn.short_description = 'LRN'


@admin.register(SF9History)
class SF9HistoryAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'lrn', 'quarter', 'general_average',
        'honors', 'is_issued', 'generated_date',
    ]
    list_filter = ['is_issued', 'quarter']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
        'enrollment__student__first_name',
    ]
    raw_id_fields = ['enrollment', 'quarter', 'generated_by']
    readonly_fields = ['created_at', 'updated_at']

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'enrollment__student__last_name'

    def lrn(self, obj):
        return obj.enrollment.student.lrn
    lrn.short_description = 'LRN'


@admin.register(DocumentRequest)
class DocumentRequestAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'document_name', 'status', 'release_status',
        'tracking_number', 'priority', 'request_date',
    ]
    list_filter = ['status', 'release_status', 'priority', 'payment_received']
    search_fields = [
        'student__lrn',
        'student__last_name',
        'tracking_number',
        'requested_by_external_name',
        'requested_by_external_school',
    ]
    raw_id_fields = ['student', 'school_form', 'requested_by_user', 'processed_by', 'released_by']
    readonly_fields = ['created_at', 'updated_at']

    def student_name(self, obj):
        return obj.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'student__last_name'