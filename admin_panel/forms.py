from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q
import json

# ===== USE REAL MODELS =====
from academics.models import School, GradeLevel, SchoolYear, Quarter, GradingSchema
from accounts.models import UserProfile


# =============================================================================
# ADMIN LOGIN
# =============================================================================

class AdminLoginForm(forms.Form):
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'})
    )


# =============================================================================
# SCHOOL FORM — With Grading Schema Auto-Creation
# =============================================================================

class SchoolForm(forms.ModelForm):
    """School form that auto-creates grading schema(s) on save."""

    grading_schema_type = forms.ChoiceField(
        choices=[
            ('', '--- Select Grading System ---'),
            # ===== SEPARATE (Single Level) =====
            ('DEPED_JHS', 'DepEd JHS Only — DO 31, s. 2020 (Quarterly, Grades 7-10)'),
            ('DEPED_SHS', 'DepEd SHS Only — DO 31, s. 2020 (Semestral, Grades 11-12)'),
            # ===== INTEGRATED (Combined) =====
            ('DEPED_INTEGRATED', 'DepEd Integrated School — DO 31, s. 2020 (JHS Quarterly + SHS Semestral, Grades 7-12)'),
            # ===== ELEMENTARY =====
            ('DEPED_ELEMENTARY', 'DepEd Elementary — DO 31, s. 2020 (Quarterly, Grades 1-6)'),
            # ===== K-12 COMPLETE =====
            ('DEPED_K12_COMPLETE', 'DepEd K-12 Complete — DO 31, s. 2020 (Quarterly G1-10 + Semestral G11-12)'),
            # ===== HIGHER EDUCATION =====
            ('CHED_STANDARD', 'CHED Standard — CMO 14, s. 2019 (Semestral)'),
            ('CHED_TRIMESTER', 'CHED Trimester — CMO 14, s. 2019 (Trimester)'),
            # ===== TECH-VOC =====
            ('TESDA_COMPETENCY', 'TESDA Competency-Based — COC/NC (Modular)'),
            # ===== CUSTOM =====
            ('CUSTOM', 'Custom Grading System'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Grading System',
        required=False,
        help_text='Select the grading system based on school type and grade levels offered.'
    )

    class Meta:
        model = School
        fields = [
            'school_id', 'school_name', 'short_name',
            'grading_scale', 'period_type', 'passing_grade',
            'quarters_count', 'email_domain',
            'address', 'contact_number', 'theme_color', 'is_active',
        ]
        widgets = {
            'school_id': forms.TextInput(attrs={'class': 'form-control'}),
            'school_name': forms.TextInput(attrs={'class': 'form-control'}),
            'short_name': forms.TextInput(attrs={'class': 'form-control'}),
            'grading_scale': forms.Select(choices=[
                ('', '--- Select ---'),
                ('PERCENTAGE', '0-100 Percentage'),
                ('NUMERIC_1_5', '1.0 - 5.0 (1.0 highest)'),
                ('NUMERIC_5_1', '5.0 - 1.0 (5.0 highest)'),
                ('GPA_4', '0.0 - 4.0 GPA'),
                ('GPA_5', '0.0 - 5.0 GPA'),
                ('LETTER', 'A - F Letter Grades'),
            ], attrs={'class': 'form-select'}),
            'period_type': forms.Select(choices=[   
                ('QUARTERLY', 'Quarterly'),
                ('SEMESTRAL', 'Semestral'),
            ], attrs={'class': 'form-select'}),
            'passing_grade': forms.NumberInput(attrs={'class': 'form-control', 'step': '0.01', 'min': '0', 'max': '100'}),
            'quarters_count': forms.NumberInput(attrs={'class': 'form-control', 'min': '2', 'max': '4'}),
            'email_domain': forms.TextInput(attrs={'class': 'form-control', 'placeholder': '@school.edu (optional)'}),
            'address': forms.Textarea(attrs={'class': 'form-control', 'rows': 2}),
            'contact_number': forms.TextInput(attrs={'class': 'form-control'}),
            'theme_color': forms.TextInput(attrs={'class': 'form-control', 'type': 'color'}),
            'is_active': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'school_id': 'School ID',
            'school_name': 'School Name',
            'short_name': 'Short Name',
            'grading_scale': 'Grading Scale',
            'period_type': 'Period Type',
            'passing_grade': 'Passing Grade',
            'quarters_count': 'Number of Quarters',
            'email_domain': 'Email Domain',
            'address': 'Street Address',
            'contact_number': 'Contact Number',
            'theme_color': 'Theme Color',
            'is_active': 'Active',
        }

    def clean_school_id(self):
        school_id = self.cleaned_data.get('school_id')
        if school_id:
            existing = School.objects.exclude(pk=self.instance.pk).filter(school_id=school_id)
            if existing.exists():
                raise ValidationError('This School ID already exists.')
        return school_id

    def save(self, commit=True):
        school = super().save(commit=False)
        if commit:
            school.save()
            # Auto-create grading schema(s) if school is new
            schema_type = self.cleaned_data.get('grading_schema_type')
            if schema_type and not GradingSchema.objects.filter(school=school).exists():
                self._create_default_schema(school, schema_type)
        return school

    def _create_default_schema(self, school, schema_type):
        """Create default grading schema(s) based on school type."""
        import json

        # ===== COMMON GRADE RANGES =====

        # DepEd DO 31, s. 2020 — JHS & Elementary
        DEPED_RANGES = [
            (90, 100, 'A', 'Advanced', 4.0, True),
            (85, 89, 'P', 'Proficient', 3.5, True),
            (80, 84, 'AP', 'Approaching Proficiency', 3.0, True),
            (75, 79, 'D', 'Developing', 2.5, True),
            (0, 74, 'B', 'Beginning', 1.0, False),
        ]

        # CHED CMO 14, s. 2019 — College
        CHED_RANGES = [
            (96, 100, '1.00', 'Excellent', 4.0, True),
            (90, 95, '1.25', 'Superior', 3.5, True),
            (85, 89, '1.50', 'Very Good', 3.0, True),
            (80, 84, '1.75', 'Good', 2.5, True),
            (75, 79, '2.00', 'Satisfactory', 2.0, True),
            (70, 74, '2.50', 'Fair', 1.5, False),
            (65, 69, '3.00', 'Pass', 1.0, False),
            (0, 64, '5.00', 'Failed', 0.0, False),
        ]

        # TESDA Competency-Based
        TESDA_RANGES = [
            (90, 100, 'COC', 'Certificate of Competency', 4.0, True),
            (80, 89, 'NC', 'National Certificate', 3.5, True),
            (75, 79, 'NC-L1', 'NC Level 1', 3.0, True),
            (0, 74, 'NYC', 'Not Yet Competent', 0.0, False),
        ]

        # Custom fallback
        CUSTOM_RANGES = [
            (90, 100, 'A', 'Excellent', 4.0, True),
            (80, 89, 'B', 'Good', 3.0, True),
            (75, 79, 'C', 'Pass', 2.0, True),
            (0, 74, 'F', 'Fail', 0.0, False),
        ]

        # ===== BUILD SCHEMAS TO CREATE =====
        schemas_to_create = []

        if schema_type == 'DEPED_JHS':
            schemas_to_create.append(('DEPED_JHS', 'DepEd JHS — DO 31, s. 2020 (Grades 7-10)', 'QUARTERLY', 'JHS', DEPED_RANGES))

        elif schema_type == 'DEPED_SHS':
            schemas_to_create.append(('DEPED_SHS', 'DepEd SHS — DO 31, s. 2020 (Grades 11-12)', 'SEMESTRAL', 'SHS', DEPED_RANGES))

        elif schema_type == 'DEPED_INTEGRATED':
            # Creates 2 schemas: JHS (Quarterly) + SHS (Semestral)
            schemas_to_create.append(('DEPED_INTEGRATED_JHS', 'DepEd JHS — DO 31, s. 2020 (Grades 7-10)', 'QUARTERLY', 'JHS', DEPED_RANGES))
            schemas_to_create.append(('DEPED_INTEGRATED_SHS', 'DepEd SHS — DO 31, s. 2020 (Grades 11-12)', 'SEMESTRAL', 'SHS', DEPED_RANGES))

        elif schema_type == 'DEPED_ELEMENTARY':
            schemas_to_create.append(('DEPED_ELEMENTARY', 'DepEd Elementary — DO 31, s. 2020 (Grades 1-6)', 'QUARTERLY', 'ELEMENTARY', DEPED_RANGES))

        elif schema_type == 'DEPED_K12_COMPLETE':
            # Creates 3 schemas: Elementary + JHS + SHS
            schemas_to_create.append(('DEPED_K12_ELEM', 'DepEd Elementary — DO 31, s. 2020 (Grades 1-6)', 'QUARTERLY', 'ELEMENTARY', DEPED_RANGES))
            schemas_to_create.append(('DEPED_K12_JHS', 'DepEd JHS — DO 31, s. 2020 (Grades 7-10)', 'QUARTERLY', 'JHS', DEPED_RANGES))
            schemas_to_create.append(('DEPED_K12_SHS', 'DepEd SHS — DO 31, s. 2020 (Grades 11-12)', 'SEMESTRAL', 'SHS', DEPED_RANGES))

        elif schema_type == 'CHED_STANDARD':
            schemas_to_create.append(('CHED_STANDARD', 'CHED Standard — CMO 14, s. 2019', 'SEMESTRAL', 'COLLEGE', CHED_RANGES))

        elif schema_type == 'CHED_TRIMESTER':
            schemas_to_create.append(('CHED_TRIMESTER', 'CHED Trimester — CMO 14, s. 2019', 'TRIMESTER', 'COLLEGE', CHED_RANGES))

        elif schema_type == 'TESDA_COMPETENCY':
            schemas_to_create.append(('TESDA_COMPETENCY', 'TESDA Competency-Based', 'MODULAR', 'TVL', TESDA_RANGES))

        else:  # CUSTOM or fallback
            schemas_to_create.append(('CUSTOM', 'Custom Grading System', 'QUARTERLY', 'ALL', CUSTOM_RANGES))

        # ===== CREATE ALL SCHEMAS =====
        for scale_type, desc, period, grade_level, ranges in schemas_to_create:
            ranges_list = [{'min': mn, 'max': mx, 'letter': lt, 'label': lb, 'gpa': gp, 'passing': ps}
                           for mn, mx, lt, lb, gp, ps in ranges]

            GradingSchema.objects.create(
                school=school,
                scale_type=scale_type,
                passing_threshold=75,
                highest_is_best=True,
                rounding_rule='ROUND_HALF_UP',
                min_value=0,
                max_value=100,
                letter_grade_mapping=json.dumps({
                    'ranges': ranges_list,
                    'description': desc,
                    'period_type': period,
                    'grade_level': grade_level,
                }),
            )

# =============================================================================
# PRINCIPAL CREATION
# =============================================================================

class PrincipalCreationForm(forms.Form):
    """Form for creating a principal (school head) account via UserProfile."""

    first_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'First Name'})
    )
    last_name = forms.CharField(
        max_length=100,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Last Name'})
    )
    username = forms.CharField(
        max_length=150,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Username'})
    )
    email = forms.EmailField(
        widget=forms.EmailInput(attrs={'class': 'form-control', 'placeholder': 'Email'})
    )
    password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Password'}),
        help_text='Minimum 6 characters'
    )
    confirm_password = forms.CharField(
        widget=forms.PasswordInput(attrs={'class': 'form-control', 'placeholder': 'Confirm Password'})
    )
    school = forms.ModelChoiceField(
        queryset=School.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='Assign to School'
    )
    employee_id = forms.CharField(
        max_length=50,
        required=False,
        widget=forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'Employee ID (optional)'})
    )
    designation = forms.CharField(
        max_length=150,
        initial='Principal',
        widget=forms.TextInput(attrs={'class': 'form-control'})
    )

    def clean_username(self):
        username = self.cleaned_data.get('username')
        if User.objects.filter(username=username).exists():
            raise ValidationError('This username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email')
        if User.objects.filter(email=email).exists():
            raise ValidationError('This email is already in use.')
        return email

    def clean_employee_id(self):
        emp_id = self.cleaned_data.get('employee_id')
        if emp_id and UserProfile.objects.filter(employee_number=emp_id).exists():
            raise ValidationError('This Employee ID is already assigned.')
        return emp_id

    def clean(self):
        cleaned_data = super().clean()
        password = cleaned_data.get('password')
        confirm = cleaned_data.get('confirm_password')

        if password and len(password) < 6:
            raise ValidationError({'password': 'Password must be at least 6 characters.'})
        if password and password != confirm:
            raise ValidationError({'confirm_password': 'Passwords do not match.'})

        return cleaned_data


