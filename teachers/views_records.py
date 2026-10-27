"""Teacher: class records, grade uploads (preview, then confirm), submission and the notification bell."""
import csv
import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from academics.models import Quarter, SchoolYear
from communication.models import Notification
from communication.notify import notify, school_registrars
from core import grading_policy as policy
from core import periods as P
from core.caching import bump_data_version
from grades import ecr
from scheduling.models import ClassAssignment

from . import records as R

NOTE_ICONS = {'GRADE_VALIDATED': 'fi-rr-badge-check', 'GRADE_RETURNED': 'fi-rr-undo', 'GRADE_DEADLINE_REMINDER': 'fi-rr-alarm-clock'}


def _teacher(request):
    profile = getattr(request.user, 'profile', None)
    return profile if profile and profile.role == 'teacher' and profile.school_id else None


def teacher_context(request):
    profile = _teacher(request)
    school = profile.school
    policy.activate(school)          # the school's DepEd order names the levels on every teacher page
    sy = SchoolYear.objects.filter(school=school, is_current=True).first()
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number')) if sy else []
    current = P.current(periods)
    assignments = list(ClassAssignment.objects.filter(teacher=request.user, school_year=sy, is_active=True)
                       .select_related('section', 'section__grade_level', 'subject', 'subject__subject_family', 'semester', 'school_year')
                       .order_by('section__grade_level__sort_order', 'section__section_name', 'subject__subject_code')) if sy else []
    return school, sy, periods, current, assignments


def _denied(request):
    messages.error(request, 'Access denied. Teachers only.')
    return redirect('signin')


# ---------------------------------------------------------------------------------------------
# class records
# ---------------------------------------------------------------------------------------------

@login_required
def class_records(request):
    if not _teacher(request):
        return _denied(request)
    school, sy, periods, current, assignments = teacher_context(request)
    rows = R.overview(assignments, periods, current)
    notes = {}
    if current:
        from grades.models import GradeComponent
        for section_id, subject_id, note in GradeComponent.objects.filter(
                quarter=current, validation_status='Returned', enrollment__section_id__in=[a.section_id for a in assignments]
        ).exclude(validation_notes='').values_list('enrollment__section_id', 'subject_id', 'validation_notes'):
            notes.setdefault((section_id, subject_id), note)
    classes = []
    for row in rows:
        a = row['assignment']
        own, learners = R.learners_table(a, periods)
        cur = row['current'] or {}
        label, tone, hint = R.STATE_INFO[row['state']]
        classes.append({
            'id': a.id, 'grade': a.section.grade_level.grade_name, 'grade_order': a.section.grade_level.sort_order,
            'section': a.section.section_name, 'subject': a.subject.subject_name, 'code': a.subject.subject_code,
            'advisory': a.is_advisory, 'learners': row['learners'], 'state': row['state'], 'state_label': label, 'tone': tone,
            'hint': hint, 'note': notes.get((a.section_id, a.subject_id), ''),
            'graded': cur.get('graded', 0), 'missing': max(0, row['learners'] - cur.get('graded', 0)),
            'percent': cur.get('percent', 0), 'average': cur.get('average'), 'below': cur.get('below', 0),
            'cells': [{'label': c['label'], 'name': P.name(c['period']), 'graded': c['graded'], 'total': c['total'],
                       'percent': c['percent'], 'average': c['average'], 'state': c['state'], 'current': c['is_current']}
                      for c in row['cells']],
            'periods': [p.quarter_label for p in own],
            'rows': learners,
            'upload_url': f'{reverse("teachers:upload_class_record")}?class={a.id}' + (f'&period={current.id}' if current else ''),
            'submit_url': reverse('teachers:submit_class', args=[a.id, current.id]) if current else '',
            'ecr_url': reverse('teachers:class_ecr', args=[a.id]) + (f'?period={current.id}' if current else ''),
            'csv_url': reverse('teachers:class_csv', args=[a.id]) + (f'?period={current.id}' if current else ''),
            'mapeh_url': reverse('teachers:class_mapeh_final', args=[a.id]) if R.is_mapeh(a) else '',
        })
    counts = {}
    for c in classes:
        counts[c['state']] = counts.get(c['state'], 0) + 1
    graded = sum(c['graded'] for c in classes)
    learners = sum(c['learners'] for c in classes)
    days_left, overdue = P.deadline_info(current) if current else (None, False)
    return render(request, 'teachers/class_records/list.html', {
        'school': school, 'sy': sy, 'periods': periods, 'current': current, 'current_name': P.name(current),
        'period_word': P.word(school, periods), 'period_word_plural': P.word(school, periods, plural=True),
        'classes': classes, 'counts': counts, 'graded': graded, 'learners': learners,
        'to_grade': learners - graded, 'ready': counts.get('ready', 0), 'returned': counts.get('returned', 0),
        'days_left': days_left, 'overdue': overdue,
        'deadline': current.grade_encoding_deadline if current else None,
        'chip_grade': counts.get('not_started', 0) + counts.get('encoding', 0),
        'chip_done': counts.get('submitted', 0) + counts.get('validated', 0) + counts.get('locked', 0),
        'classes_json': [{k: c[k] for k in ('id', 'grade', 'section', 'subject', 'periods', 'rows')} for c in classes],
        'advisory': _advisory(request, sy),
    })


