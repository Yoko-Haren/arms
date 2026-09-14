"""
Phase 1: Academic Structure models for Formify LIS.
School years, curriculum, sections, rooms, and RPMS cycles.
"""

from builtins import dict, list, super
from locale import str
import uuid
import json
import random


from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models


# =============================================================================
# 1.0 — School (Multi-tenant support)
# =============================================================================
class School(models.Model):
    """Represents a school in the multi-tenant system"""
    GRADING_SCALE_CHOICES = [
        ('PERCENTAGE', '0-100 Percentage'),
        ('NUMERIC_1_5', '1.0 - 5.0 (1.0 highest)'),
        ('NUMERIC_5_1', '5.0 - 1.0 (5.0 highest)'),
        ('GPA_4', '0.0 - 4.0 GPA'),
        ('GPA_5', '0.0 - 5.0 GPA'),
        ('LETTER', 'A - F Letter Grades'),
    ]
    
    PERIOD_TYPE_CHOICES = [
        ('QUARTERLY', 'Quarterly - 4 periods'),
        ('SEMESTRAL', 'Semestral - 2 semesters'),
        ('TRIMESTRAL', 'Trimestral - 3 periods'),
    ]
    
    school_id = models.CharField(max_length=20, unique=True, help_text="Unique school identifier")
    school_name = models.CharField(max_length=200, help_text="Official school name")
    short_name = models.CharField(max_length=50, help_text="Abbreviated school name")
    address = models.TextField(blank=True)
    contact_number = models.CharField(max_length=20, blank=True)
    email_domain = models.CharField(max_length=100, blank=True, help_text="Optional school email domain, e.g., @school.edu")
    
    # Grading configuration for this school
    grading_scale = models.CharField(max_length=20, choices=GRADING_SCALE_CHOICES, default='PERCENTAGE')
    passing_grade = models.FloatField(default=75.0, help_text="Minimum passing grade")
    period_type = models.CharField(max_length=20, choices=PERIOD_TYPE_CHOICES, default='QUARTERLY')
    quarters_count = models.IntegerField(default=4, help_text="4 for quarterly, 3 for trimestral, 2 for semestral")
    
    # School preferences
    logo = models.ImageField(upload_to='school_logos/', null=True, blank=True)
    theme_color = models.CharField(max_length=7, default='#2c3e50', help_text="Primary theme color (hex)")
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['school_name']
        db_table = 'academics_school'
        verbose_name = 'School'
        verbose_name_plural = 'Schools'
    
    def __str__(self):
        return self.school_name


