"""Immutable execution snapshots, durable dispatch and version-safe result application."""
from copy import deepcopy
from datetime import datetime, timedelta
import hashlib
import math
import uuid

from flask import abort
from sqlalchemy import or_

from models import db, Answer
from execution_models import ExecutionRun, ExecutionUpload, ExecutionTaskFile
from checkers.check_identity import answer_fingerprint
from checkers.scoring import round_points, score_step
from attempt_lifecycle import lock_answer
import executor_transport as transport


def safe_path(name):
    if (not isinstance(name, str) or not 1 <= len(name.encode()) <= 240 or name.startswith('/')
            or '\\' in name or ':' in name or any(ord(c) < 32 or ord(c) == 127 for c in name)
            or any(p in ('', '.', '..', '.git') for p in name.split('/')) or name in ('program', '.executor')):
        raise ValueError('Invalid file path')
    return name


def task_files(question_id):
    return [dict(name=f.name, kind=f.kind, is_public=f.is_public, read_only=f.read_only,
                 include_in_check=f.include_in_check, artifact=f.artifact)
            for f in ExecutionTaskFile.query.filter_by(question_id=question_id, deleted_at=None).order_by(ExecutionTaskFile.id)]


def make_snapshot(run_id, submission_id, answer, question, attempt):
    from executor_validation import validate_executor_config, default_language
    validate_executor_config(dict(check_type=question.check_type, check_config=question.check_config, type=question.type, ui_config=question.ui_config))
    cfg = deepcopy(question.check_config or {})
    cfg.setdefault('lang', default_language(question.check_type, cfg, question.ui_config))
    value = deepcopy(answer.value or {})
    if not isinstance(value, dict): raise ValueError('Expected an answer object')
    if not isinstance(value.get('files', []), list) or len(value.get('files', [])) > 100 or any(not isinstance(f, dict) for f in value.get('files', [])):
        raise ValueError('Invalid solution files')
    mode = value.get('mode') or ('code' if 'code' in value else 'text')
    modes = cfg.get('submission_modes', ['code', 'project', 'files', 'repository'] if question.type in ('code_input', 'interactive') else ['text', 'files'])
    if mode not in modes:
        raise ValueError('Submission mode is not allowed')
    language = cfg.get('lang', 'python' if question.check_type == 'docker' else 'text')
    language = value.get('lang', language)
    if language not in cfg.get('allowed_languages', [cfg.get('lang', 'python' if question.check_type == 'docker' else 'text')]):
        raise ValueError('Language is not allowed')
    files = []
    if mode == 'repository':
        from executor_repositories import parse_repository
        repository = parse_repository(value.get('repository_url', ''), value.get('repository_ref'))
    else:
        repository = None
        if 'code' in value or mode == 'text':
            source = value.get('code') if 'code' in value else value.get('text', '')
            name = value.get('filename') or cfg.get('entrypoint') or ('solution.cpp' if language == 'cpp' else 'solution.py' if language == 'python' else 'answer.txt')
            if not isinstance(source, str): raise ValueError('Invalid source')
            files.append(dict(name=safe_path(name), artifact=transport.inline(source)))
        for file in value.get('files', []):
            if 'upload_id' in file:
                uploaded = ExecutionUpload.query.filter_by(id=file['upload_id'], answer_id=answer.id).first()
                if not uploaded: raise ValueError('File does not belong to this answer')
                files.append(dict(name=safe_path(file.get('path', uploaded.name)), artifact=uploaded.artifact))
            else:
                if not isinstance(file.get('content'), str): raise ValueError('Invalid editor file')
                files.append(dict(name=safe_path(file.get('path')), artifact=transport.inline(file['content'])))
        if not files: raise ValueError('Solution has no files')
    attachments = task_files(question.id)
    for file in attachments:
        if file['kind'] != 'starter' or not file['read_only']: continue
        existing = next((f for f in files if f['name'] == file['name']), None)
        if existing and existing['artifact']['sha256'] != file['artifact']['sha256']:
            raise ValueError('Read-only starter was modified')
        if not existing and mode != 'repository': files.append(dict(name=file['name'], artifact=file['artifact']))
    validate_files(files, cfg, allow_empty=mode == 'repository')
    if question.check_type == 'docker':
        tests = cfg.get('tests', [])
        if not isinstance(tests, list) or not 1 <= len(tests) <= 200:
            raise ValueError('Expected 1..200 tests')
        prepared = []
        for test in tests:
            if not isinstance(test, dict): raise ValueError('Invalid test')
            row = deepcopy(test)
            row['input'] = transport.inline(str(test.get('input', '')))
            row['expected'] = transport.inline(str(test.get('expected', '')))
            prepared.append(row)
        cfg['tests'] = prepared
        points = len(tests)
        check_type = 'tests'
        instructions = ''
    else:
        step = score_step(cfg)
        points = int(question.max_points / step)
        check_type = 'gpt'
        instructions = cfg.get('prompt', cfg.get('private_instructions', ''))
        if step != 1:
            instructions += f'\nМашинная шкала: каждый балл из условия умножь на {1 / step:g}. Верни целое число от 0 до {points}. Платформа пересчитает результат обратно.'
    return dict(execution_id=run_id, submission_id=submission_id, task_id=question.id, user_id=attempt.user_id,
                course_id=attempt.test_id, language=language, files=files,
                answer=dict(mode=mode, text=value.get('text', '')),
                task=dict(name=question.title, language=language, points=points, public_text=question.body or '',
                          check_type=check_type, test_mode='external', test_config=cfg,
                          private_instructions=instructions, reference_answer=cfg.get('reference_answer', ''),
                          gpt_model=cfg.get('gpt_model'), entrypoint=cfg.get('entrypoint'), task_files=attachments),
                grading=dict(max_points=question.max_points, score_step=score_step(cfg), check_type=question.check_type),
                repository=repository)


