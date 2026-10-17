import time
import unittest
from unittest.mock import patch

import jwt
from flask import Flask

from models import db
from routes.auth import auth_bp


class AuthProfileTests(unittest.TestCase):
    secret = 'test-only-avatar-signing-secret-32-bytes'

    def setUp(self):
        self.app = Flask(__name__)
        self.app.config.update(TESTING=True, SECRET_KEY='test-only', SQLALCHEMY_DATABASE_URI='sqlite://')
        db.init_app(self.app)
        self.app.register_blueprint(auth_bp)
        with self.app.app_context():
            db.create_all()
        self.client = self.app.test_client()
        patcher = patch('auth.JWT_SECRET', self.secret)
        patcher.start()
        self.addCleanup(patcher.stop)

    def tearDown(self):
        with self.app.app_context():
            db.session.remove()
            db.drop_all()
            db.engine.dispose()

    def login(self, extra=None, secret=None):
        claims = {'id': 42, 'name': 'Ученик', 'role': 'student', 'iat': int(time.time()), **(extra or {})}
        token = jwt.encode(claims, secret or self.secret, algorithm='HS256')
        return self.client.get('/auth/callback', query_string={'token': token})

    def test_signed_avatar_is_exposed_by_the_profile_api(self):
        avatar = 'https://codingprojects.example/media/user_avatars/42.jpg?v=123'
        self.assertEqual(self.login({'avatar_url': avatar}).status_code, 302)
        self.assertEqual(self.client.get('/api/me').json, {
            'id': 42, 'name': 'Ученик', 'role': 'student', 'avatar_url': avatar,
        })

    def test_legacy_token_still_logs_in_and_clears_a_previous_avatar(self):
        self.login({'avatar_url': 'https://codingprojects.example/avatar.jpg'})
        self.assertEqual(self.login().status_code, 302)
        self.assertIsNone(self.client.get('/api/me').json['avatar_url'])

    def test_anonymous_and_invalid_signature_cannot_supply_a_profile(self):
        self.assertEqual(self.client.get('/api/me').status_code, 401)
        self.assertEqual(self.login({'avatar_url': 'https://other.example/avatar.jpg'}, secret='wrong-signing-key-long-enough-for-hs256').status_code, 403)
        self.assertEqual(self.client.get('/api/me').status_code, 401)


if __name__ == '__main__':
    unittest.main()
