"""Shared execution protocol plus authenticated APIs for future submission UIs."""
from datetime import datetime
import hashlib
import hmac
import json
import time
import uuid

from flask import Blueprint, abort, jsonify, request, send_file
import jwt

from auth import api_login_required, teacher_required, current_role, current_user_id
from models import db, Answer, Question
from execution_models import ExecutionRun, ExecutionUpload, ExecutionTaskFile
from attempt_lifecycle import lock_answer, finish_if_expired
from guard_admission import admission_error, attempt_access_allowed
import executor_service as service
import executor_transport as transport

executor_bp = Blueprint('executor', __name__)


def read_body(purpose, maximum=524288):
    if request.content_length and request.content_length > maximum: abort(413)
    raw = request.stream.read(maximum + 1)
    if len(raw) > maximum: abort(413)
    claims = transport.verify(purpose, body=False)
    if not hmac.compare_digest(claims.get('body_sha256', ''), hashlib.sha256(raw).hexdigest()): abort(401)
    return raw


def read_json(purpose, maximum=524288):
    raw = read_body(purpose, maximum)
    try: value = json.loads(raw)
    except (ValueError, RecursionError): abort(422)
    if not isinstance(value, dict): abort(422)
    return value, hashlib.sha256(raw).hexdigest()


@executor_bp.after_request
def private_headers(response):
    response.headers['Cache-Control'] = 'private, no-store'
    response.headers['X-Content-Type-Options'] = 'nosniff'
    return response


@executor_bp.get('/api/executor/executions/<execution_id>/input')
def execution_input(execution_id):
    transport.verify('execution-input', body=False)
    run = db.get_or_404(ExecutionRun, execution_id)
    return jsonify(service.input_snapshot(run))


@executor_bp.post('/api/executor/executions/<execution_id>/progress')
def execution_progress(execution_id):
    value, _ = read_json('execution-progress')
    db.get_or_404(ExecutionRun, execution_id)
    service.progress(execution_id, value)
    return jsonify(state='ok')


@executor_bp.post('/api/executor/executions/<execution_id>/result')
def execution_result(execution_id):
    value, digest = read_json('execution-result')
    service.accept_result(execution_id, value, digest)
    return jsonify(state='ok', execution_id=execution_id)


@executor_bp.post('/api/executor/test-artifacts/status')
def artifact_status():
    value, _ = read_json('test-artifacts', 20000)
    ids = value.get('ids')
    if not isinstance(ids, list) or len(ids) > 200: abort(422)
    try: missing = [digest for digest in ids if not transport.artifact_path(digest).is_file()]
    except ValueError: abort(422)
    return jsonify(missing=missing)


@executor_bp.put('/api/executor/test-artifacts/<digest>')
def upload_artifact(digest):
    raw = read_body('test-artifact-upload', 32 * 1024 * 1024)
    if hashlib.sha256(raw).hexdigest() != digest: abort(422)
    return jsonify(transport.store(raw))


@executor_bp.get('/api/executor/artifacts/<digest>')
def execution_artifact(digest):
    try:
        claims = jwt.decode(request.args.get('token'), transport.key(), algorithms=['HS256'], issuer='geekexam',
                            audience='geekexam', options={'require': ['iat', 'exp', 'purpose', 'execution_id', 'blob_id']})
        if (claims['purpose'] != 'execution-artifact' or claims['blob_id'] != digest
                or type(claims['iat']) is not int or type(claims['exp']) is not int or not 0 < claims['exp'] - claims['iat'] <= 300): raise ValueError
        run = db.session.get(ExecutionRun, claims['execution_id'])
        if not run or digest not in set(transport.artifact_ids(run.snapshot)): raise ValueError
        path = transport.artifact_path(digest)
    except (jwt.PyJWTError, ValueError, TypeError, KeyError): abort(401)
    if not path.is_file(): abort(404)
    return send_file(path, as_attachment=True, download_name='data.bin', mimetype='application/octet-stream')


def owned_answer(answer_id):
    answer = db.get_or_404(Answer, answer_id)
    if current_role() not in ('teacher', 'admin'):
        if answer.attempt.user_id != current_user_id():
            abort(403)
        if not attempt_access_allowed(answer.attempt):
            abort(admission_error())
    return answer


@executor_bp.get('/api/answers/<int:answer_id>/execution')
@api_login_required
def latest_execution(answer_id):
    answer = owned_answer(answer_id)
    if not answer.latest_execution_id: return jsonify(execution=None)
    return jsonify(service.run_view(db.get_or_404(ExecutionRun, answer.latest_execution_id), current_user_id(), current_role() in ('teacher', 'admin')))


