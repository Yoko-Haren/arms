"""Assessments a teacher gives online: what a teacher may create, how answers are graded, and the results.

A teacher gives an assessment to a section of a subject they teach this school year (their ClassAssignments).
A learner opens its link, signs in with their LRN from that section's class list and answers once. With
shuffling on, each learner gets the questions and the choices in their own order; the order is kept with
their response, so a reload shows the same paper. Answers are graded here against the answer key, which
never reaches the learner's browser, and learners never see the key after submitting.

Results follow the DepEd class list: males first, then females, each by surname.
"""
import random
import re
import unicodedata
from datetime import timedelta
from decimal import Decimal
from statistics import mean

from django.db.models import Count, Q
from django.utils import timezone

from academics.models import Assessment, AssessmentAnswer, AssessmentQuestion, AssessmentResponse, Quarter, SchoolYear
from core import periods as P
from enrollment.models import Enrollment
from scheduling.models import ClassAssignment

ACTIVE = ('Enrolled', 'Transferred_In')
TYPES = dict(Assessment.TYPE_CHOICES)
QUESTION_TYPES = dict(AssessmentQuestion.TYPE_CHOICES)
# where each kind of assessment goes in the DepEd class record (DepEd Order No. 8, s. 2015)
COMPONENT = {'quiz': 'Written work', 'long_test': 'Written work', 'unit_test': 'Written work', 'assignment': 'Written work',
             'quarterly': 'Quarterly assessment', 'practice': 'Practice only, not recorded'}
STATES = {'draft': ('Draft', 'muted'), 'scheduled': ('Scheduled', 'info'), 'open': ('Open', 'good'), 'closed': ('Closed', 'muted')}
TRUE_FALSE = ['True', 'False']
MAX_QUESTIONS = 100
MAX_CHOICES = 6
GRACE = timedelta(minutes=2)       # answers sent right at the deadline or the end of the time limit still count


class Invalid(Exception):
    """The teacher's assessment cannot be saved as sent; the message says why."""


# ---------------------------------------------------------------------------------------------
# what the teacher teaches
# ---------------------------------------------------------------------------------------------

def teacher_classes(user):
    """(current school year, the teacher's active classes in it), by grade level, section and subject."""
    school = user.profile.school
    sy = SchoolYear.objects.filter(school=school, is_current=True).first()
    if not sy:
        return None, []
    classes = list(ClassAssignment.objects.filter(teacher=user, school_year=sy, is_active=True)
                   .select_related('section', 'section__grade_level', 'subject')
                   .order_by('section__grade_level__sort_order', 'section__section_name', 'subject__subject_code'))
    return sy, classes


def section_label(section):
    return f'{section.grade_level.grade_name} {section.section_name}' if section.grade_level_id else section.section_name


def subject_choices(classes):
    """The teacher's subjects, each with the sections they teach it in (and how many learners each has)."""
    learners = dict(Enrollment.objects.filter(section_id__in={a.section_id for a in classes}, status__in=ACTIVE)
                    .values_list('section_id').annotate(n=Count('id')))
    subjects = {}
    for a in classes:
        s = subjects.setdefault(a.subject_id, {'id': a.subject_id, 'code': a.subject.subject_code,
                                               'name': a.subject.subject_name, 'sections': []})
        s['sections'].append({'id': a.section_id, 'name': section_label(a.section), 'learners': learners.get(a.section_id, 0)})
    return sorted(subjects.values(), key=lambda s: s['code'])


# ---------------------------------------------------------------------------------------------
# questions
# ---------------------------------------------------------------------------------------------

def choice_text(choice):
    """Choices were saved as text or as {'text': ..., 'order': ...}."""
    return str(choice.get('text', '')) if isinstance(choice, dict) else str(choice)


def normalize(text):
    """Identification answers are compared without case, accents, extra spaces or a closing period."""
    text = unicodedata.normalize('NFKD', str(text or ''))
    text = ''.join(ch for ch in text if not unicodedata.combining(ch)).casefold()
    text = re.sub(r'[“”"‘’`´]', '', text.replace('’', "'"))
    text = re.sub(r'\s+', ' ', text).strip()
    return text.rstrip('.').strip()