# =============================================================================
# 1.1 — SchoolYear
# =============================================================================
class SchoolYear(models.Model):
    STATUS_CHOICES = [
        ('Upcoming', 'Upcoming'),
        ('Active', 'Active'),
        ('Completed', 'Completed'),
        ('Archived', 'Archived'),
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='school_years',
        help_text="School this school year belongs to",
    )
    year_label = models.CharField(
        max_length=9,
        help_text="e.g., '2025-2026'.",
    )
    year_start = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
        help_text="The starting calendar year (e.g., 2025).",
    )
    year_end = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(2000), MaxValueValidator(2100)],
        help_text="The ending calendar year (e.g., 2026).",
    )
    date_start = models.DateField(
        help_text="First day of classes for this school year.",
    )
    date_end = models.DateField(
        help_text="Last day of classes for this school year.",
    )
    total_instructional_days = models.PositiveSmallIntegerField(
        default=200,
        help_text="Total number of instructional days as required by DepEd (minimum 200).",
    )
    is_current = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Only one school year can be current at a time per school.",
    )
    status = models.CharField(
        max_length=20,
        choices=STATUS_CHOICES,
        default='Upcoming',
        db_index=True,
    )
    enrollment_open_date = models.DateField(
        null=True,
        blank=True,
        help_text="First day of enrollment period.",
    )
    enrollment_close_date = models.DateField(
        null=True,
        blank=True,
        help_text="Last day of enrollment period.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school', 'year_label']]
        ordering = ['-year_start']
        verbose_name = 'School Year'
        verbose_name_plural = 'School Years'

    def clean(self):
        if self.date_start and self.date_end and self.date_start >= self.date_end:
            raise ValidationError({
                'date_end': 'The end date must be after the start date.',
            })
        if self.year_start and self.year_end and self.year_end != self.year_start + 1:
            raise ValidationError({
                'year_end': 'The end year must be exactly one year after the start year.',
            })
        if self.enrollment_open_date and self.enrollment_close_date:
            if self.enrollment_open_date >= self.enrollment_close_date:
                raise ValidationError({
                    'enrollment_close_date': 'Enrollment close date must be after open date.',
                })
        if self.enrollment_open_date and self.date_start:
            if self.enrollment_open_date >= self.date_start:
                raise ValidationError({
                    'enrollment_open_date': 'Enrollment should open before classes start.',
                })

    def save(self, *args, **kwargs):
        if self.is_current:
            SchoolYear.objects.filter(school=self.school, is_current=True).exclude(pk=self.pk).update(is_current=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.school.short_name} - {self.year_label}"


# =============================================================================
# 1.2 — AcademicCalendar
# =============================================================================
class AcademicCalendar(models.Model):
    school_year = models.ForeignKey(
        SchoolYear,
        on_delete=models.CASCADE,
        related_name='calendar_events',
    )
    event_type = models.ForeignKey(
        'accounts.CalendarEventType',
        on_delete=models.PROTECT,
        related_name='calendar_events',
        help_text="Type of academic calendar event.",
    )
    event_name = models.CharField(max_length=200)
    event_description = models.TextField(blank=True)
    event_start_date = models.DateField(db_index=True)
    event_end_date = models.DateField()
    is_suspension_of_classes = models.BooleanField(
        default=False,
        help_text="Indicates if classes are suspended on this day.",
    )
    affects_all_grade_levels = models.BooleanField(
        default=True,
        help_text="If True, this event applies to all grade levels.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_calendar_events',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['event_start_date']
        verbose_name = 'Academic Calendar Event'
        verbose_name_plural = 'Academic Calendar Events'

    def clean(self):
        if self.event_start_date and self.event_end_date:
            if self.event_start_date > self.event_end_date:
                raise ValidationError({
                    'event_end_date': 'End date must be on or after start date.',
                })
        if self.school_year_id:
            sy = self.school_year
            if self.event_start_date:
                if self.event_start_date < sy.date_start or self.event_start_date > sy.date_end:
                    raise ValidationError({
                        'event_start_date': f'Event date must fall within the school year ({sy.date_start} to {sy.date_end}).',
                    })
            if self.event_end_date:
                if self.event_end_date < sy.date_start or self.event_end_date > sy.date_end:
                    raise ValidationError({
                        'event_end_date': f'Event date must fall within the school year ({sy.date_start} to {sy.date_end}).',
                    })

    def __str__(self):
        return f"{self.event_name} ({self.event_start_date})"


# =============================================================================
# 1.3 — Quarter
# =============================================================================
class Quarter(models.Model):
    QUARTER_LABELS = [
        ('Q1', 'Q1'),
        ('Q2', 'Q2'),
        ('Q3', 'Q3'),
        ('Q4', 'Q4'),
    ]

    school_year = models.ForeignKey(
        SchoolYear,
        on_delete=models.CASCADE,
        related_name='quarters',
    )
    quarter_label = models.CharField(max_length=10, choices=QUARTER_LABELS)
    quarter_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(4)],
    )
    date_start = models.DateField()
    date_end = models.DateField()
    grade_encoding_deadline = models.DateTimeField(
        help_text="Deadline for teachers to submit grades for this quarter.",
    )
    grade_validation_deadline = models.DateTimeField(
        help_text="Deadline for the registrar to validate submitted grades.",
    )
    card_distribution_date = models.DateField(
        null=True,
        blank=True,
        help_text="Date when report cards (SF9) are distributed.",
    )
    is_current_quarter = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Only one quarter can be current per school year.",
    )
    is_grades_locked = models.BooleanField(
        default=False,
        help_text="When locked, grades cannot be modified without admin override.",
    )
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_quarters',
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school_year', 'quarter_number']]
        ordering = ['school_year', 'quarter_number']
        verbose_name = 'Quarter'
        verbose_name_plural = 'Quarters'

    def clean(self):
        if self.date_start and self.date_end and self.date_start >= self.date_end:
            raise ValidationError({
                'date_end': 'Quarter end date must be after start date.',
            })
        if self.school_year_id:
            sy = self.school_year
            if self.date_start and (self.date_start < sy.date_start or self.date_start > sy.date_end):
                raise ValidationError({
                    'date_start': f'Quarter start must fall within school year ({sy.date_start} to {sy.date_end}).',
                })
            if self.date_end and (self.date_end < sy.date_start or self.date_end > sy.date_end):
                raise ValidationError({
                    'date_end': f'Quarter end must fall within school year ({sy.date_start} to {sy.date_end}).',
                })

    def save(self, *args, **kwargs):
        if self.is_current_quarter:
            Quarter.objects.filter(school_year=self.school_year).exclude(pk=self.pk).update(is_current_quarter=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.school_year} — {self.quarter_label}"


# =============================================================================
# 1.4 — Semester
# =============================================================================
class Semester(models.Model):
    SEMESTER_LABELS = [
        ('1st', '1st'),
        ('2nd', '2nd'),
    ]

    school_year = models.ForeignKey(
        SchoolYear,
        on_delete=models.CASCADE,
        related_name='semesters',
    )
    semester_label = models.CharField(max_length=4, choices=SEMESTER_LABELS)
    semester_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(2)],
    )
    date_start = models.DateField()
    date_end = models.DateField()
    grade_encoding_deadline = models.DateTimeField()
    grade_validation_deadline = models.DateTimeField()
    is_current_semester = models.BooleanField(
        default=False,
        db_index=True,
    )
    is_grades_locked = models.BooleanField(default=False)
    locked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='locked_semesters',
    )
    locked_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school_year', 'semester_number']]
        ordering = ['school_year', 'semester_number']
        verbose_name = 'Semester'
        verbose_name_plural = 'Semesters'

    def clean(self):
        if self.date_start and self.date_end and self.date_start >= self.date_end:
            raise ValidationError({
                'date_end': 'Semester end date must be after start date.',
            })
        if self.school_year_id:
            sy = self.school_year
            if self.date_start and (self.date_start < sy.date_start or self.date_start > sy.date_end):
                raise ValidationError({
                    'date_start': f'Semester start must fall within school year ({sy.date_start} to {sy.date_end}).',
                })
            if self.date_end and (self.date_end < sy.date_start or self.date_end > sy.date_end):
                raise ValidationError({
                    'date_end': f'Semester end must fall within school year ({sy.date_start} to {sy.date_end}).',
                })

    def save(self, *args, **kwargs):
        if self.is_current_semester:
            Semester.objects.filter(school_year=self.school_year).exclude(pk=self.pk).update(is_current_semester=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.school_year} — {self.semester_label} Semester"


