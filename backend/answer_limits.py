"""Bound drafts before copying, storing or passing them to a checker."""
SHORT_FIELD_LIMIT = 1000
TEXT_LIMIT = 10000
CODE_LIMIT = 50000
TOTAL_LIMIT = 100000
REQUEST_LIMIT = 1000000


def validate_answer_size(value, question):
    limit = CODE_LIMIT if question.type in ('code_input', 'interactive') else (
        TEXT_LIMIT if question.type == 'text_input' else SHORT_FIELD_LIMIT)
    total, nodes = 0, 0
    stack = [(value, 0)]
    while stack:
        item, depth = stack.pop()
        nodes += 1
        if depth > 20 or nodes > 10000:
            raise ValueError('Ответ содержит слишком много вложенных данных')
        if isinstance(item, str):
            # Match HTML maxlength and CodeMirror: UTF-16 code units.
            if len(item) > limit:
                raise ValueError(f'Не более {limit} символов в одном поле ответа')
            size = len(item.encode('utf-16-le', errors='surrogatepass')) // 2
            if size > limit:
                raise ValueError(f'Не более {limit} символов в одном поле ответа')
            total += size
        elif isinstance(item, dict):
            if len(item) > 10000:
                raise ValueError('Ответ содержит слишком много полей')
            stack.extend((part, depth + 1) for pair in item.items() for part in pair)
        elif isinstance(item, list):
            if len(item) > 10000:
                raise ValueError('Ответ содержит слишком много элементов')
            stack.extend((part, depth + 1) for part in item)
        if total > TOTAL_LIMIT:
            raise ValueError(f'Не более {TOTAL_LIMIT} символов во всём ответе')