@executor_bp.get('/api/answers/<int:answer_id>/executions')
@api_login_required
def execution_history(answer_id):
    owned_answer(answer_id)
    page = max(1, request.args.get('page', 1, type=int))
    rows = ExecutionRun.query.filter_by(answer_id=answer_id).order_by(ExecutionRun.created_at.desc()).paginate(page=page, per_page=20, error_out=False)
    return jsonify(items=[dict(execution_id=row.id, state=row.state, applied=row.applied, created_at=row.created_at.isoformat() + 'Z') for row in rows.items], has_more=rows.has_next)


@executor_bp.get('/api/executions/<execution_id>')
@api_login_required
def inspect_execution(execution_id):
    run = db.get_or_404(ExecutionRun, execution_id)
    owned_answer(run.answer_id)
    return jsonify(service.run_view(run, current_user_id(), current_role() in ('teacher', 'admin')))


@executor_bp.get('/api/executions/<execution_id>/artifacts/<digest>')
@api_login_required
def result_artifact(execution_id, digest):
    run = db.get_or_404(ExecutionRun, execution_id)
    owned_answer(run.answer_id)
    allowed = set(transport.artifact_ids(run.snapshot['files']))
    allowed.update(transport.artifact_ids((run.snapshot.get('repository') or {}).get('archive')))
    if current_role() in ('teacher', 'admin'):
        allowed.update(transport.artifact_ids(run.snapshot))
        allowed.update(transport.artifact_ids(run.result))
    else:
        tests = run.snapshot['task'].get('test_config', {}).get('tests', [])
        for index, detail in enumerate((run.result or {}).get('statistics', {}).get('details', [])):
            if index < len(tests) and not tests[index].get('hidden'): allowed.update(transport.artifact_ids(detail))
    if digest not in allowed: abort(403)
    try: path = transport.artifact_path(digest)
    except ValueError: abort(404)
    if not path.is_file(): abort(404)
    return send_file(path, as_attachment=True, download_name='data.bin', mimetype='application/octet-stream')


@executor_bp.route('/api/answers/<int:answer_id>/files', methods=['GET', 'POST'])
@api_login_required
def upload_answer_file(answer_id):
    if request.method == 'GET':
        owned_answer(answer_id)
        return jsonify(items=[dict(id=row.id, path=row.name, bytes=row.artifact['bytes'],
            download_url=f'/api/answers/{answer_id}/files/{row.id}')
            for row in ExecutionUpload.query.filter_by(answer_id=answer_id).order_by(ExecutionUpload.created_at)])
    if request.content_length and request.content_length > 53 * 1024 * 1024: abort(413)
    answer, attempt = lock_answer(answer_id)
    if not answer: abort(404)
    if attempt.user_id != current_user_id(): abort(403)
    if not attempt_access_allowed(attempt): return admission_error()
    if attempt.finished_at or finish_if_expired(attempt): abort(409)
    if ExecutionUpload.query.filter_by(answer_id=answer.id).count() >= 200: abort(422, 'Too many uploaded files')
    file = request.files.get('file')
    if not file: abort(422)
    try:
        name = service.safe_path(request.form.get('path') or file.filename)
        raw = file.read(transport.MAX_FILE + 1)
        artifact = transport.store(raw)
    except ValueError as error: abort(422, str(error))
    record = ExecutionUpload(id=str(uuid.uuid4()), answer_id=answer.id, name=name, artifact=artifact)
    db.session.add(record); db.session.commit()
    return jsonify(id=record.id, path=record.name, bytes=artifact['bytes']), 201


@executor_bp.route('/api/answers/<int:answer_id>/files/<file_id>', methods=['GET', 'DELETE'])
@api_login_required
def answer_file(answer_id, file_id):
    answer = owned_answer(answer_id)
    row = ExecutionUpload.query.filter_by(answer_id=answer_id, id=file_id).first_or_404()
    if request.method == 'DELETE':
        answer, attempt = lock_answer(answer_id)
        if attempt.user_id != current_user_id(): abort(403)
        if not attempt_access_allowed(attempt): return admission_error()
        if attempt.finished_at or finish_if_expired(attempt): abort(409)
        value = answer.value if isinstance(answer.value, dict) else {}
        selected = value.get('files', [])
        if isinstance(selected, list) and any(isinstance(file, dict) and file.get('upload_id') == file_id for file in selected):
            abort(409, 'Remove the file from the saved answer first')
        db.session.delete(row); db.session.commit()
        return jsonify(deleted=True)
    return send_file(transport.artifact_path(row.artifact['blob_id']), as_attachment=True,
                     download_name=row.name.rsplit('/', 1)[-1], mimetype='application/octet-stream')


