"""Numbered boxes on the form pictures exported from Excel, for the upload guides (static/shared/guides/*.png).

1. Export the cell ranges as pictures with Excel's own rendering (Windows with Excel):
       powershell -File export_range.ps1 -JobFile jobs.txt
   Each line of jobs.txt is <workbook>|<sheet name or number>|<range>|<picture.png>, all paths absolute; see
   jobs.example.txt. The sources are the demo school's files: its SF7 from School Forms, the ARMS teacher template
   with two rows filled, and the SF1 and e-class record in static/forms/simulation/.
2. Draw the boxes: python annotate.py <folder of the exported pictures>

Positions are in pixels of the exported pictures: Excel's points times 5/3 (Chart.Export at 120 dpi), read from the
column and row positions export_range.ps1 saves next to each picture.
"""
import os
import sys

from PIL import Image, ImageDraw, ImageFont

HERE = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(os.path.abspath(__file__)), 'raw')
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', '..', '..', 'static', 'shared', 'guides')
BLUE = (18, 52, 153)               # palette blue #123499
EDGE = (213, 219, 231)
PAD_TOP, PAD = 44, 14
FONT = ImageFont.truetype(r'C:\Windows\Fonts\segoeuib.ttf', 20)


def load(name, box=None):
    im = Image.open(os.path.join(HERE, name)).convert('RGB')
    return im.crop(box) if box else im


def stack(*images):
    width = max(i.width for i in images)
    out = Image.new('RGB', (width, sum(i.height for i in images)), 'white')
    y = 0
    for i in images:
        out.paste(i, (0, y))
        y += i.height
    return out


def annotate(sheet, boxes, name, scale=1.0):
    """boxes: (number, (left, top, right, bottom)[, where]) in the sheet's own pixels, before scale. The badge sits
    outside its box, so it never hides the form's text: 'above' (the default), 'left' or 'right' of it."""
    if scale != 1.0:
        sheet = sheet.resize((round(sheet.width * scale), round(sheet.height * scale)), Image.LANCZOS)
    canvas = Image.new('RGB', (sheet.width + 2 * PAD, sheet.height + PAD_TOP + PAD), 'white')
    canvas.paste(sheet, (PAD, PAD_TOP))
    layer = Image.new('RGBA', canvas.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(layer)
    draw.rectangle((PAD - 1, PAD_TOP - 1, PAD + sheet.width, PAD_TOP + sheet.height), outline=EDGE + (255,), width=1)
    placed = []
    for number, box, *where in boxes:
        l, t, r, b = (round(v * scale) for v in box)
        rect = (PAD + l + 2, PAD_TOP + t + 2, PAD + r - 2, PAD_TOP + b - 2)
        draw.rounded_rectangle(rect, radius=6, fill=BLUE + (16,), outline=BLUE + (255,), width=4)
        side = where[0] if where else 'above'
        if side == 'above':
            placed.append((number, rect[0] + 24, rect[1] - 15))
        elif side == 'left':
            placed.append((number, rect[0] - 17, (rect[1] + rect[3]) // 2))
        else:
            placed.append((number, rect[2] + 17, (rect[1] + rect[3]) // 2))
    for number, cx, cy in placed:
        draw.ellipse((cx - 19, cy - 19, cx + 19, cy + 19), fill=(255, 255, 255, 255))
        draw.ellipse((cx - 16, cy - 16, cx + 16, cy + 16), fill=BLUE + (255,))
        draw.text((cx, cy - 1), str(number), font=FONT, fill='white', anchor='mm')
    canvas = Image.alpha_composite(canvas.convert('RGBA'), layer).convert('RGB')
    path = os.path.join(OUT, name)
    canvas.quantize(colors=96, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE).save(path, optimize=True)
    print(f'{name}: {canvas.size[0]}x{canvas.size[1]}, {os.path.getsize(path) // 1024} KB')


os.makedirs(OUT, exist_ok=True)

# SF7: the personnel table's header (rows 20 and 21) and two teachers; columns A (employee no.), B (name), F (position), I (major)
sf7 = stack(load('raw_sf7_head.png', (0, 38, 883, 223)), load('raw_sf7_rows.png', (0, 0, 883, 384)))
annotate(sf7, [(1, (0, 0, 84, sf7.height)), (2, (84, 0, 310, sf7.height)), (3, (441, 0, 549, sf7.height)),
               (4, (771, 0, 883, sf7.height))], 'sf7-personnel.png')

# ARMS teacher template: names required (A:B), email (C), the rest optional (D:F)
tpl = load('raw_template.png', (0, 0, 1351, 108))
annotate(tpl, [(1, (0, 0, 378, 108)), (2, (378, 0, 684, 108)), (3, (684, 0, 1351, 108))], 'teacher-template.png')

# SF1 in one picture: the top of the form at half size (school ID, school name, school year, grade level and
# section; its large type then matches the rows), and below it the learner rows (LRN, name, sex and birth date)
head = load('raw_sf1_head.png', (410, 0, 3520, 272))
head = head.resize((head.width // 2, head.height // 2), Image.LANCZOS)
rows = load('raw_sf1_rows.png', (0, 0, 1214, 600))
top = head.height + 44                      # the gap holds the numbers of the row boxes
sf1 = Image.new('RGB', (head.width, top + rows.height), 'white')
sf1.paste(head, (0, 0))
sf1.paste(rows, (0, top))
annotate(sf1, [(1, (20, 9, 274, 61)), (2, (7, 63, 500, 123), 'right'), (3, (627, 63, 915, 123), 'left'),
               (4, (972, 63, 1548, 123), 'left'),
               (5, (0, top, 343, top + 600)), (6, (343, top, 850, top + 600)), (7, (850, top, 1097, top + 600))], 'sf1-guide.png')

# E-class record, a quarter sheet from its column headings down: names, written works, performance tasks,
# quarterly assessment, and the grades the file computed
ecr = load('raw_ecr_q2.png', (0, 38, 1926, 340))
annotate(ecr, [(1, (37, 0, 385, 302)), (2, (385, 0, 970, 302)), (3, (970, 0, 1555, 302)), (4, (1555, 0, 1740, 302)),
               (5, (1740, 0, 1926, 302))], 'ecr-quarter.png')
