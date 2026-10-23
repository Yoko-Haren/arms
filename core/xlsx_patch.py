"""Filling cells of an official Excel template without rewriting the workbook.

openpyxl rebuilds a workbook from what it understands and silently drops the rest: Excel 2010+
data validations (dropdowns that point at other sheets), dynamic-array formulas and their
metadata, some drawings. DepEd's templates rely on all of these. This module edits only what it
is asked to, directly in the sheet XML, and copies every other part of the file unchanged.

Two edits are possible:
  cells    values for given cells. str (an inline string), int / float / Decimal (a number), bool,
           date / datetime (an Excel serial number; the cell keeps its own date format), None
           (empties the cell, keeps its style) and '=...' (a formula Excel computes on opening).
  inserts  extra rows inside a block (a class list longer than the form). The new rows look like
           a given row of the block, or repeat a group of rows (one person's block of a staff list);
           everything below moves down: cells, merged cells, pictures and shapes, comments, page
           breaks, the print area and the sheet's formulas.
  merges   cells to merge, for templates whose rows are not merged alike (a name cut off in one row
           and not the next); a merge that would overlap an existing one is left out.
"""
import datetime
import io
import posixpath
import re
import zipfile
from decimal import Decimal
from xml.sax.saxutils import escape

_ROW = re.compile(r'<row\b[^>]*?\br="(\d+)"[^>]*?(?:/>|>.*?</row>)', re.S)
_CELL = re.compile(r'<c\b[^>]*?\br="([A-Z]+)(\d+)"[^>]*?(?:/>|>.*?</c>)', re.S)
_REF = re.compile(r"(?<![A-Za-z0-9_!'\]])(\$?)([A-Z]{1,3})(\$?)(\d{1,7})(?![0-9(])")
_REF_NAMED = re.compile(r"(?<![A-Za-z0-9_'\]])(\$?)([A-Z]{1,3})(\$?)(\d{1,7})(?![0-9(])")      # also after Sheet!
_ROWS_REF = re.compile(r'(?<![A-Za-z0-9_$:])(\$?)(\d{1,7}):(\$?)(\d{1,7})(?![0-9])')


class PatchError(Exception):
    pass


def col_number(letters):
    n = 0
    for ch in letters.upper():
        n = n * 26 + ord(ch) - 64
    return n


def col_letters(number):
    out = ''
    while number:
        number, rest = divmod(number - 1, 26)
        out = chr(65 + rest) + out
    return out


def split_ref(ref):
    m = re.fullmatch(r'([A-Za-z]+)(\d+)', ref.strip())
    if not m:
        raise PatchError(f'"{ref}" is not a cell reference.')
    return m.group(1).upper(), int(m.group(2))


# ---------------------------------------------------------------------------------------------
# cell values
# ---------------------------------------------------------------------------------------------

def _serial(value):
    if isinstance(value, datetime.datetime):
        delta = value - datetime.datetime(1899, 12, 30)
        return delta.days + delta.seconds / 86400
    return (value - datetime.date(1899, 12, 30)).days


def _cell_xml(ref, value, style):
    s = f' s="{style}"' if style else ''
    if value is None:
        return f'<c r="{ref}"{s}/>'
    if isinstance(value, bool):
        return f'<c r="{ref}"{s} t="b"><v>{int(value)}</v></c>'
    if isinstance(value, (datetime.date, datetime.datetime)):
        value = _serial(value)
    if isinstance(value, (int, float, Decimal)):
        number = format(value, 'f') if isinstance(value, Decimal) else repr(value)
        return f'<c r="{ref}"{s}><v>{number}</v></c>'
    text = str(value)
    if text.startswith('=') and len(text) > 1:
        return f'<c r="{ref}"{s}><f>{escape(text[1:])}</f></c>'
    space = ' xml:space="preserve"' if text != text.strip() or '\n' in text else ''
    return f'<c r="{ref}"{s} t="inlineStr"><is><t{space}>{escape(text)}</t></is></c>'


def _style_of(cell_xml):
    m = re.search(r'\bs="(\d+)"', cell_xml.split('>', 1)[0])
    return m.group(1) if m else None


