# enrollment/admin.py
from django.contrib import admin
from .models import (
    Enrollment,
    EnrollmentHistory,
    EnrollmentDocument,
    BalikAralDetails,
    DroppedStudentDetails,
)


@admin.register(Enrollment)
class EnrollmentAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'lrn', 'section', 'school_year',
        'status', 'enrollment_type', 'enrollment_date',
    ]
    list_filter = ['status', 'school_year', 'enrollment_type', 'is_4ps', 'esc_grantee']
    search_fields = [
        'student__lrn', 'student__last_name', 'student__first_name',
        'section__section_name',
    ]
    raw_id_fields = ['student', 'section', 'grade_level_at_entry', 'created_by', 'updated_by']
    readonly_fields = ['created_at', 'updated_at']

    def student_name(self, obj):
        return obj.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'student__last_name'

    def lrn(self, obj):
        return obj.student.lrn
    lrn.short_description = 'LRN'
    lrn.admin_order_field = 'student__lrn'

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(EnrollmentHistory)
class EnrollmentHistoryAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'previous_status', 'new_status', 'change_date', 'changed_by']
    list_filter = ['new_status', 'change_date']
    search_fields = ['enrollment__student__lrn', 'enrollment__student__last_name', 'reason']
    readonly_fields = ['enrollment', 'previous_status', 'new_status', 'change_date', 'changed_by', 'reason', 'ip_address']

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(EnrollmentDocument)
class EnrollmentDocumentAdmin(admin.ModelAdmin):
    list_display = ['enrollment', 'document_type', 'is_submitted', 'is_verified', 'submission_date']
    list_filter = ['document_type', 'is_submitted', 'is_verified']
    search_fields = ['enrollment__student__lrn', 'enrollment__student__last_name', 'file_name']


@admin.register(BalikAralDetails)
class BalikAralDetailsAdmin(admin.ModelAdmin):
    list_display = [
        'enrollment', 'last_grade_level_completed', 'years_out_of_school',
        'assessment_test_score', 'recommended_grade_level',
    ]
    search_fields = [
        'enrollment__student__lrn', 'last_school_attended_name',
        'interview_conducted_by',
    ]
    raw_id_fields = ['enrollment', 'recommended_grade_level']


@admin.register(DroppedStudentDetails)
class DroppedStudentDetailsAdmin(admin.ModelAdmin):
    list_display = [
        'enrollment', 'dropout_date', 'dropout_reason',
        'intervention_attempted', 'guardian_notified', 'is_reported_to_division',
    ]
    list_filter = [
        'dropout_reason', 'intervention_attempted', 'guardian_notified',
        'is_reported_to_division',
    ]
    search_fields = ['enrollment__student__lrn', 'enrollment__student__last_name', 'reason_details']
    raw_id_fields = ['enrollment', 'recorded_by', 'approved_by']