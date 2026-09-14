# admin_panel/models.py - WITH COLLEGE/UNIVERSITY SUPPORT

from django.db import models
from django.contrib.auth.models import User
from django.conf import settings
from django.core.validators import MinValueValidator, MaxValueValidator
from django.utils import timezone
import uuid


class School(models.Model):
    """School model - created by Admin"""
    SCHOOL_TYPE_CHOICES = [
        # K-12 Levels
        ('ELEMENTARY', 'Elementary (Grades 1-6)'),
        ('JHS', 'Junior High School (Grades 7-10)'),
        ('SHS', 'Senior High School (Grades 11-12)'),
        ('INTEGRATED', 'Integrated School (K-12)'),
        # Higher Education
        ('COLLEGE', 'College'),
        ('UNIVERSITY', 'University'),
        ('GRADUATE', 'Graduate School'),
        ('TVET', 'Technical and Vocational Education and Training'),
        ('SEMINARY', 'Seminary / Theological School'),
        ('ONLINE', 'Online University'),
    ]
    
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=255, unique=True)
    school_id = models.CharField(max_length=50, unique=True, help_text="DepEd/CHED School ID")
    address = models.TextField()
    city = models.CharField(max_length=100, blank=True, null=True)
    region = models.CharField(max_length=100, blank=True, null=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    website = models.URLField(blank=True, null=True)
    contact_number = models.CharField(max_length=20, blank=True)
    email = models.EmailField(blank=True)
    school_type = models.CharField(max_length=20, choices=SCHOOL_TYPE_CHOICES, default='JHS')
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'School'
        verbose_name_plural = 'Schools'
    
    def __str__(self):
        return f"{self.name} ({self.school_id})"
    
    @property
    def is_higher_education(self):
        """Check if this is a college/university"""
        return self.school_type in ['COLLEGE', 'UNIVERSITY', 'GRADUATE', 'SEMINARY', 'ONLINE']
    
    @property
    def is_k12(self):
        """Check if this is a K-12 school"""
        return self.school_type in ['ELEMENTARY', 'JHS', 'SHS', 'INTEGRATED']
    
    @property
    def principal(self):
        return Principal.objects.filter(school=self, user__is_active=True).first()
    
    @property
    def total_students(self):
        return Student.objects.filter(school=self).count()
    
    @property
    def total_teachers(self):
        return Teacher.objects.filter(school=self, user__is_active=True).count()


class GradeLevel(models.Model):
    """Grade levels / Year levels configured per school"""
    
    # For K-12
    GRADE_LEVEL_CHOICES = [
        # Elementary
        ('Grade 1', 'Grade 1'), ('Grade 2', 'Grade 2'), ('Grade 3', 'Grade 3'),
        ('Grade 4', 'Grade 4'), ('Grade 5', 'Grade 5'), ('Grade 6', 'Grade 6'),
        # Junior High School
        ('Grade 7', 'Grade 7'), ('Grade 8', 'Grade 8'), ('Grade 9', 'Grade 9'), ('Grade 10', 'Grade 10'),
        # Senior High School
        ('Grade 11', 'Grade 11'), ('Grade 12', 'Grade 12'),
        # College/University
        ('1st Year', '1st Year College'), ('2nd Year', '2nd Year College'),
        ('3rd Year', '3rd Year College'), ('4th Year', '4th Year College'),
        ('5th Year', '5th Year College'), ('Graduate Studies', 'Graduate Studies'),
        ('Post Graduate', 'Post Graduate'), ('Doctorate', 'Doctorate'),
    ]
    
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='grade_levels')
    grade_name = models.CharField(max_length=50)
    grade_number = models.IntegerField(validators=[MinValueValidator(1), MaxValueValidator(20)], null=True, blank=True)
    strand = models.CharField(max_length=100, blank=True, help_text="For SHS: STEM, ABM, HUMSS, etc. For College: Course/Major")
    year_level = models.IntegerField(null=True, blank=True, help_text="1=1st Year, 2=2nd Year, etc.")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['grade_number', 'grade_name']
        unique_together = ['school', 'grade_name']
    
    def __str__(self):
        strand_info = f" - {self.strand}" if self.strand else ""
        return f"{self.grade_name}{strand_info} ({self.school.name})"


