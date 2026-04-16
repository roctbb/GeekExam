#!/bin/sh
set -e
export FLASK_APP=manage.py
flask db upgrade
exec python app.py
