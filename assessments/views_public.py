"""Learners: answer an assessment through its link, signing in with their LRN from the section's class list.

Each learner answers once. The answer key never reaches the browser, answers are graded on the server, and
after submitting a learner sees at most their score (when the teacher allows it), never the answers.
"""
from django.contrib import messages
from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from academics.models import Assessment, AssessmentResponse
from enrollment.models import Enrollment

from . import quizzes as Q

MAX_TRIES = 8              # wrong LRNs allowed from one browser before a 15-minute pause
TRY_WINDOW = 15 * 60


def _assessment(code):
    return get_object_or_404(Assessment.objects.select_related('subject', 'section', 'section__grade_level', 'teacher'),
                             access_code=str(code).upper(), status__in=('published', 'closed'))


def _key(assessment):
    return f'quiz:{assessment.id}'


def _enrollment(request, assessment):
    enrollment_id = request.session.get(_key(assessment))
    if not enrollment_id:
        return None
    return Enrollment.objects.filter(id=enrollment_id, section_id=assessment.section_id, school_year_id=assessment.school_year_id,
                                     status__in=Q.ACTIVE).select_related('student').first()


def _response(assessment, enrollment):
    """The learner's response; answers saved before LRN sign-in are tied to the learner, not the enrollment."""
    if enrollment is None:
        return None
    return (AssessmentResponse.objects.filter(assessment=assessment, enrollment=enrollment).first()
            or AssessmentResponse.objects.filter(assessment=assessment, enrollment__isnull=True, student_id=enrollment.student_id).first())


def quiz_login(request, access_code):
    """The assessment's page: what it is, sign in with the LRN, start, continue, or see that it was submitted."""
    a = _assessment(access_code)
    error = ''
    if request.method == 'POST':
        if request.POST.get('action') == 'switch':
            request.session.pop(_key(a), None)
            return redirect('quiz_login', access_code=a.access_code)
        now = timezone.now().timestamp()
        tries = [t for t in request.session.get('quiz_tries', []) if now - t < TRY_WINDOW]
        lrn = ''.join(ch for ch in request.POST.get('lrn', '') if ch.isdigit())
        if len(tries) >= MAX_TRIES:
            error = 'Too many tries. Wait 15 minutes, or ask your teacher for help.'
        elif len(lrn) != 12:
            error = 'Type your 12-digit LRN (Learner Reference Number).'
        else:
            enrollment = Enrollment.objects.filter(section_id=a.section_id, school_year_id=a.school_year_id, status__in=Q.ACTIVE,
                                                   student__lrn=lrn).first()
            if enrollment:
                request.session[_key(a)] = enrollment.id
                request.session.pop('quiz_tries', None)
                return redirect('quiz_login', access_code=a.access_code)
            tries.append(now)
            request.session['quiz_tries'] = tries
            error = f'That LRN is not on the class list of {Q.section_label(a.section)}. Check the number, or ask your teacher.'

    enrollment = _enrollment(request, a)
    response = _response(a, enrollment)
    questions = list(a.questions.all())
    ends = Q.deadline_for(a, response) if response and not response.submitted_at else None
    out_of_time = bool(ends and timezone.now() > ends + Q.GRACE)
    return render(request, 'assessments/quiz_login.html', {
        'a': a, 'state': a.state(), 'type': Q.TYPES.get(a.assessment_type, 'Quiz'), 'section': Q.section_label(a.section),
        'teacher': a.teacher.get_full_name() or a.teacher.username, 'questions': len(questions), 'points': Q.total_points(questions),
        'enrollment': enrollment, 'learner': Q.learner_name(enrollment.student) if enrollment else '',
        'response': response, 'out_of_time': out_of_time, 'error': error,
        'percent': Q.percent(response.score, response.total_points) if response and response.submitted_at else None,
        'storage_key': f'arms-quiz-{a.access_code}-{enrollment.id}' if enrollment else '',
    })


def take_quiz(request, access_code):
    """The learner's paper. The teacher who owns it can preview it with ?preview=1 (nothing is saved)."""
    a = _assessment(access_code) if request.GET.get('preview') != '1' else get_object_or_404(
        Assessment.objects.select_related('subject', 'section', 'section__grade_level', 'teacher'), access_code=str(access_code).upper())
    questions = list(a.questions.all())
    if request.GET.get('preview') == '1':
        if not (request.user.is_authenticated and request.user.id == a.teacher_id):
            return redirect('quiz_login', access_code=a.access_code)
        sample = AssessmentResponse(item_order=Q.learner_order(questions, a.shuffle, None))
        return render(request, 'assessments/take_quiz.html', {
            'a': a, 'paper': Q.paper(a, sample), 'preview': True, 'type': Q.TYPES.get(a.assessment_type, 'Quiz'),
            'section': Q.section_label(a.section), 'learner': 'Preview', 'ends': None, 'points': Q.total_points(questions)})

    enrollment = _enrollment(request, a)
    if enrollment is None or a.state() != 'open':
        return redirect('quiz_login', access_code=a.access_code)
    response = _response(a, enrollment)
    if response and response.submitted_at:
        return redirect('quiz_login', access_code=a.access_code)
    if response is None:
        try:
            with transaction.atomic():
                response = AssessmentResponse.objects.create(
                    assessment=a, enrollment=enrollment, student=enrollment.student,
                    student_name=Q.learner_name(enrollment.student), total_points=Q.total_points(questions),
                    item_order=Q.learner_order(questions, a.shuffle, f'{a.id}:{enrollment.id}'))
        except IntegrityError:                      # opened twice at the same moment
            response = _response(a, enrollment)
    ends = Q.deadline_for(a, response)
    if ends and timezone.now() > ends + Q.GRACE:
        return redirect('quiz_login', access_code=a.access_code)
    return render(request, 'assessments/take_quiz.html', {
        'a': a, 'paper': Q.paper(a, response), 'preview': False, 'type': Q.TYPES.get(a.assessment_type, 'Quiz'),
        'section': Q.section_label(a.section), 'learner': Q.learner_name(enrollment.student),
        'ends': ends.isoformat() if ends else None, 'points': Q.total_points(questions),
        'storage_key': f'arms-quiz-{a.access_code}-{enrollment.id}',
    })


@require_POST
def submit_quiz(request, access_code):
    """The learner's answers, posted by the paper's form (q-<question id> = chosen choice or typed answer)."""
    a = _assessment(access_code)
    back = redirect('quiz_login', access_code=a.access_code)
    enrollment = _enrollment(request, a)
    if enrollment is None:
        messages.error(request, 'Sign in with your LRN again, then answer.')
        return back
    response = _response(a, enrollment)
    if response is None or response.submitted_at:
        return back
    ends = Q.deadline_for(a, response)
    if a.status != 'published' or (ends and timezone.now() > ends + Q.GRACE):
        messages.error(request, 'The time for this assessment is over, so these answers could not be accepted.')
        return back
    answers = {}
    for q in a.questions.all():
        value = request.POST.get(f'q-{q.id}', '')
        answers[str(q.id)] = {'text': value} if q.question_type == 'identification' else {'choice': value}
    with transaction.atomic():
        response = AssessmentResponse.objects.select_for_update().get(id=response.id)
        if not response.submitted_at:
            Q.grade(response, answers)
    return back
