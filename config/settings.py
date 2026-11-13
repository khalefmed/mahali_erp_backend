"""Single settings module, configured entirely from environment variables (see .env.example)."""

from datetime import timedelta
from pathlib import Path

import environ

BASE_DIR = Path(__file__).resolve().parent.parent

env = environ.Env()
environ.Env.read_env(BASE_DIR / ".env", overwrite=False)

DEBUG = env.bool("DJANGO_DEBUG", default=False)
SECRET_KEY = env("DJANGO_SECRET_KEY")
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
WEB_APP_URL = env("WEB_APP_URL", default="http://localhost:3000").rstrip("/")
ADMIN_PATH = env("DJANGO_ADMIN_PATH", default="")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "django.contrib.postgres",
    "rest_framework",
    "rest_framework_simplejwt.token_blacklist",
    "django_filters",
    "drf_spectacular",
    "pgtrigger",
    "pghistory",
    "apps.core",
    "apps.accounts",
    "apps.stores",
    "apps.console",
    "apps.catalog",
    "apps.inventory",
    "apps.sales",
    "apps.reports",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "apps.core.middleware.RequestContextMiddleware",
    "pghistory.middleware.HistoryMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
            ]
        },
    }
]

# --- Database ---------------------------------------------------------------
# The role in DATABASE_URL must NOT be a superuser and must not have BYPASSRLS:
# row-level security is what isolates stores from each other.
DATABASES = {"default": env.db("DATABASE_URL")}
# Every request runs in one transaction, so `SET LOCAL app.store_id` lasts exactly
# as long as the request (see apps.core.tenancy).
DATABASES["default"]["ATOMIC_REQUESTS"] = True
DATABASES["default"]["CONN_MAX_AGE"] = env.int("DB_CONN_MAX_AGE", default=60)
DATABASES["default"]["CONN_HEALTH_CHECKS"] = True
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

CACHES = {
    "default": {
        "BACKEND": "django_redis.cache.RedisCache",
        "LOCATION": env("REDIS_URL", default="redis://localhost:6379/0"),
    }
}

# --- Auth -------------------------------------------------------------------
AUTH_USER_MODEL = "accounts.User"
PASSWORD_HASHERS = [
    "django.contrib.auth.hashers.Argon2PasswordHasher",
    "django.contrib.auth.hashers.PBKDF2PasswordHasher",
]
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {
        "NAME": "django.contrib.auth.password_validation.MinimumLengthValidator",
        "OPTIONS": {"min_length": 10},
    },
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
    {"NAME": "apps.accounts.validators.PwnedPasswordValidator"},
]
PWNED_PASSWORDS_CHECK = env.bool("PWNED_PASSWORDS_CHECK", default=not DEBUG)
PASSWORD_RESET_TIMEOUT = 30 * 60

EMAIL_CODE_TTL = timedelta(minutes=10)
EMAIL_CODE_MAX_ATTEMPTS = 3
INVITATION_TTL = timedelta(days=7)
IMPERSONATION_TTL = timedelta(minutes=30)

SIMPLE_JWT = {
    "ACCESS_TOKEN_LIFETIME": timedelta(minutes=10),
    "REFRESH_TOKEN_LIFETIME": timedelta(days=30),
    "ROTATE_REFRESH_TOKENS": True,
    "BLACKLIST_AFTER_ROTATION": True,
    "UPDATE_LAST_LOGIN": False,
    "ALGORITHM": "HS256",
    "SIGNING_KEY": env("JWT_SIGNING_KEY", default=SECRET_KEY),
    "AUTH_HEADER_TYPES": ("Bearer",),
    "USER_ID_FIELD": "id",
    "USER_ID_CLAIM": "sub",
}

