from urllib.parse import quote, urlparse

from flask import Blueprint, redirect, session, jsonify, request, abort

from auth import _process_jwt, current_user_id, current_role
from config import AUTH_URL, FRONTEND_URL

auth_bp = Blueprint('auth', __name__)


def _safe_redirect(url):
    """Redirect to frontend. Relative paths are prepended with FRONTEND_URL."""
    if not url or url == '/':
        return redirect(FRONTEND_URL)
    if url.startswith('/'):
        return redirect(FRONTEND_URL.rstrip('/') + url)
    if url.startswith(FRONTEND_URL):
        return redirect(url)
    return redirect(FRONTEND_URL)


@auth_bp.route('/auth/login')
def login():
    next_url = request.args.get('next', '/')
    callback_url = request.host_url.rstrip('/') + '/auth/callback?next=' + quote(next_url, safe='')
    return redirect(AUTH_URL + quote(callback_url, safe=''))


@auth_bp.route('/auth/callback')
def callback():
    token = request.args.get('token')
    next_url = request.args.get('next', FRONTEND_URL)
    print(f'[auth callback] token={bool(token)}, next={next_url}, all_args={dict(request.args)}')
    if not token:
        abort(403)
    try:
        _process_jwt(token)
    except Exception as e:
        print(f'[auth callback] JWT error: {e}')
        abort(403)
    return _safe_redirect(next_url)


@auth_bp.route('/auth/logout')
def logout():
    session.clear()
    next_url = request.args.get('next', '/')
    return _safe_redirect(next_url)


@auth_bp.route('/api/me')
def me():
    if 'user_id' not in session:
        return jsonify({'error': 'Unauthorized'}), 401
    return jsonify({'id': current_user_id(), 'role': current_role(), 'name': session.get('name')})