# =============================================================================
# 1.5 — GradeLevel
# =============================================================================
class GradeLevel(models.Model):
    LEVEL_CATEGORY_CHOICES = [
        ('JHS', 'Junior High School'),
        ('SHS', 'Senior High School'),
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='grade_levels',
        null=True,
        blank=True,
        help_text="School this grade level belongs to (optional for global grade levels)",
    )
    grade_code = models.CharField(
        max_length=5,
        help_text="e.g., 'G7', 'G8', 'G9', 'G10', 'G11', 'G12'.",
    )
    grade_name = models.CharField(
        max_length=50,
        help_text="e.g., 'Grade 7', 'Grade 11'.",
    )
    grade_number = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(7), MaxValueValidator(12)],
        help_text="Numeric grade level (7-12).",
    )
    level_category = models.CharField(
        max_length=20,
        choices=LEVEL_CATEGORY_CHOICES,
        help_text="JHS covers Grades 7-10, SHS covers Grades 11-12.",
    )
    is_senior_high = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Auto-set based on grade_number >= 11.",
    )
    sort_order = models.PositiveSmallIntegerField(
        help_text="Display order in lists and reports.",
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['school', 'grade_code']]
        ordering = ['sort_order']
        verbose_name = 'Grade Level'
        verbose_name_plural = 'Grade Levels'

    def clean(self):
        if self.grade_number >= 11:
            self.is_senior_high = True
            self.level_category = 'SHS'
        else:
            self.is_senior_high = False
            self.level_category = 'JHS'

    def save(self, *args, **kwargs):
        if self.grade_number >= 11:
            self.is_senior_high = True
            self.level_category = 'SHS'
        else:
            self.is_senior_high = False
            self.level_category = 'JHS'
        super().save(*args, **kwargs)

    def __str__(self):
        school_prefix = f"{self.school.short_name} - " if self.school else ""
        return f"{school_prefix}{self.grade_name}"


# =============================================================================
# 1.6 — Track
# =============================================================================
class Track(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='tracks',
        null=True,
        blank=True,
        help_text="School this track belongs to (optional for global tracks)",
    )
    track_code = models.CharField(
        max_length=20,
        help_text="e.g., 'ACADEMIC', 'TVL', 'SPORTS', 'ARTS_DESIGN'.",
    )
    track_name = models.CharField(
        max_length=100,
        help_text="e.g., 'Academic Track', 'Technical-Vocational-Livelihood'.",
    )
    track_description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['school', 'track_code']]
        ordering = ['track_name']
        verbose_name = 'Track'
        verbose_name_plural = 'Tracks'

    def __str__(self):
        school_prefix = f"{self.school.short_name} - " if self.school else ""
        return f"{school_prefix}{self.track_name}"


# =============================================================================
# 1.7 — Strand
# =============================================================================
class Strand(models.Model):
    track = models.ForeignKey(
        Track,
        on_delete=models.CASCADE,
        related_name='strands',
    )
    strand_code = models.CharField(
        max_length=15,
        help_text="e.g., 'STEM', 'HUMSS', 'ABM', 'GAS', 'ICT', 'HE', 'IA'.",
    )
    strand_name = models.CharField(
        max_length=120,
        help_text="e.g., 'Science, Technology, Engineering and Mathematics'.",
    )
    strand_description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['track', 'strand_code']]
        ordering = ['track__track_name', 'strand_name']
        verbose_name = 'Strand'
        verbose_name_plural = 'Strands'

    def __str__(self):
        return f"{self.strand_code} — {self.strand_name}"


# =============================================================================
# 1.8 — Subject
# =============================================================================
class Subject(models.Model):
    SUBJECT_CATEGORIES = [
        ('Core', 'Core'),
        ('Applied', 'Applied'),
        ('Specialized', 'Specialized'),
        ('Elective', 'Elective'),
        ('Remedial', 'Remedial'),
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='subjects',
        help_text="School this subject belongs to",
    )
    subject_code = models.CharField(
        max_length=25,
        help_text="e.g., 'CORE-ENG11', 'SP-STEM-PRECALC'.",
    )
    subject_name = models.CharField(
        max_length=200,
        help_text="e.g., 'English for Academic and Professional Purposes'.",
    )
    subject_category = models.CharField(
        max_length=25,
        choices=SUBJECT_CATEGORIES,
        db_index=True,
        help_text="DepEd subject classification.",
    )
    subject_family = models.ForeignKey(
        'SubjectFamily',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subjects',
        help_text="Optional grouping — e.g., all Math subjects belong to 'Mathematics' family.",
    )
    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.CASCADE,
        related_name='subjects',
        help_text="The grade level this subject is offered to.",
    )
    strand = models.ForeignKey(
        Strand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subjects',
        help_text="Only set for SHS specialized subjects. NULL for JHS and core SHS subjects.",
    )
    hours_per_semester = models.PositiveSmallIntegerField(
        null=True,
        blank=True,
        help_text="Total hours per semester (typically 80 for 1-unit SHS subjects).",
    )
    hours_per_week = models.DecimalField(
        max_digits=4,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Contact hours per week.",
    )
    deped_subject_code = models.CharField(
        max_length=25,
        blank=True,
        help_text="Official DepEd curriculum code if different from internal subject_code.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_grade_computed = models.BooleanField(
        default=True,
        help_text="Subjects like Homeroom or Remedial may not count toward the general average.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school', 'subject_code']]
        ordering = ['subject_code']
        verbose_name = 'Subject'
        verbose_name_plural = 'Subjects'

    def __str__(self):
        return f"{self.subject_code} — {self.subject_name}"




# =============================================================================
# 1.9 — SubjectPrerequisite
# =============================================================================
class SubjectPrerequisite(models.Model):
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='prerequisites_of',
        help_text="The subject that requires a prerequisite.",
    )
    prerequisite_subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='required_for',
        help_text="The subject that must be completed first.",
    )
    is_corequisite = models.BooleanField(
        default=False,
        help_text="If True, this subject can be taken simultaneously with the prerequisite.",
    )
    minimum_grade_required = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Minimum grade needed in the prerequisite to enroll. NULL means passing is sufficient.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['subject', 'prerequisite_subject']]
        ordering = ['subject__subject_code']
        verbose_name = 'Subject Prerequisite'
        verbose_name_plural = 'Subject Prerequisites'

    def clean(self):
        if self.subject_id and self.prerequisite_subject_id:
            if self.subject == self.prerequisite_subject:
                raise ValidationError({
                    'prerequisite_subject': 'A subject cannot be a prerequisite of itself.',
                })

    def __str__(self):
        return f"{self.subject.subject_code} requires {self.prerequisite_subject.subject_code}"


