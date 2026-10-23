"""Ready-made emails to the ARMS administrator.

Instead of showing the address on every page, the pages offer one button that opens Gmail (or another
email app) with the subject and a short template already filled in. The school template asks for what
the admin portal needs to create the school, its school year and the first accounts.
"""
from functools import lru_cache
from urllib.parse import quote, urlencode

from django.conf import settings

SCHOOL_SUBJECT = 'ARMS school account request'
SCHOOL_BODY = """Hello ARMS team,

We would like to use ARMS at our school. Our details are below.

SCHOOL
School name:
DepEd School ID:
Short name or acronym:
Address:
Contact number:
School email domain (for example, @ourschool.edu.ph):

SCHOOL YEAR
School year to start (for example, 2026-2027):
First and last day of classes:
Grading periods (quarters, semesters or trimesters):
Grade levels (for example, Grades 7 to 12):

PRINCIPAL OR SCHOOL HEAD
Full name:
Position (for example, Principal or School Head):
Email address:

REGISTRAR
Full name:
Email address:

CONTACT PERSON
Full name and position:
Mobile number:

Thank you.
"""

HELP_SUBJECT = 'ARMS sign-in help'
HELP_BODY = """Hello ARMS team,

I need help signing in to ARMS.

Full name:
School:
Role (teacher, registrar, school head or administrator):
Username or email I sign in with:
What happened (for example, my account is locked, or the reset code did not arrive):

Thank you.
"""


def gmail_link(subject, body):
    """Opens a new message in Gmail on the web, addressed to the ARMS administrator."""
    query = urlencode({'view': 'cm', 'fs': '1', 'to': settings.ARMS_CONTACT_EMAIL, 'su': subject, 'body': body},
                      quote_via=quote)
    return f'https://mail.google.com/mail/?{query}'


def mailto_link(subject, body):
    """The same message for any other email app."""
    query = urlencode({'subject': subject, 'body': body.replace('\n', '\r\n')}, quote_via=quote)
    return f'mailto:{settings.ARMS_CONTACT_EMAIL}?{query}'


@lru_cache(maxsize=4)
def _links(address):
    return {
        'school_gmail': gmail_link(SCHOOL_SUBJECT, SCHOOL_BODY),
        'school_mailto': mailto_link(SCHOOL_SUBJECT, SCHOOL_BODY),
        'help_gmail': gmail_link(HELP_SUBJECT, HELP_BODY),
        'help_mailto': mailto_link(HELP_SUBJECT, HELP_BODY),
    }


def links():
    return _links(settings.ARMS_CONTACT_EMAIL)
