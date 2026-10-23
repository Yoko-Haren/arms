"""DepEd school forms filled from ARMS, on DepEd's own templates (documentation/sf_templates).

Each builder returns (bytes, file name). The templates are DepEd's files split one form per
workbook; core.xlsx_patch writes the values into their cells and adds rows when a class is
longer than the printed form, so logos, borders, print setup and guidelines stay as DepEd made
them. Junior High (Grades 7 to 10) and Senior High have their own versions where DepEd has two.

  SF1  School Register                        per section (Senior High: per semester)
  SF2  Daily Attendance Report                per section and month
  SF3  Books Issued and Returned              per section (names and subjects; books are not in ARMS)
  SF4  Monthly Learner Movement & Attendance  whole school, per month
  SF5  Promotion and Learning Progress        per section (Senior High: SF5A per semester, SF5B completers)
  SF6  Summarized Promotion Report            whole school
  SF7  Personnel Assignment List              whole school
  Summary of final grades (Grades 7 to 10, per section) and MAPEH final grades (per MAPEH class).

Figures that the templates format oddly (a percent format on one cell of a column, zero-padded
totals) are written as text in the form's own way of showing them.
"""
import calendar
import io
import re
import zipfile
from datetime import date
from pathlib import Path

from core import xlsx_patch
from core.xlsx_patch import Rows

from . import form_data as FD

TEMPLATES = Path(__file__).resolve().parent / 'sf_templates'
ECR_TEMPLATES = Path(__file__).resolve().parent.parent / 'grades' / 'ecr_templates'


class FormUnavailable(Exception):
    pass


FORMS = {
    'SF1': {'title': 'School Register', 'scope': 'section'},
    'SF2': {'title': 'Daily Attendance Report of Learners', 'scope': 'section', 'month': True},
    'SF3': {'title': 'Books Issued and Returned', 'scope': 'section'},
    'SF4': {'title': "Monthly Learner's Movement and Attendance", 'scope': 'school', 'month': True},
    'SF5': {'title': 'Report on Promotion and Learning Progress & Achievement', 'scope': 'section'},
    'SF5A': {'title': 'End of Semester and School Year Status of Learners', 'scope': 'section', 'shs': True},
    'SF5B': {'title': 'Learners with Complete SHS Requirements', 'scope': 'section', 'shs': True, 'grade12': True},
    'SF6': {'title': 'Summarized Report on Promotion and Learning Progress', 'scope': 'school'},
    'SF7': {'title': 'School Personnel Assignment List and Basic Profile', 'scope': 'school'},
    'SUMMARY': {'title': 'Summary of Final Grades', 'scope': 'section', 'jhs': True},
}


# ---------------------------------------------------------------------------------------------
# shared pieces
# ---------------------------------------------------------------------------------------------

def _template(name):
    path = TEMPLATES / name
    if not path.exists():
        raise FormUnavailable(f'The {name} template is missing on the server (documentation/sf_templates).')
    return path


def _sheet(data):
    return next(iter(xlsx_patch.sheet_parts(zipfile.ZipFile(io.BytesIO(data)))))


def _render(path, cells, rows=None, styles=None, merges=None):
    data = path.read_bytes()
    sheet = _sheet(data)
    steps = rows.steps() if rows else []
    return xlsx_patch.patch(data, {sheet: cells}, inserts={sheet: steps} if steps else None,
                            styles={sheet: styles} if styles else None, merges={sheet: merges} if merges else None)


def _styles_like(path, pairs):
    """{target cell: style of a template cell}, pairs being {target: source} (source in template rows)."""
    data = path.read_bytes()
    found = xlsx_patch.cell_styles(data, _sheet(data), set(pairs.values()))
    return {target: found[source] for target, source in pairs.items() if found.get(source)}


def _slug(text):
    return re.sub(r'[^A-Za-z0-9]+', '-', str(text)).strip('-')


def _file_name(code, section=None, extra='', sy=None):
    parts = [code]
    if section is not None:
        parts.append(_slug(f'{section.grade_level.grade_name}-{section.section_name}'))
    if extra:
        parts.append(_slug(extra))
    if sy is not None:
        parts.append(f'SY{sy.year_label}')
    return '_'.join(parts) + '.xlsx'


def _date_text(d):
    return d.strftime('%m/%d/%Y') if d else ''


def _grade_text(section):
    return str(section.grade_level.grade_number or section.grade_level.grade_name)


def _track_strand(section):
    s = section.strand
    if not s:
        return ''
    track = s.track.track_name if s.track_id else ''
    return f'{track} - {s.strand_code}'.strip(' -').upper() if track else s.strand_code


def _course(section):
    s = section.strand
    if s and s.track_id and s.track.track_code.upper() in ('TVL', 'TECHPRO'):
        return s.strand_name
    return ''


def _semester_label(semester):
    return f'{semester.semester_label} Semester' if semester else ''


def _counts(people, test=lambda p: True):
    m = sum(1 for p in people if p['sex'] == 'M' and test(p))
    f = sum(1 for p in people if p['sex'] != 'M' and test(p))
    return m, f, m + f


def _fmt(value, pct=False, places=2):
    """A figure as the forms print it: whole numbers plain, others with two decimals, percentages with %."""
    if value is None or value == '':
        return None
    if isinstance(value, float) and not value.is_integer():
        text = f'{value:.{places}f}'
    else:
        text = str(int(value))
    return text + '%' if pct else text


def _put3(cells, cols, row, values, pct=False, places=2):
    for col, value in zip(cols, values):
        cells[f'{col}{row}'] = _fmt(value, pct, places) if not isinstance(value, str) else value


def _pct(part, whole):
    return float(FD.round_half_up(part * 100 / whole, 2)) if whole else None


def is_senior(section):
    return section.grade_level.is_senior_high


class _DerivedSemester:
    """A semester of a school year that has quarters but no semester records: Q1-Q2 and Q3-Q4."""
    id = None
    is_current_semester = False

    def __init__(self, number, quarters):
        self.semester_number = number
        self.semester_label = '1st' if number == 1 else '2nd'
        self.date_start, self.date_end = quarters[0].date_start, quarters[-1].date_end


def semesters(sy):
    from academics.models import Quarter, Semester
    sems = list(Semester.objects.filter(school_year=sy).order_by('semester_number'))
    if sems:
        return sems
    quarters = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number'))
    half = len(quarters) // 2
    return [_DerivedSemester(1, quarters[:half]), _DerivedSemester(2, quarters[half:])] if half else []


def month_param(text):
    """A month number (1-12) from a request parameter, or None for anything else."""
    text = str(text or '').strip()
    return int(text) if text.isdigit() and 1 <= int(text) <= 12 else None


def semester_param(sy, text):
    """The semester (1 or 2) a request parameter names, or None."""
    text = str(text or '').strip()
    return semester_of(sy, text) if text in ('1', '2') else None


def semester_of(sy, number=None):
    sems = semesters(sy)
    if number:
        return next((s for s in sems if s.semester_number == int(number)), None)
    today = date.today()
    return next((s for s in sems if s.is_current_semester), None) or \
        next((s for s in sems if s.date_start <= today <= s.date_end), None) or \
        (sems[-1] if sems and today > sems[-1].date_end else sems[0] if sems else None)


# ---------------------------------------------------------------------------------------------
# SF1 School Register
# ---------------------------------------------------------------------------------------------