def _advisory(request, sy):
    """The section the teacher advises this year, with the school forms an adviser prepares."""
    if sy is None:
        return []
    from academics.models import Section
    from documentation import form_data as FD
    out = []
    for section in Section.objects.filter(school_year=sy, adviser=request.user, is_active=True).select_related('grade_level'):
        senior = section.grade_level.is_senior_high
        forms = [('SF1', 'School Register'), ('SF2', 'Daily Attendance'), ('SF3', 'Books Issued and Returned'),
                 ('SF5', 'End of Semester Status (SF5A)' if senior else 'Report on Promotion')]
        if not senior:
            forms.append(('SUMMARY', 'Summary of Final Grades'))
        out.append({'section': section, 'senior': senior, 'forms': forms, 'months': FD.months_of(sy), 'month': FD.default_month(sy),
                    'url': reverse('teachers:advisory_form', args=[section.id])})
    return out


# ---------------------------------------------------------------------------------------------
# uploads
# ---------------------------------------------------------------------------------------------

def _class_choices(assignments, periods, current):
    out = []
    for a in assignments:
        own = P.for_class(a, periods)
        out.append({'id': a.id, 'label': f'{a.section.grade_level.grade_name} {a.section.section_name} · {a.subject.subject_name}',
                    'mapeh': R.is_mapeh(a), 'periods': [{'id': p.id, 'name': P.name(p), 'locked': p.is_grades_locked,
                                                         'current': current is not None and p.id == current.id} for p in own]})
    return out


@login_required
def upload(request):
    if not _teacher(request):
        return _denied(request)
    school, sy, periods, current, assignments = teacher_context(request)
    if not sy:
        messages.error(request, 'There is no active school year yet.')
        return redirect('teachers:class_record_list')
    choices = _class_choices(assignments, periods, current)
    chosen_class = request.POST.get('class') or request.GET.get('class') or ''
    chosen_period = request.POST.get('period') or request.GET.get('period') or (str(current.id) if current else '')
    if request.method == 'POST':
        assignment = next((a for a in assignments if str(a.id) == chosen_class), None)
        period = next((p for p in periods if str(p.id) == chosen_period), None)
        uploaded = request.FILES.get('file')
        error = None
        if not assignment:
            error = 'Choose one of your classes.'
        elif not period or period not in P.for_class(assignment, periods):
            error = f'Choose the {P.word(school, periods).lower()} these grades are for.'
        elif not uploaded:
            error = 'Choose the file to upload.'
        if not error:
            try:
                result = R.analyse_upload(uploaded, assignment, period, school)
            except ecr.EcrError as exc:
                error = str(exc)
        if error:
            return render(request, 'teachers/class_records/upload.html', {
                'choices': choices, 'chosen_class': chosen_class, 'chosen_period': chosen_period, 'error': error,
                'period_word': P.word(school, periods), 'sy': sy})
        token = R.remember(request.user, {'assignment': assignment.id, 'period': period.id, 'file': uploaded.name, 'result': result})
        return redirect(f'{reverse("teachers:upload_review")}?token={token}')
    return render(request, 'teachers/class_records/upload.html', {
        'choices': choices, 'chosen_class': chosen_class, 'chosen_period': chosen_period,
        'period_word': P.word(school, periods), 'sy': sy})


