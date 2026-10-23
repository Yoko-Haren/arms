"""School Head: Page Proposals, pages that could come next, for the team and the adviser to discuss.

Nothing here changes data. Each card says what a page would answer, what it would show, how much of
its data ARMS already keeps (counted from this school's records, so the readiness shown is real),
its DepEd basis, a rough size of the work, and the questions to settle before building it. School
Overview and Forms Compliance are left out: the Dean already turned them down.
"""
from django.contrib.auth.decorators import login_required
from django.db.models import Count
from django.shortcuts import render

from attendance.models import AttendanceSummary
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
         'basis': 'DepEd Order No. 8, s. 2015 (the report card grades); DepEd Order No. 31, s. 2012 (levels).',
         'decide': ['Should advisers see it for their own section?', 'Is a printable one-page summary needed for parent conferences?']},
        {'key': 'tracker', 'icon': 'fi-rr-list-check', 'name': 'Intervention Tracker', 'size': 'Large', 'ready': 'partial',
         'question': 'Did remediation work for the learners below 75?',
         'shows': ['Every learner below 75 with the remediation plan: what, who, starting when',
                   'Weekly check-ins recorded by the teacher', 'The outcome: the next quarter\'s grade against the target',
                   'Which strategies lift learners most, by grade component'],
         'data': 'Partly ready: learners and grades are in ARMS; the plans and check-ins would be new records kept by teachers.',
         'basis': 'DepEd Order No. 8, s. 2015 requires remediation for grades below 75.',
         'decide': ['Do teachers or advisers record the check-ins?', 'Should the School Head approve plans, or only read them?']},
        {'key': 'attendance', 'icon': 'fi-rr-calendar-check', 'name': 'Attendance Watch', 'size': 'Small', 'ready': 'ready' if months else 'partial',
         'question': 'Who misses class often, and does it show in their grades?',
         'shows': ['Attendance by section and month, lowest first', 'Learners absent on 20% or more of school days',
                   'Attendance next to grades, to see where absences and low grades meet'],
         'data': (f'Ready: {attendance.count():,} monthly attendance summaries over {months} month{"" if months == 1 else "s"}.' if months
                  else 'Partly ready: no monthly attendance has been recorded yet.'),
         'basis': 'School Form 2 (Daily Attendance Report of Learners).',
         'decide': ['Which absence level should alert the School Head?', 'Should advisers get the same alerts?']},
        {'key': 'honors', 'icon': 'fi-rr-trophy', 'name': 'Honors Outlook', 'size': 'Small', 'ready': 'ready',
         'question': 'Who is on track for honors this year, and who is close?',
         'shows': ['Learners on track for With Honors, With High Honors and With Highest Honors',
                   'Learners within 2 points of a cut-off, and the subjects holding them back',
                   'The forecast for the rest of the year'],
         'data': 'Ready: quarterly grades and the grade model\'s forecasts.',
         'basis': 'DepEd Order No. 36, s. 2016 (awards and recognition).',
         'decide': ['Should near-honors learners be listed for advisers?', 'Is a list for the awards committee needed?']},
        {'key': 'accuracy', 'icon': 'fi-rr-chart-line-up', 'name': 'Forecast Accuracy', 'size': 'Small', 'ready': 'ready' if meta else 'partial',
         'question': 'How far can we trust the forecasts?',
         'shows': ['Forecast against actual grades for every past quarter', 'How far off the model was, by learner and by class',
                   'What the forecasts lean on most', 'When the model was last trained, and a button to retrain'],
         'data': model_line,
         'basis': 'Transparency for decisions made with AI support.',
         'decide': ['Who may retrain the model?', 'Should the accuracy appear on every forecast chart?']},
        {'key': 'coaching', 'icon': 'fi-rr-chalkboard-user', 'name': 'Class Coaching', 'size': 'Medium', 'ready': 'ready' if classes else 'partial',
         'question': 'Which classes would gain most from coaching, and on which grade component?',
         'shows': ['Each teacher\'s classes with averages, trend and learners per level',
                   'The weakest component (written work, performance tasks or quarterly assessment) per class',
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
    ]
    return render(request, 'heads/proposals/index.html', {'cards': cards, 'school': school})
