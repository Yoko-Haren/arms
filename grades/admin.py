# grades/admin.py
from django.contrib import admin
from .models import (
    GradeComponent,
    GradeChangeLog,
    QuarterlyGrade,
    FinalGrade,
    HonorRecord,
)


class GradeChangeLogInline(admin.TabularInline):
    model = GradeChangeLog
    extra = 0
    fields = ['field_changed', 'old_value', 'new_value', 'changed_by', 'change_reason', 'created_at']
    readonly_fields = ['field_changed', 'old_value', 'new_value', 'changed_by', 'change_reason', 'created_at']
    can_delete = False
    max_num = 0


@admin.register(GradeComponent)
class GradeComponentAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'lrn', 'subject_name', 'quarter',
        'initial_grade', 'transmuted_grade', 'descriptor',
        'validation_status', 'is_locked',
    ]
    list_filter = ['validation_status', 'quarter', 'is_locked', 'descriptor']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
        'enrollment__student__first_name',
        'subject__subject_code',
    ]
    raw_id_fields = ['enrollment', 'subject', 'quarter', 'semester', 'encoded_by', 'validated_by', 'locked_by']
    readonly_fields = [
        'written_work_percent', 'written_work_weighted',
        'performance_task_percent', 'performance_task_weighted',
        'quarterly_assessment_percent', 'quarterly_assessment_weighted',
        'initial_grade', 'transmuted_grade', 'descriptor',
        'created_at', 'updated_at',
    ]
    inlines = [GradeChangeLogInline]
    fieldsets = (
        ('Enrollment', {
            'fields': ('enrollment', 'subject', 'quarter', 'semester'),
        }),
        ('Written Work', {
            'fields': ('written_work_raw', 'written_work_max', 'written_work_percent', 'written_work_weighted'),
        }),
        ('Performance Task', {
            'fields': ('performance_task_raw', 'performance_task_max', 'performance_task_percent', 'performance_task_weighted'),
        }),
        ('Quarterly Assessment', {
            'fields': ('quarterly_assessment_raw', 'quarterly_assessment_max', 'quarterly_assessment_percent', 'quarterly_assessment_weighted'),
        }),
        ('Computed Grades', {
            'fields': ('initial_grade', 'transmuted_grade', 'descriptor'),
        }),
        ('Validation', {
            'fields': ('encoded_by', 'encoding_date', 'validation_status', 'validated_by', 'validation_date', 'validation_notes', 'is_locked', 'locked_by', 'locked_at'),
        }),
        ('Remarks', {
            'fields': ('remarks',),
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
        }),
    )

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'enrollment__student__last_name'

    def lrn(self, obj):
        return obj.enrollment.student.lrn
    lrn.short_description = 'LRN'

    def subject_name(self, obj):
        return obj.subject.subject_name
    subject_name.short_description = 'Subject'


@admin.register(GradeChangeLog)
class GradeChangeLogAdmin(admin.ModelAdmin):
    list_display = [
        'grade_component', 'field_changed', 'old_value', 'new_value',
        'changed_by', 'created_at',
    ]
    list_filter = ['field_changed', 'created_at']
    search_fields = [
        'grade_component__enrollment__student__lrn',
        'grade_component__enrollment__student__last_name',
    ]
    readonly_fields = [
        'grade_component', 'field_changed', 'old_value', 'new_value',
        'changed_by', 'change_reason', 'ip_address', 'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(QuarterlyGrade)
class QuarterlyGradeAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'quarter', 'general_average', 'total_subjects',
        'subjects_passed', 'subjects_failed', 'has_failing_grade',
        'honor_eligible', 'honor_level', 'is_complete',
    ]
    list_filter = ['quarter', 'honor_eligible', 'honor_level', 'is_complete', 'has_failing_grade']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
    ]
    readonly_fields = [
        'enrollment', 'quarter', 'general_average', 'total_subjects',
        'subjects_passed', 'subjects_failed', 'has_failing_grade',
        'has_grade_below_85', 'honor_eligible', 'honor_level',
        'is_complete', 'computed_at', 'created_at',
    ]

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(FinalGrade)
class FinalGradeAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'subject', 'q1_grade', 'q2_grade', 'q3_grade',
        'q4_grade', 'final_grade', 'status', 'is_general_average',
    ]
    list_filter = ['status', 'is_general_average']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
        'subject__subject_name',
    ]
    readonly_fields = [
        'enrollment', 'subject', 'q1_grade', 'q2_grade', 'q3_grade',
        'q4_grade', 'final_grade', 'status', 'is_general_average',
        'computed_at', 'created_at',
    ]

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(HonorRecord)
class HonorRecordAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'honor_level', 'award_type', 'quarter',
        'general_average', 'awarded_date', 'is_withdrawn',
    ]
    list_filter = ['award_type', 'honor_level', 'is_withdrawn', 'quarter']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
    ]
    raw_id_fields = ['enrollment', 'quarter', 'withdrawn_by']

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'