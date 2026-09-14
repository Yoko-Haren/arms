# students/models.py
"""
Phase 3: Core Student Master Data for Formify LIS.
Permanent student records, addresses, contacts, guardians,
medical info, documents, and sibling tracking.
"""

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator, MaxValueValidator, RegexValidator
from django.db import models
from django.utils import timezone


# =============================================================================
# 3.1 — Student
# =============================================================================
class Student(models.Model):
    SEX_CHOICES = [
        ('M', 'Male'),
        ('F', 'Female'),
    ]
    NAME_EXTENSION_CHOICES = [
        ('', 'None'),
        ('Jr.', 'Jr.'),
        ('Sr.', 'Sr.'),
        ('II', 'II'),
        ('III', 'III'),
        ('IV', 'IV'),
        ('V', 'V'),
        ('VI', 'VI'),
    ]

    lrn = models.CharField(
        max_length=12,
        unique=True,
        db_index=True,
        help_text='Learner Reference Number — 12-digit DepEd national identifier.',
        validators=[RegexValidator(r'^\d{12}$', 'LRN must be exactly 12 digits.')],
    )
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    name_extension = models.CharField(
        max_length=10,
        blank=True,
        choices=NAME_EXTENSION_CHOICES,
    )
    birth_date = models.DateField(null=True, blank=True)
    birth_place = models.CharField(max_length=255, blank=True)
    sex = models.CharField(max_length=1, choices=SEX_CHOICES)
    gender_identity = models.CharField(max_length=50, blank=True)
    nationality = models.CharField(max_length=100, default='Filipino')
    mother_tongue = models.CharField(max_length=100, blank=True)
    ethnicity = models.CharField(max_length=100, blank=True)
    is_ip = models.BooleanField(
        default=False,
        help_text='Indigenous Peoples learner.',
    )
    religion = models.CharField(max_length=100, blank=True)
    has_disability = models.BooleanField(
        default=False,
        help_text='Learner with Disability (LWD).',
    )
    disability_type = models.CharField(max_length=100, blank=True)
    is_4ps = models.BooleanField(
        default=False,
        help_text='Pantawid Pamilyang Pilipino Program (4Ps) beneficiary.',
    )
    _4ps_household_id = models.CharField(
        max_length=50,
        blank=True,
        db_column='four_ps_household_id',
        help_text='DSWD household ID number.',
    )
    psa_birth_certificate_number = models.CharField(max_length=50, blank=True)
    photo = models.ImageField(
        upload_to='students/photos/%Y/%m/',
        null=True,
        blank=True,
    )
    is_active = models.BooleanField(default=True, db_index=True)
    is_verified = models.BooleanField(
        default=False,
        help_text='Records verified against PSA/DepEd LIS database.',
    )
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_students',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='created_students')
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='updated_students')
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['last_name', 'first_name']
        verbose_name = 'Student'
        verbose_name_plural = 'Students'
        indexes = [
            models.Index(fields=['lrn']),
            models.Index(fields=['last_name', 'first_name']),
            models.Index(fields=['is_active']),
        ]

    @property
    def full_name(self):
        parts = [self.last_name + ',']
        parts.append(self.first_name)
        if self.middle_name:
            parts.append(self.middle_name)
        if self.name_extension:
            parts.append(self.name_extension)
        return ' '.join(parts)

    @property
    def age(self):
        if self.birth_date:
            today = timezone.now().date()
            return today.year - self.birth_date.year - (
                (today.month, today.day) < (self.birth_date.month, self.birth_date.day)
            )
        return None

    def clean(self):
        if self.birth_date and self.birth_date > timezone.now().date():
            raise ValidationError({
                'birth_date': 'Birth date cannot be in the future.',
            })
        if self.lrn and len(self.lrn) != 12:
            raise ValidationError({
                'lrn': 'LRN must be exactly 12 digits.',
            })

    def __str__(self):
        base = f"{self.last_name}, {self.first_name}"
        if self.middle_name:
            base += f" {self.middle_name}"
        if self.name_extension:
            base += f" {self.name_extension}"
        return base.strip()