def validate_files(files, cfg, allow_empty=False):
    if not isinstance(files, list) or not (0 if allow_empty else 1) <= len(files) <= min(cfg.get('max_files', 100), 100):
        raise ValueError('Invalid file count')
    names, total = [], 0
    for file in files:
        name = safe_path(file['name'])
        if any(name == p or name.startswith(p + '/') or p.startswith(name + '/') for p in names):
            raise ValueError('Conflicting file paths')
        names.append(name)
        total += file['artifact']['bytes']
        if file['artifact']['bytes'] > min(cfg.get('max_file_bytes', transport.MAX_FILE), transport.MAX_FILE):
            raise ValueError('File exceeds task limit')
        if cfg.get('allowed_extensions') and name.rsplit('.', 1)[-1].lower() not in cfg['allowed_extensions']:
            raise ValueError('File extension is not allowed')
    if total > min(cfg.get('max_total_bytes', transport.MAX_FILE), transport.MAX_FILE):
        raise ValueError('Solution exceeds task limit')


def submit(answer_id, checked_value, check_config, question_body, check_type, max_points, *, commit=True):
    answer, attempt = lock_answer(answer_id)
    if not answer or not attempt or answer_fingerprint(answer.value) != answer_fingerprint(checked_value):
        if commit: db.session.rollback()
        return True, None
    # Validate configuration before committing an execution that cannot be dispatched.
    transport.key()
    run_id, submission_id = str(uuid.uuid4()), str(uuid.uuid4())
    snapshot = make_snapshot(run_id, submission_id, answer, answer.question, attempt)
    old = db.session.get(ExecutionRun, answer.latest_execution_id) if answer.latest_execution_id else None
    if (old and not old.finished_at and old.fingerprint == answer_fingerprint(checked_value)
            and old.snapshot['task'] == snapshot['task']
            and (mode_repository(snapshot, old.snapshot) or (old.snapshot['files'] == snapshot['files'] and old.snapshot['answer'] == snapshot['answer']))):
        if commit: db.session.rollback()
        return True, None
    run = ExecutionRun(id=run_id, submission_id=submission_id, answer_id=answer.id,
                       fingerprint=answer_fingerprint(checked_value), snapshot=snapshot,
                       state='queued', progress=dict(phase='queued', completed=0, total=0))
    db.session.add(run)
    answer.latest_execution_id = run_id
    answer.check_state = 'checking'
    if attempt.finished_at: attempt.is_checked = False
    if commit:
        db.session.commit()
        publish_created(run_id)
    return True, None


def publish_created(run_id):
    run = db.session.get(ExecutionRun, run_id)
    answer = db.session.get(Answer, run.answer_id)
    attempt = answer.attempt
    try:
        from socket_events import publish_attempt_change
        publish_attempt_change(attempt)
        from manage import socketio
        socketio.emit('execution_created', dict(answer_id=answer.id, question_id=answer.question_id,
            execution_id=run.id, subscription=transport.subscription(run.id, attempt.user_id)), room=f'attempt_{attempt.id}')
    except Exception:
        from flask import current_app
        current_app.logger.warning('execution_created_event_deferred execution_id=%s', run.id)
    from celery_tasks.execution import dispatch_execution
    try: dispatch_execution.delay(run_id)
    except Exception:
        # The database outbox is retried by beat; broker outage must not lose a submission.
        from flask import current_app
        current_app.logger.warning('execution_dispatch_deferred execution_id=%s', run_id)
    return True, None


