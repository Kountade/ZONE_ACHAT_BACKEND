"""
Django settings for authentification project.
"""

from pathlib import Path
import os

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent


# ============================================================
# SÉCURITÉ
# ============================================================
SECRET_KEY = os.environ.get(
    'SECRET_KEY', 
    "django-insecure-$232vni+0*(&kifn+=h=+z4le9mc=6fa@d*4fdw+xw-84@^&kj"
)

DEBUG = True

ALLOWED_HOSTS = [
    "zoneachat-backend.onrender.com", # ✅ Ton backend
    "localhost",
    "127.0.0.1",
]

CSRF_TRUSTED_ORIGINS = [
    'https://zoneachat-backend.onrender.com',
    'https://zoneachat.onrender.com', # ✅ Ton frontend
]

SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')

# ✅ LIGNE CRUCIALE : Le lien dans l'email pointera vers ton frontend React
FRONTEND_URL = 'https://zoneachat.onrender.com/' 


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
    "config"
]


# ============================================================
# MIDDLEWARE
# ============================================================
MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    'whitenoise.middleware.WhiteNoiseMiddleware',
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
    "corsheaders.middleware.CorsMiddleware",
]


# ============================================================
# CORS
# ============================================================
CORS_ALLOW_ALL_ORIGINS = True
CORS_ALLOWED_ORIGINS = [
    "https://zoneachat-backend.onrender.com",
    "https://zoneachat.onrender.com", # ✅ Ton frontend
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]


# ============================================================
# AUTHENTIFICATION & REST
# ============================================================
AUTH_USER_MODEL = 'users.CustomUser'
AUTHENTICATION_BACKENDS = [
    "users.auth_backend.EmailAuthBackend", # ✅ Ajouté pour le login email
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
# DATABASE (SQLite)
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
EMAIL_HOST_USER = 'othyk2018@gmail.com'
EMAIL_HOST_PASSWORD = 'ueirfedbfnnaizps'
DEFAULT_FROM_EMAIL = EMAIL_HOST_USER


# ============================================================
# I18N
# ============================================================
LANGUAGE_CODE = "fr-fr"
TIME_ZONE = "Africa/Dakar"
USE_I18N = True
USE_TZ = True


# ============================================================
# STATIC & MEDIA
# ============================================================
STATIC_URL = '/static/'
STATICFILES_DIRS = [os.path.join(BASE_DIR, 'static')]
STATIC_ROOT = os.path.join(BASE_DIR, 'staticfiles')
STATICFILES_STORAGE = "whitenoise.storage.CompressedManifestStaticFilesStorage"

MEDIA_URL = '/media/'
MEDIA_ROOT = os.path.join(BASE_DIR, 'media/')

IMAGE_MAX_SIZE = (800, 800)
THUMBNAIL_SIZE = (150, 150)

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"