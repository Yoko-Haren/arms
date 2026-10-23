"""Teacher: assessments (quizzes, tests, assignments) answered online by a section, and their results."""
import json
from datetime import datetime, timedelta

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.views.decorators.http import require_POST

from academics.models import Assessment, AssessmentResponse
from core.xlsx import Report, safe_filename

from . import quizzes as Q


def _teacher(request):
    profile = getattr(request.user, 'profile', None)
    return profile if profile and profile.role == 'teacher' and profile.school_id else None


def _denied(request):
    messages.error(request, 'Access denied. Teachers only.')
    return redirect('signin')


def _local_input(dt):
    """A datetime as the value of an <input type="datetime-local"> (school time zone)."""
    return timezone.localtime(dt).strftime('%Y-%m-%dT%H:%M') if dt else ''


def _parse_local(value, label):
    if not value:
        return None
    try:
        return timezone.make_aware(datetime.strptime(str(value)[:16], '%Y-%m-%dT%H:%M'))
    except ValueError:
        raise Q.Invalid(f'The {label} could not be read. Pick the date and time again.')


def _default_deadline():
    """Tomorrow at 5:00 PM, school time."""
    return (timezone.localtime() + timedelta(days=1)).replace(hour=17, minute=0, second=0, microsecond=0)


# ---------------------------------------------------------------------------------------------
# list
# ---------------------------------------------------------------------------------------------

@login_required
def assessment_list(request):
    if not _teacher(request):
        return _denied(request)
    rows = Q.list_rows(request.user)
    sy, classes = Q.teacher_classes(request.user)
    counts = {key: sum(1 for r in rows if r['state'] == key) for key in Q.STATES}
    week = AssessmentResponse.objects.filter(assessment__teacher=request.user, submitted_at__isnull=False,
                                             submitted_at__gte=timezone.now() - timedelta(days=7)).count()
    return render(request, 'teachers/assessments/list.html', {
        'rows': rows, 'counts': counts, 'week': week,
        'closing_soon': sum(1 for r in rows if r['closing_soon']),
        'subjects': sorted({r['assessment'].subject.subject_code for r in rows}),
        'sections': sorted({r['section'] for r in rows}),
        'can_create': bool(classes),
    })


# ---------------------------------------------------------------------------------------------
# create, edit, copy
# ---------------------------------------------------------------------------------------------

def _builder(classes, editing=None, copy=None):
    source = editing or copy
    subjects = Q.subject_choices(classes)
    subject = source.subject_id if source and any(s['id'] == source.subject_id for s in subjects) else None
    initial = {
        'id': editing.id if editing else None,
        'title': (f'{source.title} (copy)' if copy else source.title) if source else '',
        'type': source.assessment_type if source else 'quiz',
        'subject': subject or (subjects[0]['id'] if len(subjects) == 1 else None),
        'sections': [editing.section_id] if editing else [],
        'description': source.description if source else '',
        'opens_at': _local_input(editing.opens_at) if editing else '',
        'closes_at': _local_input(editing.closes_at) if editing and editing.closes_at else _local_input(_default_deadline()),
        'time_limit': source.time_limit_minutes if source else None,
        'shuffle': source.shuffle if source else True,
        'show_score': source.show_score if source else True,
        'questions': Q.builder_rows(source) if source else [],
    }
    return {'subjects': subjects, 'types': Assessment.TYPE_CHOICES, 'components': Q.COMPONENT, 'initial': initial,
            'editing': editing, 'copy': copy, 'editing_section': Q.section_label(editing.section) if editing else ''}


@login_required
def assessment_create_page(request):
    if not _teacher(request):
        return _denied(request)
    sy, classes = Q.teacher_classes(request.user)
    if not classes:
        messages.error(request, 'You have no classes this school year yet, so there is nobody to give an assessment to.')
        return redirect('assessments:list')
    copy = Assessment.objects.filter(id=request.GET.get('copy'), teacher=request.user).first() if request.GET.get('copy') else None
    return render(request, 'teachers/assessments/create.html', _builder(classes, copy=copy))