def sf1(section, sy, semester=None):
    if is_senior(section):
        return _sf1_shs(section, sy, semester or semester_of(sy))
    info = FD.school_info(section.school, sy)
    people = FD.learners(section, sy)
    males, females = FD.split_sex(people)
    rows = Rows()
    rows.grow(10, 49, len(males) + len(females) + 3)
    cells = {'F4': info['school_id'], 'H4': 'Region', 'K4': info['region'], 'N4': info['division'], 'U4': info['district'],
             'F6': info['school_name'], 'P6': sy.year_label, 'U6': _grade_text(section), 'X6': section.section_name.upper()}
    r = 10

    def learner(p, r):
        cells.update({f'B{r}': p['lrn'], f'C{r}': p['name'], f'G{r}': p['sex'], f'H{r}': _date_text(p['birth_date']),
                      f'I{r}': p['age'], f'J{r}': p['birth_place'], f'L{r}': p['mother_tongue'], f'M{r}': p['ip'],
                      f'N{r}': p['religion'], f'O{r}': p['street'], f'P{r}': p['barangay'], f'Q{r}': p['city'],
                      f'R{r}': p['province'], f'T{r}': p['father'], f'V{r}': p['mother'], f'X{r}': p['guardian'],
                      f'Y{r}': p['relationship'], f'Z{r}': p['contact'], f'AA{r}': p['remarks']})
    for p in males:
        learner(p, r)
        r += 1
    cells.update({f'B{r}': len(males), f'C{r}': '<=== TOTAL MALE'})
    r += 1
    for p in females:
        learner(p, r)
        r += 1
    cells.update({f'B{r}': len(females), f'C{r}': '<=== TOTAL FEMALE', f'B{r + 1}': len(people), f'C{r + 1}': '<=== COMBINED'})
    bosy = _counts(people, lambda p: not p['late'])
    _register_table(cells, rows, bosy, people, sy, ('T', 'U'), (61, 62, 63))
    cells[f'W{rows.at(61)}'] = FD.adviser_of(section)
    cells[f'Z{rows.at(61)}'] = info['head']
    lrn_style = {f'B{n}': '49' for n in range(10, r + 2)}          # the Sex column's style: same borders, 18 pt
    return _render(_template('jhs/SF1.xlsx'), cells, rows, lrn_style), _file_name('SF1', section, sy=sy)


def _register_table(cells, rows, beginning, people, period, cols, table_rows, ended=None):
    """REGISTERED table: beginning of the year or semester, and its end once it is over."""
    ended = ended if ended is not None else date.today() >= period.date_end
    end = _counts(people, lambda p: p['active']) if ended else (None, None, None)
    for (row, b, e) in zip(table_rows, beginning, end):
        cells[f'{cols[0]}{rows.at(row)}'] = _fmt(b)
        cells[f'{cols[1]}{rows.at(row)}'] = _fmt(e)


# SHSF-1 rows are not merged alike (DepEd's file): every learner row gets the header's merges
_SHS_SF1_MERGES = (('A', 'B'), ('C', 'F'), ('H', 'I'), ('J', 'K'), ('N', 'Q'), ('R', 'T'), ('U', 'V'), ('X', 'Y'),
                   ('Z', 'AB'), ('AE', 'AF'))


def _sf1_shs(section, sy, semester):
    info = FD.school_info(section.school, sy)
    people = FD.learners(section, sy)
    males, females = FD.split_sex(people)
    rows = Rows()
    rows.grow(11, 40, len(males))
    rows.grow(52, 40, len(females))
    cells = {'F3': info['school_name'], 'M3': info['school_id'], 'U3': info['district'], 'Z3': info['division'],
             'AF3': info['region'], 'F5': _semester_label(semester), 'M5': sy.year_label, 'W5': _grade_text(section),
             'AC5': _track_strand(section), 'F7': section.section_name.upper(), 'P7': _course(section)}
    merges = []

    def learner(p, r):
        cells.update({f'A{r}': p['lrn'], f'C{r}': p['name'], f'G{r}': p['sex'], f'H{r}': _date_text(p['birth_date']),
                      f'J{r}': _fmt(p['age']), f'L{r}': p['religion'], f'M{r}': p['street'], f'N{r}': p['barangay'],
                      f'R{r}': p['city'], f'U{r}': p['province'], f'W{r}': p['father'], f'X{r}': p['mother'],
                      f'Z{r}': p['guardian'], f'AC{r}': p['relationship'], f'AD{r}': p['contact'], f'AE{r}': p['remarks']})
        merges.extend(f'{a}{r}:{b}{r}' for a, b in _SHS_SF1_MERGES)
    for block, first, size in ((males, 11, 40), (females, 52, 40)):
        start = rows.at(first)
        for i, p in enumerate(block):
            learner(p, start + i)
        for i in range(len(block), size):                  # the template numbers its empty LRN cells
            cells[f'A{start + i}'] = None
    cells[f'A{rows.at(51)}'] = _fmt(len(males))
    cells[f'A{rows.at(92)}'] = _fmt(len(females))
    cells[f'A{rows.at(93)}'] = _fmt(len(people))
    beginning = _counts(people, lambda p: not p['late'])
    ended = bool(semester) and date.today() >= semester.date_end
    end = _counts(people, lambda p: p['active']) if ended else (None, None, None)
    for row, b, e in zip((96, 97, 99), beginning, end):
        cells[f'U{rows.at(row)}'] = _fmt(b)
        cells[f'W{rows.at(row)}'] = _fmt(e)
    cells[f'Y{rows.at(96)}'] = FD.adviser_of(section)
    return (_render(_template('shs/SHSF-1.xlsx'), cells, rows, merges=merges),
            _file_name('SF1', section, _semester_label(semester), sy))


# ---------------------------------------------------------------------------------------------
# SF2 Daily Attendance
# ---------------------------------------------------------------------------------------------

_JHS_DAY_COLS = [['D', 'E', 'F', 'G', 'H'], ['I', 'J', 'K', 'L', 'M'], ['N', 'O', 'P', 'Q', 'R'],
                 ['S', 'T', 'U', 'V', 'W'], ['X', 'Y', 'Z', 'AA', 'AB']]
_SHS_DAY_COLS = [['F', 'H', 'I', 'J', 'K', 'L'], ['M', 'O', 'P', 'Q', 'R', 'S'], ['T', 'V', 'W', 'X', 'Z', 'AB'],
                 ['AC', 'AE', 'AF', 'AG', 'AH', 'AI'], ['AJ', 'AK', 'AM', 'AN', 'AO', 'AQ']]


def _day_columns(days, grid):
    """Each school day's column: week by week, Monday first (the first, partial week included)."""
    if not days:
        return {}
    monday = days[0].toordinal() - days[0].weekday()
    out = {}
    for d in days:
        week = (d.toordinal() - monday) // 7
        if week < len(grid) and d.weekday() < len(grid[week]):
            out[d] = grid[week][d.weekday()]
    return out


