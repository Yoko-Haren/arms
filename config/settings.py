"""
Django settings for config project.

For more information on this file, see
https://docs.djangoproject.com/en/4.2/topics/settings/

For the full list of settings and their values, see
https://docs.djangoproject.com/en/4.2/ref/settings/
"""

from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured
from django.core.management.utils import get_random_secret_key

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# =============================================================================
# CORE
# =============================================================================

# Never commit an application secret. Local development can use a temporary
# key, while every non-debug deployment must provide DJANGO_SECRET_KEY.
DEBUG = os.environ.get('DJANGO_DEBUG', 'True').lower() in ('1', 'true', 'yes')
SECRET_KEY = os.environ.get('DJANGO_SECRET_KEY')
if not SECRET_KEY:
    if DEBUG:
        SECRET_KEY = get_random_secret_key()
    else:
        raise ImproperlyConfigured('DJANGO_SECRET_KEY must be set when DEBUG is False.')

ALLOWED_HOSTS = ['127.0.0.1', 'localhost']


# =============================================================================
# APPLICATIONS
# =============================================================================

INSTALLED_APPS = [
    # 'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    # Project apps
    'accounts',
    'academics',
    'attendance',
    'admin_panel',
    'audit',
    'communication',
    'configuration',
    'documentation',
    'enrollment',
    'evaluation',
    'grades',
    'heads',
    'personnel',
    'promotion',
    'registrars',
    'scheduling',
    'students',
    'teachers',
    'transfers',
    'ml_engine',
    'assessments',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [BASE_DIR / 'templates'],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'


# =============================================================================
# DATABASE
# =============================================================================

DATABASE_URL = os.environ.get('DATABASE_URL')

# Use Supabase Postgres when DATABASE_URL is configured. SQLite remains the
# zero-configuration local-development fallback.
if DATABASE_URL:
    # This dependency is only needed when the Supabase Postgres connection is
    # enabled. Keeping it local preserves the SQLite fallback for a fresh
    # local checkout before optional deployment dependencies are installed.
    import dj_database_url

    DATABASES = {
        'default': dj_database_url.config(
            default=DATABASE_URL,
            conn_max_age=600,
            conn_health_checks=True,
        )
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',
            'NAME': BASE_DIR / 'db.sqlite3',
        }
    }

# Supabase credentials are intentionally environment-only. The anon key is
# used for user-facing Auth requests; keep the service-role key server-only.
SUPABASE_URL = os.environ.get('SUPABASE_URL', '')
SUPABASE_ANON_KEY = os.environ.get('SUPABASE_ANON_KEY', '')
SUPABASE_SERVICE_ROLE_KEY = os.environ.get('SUPABASE_SERVICE_ROLE_KEY', '')


# =============================================================================
# AUTHENTICATION
# =============================================================================

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]

LOGIN_URL = '/accounts/signin/'
LOGOUT_REDIRECT_URL = '/accounts/signin/'


# =============================================================================
# INTERNATIONALIZATION
# =============================================================================

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'Asia/Manila'
USE_I18N = True
USE_TZ = True


# =============================================================================
# STATIC & MEDIA FILES
# =============================================================================

STATIC_URL = 'static/'
STATICFILES_DIRS = [BASE_DIR / 'static']
STATIC_ROOT = BASE_DIR / 'staticfiles'   # for collectstatic in production

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'          # for profile photos, signatures, logos


# =============================================================================
# DEFAULT PRIMARY KEY
# =============================================================================

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'


# =============================================================================
# SECURITY
# =============================================================================

# Session
SESSION_COOKIE_HTTPONLY = True
SESSION_EXPIRE_AT_BROWSER_CLOSE = True
SESSION_COOKIE_AGE = 28800  # 8 hours

# CSRF — set HTTPONLY False so JS (AJAX forms) can read the token from the cookie
CSRF_COOKIE_HTTPONLY = False
CSRF_USE_SESSIONS = False

# Misc headers
X_FRAME_OPTIONS = 'DENY'
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_BROWSER_XSS_FILTER = True

# HTTPS-related — all False for localhost development.
# Set these to True when you deploy behind SSL.
SESSION_COOKIE_SECURE = False
CSRF_COOKIE_SECURE = False
SECURE_SSL_REDIRECT = False
SECURE_HSTS_SECONDS = 0


# =============================================================================
# ANOMALY DETECTION (opt-in via env var)
# =============================================================================
# Previously this ran at import time, which executed during every management
# command (migrate, makemigrations, tests, etc.). It's now opt-in and should
# be triggered from a management command or AppConfig.ready() instead.
#
# To run manually:
#     python manage.py run_anomaly_detection
#
# To auto-run on startup, set RUN_ANOMALY_DETECTION=True in your environment
# and uncomment the AppConfig approach in accounts/apps.py (see below).

RUN_ANOMALY_DETECTION = os.environ.get('RUN_ANOMALY_DETECTION', 'False') == 'True'
