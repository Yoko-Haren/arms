"""
Phase 0, 2 & 13: Foundation, User Profile, and Audit Support models for Formify LIS.
Zero-dependency reference tables, system configuration, permissions,
DepEd compliance data, user profiles, and audit support (login attempts,
session logs, password resets).
"""

from datetime import date

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver
from django.utils import timezone


# =============================================================================
# USER PROFILE — WITH SCHOOL FOREIGN KEY
# =============================================================================
class UserProfile(models.Model):
    ROLE_CHOICES = [
        ('admin', 'System Administrator'),
        ('schoolhead', 'School Head / Principal'),
        ('registrar', 'School Registrar'),
        ('teacher', 'Teacher'),
        ('guidance', 'Guidance Counselor'),
        ('librarian', 'Librarian'),
        ('clinic', 'Clinic Staff'),
        ('utility', 'Utility Staff'),
        ('other', 'Other'),
    ]
    EMPLOYMENT_STATUS_CHOICES = [
        ('Regular_Permanent', 'Regular Permanent'),
        ('Regular_Provisional', 'Regular Provisional'),
        ('Probationary', 'Probationary'),
        ('Substitute', 'Substitute'),
        ('Part_Time', 'Part-Time'),
        ('Contractual', 'Contractual / Contract of Service'),
        ('LGU_Funded', 'LGU-Funded'),
    ]
    EDUCATIONAL_ATTAINMENT_CHOICES = [
        ('', 'Unknown'),
        ('Bachelors', "Bachelor's Degree"),
        ('Masters_Units', "Master's Degree — With Units"),
        ('Masters', "Master's Degree"),
        ('Doctorate_Units', 'Doctorate — With Units'),
        ('Doctorate', 'Doctorate Degree'),
    ]

    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='profile',
        help_text='One profile per user account.',
    )
    role = models.CharField(
        max_length=30,
        choices=ROLE_CHOICES,
        db_index=True,
        help_text='Primary role in the school. Determines permissions and UI access.',
    )
    
    # ===== NEW: School ForeignKey for multi-school segregation =====
    # Django auto-creates 'school_id' column for this FK
    school = models.ForeignKey(
        'academics.School',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='staff_profiles',
        db_index=True,
        help_text='Assigned school for role-based data access. NULL for system admins.',
    )
    
    deped_email = models.EmailField(
        unique=True,
        null=True,
        blank=True,
        help_text='Official school email address.',
    )
    institutional_email = models.EmailField(
        null=True,
        blank=True,
        help_text='School-provided email for non-DepEd staff.',
    )
    employee_number = models.CharField(
        max_length=50,
        unique=True,
        null=True,
        blank=True,
        help_text='DepEd Employee Number or school-assigned personnel ID.',
    )
    designation = models.CharField(
        max_length=150,
        blank=True,
        help_text="e.g., 'Teacher III', 'School Registrar', 'Principal IV'.",
    )
    position_title = models.CharField(
        max_length=150,
        blank=True,
        help_text="Official item title: 'Teacher I', 'Master Teacher II', 'Head Teacher III'.",
    )
    salary_grade = models.CharField(
        max_length=10,
        blank=True,
        help_text="e.g., 'SG-11', 'SG-13', 'SG-19'.",
    )
    teaching_area = models.CharField(
        max_length=150,
        blank=True,
        help_text="Primary subject area.",
    )
    specialization = models.CharField(
        max_length=255,
        blank=True,
        help_text="Specific expertise.",
    )
    employment_status = models.CharField(
        max_length=30,
        blank=True,
        choices=EMPLOYMENT_STATUS_CHOICES,
    )
    date_hired = models.DateField(null=True, blank=True)
    date_regularized = models.DateField(null=True, blank=True)
    years_of_service = models.PositiveSmallIntegerField(default=0)
    educational_attainment = models.CharField(
        max_length=100, blank=True, choices=EDUCATIONAL_ATTAINMENT_CHOICES
    )
    is_homeroom_adviser = models.BooleanField(default=False)
    profile_photo = models.ImageField(upload_to='personnel/photos/%Y/%m/', null=True, blank=True)
    digital_signature = models.ImageField(upload_to='personnel/signatures/', null=True, blank=True)
    
    # ===== RENAMED: Was 'school_id', now 'beis_school_id' =====
    beis_school_id = models.CharField(
        max_length=20,
        blank=True,
        help_text='BEIS School ID — for LIS interoperability and DepEd reporting.',
    )
    
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__last_name', 'user__first_name']
        verbose_name = 'User Profile'
        verbose_name_plural = 'User Profiles'
        indexes = [
            models.Index(fields=['role']),
            models.Index(fields=['is_active']),
            models.Index(fields=['school', 'role']),
        ]

    @property
    def full_name(self):
        return f"{self.user.first_name} {self.user.last_name}".strip() or self.user.username

    @property
    def is_teacher(self):
        return self.role == 'teacher'

    @property
    def is_principal(self):
        return self.role == 'schoolhead'
    
    @property
    def is_registrar(self):
        return self.role == 'registrar'

    @property
    def can_approve(self):
        return self.role in ['admin', 'schoolhead', 'registrar']
    
    @property
    def school_name(self):
        return self.school.school_name if self.school else 'Not Assigned'

    def clean(self):
        super().clean()
        if self.role != 'admin' and not self.school:
            raise ValidationError({
                'school': f'Staff with role "{self.get_role_display()}" must be assigned to a school.'
            })

    def save(self, *args, **kwargs):
        if self.date_hired and not self.years_of_service:
            self.years_of_service = date.today().year - self.date_hired.year
        super().save(*args, **kwargs)

    def __str__(self):
        school_info = f" @ {self.school.name}" if self.school else ""
        return f"{self.user.get_full_name()} — {self.get_role_display()}{school_info}"


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def create_user_profile(sender, instance, created, **kwargs):
    if created:
        UserProfile.objects.create(user=instance)