@login_required
def assessment_edit(request, assessment_id):
    if not _teacher(request):
        return _denied(request)
    assessment = get_object_or_404(Assessment.objects.select_related('section', 'section__grade_level', 'subject'),
                                   id=assessment_id, teacher=request.user)
    if assessment.responses.exists():
        messages.info(request, 'Learners have already started this assessment, so its questions can no longer change. '
                               'You can still change its deadline here.')
        return redirect('assessments:detail', assessment_id=assessment.id)
    sy, classes = Q.teacher_classes(request.user)
    return render(request, 'teachers/assessments/create.html', _builder(classes, editing=assessment))


def _clean(data, classes, editing):
    title = str(data.get('title') or '').strip()
    if not title:
        raise Q.Invalid('Give the assessment a title.')
    if len(title) > 200:
        raise Q.Invalid('The title is too long (200 characters at most).')
    if editing:
        subject, sections = editing.subject_id, [editing.section_id]
    else:
        try:
            subject = int(data.get('subject'))
        except (TypeError, ValueError):
            raise Q.Invalid('Choose the subject.')
        allowed = {a.section_id for a in classes if a.subject_id == subject}
        if not allowed:
            raise Q.Invalid('Choose one of the subjects you teach.')
        try:
            sections = sorted({int(s) for s in data.get('sections') or []})
        except (TypeError, ValueError):
            raise Q.Invalid('Choose the sections.')
        if not sections:
            raise Q.Invalid('Choose at least one section.')
        if not set(sections) <= allowed:
            raise Q.Invalid('You can only give an assessment to the sections you teach this subject in.')
    publish = bool(data.get('publish'))
    opens_at = _parse_local(data.get('opens_at'), 'opening time')
    closes_at = _parse_local(data.get('closes_at'), 'deadline')
    if publish and not closes_at:
        raise Q.Invalid('Set the deadline: the date and time the assessment closes.')
    if publish and closes_at <= timezone.now():
        raise Q.Invalid('That deadline has already passed. Pick a later date and time.')
    if opens_at and closes_at and opens_at >= closes_at:
        raise Q.Invalid('The assessment has to open before its deadline.')
    time_limit = data.get('time_limit')
    if time_limit in ('', None):
        time_limit = None
    else:
        try:
            time_limit = int(time_limit)
        except (TypeError, ValueError):
            raise Q.Invalid('The time limit must be a whole number of minutes.')
        if not 1 <= time_limit <= 600:
            raise Q.Invalid('The time limit must be from 1 to 600 minutes.')
    return {'title': title, 'type': data.get('type') if data.get('type') in Q.TYPES else 'quiz', 'subject': subject,
            'sections': sections, 'description': str(data.get('description') or '').strip()[:5000],
            'opens_at': opens_at, 'closes_at': closes_at, 'time_limit': time_limit,
            'shuffle': bool(data.get('shuffle')), 'show_score': bool(data.get('show_score')), 'publish': publish}