# =============================================================================
# GRADE LEVEL FORM
# =============================================================================

class GradeLevelForm(forms.ModelForm):
    class Meta:
        model = GradeLevel
        fields = ['school', 'grade_code', 'grade_name', 'grade_number', 'level_category', 'is_senior_high']
        widgets = {
            'school': forms.Select(attrs={'class': 'form-select'}),
            'grade_code': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., G7, G8'}),
            'grade_name': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., Grade 7'}),
            'grade_number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '12'}),
            'level_category': forms.Select(choices=[
                ('', '--- Select ---'),
                ('JHS', 'Junior High School'),
                ('SHS', 'Senior High School'),
                ('ELEMENTARY', 'Elementary'),
            ], attrs={'class': 'form-select'}),
            'is_senior_high': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }


# =============================================================================
# BULK GRADE LEVEL FORM
# =============================================================================

class BulkGradeLevelForm(forms.Form):
    school = forms.ModelChoiceField(
        queryset=School.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='School'
    )
    school_type = forms.ChoiceField(
        choices=[
            ('', '--- Select School Type ---'),
            ('ELEMENTARY', 'Elementary (Grades 1-6)'),
            ('JHS', 'Junior High School (Grades 7-10)'),
            ('SHS', 'Senior High School (Grades 11-12)'),
            ('INTEGRATED', 'Integrated School (JHS + SHS)'),
        ],
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='School Type'
    )


