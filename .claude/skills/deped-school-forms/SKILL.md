---
name: deped-school-forms
description: How ARMS reads and fills DepEd's Excel files. Covers the SF1 School Register exported from LIS, teachers' e-class records (Grades 7 to 10, MAPEH, and the Strengthened Senior High record), the school forms SF1 to SF7, and the Summary of Final Grades. Use when adding or changing a school form, an e-class record reader or template, the SF1 import, or anything else that writes into a DepEd template.
---

# DepEd School Forms and E-Class Records

## Where things live

| Path | Role |
|---|---|
| `documentation/school_forms.py` | One builder per form. `build(code, school=..., sy=..., section=..., month=..., semester=..., senior=...)` returns `(bytes, file_name)`; it raises `FormUnavailable` with a message for the user. |
| `documentation/form_data.py` | The data the forms need: learners, school info, grades, attendance, personnel |
| `documentation/sf_templates/jhs/`, `documentation/sf_templates/shs/` | DepEd's own templates, one form per workbook (SF1 to SF7; SHSF-1 to SHSF-7 with 5A and 5B) |
| `core/xlsx_patch.py` | Writes values into a template's sheet XML, inserts rows, adds merges |
| `core/school_header.py` | The region, division and district printed on every form. ARMS learns them from imported SF1s, and the registrar can correct them on the School Forms page. |
| `grades/ecr.py`, `grades/ecr_template.py`, `grades/ecr_templates/` | Reading e-class records, and the blank records teachers download (per learning area, MAPEH, SSHS) |
| `enrollment/sf1.py`, `enrollment/sf1_import.py` | Reading the SF1 exported from LIS (.xls or .xlsx, Junior or Senior High) |
| `registrars/views_enrollment.py`, `registrars/views_forms.py` | The registrar's SF1 upload with preview, and the School Forms page |
| `teachers/records.py`, `teachers/views_records.py` | Teacher uploads with review, MAPEH final grades, the adviser's section forms |

## Rules

1. **Never open and re-save a DepEd template with openpyxl.** It silently drops Excel 2010+ dropdowns, dynamic-array formulas (the SSHS record's FILTER and SEQUENCE helper sheet) and some drawings. Fill templates with `xlsx_patch.patch(data, edits, inserts=..., merges=..., styles=...)`. openpyxl is fine for reading.
2. **Grow the form instead of cutting the class.** When a class has more learners than the printed rows, plan the block with `Rows` (`grow`, `repeat`, `at`) and pass the inserts. Borders, merges, pictures, print areas and formulas below move down with it.
3. **Write values the way the form shows them.** Figures that a template formats oddly (a percent format on one cell, zero-padded totals) are written as text; dates stay dates.
4. **Find columns by their header labels, not fixed letters,** when reading files from LIS or from teachers. Their layouts vary between versions.
5. **Grades follow DepEd.** Use the components and transmutation table of DepEd Order No. 8, s. 2015 (passing grade 75). Weights are written work / performance tasks / quarterly assessment (`grades/ecr.py`: `AREA_WEIGHTS`, `SSHS_TYPES`):

   | Grades 7 to 10 | Weights |
   |---|---|
   | Languages, Araling Panlipunan, EsP | .30 / .50 / .20 |
   | Mathematics, Science | .40 / .40 / .20 |
   | MAPEH, TLE | .20 / .60 / .20 |

   | Senior High (SSHS 2026 subject type) | Weights |
   |---|---|
   | Core Subject (All Tracks) | .25 / .50 / .25 |
   | Academic Elective (All Other Electives) | .25 / .45 / .30 |
   | Academic Elective (Field Experience / Exposure, and Sports and Arts) | .20 / .60 / .20 |
   | TechPro Elective (All Other Electives) | .15 / .65 / .20 |
   | TechPro Elective (Work Immersion) | .20 / .80 / 0 |

   A Senior High grade exists only when every weighted component has a score. A Grades 7 to 10 grade exists once there is a quarterly assessment score; blank components count as 0. ARMS's grade must equal the template's own formula.
6. **Review before saving.** Every upload shows a review page first, and a refused file writes nothing. Locked grading periods refuse uploads.
7. **Don't overwrite other people's test files.** Files in `static/forms/simulation/` that you did not create belong to the team.

## Check a generated form

- Open it in Excel and export each sheet to PDF, then look at every page. On Windows, script Excel through COM from PowerShell inside `Start-Job` with `Wait-Job -Timeout`, so a stuck call cannot hang the session. `ExportAsFixedFormat(0, path)` writes the PDF.
- To split sheets, use `Worksheet.Copy([Type]::Missing, [Type]::Missing)`, then `Workbooks.Item(Workbooks.Count)`. A plain `.Copy()` can hang.
- The Senior High templates use paper size 258 (long bond). Set `PageSetup.PaperSize = 5` (Legal) on the preview copy only, or the PDF shrinks into a corner.
- Recalculate the workbook in Excel, then compare its grades with ARMS's grades, learner by learner.
- Sample files and the walkthrough are in `static/forms/simulation/` (see its `README.txt`). Before a test upload, check which grading periods are open.