def mode_repository(first, second):
    return bool(first.get('repository') and second.get('repository') and all(
        first['repository'].get(key) == second['repository'].get(key) for key in ('url', 'ref')))


def execution_links(attempt_id, user_id, answers=None):
    links = []
    for answer in (Answer.query.filter_by(attempt_id=attempt_id) if answers is None else answers):
        if getattr(answer, 'latest_execution_id', None):
            links.append(dict(answer_id=answer.id, question_id=answer.question_id, execution_id=answer.latest_execution_id,
                              subscription=transport.subscription(answer.latest_execution_id, user_id)))
    return links


def input_snapshot(run):
    if run.snapshot.get('repository') and (not run.snapshot['repository'].get('commit') or not run.snapshot.get('files')):
        abort(409, 'Repository capture is pending')
    value = deepcopy(run.snapshot)
    value.pop('grading', None)
    value.pop('repository', None)
    return transport.with_urls(value, run.id)


def public_check_config(question):
    cfg = deepcopy(question.check_config or {})
    if question.check_type not in ('ai', 'docker'): return cfg
    public = {k: cfg[k] for k in ('lang', 'allowed_languages', 'submission_modes', 'allowed_extensions',
        'entrypoint', 'max_files', 'max_file_bytes', 'max_total_bytes', 'score_step') if k in cfg}
    if question.check_type == 'docker':
        public['tests'] = [dict(name=row.get('name'), hidden=True) if row.get('hidden') else row for row in cfg.get('tests', [])]
    return public


def progress(run_id, value):
    phases = ('queued', 'preparing', 'compiling', 'testing', 'grading', 'publishing')
    if (value.get('execution_id') != run_id or type(value.get('sequence')) is not int or value['sequence'] < 1
            or value.get('phase') not in phases or type(value.get('completed')) is not int
            or type(value.get('total')) is not int or not 0 <= value['completed'] <= value['total'] <= 200):
        abort(422)
    db.session.query(ExecutionRun).filter(ExecutionRun.id == run_id, ExecutionRun.finished_at.is_(None),
        ExecutionRun.sequence < value['sequence']).update(dict(sequence=value['sequence'], state='running',
        progress={k: value[k] for k in ('phase', 'completed', 'total')}))
    db.session.commit()


def validate_fields(value):
    if isinstance(value, dict):
        if value.get('type') in ('blob', 'inline'):
            size, digest = value.get('bytes'), value.get('sha256')
            if type(size) is not int or not 0 <= size <= 32 * 1024 * 1024 or type(value.get('truncated')) is not bool:
                abort(422, 'Invalid result artifact')
            try:
                path = transport.artifact_path(digest)
                if value['type'] == 'blob':
                    if value.get('blob_id') != digest or not path.is_file() or path.stat().st_size != size: raise ValueError
                else:
                    raw = value['text'].encode('utf-8')
                    if len(raw) != size or size > 65536 or hashlib.sha256(raw).hexdigest() != digest: raise ValueError
            except (ValueError, KeyError, AttributeError): abort(422, 'Missing or invalid artifact')
        else:
            for item in value.values(): validate_fields(item)
    elif isinstance(value, list):
        for item in value: validate_fields(item)


def public_comment(result, snapshot):
    if snapshot['grading']['check_type'] != 'docker': return result['comment'].replace('\0', '')
    statistics = result.get('statistics', {})
    tests = snapshot['task']['test_config']['tests']
    lines = [result['comment']]
    for index, detail in enumerate(statistics.get('details', [])):
        if not isinstance(detail, dict) or index >= len(tests): break
        verdict = 'пройден' if detail.get('ok') else detail.get('error_type') or 'неверный ответ'
        lines.append(f'{index + 1}. {tests[index].get("name", "Тест " + str(index + 1))}: {verdict}')
        if (not tests[index].get('hidden') or detail.get('error_type') == 'compilation_error') and detail.get('error'):
            field = detail['error']
            if isinstance(field, dict) and field.get('type') == 'inline': lines.append(field['text'][:8000])
    return '\n'.join(lines).replace('\0', '')[:200000]


