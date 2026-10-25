"""School Head: Page Proposals, pages that could come next, for the team and the adviser to discuss.

Nothing here changes data. Each card says what a page would answer, what it would show, how much of
its data ARMS already keeps (counted from this school's records, so the readiness shown is real),
its DepEd basis (the school's own grading rules), a rough size of the work, and the questions to settle
before building it. Proposals that have been built stay at the end with a link and what was settled.
School Overview and Forms Compliance are left out: the Dean already turned them down.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render
from django.urls import reverse

from attendance.models import AttendanceSummary
from core import grading_policy as policy
from enrollment.models import Enrollment
from grades.models import GradeComponent
from ml_engine import forecast as ml
from scheduling.models import ClassAssignment

from .views_academic import _denied, _head_school


@login_required
def proposals(request):
    school = _head_school(request)
    if school is None:
        return _denied(request)
    enrollments = Enrollment.objects.filter(section__school=school)
    learners = enrollments.values('student_id').distinct().count()
    years = enrollments.values('school_year_id').distinct().count()
    grades = GradeComponent.objects.filter(enrollment__section__school=school).count()
    attendance = AttendanceSummary.objects.filter(enrollment__section__school=school)
    months = attendance.values('school_year_id', 'month').distinct().count()
    classes = ClassAssignment.objects.filter(section__school=school, is_active=True).values('teacher_id').annotate(n=Count('id')).count()
    _, meta = ml.load()
    rules = policy.current()
    parts = [name.lower() for _, name, _ in policy.components()]
    model_line = (f'Ready: the grade model learned from {meta["samples"]:,} records and was off by '
                  f'{meta["evaluation"][-1]["model"]["mae"]:.1f} points on the latest unseen quarter.') if meta else \
        'Partly ready: train the grade model first (python manage.py train_ml_models).'

    cards = [
        {'key': 'profile', 'icon': 'fi-rr-id-badge', 'name': 'Learner Profile', 'size': 'Medium', 'ready': 'ready',
         'question': 'How is one learner doing across every subject, period and school year?',
         'shows': ['Quarterly grades and proficiency level in every subject, with the change from last period',
                   'Attendance month by month', 'The grade model\'s forecast and the chance of falling below 75',
                   'Support given so far (from the level-up plans)'],
         'data': f'Ready: {learners:,} learners and {grades:,} grade records across {years} school year{"" if years == 1 else "s"}.',
         'basis': f'{rules["name"]} (the report card grades and their descriptors).',
         'decide': ['Should advisers see it for their own section?', 'Is a printable one-page summary needed for parent conferences?']},
        {'key': 'tracker', 'icon': 'fi-rr-list-check', 'name': 'Intervention Tracker', 'size': 'Large', 'ready': 'partial',
         'question': 'Did remediation work for the learners below 75?',
         'shows': ['Every learner below 75 with the remediation plan: what, who, starting when',
                   'Weekly check-ins recorded by the teacher', 'The outcome: the next quarter\'s grade against the target',
                   'Which strategies lift learners most, by grade component'],
         'data': 'Partly ready: learners and grades are in ARMS; the plans and check-ins would be new records kept by teachers.',
         'basis': f'{rules["name"]} requires remediation for grades below 75.',
         'decide': ['Do teachers or advisers record the check-ins?', 'Should the School Head approve plans, or only read them?']},
        {'key': 'attendance', 'icon': 'fi-rr-calendar-check', 'name': 'Attendance Watch', 'size': 'Small', 'ready': 'ready' if months else 'partial',
         'question': 'Who misses class often, and does it show in their grades?',
         'shows': ['Attendance by section and month, lowest first', 'Learners absent on 20% or more of school days',
                   'Attendance next to grades, to see where absences and low grades meet'],
         'data': (f'Ready: {attendance.count():,} monthly attendance summaries over {months} month{"" if months == 1 else "s"}.' if months
                  else 'Partly ready: no monthly attendance has been recorded yet.'),
         'basis': 'School Form 2 (Daily Attendance Report of Learners).',
         'decide': ['Which absence level should alert the School Head?', 'Should advisers get the same alerts?']},
        {'key': 'coaching', 'icon': 'fi-rr-chalkboard-user', 'name': 'Class Coaching', 'size': 'Medium', 'ready': 'ready' if classes else 'partial',
         'question': 'Which classes would gain most from coaching, and on which grade component?',
         'shows': ['Each teacher\'s classes with averages, trend and learners per level',
                   f'The weakest component ({", ".join(parts[:-1])} or {parts[-1]}) per class',
                   'Notes from classroom observations'],
         'data': f'Ready: class assignments for {classes} teacher{"" if classes == 1 else "s"} and every grade component score.',
         'basis': 'Classroom observation and coaching in the RPMS cycle (DepEd Order No. 2, s. 2015).',
         'decide': ['How to keep it about support, never ranking teachers?', 'Should teachers see their own page?']},
        {'key': 'lac', 'icon': 'fi-rr-users-alt', 'name': 'LAC Planner', 'size': 'Medium', 'ready': 'partial',
         'question': 'What should the next Learning Action Cell session focus on?',
         'shows': ['The learning areas and grade components that need the most work', 'Suggested topics and the teachers to invite',
                   'Sessions held, and the grades of the classes afterwards'],
         'data': 'Partly ready: focus areas come from the grades; the sessions would be new records.',
         'basis': 'DepEd Order No. 35, s. 2016 (Learning Action Cells).',
         'decide': ['Who schedules the sessions?', 'Should attendance at sessions be recorded?']},
        {'key': 'enrollment', 'icon': 'fi-rr-chart-histogram', 'name': 'Enrollment Outlook', 'size': 'Medium', 'ready': 'partial' if years < 3 else 'ready',
         'question': 'How many learners should the school prepare for next school year?',
         'shows': ['Next year\'s learners by grade level, from how many move up each year', 'A likely range, and the sections it would need',
                   'Transfers in and out'],
         'data': f'Partly ready: {years} school year{"" if years == 1 else "s"} of enrollment; three or more make the outlook reliable.'
                 if years < 3 else f'Ready: {years} school years of enrollment.',
         'basis': 'School Forms 1 and 4 (School Register; Monthly Learner\'s Movement).',
         'decide': ['Should it plan sections and teachers too?', 'Who updates the expected new enrollees?']},
        {'key': 'accuracy', 'icon': 'fi-rr-chart-line-up', 'name': 'Forecast Accuracy', 'size': 'Small', 'ready': 'ready' if meta else 'partial',
         'question': 'How far can we trust the forecasts?',
         'shows': ['How far off the forecasts were for this school, tested on quarters the model never saw',
                   'The same by grade level', 'What the forecasts lean on most'],
         'data': model_line,
         'basis': 'Transparency for decisions made with AI support.',
         'decide': ['Does the School Head need it, or is the administrator\'s Grade Forecaster page enough?',
                    'Should the accuracy appear on every forecast chart?']},
        # built: kept at the end with what was settled
        {'key': 'honors', 'icon': 'fi-rr-trophy', 'name': 'Honors Outlook', 'size': 'Small', 'ready': 'built',
         'url': reverse('heads-honors'),
         'question': 'Who is on track for an academic award this year, and who is close?',
         'shows': [f'Learners on track for {rules["awards"]["label"].lower()} under {rules["short"]}, now and with the forecasts',
                   'Learners within 2 points of a cut-off, and those held back by one final grade', 'Every list as an Excel file'],
         'data': 'Built: quarterly grades and the grade model\'s forecasts.',
         'basis': f'{rules["awards"]["order"]} (awards and recognition).',
         'settled': ['Each school picks its DepEd rules on the School Year page: the honors of DepEd Order No. 36, s. 2016, '
                     'or the single Academic Excellence Award of DepEd Order No. 015, s. 2026.']},
    ]
    return render(request, 'heads/proposals/index.html', {'cards': cards, 'school': school})