@executor_bp.route('/api/questions/<int:question_id>/files', methods=['GET', 'POST'])
@teacher_required
def question_files(question_id):
    db.get_or_404(Question, question_id)
    if request.method == 'POST':
        file = request.files.get('file')
        if not file: abort(422)
        kind = request.form.get('kind', 'attachment')
        public = request.form.get('is_public', 'true') in ('true', '1')
        if kind not in ('attachment', 'starter', 'resource') or (kind != 'attachment' and not public): abort(422)
        try:
            name = service.safe_path(request.form.get('path') or file.filename)
            artifact = transport.store(file.read(transport.MAX_FILE + 1))
        except ValueError as error: abort(422, str(error))
        if ExecutionTaskFile.query.filter_by(question_id=question_id, deleted_at=None).count() >= 100: abort(422)
        if ExecutionTaskFile.query.filter_by(question_id=question_id, name=name, deleted_at=None).first(): abort(409)
        row = ExecutionTaskFile(id=str(uuid.uuid4()), question_id=question_id, name=name, kind=kind, is_public=public,
            read_only=request.form.get('read_only') in ('1', 'true'), include_in_check=request.form.get('include_in_check') in ('1', 'true'), artifact=artifact)
        db.session.add(row); db.session.commit()
    rows = ExecutionTaskFile.query.filter_by(question_id=question_id, deleted_at=None).all()
    return jsonify(items=[dict(id=row.id, path=row.name, kind=row.kind, is_public=row.is_public,
                              read_only=row.read_only, include_in_check=row.include_in_check, bytes=row.artifact['bytes']) for row in rows]), 201 if request.method == 'POST' else 200


@executor_bp.delete('/api/questions/<int:question_id>/files/<file_id>')
@teacher_required
def remove_question_file(question_id, file_id):
    file = ExecutionTaskFile.query.filter_by(question_id=question_id, id=file_id, deleted_at=None).first_or_404()
    file.deleted_at = datetime.utcnow(); db.session.commit()
    return jsonify(deleted=True)


@executor_bp.get('/api/questions/<int:question_id>/files/<file_id>')
@teacher_required
def question_file(question_id, file_id):
    row = ExecutionTaskFile.query.filter_by(question_id=question_id, id=file_id, deleted_at=None).first_or_404()
    return send_file(transport.artifact_path(row.artifact['blob_id']), as_attachment=True,
                     download_name=row.name.rsplit('/', 1)[-1], mimetype='application/octet-stream')


@executor_bp.get('/api/attempts/<int:attempt_id>/questions/<int:question_id>/files')
@api_login_required
def attempt_files(attempt_id, question_id):
    from models import Attempt
    attempt = db.get_or_404(Attempt, attempt_id)
    question = db.get_or_404(Question, question_id)
    if question.variant_id != attempt.variant_id: abort(404)
    teacher = current_role() in ('teacher', 'admin')
    if attempt.user_id != current_user_id() and not teacher: abort(403)
    if not teacher and not attempt_access_allowed(attempt): return admission_error()
    query = ExecutionTaskFile.query.filter_by(question_id=question_id, deleted_at=None)
    if not teacher: query = query.filter_by(is_public=True)
    return jsonify(items=[dict(id=row.id, path=row.name, kind=row.kind, read_only=row.read_only,
        bytes=row.artifact['bytes'], download_url=f'/api/attempts/{attempt_id}/questions/{question_id}/files/{row.id}') for row in query.order_by(ExecutionTaskFile.name)])


@executor_bp.get('/api/attempts/<int:attempt_id>/questions/<int:question_id>/files/<file_id>')
@api_login_required
def attempt_file(attempt_id, question_id, file_id):
    from models import Attempt
    attempt = db.get_or_404(Attempt, attempt_id)
    question = db.get_or_404(Question, question_id)
    teacher = current_role() in ('teacher', 'admin')
    if question.variant_id != attempt.variant_id: abort(404)
    if attempt.user_id != current_user_id() and not teacher: abort(403)
    if not teacher and not attempt_access_allowed(attempt): return admission_error()
    file = ExecutionTaskFile.query.filter_by(question_id=question_id, id=file_id, deleted_at=None).first_or_404()
    if not file.is_public and not teacher: abort(403)
    return send_file(transport.artifact_path(file.artifact['blob_id']), as_attachment=True,
                     download_name=file.name.rsplit('/', 1)[-1], mimetype='application/octet-stream')
