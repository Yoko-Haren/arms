from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import NON_FIELD_ERRORS, ValidationError
from django.db.models import Q
import json
import re

# ===== USE REAL MODELS =====
from academics.models import School, GradeLevel, SchoolYear, Quarter, GradingSchema
from accounts.models import UserProfile


# =============================================================================
# GRADING PERIODS — driven by School.period_type
# =============================================================================

PERIOD_CONFIG = {
    'QUARTERLY': {'count': 4, 'prefix': 'Q', 'noun': 'Quarter', 'plural': 'Quarters'},
    'TRIMESTRAL': {'count': 3, 'prefix': 'T', 'noun': 'Trimester', 'plural': 'Trimesters'},
    'SEMESTRAL': {'count': 2, 'prefix': 'S', 'noun': 'Semester', 'plural': 'Semesters'},
}


def period_config(school):
    """Grading-period settings (count, label prefix, wording) for a school."""
    return PERIOD_CONFIG.get(school.period_type, PERIOD_CONFIG['QUARTERLY'])


def default_registrar_account(school):
    """Default registrar login for a school: <short name>.registrar@<email domain>."""
    slug = re.sub(r'[^a-z0-9]+', '', (school.short_name or '').lower())
    domain = (school.email_domain or '').strip().lower().lstrip('@')
    if not slug or not domain:
        return None
    return f'{slug}.registrar@{domain}'


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
            'period_type': forms.Select(attrs={'class': 'form-select'}),
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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # The count always follows the period type (see clean()).
        self.fields['quarters_count'].required = False

    def clean(self):
        cleaned_data = super().clean()
        period_type = cleaned_data.get('period_type')
        if period_type in PERIOD_CONFIG:
            cleaned_data['quarters_count'] = PERIOD_CONFIG[period_type]['count']
        return cleaned_data

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
        username = self.cleaned_data.get('username', '').strip().lower()
        if User.objects.filter(username__iexact=username).exists():
            raise ValidationError('This username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exists():
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


class PrincipalEditForm(forms.Form):
    """Edit an existing principal's account details and school assignment."""

    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    username = forms.CharField(max_length=150)
    email = forms.EmailField()
    school = forms.ModelChoiceField(queryset=School.objects.none())
    employee_id = forms.CharField(max_length=50, required=False)
    designation = forms.CharField(max_length=150, required=False)

    def __init__(self, *args, principal, **kwargs):
        self.principal = principal
        super().__init__(*args, **kwargs)
        # Keep the current school selectable even if it has been deactivated.
        self.fields['school'].queryset = School.objects.filter(
            Q(is_active=True) | Q(pk=principal.school_id)
        )

    def clean_username(self):
        username = self.cleaned_data.get('username', '').strip().lower()
        if User.objects.filter(username__iexact=username).exclude(pk=self.principal.user_id).exists():
            raise ValidationError('This username is already taken.')
        return username

    def clean_email(self):
        email = self.cleaned_data.get('email', '').strip().lower()
        if User.objects.filter(email__iexact=email).exclude(pk=self.principal.user_id).exists():
            raise ValidationError('This email is already in use.')
        return email

    def clean_employee_id(self):
        emp_id = (self.cleaned_data.get('employee_id') or '').strip()
        if emp_id and UserProfile.objects.filter(employee_number=emp_id).exclude(pk=self.principal.pk).exists():
            raise ValidationError('This Employee ID is already assigned.')
        return emp_id


class RegistrarCreationForm(forms.Form):
    """Creates the default registrar account of a school; only the school is chosen."""

    school = forms.ModelChoiceField(
        queryset=School.objects.filter(is_active=True),
        widget=forms.Select(attrs={'class': 'form-select'}),
        label='School',
    )

    def clean_school(self):
        school = self.cleaned_data['school']
        account = default_registrar_account(school)
        if not account:
            raise ValidationError(
                f'{school.school_name} needs a Short Name and an Email Domain before '
                'its registrar account can be generated. Edit the school first.'
            )
        if User.objects.filter(Q(username__iexact=account) | Q(email__iexact=account)).exists():
            raise ValidationError(f'The registrar account {account} already exists.')
        self.account = account
        return school


# =============================================================================
# GRADE LEVEL FORM
# =============================================================================

# The GradeLevel model only supports Grades 7-12 (JHS / SHS).
GRADE_NUMBERS = list(range(7, 13))


class GradeLevelForm(forms.Form):
    school = forms.ModelChoiceField(queryset=School.objects.filter(is_active=True))
    grades = forms.TypedMultipleChoiceField(
        choices=[(n, f'Grade {n}') for n in GRADE_NUMBERS],
        coerce=int,
        error_messages={'required': 'Select at least one grade level.'},
    )


# =============================================================================
# SCHOOL YEAR FORM
# =============================================================================

class SchoolYearForm(forms.ModelForm):
    """Only the starting year and class dates are entered; label, end year and status are derived."""

    auto_create_periods = forms.BooleanField(required=False)

    class Meta:
        model = SchoolYear
        fields = ['school', 'year_start', 'date_start', 'date_end', 'is_current']

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['school'].queryset = School.objects.filter(is_active=True)

    def clean(self):
        cleaned_data = super().clean()
        school = cleaned_data.get('school')
        year_start = cleaned_data.get('year_start')
        if school and year_start:
            label = f'{year_start}-{year_start + 1}'
            if SchoolYear.objects.filter(school=school, year_label=label).exists():
                raise ValidationError({'year_start': f'School year {label} already exists for {school.school_name}.'})
        return cleaned_data

    def save(self, commit=True):
        sy = super().save(commit=False)
        sy.year_end = sy.year_start + 1
        sy.year_label = f'{sy.year_start}-{sy.year_end}'
        sy.status = 'Active' if sy.is_current else 'Upcoming'
        if commit:
            sy.save()
        return sy


# =============================================================================
# GRADING PERIOD FORMS (stored in the Quarter table)
# =============================================================================

class QuarterForm(forms.ModelForm):
    """One grading period; its label (Q/T/S + number) follows the school's period type."""

    class Meta:
        model = Quarter
        fields = ['school_year', 'quarter_number', 'date_start', 'date_end', 'is_current_quarter']
        error_messages = {
            NON_FIELD_ERRORS: {'unique_together': 'That period already exists for this school year.'},
        }

    def clean(self):
        cleaned_data = super().clean()
        school_year = cleaned_data.get('school_year')
        number = cleaned_data.get('quarter_number')
        if school_year and number:
            cfg = period_config(school_year.school)
            if number > cfg['count']:
                raise ValidationError({
                    'quarter_number': f'{school_year.school.school_name} only has {cfg["count"]} {cfg["plural"].lower()} per school year.'
                })
            self.instance.quarter_label = f'{cfg["prefix"]}{number}'
        return cleaned_data


class QuarterUpdateForm(forms.ModelForm):
    class Meta:
        model = Quarter
        fields = ['date_start', 'date_end', 'is_current_quarter', 'is_grades_locked']