def _sheet_data(sheet_xml):
    """(head, rows {number: xml}, tail) of a sheet."""
    start, end = sheet_xml.find('<sheetData'), sheet_xml.find('</sheetData>')
    if start < 0:
        raise PatchError('The sheet has no cell data.')
    if end < 0:                                            # <sheetData/>
        close = sheet_xml.index('/>', start)
        return sheet_xml[:start] + '<sheetData>', {}, '</sheetData>' + sheet_xml[close + 2:]
    open_end = sheet_xml.index('>', start) + 1
    body = sheet_xml[open_end:end]
    return sheet_xml[:open_end], {int(m.group(1)): m.group(0) for m in _ROW.finditer(body)}, sheet_xml[end:]


def _join(head, rows, tail):
    return head + ''.join(rows[n] for n in sorted(rows)) + tail


def _row_parts(row_xml):
    """(opening tag without spans, [(col number, letters, cell xml)])."""
    opening = row_xml[:row_xml.index('>') + 1]
    if opening.endswith('/>'):
        opening, inner = opening[:-2] + '>', ''
    else:
        inner = row_xml[len(opening):-len('</row>')]
    opening = re.sub(r'\sspans="[^"]*"', '', opening)
    return opening, [(col_number(m.group(1)), m.group(1), m.group(0)) for m in _CELL.finditer(inner)]


def set_cells(sheet_xml, values, styles=None):
    """The sheet XML with the given cells set. values: {'F10': 'Region XI', 'B12': 5, ...}."""
    styles = styles or {}
    wanted = {}
    for ref, value in values.items():
        col, row = split_ref(ref)
        wanted.setdefault(row, {})[col] = (value, styles.get(f'{col}{row}'))
    head, rows, tail = _sheet_data(sheet_xml)
    for number, cols in wanted.items():
        if number in rows:
            opening, cells = _row_parts(rows[number])
        else:
            opening, cells = f'<row r="{number}">', []
        existing = {letters: xml for _, letters, xml in cells}
        for letters, (value, style) in cols.items():
            old = existing.get(letters)
            if old is not None and re.search(r'<f\b[^>]*\bt="shared"[^>]*\bref="', old):
                raise PatchError(f'{letters}{number} starts a shared formula; it cannot be overwritten.')
            existing[letters] = _cell_xml(f'{letters}{number}', value, style or (_style_of(old) if old else None))
        ordered = sorted(existing.items(), key=lambda kv: col_number(kv[0]))
        rows[number] = opening + ''.join(xml for _, xml in ordered) + '</row>'
    return _join(head, rows, tail)


# ---------------------------------------------------------------------------------------------
# inserting rows
# ---------------------------------------------------------------------------------------------

def _shift_refs(text, after, count, qualified=False):
    """Every row reference below `after` moves down by `count` (A12, $B$40, A1:C9, $9:$11).

    qualified: also the references written after a sheet name (defined names always name their
    sheet); in a formula those point at another sheet and stay.
    """
    def cell(m):
        row = int(m.group(4))
        return f'{m.group(1)}{m.group(2)}{m.group(3)}{row + count if row > after else row}'

    def rows(m):
        a, b = int(m.group(2)), int(m.group(4))
        return f'{m.group(1)}{a + count if a > after else a}:{m.group(3)}{b + count if b > after else b}'
    return _ROWS_REF.sub(rows, (_REF_NAMED if qualified else _REF).sub(cell, text))


def _shift_formulas(row_xml, after, count):
    return re.sub(r'(<f\b[^>]*>)(.*?)(</f>)', lambda m: m.group(1) + _shift_refs(m.group(2), after, count) + m.group(3),
                  row_xml, flags=re.S)


def _renumber_row(row_xml, old, new):
    row_xml = re.sub(r'(<row\b[^>]*?\br=")\d+(")', rf'\g<1>{new}\2', row_xml, count=1)
    return re.sub(r'(<c\b[^>]*?\br="[A-Z]+)' + str(old) + '"', rf'\g<1>{new}"', row_xml)


