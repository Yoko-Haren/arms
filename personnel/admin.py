# personnel/admin.py
from django.contrib import admin
from django.utils import timezone
from .models import (
    TeacherLicense,
    TeacherEducation,
    TeacherTraining,
    TeacherServiceRecord,
    TeacherAdvisoryHistory,
)


@admin.register(TeacherLicense)
class TeacherLicenseAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'license_type', 'license_number', 'date_issued',
        'date_expiry', 'is_expired', 'is_verified',
    ]
    list_filter = ['license_type', 'is_verified']
    search_fields = [
        'user__first_name', 'user__last_name', 'license_number',
        'user__profile__employee_number',
    ]

    def is_expired(self, obj):
        if obj.date_expiry and obj.date_expiry < timezone.now().date():
            return True
        return False
    is_expired.boolean = True
    is_expired.short_description = 'Expired'


@admin.register(TeacherEducation)
class TeacherEducationAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'degree', 'major', 'institution',
        'year_graduated', 'is_highest_degree', 'is_verified',
    ]
    list_filter = ['is_highest_degree', 'is_verified', 'year_graduated']
    search_fields = [
        'user__first_name', 'user__last_name', 'degree',
        'major', 'institution',
    ]


@admin.register(TeacherTraining)
class TeacherTrainingAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'training_title', 'training_type', 'date_start',
        'date_end', 'hours_completed', 'is_cpd_accredited',
    ]
    list_filter = ['training_type', 'is_cpd_accredited', 'date_start']
    search_fields = [
        'user__first_name', 'user__last_name', 'training_title',
        'training_provider',
    ]


@admin.register(TeacherServiceRecord)
class TeacherServiceRecordAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'school_year', 'assignment', 'section_count',
        'performance_rating', 'adjectival_rating', 'is_completed',
    ]
    list_filter = ['school_year', 'is_completed', 'adjectival_rating']
    search_fields = [
        'user__first_name', 'user__last_name', 'assignment',
        'ancillary_designation',
    ]


@admin.register(TeacherAdvisoryHistory)
class TeacherAdvisoryHistoryAdmin(admin.ModelAdmin):
    list_display = [
        'user', 'section', 'school_year', 'date_assigned',
        'date_relieved', 'is_current',
    ]
    list_filter = ['is_current', 'school_year']
    search_fields = [
        'user__first_name', 'user__last_name',
        'section__section_name',
    ]