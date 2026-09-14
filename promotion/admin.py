# promotion/admin.py
from django.contrib import admin
from .models import (
    PromotionRecommendation,
    RetentionRecord,
    GraduationRecord,
)


@admin.register(PromotionRecommendation)
class PromotionRecommendationAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'grade_level', 'recommendation', 'final_decision',
        'remedial_required', 'remedial_completed', 'status',
    ]
    list_filter = ['recommendation', 'final_decision', 'status', 'remedial_required', 'remedial_completed']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
        'enrollment__student__first_name',
    ]
    raw_id_fields = ['enrollment', 'recommended_by', 'reviewed_by', 'approved_by']
    readonly_fields = ['created_at', 'updated_at']

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'enrollment__student__last_name'

    def grade_level(self, obj):
        return obj.enrollment.section.grade_level.grade_name
    grade_level.short_description = 'Grade Level'


@admin.register(RetentionRecord)
class RetentionRecordAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'reason', 'retained_grade_level',
        'next_school_year', 'parent_notified',
    ]
    list_filter = ['reason', 'next_school_year', 'parent_notified', 'intervention_attempted']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
    ]
    raw_id_fields = ['enrollment', 'retained_grade_level', 'next_school_year', 'approved_by', 'recorded_by']
    readonly_fields = ['created_at', 'updated_at']

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'enrollment__student__last_name'


@admin.register(GraduationRecord)
class GraduationRecordAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'lrn', 'graduation_type', 'grade_level_completed',
        'graduation_date', 'honors_at_graduation', 'diploma_number',
        'certificate_issued', 'is_verified',
    ]
    list_filter = ['graduation_type', 'honors_at_graduation', 'certificate_issued', 'is_verified', 'graduation_date']
    search_fields = [
        'student__lrn',
        'student__last_name',
        'student__first_name',
        'diploma_number',
    ]
    raw_id_fields = ['student', 'grade_level_completed', 'strand_completed', 'track_completed', 'verified_by']
    readonly_fields = ['created_at', 'updated_at']

    def student_name(self, obj):
        return obj.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'student__last_name'

    def lrn(self, obj):
        return obj.student.lrn
    lrn.short_description = 'LRN'