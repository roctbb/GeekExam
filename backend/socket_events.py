import re

from flask import session
from flask_socketio import join_room

from models import db, Attempt


def register_socket_handlers(socketio):
    @socketio.on('connect')
    def on_connect(auth=None):
        return session.get('user_id') is not None

    @socketio.on('join')
    def on_join(data):
        user_id = session.get('user_id')
        room = data.get('room') if isinstance(data, dict) else None
        if user_id is None or not isinstance(room, str):
            return {'error': 'Forbidden'}
        match = re.fullmatch(r'attempt_([1-9][0-9]*)', room)
        if not match:
            return {'error': 'Forbidden'}
        attempt = db.session.get(Attempt, int(match.group(1)))
        if not attempt or (attempt.user_id != user_id and session.get('role') not in ('teacher', 'admin')):
            return {'error': 'Forbidden'}
        join_room(room)
        return {'status': 'joined'}