def clean_questions(raw):
    """Checked question rows from the builder: [{'type', 'text', 'points', 'choices', 'correct', 'answers'}]."""
    if not isinstance(raw, list) or not raw:
        raise Invalid('Add at least one question.')
    if len(raw) > MAX_QUESTIONS:
        raise Invalid(f'An assessment can have up to {MAX_QUESTIONS} questions.')
    out = []
    for n, q in enumerate(raw, start=1):
        if not isinstance(q, dict):
            raise Invalid(f'Question {n} could not be read.')
        kind = q.get('type') if q.get('type') in QUESTION_TYPES else 'multiple_choice'
        text = str(q.get('text') or '').strip()
        if not text:
            raise Invalid(f'Question {n} has no question text.')
        try:
            points = Decimal(str(q.get('points') or 1))
        except Exception:
            raise Invalid(f'Question {n}: the points must be a number.')
        if not Decimal('0.5') <= points <= Decimal('100'):
            raise Invalid(f'Question {n}: points must be from 0.5 to 100.')
        row = {'type': kind, 'text': text[:5000], 'points': points, 'choices': [], 'correct': None, 'answers': []}
        if kind == 'multiple_choice':
            choices = [str(c or '').strip()[:500] for c in (q.get('choices') or [])]
            if not 2 <= len(choices) <= MAX_CHOICES:
                raise Invalid(f'Question {n} needs 2 to {MAX_CHOICES} choices.')
            if any(not c for c in choices):
                raise Invalid(f'Question {n} has an empty choice.')
            if len({normalize(c) for c in choices}) < len(choices):
                raise Invalid(f'Question {n} has the same choice twice.')
            row['choices'] = choices
        elif kind == 'true_false':
            row['choices'] = list(TRUE_FALSE)
        if kind in ('multiple_choice', 'true_false'):
            try:
                correct = int(q.get('correct'))
            except (TypeError, ValueError):
                correct = None
            if correct is None or not 0 <= correct < len(row['choices']):
                raise Invalid(f'Question {n}: mark the correct answer.')
            row['correct'] = correct
        else:
            answers = [str(a or '').strip()[:255] for a in (q.get('answers') or [])]
            answers = [a for a in answers if normalize(a)]
            if not answers:
                raise Invalid(f'Question {n}: give at least one accepted answer.')
            row['answers'] = answers[:20]
        out.append(row)
    return out


def save_questions(assessment, rows):
    """Replace the assessment's questions with the checked rows (choices kept in the teacher's order)."""
    assessment.questions.all().delete()
    AssessmentQuestion.objects.bulk_create([
        AssessmentQuestion(assessment=assessment, question_type=r['type'], question_text=r['text'], order_number=n,
                           points=r['points'], choices=[{'text': c, 'order': i} for i, c in enumerate(r['choices'])],
                           num_choices=len(r['choices']), correct_answer_index=r['correct'], accepted_answers=r['answers'])
        for n, r in enumerate(rows, start=1)])
    assessment.total_items = len(rows)
    assessment.question_order = []
    assessment.save(update_fields=['total_items', 'question_order', 'updated_at'])


def total_points(questions):
    return sum((Decimal(q.points) for q in questions), Decimal(0))


def builder_rows(assessment):
    """The assessment's questions in the shape the builder edits."""
    rows = []
    for q in assessment.questions.order_by('order_number'):
        rows.append({'type': q.question_type, 'text': q.question_text, 'points': float(q.points),
                     'choices': [choice_text(c) for c in q.choices] if q.question_type == 'multiple_choice' else [],
                     'correct': q.correct_answer_index, 'answers': list(q.accepted_answers or [])})
    return rows


# ---------------------------------------------------------------------------------------------
# a learner's paper
# ---------------------------------------------------------------------------------------------

def learner_order(questions, shuffle, seed):
    """[[question id, [choice index, ...]], ...]: the paper one learner gets (same seed, same paper)."""
    rng = random.Random(seed)
    questions = sorted(questions, key=lambda q: q.order_number)
    if shuffle:
        rng.shuffle(questions)
    order = []
    for q in questions:
        indexes = list(range(len(q.choices or [])))
        if shuffle and q.question_type == 'multiple_choice':
            rng.shuffle(indexes)
        order.append([q.id, indexes])
    return order


def paper(assessment, response):
    """The questions as one learner sees them, without the answer key: each choice carries its index in `choices`."""
    questions = {q.id: q for q in assessment.questions.all()}
    order = response.item_order or learner_order(questions.values(), False, 0)
    out = []
    for qid, indexes in order:
        q = questions.get(qid)
        if q is None:
            continue
        out.append({'id': q.id, 'type': q.question_type, 'text': q.question_text, 'points': float(q.points),
                    'choices': [{'value': i, 'text': choice_text(q.choices[i])} for i in indexes if i < len(q.choices)]})
    return out


def deadline_for(assessment, response):
    """When this learner's time is up: the deadline, or the end of the time limit if that comes first."""
    ends = [t for t in (assessment.closes_at,
                        response.started_at + timedelta(minutes=assessment.time_limit_minutes)
                        if assessment.time_limit_minutes and response.started_at else None) if t]
    return min(ends) if ends else None