@receiver(post_save, sender=settings.AUTH_USER_MODEL)
def save_user_profile(sender, instance, **kwargs):
    if hasattr(instance, 'profile'):
        instance.profile.save()


# =============================================================================
# 0.1 — SystemSettings
# =============================================================================
class SystemSettings(models.Model):
    SETTING_TYPES = [
        ("String", "String"),
        ("Integer", "Integer"),
        ("Boolean", "Boolean"),
        ("JSON", "JSON"),
        ("Date", "Date"),
    ]
    CATEGORY_CHOICES = [
        ("General", "General"),
        ("Academic", "Academic"),
        ("Grading", "Grading"),
        ("Enrollment", "Enrollment"),
        ("Notification", "Notification"),
        ("Security", "Security"),
        ("UI", "UI"),
    ]

    key = models.CharField(max_length=100, unique=True, db_index=True)
    value = models.TextField()
    value_type = models.CharField(max_length=20, choices=SETTING_TYPES, default="String")
    description = models.TextField(blank=True)
    category = models.CharField(max_length=30, choices=CATEGORY_CHOICES, default="General")
    is_editable = models.BooleanField(default=True)
    is_public = models.BooleanField(default=False)
    updated_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="updated_settings",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "key"]
        verbose_name_plural = "System Settings"
        indexes = [models.Index(fields=["category"]), models.Index(fields=["is_editable"])]

    def __str__(self):
        return self.key


