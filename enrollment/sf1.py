"""DepEd School Form 1 (School Register) reader, for enrolling a section from its SF1.

The registrar exports SF1 from LIS for each section: the Junior High register (Grades 7 to 10,
.xls or .xlsx) or the Senior High register (SF1-SHS, Grades 11 and 12, which adds the semester,
the track and strand and the course). This module reads either. It finds the columns from their
headers instead of fixed cell positions, reads the school details in the form's header, and
returns one row per learner with everything the register holds: LRN, name, sex, birth date,
address, parents, guardian, contact number and the REMARKS indicators (T/I, T/O, DRP, ...).

Nothing is saved here. The registrar reviews the result first (enrollment.sf1_import).
"""
import io
import re
import unicodedata
from datetime import date, datetime, timedelta

MAX_UPLOAD_BYTES = 10 * 1024 * 1024

# REMARKS indicators of SF1 (legend on the form) and what they mean for the enrollment
INDICATORS = {
    'T/O': 'Transferred out', 'T/I': 'Transferred in', 'DRP': 'Dropped', 'LE': 'Late enrollment',
    'CCT': 'CCT (4Ps) recipient', 'B/A': 'Balik-Aral', 'LWD': 'Learner with disability',
    'LWE': 'Learner with exceptionality', 'ACL': 'Accelerated',
}
_INDICATOR = re.compile(r'(?<![A-Z/])(T/O|T/I|DRP|LE|CCT|B/A|LWD|LWE|ACL)(?![A-Z/])', re.I)
_EXTENSIONS = {'JR': 'Jr.', 'JR.': 'Jr.', 'SR': 'Sr.', 'SR.': 'Sr.', 'II': 'II', 'III': 'III', 'IV': 'IV', 'V': 'V', 'VI': 'VI'}
_GRADE_WORDS = {'SEVEN': 7, 'EIGHT': 8, 'NINE': 9, 'TEN': 10, 'ELEVEN': 11, 'TWELVE': 12}
# header labels of the form (upper case, single spaces) and the meta field each one names
_LABELS = (
    ('SCHOOL ID', 'school_id'), ('SCHOOL NAME', 'school_name'), ('NAME OF SCHOOL', 'school_name'),
    ('SCHOOL YEAR', 'school_year'), ('GRADE LEVEL', 'grade_level'), ('SECTION', 'section'),
    ('REGION', 'region'), ('DIVISION', 'division'), ('DISTRICT', 'district'), ('SEMESTER', 'semester'),
    ('TRACK AND STRAND', 'track_strand'), ('COURSE', 'course'),
)


class SF1Error(Exception):
    """The file cannot be used at all (not an SF1, unreadable, no learners)."""


# ---------------------------------------------------------------------------------------------
# reading the workbook into a grid of values
# ---------------------------------------------------------------------------------------------

def _norm(value):
    """Upper-case text with single spaces and no accents, for comparing labels."""
    text = unicodedata.normalize('NFKD', str(value or '')).encode('ascii', 'ignore').decode()
    return re.sub(r'\s+', ' ', text).strip().upper()


def _xls_grid(data):
    import xlrd
    try:
        book = xlrd.open_workbook(file_contents=data)
    except Exception:
        raise SF1Error('The .xls file could not be opened. Open it in Excel, save it again, and retry.')
    sheets = []
    for sh in book.sheets():
        grid = [[None]]
        for r in range(sh.nrows):
            row = [None]
            for c in range(sh.ncols):
                cell = sh.cell(r, c)
                if cell.ctype == xlrd.XL_CELL_DATE:
                    try:
                        row.append(xlrd.xldate_as_datetime(cell.value, book.datemode))
                    except Exception:
                        row.append(cell.value)
                elif cell.ctype in (xlrd.XL_CELL_EMPTY, xlrd.XL_CELL_BLANK):
                    row.append(None)
                else:
                    row.append(cell.value)
            grid.append(row)
        sheets.append((sh.name, grid))
    return sheets


