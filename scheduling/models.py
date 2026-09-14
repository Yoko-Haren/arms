# scheduling/models.py
"""
Phase 5: Class & Schedule models for Formify LIS.
Teacher assignments, weekly schedules, substitution tracking,
and denormalized workload summaries.
"""

from datetime import datetime, timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone


# =============================================================================
# MODULE-LEVEL CONSTANTS
# =============================================================================
DAY_OF_WEEK_CHOICES = [
    ('Monday', 'Monday'),
    ('Tuesday', 'Tuesday'),
    ('Wednesday', 'Wednesday'),
    ('Thursday', 'Thursday'),
    ('Friday', 'Friday'),
    ('Saturday', 'Saturday'),
]

DAY_NUMBER_MAP = {
    'Monday': 1,
    'Tuesday': 2,
    'Wednesday': 3,
    'Thursday': 4,
    'Friday': 5,
    'Saturday': 6,
}

SCHEDULE_TYPE_CHOICES = [
    ('Regular', 'Regular Class'),
    ('Makeup', 'Makeup Session'),
    ('Special', 'Special/Remedial Class'),
    ('Club', 'Club/Organization Meeting'),
    ('Other', 'Other'),
]


# =============================================================================
# 5.1 — ClassAssignment
# =============================================================================
class ClassAssignment(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='class_assignments',
    )
    section = models.ForeignKey(
        'academics.Section',
        on_delete=models.CASCADE,
        related_name='class_assignments',
    )
    subject = models.ForeignKey(
        'academics.Subject',
        on_delete=models.PROTECT,
        related_name='class_assignments',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='class_assignments',
    )
    semester = models.ForeignKey(
        'academics.Semester',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='class_assignments',
        help_text='Required for SHS subjects. NULL for JHS full-year subjects.',
    )
    default_room = models.ForeignKey(
        'academics.Room',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='default_class_assignments',
        help_text='Default classroom. Individual schedule entries can override this.',
    )
    is_advisory = models.BooleanField(
        default=False,
        help_text='Is this the teacher\'s homeroom/advisory class?',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    max_students = models.PositiveSmallIntegerField(default=50)
    minutes_per_meeting = models.PositiveSmallIntegerField(
        default=60,
        help_text='Default duration per meeting in minutes.',
    )
    meetings_per_week = models.PositiveSmallIntegerField(
        default=5,
        help_text='Expected number of meetings per week.',
    )
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_class_assignments',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = [['teacher', 'section', 'subject', 'school_year', 'semester']]
        ordering = ['school_year', 'section__grade_level__sort_order', 'section__section_name', 'subject__subject_code']
        indexes = [
            models.Index(fields=['teacher', 'school_year']),
            models.Index(fields=['section', 'school_year']),
            models.Index(fields=['is_active']),
        ]
        verbose_name = 'Class Assignment'
        verbose_name_plural = 'Class Assignments'

    @property
    def grade_level(self):
        return self.section.grade_level.grade_name

    @property
    def section_name(self):
        return self.section.section_name

    @property
    def teacher_name(self):
        return self.teacher.get_full_name() or self.teacher.username

    @property
    def subject_name(self):
        return self.subject.subject_name

    @property
    def subject_code(self):
        return self.subject.subject_code

    def clean(self):
        # SHS sections require a semester
        if self.section.grade_level.is_senior_high and not self.semester:
            raise ValidationError({
                'semester': 'Semester is required for Senior High School class assignments.',
            })
        # JHS sections should not have a semester
        if not self.section.grade_level.is_senior_high and self.semester:
            raise ValidationError({
                'semester': 'Semester should be blank for Junior High School class assignments.',
            })
        # Teacher should be... well, a teacher (but allow non-teachers for admin purposes)
        if hasattr(self.teacher, 'profile'):
            if self.teacher.profile.role not in ['teacher', 'admin']:
                raise ValidationError({
                    'teacher': 'Only users with the Teacher role can be assigned to classes.',
                })

    def __str__(self):
        return f"{self.teacher_name} — {self.subject_code} — {self.section} ({self.school_year.year_label})"


# =============================================================================
# 5.2 — ClassSchedule
# =============================================================================
class ClassSchedule(models.Model):
    class_assignment = models.ForeignKey(
        ClassAssignment,
        on_delete=models.CASCADE,
        related_name='schedules',
    )
    day_of_week = models.CharField(
        max_length=10,
        choices=DAY_OF_WEEK_CHOICES,
    )
    day_number = models.PositiveSmallIntegerField(
        editable=False,
        help_text='Auto-set from DAY_NUMBER_MAP in save().',
    )
    time_start = models.TimeField()
    time_end = models.TimeField()
    duration_minutes = models.PositiveSmallIntegerField(
        editable=False,
        help_text='Auto-calculated from time_start and time_end.',
    )
    room = models.ForeignKey(
        'academics.Room',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='class_schedules',
        help_text='Overrides the default room from ClassAssignment if set.',
    )
    schedule_type = models.CharField(
        max_length=20,
        choices=SCHEDULE_TYPE_CHOICES,
        default='Regular',
    )
    effective_from = models.DateField(default=timezone.now)
    effective_until = models.DateField(
        null=True,
        blank=True,
        help_text='Leave blank for ongoing schedule. Set to retire this schedule entry.',
    )
    is_active = models.BooleanField(default=True, db_index=True)
    notes = models.CharField(max_length=255, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['day_number', 'time_start']
        indexes = [
            models.Index(fields=['day_of_week', 'time_start']),
            models.Index(fields=['is_active', 'day_number']),
        ]
        verbose_name = 'Class Schedule'
        verbose_name_plural = 'Class Schedules'

    @property
    def effective_room(self):
        """Returns the room for this meeting, falling back to the default room."""
        return self.room or self.class_assignment.default_room

    @property
    def teacher(self):
        return self.class_assignment.teacher

    @property
    def subject_code(self):
        return self.class_assignment.subject_code

    @property
    def subject_name(self):
        return self.class_assignment.subject_name

    @property
    def section_name(self):
        return self.class_assignment.section_name

    def save(self, *args, **kwargs):
        # Auto-set day_number from day_of_week
        self.day_number = DAY_NUMBER_MAP.get(self.day_of_week, 0)

        # Auto-calculate duration_minutes
        if self.time_start and self.time_end:
            start = datetime.combine(datetime.today(), self.time_start)
            end = datetime.combine(datetime.today(), self.time_end)
            if end <= start:
                # Handle overnight edge case (unlikely for classes but safe)
                end += timedelta(days=1)
            self.duration_minutes = int((end - start).total_seconds() // 60)

        super().save(*args, **kwargs)

    def clean(self):
        if self.time_start and self.time_end and self.time_start >= self.time_end:
            raise ValidationError({
                'time_end': 'End time must be after start time.',
            })

        if self.effective_from and self.effective_until:
            if self.effective_until <= self.effective_from:
                raise ValidationError({
                    'effective_until': 'Effective until date must be after effective from date.',
                })

        # --- ROOM CONFLICT DETECTION ---
        room = self.effective_room
        if room and self.day_of_week and self.time_start and self.time_end and self.is_active:
            overlapping = ClassSchedule.objects.filter(
                is_active=True,
                day_of_week=self.day_of_week,
                time_start__lt=self.time_end,
                time_end__gt=self.time_start,
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)

            # Check by room FK
            room_conflicts = overlapping.filter(room=room)
            # Check by ClassAssignment default_room
            room_conflicts |= overlapping.filter(
                room__isnull=True,
                class_assignment__default_room=room,
            )
            # Also check schedules where this room is the ClassAssignment default
            room_conflicts |= overlapping.filter(
                room__isnull=True,
                class_assignment__default_room__isnull=True,
            ).filter(
                class_assignment__default_room=room,
            )

            if room_conflicts.exists():
                conflict = room_conflicts.first()
                raise ValidationError({
                    'room': f'Room conflict: {room} is already used by {conflict.subject_code} '
                            f'({conflict.section_name}) on {self.day_of_week} at '
                            f'{conflict.time_start}-{conflict.time_end}.',
                })

        # --- TEACHER CONFLICT DETECTION ---
        teacher = self.class_assignment.teacher
        if teacher and self.day_of_week and self.time_start and self.time_end and self.is_active:
            overlapping = ClassSchedule.objects.filter(
                is_active=True,
                day_of_week=self.day_of_week,
                time_start__lt=self.time_end,
                time_end__gt=self.time_start,
                class_assignment__teacher=teacher,
            )
            if self.pk:
                overlapping = overlapping.exclude(pk=self.pk)

            if overlapping.exists():
                conflict = overlapping.first()
                raise ValidationError({
                    'time_start': f'Teacher conflict: {teacher.get_full_name()} is already teaching '
                                  f'{conflict.subject_code} ({conflict.section_name}) on '
                                  f'{self.day_of_week} at {conflict.time_start}-{conflict.time_end}.',
                })

    def __str__(self):
        room_str = f" [{self.effective_room}]" if self.effective_room else ""
        return f"{self.subject_code} — {self.section_name} — {self.day_of_week} {self.time_start}-{self.time_end}{room_str}"


# =============================================================================
# 5.3 — SubstitutionAssignment
# =============================================================================
class SubstitutionAssignment(models.Model):
    REASON_CHOICES = [
        ('Sick_Leave', 'Sick Leave'),
        ('Official_Business', 'Official Business / Training'),
        ('Personal_Leave', 'Personal Leave'),
        ('Emergency', 'Emergency'),
        ('Maternity_Leave', 'Maternity Leave'),
        ('Other', 'Other'),
    ]

    class_schedule = models.ForeignKey(
        ClassSchedule,
        on_delete=models.CASCADE,
        related_name='substitutions',
    )
    original_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='substitutions_as_original',
    )
    substitute_teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.PROTECT,
        related_name='substitutions_as_substitute',
    )
    substitution_date = models.DateField(db_index=True)
    reason = models.CharField(
        max_length=100,
        blank=True,
        choices=REASON_CHOICES,
    )
    reason_details = models.TextField(blank=True)
    was_conducted = models.BooleanField(
        default=True,
        help_text='Did the class actually take place with the substitute?',
    )
    lesson_covered = models.TextField(
        blank=True,
        help_text='Brief description of what was taught during this period.',
    )
    notes = models.TextField(blank=True)
    approved_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='approved_substitutions',
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='created_substitutions',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-substitution_date', 'class_schedule__day_number', 'class_schedule__time_start']
        indexes = [
            models.Index(fields=['substitution_date']),
            models.Index(fields=['original_teacher', 'substitution_date']),
            models.Index(fields=['substitute_teacher', 'substitution_date']),
        ]
        verbose_name = 'Substitution Assignment'
        verbose_name_plural = 'Substitution Assignments'

    def clean(self):
        if self.original_teacher == self.substitute_teacher:
            raise ValidationError({
                'substitute_teacher': 'The substitute teacher cannot be the same as the original teacher.',
            })

        # Check that the substitute teacher is not already teaching at this day/time
        schedule = self.class_schedule
        if self.substitute_teacher and schedule and self.substitution_date:
            day_name = schedule.day_of_week
            # Map the substitution date to its day of week
            sub_day = self.substitution_date.strftime('%A')
            if sub_day == day_name and schedule.is_active:
                overlapping = ClassSchedule.objects.filter(
                    is_active=True,
                    day_of_week=day_name,
                    time_start__lt=schedule.time_end,
                    time_end__gt=schedule.time_start,
                    class_assignment__teacher=self.substitute_teacher,
                ).exclude(pk=schedule.pk)

                if overlapping.exists():
                    conflict = overlapping.first()
                    raise ValidationError({
                        'substitute_teacher': (
                            f'{self.substitute_teacher.get_full_name()} is already teaching '
                            f'{conflict.subject_code} on {day_name} at '
                            f'{conflict.time_start}-{conflict.time_end}.'
                        ),
                    })

    def __str__(self):
        return f"Sub: {self.substitute_teacher.get_full_name()} → {self.class_schedule} on {self.substitution_date}"


# =============================================================================
# 5.4 — TeacherLoadSummary
# =============================================================================
class TeacherLoadSummary(models.Model):
    teacher = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='load_summaries',
    )
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='teacher_load_summaries',
    )
    total_sections = models.PositiveSmallIntegerField(default=0)
    total_subjects = models.PositiveSmallIntegerField(default=0)
    total_meetings_per_week = models.PositiveSmallIntegerField(default=0)
    total_minutes_per_week = models.PositiveSmallIntegerField(default=0)
    total_teaching_hours_per_week = models.DecimalField(
        max_digits=5,
        decimal_places=2,
        default=0.00,
    )
    is_adviser = models.BooleanField(default=False)
    advised_section_name = models.CharField(max_length=100, blank=True)
    is_overload = models.BooleanField(
        default=False,
        help_text='Exceeds DepEd maximum teaching load of 6 hours per day?',
    )
    last_calculated_at = models.DateTimeField(auto_now=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['teacher', 'school_year']]
        ordering = ['school_year', 'teacher__last_name']
        verbose_name = 'Teacher Load Summary'
        verbose_name_plural = 'Teacher Load Summaries'

    def __str__(self):
        return f"{self.teacher.get_full_name()} — {self.school_year.year_label}: {self.total_teaching_hours_per_week} hrs/week"