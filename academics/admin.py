# academics/admin.py
from django.contrib import admin
from .models import (
    SchoolYear, AcademicCalendar, Quarter, Semester, GradeLevel,
    Track, Strand, Subject, SubjectPrerequisite, CurriculumMapping,
    Room, Section, RpmsCycle, GradeLevelEnrollmentQuota, SubjectGroup,
)


@admin.register(SchoolYear)
class SchoolYearAdmin(admin.ModelAdmin):
    list_display = ['year_label', 'date_start', 'date_end', 'is_current', 'status']
    list_filter = ['is_current', 'status']
    search_fields = ['year_label']


@admin.register(AcademicCalendar)
class AcademicCalendarAdmin(admin.ModelAdmin):
    list_display = ['event_name', 'school_year', 'event_type', 'event_start_date', 'event_end_date', 'is_suspension_of_classes']
    list_filter = ['school_year', 'event_type', 'is_suspension_of_classes', 'affects_all_grade_levels']
    search_fields = ['event_name', 'event_description']


@admin.register(Quarter)
class QuarterAdmin(admin.ModelAdmin):
    list_display = ['school_year', 'quarter_label', 'date_start', 'date_end', 'is_current_quarter', 'is_grades_locked']
    list_filter = ['school_year', 'is_current_quarter', 'is_grades_locked']
    search_fields = ['school_year__year_label']


@admin.register(Semester)
class SemesterAdmin(admin.ModelAdmin):
    list_display = ['school_year', 'semester_label', 'date_start', 'date_end', 'is_current_semester', 'is_grades_locked']
    list_filter = ['school_year', 'is_current_semester', 'is_grades_locked']
    search_fields = ['school_year__year_label']


@admin.register(GradeLevel)
class GradeLevelAdmin(admin.ModelAdmin):
    list_display = ['grade_code', 'grade_name', 'grade_number', 'level_category', 'is_senior_high', 'sort_order']
    list_filter = ['level_category', 'is_senior_high']
    search_fields = ['grade_code', 'grade_name']


@admin.register(Track)
class TrackAdmin(admin.ModelAdmin):
    list_display = ['track_code', 'track_name', 'is_active']
    list_filter = ['is_active']
    search_fields = ['track_code', 'track_name']


@admin.register(Strand)
class StrandAdmin(admin.ModelAdmin):
    list_display = ['strand_code', 'strand_name', 'track', 'is_active']
    list_filter = ['track', 'is_active']
    search_fields = ['strand_code', 'strand_name']


@admin.register(Subject)
class SubjectAdmin(admin.ModelAdmin):
    list_display = ['subject_code', 'subject_name', 'subject_category', 'grade_level', 'strand', 'is_active', 'is_grade_computed']
    list_filter = ['subject_category', 'grade_level', 'strand', 'is_active', 'is_grade_computed']
    search_fields = ['subject_code', 'subject_name', 'deped_subject_code']


@admin.register(SubjectPrerequisite)
class SubjectPrerequisiteAdmin(admin.ModelAdmin):
    list_display = ['subject', 'prerequisite_subject', 'is_corequisite', 'minimum_grade_required', 'is_active']
    list_filter = ['is_corequisite', 'is_active']
    search_fields = ['subject__subject_code', 'prerequisite_subject__subject_code']


@admin.register(CurriculumMapping)
class CurriculumMappingAdmin(admin.ModelAdmin):
    list_display = ['school_year', 'grade_level', 'strand', 'subject', 'semester', 'is_required', 'is_active']
    list_filter = ['school_year', 'grade_level', 'strand', 'semester', 'is_required', 'is_active']
    search_fields = ['subject__subject_code', 'subject__subject_name']


@admin.register(Room)
class RoomAdmin(admin.ModelAdmin):
    list_display = ['room_code', 'room_name', 'room_type', 'building', 'floor', 'capacity', 'is_active']
    list_filter = ['room_type', 'building', 'is_active', 'has_projector', 'has_airconditioning']
    search_fields = ['room_code', 'room_name', 'building']


@admin.register(Section)
class SectionAdmin(admin.ModelAdmin):
    list_display = ['section_name', 'grade_level', 'strand', 'school_year', 'adviser', 'current_enrollment_count', 'max_capacity', 'is_active']
    list_filter = ['school_year', 'grade_level', 'strand', 'is_active', 'is_homeroom']
    search_fields = ['section_name', 'adviser__username', 'adviser__first_name', 'adviser__last_name']


@admin.register(RpmsCycle)
class RpmsCycleAdmin(admin.ModelAdmin):
    list_display = ['cycle_label', 'school_year', 'date_start', 'date_end', 'evaluation_deadline', 'is_current_cycle', 'is_completed']
    list_filter = ['school_year', 'is_current_cycle', 'is_completed']
    search_fields = ['cycle_label']


@admin.register(GradeLevelEnrollmentQuota)
class GradeLevelEnrollmentQuotaAdmin(admin.ModelAdmin):
    list_display = ['school_year', 'grade_level', 'current_enrollee_count', 'total_quota', 'is_enrollment_open']
    list_filter = ['school_year', 'grade_level', 'is_enrollment_open']
    search_fields = ['school_year__year_label', 'grade_level__grade_name']


@admin.register(SubjectGroup)
class SubjectGroupAdmin(admin.ModelAdmin):
    list_display = ['group_name', 'grade_level', 'strand', 'is_active']
    list_filter = ['grade_level', 'strand', 'is_active']
    search_fields = ['group_name']
    filter_horizontal = ['subjects']