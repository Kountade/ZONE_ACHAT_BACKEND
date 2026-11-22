"""
Django settings for authentification project.
"""

from pathlib import Path
import os

BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# SÉCURITÉ
# ============================================================
SECRET_KEY = os.environ.get(
    'SECRET_KEY',
    "django-insecure-$232vni+0*(&kifn+=h=+z4le9mc=6fa@d*4fdw+xw-84@^&kj"
)

DEBUG = os.environ.get('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [
    h.strip() for h in os.environ.get(
        'ALLOWED_HOSTS', 'localhost,127.0.0.1'
    ).split(',') if h.strip()
]


# ============================================================
# ✅ FONCTION UTILITAIRE — filtre les origines invalides
# ============================================================
def _parse_origins(env_var_name, default):
    """
    Lit une variable d'env type 'http://a.com,https://b.com'.
    - Ignore les entrées vides ou sans '://'
    - Retombe sur `default` si rien de valide
    → Évite les erreurs 4_0.E001 et corsheaders.E013
    """
    raw = os.environ.get(env_var_name, "").strip()
    if not raw:
        return default
    origins = [
        o.strip()
        for o in raw.split(",")
        if o.strip() and "://" in o
    ]
    return origins or default


CORS_ALLOWED_ORIGINS = _parse_origins(
    "CORS_ALLOWED_ORIGINS",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)

CSRF_TRUSTED_ORIGINS = _parse_origins(
    "CSRF_TRUSTED_ORIGINS",
    [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:8000",
        "http://127.0.0.1:8000",
    ],
)

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

FRONTEND_URL = os.environ.get('FRONTEND_URL', 'http://localhost:5173/')
if not FRONTEND_URL.endswith('/'):
    FRONTEND_URL += '/'


# ============================================================
# APPLICATIONS
# ============================================================
INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    'knox',
    'corsheaders',
    'django_filters',
    'django_rest_passwordreset',
    'rest_framework',
    "users",
    "produits_stocks",
    "tresorerie",
    "achats_fournisseurs",
    "finances",
    "ventes_clients",
    "config",
]


# ============================================================
# MIDDLEWARE — ⚠️ CorsMiddleware en HAUT
# ============================================================
MIDDLEWARE = [
    "corsheaders.middleware.CorsMiddleware",         # ✅ déplacé en premier
    "django.middleware.security.SecurityMiddleware",
    'whitenoise.middleware.WhiteNoiseMiddleware',
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]


# ============================================================
# AUTHENTIFICATION & REST
# ============================================================
# ⚠️ En production, à mettre False :
CORS_ALLOW_ALL_ORIGINS = DEBUG   # True en dev, False en prod

CORS_ALLOW_CREDENTIALS = True

AUTH_USER_MODEL = 'users.CustomUser'
AUTHENTICATION_BACKENDS = [
    "django.contrib.auth.backends.ModelBackend",
]

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': ('knox.auth.TokenAuthentication',),
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated',
    ],
}


ROOT_URLCONF = "authentification.urls"

TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        'DIRS': [BASE_DIR / "templates"],
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

WSGI_APPLICATION = "authentification.wsgi.application"


# ============================================================
# DATABASE
# ============================================================
DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.sqlite3",
        "NAME": BASE_DIR / "db.sqlite3",
    }
}


# ============================================================
# PASSWORD VALIDATION
# ============================================================
AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]


# ============================================================
# EMAIL
# ============================================================
EMAIL_BACKEND = 'django.core.mail.backends.smtp.EmailBackend'
EMAIL_HOST = 'smtp.gmail.com'
EMAIL_PORT = 587
EMAIL_USE_TLS = True
EMAIL_HOST_USER = os.environ.get('EMAIL_HOST_USER', 'othyk2018@gmail.com')
EMAIL_HOST_PASSWORD = os.environ.get('EMAIL_HOST_PASSWORD', 'ueirfedbfnnaizps')
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


# ============================================================
# I18N
# ============================================================
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True


# ============================================================
# ✅ STATIC & MEDIA — n'inclut QUE les dossiers existants
# ============================================================
STATIC_URL = '/static/'
STATICFILES_DIRS = [
    d for d in [
        BASE_DIR / 'static',
        BASE_DIR / 'authentification' / 'static',
    ] if d.exists()
]
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media/'

IMAGE_MAX_SIZE = (800, 800)
THUMBNAIL_SIZE = (150, 150)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"