# =============================================================================
# 3.2 — StudentAddress
# =============================================================================
class StudentAddress(models.Model):
    ADDRESS_TYPE_CHOICES = [
        ('Current', 'Current Residence'),
        ('Permanent', 'Permanent Address'),
        ('Guardian', 'Guardian Address'),
        ('Mailing', 'Mailing Address'),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='addresses',
    )
    address_type = models.CharField(
        max_length=20,
        choices=ADDRESS_TYPE_CHOICES,
        db_index=True,
    )
    house_number_street = models.CharField(max_length=255)
    sitio_purok = models.CharField(max_length=100, blank=True)
    barangay = models.CharField(max_length=100)
    city_municipality = models.CharField(max_length=100)
    province = models.CharField(max_length=100)
    region = models.CharField(max_length=50)
    zip_code = models.CharField(max_length=4, blank=True)
    is_primary = models.BooleanField(default=False)
    is_living_arrangement = models.BooleanField(
        default=False,
        help_text='Is this where the student lives during school days?',
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student', '-is_primary', 'address_type']
        unique_together = [['student', 'address_type']]
        verbose_name = 'Student Address'
        verbose_name_plural = 'Student Addresses'

    def __str__(self):
        return (
            f"{self.student.lrn} — {self.get_address_type_display()}: "
            f"{self.barangay}, {self.city_municipality}"
        )


# =============================================================================
# 3.3 — StudentContact
# =============================================================================
class StudentContact(models.Model):
    CONTACT_TYPE_CHOICES = [
        ('Mobile', 'Mobile Phone'),
        ('Landline', 'Landline'),
        ('Email', 'Email'),
        ('Facebook', 'Facebook'),
        ('Viber', 'Viber'),
        ('WhatsApp', 'WhatsApp'),
        ('Other', 'Other'),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='contacts',
    )
    contact_type = models.CharField(max_length=20, choices=CONTACT_TYPE_CHOICES)
    contact_value = models.CharField(max_length=255)
    is_primary = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    can_receive_sms = models.BooleanField(default=False)
    notes = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student', '-is_primary', 'contact_type']
        verbose_name = 'Student Contact'
        verbose_name_plural = 'Student Contacts'

    def __str__(self):
        return f"{self.student.lrn} — {self.get_contact_type_display()}: {self.contact_value}"


# =============================================================================
# 3.4 — StudentMedical
# =============================================================================
class StudentMedical(models.Model):
    BLOOD_TYPE_CHOICES = [
        ('', 'Unknown'),
        ('A+', 'A+'),
        ('A-', 'A-'),
        ('B+', 'B+'),
        ('B-', 'B-'),
        ('AB+', 'AB+'),
        ('AB-', 'AB-'),
        ('O+', 'O+'),
        ('O-', 'O-'),
    ]

    student = models.OneToOneField(
        Student,
        on_delete=models.CASCADE,
        related_name='medical_info',
    )
    blood_type = models.CharField(
        max_length=5,
        blank=True,
        choices=BLOOD_TYPE_CHOICES,
    )
    allergies = models.TextField(blank=True)
    chronic_conditions = models.TextField(blank=True)
    current_medications = models.TextField(blank=True)
    physician_name = models.CharField(max_length=255, blank=True)
    physician_contact = models.CharField(max_length=100, blank=True)
    emergency_notes = models.TextField(blank=True)
    last_physical_exam_date = models.DateField(null=True, blank=True)
    is_fit_for_physical_activity = models.BooleanField(default=True)
    activity_restrictions = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = 'Student Medical Record'
        verbose_name_plural = 'Student Medical Records'

    def __str__(self):
        return f"Medical Record: {self.student.lrn}"


# =============================================================================
# 3.5 — StudentLearningSupport
# =============================================================================
class StudentLearningSupport(models.Model):
    SUPPORT_TYPE_CHOICES = [
        ('ALS', 'Alternative Learning System'),
        ('Remedial', 'Remedial Program'),
        ('Intervention', 'Academic Intervention'),
        ('Enrichment', 'Enrichment Program'),
        ('SPED', 'Special Education'),
        ('MTB_MLE', 'Mother Tongue-Based Multilingual Education'),
        ('IPEd', 'Indigenous Peoples Education'),
        ('Madrasah', 'Madrasah Education'),
        ('Other', 'Other'),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='learning_supports',
    )
    support_type = models.CharField(max_length=30, choices=SUPPORT_TYPE_CHOICES)
    support_description = models.TextField(blank=True)
    start_date = models.DateField()
    end_date = models.DateField(null=True, blank=True)
    provider = models.CharField(max_length=255, blank=True)
    outcome = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student', '-start_date']
        verbose_name = 'Student Learning Support Record'
        verbose_name_plural = 'Student Learning Support Records'

    def clean(self):
        if self.end_date and self.start_date and self.end_date < self.start_date:
            raise ValidationError({
                'end_date': 'End date must be on or after the start date.',
            })

    def __str__(self):
        return f"{self.student.lrn} — {self.get_support_type_display()}"


# =============================================================================
# 3.6 — Guardian
# =============================================================================
class Guardian(models.Model):
    RELATIONSHIP_CHOICES = [
        ('Father', 'Father'),
        ('Mother', 'Mother'),
        ('Stepfather', 'Stepfather'),
        ('Stepmother', 'Stepmother'),
        ('Grandfather', 'Grandfather'),
        ('Grandmother', 'Grandmother'),
        ('Aunt', 'Aunt'),
        ('Uncle', 'Uncle'),
        ('Sibling', 'Sibling'),
        ('Legal Guardian', 'Legal Guardian'),
        ('Foster Parent', 'Foster Parent'),
        ('Other Relative', 'Other Relative'),
        ('Other', 'Other'),
    ]
    INCOME_RANGE_CHOICES = [
        ('', 'Unknown'),
        ('Below 5,000', 'Below ₱5,000'),
        ('5,000-10,000', '₱5,000–₱10,000'),
        ('10,001-20,000', '₱10,001–₱20,000'),
        ('20,001-40,000', '₱20,001–₱40,000'),
        ('Above 40,000', 'Above ₱40,000'),
    ]
    EDUCATION_CHOICES = [
        ('', 'Unknown'),
        ('No Formal Education', 'No Formal Education'),
        ('Elementary Undergraduate', 'Elementary Undergraduate'),
        ('Elementary Graduate', 'Elementary Graduate'),
        ('High School Undergraduate', 'High School Undergraduate'),
        ('High School Graduate', 'High School Graduate'),
        ('Vocational', 'Vocational/Technical'),
        ('College Undergraduate', 'College Undergraduate'),
        ('College Graduate', 'College Graduate'),
        ('Post-Graduate', 'Post-Graduate'),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='guardians',
    )
    first_name = models.CharField(max_length=100)
    middle_name = models.CharField(max_length=100, blank=True)
    last_name = models.CharField(max_length=100)
    relationship = models.CharField(max_length=30, choices=RELATIONSHIP_CHOICES)
    occupation = models.CharField(max_length=150, blank=True)
    employer = models.CharField(max_length=255, blank=True)
    monthly_income_range = models.CharField(
        max_length=50,
        blank=True,
        choices=INCOME_RANGE_CHOICES,
    )
    educational_attainment = models.CharField(
        max_length=100,
        blank=True,
        choices=EDUCATION_CHOICES,
    )
    is_primary_guardian = models.BooleanField(
        default=False,
        help_text='Primary contact for emergencies and school communications.',
    )
    is_living_with_student = models.BooleanField(default=True)
    is_authorized_to_pickup = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student', '-is_primary_guardian', 'relationship']
        verbose_name = 'Guardian'
        verbose_name_plural = 'Guardians'

    @property
    def full_name(self):
        parts = [self.last_name + ',']
        parts.append(self.first_name)
        if self.middle_name:
            parts.append(self.middle_name)
        return ' '.join(parts)

    def __str__(self):
        return f"{self.last_name}, {self.first_name} — {self.get_relationship_display()} of {self.student.lrn}"


# =============================================================================
# 3.7 — GuardianContact
# =============================================================================
class GuardianContact(models.Model):
    CONTACT_TYPE_CHOICES = [
        ('Mobile', 'Mobile Phone'),
        ('Landline', 'Landline'),
        ('Email', 'Email'),
        ('Facebook', 'Facebook'),
        ('Viber', 'Viber'),
        ('WhatsApp', 'WhatsApp'),
        ('Work', 'Work Phone'),
        ('Other', 'Other'),
    ]

    guardian = models.ForeignKey(
        Guardian,
        on_delete=models.CASCADE,
        related_name='contacts',
    )
    contact_type = models.CharField(max_length=20, choices=CONTACT_TYPE_CHOICES)
    contact_value = models.CharField(max_length=255)
    is_primary = models.BooleanField(default=False)
    can_receive_sms = models.BooleanField(default=False)
    is_verified = models.BooleanField(default=False)
    notes = models.CharField(max_length=100, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['guardian', '-is_primary', 'contact_type']
        verbose_name = 'Guardian Contact'
        verbose_name_plural = 'Guardian Contacts'

    def __str__(self):
        return f"{self.guardian} — {self.get_contact_type_display()}: {self.contact_value}"


# =============================================================================
# 3.8 — SiblingEnrollment
# =============================================================================
class SiblingEnrollment(models.Model):
    RELATIONSHIP_CHOICES = [
        ('Twin', 'Twin'),
        ('Full Sibling', 'Full Sibling'),
        ('Half Sibling', 'Half Sibling'),
        ('Step Sibling', 'Step Sibling'),
    ]

    student_1 = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='sibling_links_1',
    )
    student_2 = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='sibling_links_2',
    )
    relationship = models.CharField(max_length=20, choices=RELATIONSHIP_CHOICES)
    school_year = models.ForeignKey(
        'academics.SchoolYear',
        on_delete=models.CASCADE,
        related_name='sibling_enrollments',
    )
    is_verified = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = [['student_1', 'student_2', 'school_year']]
        ordering = ['school_year', 'student_1__last_name']
        verbose_name = 'Sibling Enrollment'
        verbose_name_plural = 'Sibling Enrollments'

    def clean(self):
        if self.student_1_id and self.student_2_id and self.student_1 == self.student_2:
            raise ValidationError({
                'student_2': 'A student cannot be their own sibling.',
            })

    def __str__(self):
        return (
            f"{self.student_1.lrn} & {self.student_2.lrn} — "
            f"{self.get_relationship_display()} ({self.school_year.year_label})"
        )


