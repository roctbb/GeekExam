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
COURSE_PLANNER_SECRET = os.getenv('COURSE_PLANNER_SECRET')
AUTH_URL = GEEKCLASS_HOST + '/insider/jwt?redirect_url='

CALLBACK_BASE_URL = os.getenv('CALLBACK_BASE_URL', 'http://localhost:8085')
FRONTEND_URL = os.getenv('FRONTEND_URL', 'http://localhost:5173')
GUARD_URL = os.getenv('GUARD_URL', '').rstrip('/')
GUARD_SERVICE_SECRET = os.getenv('GUARD_SERVICE_SECRET', '')

# Execution clients have independent signing keys; JWT_SECRET remains login-only.
GEEKEXECUTOR_URL = os.getenv('GEEKEXECUTOR_URL', 'http://geekexecutor:8086').rstrip('/')
GEEKEXECUTOR_SOCKET_URL = os.getenv('GEEKEXECUTOR_SOCKET_URL', GEEKEXECUTOR_URL).rstrip('/')
GEEKEXECUTOR_SECRET = os.getenv('GEEKEXECUTOR_SECRET', '')
EXECUTOR_CALLBACK_BASE_URL = os.getenv('EXECUTOR_CALLBACK_BASE_URL', CALLBACK_BASE_URL).rstrip('/')
EXECUTOR_STORAGE_DIR = os.getenv('EXECUTOR_STORAGE_DIR', os.path.join(os.path.dirname(__file__), 'instance', 'executor'))