def _xlsx_grid(data):
    from openpyxl import load_workbook
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise SF1Error('The .xlsx file could not be opened. Open it in Excel, save it again, and retry.')
    sheets = []
    try:
        for ws in wb.worksheets:
            grid = [[None]]
            for row in ws.iter_rows(values_only=True):
                grid.append([None] + list(row))
            sheets.append((ws.title, grid))
    finally:
        wb.close()
    return sheets


def _cell(grid, r, c):
    try:
        return grid[r][c]
    except IndexError:
        return None


def _find_header(grid):
    """(row, {field: column}) of the learner table header, or None. The header has LRN and NAME."""
    for r in range(1, min(len(grid), 40)):
        cells = {c: _norm(v) for c, v in enumerate(grid[r]) if v not in (None, '')}
        if any(t == 'LRN' for t in cells.values()) and any(t.startswith('NAME') for t in cells.values()):
            return r
    return None


def _columns(grid, header):
    """Which column holds what, from the header row and the row under it (address parts, parents, guardian)."""
    cols = {}
    top = {c: _norm(v) for c, v in enumerate(grid[header]) if v not in (None, '')}
    sub = {c: _norm(v) for c, v in enumerate(grid[header + 1]) if v not in (None, '')} if header + 1 < len(grid) else {}
    for c, t in top.items():
        if t == 'LRN':
            cols['lrn'] = c
        elif t.startswith('NAME'):
            cols['name'] = c
        elif t.startswith('SEX'):
            cols['sex'] = c
        elif 'BIRTH DATE' in t or 'BIRTHDATE' in t:
            cols['birth_date'] = c
        elif t.startswith('AGE'):
            cols['age'] = c
        elif 'BIRTH PLACE' in t or 'BIRTHPLACE' in t:
            cols['birth_place'] = c
        elif 'MOTHER TONGUE' in t:
            cols['mother_tongue'] = c
        elif t.startswith('IP') or 'ETHNIC' in t:
            cols['ethnic'] = c
        elif 'RELIGION' in t or 'RELIGIOUS' in t:
            cols['religion'] = c
        elif 'CONTACT' in t:
            cols['contact'] = c
        elif t.startswith('REMARKS'):
            cols['remarks'] = c
        elif t.startswith('GUARDIAN'):
            cols['_guardian_start'] = c
    for c, t in sub.items():
        if t.startswith('HOUSE'):
            cols['street'] = c
        elif t.startswith('BARANGAY'):
            cols['barangay'] = c
        elif 'MUNICIPALITY' in t or t.startswith('CITY'):
            cols['city'] = c
        elif t.startswith('PROVINCE'):
            cols['province'] = c
        elif t.startswith('FATHER'):
            cols['father'] = c
        elif t.startswith('MOTHER'):
            cols['mother'] = c
        elif t.startswith('NAME') and c >= cols.get('_guardian_start', 0):
            cols['guardian'] = c
        elif t.startswith('RELATION'):
            cols['relationship'] = c
    cols.pop('_guardian_start', None)
    return cols


def _label_field(text):
    for label, field in _LABELS:
        if text == label or text.startswith(label + ' ') or text.startswith(label + ':') or text.startswith(label + '('):
            return label, field
    return None, None


def _meta(grid, header):
    """The school details written above the learner table: each label's value is the next cell to its right."""
    meta = {}
    for r in range(1, header):
        row = grid[r]
        for c, value in enumerate(row):
            text = _norm(value)
            if not text:
                continue
            label, field = _label_field(text)
            if not field or field in meta:
                continue
            rest = str(value).strip()[len(label):].strip(' :') if text != label else ''
            if field == 'course' and 'TVL' in text:
                rest = ''                                  # "Course (For TVL Only)" is the whole label
            if rest and field in ('region',):              # "Region VIII" holds its own value
                meta[field] = rest
                continue
            for c2 in range(c + 1, min(len(row), c + 25)):
                v = row[c2]
                if v in (None, ''):
                    continue
                if _label_field(_norm(v))[1]:
                    break                                  # the next label: this one was left empty
                meta[field] = _text(v)
                break
    return meta


