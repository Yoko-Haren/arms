"""School Head: the school's school years and grading periods.

The System Administrator sets up schools; the School Head runs the school's own calendar from here
without waiting for the admin: starting the next school year with its grading periods, choosing the
current year and period, and adjusting period dates. Grade locks stay with the registrar (Grade
Validation), and a year that already holds sections, enrollments or grades is never deleted. Every
change is logged, and the registrars are told when a year starts or becomes current.

The School Head also chooses here which DepEd order the school follows for grade descriptors and academic
awards (core/grading_policy.py): DepEd Order No. 8, s. 2015 with DO 36, s. 2016, or DepEd Order No. 015, s. 2026.
"""
from datetime import date

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Count, ProtectedError
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from academics.models import Quarter, SchoolYear, Section
from academics.school_years import PERIOD_CONFIG, generate_periods, has_records, period_config, year_config
from communication.notify import notify, school_registrars
from core import grading_policy
from enrollment.models import Enrollment
from grades.models import GradeComponent

from .forms import PeriodDatesForm, SchoolYearStartForm
from .views_academic import _denied, _head_school, _person, period_name


def _log(request, action, sy_id, description, resource_type='SchoolYear'):
    try:
        from audit.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user, user_name=_person(request.user), user_role='schoolhead', action_type=action,
            resource_type=resource_type, resource_id=str(sy_id), details_json={'description': description},
            ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'), user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
    except Exception:
        pass


def _tell_registrars(school, title, message):
    notify(school_registrars(school), 'SYSTEM_UPDATE', title, message, action_url=reverse('registrars:dashboard'))


def _shift_year(day, years):
    try:
        return day.replace(year=day.year + years)
    except ValueError:                                     # 29 February
        return day.replace(year=day.year + years, day=28)


def _defaults(school):
    """The next school year after the latest one, with the same class dates a year later and the same grading system."""
    latest = SchoolYear.objects.filter(school=school).order_by('-year_start').first()
    kind = year_config(latest)['key'] if latest else period_config(school)['key']
    if latest:
        return {'year_start': latest.year_start + 1, 'date_start': _shift_year(latest.date_start, 1),
                'date_end': _shift_year(latest.date_end, 1), 'create_periods': True, 'period_type': kind}
    year = timezone.localdate().year
    return {'year_start': year, 'date_start': date(year, 6, 16), 'date_end': date(year + 1, 3, 31), 'create_periods': True,
            'period_type': kind}


def _errors(form):
    return ' '.join(str(e) for errors in form.errors.values() for e in errors)


@login_required
def school_year(request):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    form = SchoolYearStartForm(request.POST or None, school=school, initial=_defaults(school))
    if request.method == 'POST' and form.is_valid():
        kind = form.cleaned_data['period_type']
        cfg = PERIOD_CONFIG[kind]
        with transaction.atomic():
            if form.cleaned_data['is_current']:
                SchoolYear.objects.filter(school=school, is_current=True, status='Active').update(status='Completed')
            sy = form.save()
            # the school's grading system from now on: the new year's (its periods keep their own labels either way)
            if school.period_type != kind:
                school.period_type, school.quarters_count = kind, cfg['count']
                school.save(update_fields=['period_type', 'quarters_count', 'updated_at'])
            created = generate_periods(sy, kind)[0] if form.cleaned_data['create_periods'] else 0
            if created and sy.is_current:
                today = timezone.localdate()
                first = Quarter.objects.filter(school_year=sy, date_start__lte=today, date_end__gte=today).first() or \
                    Quarter.objects.filter(school_year=sy).order_by('quarter_number').first()
                first.is_current_quarter = True
                first.save()
        made = f' with {created} {cfg["plural"].lower()} ({cfg["name"].lower()})' if created else f' ({cfg["name"].lower()})'
        messages.success(request, f'SY {sy.year_label} is set up{made}.' + (' It is now the current school year.' if sy.is_current else
                                                                            ' Make it current when classes start.'))
        _log(request, 'CREATE_SCHOOL_YEAR', sy.id, f'Started SY {sy.year_label}{made}' + (' as the current school year' if sy.is_current else ''))
        _tell_registrars(school, f'New school year: SY {sy.year_label}',
                         f'{_person(request.user)} started SY {sy.year_label} ({sy.date_start:%B %d, %Y} to {sy.date_end:%B %d, %Y})'
                         + (', now the current school year.' if sy.is_current else '.'))
        return redirect('heads-school-year')

    years = list(SchoolYear.objects.filter(school=school).order_by('-year_start'))
    ids = [y.id for y in years]
    sections = dict(Section.objects.filter(school_year_id__in=ids).values('school_year_id').annotate(n=Count('id')).values_list('school_year_id', 'n'))
    learners = dict(Enrollment.objects.filter(school_year_id__in=ids).values('school_year_id').annotate(n=Count('id')).values_list('school_year_id', 'n'))
    grades = dict(GradeComponent.objects.filter(quarter__school_year_id__in=ids).values('quarter__school_year_id')
                  .annotate(n=Count('id')).values_list('quarter__school_year_id', 'n'))
    periods = {}
    for q in Quarter.objects.filter(school_year_id__in=ids).order_by('quarter_number'):
        q.name = period_name(q)
        q.form = PeriodDatesForm(instance=q, prefix=f'p{q.id}')
        periods.setdefault(q.school_year_id, []).append(q)
    today = timezone.localdate()
    for y in years:
        y.periods = periods.get(y.id, [])
        y.cfg = year_config(y, y.periods)
        y.missing = max(y.cfg['count'] - len(y.periods), 0)
        y.n_sections, y.n_learners, y.n_grades = sections.get(y.id, 0), learners.get(y.id, 0), grades.get(y.id, 0)
        y.deletable = not (y.n_sections or y.n_learners or y.n_grades)
        y.running = y.date_start <= today <= y.date_end
    return render(request, 'heads/school_year/index.html', {
        'school': school, 'years': years, 'form': form, 'cfg': period_config(school), 'open_form': request.method == 'POST',
        'systems': list(PERIOD_CONFIG.values()), 'chosen_system': form['period_type'].value() or period_config(school)['key'],
        'form_errors': _errors(form) if request.method == 'POST' else '',
        'policies': list(grading_policy.POLICIES.values()), 'policy_key': grading_policy.key_of(school),
    })


