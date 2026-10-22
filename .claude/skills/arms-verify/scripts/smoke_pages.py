"""Open the main pages of every ARMS role, signed in, and report any page that fails.

Run from the project root (the folder with manage.py and .env):

    python .claude/skills/arms-verify/scripts/smoke_pages.py [--school DEMO-ARMS]

Signs in as the first active account of each role in the school (the demo school by default) and
requests each page through Django's test client. Everything runs inside one database transaction
that is rolled back, sessions live in signed cookies, Poro AI and the page cache are off, and mail
goes to memory, so the shared database and inboxes are untouched. Exit code 1 if a page fails.
"""
import os
import sys
import time
from pathlib import Path

ROOT = Path.cwd() if (Path.cwd() / 'manage.py').exists() else Path(__file__).resolve().parents[4]
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# .env never overrides variables that are already set
os.environ.update({'PORO_AI_ENABLED': 'False', 'PAGE_CACHE': 'False', 'GOOGLE_BINDING_REQUIRED': 'False',
                   'EMAIL_HOST_USER': '', 'EMAIL_HOST_PASSWORD': ''})
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

import django  # noqa: E402

django.setup()

from django.conf import settings  # noqa: E402
from django.db import transaction  # noqa: E402
from django.test import Client  # noqa: E402
from django.urls import reverse  # noqa: E402

from accounts.models import UserProfile  # noqa: E402

settings.EMAIL_BACKEND = 'django.core.mail.backends.locmem.EmailBackend'
settings.SESSION_ENGINE = 'django.contrib.sessions.backends.signed_cookies'

PAGES = {
    None: ['home', 'signin'],
    'admin': ['admin_panel:dashboard', 'admin_panel:school_list', 'admin_panel:principal_list',
              'admin_panel:registrar_list', 'admin_panel:request_list', 'account_settings'],
    'schoolhead': ['heads-ai-dashboard', 'heads-school-performance', 'heads-user-management', 'account_settings'],
    'registrar': ['registrars:dashboard', 'registrars:upload_class_list', 'registrars:section_list',
                  'registrars:teacher_list', 'registrars:grade_validation', 'registrars:school_forms', 'account_settings'],
    'teacher': ['teachers:dashboard', 'teachers:class_record_list', 'assessments:list', 'account_settings'],
}


def account(role, school_id):
    people = UserProfile.objects.filter(role=role, user__is_active=True).select_related('user', 'school').order_by('id')
    if role != 'admin':
        people = people.filter(school__school_id=school_id)
    return people.first()


def main():
    school_id = sys.argv[sys.argv.index('--school') + 1] if '--school' in sys.argv else 'DEMO-ARMS'
    failures = 0
    with transaction.atomic():
        for role, names in PAGES.items():
            client = Client(HTTP_HOST='127.0.0.1')
            who = 'not signed in'
            if role:
                profile = account(role, school_id)
                if profile is None:
                    print(f'-- {role}: no active account in {school_id}, skipped')
                    continue
                client.force_login(profile.user, backend=settings.AUTHENTICATION_BACKENDS[0])
                who = profile.user.username
            print(f'-- {role or "public"} ({who})')
            for name in names:
                url = reverse(name)
                start = time.perf_counter()
                try:
                    status = client.get(url).status_code
                    note = 'ok' if status < 400 else 'FAILED'
                except Exception as exc:                      # the view raised: show what, keep going
                    status, note = 'error', f'FAILED {type(exc).__name__}: {exc}'
                failures += note != 'ok'
                print(f'   {status!s:>5}  {1000 * (time.perf_counter() - start):6.0f} ms  {url}  {note if note != "ok" else ""}')
        transaction.set_rollback(True)
    print(f'{failures} page(s) failed.' if failures else 'Every page opened.')
    return 1 if failures else 0


if __name__ == '__main__':
    sys.exit(main())
