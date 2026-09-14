# attendance/admin.py
from django.contrib import admin
from .models import (
    AttendanceRecord,
    AttendanceSummary,
    AttendanceIntervention,
    SF2AttendanceReport,
)


@admin.register(AttendanceRecord)
class AttendanceRecordAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'lrn', 'date', 'status', 'excuse_type',
        'excuse_validated', 'marked_by',
    ]
    list_filter = ['status', 'date', 'excuse_validated', 'is_holiday']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
        'enrollment__student__first_name',
    ]
    date_hierarchy = 'date'
    raw_id_fields = ['enrollment', 'marked_by', 'validated_by', 'updated_by']

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'
    student_name.admin_order_field = 'enrollment__student__last_name'

    def lrn(self, obj):
        return obj.enrollment.student.lrn
    lrn.short_description = 'LRN'


@admin.register(AttendanceSummary)
class AttendanceSummaryAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'school_year', 'month', 'total_school_days',
        'days_present', 'days_absent', 'absence_rate_percent', 'is_at_risk',
    ]
    list_filter = ['is_at_risk', 'school_year', 'month']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
    ]
    readonly_fields = [
        'enrollment', 'school_year', 'month', 'total_school_days',
        'days_present', 'days_absent', 'days_late', 'days_excused',
        'days_cutting', 'days_suspended', 'absence_rate_percent',
        'is_at_risk', 'consecutive_absences', 'last_calculated_at', 'created_at',
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


@admin.register(AttendanceIntervention)
class AttendanceInterventionAdmin(admin.ModelAdmin):
    list_display = [
        'student_name', 'intervention_date', 'intervention_type',
        'conducted_by', 'status', 'follow_up_date',
    ]
    list_filter = ['status', 'intervention_type', 'intervention_date']
    search_fields = [
        'enrollment__student__lrn',
        'enrollment__student__last_name',
        'description',
    ]
    raw_id_fields = ['enrollment', 'conducted_by']

    def student_name(self, obj):
        return obj.enrollment.student.full_name
    student_name.short_description = 'Student'


@admin.register(SF2AttendanceReport)
class SF2AttendanceReportAdmin(admin.ModelAdmin):
    list_display = [
        'section', 'school_year', 'report_month', 'report_year',
        'total_enrollment', 'average_attendance_rate', 'status', 'prepared_by',
    ]
    list_filter = ['status', 'school_year', 'quarter', 'is_submitted_to_division']
    search_fields = [
        'section__section_name',
        'prepared_by__first_name',
        'prepared_by__last_name',
    ]
    raw_id_fields = ['section', 'school_year', 'quarter', 'prepared_by', 'reviewed_by']