def _attendance_month(section, sy, month, people, saturdays=False):
    year, _ = FD.month_of(sy, month)
    days = FD.month_days(year, month, sy)
    summaries, daily = FD.attendance([p['enrollment'].id for p in people], sy, month)
    if saturdays:
        marked = {d for marks in daily.values() for d in marks if d.weekday() == 5}
        days = sorted(set(days) | marked)
    school_days = max((s.total_school_days for s in summaries.values()), default=0) or len(days)
    start, end = date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])
    for p in people:
        s = summaries.get(p['enrollment'].id)
        marks = daily.get(p['enrollment'].id, {})
        p['marks'] = {d: ('x' if st == 'Absent' else 'T' if st in ('Late', 'Cutting') else '') for d, st in marks.items()}
        p['absent'] = s.days_absent if s else (sum(1 for v in marks.values() if v == 'Absent') if marks else None)
        p['tardy'] = s.days_late if s else (sum(1 for v in marks.values() if v in ('Late', 'Cutting')) if marks else None)
        p['present'] = s.days_present if s else None
        p['consecutive'] = s.consecutive_absences if s else 0
        e = p['enrollment']
        note = ''
        if e.status in FD.LEFT and e.status_date and start <= e.status_date <= end:
            note = ('DRP' if e.status == 'Dropped' else 'T/O') + f' {e.status_date:%m/%d/%Y}'
        elif 'T/I' in p['codes'] and e.enrollment_date and start <= e.enrollment_date <= end:
            note = f'T/I {e.enrollment_date:%m/%d/%Y}'
        p['month_note'] = note
    enrollments = [p['enrollment'] for p in people]
    summary = {
        'month': calendar.month_name[month], 'year': year, 'days': days, 'school_days': school_days,
        'enrolment': _counts(people, lambda p: not p['late']),
        'late': _counts(people, lambda p: p['late'] and p['enrollment'].enrollment_date and start <= p['enrollment'].enrollment_date <= end),
        'registered': tuple(FD.registered_at(enrollments, end)) + (sum(FD.registered_at(enrollments, end)),),
        'present': [sum(p['present'] or 0 for p in people if (p['sex'] == 'M') == male) for male in (True, False)],
        'consecutive': _counts(people, lambda p: (p['consecutive'] or 0) >= 5),
        'movement': FD.month_movement(enrollments, year, month),
    }
    summary['present'].append(sum(summary['present']))
    reg = summary['registered']
    summary['ada'] = [float(FD.round_half_up(x / school_days, 2)) if school_days else None for x in summary['present']]
    summary['pct_enrolment'] = [_pct(r, e) for r, e in zip(reg, summary['enrolment'])]
    summary['pct_attendance'] = [_pct(a, r) if a is not None else None for a, r in zip(summary['ada'], reg)]
    return summary


def _movement_triplet(movement, key, which):
    m, f = movement[key][0][which], movement[key][1][which]
    return m, f, m + f


def _sf2_summary(cells, rows, s, cols, layout):
    """The SF2 summary box: rows in layout order, enrolment ... transferred in."""
    mv = s['movement']
    values = {'enrolment': (s['enrolment'], False), 'late': (s['late'], False), 'registered': (s['registered'], False),
              'pct_enrolment': (s['pct_enrolment'], True), 'ada': (s['ada'], False), 'pct_attendance': (s['pct_attendance'], True),
              'consecutive': (s['consecutive'], False), 'drp': (_movement_triplet(mv, 'drp', 1), False),
              'to': (_movement_triplet(mv, 'to', 1), False), 'ti': (_movement_triplet(mv, 'ti', 1), False),
              'shift_out': ((0, 0, 0), False), 'shift_in': ((0, 0, 0), False)}
    for key, row in layout:
        triplet, pct = values[key]
        _put3(cells, cols, rows.at(row), triplet, pct)


def sf2(section, sy, month, semester=None):
    if is_senior(section):
        return _sf2_shs(section, sy, month, semester or semester_of(sy))
    info = FD.school_info(section.school, sy)
    people = FD.learners(section, sy)
    s = _attendance_month(section, sy, month, people)
    males, females = FD.split_sex(people)
    rows = Rows()
    rows.grow(13, 21, len(males))
    rows.grow(35, 25, len(females))
    cells = {'C6': info['school_id'], 'K6': sy.year_label, 'X6': f'{s["month"]} {s["year"]}', 'C8': info['school_name'],
             'X8': _grade_text(section), 'AC8': section.section_name.upper()}
    columns = _day_columns(s['days'], _JHS_DAY_COLS)
    for d, col in columns.items():
        cells[f'{col}11'] = d.day
    _sf2_rows(cells, males, 13, columns, rows.at(34), 'A', 'B', 'AC', 'AD', 'AE')
    _sf2_rows(cells, females, rows.at(35), columns, rows.at(60), 'A', 'B', 'AC', 'AD', 'AE')
    _sf2_day_totals(cells, people, columns, rows.at(61), 'AC', 'AD')
    cells[f'AC{rows.at(63)}'] = s['month']
    cells[f'AG{rows.at(63)}'] = _fmt(s['school_days'])
    _sf2_summary(cells, rows, s, ('AH', 'AI', 'AJ'), (('enrolment', 65), ('late', 67), ('registered', 69), ('pct_enrolment', 71),
                                                       ('ada', 73), ('pct_attendance', 75), ('consecutive', 77), ('drp', 79),
                                                       ('to', 81), ('ti', 83)))
    cells[f'AD{rows.at(88)}'] = FD.adviser_of(section)
    cells[f'AD{rows.at(92)}'] = info['head']
    return _render(_template('jhs/SF2.xlsx'), cells, rows), _file_name('SF2', section, f'{s["month"]}-{s["year"]}', sy)


def _sf2_rows(cells, people, first, columns, total_row, num_col, name_col, absent_col, tardy_col, remark_col):
    for i, p in enumerate(people):
        r = first + i
        cells[f'{num_col}{r}'] = i + 1
        cells[f'{name_col}{r}'] = p['name']
        for d, col in columns.items():
            if p['marks'].get(d):
                cells[f'{col}{r}'] = p['marks'][d]
        cells[f'{absent_col}{r}'] = p['absent']
        cells[f'{tardy_col}{r}'] = p['tardy']
        cells[f'{remark_col}{r}'] = p['month_note'] or None
    _sf2_day_totals(cells, people, columns, total_row, absent_col, tardy_col)


def _sf2_day_totals(cells, people, columns, row, absent_col, tardy_col):
    """Learners present each day (when the days were marked), and the month's absences and tardiness."""
    if any(p['marks'] for p in people):
        for d, col in columns.items():
            cells[f'{col}{row}'] = _fmt(sum(1 for p in people if p['active'] and p['marks'].get(d) != 'x'))
    cells[f'{absent_col}{row}'] = _fmt(sum(p['absent'] or 0 for p in people))
    cells[f'{tardy_col}{row}'] = _fmt(sum(p['tardy'] or 0 for p in people))