# =============================================================================
# 0.2 — SchoolProfile
# =============================================================================
class SchoolProfile(models.Model):
    SCHOOL_TYPE_CHOICES = [
        ("Public", "Public"),
        ("Private", "Private"),
        ("SUC", "State University & College"),
        ("LUC", "Local University & College"),
        ("CHED", "CHED Institution"),
    ]

    school_id = models.CharField(max_length=20, unique=True)
    school_name = models.CharField(max_length=200)
    school_short_name = models.CharField(max_length=50, blank=True)
    school_type = models.CharField(max_length=20, choices=SCHOOL_TYPE_CHOICES)
    region_code = models.CharField(max_length=20)
    division_code = models.CharField(max_length=50)
    district = models.CharField(max_length=100, blank=True)
    complete_address = models.TextField()
    contact_number = models.CharField(max_length=20, blank=True)
    official_email = models.EmailField(blank=True)
    website_url = models.URLField(blank=True)
    school_head_name = models.CharField(max_length=150, blank=True)
    school_head_position = models.CharField(max_length=100, blank=True)
    school_head_deped_email = models.EmailField(blank=True)
    school_logo = models.ImageField(upload_to="school/logos/", blank=True, null=True)
    current_school_year = models.CharField(max_length=9, blank=True)
    lis_api_endpoint = models.URLField(blank=True)
    lis_api_key = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "School Profile"

    def save(self, *args, **kwargs):
        if not self.pk and SchoolProfile.objects.exists():
            raise ValidationError("Only one school profile can exist. Update the existing record.")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.school_name} ({self.school_id})"


# =============================================================================
# 0.3 — RolePermission
# =============================================================================
class RolePermission(models.Model):
    MODULE_CHOICES = [
        ("Students", "Students"), ("Enrollment", "Enrollment"),
        ("Grades", "Grades"), ("Forms", "Forms"),
        ("Transfers", "Transfers"), ("Reports", "Reports"),
        ("Settings", "Settings"), ("Users", "Users"),
        ("Attendance", "Attendance"), ("Scheduling", "Scheduling"),
        ("Communication", "Communication"), ("Audit", "Audit"), ("All", "All"),
    ]
    RISK_LEVEL_CHOICES = [
        ("Low", "Low"), ("Medium", "Medium"),
        ("High", "High"), ("Critical", "Critical"),
    ]

    code = models.CharField(max_length=80, unique=True, db_index=True)
    name = models.CharField(max_length=150)
    description = models.TextField(blank=True)
    module = models.CharField(max_length=40, choices=MODULE_CHOICES, db_index=True)
    is_deped_sensitive = models.BooleanField(default=False)
    risk_level = models.CharField(max_length=20, choices=RISK_LEVEL_CHOICES, default="Low")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["module", "code"]
        verbose_name_plural = "Role Permissions"

    def __str__(self):
        return f"{self.code} ({self.name})"


# =============================================================================
# 0.4 — PermissionAssignment
# =============================================================================
class PermissionAssignment(models.Model):
    ROLE_CHOICES = [
        ("Admin", "Admin"), ("Registrar", "Registrar"),
        ("Principal", "Principal"), ("Teacher", "Teacher"),
        ("Guidance Counselor", "Guidance Counselor"),
        ("Class Adviser", "Class Adviser"),
        ("Subject Teacher", "Subject Teacher"),
        ("LIS Coordinator", "LIS Coordinator"),
    ]

    role = models.CharField(max_length=50, db_index=True)
    role_display_name = models.CharField(max_length=100)
    permission = models.ForeignKey(RolePermission, on_delete=models.CASCADE, related_name="assignments")
    is_granted = models.BooleanField(default=True)
    assigned_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL,
        null=True, blank=True, related_name="permission_grants",
    )
    assigned_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ["role", "permission"]
        ordering = ["role", "permission__code"]
        verbose_name_plural = "Permission Assignments"

    def __str__(self):
        return f"{self.role} → {self.permission.code}"


# =============================================================================
# 0.5 — GradeTransmutationTable
# =============================================================================
class GradeTransmutationTable(models.Model):
    GRADE_CAT = [("JHS", "Junior High School"), ("SHS", "Senior High School"), ("All", "All Levels")]
    SUBJ_CAT = [("Core", "Core"), ("Applied", "Applied"), ("Specialized", "Specialized"), ("Elective", "Elective"), ("All", "All")]

    grade_level_category = models.CharField(max_length=10, choices=GRADE_CAT, default="All", db_index=True)
    subject_category = models.CharField(max_length=20, choices=SUBJ_CAT, default="All", db_index=True)
    initial_grade_min = models.DecimalField(max_digits=5, decimal_places=2)
    initial_grade_max = models.DecimalField(max_digits=5, decimal_places=2)
    transmuted_grade = models.DecimalField(max_digits=5, decimal_places=2)
    deped_order_reference = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["grade_level_category", "subject_category", "initial_grade_min"]
        verbose_name_plural = "Grade Transmutation Tables"
        indexes = [models.Index(fields=["is_active", "grade_level_category", "subject_category"])]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(initial_grade_min__lte=models.F("initial_grade_max")),
                name="chk_initial_grade_min_lte_max",
            ),
        ]
    def __str__(self):
        return f"[{self.grade_level_category}/{self.subject_category}] {self.initial_grade_min}-{self.initial_grade_max} → {self.transmuted_grade}"


