import time
import jwt
import requests
from config import GEEKPASTE_API_URL, JWT_SECRET, CALLBACK_BASE_URL


def _make_service_token():
    payload = {'service': 'geekexam', 'iat': int(time.time())}
    return jwt.encode(payload, JWT_SECRET, algorithm='HS256')


class DockerChecker:
    def submit(self, answer_id, answer_value, check_config, question_body):
        """
        Sends code/text to GeekPasteV2 for async checking.
        Returns True if submitted successfully.
        """
        payload = {
            'callback_url': f'{CALLBACK_BASE_URL}/api/callback/check',
            'callback_id': str(answer_id),
            'code': answer_value.get('code') or answer_value.get('text', ''),
            'lang': check_config.get('lang', 'python'),
            'task_text': question_body or '',
            'check_type': check_config.get('check_type', 'tests'),
            'check_config': check_config,
        }
        headers = {'Authorization': f'Bearer {_make_service_token()}'}
        try:
            resp = requests.post(GEEKPASTE_API_URL, json=payload, headers=headers, timeout=10)
            return resp.status_code == 200
        except Exception as e:
            print(f'GeekPasteV2 submit error: {e}')
            return False