def _sf2_shs(section, sy, month, semester):
    info = FD.school_info(section.school, sy)
    people = FD.learners(section, sy)
    s = _attendance_month(section, sy, month, people, saturdays=True)
    males, females = FD.split_sex(people)
    rows = Rows()
    rows.grow(12, 17, len(males))
    rows.grow(30, 27, len(females))
    cells = {'F3': info['school_name'], 'V3': info['school_id'], 'AF3': info['district'], 'AR3': info['division'],
             'AX3': info['region'], 'F5': _semester_label(semester), 'V5': sy.year_label, 'AH5': _grade_text(section),
             'AV5': _track_strand(section), 'F7': section.section_name.upper(), 'W7': _course(section),
             'AV7': f'{s["month"]} {s["year"]}'}
    columns = _day_columns(s['days'], _SHS_DAY_COLS)
    for d, col in columns.items():
        cells[f'{col}10'] = d.day
    _sf2_rows(cells, males, 12, columns, rows.at(29), 'A', 'C', 'AR', 'AT', 'AV')
    _sf2_rows(cells, females, rows.at(30), columns, rows.at(57), 'A', 'C', 'AR', 'AT', 'AV')
    _sf2_day_totals(cells, people, columns, rows.at(58), 'AR', 'AT')
    cells[f'AR{rows.at(61)}'] = s['month']
    cells[f'AU{rows.at(61)}'] = _fmt(s['school_days'])
    _sf2_summary(cells, rows, s, ('AW', 'AX', 'AY'), (('enrolment', 62), ('late', 63), ('registered', 64), ('pct_enrolment', 65),
                                                       ('ada', 66), ('pct_attendance', 67), ('consecutive', 68), ('drp', 70),
                                                       ('to', 71), ('ti', 72), ('shift_out', 73), ('shift_in', 74)))
    cells[f'AS{rows.at(79)}'] = FD.adviser_of(section)
    cells[f'AS{rows.at(84)}'] = info['head']
    return _render(_template('shs/SHSF-2.xlsx'), cells, rows), _file_name('SF2', section, f'{s["month"]}-{s["year"]}', sy)


# ---------------------------------------------------------------------------------------------
# SF3 Books
# ---------------------------------------------------------------------------------------------

def sf3(section, sy, semester=None):
    info = FD.school_info(section.school, sy)
    people = FD.learners(section, sy, include_left=False)
    males, females = FD.split_sex(people)
    rows = Rows()
    if is_senior(section):
        semester = semester or semester_of(sy)
        classes = [a for a in FD.class_assignments(section, sy) if a.semester_id in (None, getattr(semester, 'id', None))]
        rows.grow(13, 40, len(males))
        rows.grow(54, 38, len(females))
        cells = {'D3': info['school_name'], 'M3': info['school_id'], 'Q3': info['district'], 'Y3': info['division'],
                 'AD3': info['region'], 'D5': _semester_label(semester), 'M5': sy.year_label, 'R5': _grade_text(section),
                 'Y5': _track_strand(section), 'D7': section.section_name.upper(), 'N7': _course(section)}
        for col, a in zip(('D', 'F', 'I', 'K', 'N', 'P', 'R', 'T', 'W', 'Z'), classes):
            cells[f'{col}9'] = a.subject.subject_name
        for i, p in enumerate(males):
            cells[f'B{13 + i}'] = p['name']
        for i, p in enumerate(females):
            cells[f'B{rows.at(54) + i}'] = p['name']
        cells[f'T{rows.at(95)}'] = FD.adviser_of(section)
        return _render(_template('shs/SHSF-3.xlsx'), cells, rows), _file_name('SF3', section, _semester_label(semester), sy)
    classes = FD.class_assignments(section, sy)
    rows.grow(12, 24, len(males))
    rows.grow(37, 23, len(females))
    cells = {'C5': info['school_id'], 'K5': sy.year_label, 'C7': info['school_name'], 'K7': _grade_text(section),
             'N7': section.section_name.upper()}
    for col, a in zip(('D', 'F', 'H', 'J', 'L', 'N', 'P', 'R'), classes):
        cells[f'{col}9'] = a.subject.subject_name
    for i, p in enumerate(males):
        cells.update({f'A{12 + i}': i + 1, f'B{12 + i}': p['name']})
    for i, p in enumerate(females):
        cells.update({f'A{rows.at(37) + i}': i + 1, f'B{rows.at(37) + i}': p['name']})
    cells[f'R{rows.at(64)}'] = FD.adviser_of(section)
    return _render(_template('jhs/SF3.xlsx'), cells, rows), _file_name('SF3', section, sy=sy)


# ---------------------------------------------------------------------------------------------
# SF4 Monthly movement (whole school)
# ---------------------------------------------------------------------------------------------

def _section_month(section, sy, month):
    people = FD.learners(section, sy)
    s = _attendance_month(section, sy, month, people)
    mv = s['movement']
    return {
        'section': section, 'registered': s['registered'], 'ada': s['ada'], 'pct': s['pct_attendance'],
        'drp': [_movement_triplet(mv, 'drp', 0), _movement_triplet(mv, 'drp', 1)],
        'to': [_movement_triplet(mv, 'to', 0), _movement_triplet(mv, 'to', 1)],
        'ti': [_movement_triplet(mv, 'ti', 0), _movement_triplet(mv, 'ti', 1)],
    }


def _movement_cells(cells, row, d, cols):
    """registered, ADA, %, then (before, month, cumulative) for dropped, transferred out, transferred in."""
    groups = [(d['registered'], False), (d['ada'], False), (d['pct'], False)]
    for key in ('drp', 'to', 'ti'):
        before, month = d[key]
        groups += [(before, False), (month, False), (tuple(a + b for a, b in zip(before, month)), False)]
    for i, (values, pct) in enumerate(groups):
        _put3(cells, cols[i * 3:i * 3 + 3], row, values, pct, places=1)      # SF4's columns are narrow


def _sum_month(items):
    total = {'registered': [0, 0, 0], 'present_ada': [0.0, 0.0, 0.0], 'drp': [[0, 0, 0], [0, 0, 0]],
             'to': [[0, 0, 0], [0, 0, 0]], 'ti': [[0, 0, 0], [0, 0, 0]]}
    for d in items:
        for i in range(3):
            total['registered'][i] += d['registered'][i]
            total['present_ada'][i] += d['ada'][i] or 0
            for key in ('drp', 'to', 'ti'):
                for w in range(2):
                    total[key][w][i] += d[key][w][i]
    return {'registered': total['registered'], 'ada': [float(FD.round_half_up(x, 2)) for x in total['present_ada']],
            'pct': [_pct(a, r) for a, r in zip(total['present_ada'], total['registered'])],
            'drp': total['drp'], 'to': total['to'], 'ti': total['ti']}


_COLS = [xlsx_patch.col_letters(n) for n in range(1, 60)]


def sf4(school, sy, month, *, senior=False, semester=None):
    from academics.models import Section
    info = FD.school_info(school, sy)
    year, _ = FD.month_of(sy, month)
    sections = list(Section.objects.filter(school=school, school_year=sy, is_active=True,
                                           grade_level__is_senior_high=senior)
                    .select_related('grade_level', 'adviser', 'strand', 'strand__track')
                    .order_by('grade_level__grade_number', 'section_name'))
    if not sections:
        raise FormUnavailable(f'There is no {"Senior High" if senior else "Junior High"} section in SY {sy.year_label}.')
    data = [_section_month(s, sy, month) for s in sections]
    label = f'{calendar.month_name[month]} {year}'
    if senior:
        return _sf4_shs(info, sy, data, label, semester or semester_of(sy))
    rows = Rows()
    rows.grow(12, 18, len(data))
    cells = {'D5': info['school_id'], 'I5': info['region'], 'N5': info['division'], 'Y5': info['district'],
             'C7': info['school_name'], 'Y7': sy.year_label, 'AJ7': label}
    cols = _COLS[4:40]                                     # E .. AN
    for i, d in enumerate(data):
        r = 12 + i
        cells.update({f'A{r}': d['section'].grade_level.grade_number, f'B{r}': d['section'].section_name,
                      f'C{r}': FD.adviser_of(d['section'])})
        _movement_cells(cells, r, d, cols)
    by_grade = {}
    for d in data:
        by_grade.setdefault(d['section'].grade_level.grade_number, []).append(d)
    for number, row in ((7, 32), (8, 33), (9, 34), (10, 35)):
        if number in by_grade:
            _movement_cells(cells, rows.at(row), _sum_month(by_grade[number]), cols)
    _movement_cells(cells, rows.at(39), _sum_month(data), cols)
    cells[f'AG{rows.at(42)}'] = info['head']
    return _render(_template('jhs/SF4.xlsx'), cells, rows), _file_name('SF4', extra=label, sy=sy)