def _blank_copy(row_xml, like, new, keep=False):
    """Row `like` as row `new`: same height and cell styles, formulas following the row, and no values
    unless keep (a repeated block keeps its printed labels)."""
    opening, cells = _row_parts(row_xml)
    opening = re.sub(r'(\br=")\d+(")', rf'\g<1>{new}\2', opening, count=1)
    out = []
    for _, letters, xml in cells:
        if keep and '<f' not in xml and ('<v>' in xml or '<is>' in xml):
            out.append(re.sub(r'(<c\b[^>]*?\br=")[A-Z]+\d+(")', rf'\g<1>{letters}{new}\2', xml, count=1))
            continue
        style = _style_of(xml)
        formula = re.search(r'<f>(.*?)</f>', xml, re.S)
        if formula and not re.search(r'<f\b[^>]*\bt=', xml):
            moved = re.sub(r'(?<![A-Za-z$])([A-Z]{1,3})' + str(like) + r'(?![0-9])', rf'\g<1>{new}', formula.group(1))
            out.append(f'<c r="{letters}{new}"{f" s={chr(34)}{style}{chr(34)}" if style else ""}><f>{moved}</f></c>')
        else:
            out.append(f'<c r="{letters}{new}"{f" s={chr(34)}{style}{chr(34)}" if style else ""}/>')
    return opening + ''.join(out) + '</row>'


def _range_rows(ref):
    cells = re.findall(r'([A-Z]+)(\d+)', ref)
    rows = [int(r) for _, r in cells]
    return min(rows), max(rows)


def _insert_in_sheet(xml, after, count, like):
    """like: the row the new rows copy, or (first, last[, keep]), a group of rows the new rows repeat
    (keep: with the group's printed text)."""
    first, last, keep = (like, like, False) if isinstance(like, int) else (tuple(like) + (False,))[:3]
    size = last - first + 1
    head, rows, tail = _sheet_data(xml)
    templates = {r: rows.get(r) for r in range(first, last + 1)}
    moved = {}
    for n, row_xml in rows.items():
        row_xml = _shift_formulas(row_xml, after, count)
        moved[n + count if n > after else n] = _renumber_row(row_xml, n, n + count) if n > after else row_xml
    for i in range(1, count + 1):
        src = first + (i - 1) % size
        moved[after + i] = _blank_copy(templates[src], src, after + i, keep) if templates[src] else f'<row r="{after + i}"/>'
    xml = _join(head, moved, tail)

    def merge(m):
        ref = m.group(1)
        low, high = _range_rows(ref)
        if low > after:
            return f'<mergeCell ref="{_shift_refs(ref, after, count)}"/>'
        if low <= after < high:                            # a merge across the insertion point grows
            a, b = ref.split(':')
            return f'<mergeCell ref="{a}:{_shift_refs(b, after, count)}"/>'
        extra = ''
        if first <= low and high <= last:                  # merges of the copied rows repeat on the copies
            for start in range(after + 1, after + count + 1, size):
                offset = start - first
                if high + offset <= after + count:
                    extra += '<mergeCell ref="' + re.sub(r'([A-Z]+)(\d+)', lambda c: f'{c.group(1)}{int(c.group(2)) + offset}', ref) + '"/>'
        return f'<mergeCell ref="{ref}"/>' + extra
    xml = re.sub(r'<mergeCell ref="([^"]+)"/>', merge, xml)
    xml = re.sub(r'<mergeCells count="\d+">', lambda m: f'<mergeCells count="{xml.count("<mergeCell ")}">', xml)
    for tag, attr in (('dimension', 'ref'), ('conditionalFormatting', 'sqref'), ('dataValidation', 'sqref'),
                      ('hyperlink', 'ref'), ('selection', 'sqref'), ('selection', 'activeCell'), ('pane', 'topLeftCell')):
        xml = re.sub(rf'(<{tag}\b[^>]*?\b{attr}=")([^"]*)(")', lambda m: m.group(1) + _shift_refs(m.group(2), after, count)
                     + m.group(3), xml)
    xml = re.sub(r'(<brk\b[^>]*?\bid=")(\d+)(")', lambda m: m.group(1) + str(int(m.group(2)) + count if int(m.group(2)) > after
                                                                         else int(m.group(2))) + m.group(3), xml)
    return xml