@login_required
@require_POST
def assessment_save(request):
    """Create (one per chosen section) or update an assessment from the builder. Answers JSON."""
    if not _teacher(request):
        return JsonResponse({'ok': False, 'error': 'Teachers only.'}, status=403)
    try:
        data = json.loads(request.body or b'{}')
    except ValueError:
        return JsonResponse({'ok': False, 'error': 'The form could not be read. Reload the page and try again.'}, status=400)
    sy, classes = Q.teacher_classes(request.user)
    if sy is None:
        return JsonResponse({'ok': False, 'error': 'There is no current school year yet.'}, status=400)
    editing = None
    if data.get('id'):
        editing = Assessment.objects.filter(id=data.get('id'), teacher=request.user).first()
        if editing is None:
            return JsonResponse({'ok': False, 'error': 'That assessment was not found.'}, status=404)
        if editing.responses.exists():
            return JsonResponse({'ok': False, 'error': 'Learners have already started this assessment, so its questions can no longer change.'}, status=409)
    try:
        d = _clean(data, classes, editing)
        rows = Q.clean_questions(data.get('questions'))
    except Q.Invalid as exc:
        return JsonResponse({'ok': False, 'error': str(exc)}, status=400)

    period = Q.current_period(sy)
    made = []
    with transaction.atomic():
        for section_id in d['sections']:
            a = editing or Assessment(teacher=request.user, school_year=sy, quarter=period)
            a.subject_id, a.section_id = d['subject'], section_id
            a.title, a.assessment_type, a.description = d['title'], d['type'], d['description']
            a.opens_at, a.closes_at, a.time_limit_minutes = d['opens_at'], d['closes_at'], d['time_limit']
            a.shuffle, a.show_score = d['shuffle'], d['show_score']
            a.status = 'published' if d['publish'] else 'draft'
            a.total_items = len(rows)
            a.save()
            Q.save_questions(a, rows)
            made.append(a)
    word = 'published' if d['publish'] else 'saved as a draft'
    if len(made) == 1:
        messages.success(request, f'"{made[0].title}" is {word}.' + (' Share its link with the class.' if d['publish'] else ''))
        target = reverse('assessments:detail', args=[made[0].id])
    else:
        messages.success(request, f'"{d["title"]}" is {word} for {len(made)} sections. Each section has its own link.')
        target = reverse('assessments:list')
    return JsonResponse({'ok': True, 'redirect': target})


# ---------------------------------------------------------------------------------------------
# results and actions
# ---------------------------------------------------------------------------------------------

@login_required
def assessment_detail(request, assessment_id):
    if not _teacher(request):
        return _denied(request)
    a = get_object_or_404(Assessment.objects.select_related('subject', 'section', 'section__grade_level', 'quarter'),
                          id=assessment_id, teacher=request.user)
    res = Q.results(a)
    state = a.state()
    label, tone = Q.STATES[state]
    items = res['items']['items']
    return render(request, 'teachers/assessments/detail.html', {
        'a': a, 'res': res, 'state': state, 'state_label': label, 'state_tone': tone,
        'type': Q.TYPES.get(a.assessment_type, 'Quiz'), 'component': Q.COMPONENT.get(a.assessment_type, ''),
        'section': Q.section_label(a.section), 'share_url': request.build_absolute_uri(a.get_share_url()),
        'editable': not a.responses.exists(),
        'deadline_input': _local_input(a.closes_at if a.closes_at and a.closes_at > timezone.now() else _default_deadline()),
        'now_input': _local_input(timezone.now()),
        'items': items,
        'hardest': sorted([i for i in items if i['percent'] is not None], key=lambda i: (i['percent'], i['number']))[:5],
        'question_types': sorted({i['type'] for i in items}),
    })


@login_required
@require_POST
def assessment_action(request, assessment_id):
    if not _teacher(request):
        return _denied(request)
    a = get_object_or_404(Assessment, id=assessment_id, teacher=request.user)
    action = request.POST.get('action')
    now = timezone.now()
    back = redirect('assessments:detail', assessment_id=a.id)
    try:
        if action in ('publish', 'deadline', 'reopen'):
            closes_at = _parse_local(request.POST.get('closes_at'), 'deadline') or a.closes_at
            if not closes_at or closes_at <= now:
                raise Q.Invalid('Pick a deadline that is still ahead.')
            if a.opens_at and a.opens_at >= closes_at:
                raise Q.Invalid('The deadline has to come after the opening time.')
            if action == 'publish' and not a.questions.exists():
                raise Q.Invalid('Add questions before publishing.')
            a.closes_at, a.status = closes_at, 'published'
            a.save(update_fields=['closes_at', 'status', 'updated_at'])
            when = timezone.localtime(closes_at).strftime('%b %d, %I:%M %p').replace(' 0', ' ')
            messages.success(request, {'publish': f'Published. It closes {when}.', 'deadline': f'The deadline is now {when}.',
                                       'reopen': f'Reopened until {when}.'}[action])
        elif action == 'close':
            a.status = 'closed'
            a.save(update_fields=['status', 'updated_at'])
            messages.success(request, 'Closed. Learners can no longer answer it.')
        elif action == 'delete':
            title = a.title
            a.delete()
            messages.success(request, f'"{title}" was deleted with its answers.')
            return redirect('assessments:list')
        else:
            messages.error(request, 'That action is not available.')
    except Q.Invalid as exc:
        messages.error(request, str(exc))
    return back