def _sf4_shs(info, sy, data, label, semester):
    rows = Rows()
    groups = {11: {}, 12: {}}
    for d in data:
        s = d['section']
        key = (s.strand.track.track_code.title() if s.strand_id and s.strand.track_id else '', s.strand.strand_code if s.strand_id else s.section_name)
        groups.setdefault(s.grade_level.grade_number, {}).setdefault(key, []).append(d)
    rows.grow(12, 11, len(groups.get(11, {})))
    rows.grow(24, 11, len(groups.get(12, {})))
    cells = {'C4': info['school_name'], 'P4': info['district'], 'AC4': info['division'], 'AS4': info['region'],
             'C6': info['school_id'], 'P6': _semester_label(semester), 'AF6': sy.year_label, 'AW6': label}
    cols = _COLS[2:38]                                     # C .. AL
    for grade, first, total_row in ((11, 12, 23), (12, 24, 35)):
        start = rows.at(first)
        for i, ((track, strand), items) in enumerate(sorted(groups.get(grade, {}).items())):
            cells.update({f'A{start + i}': track, f'B{start + i}': strand})
            _movement_cells(cells, start + i, _sum_month(items), cols)
        if groups.get(grade):
            _movement_cells(cells, rows.at(total_row), _sum_month([d for v in groups[grade].values() for d in v]), cols)
    _movement_cells(cells, rows.at(36), _sum_month(data), cols)
    cells[f'AA{rows.at(41)}'] = info['head']
    return _render(_template('shs/SHSF-4.xlsx'), cells, rows), _file_name('SF4-SHS', extra=label, sy=sy)


# ---------------------------------------------------------------------------------------------
# SF5 Promotion (Grades 7 to 10), SF5A / SF5B (Senior High)
# ---------------------------------------------------------------------------------------------

def _progress_counts(people):
    """Learners per descriptor of their general average, (male, female, total)."""
    bands = {}
    for low, name in FD.DESCRIPTOR_BANDS:
        bands[name] = _counts(people, lambda p, low=low, name=name: p.get('general_average') is not None
                              and FD.descriptor(p['general_average']) == name)
    return bands


def _general_average_text(p):
    """Whole numbers for non-honor learners; honors (90 and up) with three decimals (SF5 heading)."""
    if p.get('general_average') is None:
        return None
    if p['general_average'] >= 90 and p.get('general_average_exact') is not None:
        return f'{p["general_average_exact"]:.3f}'
    return str(p['general_average'])


def sf5(section, sy, semester=None):
    if is_senior(section):
        return sf5a(section, sy, semester or semester_of(sy))
    info = FD.school_info(section.school, sy)
    people = [p for p in FD.learners(section, sy) if p['status'] not in FD.LEFT]     # no dropouts or transfers (D.O. 4, 2014)
    FD.jhs_record(section, sy, people)
    males, females = FD.split_sex(people)
    rows = Rows()
    rows.grow(13, 20, len(males))
    rows.grow(34, 26, len(females))
    cells = {'C3': info['region'], 'E3': info['division'], 'J3': info['district'], 'C5': info['school_id'],
             'G5': sy.year_label, 'J5': 'K to 12 BEC', 'C7': info['school_name'], 'J7': _grade_text(section),
             'M7': section.section_name.upper()}

    def learner(p, r):
        cells.update({f'A{r}': p['lrn'], f'B{r}': p['name'], f'F{r}': _general_average_text(p), f'G{r}': p['action'] or None,
                      f'I{r}': ', '.join(FD.AREA_SHORT[k] for k in p['failed_keys']) or None})
    for i, p in enumerate(males):
        learner(p, 13 + i)
    for i, p in enumerate(females):
        learner(p, rows.at(34) + i)
    cells[f'A{rows.at(33)}'] = _fmt(len(males))
    cells[f'A{rows.at(60)}'] = _fmt(len(females))
    cells[f'A{rows.at(61)}'] = _fmt(len(people))
    for row, action in ((15, 'PROMOTED'), (17, 'CONDITIONAL'), (19, 'RETAINED')):
        _put3(cells, ('M', 'N', 'O'), row, _counts(people, lambda p, action=action: p['action'] == action))
    bands = _progress_counts(people)
    for row, name in ((24, 'Did Not Meet Expectations'), (26, 'Fairly Satisfactory'), (28, 'Satisfactory'),
                      (30, 'Very Satisfactory'), (32, 'Outstanding')):
        _put3(cells, ('M', 'N', 'O'), row, bands[name])
    cells['L36'] = FD.adviser_of(section)
    cells['L41'] = info['head']
    return _render(_template('jhs/SF5.xlsx'), cells, rows), _file_name('SF5', section, sy=sy)


def _year_status(section, sy, people, semester):
    """Regular / Irregular at the end of the year: both semesters complete. Needs the first semester's status."""
    first = semester_of(sy, 1)
    earlier = {p['enrollment'].id: p for p in FD.shs_semester(section, sy, first, [dict(p) for p in people])['people']} if first else {}
    for p in people:
        one = earlier.get(p['enrollment'].id)
        p['first_status'] = one['semester_status'] if one else ''
        if p['semester_status'] and one and one['semester_status']:
            p['year_status'] = 'Regular' if p['semester_complete'] and one['semester_complete'] else 'Irregular'
        else:
            p['year_status'] = ''


def _back_subjects_text(p):
    names = ', '.join(p['back_subjects'])
    if len(names) <= 48:
        return names or None
    codes = [s['subject'].subject_code for s in p['subjects'] if s['subject'].subject_name in p['back_subjects']]
    return ', '.join(codes)