# =============================================================================
# 1.10 — CurriculumMapping
# =============================================================================
class CurriculumMapping(models.Model):
    school_year = models.ForeignKey(
        SchoolYear,
        on_delete=models.CASCADE,
        related_name='curriculum_mappings',
    )
    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.CASCADE,
        related_name='curriculum_mappings',
    )
    strand = models.ForeignKey(
        Strand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='curriculum_mappings',
        help_text="Only set for SHS. NULL for JHS.",
    )
    subject = models.ForeignKey(
        Subject,
        on_delete=models.CASCADE,
        related_name='curriculum_mappings',
    )
    semester = models.ForeignKey(
        Semester,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='curriculum_mappings',
        help_text="Required for SHS subjects (1st or 2nd semester). NULL for JHS full-year subjects.",
    )
    is_required = models.BooleanField(
        default=True,
        help_text="Is this subject required for this grade level/strand combination?",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['school_year', 'grade_level', 'strand', 'subject', 'semester']]
        ordering = ['school_year', 'grade_level__sort_order', 'subject__subject_code']
        verbose_name = 'Curriculum Mapping'
        verbose_name_plural = 'Curriculum Mappings'

    def clean(self):
        if self.grade_level_id:
            if self.grade_level.is_senior_high:
                if self.strand is None:
                    raise ValidationError({
                        'strand': 'Strand is required for Senior High School curriculum mappings.',
                    })
                if self.semester is None:
                    raise ValidationError({
                        'semester': 'Semester is required for Senior High School subjects.',
                    })
            else:
                if self.semester is not None:
                    raise ValidationError({
                        'semester': 'Semester must be NULL for Junior High School subjects (full-year).',
                    })

    def __str__(self):
        parts = [str(self.school_year), str(self.grade_level)]
        if self.strand:
            parts.append(str(self.strand.strand_code))
        parts.append(str(self.subject.subject_code))
        return ' — '.join(parts)


# =============================================================================
# 1.11 — Room
# =============================================================================
class Room(models.Model):
    ROOM_TYPE_CHOICES = [
        ('Classroom', 'Classroom'),
        ('Laboratory', 'Laboratory'),
        ('Computer Lab', 'Computer Lab'),
        ('Science Lab', 'Science Lab'),
        ('Library', 'Library'),
        ('Gymnasium', 'Gymnasium'),
        ('Auditorium', 'Auditorium'),
        ('Office', 'Office'),
        ('Clinic', 'Clinic'),
        ('Faculty Room', 'Faculty Room'),
        ('Conference Room', 'Conference Room'),
        ('Storage', 'Storage'),
        ('Other', 'Other'),
    ]

    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='rooms',
        help_text="School this room belongs to",
    )
    room_code = models.CharField(
        max_length=20,
        help_text="e.g., 'BLDG1-201', 'SCI-LAB-A', 'LIB-MAIN'.",
    )
    room_name = models.CharField(
        max_length=100,
        null=True,
        blank=True,
        help_text="e.g., 'Science Laboratory A'.",
    )
    room_type = models.CharField(
        max_length=30,
        choices=ROOM_TYPE_CHOICES,
        default='Classroom',
    )
    building = models.CharField(
        max_length=60,
        null=True,
        blank=True,
        help_text="Building name or number.",
    )
    floor = models.CharField(
        max_length=15,
        null=True,
        blank=True,
        help_text="Floor number or designation.",
    )
    capacity = models.PositiveSmallIntegerField(default=50)
    has_projector = models.BooleanField(default=False)
    has_airconditioning = models.BooleanField(default=False)
    has_internet = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school', 'room_code']]
        ordering = ['room_code']
        verbose_name = 'Room'
        verbose_name_plural = 'Rooms'

    def __str__(self):
        if self.room_name:
            return f"{self.room_code} — {self.room_name}"
        return self.room_code


