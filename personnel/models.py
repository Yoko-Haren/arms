# personnel/models.py
"""
Phase 2: Teacher personnel models for Formify LIS.
Licenses, education, training, service records, and advisory history.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone


# =============================================================================
# B.1 — TeacherLicense
# =============================================================================
class TeacherLicense(models.Model):
    LICENSE_TYPE_CHOICES = [
        ('LET', 'Licensure Examination for Teachers'),
        ('PBET', 'Philippine Board Examination for Teachers'),
        ('Career_Service', 'Career Service Professional'),
        ('Bar_Board', 'Bar/Board Examination'),
        ('NC_II', 'TESDA NC II / NC III'),
        ('Other', 'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='licenses',
        help_text='The teacher who holds this license.',
    )
    license_type = models.CharField(max_length=30, choices=LICENSE_TYPE_CHOICES)
    license_number = models.CharField(
        max_length=50,
        help_text='PRC License number or equivalent.',
    )
    date_issued = models.DateField(null=True, blank=True)
    date_expiry = models.DateField(
        null=True,
        blank=True,
        help_text='For renewal tracking. PRC licenses require renewal every 3 years.',
    )
    is_verified = models.BooleanField(
        default=False,
        help_text='Has the Registrar verified this license against PRC records?',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_licenses',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    file = models.FileField(
        upload_to='personnel/licenses/%Y/%m/',
        null=True,
        blank=True,
        help_text='Scanned copy of the license certificate.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__last_name', '-date_issued']
        verbose_name = 'Teacher License'
        verbose_name_plural = 'Teacher Licenses'
        indexes = [
            models.Index(fields=['license_type']),
            models.Index(fields=['date_expiry']),
        ]

    def clean(self):
        if self.date_issued and self.date_expiry and self.date_expiry <= self.date_issued:
            raise ValidationError({
                'date_expiry': 'Expiry date must be after the issue date.',
            })

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.get_license_type_display()}: {self.license_number}"


# =============================================================================
# B.2 — TeacherEducation
# =============================================================================
class TeacherEducation(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='education_records',
    )
    degree = models.CharField(
        max_length=150,
        help_text="e.g., 'Bachelor of Secondary Education', 'Master of Arts in Education'.",
    )
    major = models.CharField(
        max_length=150,
        blank=True,
        help_text="e.g., 'Major in Science', 'Major in Mathematics'.",
    )
    institution = models.CharField(
        max_length=255,
        help_text='College or university name.',
    )
    year_graduated = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        validators=[MinValueValidator(1900), MaxValueValidator(2100)],
    )
    honors_received = models.CharField(
        max_length=150,
        blank=True,
        help_text="e.g., 'Cum Laude', 'Magna Cum Laude', 'Summa Cum Laude', 'With Distinction'.",
    )
    is_highest_degree = models.BooleanField(
        default=False,
        help_text="Is this the teacher's highest educational attainment?",
    )
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_education_records',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    file = models.FileField(
        upload_to='personnel/education/%Y/%m/',
        null=True,
        blank=True,
        help_text='Scanned diploma or transcript.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__last_name', '-year_graduated']
        verbose_name = 'Teacher Education Record'
        verbose_name_plural = 'Teacher Education Records'

    def save(self, *args, **kwargs):
        if self.is_highest_degree:
            TeacherEducation.objects.filter(
                user=self.user,
                is_highest_degree=True,
            ).exclude(pk=self.pk).update(is_highest_degree=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.degree} ({self.institution})"


# =============================================================================
# B.3 — TeacherTraining
# =============================================================================
class TeacherTraining(models.Model):
    TRAINING_TYPE_CHOICES = [
        ('Seminar', 'Seminar'),
        ('Workshop', 'Workshop / Hands-on Training'),
        ('Conference', 'Conference'),
        ('Online_Course', 'Online Course / MOOC'),
        ('Graduate_Study', 'Graduate Study'),
        ('INSET', 'In-Service Training (INSET)'),
        ('LAC', 'Learning Action Cell (LAC) Session'),
        ('Coaching', 'Coaching / Mentoring'),
        ('Other', 'Other'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='trainings',
    )
    training_title = models.CharField(
        max_length=255,
        help_text="e.g., 'Division Training on RPMS-PPST for Teachers'.",
    )
    training_provider = models.CharField(
        max_length=255,
        blank=True,
        help_text="e.g., 'DepEd Division of Davao City', 'NEAP', 'SEAMEO INNOTECH'.",
    )
    training_type = models.CharField(max_length=30, choices=TRAINING_TYPE_CHOICES)
    date_start = models.DateField()
    date_end = models.DateField(
        null=True,
        blank=True,
        help_text='Same as date_start for single-day events.',
    )
    hours_completed = models.DecimalField(
        max_digits=6,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Total CPD units or training hours earned.',
    )
    is_cpd_accredited = models.BooleanField(
        default=False,
        help_text='Is this training accredited by PRC for CPD units?',
    )
    cpd_accreditation_number = models.CharField(max_length=50, blank=True)
    certificate_file = models.FileField(
        upload_to='personnel/trainings/%Y/%m/',
        null=True,
        blank=True,
        help_text='Scanned certificate of completion.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['user__last_name', '-date_start']
        verbose_name = 'Teacher Training Record'
        verbose_name_plural = 'Teacher Training Records'
        indexes = [
            models.Index(fields=['date_start']),
            models.Index(fields=['training_type']),
        ]

    def clean(self):
        if self.date_start and self.date_end and self.date_end < self.date_start:
            raise ValidationError({
                'date_end': 'End date must be on or after the start date.',
            })

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.training_title} ({self.date_start})"


# =============================================================================
# B.4 — TeacherServiceRecord
# =============================================================================
class TeacherServiceRecord(models.Model):
    ADJECTIVAL_RATING_CHOICES = [
        ('', 'Not Rated'),
        ('Outstanding', 'Outstanding (4.50-5.00)'),
        ('Very_Satisfactory', 'Very Satisfactory (3.50-4.49)'),
        ('Satisfactory', 'Satisfactory (2.50-3.49)'),
        ('Unsatisfactory', 'Unsatisfactory (1.50-2.49)'),
        ('Poor', 'Poor (Below 1.50)'),
    ]

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='service_records',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='teacher_service_records',
    )
    assignment = models.CharField(
        max_length=255,
        help_text="e.g., 'Grade 7 Science Teacher', 'Grade 11-STEM Physics Teacher'.",
    )
    grade_levels_handled = models.CharField(
        max_length=100,
        blank=True,
        help_text="e.g., 'Grade 7, Grade 8' or 'Grade 11, Grade 12'.",
    )
    section_count = models.PositiveSmallIntegerField(
        default=0,
        help_text='Number of sections handled this school year.',
    )
    total_teaching_hours_per_week = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='Sum of all class contact hours per week.',
    )
    ancillary_designation = models.CharField(
        max_length=150,
        blank=True,
        help_text="e.g., 'Grade Level Chairperson', 'Science Department Head', 'Sports Coordinator', 'Yes-O Adviser'.",
    )
    performance_rating = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text='RPMS overall numerical rating for this school year (e.g., 4.25).',
    )
    adjectival_rating = models.CharField(
        max_length=30,
        blank=True,
        choices=ADJECTIVAL_RATING_CHOICES,
    )
    awards_received = models.TextField(
        blank=True,
        help_text="e.g., 'Outstanding Teacher of the Year, Division Level'.",
    )
    is_completed = models.BooleanField(
        default=False,
        help_text='Has this service year been completed and verified?',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'school_year']]
        ordering = ['user__last_name', '-school_year__year_start']
        verbose_name = 'Teacher Service Record'
        verbose_name_plural = 'Teacher Service Records'

    def __str__(self):
        return f"{self.user.get_full_name()} — {self.school_year.year_label}: {self.assignment}"


# =============================================================================
# B.5 — TeacherAdvisoryHistory
# =============================================================================
class TeacherAdvisoryHistory(models.Model):
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='advisory_history',
        help_text='The teacher who served as adviser.',
    )
    section = models.ForeignKey(
        'academics.Section',
        on_delete=models.CASCADE,
        related_name='adviser_history',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='adviser_assignments',
    )
    date_assigned = models.DateField(
        null=True,
        blank=True,
        help_text='When the teacher became adviser of this section.',
    )
    date_relieved = models.DateField(
        null=True,
        blank=True,
        help_text='When the teacher stopped being adviser (transferred, promoted, etc.).',
    )
    is_current = models.BooleanField(
        default=True,
        db_index=True,
        help_text='Currently active advisory? Set False when relieved.',
    )
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['user', 'section', 'school_year']]
        ordering = ['-school_year__year_start', 'user__last_name']
        verbose_name = 'Teacher Advisory History'
        verbose_name_plural = 'Teacher Advisory History'
        indexes = [
            models.Index(fields=['is_current']),
        ]

    def clean(self):
        if self.is_current:
            existing = TeacherAdvisoryHistory.objects.filter(
                user=self.user,
                is_current=True,
            )
            if self.pk:
                existing = existing.exclude(pk=self.pk)
            if existing.exists():
                raise ValidationError({
                    'is_current': 'This teacher already has a current advisory assignment.',
                })
        if self.date_relieved and self.is_current:
            raise ValidationError({
                'is_current': 'is_current must be False if date_relieved is set.',
            })
        if self.date_assigned and self.date_relieved and self.date_relieved < self.date_assigned:
            raise ValidationError({
                'date_relieved': 'Relieved date must be on or after assigned date.',
            })

    def __str__(self):
        return f"{self.user.get_full_name()} — Adviser of {self.section} ({self.school_year.year_label})"