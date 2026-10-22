# CLAUDE.md

Guidance for Claude Code and other AI agents working in this repository.

## Project

ARMS is the AI-Enabled Academic Records Management System with Predictive Analytics and School Performance Prediction for Private Secondary Schools. It is a Django web system for Junior High (Grades 7 to 10) and Senior High (Grades 11 and 12) that follows DepEd rules. Four signed-in roles each have their own portal: System Administrator, School Head, Registrar and Teacher. The partner school is Northern Paramedical & Technological College of Panabo, Inc. (NPTCI).

## Commands

Run everything from the repository root with Python 3.12.

- Install: `pip install -r requirements.txt`
- Configure: copy `.env.example` to `.env` and fill it in. `DATABASE_URL` must point to the Supabase PostgreSQL database; SQLite is disabled on purpose.
- Run: `python manage.py runserver` (http://127.0.0.1:8000)
- Check: `python manage.py check` and `python manage.py makemigrations --check --dry-run`
- Page check for every role: `python .claude/skills/arms-verify/scripts/smoke_pages.py`
- Migrate: `python manage.py makemigrations <app>`, then `python manage.py migrate`
- Demo data: `python manage.py seed_demo` (school ID `DEMO-ARMS`; the accounts share `DEMO_PASSWORD` from `.env`)
- Machine-learning models: `python manage.py train_ml_models`

## Layout

| Path | What it holds |
|---|---|
| `config/` | Settings and URLs: `/` landing page, `/accounts/`, `/admin-panel/`, `/heads/`, `/registrars/`, `/teachers/`, `/assessments/`, `/quiz/<code>/` |
| `accounts/` | Sign-in (`ProfileBackend`), Google sign-in, Remember me, password reset, account settings, `seed_demo` |
| `admin_panel/` | System Administrator: schools, school years, grading periods, principal and registrar accounts, contact requests |
| `heads/` | School Head: Academic Dashboard, Poro AI section briefs (`heads/insights.py`), School Performance, users, Excel reports |
| `registrars/` | Registrar: SF1 enrollment, sections, teachers, grade validation, School Forms |
| `teachers/` | Teacher: class records, e-class record upload and review, submission to the registrar, adviser forms |
| `grades/`, `enrollment/`, `documentation/` | E-class records (`grades/ecr.py`), the SF1 reader (`enrollment/sf1.py`), DepEd school forms (`documentation/school_forms.py`) |
| `core/` | Shared helpers: page caching (`core/caching.py`), `xlsx_patch`, the school form header |
| `ml_engine/` | Trained XGBoost, Random Forest and K-Means models; the pages do not use them yet |
| `templates/`, `static/` | `templates/shared/portal_base.html` is the signed-in layout; shared CSS is in `static/shared/css/` |

## Rules

- **DepEd first.** Grades follow DepEd Order No. 8, s. 2015 (components, transmutation, passing grade 75, remediation below 75). Proficiency levels follow DepEd Order No. 31, s. 2012, and honors follow DepEd Order No. 36, s. 2016. Name the order in the interface wherever a rule comes from one.
- **No invented numbers.** Every figure in a report is computed in code by rules a person can check (`heads/insights.py`). Poro AI, a local Qwen model run through Ollama, only rewords a summary. Its text is shown only when every figure survives unchanged.
- **Patch DepEd templates, never re-save them.** Write into DepEd's Excel files with `core/xlsx_patch`; openpyxl drops their dropdowns and formulas. See the `deped-school-forms` skill.
- **The database is shared.** It is the team's Supabase Postgres, and its pooler allows 15 connections. Run one dev server at a time, and run experiments inside a transaction that is rolled back. Never wipe, reseed or bulk-edit data without asking.
- **Secrets stay in `.env`.** The file is git-ignored. Never print, log or commit its values. Tests use the in-memory (locmem) email backend, and nothing may send real email.
- **Keep the look.** Follow the `arms-brand-ui` skill: light surfaces, palette blue `#123499`, the purple brand gradient, one overall status, and "Show all" lists in dialogs. No emojis.
- **Names.** The system is ARMS; the old name Formify is retired. "LIS" means DepEd's Learner Information System. State facts about NPTCI only from its supplied seal and photos.
- **Cache.** Pages are cached per user and refreshed when data changes (`core/caching.py`). Set `PAGE_CACHE=False` in `.env` while troubleshooting.

## Skills

Project skills live in `.claude/skills/` (see its README for sources and licenses):

- `arms-brand-ui`: design rules for any page, chart, dialog or export.
- `deped-school-forms`: SF1 imports, e-class records and school forms on DepEd's templates.
- `arms-verify`: the checks to run before a commit.
- From providers: `frontend-design` (Anthropic), `web-design-guidelines` (Vercel) and `supabase-postgres-best-practices` (Supabase). Where `frontend-design` and `arms-brand-ui` disagree, `arms-brand-ui` wins.
