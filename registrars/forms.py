import re

from django import forms
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.db.models import Q

from accounts.models import UserProfile


def _name_slug(value):
    return re.sub(r'[^a-z0-9]+', '', (value or '').lower())


def school_email_domain(school):
    return (school.email_domain or '').strip().lower().lstrip('@')


def _email_taken(email, reserved=()):
    return (
        email in reserved
        or User.objects.filter(Q(username__iexact=email) | Q(email__iexact=email)).exists()
        or UserProfile.objects.filter(deped_email__iexact=email).exists()
    )


def suggest_teacher_email(school, first_name, last_name, reserved=()):
    """firstname.lastname@<school domain>, numbered if that address is already used.

    `reserved` holds addresses already taken by earlier rows of the same batch.
    """
    domain = school_email_domain(school)
    local = '.'.join(part for part in (_name_slug(first_name), _name_slug(last_name)) if part)
    if not domain or not local:
        return None
    email, counter = f'{local}@{domain}', 1
    while _email_taken(email, reserved):
        counter += 1
        email = f'{local}{counter}@{domain}'
    return email


class TeacherAccountForm(forms.Form):
    """Teacher account for the registrar's own school. The email doubles as the username."""

    first_name = forms.CharField(max_length=100)
    last_name = forms.CharField(max_length=100)
    email = forms.EmailField(required=False)
    employee_number = forms.CharField(max_length=50, required=False)
    designation = forms.CharField(max_length=150, required=False)
    teaching_area = forms.CharField(max_length=150, required=False)

    def __init__(self, *args, school, reserved=(), **kwargs):
        self.school = school
        self.reserved = reserved
        super().__init__(*args, **kwargs)

    def clean_first_name(self):
        return ' '.join(self.cleaned_data['first_name'].split())

    def clean_last_name(self):
        return ' '.join(self.cleaned_data['last_name'].split())

    def clean_employee_number(self):
        number = (self.cleaned_data.get('employee_number') or '').strip()
        if number and UserProfile.objects.filter(employee_number=number).exists():
            raise ValidationError('This employee number is already assigned to another account.')
        return number

    def clean(self):
        cleaned_data = super().clean()
        if 'email' not in cleaned_data:
            return cleaned_data
        email = (cleaned_data.get('email') or '').strip().lower()
        if email:
            if _email_taken(email, self.reserved):
                self.add_error('email', 'An account with this email already exists.')
        else:
            email = suggest_teacher_email(self.school, cleaned_data.get('first_name'), cleaned_data.get('last_name'), self.reserved)
            if not email and cleaned_data.get('first_name') and cleaned_data.get('last_name'):
                self.add_error('email', 'Your school has no email domain set, so please type the teacher\'s email.')
        cleaned_data['email'] = email
        return cleaned_data
