# ARMS

**AI-Enabled Academic Records Management System with Predictive Analytics and School Performance Prediction for Private Secondary Schools**

ARMS is a web system for the academic records of a private secondary school: Junior High (Grades 7 to 10) and Senior High (Grades 11 and 12). It follows the Department of Education (DepEd) rules for grading, grade descriptors, academic awards and school forms; each school chooses DepEd Order No. 8, s. 2015 or DepEd Order No. 015, s. 2026. It forecasts grades and school performance so the school can act before a quarter ends.

Each signed-in role has its own portal: System Administrator, School Head, Registrar and Teacher. The partner school is Northern Paramedical & Technological College of Panabo, Inc. (NPTCI). ARMS is a capstone project of the Institute of Computing, Davao del Norte State College (DNSC).

## What it does

### System Administrator (`/admin-panel/`)

- Sets up schools, school years, grading periods and grade levels.
- Creates the School Head (principal) and registrar accounts of each school.
- Tracks the contact requests sent from the public page (New, Contacted, Done).
- **Grade Forecaster.** Shows when the grade model was trained, how it did on grading periods it never saw, and what it leans on, with a button to retrain it in the background.

### School Head (`/heads/`)

- **Academic Dashboard.** It shows one overall status for the selection, on the five grade descriptors of the school's DepEd order (Did Not Meet Expectations to Outstanding, or Emerging to Advancing). The selection can be:
  - one discipline, every discipline, or one subject;
  - one grade level, all of Junior High, all of Senior High, or every grade level;
  - one grading period, or the whole school year so far.

  The page also shows where each discipline (or subject, or section) stands on the five levels, three to a level with the rest in a dialog, and a forecast chart with every discipline in one chart.
- **Poro AI recommends.** First the main recommendation, for the selection's own level (its status): how far the next level is, the step for the disciplines on that level, and the grade component the whole selection scores lowest in, with its written work, performance task and quarterly assessment (or examination) averages. Then one decision for every other level, the lowest first: keep the top level there (contests, sharing practice at a LAC session), lift each passing level one level up, bring a failing level up to 75 with remediation, and act first on the lowest. Each decision names how far the discipline is from its goal and aims at its lowest component, and shows each discipline's three component averages. Poro AI rewords the decisions (see below). Following each section and learner is the advisers' work (the teacher's My Advisory), so the School Head's portal has no section pages.
- **Honors Outlook.** Who is on track for an academic award this school year, now and with the forecasts; who is within 2 points of a cut-off; who is held back by one final grade. Every list downloads as Excel.
- **School Performance.** The whole school's year-end picture: the promotion outlook if the year ended now, the school performance forecast by grade level, each grade level's outlook, honors and attendance, enrollment over the years, and a comparison with the same period last year. The school's level and each discipline are on the dashboard.
- **School Year.** The School Head can start a school year with its grading system (quarterly: four quarters; trimestral: the three terms of DepEd Order No. 009, s. 2026; or semestral: two semesters) and its grading periods, make it current and adjust period dates, without waiting for the administrator. Each year keeps the system it was started with, so a school can move from quarters to terms as DepEd did in SY 2026-2027. Here the school also chooses its DepEd grading rules.
- **User Management.** When the School Head is busy, a registrar or a teacher (an ICT coordinator, say) can be allowed to manage the school's accounts from their own portal: edit details, reset passwords, activate and deactivate. They never touch a School Head's account, cannot add registrars and cannot pass the permission on. Sign-in help requests from the school's staff reach the School Head and these delegates, so the System Administrator is not the only way back in.
- **Excel reports, and Page Proposals** (candidate pages to discuss next).

### Registrar (`/registrars/`)

- Enrolls learners from DepEd's SF1, and manages sections and teacher accounts.
- Creates many teacher accounts at once from the school's SF7 (School Personnel Assignment List and Basic Profile), the ARMS teacher template (Excel) or a CSV. SF7 has no email column, so each teacher's sign-in is made from their name and the school's email domain (firstname.lastname@domain).
- Every upload page shows a picture of the expected file with the parts ARMS reads numbered: SF1 for enrollment, SF7 and the template for teachers, and the e-class record for teachers' grades.
- Validates, returns and locks grades that teachers submit.
- Generates the DepEd School Forms SF1 to SF7 on DepEd's own templates.

