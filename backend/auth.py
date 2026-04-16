import time
from functools import wraps
from urllib.parse import quote

import jwt
from flask import session, redirect, request, abort, jsonify

from config import JWT_SECRET, AUTH_URL
from models import db, User


def _process_jwt(token):
    data = jwt.decode(token, JWT_SECRET, algorithms=['HS256'])
    if time.time() - data['iat'] > 60:
        abort(403)
    # Upsert user
    user = User.query.get(data['id'])
    if user is None:
        user = User(id=data['id'], name=data['name'], role=data['role'])
        db.session.add(user)
    else:
        user.name = data['name']
        user.role = data['role']
        from datetime import datetime
        user.last_login = datetime.utcnow()
    db.session.commit()
    session['user_id'] = data['id']
    session['role'] = data['role']
    session['name'] = data['name']


def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        token = request.args.get('token')
        if token:
            try:
                _process_jwt(token)
            except Exception:
                abort(403)
            args_without_token = {k: v for k, v in request.args.items() if k != 'token'}
            return redirect(request.path + ('?' + '&'.join(f'{k}={v}' for k, v in args_without_token.items()) if args_without_token else ''))
        if 'user_id' not in session:
            return redirect(AUTH_URL + quote(request.url, safe=''))
        return f(*args, **kwargs)
    return decorated


def api_login_required(f):
    """For JSON API endpoints — returns 401 instead of redirect."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        return f(*args, **kwargs)
    return decorated


def teacher_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return jsonify({'error': 'Unauthorized'}), 401
        if session.get('role') not in ('teacher', 'admin'):
            return jsonify({'error': 'Forbidden'}), 403
        return f(*args, **kwargs)
    return decorated


def current_user_id():
    return session.get('user_id')


def current_role():
    return session.get('role')