# ---------------------------------------------------------------------------------------------
# one learner row
# ---------------------------------------------------------------------------------------------

def _text(value):
    if value is None:
        return ''
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, (datetime, date)):
        return value.strftime('%m/%d/%Y')
    text = str(value).strip()
    return '' if text in ('0', '-', 'N/A', 'n/a', 'NA', 'None') else re.sub(r'\s+', ' ', text)


def _lrn(*values):
    for v in values:
        if v is None:
            continue
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        digits = re.sub(r'\D', '', str(v))
        if len(digits) == 12:
            return digits
    return ''


def split_name(raw):
    """'LAST, FIRST [EXT], MIDDLE' or 'LAST, FIRST, EXT, MIDDLE' -> (last, first, middle, ext), title-cased."""
    text = re.sub(r'\s+', ' ', str(raw or '')).strip().strip(',')
    parts = [p.strip() for p in text.split(',')]
    parts = [p for p in parts if p]
    if not parts:
        return '', '', '', ''
    last = parts[0]
    first, middle, ext = '', '', ''
    rest = parts[1:]
    if rest and _EXTENSIONS.get(rest[-1].upper().replace(' ', '')) and len(rest) >= 2:
        ext = _EXTENSIONS[rest[-1].upper().replace(' ', '')]      # LAST, FIRST, MIDDLE, JR (unusual order)
        rest = rest[:-1]
    if len(rest) >= 3 and _EXTENSIONS.get(rest[1].upper().replace(' ', '')):
        first, ext, middle = rest[0], _EXTENSIONS[rest[1].upper().replace(' ', '')], ' '.join(rest[2:])
    elif len(rest) >= 2:
        first, middle = rest[0], ' '.join(rest[1:])
    elif rest:
        first = rest[0]
    words = first.split()
    if not ext and len(words) > 1 and _EXTENSIONS.get(words[-1].upper()):
        ext, first = _EXTENSIONS[words[-1].upper()], ' '.join(words[:-1])
    if middle and len(middle.replace('.', '')) == 1:
        middle = middle.replace('.', '')                      # an initial only
    return _title(last), _title(first), _title(middle), ext


def _title(text):
    """'DELA CRUZ' -> 'Dela Cruz', keeping particles and Roman numerals readable."""
    def word(w):
        if w.upper() in ('II', 'III', 'IV', 'VI'):
            return w.upper()
        return '-'.join(part[:1].upper() + part[1:].lower() for part in w.split('-'))
    return ' '.join(word(w) for w in str(text).split())


def _sex(value, default=None):
    t = _norm(value)
    if t in ('M', 'MALE'):
        return 'M'
    if t in ('F', 'FEMALE'):
        return 'F'
    return default


def _birth_date(value):
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, (int, float)) and 1 < value < 80000:          # an Excel serial number
        return (datetime(1899, 12, 30) + timedelta(days=float(value))).date()
    text = _text(value)
    for fmt in ('%m/%d/%Y', '%m-%d-%Y', '%Y-%m-%d', '%m/%d/%y', '%B %d, %Y', '%b %d, %Y', '%d-%b-%Y'):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def indicators(remarks):
    """The SF1 REMARKS codes in a remarks text, in the order written: ['T/I', 'CCT']."""
    found = []
    for m in _INDICATOR.finditer(remarks or ''):
        code = m.group(1).upper()
        if code not in found:
            found.append(code)
    return found


def grade_number(text):
    """7 for 'Grade 7', 'G7', '7', 'GRADE SEVEN'; None when unclear."""
    t = _norm(text)
    m = re.search(r'\b(7|8|9|10|11|12)\b', t) or re.search(r'G\s*(7|8|9|10|11|12)\b', t)
    if m:
        return int(m.group(1))
    for word, n in _GRADE_WORDS.items():
        if word in t:
            return n
    return None


