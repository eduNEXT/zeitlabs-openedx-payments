"""
These settings are here to use during tests, because django requires them.

In a real-world use case, apps in this project are installed into other
Django applications, so these settings will not be used.
"""
from os.path import abspath, dirname, join


def root(*args):
    """
    Get the absolute path of the given path relative to the project root.
    """
    return join(abspath(dirname(__file__)), *args)

USE_TZ = True
TIME_ZONE = 'UTC'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': 'default.db',
        'USER': '',
        'PASSWORD': '',
        'HOST': '',
        'PORT': '',
    }
}

INSTALLED_APPS = (
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.messages',
    'django.contrib.sites',
    'django.contrib.sessions',
    'waffle',
    'fake_models',
    'zeitlabs_payments',
)

LOCALE_PATHS = [
    root('zeitlabs_payments', 'conf', 'locale'),
]

ROOT_URLCONF = 'tests.urls'

SECRET_KEY = 'insecure-secret-key'

# Invoice pages answer only on the host an invoice was issued on, and the tests ask for them on several.
ALLOWED_HOSTS = ['*']

MIDDLEWARE = (
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    # As in the LMS: the hand-off records the origin of the site the request is for.
    'django.contrib.sites.middleware.CurrentSiteMiddleware',
    # As in the LMS: edx-toggles remembers what it read in the request cache, which this middleware empties between
    # requests.
    'edx_django_utils.cache.middleware.RequestCacheMiddleware',
)

TEMPLATES = [{
    'BACKEND': 'django.template.backends.django.DjangoTemplates',
    'DIRS': ['tests/templates'],
    'APP_DIRS': True,
    'OPTIONS': {
        'context_processors': [
            'django.contrib.auth.context_processors.auth',  # this is required for admin
            'django.contrib.messages.context_processors.messages',  # this is required for admin
            'django.template.context_processors.request'
        ],
    },
}]

# Avoid warnings about migrations
DEFAULT_AUTO_FIELD = 'django.db.models.AutoField'

ECOMMERCE_PUBLIC_URL_ROOT = 'test.com'
ZEITLABS_PAYMENTS_SETTINGS = {
    'invoice_prefix': 'TEST',
    'organization_info': {'name': 'test_org', 'vat_no': '112233'},
    'valid_currency': 'SAR',
}
IS_ZEITLABS_PAYMENTS_ENABLED = False
SITE_ID = 1
