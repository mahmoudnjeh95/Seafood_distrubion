"""Settings shared by every environment. Environment-specific files import from here."""

from pathlib import Path

import django_stubs_ext
import environ

# Lets typed code write ModelAdmin[Model], DecimalField[...] and similar at runtime.
django_stubs_ext.monkeypatch()

BASE_DIR = Path(__file__).resolve().parent.parent.parent  # backend/
REPO_ROOT = BASE_DIR.parent

env = environ.Env()
# A .env file at the repository root is optional; real environments use real env vars.
environ.Env.read_env(REPO_ROOT / ".env", overwrite=False)

SECRET_KEY = env("DJANGO_SECRET_KEY", default="")
DEBUG = env.bool("DJANGO_DEBUG", default=False)
ALLOWED_HOSTS = env.list("DJANGO_ALLOWED_HOSTS", default=[])
CSRF_TRUSTED_ORIGINS = env.list("DJANGO_CSRF_TRUSTED_ORIGINS", default=[])
# The company the public site sells for (D-186); empty: the oldest active organization.
PUBLIC_SITE_ORGANIZATION_ID = env.int("PUBLIC_SITE_ORGANIZATION_ID", default=None)

DJANGO_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
]
THIRD_PARTY_APPS = [
    "rest_framework",
    "drf_spectacular",
]
LOCAL_APPS = [
    "apps.core",
    "apps.catalog",
    "apps.partners",
    "apps.inventory",
    "apps.boxes",
    "apps.fleet",
    "apps.purchasing",
    "apps.sales",
    "apps.hr",
    "apps.expenses",
    "apps.partnerships",
    "apps.closing",
    "apps.reports",
    "apps.dayclose",
    "apps.documents",
    "apps.doclist",
    "apps.dataimport",
    "apps.notifications",
    "apps.storefront",
    "apps.treasury",
    "apps.demo",
]
INSTALLED_APPS = DJANGO_APPS + THIRD_PARTY_APPS + LOCAL_APPS

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "apps.core.middleware.RequestSizeLimitMiddleware",
    "apps.core.middleware.AdminLoginThrottleMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.locale.LocaleMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "apps.core.middleware.UserLanguageMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

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
    "default": env.db("DATABASE_URL", default="postgres://frutti:frutti@localhost:5432/frutti"),
}
# Login throttling counts attempts here (D-023, D-108). The default in-process cache is per server process,
# so with several processes every limit is multiplied: production sets DJANGO_CACHE_URL to the shared Redis.
CACHES = {
    "default": (
        {"BACKEND": "django.core.cache.backends.redis.RedisCache", "LOCATION": env("DJANGO_CACHE_URL")}
        if env("DJANGO_CACHE_URL", default="")
        else {"BACKEND": "django.core.cache.backends.locmem.LocMemCache"}
    ),
}

DATABASES["default"]["ATOMIC_REQUESTS"] = False  # transactions are explicit, in services
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
# Session and CSRF cookies (D-108): scripts cannot read the session, and neither cookie travels with a request
# started from another site. The apps read the CSRF cookie themselves, so that one is not HttpOnly.
SESSION_COOKIE_HTTPONLY = True
SESSION_COOKIE_SAMESITE = "Lax"
CSRF_COOKIE_SAMESITE = "Lax"
X_FRAME_OPTIONS = "DENY"
SECURE_REFERRER_POLICY = "same-origin"

AUTH_USER_MODEL = "core.User"

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

# French first; Arabic is planned (right-to-left), see docs/phases/00-foundations.md P0-T08.
LANGUAGE_CODE = "fr"
LANGUAGES = [("fr", "Français"), ("ar", "العربية")]
TIME_ZONE = "Africa/Tunis"
USE_I18N = True
# Server messages are written in French; other languages get .po files here (needs GNU gettext).
LOCALE_PATHS = [BASE_DIR / "locale"]
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
# The largest API request body: an 8 MB photo or PDF plus its form fields (D-108).
MAX_REQUEST_BYTES = 10 * 1024 * 1024

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