# =============================================================================
# 0.6 — GradeComponentWeight
# =============================================================================
class GradeComponentWeight(models.Model):
    GRADE_CAT = [("JHS", "Junior High School"), ("SHS", "Senior High School"), ("All", "All Levels")]
    SUBJ_CAT = [("Core", "Core"), ("Applied", "Applied"), ("Specialized", "Specialized"), ("Elective", "Elective"), ("All", "All")]
    COMP_TYPES = [
        ("Written_Work", "Written Work"),
        ("Performance_Task", "Performance Task"),
        ("Quarterly_Assessment", "Quarterly Assessment"),
    ]

    grade_level_category = models.CharField(max_length=10, choices=GRADE_CAT, db_index=True)
    subject_category = models.CharField(max_length=20, choices=SUBJ_CAT, db_index=True)
    component_type = models.CharField(max_length=25, choices=COMP_TYPES)
    percentage_weight = models.DecimalField(max_digits=5, decimal_places=2)
    deped_order_reference = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ["grade_level_category", "subject_category", "component_type"]
        ordering = ["grade_level_category", "subject_category", "component_type"]
        verbose_name_plural = "Grade Component Weights"

    def __str__(self):
        return f"[{self.grade_level_category}/{self.subject_category}] {self.get_component_type_display()}: {self.percentage_weight}%"


# =============================================================================
# 0.7 — SchoolForm
# =============================================================================
class SchoolForm(models.Model):
    FREQ = [("Daily", "Daily"), ("Monthly", "Monthly"), ("Quarterly", "Quarterly"),
            ("Yearly", "Yearly"), ("On_Demand", "On Demand"), ("Once", "Once Per Enrollment")]

    form_code = models.CharField(max_length=10, unique=True)
    form_name = models.CharField(max_length=200)
    form_description = models.TextField(blank=True)
    form_frequency = models.CharField(max_length=20, choices=FREQ)
    is_permanent_record = models.BooleanField(default=False)
    is_digital_signature_required = models.BooleanField(default=False)
    requires_principal_approval = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    deped_order_reference = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["form_code"]
        verbose_name_plural = "School Forms"

    def __str__(self):
        return f"{self.form_code} — {self.form_name}"


# =============================================================================
# 0.8 — NotificationTemplate
# =============================================================================
class NotificationTemplate(models.Model):
    CAT = [("Enrollment", "Enrollment"), ("Grades", "Grades"), ("Forms", "Forms"),
           ("Transfer", "Transfer"), ("Attendance", "Attendance"), ("System", "System"),
           ("Announcement", "Announcement")]
    PRI = [("Low", "Low"), ("Normal", "Normal"), ("High", "High"), ("Urgent", "Urgent")]

    code = models.CharField(max_length=60, unique=True, db_index=True)
    name = models.CharField(max_length=120)
    subject_template = models.CharField(max_length=250)
    body_template = models.TextField()
    channels = models.CharField(max_length=100, default="in_app")
    category = models.CharField(max_length=30, choices=CAT, db_index=True)
    priority = models.CharField(max_length=15, choices=PRI, default="Normal")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["category", "code"]
        verbose_name_plural = "Notification Templates"

    def __str__(self):
        return f"{self.code} — {self.name}"