def sf5a(section, sy, semester):
    if not semester:
        raise FormUnavailable(f'SY {sy.year_label} has no semesters yet, so there is no end-of-semester status to report.')
    info = FD.school_info(section.school, sy)
    people = [p for p in FD.learners(section, sy) if p['status'] not in FD.LEFT]
    FD.shs_semester(section, sy, semester, people)
    second = semester.semester_number == 2
    if second:
        _year_status(section, sy, people, semester)
    males, females = FD.split_sex(people)
    rows = Rows()
    rows.grow(13, 31, len(males))
    rows.grow(45, 22, len(females))
    cells = {'F3': info['school_name'], 'M3': info['school_id'], 'O3': info['district'], 'R3': info['division'],
             'U3': info['region'], 'E5': _semester_label(semester), 'L5': sy.year_label, 'O5': _grade_text(section),
             'R5': section.section_name.upper(), 'E7': _track_strand(section), 'P7': _course(section)}
    styles = {}

    def learner(p, i, r):
        cells.update({f'B{r}': i + 1, f'C{r}': p['lrn'], f'D{r}': p['name'], f'J{r}': _back_subjects_text(p),
                      f'N{r}': p['semester_status'] or None, f'O{r}': p.get('year_status') or None})
        styles.update({f'N{r}': 'N15', f'O{r}': 'O15'})   # the template's status cells, some of them in red
    for i, p in enumerate(males):
        learner(p, i, 13 + i)
    for i, p in enumerate(females):
        learner(p, i, rows.at(45) + i)
    tables = [(21 if second else 15, 'semester_status')]
    if second:
        tables.append((15, 'first_status'))
    for top, key in tables:
        for offset, test in ((0, lambda p, key=key: p.get(key) == 'Complete'), (1, lambda p, key=key: p.get(key) == 'Incomplete'),
                             (2, lambda p, key=key: bool(p.get(key)))):
            _put3(cells, ('R', 'S', 'T'), top + offset, _counts(people, test))
    if second:
        for offset, test in ((0, lambda p: p.get('year_status') == 'Regular'), (1, lambda p: p.get('year_status') == 'Irregular'),
                             (2, lambda p: bool(p.get('year_status')))):
            _put3(cells, ('R', 'S', 'T'), 27 + offset, _counts(people, test))
    cells[f'Q{rows.at(52)}'] = FD.adviser_of(section)
    cells[f'Q{rows.at(59)}'] = info['head']
    path = _template('shs/SHSF-5A.xlsx')
    return (_render(path, cells, rows, _styles_like(path, styles)),
            _file_name('SF5A', section, _semester_label(semester), sy))


def sf5b(section, sy, semester=None):
    """Grade 12 learners who completed every subject of both semesters of the school year."""
    from enrollment.models import Enrollment
    if section.grade_level.grade_number != 12:
        raise FormUnavailable('SF5B lists Grade 12 learners who completed Senior High; choose a Grade 12 section.')
    info = FD.school_info(section.school, sy)
    people = [p for p in FD.learners(section, sy) if p['active']]
    sems = semesters(sy)
    status = {}
    for sem in sems:
        for p in FD.shs_semester(section, sy, sem, [dict(p) for p in people])['people']:
            status.setdefault(p['enrollment'].id, []).append(p['semester_complete'])
    done = [p for p in people if sems and all(status.get(p['enrollment'].id, [False]))]
    grade11 = set(Enrollment.objects.filter(student__in=[p['student'] for p in done], school_year__year_start=sy.year_start - 1,
                                            grade_level_at_entry__grade_number=11).values_list('student_id', flat=True))
    for p in done:
        p['two_years'] = 'Y' if p['student'].id in grade11 else ''
    males, females = FD.split_sex(done)
    rows = Rows()
    rows.grow(15, 29, len(males))
    rows.grow(45, 21, len(females))
    semester = semester or (sems[-1] if sems else None)
    cells = {'E3': info['school_name'], 'Q3': info['school_id'], 'T3': info['district'], 'X3': info['division'],
             'Z3': info['region'], 'E5': _semester_label(semester), 'Q5': sy.year_label, 'T5': section.section_name.upper(),
             'E7': _track_strand(section), 'T7': _course(section)}
    for block, first in ((males, 15), (females, rows.at(45))):
        for i, p in enumerate(block):
            r = first + i
            cells.update({f'A{r}': i + 1, f'B{r}': p['lrn'], f'C{r}': p['name'], f'S{r}': p['two_years'] or None})
    _put3(cells, ('X', 'Y', 'Z'), 17, _counts(done, lambda p: p['two_years'] == 'Y'))
    _put3(cells, ('X', 'Y', 'Z'), 21, _counts(done, lambda p: p['two_years'] != 'Y'))
    _put3(cells, ('X', 'Y', 'Z'), 25, _counts(done))
    cells[f'W{rows.at(47)}'] = FD.adviser_of(section)
    cells[f'W{rows.at(54)}'] = info['head']
    return _render(_template('shs/SHSF-5B.xlsx'), cells, rows), _file_name('SF5B', section, sy=sy)


# ---------------------------------------------------------------------------------------------
# SF6 Summarized promotion (whole school)
# ---------------------------------------------------------------------------------------------

def sf6(school, sy, *, senior=False, semester=None):
    from academics.models import Section
    info = FD.school_info(school, sy)
    sections = list(Section.objects.filter(school=school, school_year=sy, is_active=True, grade_level__is_senior_high=senior)
                    .select_related('grade_level', 'strand', 'strand__track').order_by('grade_level__grade_number', 'section_name'))
    if not sections:
        raise FormUnavailable(f'There is no {"Senior High" if senior else "Junior High"} section in SY {sy.year_label}.')
    if senior:
        return _sf6_shs(info, sy, sections, semester or semester_of(sy))
    by_grade = {}
    for s in sections:
        people = [p for p in FD.learners(s, sy) if p['status'] not in FD.LEFT]
        FD.jhs_record(s, sy, people)
        by_grade.setdefault(s.grade_level.grade_number, []).extend(people)
    cells = {'E5': info['school_id'], 'J5': info['region'], 'O5': info['division'], 'D7': info['school_name'],
             'O7': info['district'], 'V7': sy.year_label}
    columns = {7: ('C', 'D', 'E'), 8: ('F', 'G', 'H'), 9: ('I', 'J', 'K'), 10: ('L', 'M', 'N'), 11: ('O', 'P', 'Q'), 12: ('R', 'S', 'T')}
    everyone = [p for v in by_grade.values() for p in v]
    groups = [(cols, by_grade[g]) for g, cols in columns.items() if g in by_grade] + [(('U', 'V', 'W'), everyone)]
    for cols, people in groups:
        for row, action in ((11, 'PROMOTED'), (12, 'CONDITIONAL'), (13, 'RETAINED')):
            _put3(cells, cols, row, _counts(people, lambda p, action=action: p['action'] == action))
        bands = _progress_counts(people)
        for row, name in ((15, 'Did Not Meet Expectations'), (17, 'Fairly Satisfactory'), (19, 'Satisfactory'),
                          (22, 'Very Satisfactory'), (24, 'Outstanding')):
            _put3(cells, cols, row, bands[name])
        _put3(cells, cols, 26, _counts(people, lambda p: p.get('general_average') is not None))
    cells['D29'] = info['head']
    return _render(_template('jhs/SF6.xlsx'), cells), _file_name('SF6', sy=sy)