def _insert_in_drawing(xml, after, count):
    """Pictures and shapes anchored below the insertion point move down (rows are 0-based here)."""
    def anchor(m):
        row = int(m.group(2))
        return m.group(1) + str(row + count if row + 1 > after else row) + m.group(3)
    return re.sub(r'(<xdr:row>)(\d+)(</xdr:row>)', anchor, xml)


def _insert_in_vml(xml, after, count):
    def anchor(m):
        parts = [p.strip() for p in m.group(2).split(',')]
        if len(parts) == 8:
            for i in (2, 6):
                if int(parts[i]) + 1 > after:
                    parts[i] = str(int(parts[i]) + count)
        return m.group(1) + ', '.join(parts) + m.group(3)
    xml = re.sub(r'(<x:Anchor>)([^<]*)(</x:Anchor>)', anchor, xml)
    return re.sub(r'(<x:Row>)(\d+)(</x:Row>)', lambda m: m.group(1) + str(int(m.group(2)) + count if int(m.group(2)) + 1 > after
                                                                        else int(m.group(2))) + m.group(3), xml)


def _insert_in_comments(xml, after, count):
    return re.sub(r'(<comment\b[^>]*?\bref=")([^"]*)(")', lambda m: m.group(1) + _shift_refs(m.group(2), after, count) + m.group(3), xml)


def _insert_in_names(workbook_xml, sheet_name, sheet_index, after, count):
    """The print area, print titles and filters of the sheet follow the rows."""
    quoted = {f"'{sheet_name}'!", f'{sheet_name}!', f"'{sheet_name.replace(chr(39), chr(39) * 2)}'!"}

    def name(m):
        attrs, text = m.group(1), m.group(2)
        local = re.search(r'\blocalSheetId="(\d+)"', attrs)
        if not (local and int(local.group(1)) == sheet_index) and not any(q in _unescape(text) for q in quoted):
            return m.group(0)
        return f'<definedName{attrs}>{_shift_refs(text, after, count, qualified=True)}</definedName>'
    return re.sub(r'<definedName\b([^>]*)>(.*?)</definedName>', name, workbook_xml, flags=re.S)


def _bounds(ref):
    a, _, b = ref.partition(':')
    (c1, r1), (c2, r2) = split_ref(a), split_ref(b or a)
    return col_number(c1), r1, col_number(c2), r2


def add_merges(xml, refs):
    """Merge the given ranges, skipping any that overlap a merge already there."""
    existing = [_bounds(m) for m in re.findall(r'<mergeCell ref="([^"]+)"/>', xml)]
    new = []
    for ref in refs:
        c1, r1, c2, r2 = _bounds(ref)
        if any(c1 <= b3 and b1 <= c2 and r1 <= b4 and b2 <= r2 for b1, b2, b3, b4 in existing):
            continue
        existing.append((c1, r1, c2, r2))
        new.append(f'<mergeCell ref="{ref}"/>')
    if not new:
        return xml
    if '<mergeCells' in xml:
        xml = re.sub(r'</mergeCells>', ''.join(new) + '</mergeCells>', xml, count=1)
    else:                                                  # mergeCells comes right after sheetData (or its siblings)
        anchor = re.search(r'</sheetData>(\s*<sheetCalcPr\b[^>]*/>)?(\s*<sheetProtection\b[^>]*/>)?(\s*<protectedRanges>.*?</protectedRanges>)?'
                           r'(\s*<scenarios\b.*?</scenarios>)?(\s*<autoFilter\b.*?(?:/>|</autoFilter>))?(\s*<sortState\b.*?(?:/>|</sortState>))?'
                           r'(\s*<dataConsolidate\b.*?(?:/>|</dataConsolidate>))?(\s*<customSheetViews>.*?</customSheetViews>)?', xml, re.S)
        xml = xml[:anchor.end()] + '<mergeCells count="0">' + ''.join(new) + '</mergeCells>' + xml[anchor.end():]
    return re.sub(r'<mergeCells count="\d+">', f'<mergeCells count="{xml.count("<mergeCell ")}">', xml, count=1)


# ---------------------------------------------------------------------------------------------
# the package
# ---------------------------------------------------------------------------------------------

def _unescape(text):
    return text.replace('&apos;', "'").replace('&quot;', '"').replace('&lt;', '<').replace('&gt;', '>').replace('&amp;', '&')


