"""Optional real GeekExam -> Celery -> GeekExecutor -> WebSocket smoke.

Run: python tests/executor_live_smoke.py --executor-dir /path/to/GeekExecutor
Uses temporary databases/storage, ephemeral Redis, dummy keys and Brainfuck;
does not require Docker, a paid AI provider or production credentials.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time

import jwt
import requests
import socketio

ROOT = Path(__file__).resolve().parents[1]
SECRET = 'exam-live-execution-secret-' * 3
LOGIN_SECRET = 'exam-live-login-secret-' * 3


def free_port():
    with socket.socket() as server:
        server.bind(('127.0.0.1', 0))
        return server.getsockname()[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--executor-dir', type=Path, required=True)
    executor = parser.parse_args().executor_dir.resolve()
    if not (executor / 'executor_server.py').is_file(): raise SystemExit('Invalid GeekExecutor directory')
    if not shutil.which('redis-server'): raise SystemExit('redis-server is required')
    redis_port, exam_port, executor_port = free_port(), free_port(), free_port()
    exam_url, executor_url = f'http://127.0.0.1:{exam_port}', f'http://127.0.0.1:{executor_port}'
    processes, logs = [], []
    socket_client = socketio.Client(reconnection=False)
    done, events = threading.Event(), []
    try:
        with tempfile.TemporaryDirectory(prefix='geekexam-executor-smoke-') as directory:
            temporary = Path(directory)
            common = dict(os.environ, PYTHONUNBUFFERED='1')
            exam_env = dict(common, SECRET_KEY=LOGIN_SECRET, JWT_SECRET=LOGIN_SECRET,
                CONNECTION_STRING='sqlite:///' + str(temporary / 'exam.sqlite'),
                REDIS_URL=f'redis://127.0.0.1:{redis_port}/1', CELERY_BROKER=f'redis://127.0.0.1:{redis_port}/1',
                GEEKEXECUTOR_URL=executor_url,
                GEEKEXECUTOR_SOCKET_URL=executor_url, GEEKEXECUTOR_SECRET=SECRET,
                EXECUTOR_CALLBACK_BASE_URL=exam_url, EXECUTOR_STORAGE_DIR=str(temporary / 'exam-files'))
            executor_env = dict(common, SECRET=SECRET, JWT_SECRET=SECRET,
                CONNECTION_STRING='sqlite:///' + str(temporary / 'executor.sqlite'),
                REDIS_URL=f'redis://127.0.0.1:{redis_port}/0', CELERY_BROKER=f'redis://127.0.0.1:{redis_port}/0',
                TEST_ARTIFACTS_DIR=str(temporary / 'executor-cache'), SOCKET_ALLOWED_ORIGINS='*',
                CHECKER_CLIENTS_JSON=json.dumps({'geekexam': dict(base_url=exam_url, jwt_secret=SECRET, api_prefix='/api/executor')}))

            def start(command, name, cwd, env):
                log = (temporary / (name + '.log')).open('w+')
                logs.append(log)
                processes.append(subprocess.Popen(command, cwd=cwd, env=env, stdout=log, stderr=log))

            start(['redis-server', '--bind', '127.0.0.1', '--port', str(redis_port), '--save', '', '--appendonly', 'no'], 'redis', ROOT, common)
            seed = '''from manage import app
from models import db, User, Test, Variant, Question, Attempt, Answer
import execution_models
with app.app_context():
    db.create_all()
    db.session.add_all([User(id=1, name='Teacher', role='teacher'), User(id=2, name='Student', role='student')])
    t = Test(id=1, title='Live', created_by=1, is_active=True, code='LIVE')
    v = Variant(id=1, title='A', test=t)
    q = Question(id=1, variant=v, title='Program', body='Print a byte', type='code_input', max_points=3,
        check_type='docker', check_config=dict(lang='brainfuck', submission_modes=['files'], score_step=.5,
            tests=[dict(input='', expected='\\x03'), dict(input='SECRET INPUT' * 12000, expected='\\x04', hidden=True)]))
    a = Attempt(id=1, test=t, variant=v, user_id=2, max_points=3)
    answer = Answer(id=1, attempt=a, question=q, value=None)
    db.session.add_all([t, a, answer]); db.session.commit()
'''
            subprocess.run([sys.executable, '-c', seed], cwd=ROOT, env=exam_env, check=True, stdout=subprocess.DEVNULL)
            subprocess.run([sys.executable, '-m', 'flask', '--app', 'executor_server', 'db', 'upgrade'], cwd=executor, env=executor_env, check=True, stdout=subprocess.DEVNULL)
            start([sys.executable, '-m', 'gunicorn', '--bind', f'127.0.0.1:{exam_port}', '--worker-class', 'eventlet', '--workers', '1', 'app:app'], 'exam-http', ROOT, exam_env)
            start([sys.executable, '-m', 'gunicorn', '--bind', f'127.0.0.1:{executor_port}', '--worker-class', 'gthread', '--threads', '8', '--workers', '1', 'executor_server:app'], 'executor-http', executor, executor_env)
            start([sys.executable, '-m', 'celery', '-A', 'celery_app.celery', 'worker', '--pool=solo', '--loglevel=WARNING'], 'exam-worker', ROOT, exam_env)
            start([sys.executable, '-m', 'celery', '-A', 'executor_queue.celery', 'worker', '--pool=solo', '--loglevel=WARNING'], 'executor-worker', executor, executor_env)
            for url, status in ((exam_url + '/api/me', 401), (executor_url + '/health', 200)):
                for _ in range(100):
                    try:
                        if requests.get(url, timeout=1).status_code == status: break
                    except requests.RequestException: pass
                    time.sleep(.1)
                else: raise AssertionError('Service did not start: ' + url)

            def login(user_id, role):
                client = requests.Session()
                token = jwt.encode(dict(id=user_id, name=role, role=role, iat=int(time.time())), LOGIN_SECRET, algorithm='HS256')
                response = client.get(exam_url + '/auth/callback', params=dict(token=token), allow_redirects=False, timeout=5)
                assert response.status_code == 302, response.text
                return client

            student, teacher = login(2, 'student'), login(1, 'teacher')
            source = b'+' * 131072 + b'+++.'
            response = student.post(exam_url + '/api/answers/1/files', files={'file': ('main.bf', source)}, timeout=5)
            assert response.status_code == 201, response.text
            response = student.put(exam_url + '/api/answers/1', json=dict(value=dict(mode='files', files=[dict(upload_id=response.json()['id'])])), timeout=5)
            assert response.status_code == 200, response.text
            response = student.post(exam_url + '/api/attempts/1/finish', timeout=10)
            assert response.status_code == 200, response.text
            link = response.json()['executions'][0]

            @socket_client.on('execution_progress', namespace='/executions')
            def progress(event):
                events.append(event)
                if event['phase'] in ('completed', 'error'): done.set()

            socket_client.connect(executor_url, namespaces=['/executions'], transports=['websocket'], auth={'token': link['subscription']['token']}, wait_timeout=10)
            assert socket_client.transport() == 'websocket'
            assert done.wait(45), 'No terminal WebSocket event'
            assert events[-1]['phase'] == 'completed', events
            path = f'/api/executions/{link["execution_id"]}'
            public = student.get(exam_url + path, timeout=5)
            private = teacher.get(exam_url + path, timeout=5)
            assert public.status_code == private.status_code == 200
            assert 'SECRET INPUT' not in public.text and 'expected' not in public.json()['statistics']['details'][1]
            assert 'expected' in private.json()['statistics']['details'][1]
            download = public.json()['files'][0]['artifact']['download_url']
            assert student.get(exam_url + download, timeout=5).content == source
            with sqlite3.connect(temporary / 'exam.sqlite') as database:
                assert database.execute('SELECT points, check_state FROM answers WHERE id=1').fetchone() == (1.5, 'checked')
                assert database.execute('SELECT total_points, is_checked FROM attempts WHERE id=1').fetchone() == (1.5, 1)
                assert database.execute('SELECT applied, result_hash IS NOT NULL FROM execution_runs').fetchone() == (1, 1)
            assert all(set(event) <= {'execution_id', 'sequence', 'phase', 'completed', 'total'} for event in events)
            print('GeekExam live smoke passed: file upload -> finish/subscription -> Celery -> signed large artifacts -> GeekExecutor -> callback -> fractional grade -> direct WebSocket.')
            print('Phases: ' + ', '.join(event['phase'] for event in events))
    except Exception:
        for log in logs:
            log.flush(); log.seek(0); print(log.read()[-3500:], file=sys.stderr)
        raise
    finally:
        if socket_client.connected: socket_client.disconnect()
        for process in reversed(processes):
            process.terminate()
            try: process.wait(timeout=5)
            except subprocess.TimeoutExpired: process.kill(); process.wait()
        for log in logs: log.close()


if __name__ == '__main__': main()