### Teacher (`/teachers/`)

- Uploads DepEd e-class records:
  - Grades 7 to 10, four quarters: one record per learning area; MAPEH has one per quarter.
  - Grades 7 to 10, three terms (DepEd Order No. 015, s. 2026): the three-term records for the core learning areas, GMRC and Values Education (scored by domain), MAPEH (Music and Arts, PE and Health) and EPP/TLE (also kept per component). Examinations are two summative tests and a term examination (30, 30 and 40), and the term grade comes from DepEd's adjusted transmutation table for SY 2026-2027, computed exactly as the record does.
  - Senior High: the Strengthened Senior High School (SSHS) record.
- Each class's record downloads from Class records with the learners and their LRNs filled in.
- ARMS recomputes every grade from the raw scores, matches each row to a learner, and lets the teacher review it before saving.
- Submits class records to the registrar. Advisers download their section's school forms.
- **My Advisory** (advisers only). Every subject's grades for the adviser's section in one grading period, uploaded by the subject teachers: who is below 75 and in how many learning areas, which subjects still have no grades, and each learner's record for the school year (every subject and period, the grade components and the general average).
- Gives online quizzes. Learners join with an access code at `/quiz/<code>/`.

### Public pages

- The school's landing page at `/`.
- Sign-in with Remember me, optional Google sign-in, and password reset by emailed code.
- A contact form whose messages reach the administrator.

## Forecasts and Poro AI

- **Grade forecaster** (`ml_engine/forecast.py`). An XGBoost model trained on every learner, subject and grading period in the database. It forecasts the next grading periods with a 90% likely range.
  - Its forecasts appear on the dashboard, Honors Outlook and School Performance.
  - Each chart has Line, Bar and Table views. The administrator's Grade Forecaster page reports how the model did on grading periods it never saw.
  - On the demo data, for quarters it had not seen, it missed by about 2 points on average. A simple trend rule missed by about 3.
  - Train it with `python manage.py train_ml_models`. It also retrains itself in the background when the registrar locks a grading period, and the administrator can retrain it from the Grade Forecaster page. The trained files are not in git, so a fresh copy uses the trend rule until the model is trained once.
