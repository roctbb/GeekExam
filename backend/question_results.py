import json
from collections import Counter

from sqlalchemy.orm import defer

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


def question_results(test_id):
    rows = db.session.query(
        Question.id.label('question_id'), Question.title, Question.order,
        Variant.id.label('variant_id'), Variant.title.label('variant_title'),
    ).join(Variant, Variant.id == Question.variant_id).filter(
        Variant.test_id == test_id,
    ).order_by(Variant.order, Variant.id, Question.order, Question.id).all()

    below_max = Answer.points < Question.max_points
    grades = _graded_answers(test_id).with_entities(
        Answer.question_id, Question.type, below_max, db.case((below_max, Answer.value)),
    ).yield_per(100)
    graded, below, skipped = Counter(), Counter(), Counter()
    for question_id, question_type, is_below_max, value in grades:
        graded[question_id] += 1
        if is_below_max:
            below[question_id] += 1
            if not _has_submitted_content(value, question_type):
                skipped[question_id] += 1

    summary = []
    by_order = {}
    for row in rows:
        graded_count, below_count = graded[row.question_id], below[row.question_id]
        item = dict(question_id=row.question_id, title=row.title, order=row.order,
                    variant_title=row.variant_title, graded_count=graded_count, below_max_count=below_count)
        if graded_count:
            summary.append(item)
        group = by_order.setdefault(row.order, {'order': row.order, 'title': row.title, 'variants': []})
        skipped_count = skipped[row.question_id]
        group['variants'].append(dict(
            question_id=row.question_id, title=row.title, variant_id=row.variant_id, variant_title=row.variant_title,
            correct_count=graded_count - below_count, incorrect_count=below_count - skipped_count, skipped_count=skipped_count,
        ))

    summary.sort(key=lambda row: (-row['below_max_count'] / row['graded_count'], -row['below_max_count']))
    return {'question_summary': summary, 'question_review': list(by_order.values())}


def question_review_details(test_id, order):
    questions = Question.query.join(Variant).filter(
        Variant.test_id == test_id, Question.order == order,
    ).options(defer(Question.check_config)).order_by(Variant.order, Variant.id).all()
    return [_review_question(question) for question in questions]


def _review_question(question):
    reference = {}
    if question.check_type in ('exact', 'ai', 'manual'):
        config = question.check_config or {}
        reference = {key: config[key] for key in ('answer', 'answers', 'correct', 'matrix', 'fields') if key in config}
        if 'answer' not in reference and config.get('reference_answer') is not None:
            reference['answer'] = config['reference_answer']
    return dict(id=question.id, type=question.type, body=question.body, ui_config=question.ui_config,
                check_type=question.check_type, check_config=reference)


def _has_content(value):
    if isinstance(value, dict):
        return any(_has_content(item) for item in value.values())
    if isinstance(value, list):
        return any(_has_content(item) for item in value)
    if isinstance(value, str):
        return bool(value.strip())
    return value is not None


def _has_submitted_content(value, question_type):
    if not isinstance(value, dict) or question_type not in ('text_input', 'code_input', 'interactive'):
        return _has_content(value)
    mode = value.get('mode')
    if mode == 'repository':
        return _has_content(value.get('repository_url'))
    files = value.get('files')
    if isinstance(files, list) and any(
        isinstance(file, dict) and (file.get('upload_id') or _has_content(file.get('content'))) for file in files
    ):
        return True
    if mode == 'code':
        return _has_content(value.get('code'))
    return any(_has_content(item) for key, item in value.items() if key not in ('mode', 'lang', 'files', 'filename'))


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


def common_wrong_answers(test_id, question, limit=10, *, include_skipped=True):
    rows = _graded_answers(test_id).with_entities(Answer.value, Attempt.id.label('attempt_id')).filter(
        Question.id == question.id, Answer.points < Question.max_points,
    ).order_by(Answer.id).yield_per(100)

    groups = {}
    for value, attempt_id in rows:
        if not include_skipped and not _has_submitted_content(value, question.type):
            continue
        key = _answer_group(question, value)
        if not include_skipped and key is None:
            key = answer_fingerprint(value)
        if key not in groups:
            preview = _answer_preview(question, value) if key is not None else None
            if preview and len(preview) > 1500:
                preview = preview[:1500] + '…'
            groups[key] = {'preview': preview, 'count': 0, 'example_attempt_id': attempt_id}
        groups[key]['count'] += 1

    ranked = sorted(groups.values(), key=lambda group: -group['count'])
    return {'answers': ranked[:limit], 'distinct_count': len(ranked)}