# =============================================================================
# 1.12 — Section
# =============================================================================
class Section(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='sections',
        help_text="School this section belongs to",
    )
    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.CASCADE,
        related_name='sections',
    )
    strand = models.ForeignKey(
        Strand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sections',
    )
    school_year = models.ForeignKey(
        SchoolYear,
        on_delete=models.CASCADE,
        related_name='sections',
    )
    section_name = models.CharField(
        max_length=60,
        help_text="e.g., 'Rizal', 'STEM-A', 'Sampaguita', 'Bonifacio'.",
    )
    adviser = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='advised_sections',
        help_text="Homeroom adviser assigned to this section.",
    )
    room = models.ForeignKey(
        Room,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='sections',
        help_text="Default classroom for this section.",
    )
    max_capacity = models.PositiveSmallIntegerField(
        default=50,
        help_text="Maximum number of students allowed in this section.",
    )
    current_enrollment_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="DENORMALIZED COUNT — updated via EnrollmentRecord.save() or management command. Rebuild periodically.",
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_homeroom = models.BooleanField(
        default=False,
        help_text="Designates this as a homeroom/advisory section.",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school', 'section_name', 'grade_level', 'school_year']]
        ordering = ['school_year', 'grade_level__sort_order', 'section_name']
        verbose_name = 'Section'
        verbose_name_plural = 'Sections'

    def clean(self):
        if self.strand and self.grade_level_id:
            if not self.grade_level.is_senior_high:
                raise ValidationError({
                    'strand': 'Strand can only be assigned to Senior High School sections (Grades 11-12).',
                })

    def __str__(self):
        parts = [self.school_year.year_label, self.grade_level.grade_name, self.section_name]
        if self.strand:
            parts.insert(2, self.strand.strand_code)
        return ' — '.join(parts)

# =============================================================================
# 1.13 — RpmsCycle
# =============================================================================
class RpmsCycle(models.Model):
    school_year = models.ForeignKey(
        SchoolYear,
        on_delete=models.CASCADE,
        related_name='rpms_cycles',
    )
    cycle_label = models.CharField(
        max_length=100,
        help_text="e.g., 'RPMS SY 2025-2026'.",
    )
    date_start = models.DateField(
        help_text="Start date of the RPMS cycle.",
    )
    date_end = models.DateField(
        help_text="End date of the RPMS cycle.",
    )
    evaluation_deadline = models.DateField(
        help_text="Deadline for completing all evaluations.",
    )
    is_current_cycle = models.BooleanField(
        default=False,
        db_index=True,
        help_text="Only one RPMS cycle can be current at a time.",
    )
    is_completed = models.BooleanField(
        default=False,
        help_text="Marks the cycle as fully completed and archived.",
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_rpms_cycles',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-date_start']
        verbose_name = 'RPMS Cycle'
        verbose_name_plural = 'RPMS Cycles'

    def clean(self):
        if self.date_start and self.date_end and self.date_start >= self.date_end:
            raise ValidationError({
                'date_end': 'Cycle end date must be after start date.',
            })
        if self.evaluation_deadline and self.date_end:
            if self.evaluation_deadline > self.date_end:
                raise ValidationError({
                    'evaluation_deadline': 'Evaluation deadline should not exceed the cycle end date.',
                })

    def save(self, *args, **kwargs):
        if self.is_current_cycle:
            RpmsCycle.objects.filter(school_year=self.school_year).exclude(pk=self.pk).update(is_current_cycle=False)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.cycle_label


# =============================================================================
# 1.14 — GradeLevelEnrollmentQuota
# =============================================================================
class GradeLevelEnrollmentQuota(models.Model):
    school_year = models.ForeignKey(
        SchoolYear,
        on_delete=models.CASCADE,
        related_name='enrollment_quotas',
    )
    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.CASCADE,
        related_name='enrollment_quotas',
    )
    total_quota = models.PositiveSmallIntegerField(
        help_text="Maximum number of students that can be enrolled in this grade level.",
    )
    current_enrollee_count = models.PositiveSmallIntegerField(
        default=0,
        help_text="DENORMALIZED COUNT — updated on enrollment. Rebuild periodically via management command.",
    )
    is_enrollment_open = models.BooleanField(
        default=True,
        help_text="Can new students still enroll in this grade level?",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school_year', 'grade_level']]
        ordering = ['school_year', 'grade_level__sort_order']
        verbose_name = 'Grade Level Enrollment Quota'
        verbose_name_plural = 'Grade Level Enrollment Quotas'

    def __str__(self):
        return f"{self.school_year} — {self.grade_level}: {self.current_enrollee_count}/{self.total_quota}"


# =============================================================================
# 1.15 — SubjectGroup
# =============================================================================
class SubjectGroup(models.Model):
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='subject_groups',
        help_text="School this subject group belongs to",
    )
    group_name = models.CharField(
        max_length=150,
        help_text="e.g., 'Grade 11 STEM Core Subjects', 'Grade 7 Remedial Subjects'.",
    )
    grade_level = models.ForeignKey(
        GradeLevel,
        on_delete=models.CASCADE,
        related_name='subject_groups',
    )
    strand = models.ForeignKey(
        Strand,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='subject_groups',
    )
    subjects = models.ManyToManyField(
        Subject,
        related_name='subject_groups',
        help_text="Subjects that belong to this group.",
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['school', 'group_name']]
        ordering = ['group_name']
        verbose_name = 'Subject Group'
        verbose_name_plural = 'Subject Groups'

    def __str__(self):
        return self.group_name


