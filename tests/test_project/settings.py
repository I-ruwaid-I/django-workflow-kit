"""Django settings used by the test suite and the example applications."""

from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = "test-secret-key-not-for-production"

DEBUG = True

ALLOWED_HOSTS = ["*"]

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "rest_framework",
    "workflow_kit",
    "workflow_kit.dashboard",
    "tests.test_project.demo",
]

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "rest_framework.authentication.SessionAuthentication",
    ],
    "DEFAULT_RENDERER_CLASSES": [
        "rest_framework.renderers.JSONRenderer",
    ],
    "DEFAULT_PAGINATION_CLASS": "workflow_kit.api.pagination.WorkflowKitPagination",
    "EXCEPTION_HANDLER": "workflow_kit.api.exceptions.workflow_error_handler",
}

MIDDLEWARE = [
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
]

ROOT_URLCONF = "tests.test_project.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ],
        },
    },
]

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "test_db.sqlite3",
        # A file-backed test database (not the default in-memory one): the
        # versioning concurrency tests spawn threads with their own connections,
        # and Django ignores close() on in-memory DBs, which would leak and trip
        # the suite's ResourceWarning=error filter. The timeout lets concurrent
        # writer threads wait for the SQLite file lock instead of failing with
        # "database table is locked".
        "OPTIONS": {"timeout": 60},
        "TEST": {"NAME": BASE_DIR / "test_db_test.sqlite3"},
    }
}

AUTH_PASSWORD_VALIDATORS = []

PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.MD5PasswordHasher",
]

LANGUAGE_CODE = "en-us"

TIME_ZONE = "UTC"

USE_I18N = True

USE_TZ = True

STATIC_URL = "static/"

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media_test"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

MAILERS = {
    "default": {
        "BACKEND": "django.core.mail.backends.locmem.EmailBackend",
    },
}

WORKFLOW_KIT = {}

TEST_PASSWORD = "test-password-123"

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "loggers": {
        "workflow_kit": {
            "handlers": ["console"],
            "level": "WARNING",
            "propagate": True,
        },
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
        },
    },
}
