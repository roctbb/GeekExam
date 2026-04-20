import os
from dotenv import load_dotenv

load_dotenv()

SECRET_KEY = os.getenv('SECRET_KEY', 'dev-secret')
DEBUG = os.getenv('DEBUG', 'false').lower() == 'true'
PORT = int(os.getenv('PORT', 8085))

CONNECTION_STRING = os.getenv('CONNECTION_STRING', 'postgresql+psycopg2://user:pass@localhost:5432/geekexam')
CELERY_BROKER = os.getenv('CELERY_BROKER', 'redis://localhost:6379/0')
REDIS_URL = os.getenv('REDIS_URL', CELERY_BROKER)

GEEKCLASS_HOST = os.getenv('GEEKCLASS_HOST', 'https://codingprojects.ru')
JWT_SECRET = os.getenv('JWT_SECRET')
AUTH_URL = GEEKCLASS_HOST + '/insider/jwt?redirect_url='

GEEKPASTE_API_URL = os.getenv('GEEKPASTE_API_URL', 'https://paste.geekclass.ru/api/external/check')
CALLBACK_BASE_URL = os.getenv('CALLBACK_BASE_URL', 'http://localhost:8085')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')
GEEKPASTE_CALLBACK_REQUIRE_AUTH = os.getenv('GEEKPASTE_CALLBACK_REQUIRE_AUTH', 'true').lower() == 'true'
GEEKPASTE_CALLBACK_EXPECTED_SERVICE = os.getenv('GEEKPASTE_CALLBACK_EXPECTED_SERVICE', 'geekpaste')
GEEKPASTE_CALLBACK_MAX_AGE_SECONDS = int(os.getenv('GEEKPASTE_CALLBACK_MAX_AGE_SECONDS', 120))
GEEKPASTE_CALLBACK_DEDUP_TTL_SECONDS = int(os.getenv('GEEKPASTE_CALLBACK_DEDUP_TTL_SECONDS', 86400))
