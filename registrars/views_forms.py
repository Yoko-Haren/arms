"""Registrar: the DepEd school forms (SF1 to SF7, the summaries) filled from ARMS, ready to download.

The forms are DepEd's own templates (documentation.school_forms). The page offers every form with
what it needs (a section, a month, a semester, Junior or Senior High), the school year to report
on, and the header every form carries (region, division, district), which ARMS learns from the
SF1 the registrar imports and the registrar may correct here.
"""
from django.contrib import messages
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import urlencode

from academics.models import Quarter, SchoolYear, Section
from core import school_header
from enrollment.models import Enrollment
from documentation import form_data as FD
from documentation import school_forms as SF

XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

# The cards of the page, in DepEd's order: what each form is, what it is filled from, what it asks for
CARDS = (
    ('SF1', 'School Register', 'Every learner with LRN, birth date, address, parents or guardian and REMARKS codes.',
     'section', ('semester',)),
    ('SF2', 'Daily Attendance Report', 'School days of the month, each learner\'s absences and tardiness, and the summary box.',
     'section', ('month', 'semester')),
    ('SF3', 'Books Issued and Returned', 'The class list with the section\'s subjects as the book titles; dates are filled by hand.',
     'section', ('semester',)),
    ('SF4', "Monthly Learner's Movement", 'Every section: registered learners, average daily attendance, dropouts and transfers.',
     'school', ('month', 'level', 'semester')),
    ('SF5', 'Report on Promotion', 'General average and action taken (Grades 7 to 10); end-of-semester status SF5A (Senior High).',
     'section', ('semester',)),
    ('SF5B', 'SHS Completers', 'Grade 12 learners who completed every subject of both semesters.', 'section12', ()),
    ('SF6', 'Summarized Promotion Report', 'Promoted, conditional and retained, and the learning progress, by grade level.',
     'school', ('level', 'semester')),
    ('SF7', 'Personnel Assignment List', 'Staff by position with their subjects, sections, advisory and teaching minutes.',
     'school', ('level', 'semester')),
    ('SUMMARY', 'Summary of Final Grades', 'Each learner\'s quarterly grades in the eight learning areas; the sheet computes the '
     'final grades and the general average.', 'section_jhs', ()),
)


def _registrar_school(request):
    return request.user.profile.school


def _school_years(school):
    return list(SchoolYear.objects.filter(school=school).order_by('-year_start'))


def _chosen_year(request, school, years):
    wanted = request.GET.get('sy') or request.POST.get('sy')
    return next((y for y in years if str(y.id) == str(wanted)), None) or next((y for y in years if y.is_current), None) or \
        (years[0] if years else None)


def _page_url(sy=None, section=None):
    query = {k: v for k, v in (('sy', sy.id if sy else ''), ('section', section or '')) if v}
    return reverse('registrars:school_forms') + (f'?{urlencode(query)}' if query else '')


def school_forms(request):
    school = _registrar_school(request)
    years = _school_years(school)
    sy = _chosen_year(request, school, years)
    if request.method == 'POST' and request.POST.get('action') == 'header':
        saved = school_header.save(school, {f: request.POST.get(f, '') for f in school_header.FIELDS}, request.user)
        messages.success(request, 'The form header is saved. Every school form now prints '
                                  f'{school_header.region_label(saved["region"]) or "no region"}, '
                                  f'{saved["division"] or "no division"} and {saved["district"] or "no district"}.')
        return redirect(_page_url(sy))
    if sy is None:
        return render(request, 'registrars/school_forms/index.html', {'school': school, 'no_year': True})

    sections = list(Section.objects.filter(school=school, school_year=sy).select_related('grade_level', 'strand', 'adviser')
                    .order_by('grade_level__grade_number', 'section_name'))
    jhs = [s for s in sections if not s.grade_level.is_senior_high]
    shs = [s for s in sections if s.grade_level.is_senior_high]
    info = FD.school_info(school, sy)
    periods = list(Quarter.objects.filter(school_year=sy))
    ids = list(Enrollment.objects.filter(section__in=sections, school_year=sy, status__in=FD.ACTIVE).values_list('id', flat=True))
    unvalidated = FD.unvalidated_count(ids, periods) if periods else 0
    sems = SF.semesters(sy)
    current_sem = SF.semester_of(sy)
    picked = request.GET.get('section', '')
    cards = []
    for code, title, about, scope, needs in CARDS:
        if scope == 'section12' and not any(s.grade_level.grade_number == 12 for s in shs):
            continue
        if scope == 'section_jhs' and not jhs:
            continue
        cards.append({'code': code, 'badge': 'Grades' if code == 'SUMMARY' else code, 'title': title, 'about': about,
                      'scope': scope, 'needs': needs})
    return render(request, 'registrars/school_forms/index.html', {
        'school': school, 'current_sy': sy, 'years': years, 'jhs': jhs, 'shs': shs, 'grade12': [s for s in shs if s.grade_level.grade_number == 12],
        'months': FD.months_of(sy), 'month': FD.default_month(sy), 'semesters': sems,
        'semester': current_sem.semester_number if current_sem else 1, 'cards': cards, 'picked': picked,
        'info': info, 'header': school_header.get(school), 'region_label': info['region_label'],
        'unvalidated': unvalidated, 'has_jhs': bool(jhs), 'has_shs': bool(shs),
        'level': 'shs' if (picked and any(str(s.id) == picked for s in shs)) or not jhs else 'jhs',
    })


def school_form_download(request):
    school = _registrar_school(request)
    years = _school_years(school)
    sy = _chosen_year(request, school, years)
    code = request.GET.get('code', '')
    section_id = request.GET.get('section', '')
    back = _page_url(sy, section_id)
    if sy is None:
        messages.error(request, 'There is no school year yet.')
        return redirect(back)
    section = None
    if section_id:
        section = Section.objects.filter(id=section_id if section_id.isdigit() else 0, school=school, school_year=sy).select_related(
            'grade_level', 'strand', 'strand__track', 'adviser', 'school').first()
        if section is None:
            messages.error(request, 'That section is not in this school year.')
            return redirect(back)
    month = SF.month_param(request.GET.get('month'))
    semester = SF.semester_param(sy, request.GET.get('semester'))
    senior = request.GET.get('level') == 'shs'
    try:
        content, name = SF.build(code, school=school, sy=sy, section=section, month=month, semester=semester, senior=senior)
    except SF.FormUnavailable as exc:
        messages.error(request, str(exc))
        return redirect(back)
    _log(request, code, name)
    response = HttpResponse(content, content_type=XLSX)
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    return response


def _log(request, code, name):
    try:
        from audit.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user, user_name=request.user.get_full_name() or request.user.username, user_role='registrar',
            action_type='EXPORT_DATA', resource_type='SchoolForm', resource_id=code,
            details_json={'description': f'Downloaded {name}'},
            ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'), user_agent=request.META.get('HTTP_USER_AGENT', '')[:255],
        )
    except Exception:
        pass