def _review_context(request, stash, token, problems=None):
    assignment = get_object_or_404(ClassAssignment.objects.select_related('section', 'section__grade_level', 'subject'),
                                   id=stash['assignment'], teacher=request.user)
    period = get_object_or_404(Quarter, id=stash['period'], school_year=assignment.school_year)
    result = stash['result']
    rows = result['rows']
    errors = [t for level, t in result['checks'] if level == 'error']
    warns = [t for level, t in result['checks'] if level == 'warn']
    groups = {'ready': [], 'settle': [], 'skipped': [], 'empty': []}
    for r in rows:
        r['grade_text'] = '' if r['quarterly'] is None else str(r['quarterly'])
        r['initial_text'] = '' if r['initial'] is None else f'{r["initial"]:.2f}'
        r['parts_text'] = [{'name': p['component'].title(), 'grade': p['result']['quarterly']}
                           for p in r.get('parts', []) if p and p.get('result') and len(r.get('parts', [])) > 1]
        r['components'] = []
        if len(r.get('parts', [])) == 1 and r['parts'][0]:
            res = r['parts'][0]['result']
            r['components'] = [('WW', res['ww']['ps']), ('PT', res['pt']['ps']), ('QA', res['qa']['ps'])]
        if r['quarterly'] is None and not r['errors']:
            groups['empty'].append(r)
        elif r['errors'] or r.get('frozen'):
            groups['skipped'].append(r)
        elif r['status'] == 'matched':
            groups['ready'].append(r)
        else:
            groups['settle'].append(r)
    acknowledge = bool(warns) or any(r['warnings'] for r in rows if r['quarterly'] is not None)
    resubmit = any(r.get('current_status') == 'Submitted' for r in groups['ready'] + groups['settle'])
    return {
        'assignment': assignment, 'period': period, 'period_name': P.name(period), 'token': token, 'file': stash['file'],
        'result': result, 'errors': errors, 'warns': warns, 'groups': groups, 'acknowledge': acknowledge,
        'resubmit': resubmit, 'problems': problems or [], 'roster': result['roster'],
        'roster_json': json.dumps(result['roster']),
        'other_periods': [f'{P.word(assignment.section.school, [period])} {n}' for n in result.get('other_periods', [])],
        'importable': len(groups['ready']) + len(groups['settle']),
    }


@login_required
def upload_review(request):
    if not _teacher(request):
        return _denied(request)
    token = request.GET.get('token') or request.POST.get('token')
    stash = R.recall(request.user, token)
    if not stash:
        messages.error(request, 'That upload has expired. Upload the file again.')
        return redirect('teachers:upload_class_record')
    if request.method == 'POST':
        ctx = _review_context(request, stash, token)
        if ctx['errors']:
            messages.error(request, 'This file cannot be imported. See the problems listed.')
            return redirect(f'{reverse("teachers:upload_review")}?token={token}')
        if ctx['acknowledge'] and request.POST.get('acknowledge') != 'yes':
            return render(request, 'teachers/class_records/review.html',
                          _review_context(request, stash, token, ['Confirm that you checked the notes above before importing.']))
        choices = {k[4:]: v for k, v in request.POST.items() if k.startswith('row-')}
        plan, problems = R.decide(stash['result'], choices)
        if problems:
            return render(request, 'teachers/class_records/review.html', _review_context(request, stash, token, problems))
        if not plan:
            messages.info(request, 'Nothing was imported: no row had a grade to save.')
            return redirect('teachers:class_record_list')
        assignment, period = ctx['assignment'], ctx['period']
        source = f'{"e-class record" if stash["result"]["source"] == "ecr" else "CSV"} "{stash["file"]}"'
        counts = R.save(assignment, period, plan, request.user, source, request.META.get('REMOTE_ADDR'))
        R.forget(request.user, token)
        bump_data_version()
        _log(request, 'UPLOAD_GRADES', assignment.id,
             f'Uploaded {P.name(period)} grades for {assignment.subject.subject_code} {assignment.section.section_name}: '
             f'{counts["created"]} new, {counts["updated"]} changed, {counts["unchanged"]} unchanged from {source}')
        parts = [f'{counts["created"]} new', f'{counts["updated"]} changed']
        if counts['unchanged']:
            parts.append(f'{counts["unchanged"]} unchanged')
        if counts['kept']:
            parts.append(f'{counts["kept"]} already validated (not changed)')
        messages.success(request, f'{P.name(period)} grades saved for {assignment.section.section_name} '
                                  f'({assignment.subject.subject_code}): {", ".join(parts)}. They are drafts until you submit them.')
        return redirect(f'{reverse("teachers:class_record_list")}#class-{assignment.id}')
    return render(request, 'teachers/class_records/review.html', _review_context(request, stash, token))