class Program(models.Model):
    """For Colleges/Universities - Academic Programs/Courses"""
    DEGREE_CHOICES = [
        ('BS', 'Bachelor of Science'),
        ('BA', 'Bachelor of Arts'),
        ('BSE', 'Bachelor of Secondary Education'),
        ('BEEd', 'Bachelor of Elementary Education'),
        ('BSTM', 'Bachelor of Science in Tourism Management'),
        ('BSHM', 'Bachelor of Science in Hospitality Management'),
        ('BSIT', 'Bachelor of Science in Information Technology'),
        ('BSIS', 'Bachelor of Science in Information Systems'),
        ('BSCS', 'Bachelor of Science in Computer Science'),
        ('BSA', 'Bachelor of Science in Accountancy'),
        ('BSBA', 'Bachelor of Science in Business Administration'),
        ('LLB', 'Bachelor of Laws'),
        ('JD', 'Juris Doctor'),
        ('MD', 'Doctor of Medicine'),
        ('MA', 'Master of Arts'),
        ('MS', 'Master of Science'),
        ('PhD', 'Doctor of Philosophy'),
        ('CERT', 'Certificate Program'),
        ('DIP', 'Diploma Program'),
    ]
    
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='programs')
    program_code = models.CharField(max_length=20, unique=True)
    program_name = models.CharField(max_length=200)
    degree_type = models.CharField(max_length=20, choices=DEGREE_CHOICES, blank=True)
    department = models.CharField(max_length=100, blank=True)
    duration_years = models.IntegerField(default=4, help_text="Number of years to complete")
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['program_code']
    
    def __str__(self):
        return f"{self.program_code} - {self.program_name} ({self.school.name})"


class SchoolYear(models.Model):
    """School Year / Academic Year management"""
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='school_years')
    year_label = models.CharField(max_length=20)  # e.g., "2025-2026" or "2025-2026 Academic Year"
    start_date = models.DateField()
    end_date = models.DateField()
    is_current = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    
    # For Higher Education (terms)
    TERM_CHOICES = [
        ('SEMESTRAL', 'Semestral (2 terms)'),
        ('TRIMESTRAL', 'Trimestral (3 terms)'),
        ('QUARTERLY', 'Quarterly (4 terms)'),
    ]
    term_system = models.CharField(max_length=20, choices=TERM_CHOICES, default='SEMESTRAL')
    
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-start_date']
        unique_together = ['school', 'year_label']
    
    def __str__(self):
        return f"{self.year_label} - {self.school.name}"
    
    def save(self, *args, **kwargs):
        if self.is_current:
            SchoolYear.objects.filter(school=self.school, is_current=True).update(is_current=False)
        super().save(*args, **kwargs)


class Quarter(models.Model):
    """Quarter/Term management per school year"""
    QUARTER_CHOICES = [
        # For Quarterly/Semestral systems
        ('Q1', 'First Quarter'), ('Q2', 'Second Quarter'),
        ('Q3', 'Third Quarter'), ('Q4', 'Fourth Quarter'),
        # For Trimestral systems
        ('T1', 'First Trimester'), ('T2', 'Second Trimester'), ('T3', 'Third Trimester'),
        # For Semestral systems
        ('S1', 'First Semester'), ('S2', 'Second Semester'),
        ('SUMMER', 'Summer Term'), ('MIDYEAR', 'Midyear Term'),
    ]
    
    school_year = models.ForeignKey(SchoolYear, on_delete=models.CASCADE, related_name='quarters')
    quarter_label = models.CharField(max_length=10, choices=QUARTER_CHOICES)
    quarter_number = models.IntegerField(null=True, blank=True, help_text="1,2,3,4 for ordering")
    start_date = models.DateField()
    end_date = models.DateField()
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['school_year', 'quarter_number', 'quarter_label']
        unique_together = ['school_year', 'quarter_label']
    
    def save(self, *args, **kwargs):
        # Auto-set quarter_number based on label
        quarter_map = {'Q1': 1, 'Q2': 2, 'Q3': 3, 'Q4': 4, 'S1': 1, 'S2': 2, 'T1': 1, 'T2': 2, 'T3': 3}
        if self.quarter_label in quarter_map:
            self.quarter_number = quarter_map[self.quarter_label]
        super().save(*args, **kwargs)
    
    def __str__(self):
        return f"{self.get_quarter_label_display()} - {self.school_year.year_label}"


