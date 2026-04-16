#!/bin/sh
set -e
export FLASK_APP=manage.py
flask db upgrade
exec gunicorn --worker-class eventlet --bind 0.0.0.0:8085 --workers 1 'app:app'