# strand codes as LIS and schools write them, most specific first
_STRANDS = (
    ('STEM', r'\bSTEM\b|SCIENCE, TECHNOLOGY, ENGINEERING'), ('HUMSS', r'\bHUMSS\b|HUMANITIES'),
    ('ABM', r'\bABM\b|ACCOUNTANCY, BUSINESS'), ('GAS', r'\bGAS\b|GENERAL ACADEMIC'),
    ('ICT', r'\bICT\b|INFORMATION AND COMMUNICATIONS'), ('HE', r'\bHE\b|HOME ECONOMICS'),
    ('IA', r'\bIA\b|INDUSTRIAL ARTS'), ('AFA', r'\bAFA\b|AGRI-FISHERY|AGRICULTURAL'),
    ('SPORTS', r'\bSPORTS\b'), ('ARTS', r'\bARTS AND DESIGN\b|\bA&D\b'),
)
_TRACKS = (('TVL', r'\bTVL\b|TECHNICAL-VOCATIONAL|TECHPRO|TECHNICAL-PROFESSIONAL'), ('ACADEMIC', r'\bACADEMIC\b'),
           ('SPORTS', r'\bSPORTS\b'), ('ARTS', r'\bARTS AND DESIGN\b'))
_TRACK_OF = {'STEM': 'ACADEMIC', 'HUMSS': 'ACADEMIC', 'ABM': 'ACADEMIC', 'GAS': 'ACADEMIC',
             'ICT': 'TVL', 'HE': 'TVL', 'IA': 'TVL', 'AFA': 'TVL', 'SPORTS': 'SPORTS', 'ARTS': 'ARTS'}


def track_strand(text):
    """('ACADEMIC', 'STEM') from 'ACADEMIC - STEM', 'Academic Track (STEM Strand)', 'TVL-ICT'; codes may be None."""
    t = _norm(text)
    strand = next((code for code, pattern in _STRANDS if re.search(pattern, t)), None)
    track = next((code for code, pattern in _TRACKS if re.search(pattern, t)), None)
    return track or _TRACK_OF.get(strand), strand


# ---------------------------------------------------------------------------------------------
# the whole form
# ---------------------------------------------------------------------------------------------

def _pick_sheet(sheets):
    """The SF1 sheet of a workbook: named like SF1 / SHSF-1 / School Form 1, else the first with the learner table."""
    def is_sf1(name):
        n = _norm(name).replace(' ', '')
        return 'SF1' in n or 'SHSF-1' in n or 'SCHOOLFORM1' in n.replace('(', '').replace(')', '')
    ordered = [s for s in sheets if is_sf1(s[0])] + [s for s in sheets if not is_sf1(s[0])]
    for name, grid in ordered:
        header = _find_header(grid)
        if header:
            return name, grid, header
    return None