- **Poro AI** (`heads/poro.py`). What Poro recommends is decided in code by rules a person can check (`heads/insights.py`, `school_decisions`). Poro AI runs a local model through [Ollama](https://ollama.com): `poro` is Qwen 2.5 (3B) with Poro's persona (`ml_engine/poro/Modelfile`). In the background it rewords each sentence of the recommendations, told what that sentence must keep.
  - A reworded sentence is shown only when it keeps every number in the same order, says "higher", "below" and the like the same way, keeps every name, period, level, grade component and DepEd order, and brings in no new subject, cause or promise. A second reading by the model must then find the same meaning.
  - The other sentences keep the computed wording, and the School Head can switch between Poro's wording and the computed one.
  - It runs on the school's own computer and is off on Vercel, which cannot run Ollama. Each set of recommendations is kept until the grades change. Without Ollama, the computed wording is shown.

## DepEd basis

| Rule | Source |
|---|---|
| Grade components (Written Work, Performance Tasks, Quarterly Assessment), transmutation, passing grade of 75, remediation below 75 | DepEd Order No. 8, s. 2015 |
| Grade descriptors: Outstanding, Very Satisfactory, Satisfactory, Fairly Satisfactory, Did Not Meet Expectations | DepEd Order No. 8, s. 2015 |
| Academic honors: With Honors, With High Honors, With Highest Honors | DepEd Order No. 36, s. 2016 |
| Descriptors Advancing, Benchmarking, Connecting, Developing, Emerging, and the Academic Excellence Award | DepEd Order No. 015, s. 2026, for schools that choose it on the School Year page (`core/grading_policy.py`) |
| Three terms a school year (Term 1 June to September, Term 2 September to December, Term 3 January to April) | DepEd Order No. 009, s. 2026 |
| Three-term grading: written/oral works, product/performance tasks and examinations, weighed 20/50/30 (20/60/20 for MAPEH and EPP/TLE); examinations of two summative tests and a term examination (30/30/40); the adjusted transmutation table of SY 2026-2027; the final grade the average of the three term grades | DepEd Order No. 015, s. 2026 and DepEd's three-term e-class records (`grades/ecr.py`) |
| School Forms SF1 to SF7 and e-class records | DepEd's official templates (`documentation/sf_templates/`, `grades/ecr_templates/`) |
| Which discipline a subject belongs to, including the TVL / TechPro specializations (TESDA qualifications such as EIM NC II and SMAW NC I) under TLE | The K to 12, MATATAG and Strengthened SHS curricula (`academics/subject_catalog.py`) |

KPUP (Knowledge, Process or Skills, Understanding, Products or Performances) and the levels Beginning to Advanced came from DepEd Order No. 73, s. 2012, which DepEd Order No. 8, s. 2015 replaced. ARMS no longer uses them. Senior High in a three-term year still uses the SSHS e-class record: DepEd had published no three-term Senior High record when this was built.

Subjects get their discipline when they are added: ARMS reads the name (then the code) against the curriculum and puts the subject in the school's own family for it, or in the learning area that usually keeps it when the school has no such department (a school without ABM keeps Applied Economics in Araling Panlipunan). For subjects added earlier, preview with `python manage.py classify_subjects` and save with `--apply`.

DepEd's Excel templates are filled by editing their cells in place (`core/xlsx_patch.py`), so their dropdowns, formulas and print setup stay as DepEd made them.

## Tech stack

- Python 3.12 and Django 6.0
- PostgreSQL on [Supabase](https://supabase.com). SQLite is disabled on purpose.
- XGBoost, scikit-learn, pandas and NumPy for the forecaster
- openpyxl and xlrd for Excel files
- Django templates with plain CSS and JavaScript; Chart.js and SVG charts
- Optional: Ollama for Poro AI, and Redis for a shared cache across several servers

## Getting started

1. **Install.** Use Python 3.12.

   ```bash
   git clone https://github.com/Yoko-Haren/arms.git
   cd arms
   python -m venv .venv
   ```

   Activate the virtual environment (Windows: `.venv\Scripts\activate`, macOS or Linux: `source .venv/bin/activate`), then install the packages:

   ```bash
   pip install -r requirements.txt
   ```

2. **Configure.** Copy `.env.example` to `.env` and fill it in (see [Configuration](#configuration)). `.env` holds your secrets and is git-ignored. Never commit it.

3. **Create the database tables.**

   ```bash
   python manage.py migrate
   ```

4. **Create the first System Administrator.** Superusers can open the Admin Portal at `/admin-panel/`. From there, add the school, its school year, its School Head and its registrar.

   ```bash
   python manage.py createsuperuser
   ```

5. **Optional: load the demo schools.** `seed_demo` creates school ID `DEMO-ARMS`, graded by quarter, with accounts for every role; their usernames end in `@demo.arms.edu.ph`. `seed_demo --trimestral` creates `DEMO-TERM`, a three-term school under DepEd Order No. 015, s. 2026 (last year in quarters, this year in terms; Grade 11 on the Strengthened SHS curriculum), with usernames ending in `@term.demo.arms.edu.ph`. All demo accounts share the password in `DEMO_PASSWORD`. Both take `--reset`, `--remove` and `--dry-run`, and `--spread-levels`, which moves each discipline's grades so the nine disciplines cover all five levels (retrain the forecaster after it).

   ```bash
   python manage.py seed_demo
   python manage.py seed_demo --trimestral
   ```

6. **Train the forecaster.** Run it again after new grades come in.

   ```bash
   python manage.py train_ml_models
   ```

7. **Run the server**, then open http://127.0.0.1:8000.

   ```bash
   python manage.py runserver
   ```

8. **Optional: Poro AI.** Install [Ollama](https://ollama.com), pull the base model (about 1.9 GB), then build `poro` from it:

   ```bash
   ollama pull qwen2.5:3b
   ```

   ```bash
   python manage.py setup_poro
   ```

## Configuration

All settings come from `.env`. The full list with examples is in `.env.example`.

| Variable | What it is |
|---|---|
| `DJANGO_SECRET_KEY` | A long random secret. Required. |
| `DJANGO_DEBUG` | `True` only on a development machine. |
| `DATABASE_URL` | The Supabase PostgreSQL connection URL. Required. |
| `SUPABASE_URL`, `SUPABASE_ANON_KEY`, `SUPABASE_SERVICE_ROLE_KEY` | The Supabase project and its keys. |
| `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`, `GOOGLE_REDIRECT_URI` | The Google sign-in OAuth client. The redirect URI for local use is `http://127.0.0.1:8000/accounts/google/callback/`. |
| `GOOGLE_BINDING_REQUIRED` | `False` lets users skip linking a Google account. |
| `EMAIL_HOST`, `EMAIL_PORT`, `EMAIL_USE_TLS`, `EMAIL_HOST_USER`, `EMAIL_HOST_PASSWORD`, `DEFAULT_FROM_EMAIL` | The mail account for verification and password-reset codes. For Gmail, use an App Password. |
| `ARMS_CONTACT_EMAIL` | Where contact-form messages go. |
| `DEMO_PASSWORD` | The password of the demo accounts. It is generated on the first `seed_demo` run if empty. |
| `PORO_AI_ENABLED`, `OLLAMA_URL`, `PORO_AI_MODEL`, `PORO_AI_BASE_MODEL`, `PORO_AI_WRITE_TIMEOUT` | Poro AI and its local model. `PORO_AI_ENABLED` is off by default on Vercel. |
| `PAGE_CACHE` | `False` turns the per-user page cache off while troubleshooting. |
| `REMEMBER_ME_DAYS` | How long Remember me keeps a user signed in. The default is 30. |
| `REDIS_URL` | Optional shared cache when the app runs on several servers. |
| `DJANGO_ALLOWED_HOSTS`, `DJANGO_CSRF_TRUSTED_ORIGINS` | Extra host names and origins when deployed, comma separated. |

## Project layout

| Path | What it holds |
|---|---|
| `config/` | Settings and the main URLs |
| `accounts/` | Sign-in, Google sign-in, password reset, account settings, the `seed_demo` command |
| `admin_panel/` | The System Administrator portal |
| `heads/` | The School Head portal: dashboard, its decisions (`insights.py`) and Poro AI (`poro.py`), forecast charts (`forecasts.py`), Honors Outlook, School Performance, School Year, User Management |
| `registrars/` | The Registrar portal: enrollment, sections, teachers and the teacher file reader (`teacher_import.py`), grade validation, School Forms |
| `teachers/` | The Teacher portal: class records, e-class record uploads, adviser forms |
| `assessments/` | Online quizzes |
| `grades/`, `enrollment/`, `documentation/` | The e-class record reader, the SF1 reader and the DepEd school forms |
| `academics/`, `students/`, `attendance/`, `scheduling/`, `promotion/`, … | School structure, learners, attendance, class assignments and promotion records |
| `ml_engine/` | The grade forecaster, the `train_ml_models` command, background retraining (`training.py`), and Poro's Modelfile with the `setup_poro` command |
| `communication/` | Notifications and contact requests |
| `audit/` | Activity logs and anomaly detection (`python manage.py detect_anomalies`) |
| `core/` | Shared helpers: the DepEd grading rules each school follows (`grading_policy.py`), page caching, Excel template patching, the school form header |
| `templates/`, `static/` | Pages, styles, scripts, the ARMS logo, the upload guide pictures (`static/shared/guides/`) and DepEd form templates for download |
