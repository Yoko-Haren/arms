# students/admin.py
from django.contrib import admin
from .models import (
    Student,
    StudentAddress,
    StudentContact,
    StudentMedical,
    StudentLearningSupport,
    Guardian,
    GuardianContact,
    SiblingEnrollment,
    StudentDocument,
)


class StudentAddressInline(admin.TabularInline):
    model = StudentAddress
    extra = 1
    fields = ['address_type', 'house_number_street', 'barangay', 'city_municipality', 'province', 'region', 'is_primary']


class StudentContactInline(admin.TabularInline):
    model = StudentContact
    extra = 1
    fields = ['contact_type', 'contact_value', 'is_primary', 'is_verified', 'can_receive_sms']


class GuardianInline(admin.TabularInline):
    model = Guardian
    extra = 1
    fields = ['first_name', 'last_name', 'relationship', 'is_primary_guardian', 'occupation', 'contact_number_display']
    readonly_fields = ['contact_number_display']
    show_change_link = True

    def contact_number_display(self, obj):
        if obj and obj.pk:
            primary = obj.contacts.filter(is_primary=True).first()
            if primary:
                return primary.contact_value
        return '-'
    contact_number_display.short_description = 'Primary Contact'


@admin.register(Student)
class StudentAdmin(admin.ModelAdmin):
    list_display = [
        'lrn', 'last_name', 'first_name', 'middle_name', 'name_extension',
        'sex', 'birth_date', 'is_active', 'is_verified', 'created_at',
    ]
    list_filter = ['sex', 'is_active', 'is_verified', 'is_ip', 'is_4ps', 'has_disability']
    search_fields = ['lrn', 'first_name', 'middle_name', 'last_name', 'psa_birth_certificate_number']
    readonly_fields = ['created_at', 'updated_at', 'created_by', 'updated_by', 'verified_by', 'verified_at']
    inlines = [StudentAddressInline, StudentContactInline, GuardianInline]
    fieldsets = (
        ('Learner Identity', {
            'fields': (
                'lrn', 'first_name', 'middle_name', 'last_name', 'name_extension',
                'birth_date', 'birth_place', 'sex', 'gender_identity', 'nationality',
            ),
        }),
        ('Cultural & Social Profile', {
            'fields': (
                'mother_tongue', 'ethnicity', 'is_ip', 'religion',
                'has_disability', 'disability_type', 'is_4ps', '_4ps_household_id',
            ),
        }),
        ('Verification & Status', {
            'fields': (
                'psa_birth_certificate_number', 'is_active', 'is_verified',
                'verified_by', 'verified_at', 'notes',
            ),
        }),
        ('Photo', {
            'fields': ('photo',),
        }),
        ('Audit Trail', {
            'fields': ('created_by', 'created_at', 'updated_by', 'updated_at'),
        }),
    )

    def save_model(self, request, obj, form, change):
        if not change:
            obj.created_by = request.user
        obj.updated_by = request.user
        super().save_model(request, obj, form, change)


@admin.register(StudentAddress)
class StudentAddressAdmin(admin.ModelAdmin):
    list_display = ['student', 'address_type', 'barangay', 'city_municipality', 'province', 'is_primary']
    list_filter = ['address_type', 'province', 'region', 'is_primary']
    search_fields = ['student__lrn', 'student__last_name', 'barangay', 'city_municipality']


@admin.register(StudentContact)
class StudentContactAdmin(admin.ModelAdmin):
    list_display = ['student', 'contact_type', 'contact_value', 'is_primary', 'is_verified', 'can_receive_sms']
    list_filter = ['contact_type', 'is_primary', 'is_verified', 'can_receive_sms']
    search_fields = ['student__lrn', 'contact_value']


@admin.register(StudentMedical)
class StudentMedicalAdmin(admin.ModelAdmin):
    list_display = ['student', 'blood_type', 'is_fit_for_physical_activity', 'last_physical_exam_date']
    list_filter = ['blood_type', 'is_fit_for_physical_activity']
    search_fields = ['student__lrn', 'student__last_name', 'allergies', 'chronic_conditions']


@admin.register(StudentLearningSupport)
class StudentLearningSupportAdmin(admin.ModelAdmin):
    list_display = ['student', 'support_type', 'start_date', 'end_date', 'is_active']
    list_filter = ['support_type', 'is_active']
    search_fields = ['student__lrn', 'support_description', 'provider']


class GuardianContactInline(admin.TabularInline):
    model = GuardianContact
    extra = 1
    fields = ['contact_type', 'contact_value', 'is_primary', 'can_receive_sms', 'is_verified']


@admin.register(Guardian)
class GuardianAdmin(admin.ModelAdmin):
    list_display = ['first_name', 'last_name', 'relationship', 'student', 'is_primary_guardian', 'occupation']
    list_filter = ['relationship', 'is_primary_guardian', 'is_living_with_student', 'educational_attainment']
    search_fields = ['first_name', 'last_name', 'student__lrn', 'student__last_name', 'occupation', 'employer']
    inlines = [GuardianContactInline]


@admin.register(GuardianContact)
class GuardianContactAdmin(admin.ModelAdmin):
    list_display = ['guardian', 'contact_type', 'contact_value', 'is_primary', 'can_receive_sms', 'is_verified']
    list_filter = ['contact_type', 'is_primary', 'is_verified', 'can_receive_sms']
    search_fields = ['guardian__first_name', 'guardian__last_name', 'contact_value']


@admin.register(SiblingEnrollment)
class SiblingEnrollmentAdmin(admin.ModelAdmin):
    list_display = ['student_1', 'student_2', 'relationship', 'school_year', 'is_verified']
    list_filter = ['relationship', 'school_year', 'is_verified']
    search_fields = ['student_1__lrn', 'student_2__lrn', 'student_1__last_name', 'student_2__last_name']


@admin.register(StudentDocument)
class StudentDocumentAdmin(admin.ModelAdmin):
    list_display = ['student', 'document_type', 'file_name', 'is_submitted', 'is_verified', 'submission_date']
    list_filter = ['document_type', 'is_submitted', 'is_verified']
    search_fields = ['student__lrn', 'student__last_name', 'file_name']
    readonly_fields = ['verified_by', 'verified_at']