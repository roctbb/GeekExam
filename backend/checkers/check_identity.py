import hashlib
import json


def answer_fingerprint(value):
    serialized = json.dumps(value, sort_keys=True, ensure_ascii=True, separators=(',', ':'))
    return hashlib.sha256(serialized.encode('utf-8')).hexdigest()


def versioned_callback_id(answer_id, value):
    return f'{answer_id}:{answer_fingerprint(value)}'
