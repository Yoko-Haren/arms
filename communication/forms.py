"""The public contact form: schools asking for ARMS, and people who need help signing in."""
from django import forms
from django.core.validators import RegexValidator

from .models import ContactRequest

POSITIONS = ['School head / Principal', 'Registrar', 'Teacher', 'IT coordinator', 'Other']

phone_format = RegexValidator(r'^[0-9+()\-.\s]{7,40}$', 'Enter a phone number using digits, spaces, + or -.')


class ContactRequestForm(forms.ModelForm):
    name = forms.CharField(max_length=120, error_messages={'required': 'Enter your name.'})
    email = forms.EmailField(max_length=254, error_messages={
        'required': 'Enter your email address so we can reply.',
        'invalid': 'Enter a valid email address, like name@school.edu.ph.',
    })
    phone = forms.CharField(max_length=40, required=False, validators=[phone_format])
    school_name = forms.CharField(max_length=200, required=False)
    position = forms.CharField(max_length=80, required=False)
    message = forms.CharField(max_length=3000, required=False, widget=forms.Textarea, error_messages={
        'max_length': 'Keep the message under 3,000 characters.',
    })

    class Meta:
        model = ContactRequest
        fields = ['topic', 'name', 'email', 'phone', 'school_name', 'position', 'message']

    def clean(self):
        data = super().clean()
        topic = data.get('topic')
        if topic == ContactRequest.TOPIC_SCHOOL and not data.get('school_name'):
            self.add_error('school_name', 'Enter the name of your school.')
        if topic == ContactRequest.TOPIC_SUPPORT and not data.get('message'):
            self.add_error('message', 'Tell us what went wrong so we can help.')
        return data
