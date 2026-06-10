import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent

SECRET_KEY = os.environ.get("DJANGO_SECRET_KEY", "dev-only-ai-shell-secret-key")
DEBUG = os.environ.get("DJANGO_DEBUG", "1") == "1"
ALLOWED_HOSTS = [host.strip() for host in os.environ.get("ALLOWED_HOSTS", "*").split(",") if host.strip()]
RENDER_EXTERNAL_HOSTNAME = os.environ.get("RENDER_EXTERNAL_HOSTNAME")
if RENDER_EXTERNAL_HOSTNAME and RENDER_EXTERNAL_HOSTNAME not in ALLOWED_HOSTS:
    ALLOWED_HOSTS.append(RENDER_EXTERNAL_HOSTNAME)

INSTALLED_APPS = [
    "django.contrib.contenttypes",
    "django.contrib.staticfiles",
    "core",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "core.middleware.SimpleCorsMiddleware",
    "django.middleware.common.CommonMiddleware",
]

ROOT_URLCONF = "ai_backend.urls"
WSGI_APPLICATION = "ai_backend.wsgi.application"

DATABASE_URL = os.environ.get("DATABASE_URL")
if DATABASE_URL:
    import dj_database_url

    DATABASES = {
        "default": dj_database_url.parse(
            DATABASE_URL,
            conn_max_age=600,
            ssl_require=os.environ.get("DATABASE_SSL_REQUIRE", "1") == "1",
        )
    }
else:
    DATABASES = {
        "default": {
            "ENGINE": "django.db.backends.sqlite3",
            "NAME": BASE_DIR / "db.sqlite3",
        }
    }

LANGUAGE_CODE = "zh-hans"
TIME_ZONE = "Asia/Shanghai"
USE_I18N = True
USE_TZ = True

STATIC_URL = "static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STORAGES = {
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    }
}
DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"
DATA_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024
FILE_UPLOAD_MAX_MEMORY_SIZE = 10 * 1024 * 1024

ADMIN_USER = os.environ.get("ADMIN_USER", "admin")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "admin123")

SITE_BASE_URL = os.environ.get("SITE_BASE_URL", "").rstrip("/")
FRONTEND_USER_URL = os.environ.get("FRONTEND_USER_URL", "").rstrip("/")

ALIPAY_APP_ID = os.environ.get("ALIPAY_APP_ID", "")
ALIPAY_APP_PRIVATE_KEY = os.environ.get("ALIPAY_APP_PRIVATE_KEY", "")
ALIPAY_PUBLIC_KEY = os.environ.get("ALIPAY_PUBLIC_KEY", "")
ALIPAY_NOTIFY_URL = os.environ.get(
    "ALIPAY_NOTIFY_URL",
    f"{SITE_BASE_URL}/api/pay/alipay/notify" if SITE_BASE_URL else "",
)
ALIPAY_RETURN_URL = os.environ.get("ALIPAY_RETURN_URL", FRONTEND_USER_URL)
ALIPAY_DEBUG = os.environ.get("ALIPAY_DEBUG", "0") == "1"
ALIPAY_GATEWAY = os.environ.get(
    "ALIPAY_GATEWAY",
    "https://openapi-sandbox.dl.alipaydev.com/gateway.do"
    if os.environ.get("ALIPAY_DEBUG", "0") == "1"
    else "https://openapi.alipay.com/gateway.do",
)