def grade_answer(question, given):
    """(correct?, chosen index, typed text) for one answer as sent by the learner's browser."""
    given = given if isinstance(given, dict) else {}
    if question.question_type == 'identification':
        text = str(given.get('text') or '').strip()[:255]
        accepted = {normalize(a) for a in question.accepted_answers or []} - {''}
        return bool(text) and normalize(text) in accepted, None, text
    try:
        index = int(given.get('choice'))
    except (TypeError, ValueError):
        return False, None, ''
    if not 0 <= index < len(question.choices or []):
        return False, None, ''
    return index == question.correct_answer_index, index, ''


def grade(response, answers):
    """Grade and save a learner's answers (a dict keyed by question id); returns (score, total points)."""
    questions = list(response.assessment.questions.all())
    rows, score, total = [], Decimal(0), Decimal(0)
    for q in questions:
        correct, index, text = grade_answer(q, answers.get(str(q.id)) if isinstance(answers, dict) else None)
        earned = Decimal(q.points) if correct else Decimal(0)
        score += earned
        total += Decimal(q.points)
        if index is not None or text:
            rows.append(AssessmentAnswer(response=response, question=q, selected_index=index, text_answer=text,
                                         is_correct=correct, points_earned=earned))
    response.answers.all().delete()
    AssessmentAnswer.objects.bulk_create(rows)
    response.score, response.total_points, response.passed = score, total, False
    response.submitted_at = timezone.now()
    response.save(update_fields=['score', 'total_points', 'passed', 'submitted_at'])
    return score, total


# ---------------------------------------------------------------------------------------------
# results
# ---------------------------------------------------------------------------------------------

def class_list_key(student):
    """DepEd class list order: males, then females, each by surname and first name."""
    return (0 if (student.sex or '').upper().startswith('M') else 1, (student.last_name or '').casefold(),
            (student.first_name or '').casefold())


def learner_name(student):
    middle = f' {student.middle_name[0]}.' if student.middle_name else ''
    ext = f' {student.name_extension}' if getattr(student, 'name_extension', '') else ''
    return f'{student.last_name}, {student.first_name}{ext}{middle}'


def percent(score, total):
    return round(float(score) * 100 / float(total), 1) if total else None


def results(assessment):
    """Every learner of the section (and any older response not tied to one), class-list order, plus summary figures."""
    questions = list(assessment.questions.order_by('order_number'))
    points = total_points(questions)
    enrollments = list(Enrollment.objects.filter(section_id=assessment.section_id, school_year_id=assessment.school_year_id)
                       .select_related('student'))
    responses = list(assessment.responses.all())
    by_enrollment = {r.enrollment_id: r for r in responses if r.enrollment_id}
    by_student = {r.student_id: r for r in responses if r.student_id and not r.enrollment_id}
    used, rows = set(), []
    for e in enrollments:
        r = by_enrollment.get(e.id) or by_student.get(e.student_id)
        if e.status not in ACTIVE and r is None:
            continue
        if r:
            used.add(r.id)
        rows.append(_row(e.student, r, e, points))
    rows.sort(key=lambda row: row['order'])
    others = [_row(None, r, None, points) for r in responses if r.id not in used]
    submitted = [row for row in rows + others if row['status'] == 'submitted']
    scores = [row['percent'] for row in submitted if row['percent'] is not None]
    enrolled = sum(1 for row in rows if row['active'])
    return {
        'questions': questions, 'points': points, 'rows': rows, 'others': others,
        'males': sum(1 for row in rows if row['sex'] == 'M'), 'females': sum(1 for row in rows if row['sex'] == 'F'),
        'enrolled': enrolled, 'submitted': len(submitted),
        'started': sum(1 for row in rows + others if row['status'] == 'started'),
        'missing': sum(1 for row in rows if row['active'] and row['status'] == 'not_started'),
        'average': round(mean(scores), 1) if scores else None,
        'highest': max(scores) if scores else None, 'lowest': min(scores) if scores else None,
        'items': item_analysis(questions, [r for r in responses if r.submitted_at]),
    }


