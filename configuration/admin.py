# configuration/admin.py
from django.contrib import admin
from .models import DepEdConfiguration, GradingPeriod


@admin.register(DepEdConfiguration)
class DepEdConfigurationAdmin(admin.ModelAdmin):
    list_display = [
        'config_key', 'category', 'config_type',
        'is_required', 'is_encrypted', 'updated_at',
    ]
    list_filter = ['category', 'config_type', 'is_required', 'is_encrypted']
    search_fields = ['config_key', 'description']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('Configuration', {
            'fields': (
                'config_key', 'config_value', 'config_type',
                'category', 'description',
            ),
        }),
        ('Flags', {
            'fields': ('is_required', 'is_encrypted', 'validation_regex'),
        }),
        ('Audit', {
            'fields': ('updated_by', 'created_at', 'updated_at'),
        }),
    )


@admin.register(GradingPeriod)
class GradingPeriodAdmin(admin.ModelAdmin):
    list_display = [
        'school_year', 'period_name', 'period_type', 'report_card_type',
        'is_grade_encoding_open', 'is_grades_locked',
        'weight_in_final_grade', 'order',
    ]
    list_filter = [
        'period_type', 'is_grade_encoding_open', 'is_grades_locked',
        'school_year', 'is_active',
    ]
    raw_id_fields = ['school_year', 'quarter', 'semester']
    readonly_fields = ['created_at', 'updated_at']
    fieldsets = (
        ('School Year & Period', {
            'fields': (
                'school_year', 'period_type', 'quarter', 'semester',
                'report_card_type', 'order',
            ),
        }),
        ('Grade Encoding', {
            'fields': (
                'is_grade_encoding_open', 'grade_encoding_deadline',
                'grade_validation_deadline', 'is_grades_locked',
            ),
        }),
        ('Weight & Status', {
            'fields': ('weight_in_final_grade', 'is_active', 'notes'),
        }),
        ('Audit', {
            'fields': ('created_at', 'updated_at'),
        }),
    )