@login_required
def assessment_export(request, assessment_id):
    """The results as a designed Excel report: learners in class-list order, then the item analysis."""
    if not _teacher(request):
        return _denied(request)
    a = get_object_or_404(Assessment.objects.select_related('subject', 'section', 'section__grade_level'),
                          id=assessment_id, teacher=request.user)
    res = Q.results(a)
    school = request.user.profile.school
    teacher = request.user.get_full_name() or request.user.username
    report = Report(a.title, school.school_name if school else 'ARMS', prepared_by=teacher)
    when = timezone.localtime(a.closes_at).strftime('%B %d, %Y, %I:%M %p') if a.closes_at else 'No deadline'
    sheet = report.sheet('Results', [6, 36, 16, 9, 12, 12, 12, 22],
                         subtitle=f'{Q.TYPES.get(a.assessment_type, "Quiz")} · {a.subject.subject_name} · {Q.section_label(a.section)}',
                         meta=[('Teacher', teacher), ('Deadline', when), ('Questions', str(len(res['questions']))),
                               ('Total points', f'{res["points"]:g}')])
    sheet.figures([('Submitted', f'{res["submitted"]} of {res["enrolled"]}', None),
                   ('Average', f'{res["average"]}%' if res['average'] is not None else '—', None),
                   ('Highest', f'{res["highest"]}%' if res['highest'] is not None else '—', None),
                   ('Lowest', f'{res["lowest"]}%' if res['lowest'] is not None else '—', None)])
    sheet.heading('Learners (males, then females, by surname)')
    status = {'submitted': 'Submitted', 'started': 'Started, not submitted', 'not_started': 'Not yet answered'}
    rows = []
    for n, r in enumerate(res['rows'] + res['others'], start=1):
        rows.append([n, r['name'] + (' (left the class)' if r['left'] else ''), r['lrn'], r['sex'],
                     float(r['score']) if r['score'] is not None else None, float(r['total']) if r['total'] else None,
                     r['percent'], status[r['status']] + (f', {timezone.localtime(r["submitted_at"]):%b %d %I:%M %p}' if r['submitted_at'] else '')])
    sheet.table([{'title': '#', 'format': 'int'}, {'title': 'Learner'}, {'title': 'LRN'}, {'title': 'Sex'},
                 {'title': 'Score', 'format': 'grade'}, {'title': 'Out of', 'format': 'grade'}, {'title': 'Percent', 'format': 'percent'},
                 {'title': 'Status', 'wrap': True}], rows)
    items = report.sheet('Item analysis', [6, 52, 16, 22, 12, 28], subtitle=a.title,
                         meta=[('Answers analysed', str(res['items']['responses']))], title='Item analysis')
    items.table([{'title': 'No.', 'format': 'int'}, {'title': 'Question', 'wrap': True}, {'title': 'Type'},
                 {'title': 'Answer key', 'wrap': True}, {'title': 'Correct', 'format': 'percent'}, {'title': 'Most common wrong answer', 'wrap': True}],
                [[i['number'], i['text'], i['type'], i['answer'], i['percent'],
                  f'{i["common_wrong"]["text"]} ({i["common_wrong"]["count"]})' if i['common_wrong'] else ''] for i in res['items']['items']])
    return report.response(safe_filename(a.subject.subject_code, a.section.section_name, a.title) + '.xlsx')