@login_required
@require_POST
def submit_class(request, assignment_id, period_id):
    if not _teacher(request):
        return _denied(request)
    assignment = get_object_or_404(ClassAssignment.objects.select_related('section', 'section__school', 'section__grade_level', 'subject'),
                                   id=assignment_id, teacher=request.user)
    period = get_object_or_404(Quarter, id=period_id, school_year=assignment.school_year)
    ok, message = R.submit(assignment, period, request.user)
    if ok:
        bump_data_version()
        _log(request, 'SUBMIT_GRADES', assignment.id,
             f'Submitted {P.name(period)} grades of {assignment.subject.subject_code} {assignment.section.section_name} for validation')
        _notify_registrars(assignment, period, request.user)
        messages.success(request, f'{assignment.section.section_name} ({assignment.subject.subject_code}): {message}')
    else:
        messages.error(request, f'{assignment.section.section_name} ({assignment.subject.subject_code}): {message}')
    return redirect(f'{reverse("teachers:class_record_list")}#class-{assignment.id}')


def _notify_registrars(assignment, period, teacher):
    where = f'{assignment.section.grade_level.grade_name} {assignment.section.section_name} · {assignment.subject.subject_code}'
    notify(school_registrars(assignment.section.school), 'GRADE_SUBMITTED', f'Submitted: {where}',
           f'{teacher.get_full_name() or teacher.username} submitted the {P.name(period)} grades for validation.',
           reverse('registrars:grade_class_detail', args=[assignment.id, period.id]), assignment_id=assignment.id)


def _log(request, action, resource_id, description):
    try:
        from audit.models import ActivityLog
        ActivityLog.objects.create(
            user=request.user, user_name=request.user.get_full_name() or request.user.username, user_role='teacher',
            action_type=action, resource_type='ClassAssignment', resource_id=str(resource_id),
            details_json={'description': description}, ip_address=request.META.get('REMOTE_ADDR', '127.0.0.1'),
            user_agent=request.META.get('HTTP_USER_AGENT', '')[:255])
    except Exception:
        pass


# ---------------------------------------------------------------------------------------------
# ready-made files for one class
# ---------------------------------------------------------------------------------------------

@login_required
def class_csv(request, assignment_id):
    """The class list as a CSV to fill in: LRN, learner, sex, quarterly grade."""
    if not _teacher(request):
        return _denied(request)
    assignment = get_object_or_404(ClassAssignment.objects.select_related('section', 'subject'), id=assignment_id, teacher=request.user)
    period = Quarter.objects.filter(id=request.GET.get('period'), school_year=assignment.school_year).first()
    response = HttpResponse(content_type='text/csv; charset=utf-8')
    name = f'{assignment.subject.subject_code}_{assignment.section.section_name}_{period.quarter_label if period else "grades"}'
    response['Content-Disposition'] = f'attachment; filename="{ecr._clean(name).replace(" ", "-")}.csv"'
    response.write('﻿')
    writer = csv.writer(response)
    writer.writerow(['LRN', 'Learner', 'Sex', 'Quarterly grade'])
    for p in R.roster(assignment, include_inactive=False):
        writer.writerow([p['lrn'], R.display_name(p), p['sex'], ''])
    return response