def read(uploaded):
    """An SF1 file as {'kind', 'sheet', 'meta', 'rows', 'warnings'}. Raises SF1Error when it cannot be used."""
    name = (getattr(uploaded, 'name', '') or '').lower()
    size = getattr(uploaded, 'size', None)
    if size is not None and size > MAX_UPLOAD_BYTES:
        raise SF1Error('The file is larger than 10 MB. An SF1 is usually well under 1 MB.')
    data = uploaded.read()
    if name.endswith('.xls') or data[:8] == b'\xd0\xcf\x11\xe0\xa1\xb1\x1a\xe1':
        sheets = _xls_grid(data)
    elif name.endswith(('.xlsx', '.xlsm')) or data[:2] == b'PK':
        sheets = _xlsx_grid(data)
    else:
        raise SF1Error('Upload the SF1 as an Excel file (.xls or .xlsx), as LIS exports it.')

    picked = _pick_sheet(sheets)
    if not picked:
        raise SF1Error('This file has no learner table with LRN and NAME columns, so it is not a School Form 1.')
    sheet, grid, header = picked
    cols = _columns(grid, header)
    if 'name' not in cols:
        raise SF1Error('The NAME column of the register could not be found.')
    meta = _meta(grid, header)
    title = ' '.join(_norm(v) for r in range(1, min(header, 4)) for v in grid[r] if v)
    senior = 'SENIOR HIGH' in title or 'SHS' in title or 'track_strand' in meta or 'semester' in meta
    meta['grade_number'] = grade_number(meta.get('grade_level', ''))
    if meta['grade_number'] in (11, 12):
        senior = True
    elif meta['grade_number'] in (7, 8, 9, 10):
        senior = False
    if senior:
        meta['track'], meta['strand'] = track_strand(meta.get('track_strand', ''))

    rows, warnings, block_sex = [], [], None
    first_data = header + 2 if header + 1 < len(grid) and any(
        _norm(v).startswith(('HOUSE', 'BARANGAY', 'FATHER', 'NAME')) for v in grid[header + 1] if v) else header + 1
    for r in range(first_data, len(grid)):
        row = grid[r]
        joined = ' '.join(_norm(v) for v in row if v not in (None, ''))
        if not joined:
            continue
        if joined.startswith(('LIST AND CODE', 'LEGEND', 'INDICATOR', 'PREPARED BY')) or 'LIST AND CODE OF INDICATORS' in joined:
            break
        if 'TOTAL MALE' in joined:
            block_sex = 'F'
            continue
        if 'TOTAL FEMALE' in joined or 'COMBINED' in joined:
            continue
        get = lambda field: _cell(grid, r, cols[field]) if field in cols else None
        raw_name = _text(get('name'))
        lrn = _lrn(get('lrn'), _cell(grid, r, cols.get('lrn', 0) + 1) if 'lrn' in cols else None)
        if not raw_name and not lrn:
            continue                                          # an empty, numbered row of the template
        last, first, middle, ext = split_name(raw_name)
        remarks = _text(get('remarks'))
        item = {
            'row': r, 'lrn': lrn, 'name': raw_name, 'last': last, 'first': first, 'middle': middle, 'ext': ext,
            'sex': _sex(get('sex'), block_sex), 'birth_date': _birth_date(get('birth_date')),
            'birth_date_text': _text(get('birth_date')), 'age': _text(get('age')),
            'birth_place': _text(get('birth_place')), 'mother_tongue': _text(get('mother_tongue')),
            'ethnic': _text(get('ethnic')), 'religion': _text(get('religion')),
            'street': _text(get('street')), 'barangay': _text(get('barangay')), 'city': _text(get('city')),
            'province': _text(get('province')), 'father': _text(get('father')), 'mother': _text(get('mother')),
            'guardian': _text(get('guardian')), 'relationship': _text(get('relationship')),
            'contact': _text(get('contact')), 'remarks': remarks, 'codes': indicators(remarks),
            'errors': [], 'warnings': [],
        }
        raw_lrn = _text(get('lrn'))
        if not lrn:
            item['errors'].append(f'"{raw_lrn}" is not a 12-digit LRN.' if raw_lrn else 'The LRN is missing.')
        if not last or not first:
            item['errors'].append('The name must be written LAST NAME, FIRST NAME, MIDDLE NAME.')
        if not item['sex']:
            item['errors'].append('Sex must be M or F.')
        if item['birth_date_text'] and not item['birth_date']:
            item['warnings'].append(f'Birth date "{item["birth_date_text"]}" is not mm/dd/yyyy, so it is left out.')
        rows.append(item)
    if not rows:
        raise SF1Error('No learners were found in the register. Export the SF1 from LIS with the learners listed.')
    for field, label in (('grade_level', 'GRADE LEVEL'), ('section', 'SECTION'), ('school_year', 'SCHOOL YEAR')):
        if not meta.get(field):
            warnings.append(f'The {label} box at the top of the form is empty.')
    return {'kind': 'SHS' if senior else 'JHS', 'sheet': sheet, 'meta': meta, 'rows': rows, 'warnings': warnings}