# =============================================================================
# 1.16 — GradingSchema (Dynamic grading for different schools)
# =============================================================================
class GradingSchema(models.Model):
    """Dynamic grading schema for different schools"""
    SCALE_TYPES = [
        ('PERCENTAGE', '0-100 Percentage'),
        ('NUMERIC_1_5', '1.0 - 5.0 (1.0 highest)'),
        ('NUMERIC_5_1', '5.0 - 1.0 (5.0 highest)'),
        ('GPA_4', '0.0 - 4.0 GPA'),
        ('LETTER', 'A - F Letter Grades'),
    ]
    
    ROUNDING_RULES = [
        ('NEAREST_INT', 'Round to nearest integer (0.5 up)'),
        ('NEAREST_INT_DOWN', 'Round down always'),
        ('ONE_DECIMAL', 'Keep 1 decimal place'),
        ('TWO_DECIMAL', 'Keep 2 decimal places'),
        ('NONE', 'No rounding'),
    ]
    
    school = models.ForeignKey(
        'School',
        on_delete=models.CASCADE,
        related_name='grading_schemas',
        help_text="School this grading schema belongs to",
    )
    scale_type = models.CharField(max_length=20, choices=SCALE_TYPES, default='PERCENTAGE')
    passing_threshold = models.FloatField(default=75.0)
    highest_is_best = models.BooleanField(default=True)
    rounding_rule = models.CharField(max_length=20, choices=ROUNDING_RULES, default='NEAREST_INT')
    letter_grade_mapping = models.JSONField(default=dict, blank=True)
    
    # Custom range (for 50-base schools)
    min_value = models.FloatField(default=0)
    max_value = models.FloatField(default=100)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"{self.school.school_name} - {self.scale_type}"
    
    class Meta:
        db_table = 'academics_gradingschema'


# =============================================================================
# 1.17 — SectionQuarterlySummary (AI aggregated data)
# =============================================================================
class SectionQuarterlySummary(models.Model):
    """Aggregated performance per section per subject per quarter"""
    CATEGORY_CHOICES = [
        ('EXCELLENCE', 'Excellence Track'),
        ('STANDARD', 'Standard Track'),
        ('INTERVENTION', 'Intervention Track'),
    ]
    
    section = models.ForeignKey(Section, on_delete=models.CASCADE, related_name='quarterly_summaries')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='section_summaries')
    quarter = models.ForeignKey(Quarter, on_delete=models.CASCADE, related_name='section_summaries')
    school_year = models.ForeignKey(SchoolYear, on_delete=models.CASCADE, related_name='section_summaries')
    
    # Metrics
    average_grade = models.FloatField(default=0)
    median_grade = models.FloatField(default=0)
    highest_grade = models.FloatField(default=0)
    lowest_grade = models.FloatField(default=0)
    passing_rate = models.FloatField(default=0)  # percentage
    excellent_rate = models.FloatField(default=0)  # percentage (>=90%)
    at_risk_count = models.IntegerField(default=0)
    total_students = models.IntegerField(default=0)
    
    # Trends
    trend_direction = models.CharField(max_length=20, blank=True)  # improving, declining, stable, erratic
    trend_slope = models.FloatField(default=0)
    
    # Categorization
    category = models.CharField(max_length=20, choices=CATEGORY_CHOICES, blank=True)
    category_score = models.FloatField(default=0)
    
    needs_intervention = models.BooleanField(default=False)
    
    calculated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'academics_sectionquarterlysummary'
        unique_together = ['section', 'subject', 'quarter', 'school_year']
    
    def __str__(self):
        return f"{self.section} - {self.subject} - {self.quarter}"


# =============================================================================
# 1.18 — AISectionRecommendation (AI recommendations for principal)
# =============================================================================
class AISectionRecommendation(models.Model):
    """AI-generated recommendations for principals"""
    section_summary = models.OneToOneField(
        SectionQuarterlySummary,
        on_delete=models.CASCADE,
        related_name='ai_recommendation'
    )
    
    # AI Output
    category = models.CharField(max_length=50)
    one_sentence_summary = models.TextField()
    key_insights = models.TextField()  # Bullet points as JSON or plain text
    recommendations = models.TextField()  # Actionable steps
    confidence_score = models.FloatField(default=0)
    
    # Tracking
    was_implemented = models.BooleanField(default=False)
    implemented_at = models.DateTimeField(null=True, blank=True)
    implementation_notes = models.TextField(blank=True)
    principal_feedback = models.TextField(blank=True)  # For improving AI
    
    generated_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'academics_aisectionrecommendation'
    
    def __str__(self):
        return f"AI Rec: {self.section_summary.section} - {self.category}"


# =============================================================================
# 1.19 — GradePrediction (Store predictions for audit)
# =============================================================================
class GradePrediction(models.Model):
    """Store grade predictions for audit and improvement"""
    enrollment = models.ForeignKey('enrollment.Enrollment', on_delete=models.CASCADE, related_name='grade_predictions')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE, related_name='grade_predictions')
    quarter = models.ForeignKey(Quarter, on_delete=models.CASCADE, null=True, blank=True, related_name='grade_predictions')
    
    predicted_grade = models.FloatField()
    actual_grade = models.FloatField(null=True, blank=True)
    confidence_score = models.FloatField()
    
    # Risk assessment
    risk_score = models.FloatField(default=0)
    risk_factors = models.JSONField(default=list, blank=True)
    is_at_risk = models.BooleanField(default=False)
    
    predicted_at = models.DateTimeField(auto_now_add=True)
    model_version = models.CharField(max_length=50, blank=True)
    
    class Meta:
        db_table = 'academics_gradeprediction'
        ordering = ['-predicted_at']
    
    def __str__(self):
        return f"Prediction for {self.enrollment.student} - {self.subject}: {self.predicted_grade}"