def accept_result(run_id, value, digest):
    initial = db.session.get(ExecutionRun, run_id)
    if not initial: abort(404)
    answer, attempt = lock_answer(initial.answer_id)
    run = ExecutionRun.query.filter_by(id=run_id).populate_existing().with_for_update().one()
    if run.result_hash:
        if run.result_hash != digest: abort(409, 'Result is immutable')
        db.session.rollback()
        return
    maximum = run.snapshot['task']['points']
    if (value.get('execution_id') != run_id or value.get('state') not in ('done', 'partially done', 'execution error')
            or type(value.get('points')) is not int or not 0 <= value['points'] <= maximum
            or not isinstance(value.get('comment'), str) or len(value['comment'].encode()) > 200000):
        abort(422)
    validate_fields(value)
    run.result = value
    run.result_hash = digest
    run.finished_at = datetime.utcnow()
    run.state = 'error' if value['state'] == 'execution error' else 'completed'
    run.progress = dict(phase=run.state, completed=value.get('statistics', {}).get('tests_total', 0),
                        total=value.get('statistics', {}).get('tests_total', 0))
    payload = None
    if (answer and attempt and answer.latest_execution_id == run.id and answer.check_state == 'checking'
            and answer_fingerprint(answer.value) == run.fingerprint):
        cfg = run.snapshot['grading']
        points = round_points(cfg['max_points'] * value['points'] / maximum if maximum else 0, cfg)
        statistics = value.get('statistics', {})
        error = value['state'] == 'execution error' or statistics.get('verdict') == 'compilation_error'
        comment = public_comment(value, run.snapshot)
        if attempt.finished_at:
            if value['state'] != 'execution error': answer.points = 0 if error else points
            answer.check_state = 'error' if error else 'checked'
            answer.check_comment = comment
            attempt.is_checked = False
            attempt.total_points = None
        else:
            answer.points = None
            answer.check_state = 'pending'
            answer.check_comment = None
        payload = dict(answer_id=answer.id, question_id=answer.question_id, points=answer.points if attempt.finished_at else 0 if error else points,
                       check_state=answer.check_state if attempt.finished_at else 'error' if error else 'intermediate',
                       check_comment=comment, checked_value=deepcopy(answer.value))
        run.applied = True
    db.session.commit()
    if payload:
        from manage import socketio
        try: socketio.emit('answer_checked', payload, room=f'attempt_{attempt.id}')
        except Exception:
            from flask import current_app
            current_app.logger.warning('answer_event_delivery_failed execution_id=%s', run.id)
        if attempt.finished_at:
            from celery_tasks.check_answer import _finalize_attempt_if_done_inner
            _finalize_attempt_if_done_inner(attempt.id)


def run_view(run, user_id, teacher=False):
    value = dict(execution_id=run.id, state=run.state, progress=run.progress, sequence=run.sequence,
                 applied=run.applied, subscription=transport.subscription(run.id, user_id))
    value['answer'] = run.snapshot.get('answer')
    value['files'] = [dict(path=file['name'], bytes=file['artifact']['bytes'], artifact=file['artifact']) for file in run.snapshot['files']]
    if run.snapshot.get('repository'):
        repository = run.snapshot['repository']
        value['repository'] = {key: repository[key] for key in ('url', 'ref', 'commit') if key in repository}
        if repository.get('archive'): value['repository']['archive'] = repository['archive']
    if run.result:
        value['comment'] = public_comment(run.result, run.snapshot)
        statistics = run.result.get('statistics', {})
        value['statistics'] = {k: statistics.get(k) for k in ('tests_passed', 'tests_total', 'verdict', 'error_type')}
        tests = run.snapshot['task'].get('test_config', {}).get('tests', [])
        details = []
        for index, item in enumerate(statistics.get('details', [])):
            row = dict(number=index + 1, ok=item.get('ok', False), error_type=item.get('error_type'))
            if teacher or (index < len(tests) and not tests[index].get('hidden')):
                row.update({key: item[key] for key in ('input', 'expected', 'got', 'error') if key in item})
            details.append(row)
        value['statistics']['details'] = details
        if teacher:
            value['result'] = run.result
            value['configuration'] = run.snapshot['task']
    def links(item):
        if isinstance(item, dict):
            if item.get('type') == 'blob': return dict(item, download_url=f'/api/executions/{run.id}/artifacts/{item["blob_id"]}')
            return {key: links(child) for key, child in item.items()}
        if isinstance(item, list): return [links(child) for child in item]
        return item
    return links(value)