def _rels(z, part):
    """{rId: (type, target part)} of a part."""
    folder, name = posixpath.split(part)
    path = posixpath.join(folder, '_rels', name + '.rels')
    if path not in z.namelist():
        return {}
    out = {}
    for m in re.finditer(r'<Relationship\b[^>]*>', z.read(path).decode('utf-8')):
        tag = m.group(0)
        rid = re.search(r'\bId="([^"]+)"', tag).group(1)
        kind = re.search(r'\bType="([^"]+)"', tag).group(1).rsplit('/', 1)[-1]
        target = re.search(r'\bTarget="([^"]+)"', tag).group(1)
        if re.search(r'\bTargetMode="External"', tag):
            continue
        out[rid] = (kind, target.lstrip('/') if target.startswith('/') else posixpath.normpath(posixpath.join(folder, target)))
    return out


def cell_styles(data, sheet, refs):
    """{ref: style id} of cells of a workbook, to write other cells the way the template writes these."""
    z = zipfile.ZipFile(io.BytesIO(data))
    _, rows, _ = _sheet_data(z.read(sheet_parts(z)[sheet]).decode('utf-8'))
    out = {}
    for ref in refs:
        col, row = split_ref(ref)
        _, cells = _row_parts(rows[row]) if row in rows else ('', [])
        xml = next((x for _, letters, x in cells if letters == col), None)
        out[ref] = _style_of(xml) if xml else None
    return out


def sheet_parts(z):
    """{sheet name: 'xl/worksheets/sheetN.xml'} in workbook order."""
    workbook = z.read('xl/workbook.xml').decode('utf-8')
    targets = {rid: target for rid, (_, target) in _rels(z, 'xl/workbook.xml').items()}
    out = {}
    for m in re.finditer(r'<sheet\b[^>]*/>', workbook):
        tag = m.group(0)
        name = re.search(r'\bname="([^"]+)"', tag).group(1)
        rid = re.search(r'\br:id="([^"]+)"', tag)
        out[_unescape(name)] = targets.get(rid.group(1)) if rid else None
    return out


def patch(data, edits=None, *, inserts=None, merges=None, hidden=(), visible=(), active=None, styles=None):
    """A copy of the workbook (bytes) with rows inserted and cells set.

    edits: {sheet name: {ref: value}} in the rows as they are after the inserts (merges too).
    inserts: {sheet name: [(after, count, like), ...]}: `count` rows after row `after`, looking like
    row `like` of the block; applied in order, each in the rows as they are at that moment.
    Excel recomputes every formula when the copy is opened. hidden / visible change sheet
    visibility; active is the sheet the file opens on.
    """
    edits, inserts, merges = edits or {}, inserts or {}, merges or {}
    src = zipfile.ZipFile(io.BytesIO(data))
    parts = sheet_parts(src)
    missing = [name for name in list(edits) + list(inserts) + list(merges) if name not in parts]
    if missing:
        raise PatchError(f'The template has no sheet named {", ".join(sorted(set(missing)))}.')
    order = list(parts)
    contents = {}

    def get(part):
        if part not in contents:
            contents[part] = src.read(part).decode('utf-8')
        return contents[part]

    for sheet, steps in inserts.items():
        part = parts[sheet]
        related = _rels(src, part)
        for after, count, like in steps:
            if count <= 0:
                continue
            if (like if isinstance(like, int) else like[1]) > after:
                raise PatchError('New rows copy rows above them.')
            contents[part] = _insert_in_sheet(get(part), after, count, like)
            for kind, target in related.values():
                if target not in src.namelist():
                    continue
                if kind == 'drawing':
                    contents[target] = _insert_in_drawing(get(target), after, count)
                elif kind == 'vmlDrawing':
                    contents[target] = _insert_in_vml(get(target), after, count)
                elif kind == 'comments':
                    contents[target] = _insert_in_comments(get(target), after, count)
            contents['xl/workbook.xml'] = _insert_in_names(get('xl/workbook.xml'), sheet, order.index(sheet), after, count)
    for sheet, refs in merges.items():
        contents[parts[sheet]] = add_merges(get(parts[sheet]), refs)
    for sheet, cells in edits.items():
        part = parts[sheet]
        contents[part] = set_cells(get(part), cells, (styles or {}).get(sheet))
    if active is not None:
        for sheet, part in parts.items():
            contents[part] = _selected(get(part), sheet == active)
    contents['xl/workbook.xml'] = _workbook(get('xl/workbook.xml'), hidden, visible, active, order)

    out = io.BytesIO()
    with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as dst:
        for info in src.infolist():
            name = info.filename
            if name == 'xl/calcChain.xml':
                continue                                   # Excel rebuilds it; a stale one makes it "repair" the file
            if name in contents:
                raw = contents[name].encode('utf-8')
            else:
                raw = src.read(name)
                if name == 'xl/_rels/workbook.xml.rels':
                    raw = re.sub(r'<Relationship\b[^>]*calcChain[^>]*/>', '', raw.decode('utf-8')).encode('utf-8')
                elif name == '[Content_Types].xml':
                    raw = re.sub(r'<Override\b[^>]*calcChain[^>]*/>', '', raw.decode('utf-8')).encode('utf-8')
            dst.writestr(info, raw)
    return out.getvalue()