# E-mail (D-206): documents leave from the company's mailbox. Without EMAIL_HOST nothing is sent (the console
# backend prints them in development); production sets the provider's SMTP account in the environment.
EMAIL_HOST = env("EMAIL_HOST", default="")
EMAIL_PORT = env.int("EMAIL_PORT", default=587)
EMAIL_HOST_USER = env("EMAIL_HOST_USER", default="")
EMAIL_HOST_PASSWORD = env("EMAIL_HOST_PASSWORD", default="")
EMAIL_USE_TLS = env.bool("EMAIL_USE_TLS", default=True)
EMAIL_USE_SSL = env.bool("EMAIL_USE_SSL", default=False)
EMAIL_TIMEOUT = 20
DEFAULT_FROM_EMAIL = env("DEFAULT_FROM_EMAIL", default="contact@fruttidelmare.com")
EMAIL_BACKEND = env(
    "EMAIL_BACKEND",
    default="django.core.mail.backends.smtp.EmailBackend"
    if EMAIL_HOST
    else "django.core.mail.backends.console.EmailBackend",
)

# Background jobs (D-071). Redis is the broker; with CELERY_EAGER the job runs inside the request, which is
# what `make backend` and the tests do (no Redis, no worker needed). Staging and production run a worker.
CELERY_BROKER_URL = env("CELERY_BROKER_URL", default="redis://localhost:6379/0")
CELERY_TASK_ALWAYS_EAGER = env.bool("CELERY_EAGER", default=False)
CELERY_TASK_EAGER_PROPAGATES = False
CELERY_TASK_TIME_LIMIT = 120
CELERY_BROKER_CONNECTION_RETRY_ON_STARTUP = True

REST_FRAMEWORK = {
    "DEFAULT_AUTHENTICATION_CLASSES": [
        "apps.core.authentication.SessionAuthentication",
    ],
    "DEFAULT_PERMISSION_CLASSES": [
        "rest_framework.permissions.IsAuthenticated",
    ],
    "DEFAULT_SCHEMA_CLASS": "drf_spectacular.openapi.AutoSchema",
    # Business-rule errors raised by services become 400 answers (apps/core/api/exceptions.py).
    "EXCEPTION_HANDLER": "apps.core.api.exceptions.exception_handler",
    # Amounts travel as strings so no precision is lost (docs/ARCHITECTURE.md rule 1).
    "COERCE_DECIMAL_TO_STRING": True,
    # Login attempts, per address and per account (apps/core/authentication.py).
    "DEFAULT_THROTTLE_RATES": {
        "login_ip": "30/min",
        "login_username": "8/min",
        "admin_login": "8/min",
        "password_change": "8/min",
        # The public site (D-186): the catalogue, and the requests a visitor sends.
        "site_catalog": "120/min",
        "site_request": "10/hour",
    },
}