@login_required
@require_POST
def grading_policy_update(request):
    """The DepEd rules the school follows for grade descriptors and academic awards (core/grading_policy.py)."""
    school = _head_school(request)
    if school is None:
        return _denied(request)
    chosen = request.POST.get('grading_policy')
    if chosen not in grading_policy.POLICIES:
        messages.error(request, 'Choose one of the two DepEd orders.')
        return redirect('heads-school-year')
    if chosen != school.grading_policy:
        school.grading_policy = chosen
        school.save(update_fields=['grading_policy', 'updated_at'])
        rules = grading_policy.POLICIES[chosen]
        messages.success(request, f'{school.school_name} now follows {rules["name"]} for grade descriptors and academic awards. '
                                  'Every School Head page uses it from now on.')
        _log(request, 'UPDATE_SCHOOL', school.id, f'Grading rules set to {rules["name"]}', resource_type='School')
    return redirect('heads-school-year')


@login_required
@require_POST
def school_year_make_current(request, sy_id):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    sy = get_object_or_404(SchoolYear, id=sy_id, school=school)
    with transaction.atomic():
        SchoolYear.objects.filter(school=school, is_current=True, status='Active').exclude(pk=sy.pk).update(status='Completed')
        sy.is_current, sy.status = True, 'Active'
        sy.save()                                          # SchoolYear.save clears the school's other current year
        periods = Quarter.objects.filter(school_year=sy)
        if periods.exists() and not periods.filter(is_current_quarter=True).exists():
            today = timezone.localdate()
            pick = periods.filter(date_start__lte=today, date_end__gte=today).first() or periods.order_by('quarter_number').first()
            pick.is_current_quarter = True
            pick.save()
    messages.success(request, f'SY {sy.year_label} is now the current school year. The dashboards and the registrar open it by default.')
    _log(request, 'UPDATE_SCHOOL_YEAR', sy.id, f'Made SY {sy.year_label} the current school year')
    _tell_registrars(school, f'SY {sy.year_label} is now the current school year',
                     f'{_person(request.user)} made SY {sy.year_label} the current school year.')
    return redirect('heads-school-year')


@login_required
@require_POST
def school_year_periods(request, sy_id):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    sy = get_object_or_404(SchoolYear.objects.select_related('school'), id=sy_id, school=school)
    created, existing = generate_periods(sy)
    plural = year_config(sy)['plural'].lower()
    if created:
        messages.success(request, f'{created} {plural} created for SY {sy.year_label}, split evenly over its dates. Adjust any of them below.')
        _log(request, 'CREATE_PERIODS', sy.id, f'Created {created} {plural} for SY {sy.year_label}')
    else:
        messages.info(request, f'All {existing} {plural} of SY {sy.year_label} already exist.')
    return redirect('heads-school-year')


@login_required
@require_POST
def period_update(request, period_id):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    period = get_object_or_404(Quarter.objects.select_related('school_year'), id=period_id, school_year__school=school)
    form = PeriodDatesForm(request.POST, instance=period, prefix=f'p{period.id}')
    if form.is_valid():
        form.save()
        messages.success(request, f'{period_name(period)} of SY {period.school_year.year_label} updated.')
        _log(request, 'UPDATE_PERIOD', period.school_year_id, f'Updated {period_name(period)} of SY {period.school_year.year_label}')
    else:
        messages.error(request, f'{period_name(period)} was not changed. {_errors(form)}')
    return redirect('heads-school-year')


@login_required
@require_POST
def school_year_delete(request, sy_id):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    sy = get_object_or_404(SchoolYear, id=sy_id, school=school)
    if has_records(sy):
        messages.error(request, f'SY {sy.year_label} already has sections, enrollments or grades, so it cannot be deleted.')
        return redirect('heads-school-year')
    label, sy_id = sy.year_label, sy.id
    try:
        with transaction.atomic():
            Quarter.objects.filter(school_year=sy).delete()
            sy.delete()
    except ProtectedError:
        messages.error(request, f'SY {label} has records attached and cannot be deleted.')
        return redirect('heads-school-year')
    messages.success(request, f'SY {label} deleted.')
    _log(request, 'DELETE_SCHOOL_YEAR', sy_id, f'Deleted the empty SY {label}')
    return redirect('heads-school-year')
