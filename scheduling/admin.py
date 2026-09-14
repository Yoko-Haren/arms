# scheduling/admin.py
from django.contrib import admin
from .models import (
    ClassAssignment,
    ClassSchedule,
    SubstitutionAssignment,
    TeacherLoadSummary,
)


class ClassScheduleInline(admin.TabularInline):
    model = ClassSchedule
    extra = 1
    fields = [
        'day_of_week', 'time_start', 'time_end', 'room',
        'schedule_type', 'is_active',
    ]


@admin.register(ClassAssignment)
class ClassAssignmentAdmin(admin.ModelAdmin):
    list_display = [
        'teacher', 'subject', 'section', 'school_year', 'semester',
        'default_room', 'is_advisory', 'is_active',
    ]
    list_filter = ['school_year', 'semester', 'is_advisory', 'is_active']
    search_fields = [
        'teacher__first_name', 'teacher__last_name',
        'subject__subject_code', 'subject__subject_name',
        'section__section_name',
    ]
    raw_id_fields = ['teacher', 'section', 'subject', 'school_year', 'default_room', 'created_by']
    inlines = [ClassScheduleInline]


@admin.register(ClassSchedule)
class ClassScheduleAdmin(admin.ModelAdmin):
    list_display = [
        'class_assignment', 'day_of_week', 'time_start', 'time_end',
        'effective_room', 'schedule_type', 'is_active',
    ]
    list_filter = ['day_of_week', 'schedule_type', 'is_active']
    search_fields = [
        'class_assignment__subject__subject_code',
        'class_assignment__teacher__last_name',
        'class_assignment__section__section_name',
    ]
    raw_id_fields = ['class_assignment', 'room']


@admin.register(SubstitutionAssignment)
class SubstitutionAssignmentAdmin(admin.ModelAdmin):
    list_display = [
        'class_schedule', 'original_teacher', 'substitute_teacher',
        'substitution_date', 'reason', 'was_conducted',
    ]
    list_filter = ['reason', 'was_conducted', 'substitution_date']
    search_fields = [
        'original_teacher__first_name', 'original_teacher__last_name',
        'substitute_teacher__first_name', 'substitute_teacher__last_name',
        'lesson_covered',
    ]
    raw_id_fields = ['class_schedule', 'original_teacher', 'substitute_teacher', 'approved_by', 'created_by']


@admin.register(TeacherLoadSummary)
class TeacherLoadSummaryAdmin(admin.ModelAdmin):
    list_display = [
        'teacher', 'school_year', 'total_subjects', 'total_sections',
        'total_teaching_hours_per_week', 'is_adviser', 'is_overload',
        'last_calculated_at',
    ]
    list_filter = ['school_year', 'is_adviser', 'is_overload']
    search_fields = ['teacher__first_name', 'teacher__last_name', 'advised_section_name']
    readonly_fields = [
        'teacher', 'school_year', 'total_sections', 'total_subjects',
        'total_meetings_per_week', 'total_minutes_per_week',
        'total_teaching_hours_per_week', 'is_adviser', 'advised_section_name',
        'is_overload', 'last_calculated_at', 'created_at',
    ]

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False