def _sf6_shs(info, sy, sections, semester):
    second = bool(semester) and semester.semester_number == 2
    groups = {11: {}, 12: {}}
    for s in sections:
        people = [p for p in FD.learners(s, sy) if p['status'] not in FD.LEFT]
        FD.shs_semester(s, sy, semester, people)
        if second:
            _year_status(s, sy, people, semester)
        key = (s.strand.track.track_name if s.strand_id and s.strand.track_id else '') + \
            (f' - {s.strand.strand_code}' if s.strand_id else '')
        groups.setdefault(s.grade_level.grade_number, {}).setdefault(key.strip(' -') or s.section_name, []).extend(people)
    rows = Rows()
    rows.grow(13, 8, len(groups.get(11, {})))
    rows.grow(24, 9, len(groups.get(12, {})))
    cells = {'D3': info['school_name'], 'I3': info['school_id'], 'L3': info['district'], 'P3': info['division'],
             'T3': info['region'], 'D5': _semester_label(semester), 'I5': sy.year_label}

    def line(row, people):
        _put3(cells, ('D', 'E', 'F'), row, _counts(people, lambda p: p['semester_status'] == 'Complete'))
        _put3(cells, ('G', 'H', 'I'), row, _counts(people, lambda p: p['semester_status'] == 'Incomplete'))
        _put3(cells, ('J', 'K', 'L'), row, _counts(people, lambda p: bool(p['semester_status'])))
        if second:
            _put3(cells, ('M', 'N', 'O'), row, _counts(people, lambda p: p.get('year_status') == 'Regular'))
            _put3(cells, ('P', 'Q', 'R'), row, _counts(people, lambda p: p.get('year_status') == 'Irregular'))
            _put3(cells, ('S', 'T', 'U'), row, _counts(people, lambda p: bool(p.get('year_status'))))
    everyone = []
    for grade, first, subtotal in ((11, 13, 21), (12, 24, 33)):
        start, members = rows.at(first), []
        for i, (label, people) in enumerate(sorted(groups.get(grade, {}).items())):
            cells[f'A{start + i}'] = label
            line(start + i, people)
            members += people
        if members:
            line(rows.at(subtotal), members)
        everyone += members
    line(rows.at(34), everyone)
    cells[f'D{rows.at(36)}'] = info['head']
    return _render(_template('shs/SHSF-6.xlsx'), cells, rows), _file_name('SF6-SHS', extra=_semester_label(semester), sy=sy)


# ---------------------------------------------------------------------------------------------
# SF7 Personnel (whole school)
# ---------------------------------------------------------------------------------------------

_SF7_BLOCKS = [(20, 28), (29, 36), (37, 43), (44, 50), (51, 57), (58, 64), (65, 71)]


def _staff_for(staff, senior):
    """Personnel of one level: everyone not teaching, and teachers with classes at that level (or none)."""
    out = []
    for s in staff:
        here = [c for c in s['classes'] if c['assignment'].section.grade_level.is_senior_high == senior]
        if s['classes'] and not here and s['profile'].role == 'teacher':
            continue
        other = sum(c['minutes'] for c in s['classes'] if c not in here)
        out.append(dict(s, classes=here, minutes_week=sum(c['minutes'] for c in here), other_minutes=other))
    return out


def _position_counts(staff):
    """(teaching, non-teaching) [(position, count)], highest position first, as the form lists them."""
    teaching, other = {}, {}
    order = {}
    for i, s in enumerate(staff):
        bucket = teaching if s['teaching_role'] else other
        title = s['position'] or 'Unspecified'
        bucket[title] = bucket.get(title, 0) + 1
        order.setdefault(title, i)
    return sorted(teaching.items(), key=lambda kv: order[kv[0]]), sorted(other.items(), key=lambda kv: order[kv[0]])


def _section_short(a):
    return f'{a.section.grade_level.grade_number} - {a.section.section_name}'


def sf7(school, sy, *, senior=False, semester=None):
    info = FD.school_info(school, sy)
    if senior:
        return _sf7_shs(info, school, sy, semester or semester_of(sy))
    staff = _staff_for(FD.personnel(school, sy), senior=False)
    if not staff:
        raise FormUnavailable('The school has no personnel accounts yet.')
    teaching, other = _position_counts(staff)
    rows = Rows()
    rows.grow(12, 5, max(len(teaching), len(other)))
    extra = max(0, len(staff) - len(_SF7_BLOCKS))
    rows.repeat(65, 71, extra)
    blocks = [(rows.at(a), rows.at(b)) for a, b in _SF7_BLOCKS]
    blocks += [(rows.at(71) + 1 + k * 7, rows.at(71) + 7 + k * 7) for k in range(extra)]
    cells = {'D5': info['school_id'], 'H5': info['region'], 'K5': info['division'], 'D7': info['school_name'],
             'K7': info['district'], 'R7': sy.year_label}
    for i, (title, n) in enumerate(teaching):
        cells.update({f'A{12 + i}': title, f'C{12 + i}': _fmt(n)})
    for i, (title, n) in enumerate(other):
        cells.update({f'F{12 + i}': title, f'I{12 + i}': _fmt(n)})
    merges = [f'{a}{12 + i}:{b}{12 + i}' for i in range(max(5, len(teaching), len(other)))
              for a, b in (('A', 'B'), ('C', 'D'), ('F', 'H'), ('K', 'M'), ('N', 'O'), ('P', 'Q'))]   # one template row is not merged
    for person, (first, last) in zip(staff, blocks):
        cells.update({f'A{first}': person['employee_no'], f'B{first}': person['name'], f'D{first}': person['fund'],
                      f'F{first}': person['position'], f'G{first}': person['appointment'], f'H{first}': person['degree'],
                      f'I{first}': person['major'], f'K{first}': person['minor'],
                      f'R{first}': f'SHS load: {person["other_minutes"]} min/week' if person['other_minutes'] else None})
        lines = [(f'{c["assignment"].subject.subject_name} ({_section_short(c["assignment"])})', c['minutes'], c['schedules'])
                 for c in person['classes']]
        if person['advisory']:
            lines.append((f'Advisory: {person["advisory"]}', None, []))
        room = last - first                                # the last row is "Ave. Minutes per Day"
        if len(lines) > room:
            lines = lines[:room - 1] + [('; '.join(l[0] for l in lines[room - 1:]), sum(l[1] or 0 for l in lines[room - 1:]), [])]
        for j, (label, minutes, schedules) in enumerate(lines):
            r = first + j
            cells[f'M{r}'] = label
            if schedules:
                sch = schedules[0]
                days = ''.join(sorted({x.day_of_week[:2].upper() if x.day_of_week else '' for x in schedules}))
                cells.update({f'N{r}': days or None, f'O{r}': sch.time_start.strftime('%H:%M') if sch.time_start else None,
                              f'P{r}': sch.time_end.strftime('%H:%M') if sch.time_end else None})
            cells[f'Q{r}'] = minutes or None
        cells[f'Q{last}'] = round(person['minutes_week'] / 5) if person['minutes_week'] else None
    cells[f'Q{rows.at(75)}'] = info['head']
    return _render(_template('jhs/SF7.xlsx'), cells, rows, merges=merges), _file_name('SF7', sy=sy)


