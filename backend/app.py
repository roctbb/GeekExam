import eventlet
eventlet.monkey_patch()

from manage import app, socketio
from routes.auth import auth_bp
from routes.tests import tests_bp
from routes.attempts import attempts_bp
from routes.answers import answers_bp
from routes.callbacks import callbacks_bp
from flask_socketio import join_room

app.register_blueprint(auth_bp)
app.register_blueprint(tests_bp)
app.register_blueprint(attempts_bp)
app.register_blueprint(answers_bp)
app.register_blueprint(callbacks_bp)


@socketio.on('join')
def on_join(data):
    join_room(data.get('room'))


if __name__ == '__main__':
    from config import PORT, DEBUG
    socketio.run(app, host='0.0.0.0', port=PORT, debug=DEBUG, allow_unsafe_werkzeug=True)
