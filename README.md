# ARMS

**AI-Enabled Academic Records Management System with Predictive Analytics and School Performance Prediction for Private Secondary Schools**

ARMS is a web system for the academic records of a private secondary school: Junior High (Grades 7 to 10) and Senior High (Grades 11 and 12). It follows the Department of Education (DepEd) rules for grading, proficiency levels and school forms. It forecasts grades and school performance so the school can act before a quarter ends.

Each signed-in role has its own portal: System Administrator, School Head, Registrar and Teacher. The partner school is Northern Paramedical & Technological College of Panabo, Inc. (NPTCI). ARMS is a capstone project of the Institute of Computing, Davao del Norte State College (DNSC).

## What it does

### System Administrator (`/admin-panel/`)

- Sets up schools, school years, grading periods and grade levels.
- Creates the School Head (principal) and registrar accounts of each school.
- Tracks the contact requests sent from the public page (New, Contacted, Done).

### School Head (`/heads/`)

- **Academic Dashboard.** It shows one overall status for the selection, from Beginning to Advanced. The selection can be:
  - one discipline, every discipline, or one subject;
  - one grade level, all of Junior High, all of Senior High, or every grade level;
  - one grading period, or the whole school year so far.

  The page also shows where each discipline stands on the five levels, a sections table with each section's KPUP breakdown (Knowledge, Process, Understanding, Product), the learners below 75, and a forecast chart.
- **Section briefs.** Each class has a summary, what stands out, and what to do next. A level-up plan takes every group of learners one level higher, from Beginning to Advanced.
- **School Performance.** It covers the promotion outlook, learning areas, grade levels, enrollment over the years and a comparison with last year.
- **School Year.** The School Head can start a school year with its grading periods, make it current and adjust period dates, without waiting for the administrator.
- **User Management, Excel reports, and Page Proposals** (candidate pages to discuss next).

### Registrar (`/registrars/`)

- Enrolls learners from DepEd's SF1, and manages sections and teacher accounts.
- Validates, returns and locks grades that teachers submit.
- Generates the DepEd School Forms SF1 to SF7 on DepEd's own templates.

### Teacher (`/teachers/`)

- Uploads DepEd e-class records:
  - Grades 7 to 10: one record per learning area; MAPEH has one per quarter.
  - Senior High: the Strengthened Senior High School (SSHS) record.
- ARMS recomputes every grade from the raw scores, matches each row to a learner, and lets the teacher review it before saving.
- Submits class records to the registrar. Advisers download their section's school forms.
- Gives online quizzes. Learners join with an access code at `/quiz/<code>/`.

### Public pages

- The school's landing page at `/`.
- Sign-in with Remember me, optional Google sign-in, and password reset by emailed code.
- A contact form whose messages reach the administrator.

## Forecasts and Poro AI

- **Grade forecaster** (`ml_engine/forecast.py`). An XGBoost model trained on every learner, subject and grading period in the database. It forecasts the next grading periods with a 90% likely range.
  - Its forecasts appear on the dashboard, the section briefs and School Performance.
  - Each chart has Line, Bar and Table views. Each also shows what the model forecast one period earlier, so its accuracy stays visible.
  - On the demo data, for quarters it had not seen, it missed by about 2 points on average. A simple trend rule missed by about 3.
  - Train it with `python manage.py train_ml_models`. The trained files are not in git, so a fresh copy uses the trend rule until the model is trained once.
- **Poro AI.** Every figure in a summary is computed in code by rules a person can check (`heads/insights.py`). Poro AI uses a local Qwen model through [Ollama](https://ollama.com), and only rewords the summary. Its wording is shown only when every figure, name and level survives unchanged. Without Ollama, the computed wording is shown.

## DepEd basis

| Rule | Source |
|---|---|
| Grade components, transmutation, passing grade of 75, remediation below 75 | DepEd Order No. 8, s. 2015 |
| Proficiency levels: Beginning, Developing, Approaching Proficiency, Proficient, Advanced | DepEd Order No. 31, s. 2012 |
| Academic honors | DepEd Order No. 36, s. 2016 |
| School Forms SF1 to SF7 and e-class records | DepEd's official templates (`documentation/sf_templates/`, `grades/ecr_templates/`) |

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

5. **Optional: load the demo school.** This creates school ID `DEMO-ARMS` with accounts for every role. Their usernames end in `@demo.arms.edu.ph`, and they share the password in `DEMO_PASSWORD`. The command has `--reset`, `--remove` and `--dry-run` options.

   ```bash
   python manage.py seed_demo
   ```

6. **Train the forecaster.** Run it again after new grades come in.

   ```bash
   python manage.py train_ml_models
   ```

7. **Run the server**, then open http://127.0.0.1:8000.

   ```bash
   python manage.py runserver
   ```

8. **Optional: Poro AI.** Install [Ollama](https://ollama.com) and pull the model:

   ```bash
   ollama pull qwen2.5:1.5b
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
| `PORO_AI_ENABLED`, `OLLAMA_URL`, `PORO_AI_MODEL`, `PORO_AI_TIMEOUT` | Poro AI and its local model. |
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
| `heads/` | The School Head portal: dashboard, section briefs and Poro AI (`insights.py`), forecast charts (`forecasts.py`), School Performance, School Year |
| `registrars/` | The Registrar portal: enrollment, sections, teachers, grade validation, School Forms |
| `teachers/` | The Teacher portal: class records, e-class record uploads, adviser forms |
| `assessments/` | Online quizzes |
| `grades/`, `enrollment/`, `documentation/` | The e-class record reader, the SF1 reader and the DepEd school forms |
| `academics/`, `students/`, `attendance/`, `scheduling/`, `promotion/`, … | School structure, learners, attendance, class assignments and promotion records |
| `ml_engine/` | The grade forecaster and the `train_ml_models` command |
| `communication/` | Notifications and contact requests |
| `audit/` | Activity logs and anomaly detection (`python manage.py detect_anomalies`) |
| `core/` | Shared helpers: page caching, Excel template patching, the school form header |
| `templates/`, `static/` | Pages, styles, scripts, the ARMS logo and DepEd form templates for download |