def _row(student, response, enrollment, points):
    status = 'submitted' if response and response.submitted_at else ('started' if response else 'not_started')
    total = response.total_points if response and response.total_points else points
    taken = None
    if response and response.submitted_at and response.started_at and response.submitted_at >= response.started_at:
        taken = max(1, round((response.submitted_at - response.started_at).total_seconds() / 60))
    if student is not None:
        name, lrn, sex, order = learner_name(student), student.lrn or '', (student.sex or '').upper()[:1], class_list_key(student)
    else:
        name = (response.student_name or response.student_email or 'Unknown learner') if response else ''
        lrn, sex, order = '', '', (2, name.casefold(), '')
    return {
        'name': name, 'lrn': lrn, 'sex': sex, 'order': order, 'status': status, 'response': response,
        'active': enrollment is not None and enrollment.status in ACTIVE,
        'left': enrollment is not None and enrollment.status not in ACTIVE,
        'score': response.score if status == 'submitted' else None, 'total': total,
        'percent': percent(response.score, total) if status == 'submitted' else None,
        'submitted_at': response.submitted_at if response else None, 'minutes': taken,
    }


def item_analysis(questions, responses):
    """Per question: how many answered, how many got it right, and the most chosen wrong choice."""
    ids = [r.id for r in responses]
    stats = {q.id: {'answered': 0, 'correct': 0, 'picks': {}} for q in questions}
    if ids:
        for qid, index, text, correct in AssessmentAnswer.objects.filter(response_id__in=ids).values_list(
                'question_id', 'selected_index', 'text_answer', 'is_correct'):
            s = stats.get(qid)
            if s is None:
                continue
            s['answered'] += 1
            s['correct'] += bool(correct)
            if not correct:
                key = index if index is not None else normalize(text)
                s['picks'][key] = s['picks'].get(key, 0) + 1
    # responses saved before answers were kept (older demo data) have a score but no answers to analyse
    with_details = AssessmentAnswer.objects.filter(response_id__in=ids).values('response_id').distinct().count() if ids else 0
    items = []
    for q in questions:
        s = stats[q.id]
        wrong = max(s['picks'].items(), key=lambda kv: kv[1]) if s['picks'] else None
        common = None
        if wrong:
            key, count = wrong
            common = {'text': choice_text(q.choices[key]) if isinstance(key, int) and key < len(q.choices or []) else key,
                      'count': count}
        items.append({
            'number': q.order_number, 'id': q.id, 'type': QUESTION_TYPES.get(q.question_type, ''), 'text': q.question_text,
            'answer': answer_key_text(q), 'answered': s['answered'], 'correct': s['correct'],
            'percent': round(s['correct'] * 100 / with_details, 1) if with_details else None, 'common_wrong': common,
        })
    return {'items': items, 'responses': with_details}


def answer_key_text(question):
    if question.question_type == 'identification':
        return ' / '.join(question.accepted_answers or [])
    if question.correct_answer_index is not None and question.correct_answer_index < len(question.choices or []):
        return choice_text(question.choices[question.correct_answer_index])
    return ''


# ---------------------------------------------------------------------------------------------
# the teacher's list
# ---------------------------------------------------------------------------------------------

def list_rows(user, now=None):
    """The teacher's assessments with state, deadline and how many of the section have submitted."""
    now = now or timezone.now()
    assessments = list(Assessment.objects.filter(teacher=user).select_related('subject', 'section', 'section__grade_level')
                       .annotate(n_questions=Count('questions', distinct=True),
                                 n_submitted=Count('responses', filter=Q(responses__submitted_at__isnull=False), distinct=True)))
    sections = {a.section_id for a in assessments}
    learners = dict(Enrollment.objects.filter(section_id__in=sections, status__in=ACTIVE)
                    .values_list('section_id').annotate(n=Count('id')))
    averages = {}
    for aid, score, total in AssessmentResponse.objects.filter(assessment__in=assessments, submitted_at__isnull=False) \
            .values_list('assessment_id', 'score', 'total_points'):
        if total:
            averages.setdefault(aid, []).append(float(score) * 100 / float(total))
    rows = []
    for a in assessments:
        state = a.state(now)
        label, tone = STATES[state]
        enrolled = learners.get(a.section_id, 0)
        left = (a.closes_at - now) if a.closes_at and state in ('open', 'scheduled') else None
        rows.append({
            'assessment': a, 'state': state, 'state_label': label, 'state_tone': tone,
            'type': TYPES.get(a.assessment_type, 'Quiz'), 'section': section_label(a.section),
            'enrolled': enrolled, 'submitted': a.n_submitted, 'questions': a.n_questions,
            'missing': max(0, enrolled - a.n_submitted) if state != 'draft' else 0,
            'progress': min(100, round(a.n_submitted * 100 / enrolled)) if enrolled else 0,
            'average': round(mean(averages[a.id]), 1) if a.id in averages else None,
            'closing_soon': left is not None and left <= timedelta(hours=24),
            'deadline_sort': a.closes_at.timestamp() if a.closes_at else float('inf'),
        })
    return rows


def current_period(school_year):
    return P.current(list(Quarter.objects.filter(school_year=school_year).order_by('quarter_number'))) if school_year else None