# Rest of your models (Principal, Registrar, Teacher, Student) remain the same
# ...


class Principal(models.Model):
    """Principal/Rector/Dean account - created by Admin"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='principal_profile')
    school = models.OneToOneField(School, on_delete=models.CASCADE, related_name='principal_profile')
    employee_id = models.CharField(max_length=50, unique=True)
    designation = models.CharField(max_length=100, default="School Principal")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, related_name='created_principals')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['school__name']
        verbose_name = 'Principal'
        verbose_name_plural = 'Principals'
    
    def __str__(self):
        return f"{self.user.get_full_name()} - {self.school.name}"
    
    @property
    def full_name(self):
        return self.user.get_full_name()
    
    @property
    def title(self):
        """Appropriate title based on school type"""
        if self.school.school_type in ['UNIVERSITY', 'COLLEGE']:
            return "Dean / Rector"
        return "School Principal"


class Registrar(models.Model):
    """Registrar account - created by Principal/Dean"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='registrar_profile')
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='registrars')
    employee_id = models.CharField(max_length=50, unique=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(Principal, on_delete=models.CASCADE, related_name='created_registrars')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['school__name', 'user__last_name']
    
    def __str__(self):
        return f"{self.user.get_full_name()} - Registrar ({self.school.name})"


class Teacher(models.Model):
    """Teacher/Faculty account - created by Registrar"""
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name='teacher_profile')
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='teachers')
    employee_id = models.CharField(max_length=50, unique=True)
    designation = models.CharField(max_length=100, blank=True)
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(Registrar, on_delete=models.CASCADE, related_name='created_teachers')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['school__name', 'user__last_name']
    
    def __str__(self):
        return f"{self.user.get_full_name()} - Teacher ({self.school.name})"


class Student(models.Model):
    """Student model - managed by Registrar"""
    lrn = models.CharField(max_length=20, unique=True, primary_key=True)  # Increased length for college IDs
    school = models.ForeignKey(School, on_delete=models.CASCADE, related_name='students')
    student_id = models.CharField(max_length=50, blank=True, help_text="College/University Student ID")
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    grade_level = models.ForeignKey(GradeLevel, on_delete=models.SET_NULL, null=True, related_name='students')
    program = models.ForeignKey(Program, on_delete=models.SET_NULL, null=True, blank=True, related_name='students')
    year_level = models.IntegerField(null=True, blank=True, help_text="1st Year, 2nd Year, etc.")
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(Registrar, on_delete=models.SET_NULL, null=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    class Meta:
        ordering = ['last_name', 'first_name']
    
    def __str__(self):
        return f"{self.last_name}, {self.first_name} ({self.lrn})"
    
    @property
    def full_name(self):
        return f"{self.last_name}, {self.first_name} {self.middle_name[0] if self.middle_name else ''}"
    
    @property
    def year_display(self):
        if self.year_level:
            suffixes = {1: 'st', 2: 'nd', 3: 'rd'}
            suffix = suffixes.get(self.year_level, 'th')
            return f"{self.year_level}{suffix} Year"
        return "N/A"