@login_required
def class_ecr(request, assignment_id):
    """The official e-class record for this class, with its learners (and their LRNs) filled in."""
    if not _teacher(request):
        return _denied(request)
    assignment = get_object_or_404(ClassAssignment.objects.select_related('section', 'section__grade_level', 'section__school', 'subject',
                                                                          'subject__subject_family', 'school_year'),
                                   id=assignment_id, teacher=request.user)
    from grades import ecr_template
    period = Quarter.objects.filter(id=request.GET.get('period'), school_year=assignment.school_year).first()
    try:
        content, filename = ecr_template.build(assignment, R.roster(assignment, include_inactive=False), request.user, period)
    except ecr_template.TemplateUnavailable as exc:
        messages.error(request, str(exc))
        return redirect('teachers:class_record_list')
    response = HttpResponse(content, content_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet')
    response['Content-Disposition'] = f'attachment; filename="{filename}"'
    return response


XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'


def _xlsx(content, name):
    response = HttpResponse(content, content_type=XLSX)
    response['Content-Disposition'] = f'attachment; filename="{name}"'
    return response


@login_required
def class_mapeh_final(request, assignment_id):
    """The MAPEH final grades sheet of one MAPEH class: its quarterly MAPEH grades; the sheet averages them."""
    if not _teacher(request):
        return _denied(request)
    assignment = get_object_or_404(ClassAssignment.objects.select_related('section', 'section__grade_level', 'section__school',
                                                                          'subject', 'subject__subject_family', 'school_year', 'teacher'),
                                   id=assignment_id, teacher=request.user)
    from documentation import school_forms as SF
    if not R.is_mapeh(assignment):
        messages.error(request, 'The MAPEH final grades sheet is for MAPEH classes.')
        return redirect('teachers:class_record_list')
    try:
        content, name = SF.mapeh_final_grades(assignment)
    except SF.FormUnavailable as exc:
        messages.error(request, str(exc))
        return redirect('teachers:class_record_list')
    return _xlsx(content, name)


ADVISER_FORMS = ('SF1', 'SF2', 'SF3', 'SF5', 'SUMMARY')


@login_required
def advisory_form(request, section_id):
    """A school form of the teacher's advisory class (SF1, SF2, SF3, SF5 or the summary of final grades)."""
    profile = _teacher(request)
    if not profile:
        return _denied(request)
    from academics.models import Section
    from documentation import school_forms as SF
    section = get_object_or_404(Section.objects.select_related('grade_level', 'strand', 'strand__track', 'adviser', 'school', 'school_year'),
                                id=section_id, adviser=request.user, school=profile.school)
    code = request.GET.get('code', '')
    if code not in ADVISER_FORMS:
        messages.error(request, 'Choose one of the forms of your advisory class.')
        return redirect('teachers:class_record_list')
    sy = section.school_year
    try:
        content, name = SF.build(code, school=section.school, sy=sy, section=section, month=SF.month_param(request.GET.get('month')),
                                 semester=SF.semester_param(sy, request.GET.get('semester')))
    except SF.FormUnavailable as exc:
        messages.error(request, str(exc))
        return redirect('teachers:class_record_list')
    return _xlsx(content, name)


# ---------------------------------------------------------------------------------------------
# notification bell
# ---------------------------------------------------------------------------------------------

@login_required
def updates(request):
    """What still needs the teacher this period, plus their notifications."""
    if not _teacher(request):
        return JsonResponse({'error': 'Teachers only.'}, status=403)
    school, sy, periods, current, assignments = teacher_context(request)
    reminders = []
    if current:
        rows = R.overview(assignments, periods, current)
        days_left, overdue = P.deadline_info(current)
        due = P.due_text(current)
        for row in rows:
            a, cur = row['assignment'], row['current']
            if not cur:
                continue
            where = f'{a.section.grade_level.grade_name} {a.section.section_name} · {a.subject.subject_code}'
            url = f'{reverse("teachers:class_record_list")}#class-{a.id}'
            missing = cur['total'] - cur['graded']
            if row['state'] == 'returned':
                reminders.append({'kind': 'returned', 'icon': 'fi-rr-undo', 'title': f'Returned: {where}',
                                  'message': 'The registrar returned these grades for correction.', 'url': url, 'urgent': True})
            elif row['state'] in ('not_started', 'encoding') and missing > 0:
                reminders.append({'kind': 'missing', 'icon': 'fi-rr-time-quarter-past', 'title': f'{missing} without a grade: {where}',
                                  'message': f'{missing} of {cur["total"]} learners have no {P.name(current)} grade yet.{due}',
                                  'url': url, 'urgent': overdue or (days_left is not None and days_left <= 3)})
            elif row['state'] == 'ready':
                reminders.append({'kind': 'ready', 'icon': 'fi-rr-paper-plane', 'title': f'Ready to submit: {where}',
                                  'message': f'Every learner has a {P.name(current)} grade. Submit them to the registrar.{due}',
                                  'url': url, 'urgent': overdue})
    notes = []
    for n in Notification.objects.filter(recipient=request.user, is_dismissed=False).order_by('-created_at')[:8]:
        notes.append({'id': n.id, 'title': n.title, 'message': n.message, 'unread': not n.is_read,
                      'url': reverse('teachers:open_notification', args=[n.id]) if n.action_url else '',
                      'when': timezone.localtime(n.created_at).strftime('%b %d, %I:%M %p'),
                      'icon': NOTE_ICONS.get(n.notification_type, 'fi-rr-bell')})
    unread = Notification.objects.filter(recipient=request.user, is_read=False, is_dismissed=False).count()
    return JsonResponse({'period': P.name(current), 'reminders': reminders, 'notifications': notes,
                         'count': len(reminders) + unread})


@login_required
def open_notification(request, notification_id):
    n = get_object_or_404(Notification, id=notification_id, recipient=request.user)
    if not n.is_read:
        n.is_read, n.read_at = True, timezone.now()
        n.save(update_fields=['is_read', 'read_at'])
    target = n.action_url if n.action_url and url_has_allowed_host_and_scheme(n.action_url, {request.get_host()}) else reverse('teachers:class_record_list')
    return redirect(target)


@login_required
@require_POST
def read_all(request):
    Notification.objects.filter(recipient=request.user, is_read=False).update(is_read=True, read_at=timezone.now())
    return JsonResponse({'ok': True})