# academics/models.py - ADD THESE MODELS

class AssessmentItem(models.Model):
    """Individual quiz/test question mapped to KPUP level"""
    COGNITIVE_LEVELS = [
        ('REMEMBERING', 'Remembering (Knowledge)'),
        ('UNDERSTANDING', 'Understanding (Knowledge)'),
        ('APPLYING', 'Applying (Process)'),
        ('ANALYZING', 'Analyzing (Process)'),
        ('EVALUATING', 'Evaluating (Understanding)'),
        ('CREATING', 'Creating (Product)'),
    ]
    
    subject = models.ForeignKey('academics.Subject', on_delete=models.CASCADE)
    question_text = models.TextField()
    cognitive_level = models.CharField(max_length=20, choices=COGNITIVE_LEVELS)
    max_score = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    topic = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'academics_assessment_item'


class StudentAssessmentResult(models.Model):
    """Individual student's score on an assessment item"""
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    assessment_item = models.ForeignKey(AssessmentItem, on_delete=models.CASCADE)
    score = models.DecimalField(max_digits=5, decimal_places=2)
    quarter = models.ForeignKey('academics.Quarter', on_delete=models.CASCADE)
    school_year = models.ForeignKey('academics.SchoolYear', on_delete=models.CASCADE)
    answered_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'academics_student_assessment_result'


class KPUPMastery(models.Model):
    """Aggregated KPUP mastery per student per subject per quarter"""
    MASTERY_LEVELS = [
        ('ADVANCED', 'Advanced (96-100%)'),
        ('PROFICIENT', 'Proficient (86-95%)'),
        ('DEVELOPING', 'Developing (66-85%)'),
        ('BEGINNING', 'Beginning (0-65%)'),
    ]
    
    student = models.ForeignKey('students.Student', on_delete=models.CASCADE)
    subject = models.ForeignKey('academics.Subject', on_delete=models.CASCADE)
    quarter = models.ForeignKey('academics.Quarter', on_delete=models.CASCADE)
    school_year = models.ForeignKey('academics.SchoolYear', on_delete=models.CASCADE)
    
    # KPUP Scores (0-100)
    knowledge_score = models.FloatField(default=0)  # K - 15% weight
    process_score = models.FloatField(default=0)    # P - 25% weight
    understanding_score = models.FloatField(default=0)  # U - 30% weight
    product_score = models.FloatField(default=0)    # P - 30% weight
    
    # Mastery levels for each dimension
    knowledge_mastery = models.CharField(max_length=20, choices=MASTERY_LEVELS, blank=True)
    process_mastery = models.CharField(max_length=20, choices=MASTERY_LEVELS, blank=True)
    understanding_mastery = models.CharField(max_length=20, choices=MASTERY_LEVELS, blank=True)
    product_mastery = models.CharField(max_length=20, choices=MASTERY_LEVELS, blank=True)
    
    # Overall subject grade (computed from KPUP)
    overall_grade = models.FloatField(default=0)
    overall_mastery = models.CharField(max_length=20, choices=MASTERY_LEVELS, blank=True)
    
    computed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'academics_kpup_mastery'
        unique_together = ['student', 'subject', 'quarter', 'school_year']


class SubjectKPUPSummary(models.Model):
    """Subject-level KPUP summary for principal dashboard"""
    subject = models.ForeignKey('academics.Subject', on_delete=models.CASCADE)
    quarter = models.ForeignKey('academics.Quarter', on_delete=models.CASCADE)
    school_year = models.ForeignKey('academics.SchoolYear', on_delete=models.CASCADE)
    
    # Average scores across all students
    avg_knowledge = models.FloatField(default=0)
    avg_process = models.FloatField(default=0)
    avg_understanding = models.FloatField(default=0)
    avg_product = models.FloatField(default=0)
    
    # Distribution counts
    advanced_count = models.IntegerField(default=0)
    proficient_count = models.IntegerField(default=0)
    developing_count = models.IntegerField(default=0)
    beginning_count = models.IntegerField(default=0)
    
    total_students = models.IntegerField(default=0)
    computed_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        db_table = 'academics_subject_kpup_summary'











# =============================================================================
# 1.20 — SubjectFamily (Groups related subjects across grade levels)
# =============================================================================
class SubjectFamily(models.Model):
    """
    Groups related subjects across grade levels.
    Example: 'Mathematics' family contains Math 7, Math 8, Math 9, Math 10
             'English' family contains English 7, English 8, English 9, English 10
    """
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name='subject_families',
        help_text="School this subject family belongs to",
    )
    family_name = models.CharField(
        max_length=150,
        help_text="e.g., 'Mathematics', 'English', 'Science', 'Filipino'.",
    )
    family_code = models.CharField(
        max_length=25,
        help_text="e.g., 'MATH', 'ENG', 'SCI', 'FIL'.",
    )
    description = models.TextField(blank=True)
    
    # Display preferences
    color_hex = models.CharField(
        max_length=7,
        default='#123499',
        help_text="Color for charts and badges (e.g., '#2E7D32' for Science).",
    )
    icon_class = models.CharField(
        max_length=50,
        blank=True,
        help_text="CSS icon class for the subject family (e.g., 'fi fi-rr-calculator').",
    )
    sort_order = models.PositiveSmallIntegerField(
        default=0,
        help_text="Display order in dropdowns and lists.",
    )
    
    is_active = models.BooleanField(default=True, db_index=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['school', 'family_code']]
        ordering = ['sort_order', 'family_name']
        verbose_name = 'Subject Family'
        verbose_name_plural = 'Subject Families'
        db_table = 'academics_subject_family'

    def __str__(self):
        return f"{self.family_code} — {self.family_name}"




