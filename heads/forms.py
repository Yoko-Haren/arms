"""Forms of the School Head portal: starting a school year and adjusting a grading period."""
from django import forms

from academics.models import Quarter, SchoolYear
from academics.school_years import PERIOD_CONFIG


class SchoolYearStartForm(forms.ModelForm):
    """A new school year of the head's own school: its grading system (quarterly, trimestral or semestral), the
    starting year and the class dates. The label, end year and status follow, as in the admin panel."""

    period_type = forms.ChoiceField(choices=[(key, cfg['name']) for key, cfg in PERIOD_CONFIG.items()], widget=forms.RadioSelect)
    create_periods = forms.BooleanField(required=False, initial=True)

    class Meta:
        model = SchoolYear
        fields = ['year_start', 'date_start', 'date_end', 'is_current']
        widgets = {'date_start': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'date_end': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, school, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.school = school

    def clean(self):
        cleaned = super().clean()
        year, start, end = cleaned.get('year_start'), cleaned.get('date_start'), cleaned.get('date_end')
        if year:
            label = f'{year}-{year + 1}'
            if SchoolYear.objects.filter(school=self.instance.school, year_label=label).exists():
                self.add_error('year_start', f'School year {label} already exists.')
            self.instance.year_end, self.instance.year_label = year + 1, label
            if start and start.year != year:
                self.add_error('date_start', f'Classes of SY {label} start in {year}.')
            if end and end.year not in (year, year + 1):
                self.add_error('date_end', f'Classes of SY {label} end in {year} or {year + 1}.')
        if start and end and end <= start:
            self.add_error('date_end', 'The last day of classes must come after the first.')
        return cleaned

    def save(self, commit=True):
        sy = super().save(commit=False)
        sy.year_end = sy.year_start + 1
        sy.year_label = f'{sy.year_start}-{sy.year_end}'
        sy.status = 'Active' if sy.is_current else 'Upcoming'
        if commit:
            sy.save()
        return sy


class PeriodDatesForm(forms.ModelForm):
    """A grading period's dates and whether it is the current one. Grade locks stay with the registrar."""

    class Meta:
        model = Quarter
        fields = ['date_start', 'date_end', 'is_current_quarter']
        widgets = {'date_start': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'),
                   'date_end': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}