def _sf7_shs(info, school, sy, semester):
    staff = _staff_for(FD.personnel(school, sy), senior=True)
    if not staff:
        raise FormUnavailable('The school has no personnel accounts yet.')
    teaching, other = _position_counts(staff)
    size, first_block, slots = 17, 19, 6
    rows = Rows()
    rows.grow(12, 4, max(len(teaching), len(other)))
    rows.repeat(first_block + (slots - 1) * size, first_block + slots * size - 1, max(0, len(staff) - slots))
    cells = {'C5': info['school_name'], 'H5': info['school_id'], 'J5': info['district'], 'P5': info['division'],
             'T5': info['region'], 'C7': _semester_label(semester), 'I7': sy.year_label}
    for i, (title, n) in enumerate(teaching):
        cells.update({f'A{12 + i}': title, f'C{12 + i}': _fmt(n)})
    for i, (title, n) in enumerate(other):
        cells.update({f'F{12 + i}': title, f'I{12 + i}': _fmt(n)})
    merges = [f'{a}{12 + i}:{b}{12 + i}' for i in range(max(4, len(teaching), len(other)))
              for a, b in (('A', 'B'), ('C', 'D'), ('F', 'H'), ('K', 'N'), ('O', 'P'), ('Q', 'R'))]
    number = semester.semester_number if semester else 1
    styles = {}
    base = rows.at(first_block)
    for k, person in enumerate(staff):
        top = base + k * size
        cells.update({f'A{top}': person['employee_no'], f'B{top}': person['name'], f'D{top}': person['fund'],
                      f'F{top}': person['position'], f'G{top}': person['appointment'], f'H{top}': person['degree'],
                      f'I{top}': person['major'], f'K{top}': person['minor'],
                      f'S{top}': f'JHS load: {person["other_minutes"]} min/week' if person['other_minutes'] else None})
        for start, sem in ((top + 1, 1), (top + 8, 2)):
            # the form is for one semester: whole-year classes go under it; the other lists only its own classes
            mine = [c for c in person['classes'] if (c['assignment'].semester.semester_number == sem if c['assignment'].semester
                                                     else sem == number)]
            for j, c in enumerate(mine[:6]):
                a = c['assignment']
                cells.update({f'M{start + j}': a.subject.subject_name, f'N{start + j}': _section_short(a),
                              f'R{start + j}': c['minutes'] or None})
            styles.update({f'M{start + 5}': f'M{first_block + 4}', f'N{start + 5}': f'N{first_block + 4}'})   # the sixth line is red
        cells[f'N{top + 14}'] = person['advisory'].replace('Grade ', '') if person['advisory'] else None
        cells[f'R{top + 16}'] = round(person['minutes_week'] / 5) if person['minutes_week'] else None
    cells[f'P{rows.at(127)}'] = info['head']
    path = _template('shs/SHSF-7.xlsx')
    return (_render(path, cells, rows, _styles_like(path, styles), merges),
            _file_name('SF7-SHS', extra=_semester_label(semester), sy=sy))


# ---------------------------------------------------------------------------------------------
# Summary of final grades (Grades 7 to 10) and MAPEH final grades
# ---------------------------------------------------------------------------------------------

_SUMMARY_COLS = {'FILIPINO': 'F', 'ENGLISH': 'K', 'MATH': 'P', 'SCIENCE': 'U', 'AP': 'Z', 'TLE': 'AE', 'MAPEH': 'AJ', 'ESP': 'AO'}


def summary_final_grades(section, sy):
    """The section's quarterly grade in every learning area; the template's own formulas give the final
    grades and the general average. Returns ((bytes, file name), record)."""
    if is_senior(section):
        raise FormUnavailable('The summary of final grades is for Grades 7 to 10. Senior High uses SF5A.')
    info = FD.school_info(section.school, sy)
    people = FD.learners(section, sy, include_left=False)
    record = FD.jhs_record(section, sy, people)
    males, females = FD.split_sex(people)
    if len(males) > 50 or len(females) > 50:
        raise FormUnavailable('The summary of final grades has room for 50 male and 50 female learners.')
    cells = {'G3': info['region_label'] or None, 'U3': info['division'] or None, 'AK3': sy.year_label, 'G5': info['school_name'],
             'U5': info['school_id'], 'AK5': f'{section.grade_level.grade_name} - {section.section_name}'.upper()}
    for block, first in ((males, 11), (females, 62)):
        for i, p in enumerate(block):
            r = first + i
            cells[f'B{r}'] = p['short']
            for key, col in _SUMMARY_COLS.items():
                start = xlsx_patch.col_number(col)
                for q, value in enumerate(p['areas'][key]['quarters'][:4]):
                    cells[f'{xlsx_patch.col_letters(start + q)}{r}'] = value
    data = (ECR_TEMPLATES / 'SUMMARY_FINAL_GRADES.xlsx').read_bytes()
    content = xlsx_patch.patch(data, {'SUMMARY - FINAL GRADES': cells},
                               merges={'SUMMARY - FINAL GRADES': ['G3:K3', 'U3:Z3', 'AK3:AP3', 'G5:P5', 'U5:Z5', 'AK5:AP5']})
    return (content, _file_name('Summary-of-Final-Grades', section, sy=sy)), record


def mapeh_final_grades(assignment):
    """One MAPEH class: its quarterly MAPEH grade per quarter; the template computes the final grade."""
    from academics.models import Quarter
    section, sy = assignment.section, assignment.school_year
    info = FD.school_info(section.school, sy)
    people = FD.learners(section, sy, include_left=False)
    periods = list(Quarter.objects.filter(school_year=sy).order_by('quarter_number'))
    grades = FD.quarter_grades([p['enrollment'].id for p in people], [assignment.subject_id], periods)
    males, females = FD.split_sex(people)
    if len(males) > 50 or len(females) > 50:
        raise FormUnavailable('The MAPEH final grades sheet has room for 50 male and 50 female learners.')
    cells = {'G5': info['region_label'] or None, 'O5': info['division'] or None, 'G6': info['school_name'], 'W6': info['school_id'],
             'K8': f'{section.grade_level.grade_name} - {section.section_name}'.upper(), 'W8': sy.year_label,
             'K9': FD.person_name(assignment.teacher)}
    for block, first in ((males, 13), (females, 64)):
        for i, p in enumerate(block):
            r = first + i
            cells[f'B{r}'] = p['short']
            for col, q in zip(('F', 'J', 'N', 'R'), periods[:4]):
                cells[f'{col}{r}'] = grades.get((p['enrollment'].id, assignment.subject_id, q.id))
    content = xlsx_patch.patch((ECR_TEMPLATES / 'MAPEH_FINAL.xlsx').read_bytes(), {'MAPEH FINAL GRADES': cells})
    return content, _file_name('MAPEH-Final-Grades', section, sy=sy)


# ---------------------------------------------------------------------------------------------
# one entry point for the pages
# ---------------------------------------------------------------------------------------------

def build(code, *, school, sy, section=None, month=None, semester=None, senior=False):
    """(bytes, file name) of a form. Raises FormUnavailable with a message for the registrar."""
    if code not in FORMS:
        raise FormUnavailable('Unknown school form.')
    spec = FORMS[code]
    if spec['scope'] == 'section' and section is None:
        raise FormUnavailable('Choose a section.')
    if spec.get('month') and not month:
        raise FormUnavailable('Choose the month.')
    if spec.get('jhs') and section is not None and is_senior(section):
        raise FormUnavailable(f'{FORMS[code]["title"]} is for Grades 7 to 10. Senior High sections use SF5A.')
    if spec.get('shs') and section is not None and not is_senior(section):
        raise FormUnavailable(f'{FORMS[code]["title"]} is for Senior High sections.')
    if code == 'SF1':
        return sf1(section, sy, semester)
    if code == 'SF2':
        return sf2(section, sy, int(month), semester)
    if code == 'SF3':
        return sf3(section, sy, semester)
    if code == 'SF4':
        return sf4(school, sy, int(month), senior=senior, semester=semester)
    if code == 'SF5':
        return sf5(section, sy, semester)
    if code == 'SF5A':
        return sf5a(section, sy, semester or semester_of(sy))
    if code == 'SF5B':
        return sf5b(section, sy, semester)
    if code == 'SF6':
        return sf6(school, sy, senior=senior, semester=semester)
    if code == 'SF7':
        return sf7(school, sy, senior=senior, semester=semester)
    if code == 'SUMMARY':
        return summary_final_grades(section, sy)[0]
    raise FormUnavailable('Unknown school form.')