# =============================================================================
# SCHOOL YEAR FORM
# =============================================================================

class SchoolYearForm(forms.ModelForm):
    auto_create_quarters = forms.BooleanField(
        required=False,
        initial=True,
        widget=forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        label='Auto-create 4 quarters',
        help_text='Automatically create Q1-Q4 with evenly spaced dates.'
    )

    class Meta:
        model = SchoolYear
        fields = ['school', 'year_label', 'year_start', 'year_end', 'date_start', 'date_end', 'is_current', 'status']
        widgets = {
            'school': forms.Select(attrs={'class': 'form-select'}),
            'year_label': forms.TextInput(attrs={'class': 'form-control', 'placeholder': 'e.g., SY 2026-2027'}),
            'year_start': forms.NumberInput(attrs={'class': 'form-control', 'min': '2000', 'max': '2100'}),
            'year_end': forms.NumberInput(attrs={'class': 'form-control', 'min': '2000', 'max': '2100'}),
            'date_start': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_end': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_current': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'status': forms.Select(choices=[
                ('Pending', 'Pending'),
                ('Active', 'Active'),
                ('Completed', 'Completed'),
                ('Closed', 'Closed'),
            ], attrs={'class': 'form-select'}),
        }
        labels = {
            'school': 'School',
            'year_label': 'School Year Label',
            'year_start': 'Year Start (e.g., 2026)',
            'year_end': 'Year End (e.g., 2027)',
            'date_start': 'Start Date',
            'date_end': 'End Date',
            'is_current': 'Set as Current School Year',
            'status': 'Status',
        }

    def clean(self):
        cleaned_data = super().clean()
        date_start = cleaned_data.get('date_start')
        date_end = cleaned_data.get('date_end')
        if date_start and date_end and date_start >= date_end:
            raise ValidationError({'date_end': 'End date must be after start date.'})
        return cleaned_data


