import os
from datetime import timedelta

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if not SECRET_KEY:
        raise ValueError('SECRET_KEY manquante dans .env')

    WTF_CSRF_ENABLED = True
    WTF_CSRF_TIME_LIMIT = 3600

    PERMANENT_SESSION_LIFETIME = timedelta(hours=2)
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    SESSION_COOKIE_SECURE = os.environ.get('FLASK_ENV') == 'production'

    BASE_DIR = os.path.abspath(os.path.dirname(__file__))
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        'DATABASE_URL',
        'sqlite:///' + os.path.join(BASE_DIR, 'database', 'users.db')
    ).replace('postgres://', 'postgresql://')
    SQLALCHEMY_TRACK_MODIFICATIONS = False

    MAIL_SERVER  = 'smtp.gmail.com'
    MAIL_PORT    = 587
    MAIL_USE_TLS = True
    MAIL_USERNAME = os.environ.get('MAIL_USERNAME')
    MAIL_PASSWORD = os.environ.get('MAIL_PASSWORD')
    MAIL_DEFAULT_SENDER = ('AgroPac AI HdF', os.environ.get('MAIL_USERNAME'))

    RATELIMIT_DEFAULT    = '200 per day;50 per hour'
    RATELIMIT_STORAGE_URL = 'memory://'

    TOKEN_EXPIRATION_CONFIRM = 3600
    TOKEN_EXPIRATION_RESET   = 1800
