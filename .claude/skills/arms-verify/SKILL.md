---
name: arms-verify
description: Run ARMS's checks in order and report what fails (Django's system check, missing migrations, a signed-in page check for every role, and a secrets scan of the staged changes). Use before committing, after changing models, views, templates or settings, or when asked to "verify", "check", "test the pages" or "make sure it still works".
---

# ARMS Verify

Run these from the repository root (the folder with `manage.py` and `.env`), in order. A step that fails stops the run: report the step, the command and its output, then fix it or ask.

1. **System check**

   ```
   python manage.py check
   ```

   Expected: `System check identified no issues (0 silenced).`

2. **Missing migrations** (a dry run; nothing is written)

   ```
   python manage.py makemigrations --check --dry-run
   ```

   Expected: `No changes detected`. If it lists a migration, the models changed without one. Create it with `python manage.py makemigrations <app>` only when the model change was intended, and say so in the report.

3. **Pages for every role**

   ```
   python .claude/skills/arms-verify/scripts/smoke_pages.py
   ```

   This signs in as the first active System Administrator, and the first School Head, Registrar and Teacher of the demo school (`--school <ID>` picks another school). It opens each portal's main pages and prints the status and time of each one. Everything runs in one database transaction that is rolled back, sessions live in signed cookies, Poro AI and the page cache are off, and mail stays in memory. Expected: `Every page opened.` Any line marked `FAILED` names the URL and the exception.

4. **What changed**
   - DepEd forms or e-class records: also run "Check a generated form" in the `deped-school-forms` skill.
   - Templates or CSS: look at the page signed in, at desktop and phone width, against the `arms-brand-ui` rules.

5. **Before committing**
   - `git diff --cached --stat` lists only files you meant to change.
   - `.env`, `db.sqlite3*`, `.cache/`, `media/` and `design/screens/` are never staged.
   - `git diff --cached` contains no keys, passwords, tokens or `DATABASE_URL` values.

## Rules for checking

- The database is the team's shared Supabase Postgres, and its pooler allows 15 connections. Run one dev server at a time and never point a test at production data without rolling it back.
- The apps' `tests.py` files are still empty, so `python manage.py test` checks nothing yet. Use step 3.
- Nothing sends real email while checking. Use the locmem backend, or leave `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD` blank for a test server.
- For a signed-in look at a page, run a separate dev server on a free port. Leave the team's own `runserver` on 8000 alone. Give it its own `*.localhost` host name (cookies ignore ports) and run it with `PAGE_CACHE=False` and `GOOGLE_BINDING_REQUIRED=False`. Stop it when done.

## Report

End with one line per step: passed, failed (with the first error), or skipped (with the reason).