# =============================================================================
# 0.9 — NotificationPreference
# =============================================================================
class NotificationPreference(models.Model):
    DIGEST = [("Instant", "Instant"), ("Hourly", "Hourly"), ("Daily", "Daily"),
              ("Weekly", "Weekly"), ("Never", "Never")]

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_preferences")
    email_enabled = models.BooleanField(default=True)
    in_app_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    digest_frequency = models.CharField(max_length=15, choices=DIGEST, default="Instant")
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    muted_categories = models.JSONField(default=list, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name_plural = "Notification Preferences"

    def __str__(self):
        return f"{self.user.get_full_name() or self.user.username} — Notification Preferences"


# =============================================================================
# 0.10 — RpmsCriteriaTemplate
# =============================================================================
class RpmsCriteriaTemplate(models.Model):
    code = models.CharField(max_length=30, unique=True)
    kra_number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    kra_name = models.CharField(max_length=150)
    objective_number = models.PositiveSmallIntegerField(validators=[MinValueValidator(1)])
    objective = models.TextField()
    means_of_verification = models.TextField()
    quality_indicator = models.TextField(blank=True)
    efficiency_indicator = models.TextField(blank=True)
    timeliness_indicator = models.TextField(blank=True)
    weight_percentage = models.DecimalField(max_digits=5, decimal_places=2)
    applicable_positions = models.TextField(default="All")
    deped_order_reference = models.CharField(max_length=100, blank=True)
    school_year_label = models.CharField(max_length=9, blank=True)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["kra_number", "objective_number"]
        verbose_name_plural = "RPMS Criteria Templates"
        indexes = [models.Index(fields=["is_active", "school_year_label"])]

    def __str__(self):
        return f"{self.code} — {self.objective[:60]}"


# =============================================================================
# 0.11 — DocumentType
# =============================================================================
class DocumentType(models.Model):
    CAT = [("Certificate", "Certificate"), ("Form_Copy", "Form Copy"),
           ("Transcript", "Transcript"), ("Diploma", "Diploma"),
           ("Letter", "Letter"), ("Other", "Other")]

    code = models.CharField(max_length=30, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    document_category = models.CharField(max_length=30, choices=CAT, default="Certificate")
    requires_approval = models.BooleanField(default=False)
    processing_fee = models.DecimalField(max_digits=8, decimal_places=2, default=0.00)
    estimated_processing_days = models.PositiveSmallIntegerField(default=1)
    requires_payment = models.BooleanField(default=False)
    max_copies_per_request = models.PositiveSmallIntegerField(default=1)
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["document_category", "name"]
        verbose_name_plural = "Document Types"

    def __str__(self):
        return f"{self.code} — {self.name}"


# =============================================================================
# 0.12 — CalendarEventType
# =============================================================================
class CalendarEventType(models.Model):
    code = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=120)
    is_instructional_day = models.BooleanField(default=True)
    is_holiday = models.BooleanField(default=False)
    is_examination = models.BooleanField(default=False)
    default_color_hex = models.CharField(max_length=7, default="#3788d8")
    sort_priority = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_priority", "name"]
        verbose_name_plural = "Calendar Event Types"

    def __str__(self):
        return f"{self.name} ({self.code})"


# =============================================================================
# 0.13 — GradeRemarksTemplate
# =============================================================================
class GradeRemarksTemplate(models.Model):
    code = models.CharField(max_length=20, unique=True)
    label = models.CharField(max_length=50)
    description = models.TextField(blank=True)
    is_passing = models.BooleanField(default=True)
    is_counted_in_average = models.BooleanField(default=True)
    sf9_display_text = models.CharField(max_length=100, blank=True)
    sort_order = models.PositiveSmallIntegerField(default=0)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["sort_order"]
        verbose_name_plural = "Grade Remarks Templates"

    def __str__(self):
        return f"{self.code} — {self.label}"


# =============================================================================
# PHASE 13 — A.1: LoginAttempt
# =============================================================================
class LoginAttempt(models.Model):
    ATTEMPT_RESULT_CHOICES = [
        ('SUCCESS', 'Success'),
        ('FAILED_INVALID_CREDENTIALS', 'Failed — Invalid Credentials'),
        ('FAILED_LOCKED', 'Failed — Account Locked'),
        ('FAILED_INACTIVE', 'Failed — Account Inactive'),
    ]

    username_attempted = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    attempt_result = models.CharField(
        max_length=30,
        choices=ATTEMPT_RESULT_CHOICES,
        db_index=True,
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='login_attempts',
        help_text='NULL if login failed (user not resolved).',
    )
    attempted_at = models.DateTimeField(default=timezone.now, db_index=True)

    class Meta:
        ordering = ['-attempted_at']
        indexes = [
            models.Index(fields=['attempt_result', 'attempted_at']),
            models.Index(fields=['ip_address', 'attempted_at']),
        ]
        verbose_name = 'Login Attempt'
        verbose_name_plural = 'Login Attempts'

    def __str__(self):
        return (
            f"Login: {self.username_attempted} — {self.get_attempt_result_display()} "
            f"({self.attempted_at.strftime('%Y-%m-%d %H:%M')})"
        )


# =============================================================================
# PHASE 13 — A.2: SessionLog
# =============================================================================
class SessionLog(models.Model):
    LOGOUT_TYPE_CHOICES = [
        ('Manual', 'Manual Logout'),
        ('Timeout', 'Session Timeout'),
        ('System', 'System Logout'),
        ('Forced_Admin', 'Forced by Admin'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='session_logs',
    )
    session_key = models.CharField(max_length=255)
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    login_at = models.DateTimeField(default=timezone.now, db_index=True)
    logout_at = models.DateTimeField(null=True, blank=True)
    duration_seconds = models.PositiveIntegerField(
        null=True,
        blank=True,
        help_text='Auto-calculated: logout_at - login_at in seconds.',
    )
    logout_type = models.CharField(
        max_length=20,
        blank=True,
        choices=LOGOUT_TYPE_CHOICES,
    )

    class Meta:
        ordering = ['-login_at']
        indexes = [
            models.Index(fields=['user', 'login_at']),
            models.Index(fields=['session_key']),
        ]
        verbose_name = 'Session Log'
        verbose_name_plural = 'Session Logs'

    @property
    def is_active(self):
        return self.logout_at is None

    @property
    def duration_display(self):
        if self.duration_seconds is None:
            return 'Active'
        minutes = self.duration_seconds // 60
        hours = minutes // 60
        minutes = minutes % 60
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def save(self, *args, **kwargs):
        if self.logout_at and self.duration_seconds is None:
            delta = self.logout_at - self.login_at
            self.duration_seconds = int(delta.total_seconds())
        super().save(*args, **kwargs)

    def __str__(self):
        status = 'Active' if self.is_active else 'Ended'
        return (
            f"Session: {self.user.get_full_name()} — "
            f"{self.login_at.strftime('%Y-%m-%d %H:%M')} — {status}"
        )


# =============================================================================
# PHASE 13 — A.3: PasswordReset
# =============================================================================
class PasswordReset(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='password_resets',
    )
    token_hash = models.CharField(
        max_length=128,
        help_text='SHA-256 hash of the reset token.',
    )
    ip_address = models.GenericIPAddressField()
    user_agent = models.TextField(blank=True)
    requested_at = models.DateTimeField(default=timezone.now, db_index=True)
    expires_at = models.DateTimeField(
        help_text='Token expiry — typically 24 hours after request.',
    )
    used_at = models.DateTimeField(null=True, blank=True)
    is_used = models.BooleanField(default=False, db_index=True)

    class Meta:
        ordering = ['-requested_at']
        indexes = [
            models.Index(fields=['user', 'requested_at']),
        ]
        verbose_name = 'Password Reset'
        verbose_name_plural = 'Password Resets'

    @property
    def is_expired(self):
        return not self.is_used and timezone.now() > self.expires_at

    def __str__(self):
        status = 'Used' if self.is_used else 'Pending'
        return (
            f"Password Reset: {self.user.get_full_name()} — "
            f"{self.requested_at.strftime('%Y-%m-%d %H:%M')} — {status}"
        )
