import os
from flask import Flask
from flask_migrate import Migrate
from flask_socketio import SocketIO
from models import db
from config import CONNECTION_STRING, SECRET_KEY, REDIS_URL, DEBUG

app = Flask(__name__)
app.config['SQLALCHEMY_DATABASE_URI'] = CONNECTION_STRING
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
app.config['SECRET_KEY'] = SECRET_KEY
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['SESSION_COOKIE_HTTPONLY'] = True

db.init_app(app)
migrate = Migrate(app, db)

# Use redis message_queue only in production (when celery workers emit events separately)
_mq = REDIS_URL if not DEBUG else None
socketio = SocketIO(app, message_queue=_mq, cors_allowed_origins='*', async_mode='threading')
