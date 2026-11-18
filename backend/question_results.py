import json

from checkers.check_identity import answer_fingerprint
from checkers.check_types.exact import normalize_text
from models import Answer, Attempt, Question, Variant, db


def _graded_answers(test_id):
    return db.session.query(Answer).select_from(Attempt).join(
        Answer, Answer.attempt_id == Attempt.id,
    ).join(
        Question, (Question.id == Answer.question_id) & (Question.variant_id == Attempt.variant_id),
    ).filter(
        Attempt.test_id == test_id, Attempt.finished_at.is_not(None), Attempt.is_checked.is_(True),
        Answer.check_state == 'checked', Answer.points.is_not(None),
    )


def question_summary(test_id):
    rows = _graded_answers(test_id).with_entities(
        Question.id.label('question_id'), Question.title, Question.order,
        Variant.title.label('variant_title'),
        db.func.count(Answer.id).label('graded_count'),
        db.func.sum(db.case((Answer.points < Question.max_points, 1), else_=0)).label('below_max_count'),
    ).join(Variant, Variant.id == Question.variant_id).group_by(
        Variant.id, Variant.title, Variant.order, Question.id, Question.title, Question.order,
    ).order_by(Variant.order, Variant.id, Question.order, Question.id).all()

    return [dict(row._mapping) for row in sorted(
        rows, key=lambda row: (-row.below_max_count / row.graded_count, -row.below_max_count),
    )]


def _has_content(value):
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _answer_group(question, value):
    if isinstance(value, dict):
        content = {key: item for key, item in value.items() if key not in ('mode', 'lang')}
        if (question.type == 'text_input' and value.get('mode') in (None, 'text')
                and set(content) <= {'text', 'files'} and not content.get('files')):
            text = content.get('text') or ''
            if question.check_type == 'exact':
                text = normalize_text(text, question.check_config or {})
            elif not text.strip():
                text = ''
            return answer_fingerprint({'text': text}) if text else None
        if _has_content(content):
            return answer_fingerprint(value)
    elif _has_content(value):
        return answer_fingerprint(value)
    return None


def _preview_value(value):
    if value is None or value == '':
        return '—'
    if type(value) is bool:
        return 'Верно' if value else 'Неверно'
    return value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def _answer_preview(question, value):
    if not isinstance(value, dict):
        return _preview_value(value)
    ui = question.ui_config or {}
    if value.get('mode') == 'repository' and value.get('repository_url'):
        return '\n'.join(_preview_value(part) for part in (value.get('repository_url'), value.get('repository_ref')) if part)
    if isinstance(value.get('files'), list) and value['files']:
        paths = [file.get('path') or 'Файл решения' for file in value['files'] if isinstance(file, dict)]
        if paths:
            return '\n'.join(_preview_value(part) for part in [value.get('text'), *paths] if part)
    if question.type in ('choice_table', 'true_false_table') and isinstance(value.get('answers'), list):
        options = ui.get('options') or []
        return '\n'.join(
            f'{i}. ' + next((_preview_value(option['label']) for option in options if isinstance(option, dict)
                            and type(option.get('value')) is type(item) and option.get('value') == item
                            and option.get('label')), _preview_value(item))
            for i, item in enumerate(value['answers'], start=1)
        )
    if question.type in ('multi_input', 'matrix_input'):
        labels = {field['name']: field.get('label') or field['name'] for field in ui.get('fields') or []
                  if isinstance(field, dict) and isinstance(field.get('name'), str)}
        fields = (value.get('fields') or {}) if question.type == 'matrix_input' else value
        lines = [f'{labels.get(key, key)}: {_preview_value(item)}' for key, item in fields.items()]
        matrix = ['  '.join(map(_preview_value, row)) for row in value.get('matrix') or []] if question.type == 'matrix_input' else []
        return '\n'.join(matrix + lines)
    for text in (value.get('code'), value.get('text')):
        if isinstance(text, str) and text:
            return text if text.strip() else json.dumps(text, ensure_ascii=False)
    return json.dumps(value, ensure_ascii=False)


def common_wrong_answers(test_id, question, limit=10):
    rows = _graded_answers(test_id).with_entities(Answer.value, Attempt.id.label('attempt_id')).filter(
        Question.id == question.id, Answer.points < Question.max_points,
    ).order_by(Answer.id).yield_per(100)

    groups = {}
    for value, attempt_id in rows:
        key = _answer_group(question, value)
        if key not in groups:
            preview = _answer_preview(question, value) if key is not None else None
            if preview and len(preview) > 1500:
                preview = preview[:1500] + '…'
            groups[key] = {'preview': preview, 'count': 0, 'example_attempt_id': attempt_id}
        groups[key]['count'] += 1

    ranked = sorted(groups.values(), key=lambda group: -group['count'])
    return {'answers': ranked[:limit], 'distinct_count': len(ranked)}