# =============================================================================
# QUARTER FORM
# =============================================================================

class QuarterForm(forms.ModelForm):
    class Meta:
        model = Quarter
        fields = ['school_year', 'quarter_label', 'quarter_number', 'date_start', 'date_end', 'is_current_quarter', 'is_grades_locked']
        widgets = {
            'school_year': forms.Select(attrs={'class': 'form-select'}),
            'quarter_label': forms.Select(choices=[
                ('Q1', 'First Quarter (Q1)'),
                ('Q2', 'Second Quarter (Q2)'),
                ('Q3', 'Third Quarter (Q3)'),
                ('Q4', 'Fourth Quarter (Q4)'),
            ], attrs={'class': 'form-select'}),
            'quarter_number': forms.NumberInput(attrs={'class': 'form-control', 'min': '1', 'max': '4'}),
            'date_start': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'date_end': forms.DateInput(attrs={'class': 'form-control', 'type': 'date'}),
            'is_current_quarter': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
            'is_grades_locked': forms.CheckboxInput(attrs={'class': 'form-check-input'}),
        }
        labels = {
            'school_year': 'School Year',
            'quarter_label': 'Quarter Label',
            'quarter_number': 'Quarter Number',
            'date_start': 'Start Date',
            'date_end': 'End Date',
            'is_current_quarter': 'Current Quarter',
            'is_grades_locked': 'Grades Locked',
        }