def _selected(xml, selected):
    """Only the sheet the file opens on is selected (two selected tabs would be edited together)."""
    def view(m):
        tag = re.sub(r'\stabSelected="[^"]*"', '', m.group(0))
        return tag.replace('<sheetView', '<sheetView tabSelected="1"', 1) if selected else tag
    return re.sub(r'<sheetView\b[^>]*>', view, xml, count=1)


def _workbook(xml, hidden, visible, active, order):
    if re.search(r'<calcPr\b', xml):
        xml = re.sub(r'<calcPr\b([^>]*?)(/?)>', lambda m: '<calcPr' + re.sub(r'\sfullCalcOnLoad="[^"]*"', '', m.group(1))
                     + ' fullCalcOnLoad="1"' + m.group(2) + '>', xml, count=1)
    else:
        xml = xml.replace('</workbook>', '<calcPr fullCalcOnLoad="1"/></workbook>')

    def sheet(m):
        tag = m.group(0)
        name = _unescape(re.search(r'\bname="([^"]+)"', tag).group(1))
        if name in hidden:
            tag = re.sub(r'\sstate="[^"]*"', '', tag).replace('<sheet ', '<sheet state="hidden" ', 1)
        elif name in visible:
            tag = re.sub(r'\sstate="[^"]*"', '', tag)
        return tag
    xml = re.sub(r'<sheet\b[^>]*/>', sheet, xml)
    if active is not None and active in order:
        index = order.index(active)
        xml = re.sub(r'(<workbookView\b[^>]*?)\sactiveTab="\d+"', r'\1', xml)
        xml = re.sub(r'(<workbookView\b[^>]*?)\sfirstSheet="\d+"', r'\1', xml)
        xml = re.sub(r'<workbookView\b', f'<workbookView activeTab="{index}"', xml, count=1)
    return xml


class Rows:
    """Where the rows of a template block end up once rows are inserted.

    Blocks are named by their template rows. at(row) is the row a template row is now, steps() the
    inserts for patch(). Example: a block of 20 learner rows (13-32) for 25 learners:
    grow(13, 20, 25) adds 5 rows after row 32, and at(33) is 38.
    """

    def __init__(self):
        self._added = []                                   # (template row after which, count, like rows)

    def grow(self, first, size, needed):
        """Room for `needed` rows in a block of `size` rows starting at `first`; returns the rows added."""
        extra = max(0, needed - size)
        if extra:
            last = first + size - 1
            self._added.append((last, extra, (last, last)))
        return extra

    def repeat(self, first, last, times):
        """`times` more copies of the group first..last right after it (the last person block of a list)."""
        if times > 0:
            self._added.append((last, (last - first + 1) * times, (first, last, True)))
        return times

    def at(self, row):
        return row + sum(count for after, count, _ in self._added if row > after)

    def steps(self):
        out = []
        for after, count, like in sorted(self._added):
            a, b, keep = (tuple(like) + (False,))[:3]
            out.append((self.at(after), count, (self.at(a), self.at(b), keep)))
        return out