# =============================================================================
# 3.9 — StudentDocument
# =============================================================================
class StudentDocument(models.Model):
    DOCUMENT_TYPE_CHOICES = [
        ('PSA_Birth_Certificate', 'PSA Birth Certificate'),
        ('SF9_Previous', 'SF9 — Previous Report Card'),
        ('SF10_Form137', 'SF10 — Form 137'),
        ('Good_Moral', 'Certificate of Good Moral Character'),
        ('Medical_Certificate', 'Medical Certificate'),
        ('Barangay_Clearance', 'Barangay Clearance'),
        ('ID_Photo', 'ID Photo'),
        ('ESC_Certificate', 'ESC Certificate'),
        ('Immunization_Record', 'Immunization Record'),
        ('Other', 'Other'),
    ]

    student = models.ForeignKey(
        Student,
        on_delete=models.CASCADE,
        related_name='documents',
    )
    document_type = models.CharField(max_length=30, choices=DOCUMENT_TYPE_CHOICES)
    file = models.FileField(upload_to='students/documents/%Y/%m/%d/')
    file_name = models.CharField(max_length=255)
    is_submitted = models.BooleanField(default=False)
    submission_date = models.DateField(null=True, blank=True)
    is_verified = models.BooleanField(default=False)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='verified_documents',
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['student', 'document_type']
        verbose_name = 'Student Document'
        verbose_name_plural = 'Student Documents'

    def __str__(self):
        return f"{self.student.lrn} — {self.get_document_type_display()}"