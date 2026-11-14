import re

from flask import session
from flask_socketio import join_room

from models import db, Attempt, Test


def publish_attempt_change(attempt):
    from manage import socketio
    try:
        for room in (f'user_{attempt.user_id}', f'test_{attempt.test_id}'):
            socketio.emit('attempt_list_updated', {'attempt_id': attempt.id}, room=room)
    except Exception:
        from flask import current_app
        current_app.logger.warning('attempt_list_event_delivery_failed attempt_id=%s', attempt.id)


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
        if room == f'user_{user_id}':
            join_room(room)
            return {'status': 'joined'}
        test_match = re.fullmatch(r'test_([1-9][0-9]*)', room)
        if test_match and session.get('role') in ('teacher','admin') and db.session.get(Test, int(test_match.group(1))):
            join_room(room)
            return {'status': 'joined'}
        match = re.fullmatch(r'attempt_([1-9][0-9]*)', room)
        if not match:
            return {'error': 'Forbidden'}
        attempt = db.session.get(Attempt, int(match.group(1)))
        if not attempt or (attempt.user_id != user_id and session.get('role') not in ('teacher', 'admin')):
            return {'error': 'Forbidden'}
        join_room(room)
        return {'status': 'joined'}