class Assessment(models.Model):
    """Teacher-created quiz/assessment."""
    STATUS_CHOICES = [
        ('draft', 'Draft'),
        ('published', 'Published'),
        ('closed', 'Closed'),
    ]
    
    teacher = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='assessments')
    subject = models.ForeignKey(Subject, on_delete=models.CASCADE)
    section = models.ForeignKey(Section, on_delete=models.CASCADE)
    school_year = models.ForeignKey(SchoolYear, on_delete=models.CASCADE)
    quarter = models.ForeignKey(Quarter, on_delete=models.SET_NULL, null=True)
    
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    total_items = models.PositiveSmallIntegerField()
    points_per_item = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    passing_score = models.DecimalField(max_digits=5, decimal_places=2, default=60.0)
    
    # Time limit (optional)
    time_limit_minutes = models.PositiveSmallIntegerField(null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='draft')
    
    # Unique code for sharing
    access_code = models.CharField(max_length=10, unique=True, db_index=True)
    
    # Shuffled order of questions (stored as JSON list of question IDs)
    question_order = models.JSONField(default=list, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['-created_at']
    
    def save(self, *args, **kwargs):
        if not self.access_code:
            self.access_code = uuid.uuid4().hex[:8].upper()
        super().save(*args, **kwargs)
    
    def shuffle_questions(self):
        """Randomize question order and save."""
        question_ids = list(self.questions.values_list('id', flat=True))
        random.shuffle(question_ids)
        self.question_order = question_ids
        self.save(update_fields=['question_order'])
    
    def get_share_url(self):
        return f"/quiz/{self.access_code}/"
    
    def __str__(self):
        return f"{self.title} — {self.subject.subject_code}"


class AssessmentQuestion(models.Model):
    """Individual question in an assessment."""
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='questions')
    question_text = models.TextField()
    order_number = models.PositiveSmallIntegerField()  # Original order (before shuffle)
    
    # Number of choices teacher wants
    num_choices = models.PositiveSmallIntegerField(default=4)
    
    # Correct answer (stored as index 0-5)
    correct_answer_index = models.PositiveSmallIntegerField()
    
    # Choices stored as JSON (shuffled when assessment is published)
    # Format: [{"text": "Choice A", "order": 0}, {"text": "Choice B", "order": 1}, ...]
    choices = models.JSONField()
    
    # Shuffled order of choices for display
    shuffled_choice_order = models.JSONField(default=list, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['assessment', 'order_number']
    
    def shuffle_choices(self):
        """Randomize choice order and store the mapping."""
        num = len(self.choices)
        order = list(range(num))
        random.shuffle(order)
        self.shuffled_choice_order = order
        self.save(update_fields=['shuffled_choice_order'])
    
    def get_display_choices(self):
        """Return choices in shuffled order."""
        if self.shuffled_choice_order:
            return [self.choices[i] for i in self.shuffled_choice_order]
        return self.choices
    
    def __str__(self):
        return f"Q{self.order_number}: {self.question_text[:50]}..."


class AssessmentResponse(models.Model):
    """A student's complete response to an assessment."""
    assessment = models.ForeignKey(Assessment, on_delete=models.CASCADE, related_name='responses')
    
    # Student can use Gmail or Full Name
    student_email = models.EmailField(null=True, blank=True)
    student_name = models.CharField(max_length=200, null=True, blank=True)
    
    # Or link to actual student if they exist in system
    student = models.ForeignKey('students.Student', on_delete=models.SET_NULL, null=True, blank=True)
    
    score = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    total_points = models.DecimalField(max_digits=6, decimal_places=2, default=0)
    passed = models.BooleanField(default=False)
    
    started_at = models.DateTimeField(auto_now_add=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    
    class Meta:
        ordering = ['-submitted_at']
    
    def __str__(self):
        name = self.student_name or self.student_email or f"Student #{self.id}"
        return f"{name} — {self.assessment.title} ({self.score}/{self.total_points})"


class AssessmentAnswer(models.Model):
    """Individual answer to a question."""
    response = models.ForeignKey(AssessmentResponse, on_delete=models.CASCADE, related_name='answers')
    question = models.ForeignKey(AssessmentQuestion, on_delete=models.CASCADE)
    
    # The index the student selected (from shuffled display)
    selected_index = models.PositiveSmallIntegerField()
    
    # Whether it was correct
    is_correct = models.BooleanField(default=False)
    
    points_earned = models.DecimalField(max_digits=5, decimal_places=2, default=0)
    
    class Meta:
        unique_together = ['response', 'question']
    
    def __str__(self):
        return f"Q{self.question.order_number}: {'✅' if self.is_correct else '❌'}"