SPECTACULAR_SETTINGS = {
    "TITLE": "Frutti Del Mare ERP API",
    "VERSION": "1.0.0",
    "SERVE_INCLUDE_SCHEMA": False,
    # The schema is generated offline for the TS client (make gen-api); online it needs a login.
    "SERVE_PERMISSIONS": ["apps.core.permissions.IsOwnerOrManager"],
    # Choice sets get stable names after their model, not their field: several models have a `kind`,
    # and "status" and "method" will exist on sales documents too.
    "ENUM_NAME_OVERRIDES": {
        # D-186 · public site
        "WebRequestKindEnum": "apps.storefront.models.WebRequestKind",
        "WebRequestStatusEnum": "apps.storefront.models.WebRequestStatus",
        "CustomerKindEnum": "apps.partners.models.CustomerKind",
        "SupplierInvoiceStatusEnum": "apps.purchasing.models.SupplierInvoiceStatus",
        "PaymentMethodEnum": "apps.purchasing.models.PaymentMethod",
        "PurchaseOrderStatusEnum": "apps.purchasing.models.PurchaseOrderStatus",
        "FieldPurchaseStatusEnum": "apps.purchasing.models.FieldPurchaseStatus",
        "PaymentTermsEnum": "apps.purchasing.models.PaymentTerms",
        "FieldPurchaseActionEnum": "apps.purchasing.models.FieldPurchaseAction",
        "StockLocationKindEnum": "apps.inventory.models.LocationKind",
        "TransferKindEnum": "apps.inventory.models.TransferKind",
        "TransferStatusEnum": "apps.inventory.models.TransferStatus",
        "LossStatusEnum": "apps.inventory.models.LossStatus",
        "LossReasonEnum": "apps.inventory.models.LossReason",
        "CountStatusEnum": "apps.inventory.models.CountStatus",
        # P1-T14 · returnable boxes
        "BoxTypeEnum": "apps.boxes.models.BoxType",
        "BoxMovementKindEnum": "apps.boxes.models.BoxMovementKind",
        "QuoteStatusEnum": "apps.sales.models.QuoteStatus",
        # P2-T04 · sales
        "SaleStatusEnum": "apps.sales.models.SaleStatus",
        "SalePaymentMethodEnum": "apps.sales.models.SalePaymentMethod",
        "CustomerPaymentMethodEnum": "apps.sales.models.CustomerPaymentMethod",
        "InstrumentKindEnum": "apps.treasury.models.InstrumentKind",
        "InstrumentStatusEnum": "apps.treasury.models.InstrumentStatus",
        "InstrumentDirectionEnum": "apps.treasury.models.InstrumentDirection",
        "SalePriceSourceEnum": "apps.sales.models.PriceSource",
        # P2-T05 · invoices
        "InvoiceStatusEnum": "apps.sales.models.InvoiceStatus",
        "EInvoiceStatusEnum": "apps.sales.models.EInvoiceStatus",
        "CreditNoteKindEnum": "apps.sales.models.CreditNoteKind",
        # P2-T07 · customer returns
        "CreditNoteStockEnum": "apps.sales.models.CreditNoteStock",
        # P2-T06 · customer credit
        "SaleCreditStatusEnum": "apps.sales.models.CreditStatus",
        "CreditPolicyEnum": "apps.sales.models.CreditPolicy",
        "SalaryStatusEnum": "apps.hr.models.SalaryStatus",
        "SalaryPaymentMethodEnum": "apps.hr.models.SalaryPaymentMethod",
        "ExpenseStatusEnum": "apps.expenses.models.ExpenseStatus",
        "LotCostKindEnum": "apps.expenses.models.LotCostKind",
        "WorkTypeEnum": "apps.expenses.models.WorkType",
        # P5-T02 / P5-T05 · cold-room cost, general costs
        "LotCostAdjustmentKindEnum": "apps.expenses.models.LotCostAdjustmentKind",
        # P6-T01 / P6-T02 · partnership lots and lot results
        "PartnershipStatusEnum": "apps.partnerships.models.PartnershipStatus",
        "CapitalEntryKindEnum": "apps.partnerships.models.CapitalEntryKind",
        "LotResultStatusEnum": "apps.closing.models.LotResultStatus",
        "DayClosingStatusEnum": "apps.dayclose.models.DayClosingStatus",
        "LotOutcomeEnum": "apps.closing.models.LotOutcome",
        "LotStateEnum": "apps.closing.models.LotState",
        # P6-T03 · settlement with the partner (its payment methods are `PaymentMethodEnum`)
        "ProfitShareKindEnum": "apps.partnerships.models.ProfitShareKind",
        "SettlementStateEnum": "apps.closing.models.SettlementState",
        # P6-T06 · monthly closing
        "MonthlyClosingStatusEnum": "apps.closing.models.MonthlyClosingStatus",
        "MonthStateEnum": "apps.closing.models.MonthState",
        "DocumentTypeEnum": "apps.core.documents.DOCUMENT_TYPE_CHOICES",
        "DocumentToneEnum": "apps.core.documents.TONE_CHOICES",
        "PartnerSideEnum": "apps.core.documents.PARTNER_SIDE_CHOICES",
    },
}
