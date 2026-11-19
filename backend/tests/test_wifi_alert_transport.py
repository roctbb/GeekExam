import hashlib
import hmac
import json
from unittest import TestCase
from unittest.mock import patch

from celery_app import celery
from wifi_alerts import send


class WifiAlertTransportTest(TestCase):
    def test_signature_covers_the_exact_utf8_payload_and_destination(self):
        payload = {'student_name': 'Ученик', 'event_id': 'event'}
        key = 'local-fixture-key-' * 3
        with (patch('config.GEEKEXAM_ALERT_SECRET', key), patch('config.GEEKCLASS_HOST', 'https://cp.example/'),
              patch('wifi_alerts.time.time', return_value=1787654321), patch('wifi_alerts.requests.post') as post):
            post.return_value.status_code = 200
            post.return_value.json.return_value = {'status': 'sent'}
            self.assertEqual(send(payload), ('sent', 0))
            args, kwargs = post.call_args
            self.assertEqual(args, ('https://cp.example/api/geekexam/wifi-disconnect',))
            self.assertEqual(json.loads(kwargs['data']), payload)
            self.assertFalse(kwargs['allow_redirects'])
            signed = b'POST\n/api/geekexam/wifi-disconnect\n1787654321\n' + kwargs['data']
            self.assertEqual(kwargs['headers']['X-Exam-Signature'], hmac.new(key.encode(), signed, hashlib.sha256).hexdigest())

    def test_pending_and_ambiguous_outcomes_are_distinct_and_use_a_separate_worker(self):
        self.assertEqual(celery.amqp.router.route({}, 'celery_tasks.presence.notify')['queue'].name, 'notification_queue')
        self.assertEqual(celery.amqp.router.route({}, 'celery_tasks.presence.collect')['queue'].name, 'presence_queue')
        with patch('config.GEEKEXAM_ALERT_SECRET', 'a' * 32), patch('wifi_alerts.requests.post') as post:
            response = post.return_value
            response.headers = {'Retry-After': '45'}
            response.status_code = 503
            self.assertEqual(send({}), ('retry', 45))
            response.status_code = 200
            response.json.return_value = {'status': 'uncertain'}
            self.assertEqual(send({}), ('uncertain', 0))
            response.json.return_value = ['invalid']
            self.assertEqual(send({})[0], 'retry')
        with patch('config.GEEKEXAM_ALERT_SECRET', ''), patch('wifi_alerts.requests.post') as post:
            self.assertEqual(send({})[0], 'retry')
            post.assert_not_called()
