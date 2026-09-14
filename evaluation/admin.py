# evaluation/admin.py
from django.contrib import admin
from .models import TeacherEvaluation, EvaluationCriterion, IpcrfRecord


class EvaluationCriterionInline(admin.TabularInline):
    model = EvaluationCriterion
    extra = 1
    fields = [
        'kra_number', 'objective_number', 'indicator_name',
        'score', 'quality_of_evidence', 'comments',
    ]


@admin.register(TeacherEvaluation)
class TeacherEvaluationAdmin(admin.ModelAdmin):
    list_display = [
        'teacher_name', 'evaluator_name', 'evaluation_type',
        'observation_date', 'overall_rating', 'adjectival_rating', 'status',
    ]
    list_filter = ['evaluation_type', 'status', 'rpms_cycle']
    search_fields = [
        'teacher__first_name', 'teacher__last_name',
        'evaluator__first_name', 'evaluator__last_name',
    ]
    raw_id_fields = ['rpms_cycle', 'teacher', 'evaluator', 'subject_observed', 'section_observed']
    readonly_fields = ['created_at', 'updated_at']
    inlines = [EvaluationCriterionInline]
    fieldsets = (
        ('Cycle & Participants', {
            'fields': ('rpms_cycle', 'teacher', 'evaluator', 'evaluation_type'),
        }),
        ('Observation Details', {
            'fields': (
                'observation_date', 'time_in', 'time_out',
                'subject_observed', 'section_observed',
            ),
        }),
        ('Ratings', {
            'fields': ('overall_rating', 'adjectival_rating'),
        }),
        ('Comments', {
            'fields': ('strengths', 'areas_for_improvement', 'teacher_comments'),
        }),
        ('Status & Attachments', {
            'fields': (
                'status', 'submitted_at', 'acknowledged_at', 'finalized_at',
                'attachment', 'attachment_name',
            ),
        }),
        ('Notes & Audit', {
            'fields': ('notes', 'created_at', 'updated_at'),
        }),
    )

    def teacher_name(self, obj):
        return obj.teacher.get_full_name() or obj.teacher.username
    teacher_name.short_description = 'Teacher'
    teacher_name.admin_order_field = 'teacher__last_name'

    def evaluator_name(self, obj):
        return obj.evaluator.get_full_name() or obj.evaluator.username
    evaluator_name.short_description = 'Evaluator'
    evaluator_name.admin_order_field = 'evaluator__last_name'


@admin.register(EvaluationCriterion)
class EvaluationCriterionAdmin(admin.ModelAdmin):
    list_display = [
        'evaluation', 'kra_number', 'objective_number', 'indicator_name',
        'score', 'quality_of_evidence',
    ]
    list_filter = ['kra_number', 'quality_of_evidence']
    search_fields = ['indicator_name', 'means_of_verification']
    raw_id_fields = ['evaluation', 'criteria_template']


@admin.register(IpcrfRecord)
class IpcrfRecordAdmin(admin.ModelAdmin):
    list_display = [
        'teacher_name', 'rpms_cycle', 'final_overall_rating',
        'adjectival_rating', 'status', 'teacher_signed_at', 'rater_signed_at',
    ]
    list_filter = ['status', 'rpms_cycle', 'adjectival_rating']
    search_fields = ['teacher__first_name', 'teacher__last_name']
    raw_id_fields = ['teacher', 'rpms_cycle']
    readonly_fields = ['created_at', 'updated_at']

    def teacher_name(self, obj):
        return obj.teacher.get_full_name() or obj.teacher.username
    teacher_name.short_description = 'Teacher'
    teacher_name.admin_order_field = 'teacher__last_name'