# --- API --------------------------------------------------------------------
REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": ["apps.accounts.authentication.MerchantJWTAuthentication"],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
        "apps.accounts.permissions.NotReadOnlySession",
    ],
    "DEFAULT_RENDERER_CLASSES": ["rest_framework.renderers.JSONRenderer"],
    "DEFAULT_PARSER_CLASSES": [
        "rest_framework.parsers.JSONParser",
        "rest_framework.parsers.MultiPartParser",
    ],
    "DEFAULT_PAGINATION_CLASS": "apps.core.pagination.PageNumberPagination",
    "DEFAULT_FILTER_BACKENDS": [
        "django_filters.rest_framework.DjangoFilterBackend",
        "rest_framework.filters.OrderingFilter",
        "rest_framework.filters.SearchFilter",
    ],
    "DEFAULT_SCHEMA_CLASS": "apps.core.schema.AutoSchema",
    "EXCEPTION_HANDLER": "apps.core.exceptions.problem_exception_handler",
    "DEFAULT_THROTTLE_RATES": {
        "auth_ip": "20/min",
        "auth_email": "5/min",
        "email_code": "5/hour",
        "user": "600/min",
    },
    "DEFAULT_THROTTLE_CLASSES": ["rest_framework.throttling.UserRateThrottle"],
    "TEST_REQUEST_DEFAULT_FORMAT": "json",
    "COERCE_DECIMAL_TO_STRING": True,
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Mahali ERP API",
    "DESCRIPTION": (
        "API of Mahali ERP. Errors use RFC 9457 problem details with a stable `code` "
        "that the web app translates. Money is integer MRU. Store-scoped routes live "
        "under `/api/v1/stores/{store_id}/`."
    ),
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    "COMPONENT_SPLIT_REQUEST": True,
    "ENUM_NAME_OVERRIDES": {
        "StoreStatusEnum": "apps.stores.models.StoreStatus",
        "StoreRoleEnum": "apps.stores.roles.Role",
        "InvitableRoleEnum": [
            ("manager", "Gérant"),
            ("cashier", "Caissier"),
            ("stock_keeper", "Magasinier"),
            ("seller", "Vendeur"),
        ],
        "StaffRoleEnum": "apps.console.models.StaffRole",
        "DocumentKindEnum": "apps.stores.models.DocumentKind",
        "TradeEnum": "apps.stores.models.Trade",
        "ProductRequestStatusEnum": "apps.catalog.models.ProductRequestStatus",
        "SaleStatusEnum": "apps.sales.models.Sale.Status",
        "CashSessionStatusEnum": "apps.sales.models.CashSession.Status",
        "CreditStatusEnum": "apps.sales.models.Credit.Status",
        "SerialStatusEnum": "apps.inventory.models.SerialStatus",
        "PaymentKindEnum": "apps.sales.models.Payment.Kind",
        "MovementKindEnum": "apps.inventory.models.MovementKind",
        "InvitationStatusEnum": ["pending", "accepted", "revoked", "expired"],
        "ProductStatusEnum": "apps.catalog.models.ProductStatus",
        "PaymentMethodEnum": "apps.sales.models.PaymentMethod",
        "ExpenseCategoryEnum": "apps.sales.models.ExpenseCategory",
        "AdjustmentReasonEnum": "apps.inventory.models.AdjustmentReason",
    },
    "POSTPROCESSING_HOOKS": ["drf_spectacular.hooks.postprocess_schema_enums"],
    "SCHEMA_PATH_PREFIX": r"/api/v1",
    "SECURITY": [{"jwtAuth": []}],
    "APPEND_COMPONENTS": {
        "securitySchemes": {"jwtAuth": {"type": "http", "scheme": "bearer", "bearerFormat": "JWT"}}
    },
}

# --- Files ------------------------------------------------------------------
# Store documents (ID cards, storefront photos) are private: never served by a
# public URL, only through a signed, audited download view.
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
        "OPTIONS": {"location": env("MEDIA_ROOT", default=str(BASE_DIR / "media"))},
    },
    "staticfiles": {"BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage"},
}
STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
FILE_UPLOAD_MAX_MEMORY_SIZE = 5 * 1024 * 1024
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
MAX_DOCUMENT_SIZE = 8 * 1024 * 1024
SIGNED_URL_TTL = 5 * 60

# --- Email ------------------------------------------------------------------
vars().update(env.email_url("EMAIL_URL", default="consolemail://"))
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="Mahali <no-reply@mahali.infinity.mr>")
EMAIL_TIMEOUT = 10

# --- i18n -------------------------------------------------------------------
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("ar", "العربية"), ("en", "English")]
TIME_ZONE = "Africa/Nouakchott"
USE_I18N = True
USE_TZ = True

# --- Security ---------------------------------------------------------------
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
X_FRAME_OPTIONS = "DENY"
SESSION_COOKIE_HTTPONLY = True
CSRF_TRUSTED_ORIGINS = env.list("CSRF_TRUSTED_ORIGINS", default=[])
if not DEBUG:
    SECURE_SSL_REDIRECT = env.bool("SECURE_SSL_REDIRECT", default=True)
    SECURE_REDIRECT_EXEMPT = [r"^health/?$"]
    SECURE_HSTS_SECONDS = 60 * 60 * 24 * 365
    SECURE_HSTS_INCLUDE_SUBDOMAINS = True
    SESSION_COOKIE_SECURE = True
    CSRF_COOKIE_SECURE = True

LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "json": {
            "()": "apps.core.logging.JsonFormatter",
        }
    },
    "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "json"}},
    "root": {"handlers": ["console"], "level": env("LOG_LEVEL", default="INFO")},
    "loggers": {"django.db.backends": {"level": "WARNING"}},
}

SENTRY_DSN = env("SENTRY_DSN", default="")
if SENTRY_DSN:
    import sentry_sdk

    sentry_sdk.init(
        dsn=SENTRY_DSN,
        environment=env("SENTRY_ENVIRONMENT", default="production"),
        send_default_pii=False,
        traces_sample_rate=0.0,
    )
