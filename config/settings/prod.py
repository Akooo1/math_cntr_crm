from .base import *  # noqa: F403
from .base import env

DEBUG = False
# Demo data never exists in production: without the app there is no seed_demo command.
INSTALLED_APPS = [a for a in INSTALLED_APPS if a != "apps.demo"]  # noqa: F405
SECRET_KEY = env("DJANGO_SECRET_KEY")
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
X_FRAME_OPTIONS = "DENY"
