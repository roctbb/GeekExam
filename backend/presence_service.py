"""Correlate independently timestamped connection evidence. Never change grades."""
from datetime import datetime,timedelta,timezone
import hashlib

from flask import current_app
from models import db,Attempt,Test
from presence_models import PresenceConfig,PresenceClient,PresenceHeartbeat,AttemptPresence,PresenceEvent
from time_utils import utc_iso
import guard_client

HEARTBEAT_TTL=20
GUARD_TTL=20


def now():
    return current_app.config.get('PRESENCE_NOW',datetime.utcnow)()


def parse(value):
    if not value:return None
    parsed=datetime.fromisoformat(value.replace('Z','+00:00'))
    return (parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed).astimezone(timezone.utc).replace(tzinfo=None)


def ensure_config(test):
    row=db.session.get(PresenceConfig,test.id)
    if row is None:
        row=PresenceConfig(test_id=test.id,enabled=True,configured_by=test.created_by,updated_at=now())
        db.session.add(row);db.session.flush()
    return row


def ensure_attempt(attempt):
    row=db.session.get(AttemptPresence,attempt.id)
    if row is None:
        row=AttemptPresence(attempt_id=attempt.id)
        db.session.add(row);db.session.flush()
    return row


def event(test_id,key,kind,at,*,attempt_id=None,router_id=None,last_confirmed=None,details=None):
    key=hashlib.sha256(key.encode()).hexdigest()
    row=db.session.execute(db.select(PresenceEvent).where(PresenceEvent.test_id==test_id,PresenceEvent.source_key==key)).scalar_one_or_none()
    if row is None:
        row=PresenceEvent(test_id=test_id,attempt_id=attempt_id,source_key=key,kind=kind,
            router_id=router_id,started_at=at,detected_at=now(),last_confirmed_at=last_confirmed,details=details or {})
        db.session.add(row);db.session.flush()
    return row


def guard_admission_event():
    # Strict test admission uses a test-scoped proof, before any attempt client is registered.
    return db.and_(
        PresenceEvent.kind == 'binding_confirmed',
        PresenceEvent.details['method'].as_string() == 'browser_lan_proof',
        PresenceEvent.details['proof_id'].as_string().is_not(None),
        PresenceEvent.details['client_code'].as_string().is_(None),
    )


def exam_status(attempt,at):
    clients=db.session.execute(db.select(PresenceClient).where(PresenceClient.attempt_id==attempt.id)).scalars().all()
    last=max((client.last_seen_at for client in clients),default=None)
    active=[client for client in clients if at-client.last_seen_at<=timedelta(seconds=HEARTBEAT_TTL)]
    state='finished' if attempt.finished_at else 'not_seen' if not last else 'online' if active else 'offline'
    return {'state':state,'last_seen_at':utc_iso(last),'since':utc_iso(last+timedelta(seconds=HEARTBEAT_TTL)) if state=='offline' else None,
            'active_clients':len(active),'clients':[{'id':client.id,'code':client.id[:8].upper(),
             'last_seen_at':utc_iso(client.last_seen_at),'visible':client.visible} for client in clients]}


def update_review_evidence(attempt):
    """A cached 'online' state is insufficient: require a later server heartbeat."""
    rows=db.session.execute(db.select(PresenceEvent).where(PresenceEvent.attempt_id==attempt.id,
        PresenceEvent.kind=='device_disconnected',PresenceEvent.exam_continued_at.is_(None))).scalars().all()
    for row in rows:
        if row.details.get('mass_disconnect') or not row.details.get('history_complete',False):continue
        upper=min([value for value in [row.ended_at,attempt.finished_at] if value],default=now())
        heartbeat=db.session.execute(db.select(PresenceHeartbeat).where(PresenceHeartbeat.attempt_id==attempt.id,
            PresenceHeartbeat.received_at>row.started_at,PresenceHeartbeat.received_at<=upper
        ).order_by(PresenceHeartbeat.received_at,PresenceHeartbeat.id)).scalars().first()
        if heartbeat:
            row.exam_continued_at=heartbeat.received_at
            row.review_required=True
            row.details={**row.details,'evidence_client_id':heartbeat.client_id,'evidence_sequence':heartbeat.sequence}


def close_guard_gaps(attempt):
    for gap in db.session.execute(db.select(PresenceEvent).where(
        PresenceEvent.attempt_id == attempt.id, PresenceEvent.kind == 'device_disconnected',
        PresenceEvent.ended_at.is_(None),
    )).scalars():
        gap.ended_at = now()
        gap.details = {**gap.details, 'closed_by': 'binding_changed'}
    update_review_evidence(attempt)


def update_exam_gaps(attempt,at):
    status=exam_status(attempt,at)
    if status['state']=='offline':
        event(attempt.test_id,'exam-gap:'+str(attempt.id)+':'+status['last_seen_at'],'exam_disconnected',
              parse(status['since']),attempt_id=attempt.id,last_confirmed=parse(status['last_seen_at']))
    if status['state']=='online':
        for row in db.session.execute(db.select(PresenceEvent).where(PresenceEvent.attempt_id==attempt.id,
            PresenceEvent.kind=='exam_disconnected',PresenceEvent.ended_at.is_(None))).scalars():
            if parse(status['last_seen_at'])>row.started_at:row.ended_at=parse(status['last_seen_at'])
    update_review_evidence(attempt)


def ingest_guard(config,attempts,data,at):
    if not isinstance(data.get('items'),list) or not isinstance(data.get('events'),list) or not isinstance(data.get('room'),dict):
        raise ValueError('Invalid Guard response')
    if data['room'].get('id')!=config.guard_room_id:raise ValueError('Wrong Guard room')
    server_time=parse(data['server_time'])
    if abs((at-server_time).total_seconds())>GUARD_TTL:raise ValueError('Stale Guard response')
    by_session={item['session_id']:item for item in data['items']}
    routers=data['room'].get('routers',[])
    complete=data.get('history_complete') is True
    cutoff=max((attempt.finished_at for attempt in attempts),default=at) if all(a.finished_at for a in attempts) else at
    for raw in data['events']:
        if parse(raw['occurred_at'])>cutoff:continue
        if raw['kind']=='source_lost':
            event(config.test_id,'source-gap:'+raw['router_id']+':'+raw['occurred_at'],'guard_source_lost',
                parse(raw['occurred_at']),router_id=raw['router_id'],last_confirmed=parse(raw.get('last_confirmed_at')),
                details={'reason':raw.get('reason'),'scope':'classroom'})
        elif raw['kind']=='source_recovered':
            for row in db.session.execute(db.select(PresenceEvent).where(PresenceEvent.test_id==config.test_id,
                PresenceEvent.router_id==raw['router_id'],PresenceEvent.kind=='guard_source_lost',
                PresenceEvent.ended_at.is_(None),PresenceEvent.started_at<=parse(raw['occurred_at']))).scalars():
                row.ended_at=parse(raw['occurred_at'])
        elif raw['kind']=='agent_restarted':
            event(config.test_id,'guard:'+raw['id'],'agent_restarted',parse(raw['occurred_at']),
                router_id=raw['router_id'],details={'scope':'classroom'})
    for router in routers if any(not a.finished_at for a in attempts) else []:
        if not router.get('fresh') and router.get('unavailable_since'):
            event(config.test_id,'source-gap:'+router['id']+':'+router['unavailable_since'],'guard_source_lost',
                parse(router['unavailable_since']),router_id=router['id'],last_confirmed=parse(router.get('observed_at')),
                details={'reason':router.get('reason'),'scope':'classroom'})
        elif router.get('fresh'):
            for row in db.session.execute(db.select(PresenceEvent).where(PresenceEvent.test_id==config.test_id,
                PresenceEvent.router_id==router['id'],PresenceEvent.kind=='guard_source_lost',PresenceEvent.ended_at.is_(None))).scalars():
                row.ended_at=server_time
    for attempt in attempts:
        state=ensure_attempt(attempt)
        if not state.guard_session_id:continue
        item=by_session.get(state.guard_session_id)
        if not item or item.get('user_id') not in {None,attempt.user_id}:
            state.guard_state,state.guard_reason='unbound','identity_mismatch';state.guard_checked_at=at;continue
        if item.get('state') not in {'online','offline','unknown','unbound'}:raise ValueError('Invalid Guard state')
        if not attempt.finished_at:
            state.guard_state,state.guard_reason=item['state'],item.get('reason')
            state.guard_since=parse(item.get('since'));state.guard_last_confirmed_at=parse(item.get('last_confirmed_at'))
            state.guard_checked_at=at;state.history_complete=complete
        relevant=[raw for raw in data['events'] if raw.get('session_id')==state.guard_session_id]
        baseline=max(value for value in [state.binding_observed_at,attempt.started_at] if value)
        for raw in relevant:
            occurred=parse(raw['occurred_at'])
            if occurred<baseline or (attempt.finished_at and occurred>attempt.finished_at):continue
            if raw['kind']=='device_disconnected':
                mass=raw.get('batch_departed',0)>=3 and raw.get('batch_departed',0)*2>=raw.get('batch_total',1)
                row=event(config.test_id,'guard:'+raw['id']+':'+str(attempt.id),'device_disconnected',occurred,
                    attempt_id=attempt.id,router_id=raw['router_id'],last_confirmed=parse(raw.get('last_confirmed_at')),
                    details={'history_complete':complete,'mass_disconnect':mass,'guard_event_id':raw['id'],
                             'session_id':state.guard_session_id,'binding_client_id':state.bound_client_id})
                if complete and not row.details.get('history_complete'):row.details={**row.details,'history_complete':True}
                if mass:
                    event(config.test_id,'mass:'+raw['router_id']+':'+raw['batch'],'mass_disconnect',occurred,
                        router_id=raw['router_id'],details={'count':raw['batch_departed'],'scope':'classroom'})
            elif raw['kind']=='binding_changed':
                event(config.test_id,'guard:'+raw['id']+':'+str(attempt.id),'binding_changed',occurred,
                    attempt_id=attempt.id,router_id=raw['router_id'],details={'reason':raw.get('reason')})
        for raw in relevant:
            if raw['kind']!='device_reconnected':continue
            recovered=parse(raw['occurred_at'])
            if attempt.finished_at and recovered>attempt.finished_at:continue
            for row in db.session.execute(db.select(PresenceEvent).where(PresenceEvent.attempt_id==attempt.id,
                PresenceEvent.kind=='device_disconnected',PresenceEvent.ended_at.is_(None),PresenceEvent.started_at<recovered)).scalars():
                if row.details.get('session_id')==state.guard_session_id:row.ended_at=recovered
        update_review_evidence(attempt)
        if attempt.finished_at:finish_monitoring(attempt)


def mark_guard_unavailable(config,attempts,reason,at):
    # The service connection is missing; this is never an individual departure.
    if not any(not attempt.finished_at for attempt in attempts):return
    open_gap=db.session.execute(db.select(PresenceEvent).where(PresenceEvent.test_id==config.test_id,
        PresenceEvent.kind=='guard_service_unavailable',PresenceEvent.ended_at.is_(None))).scalars().first()
    if not open_gap:event(config.test_id,'service-gap:'+utc_iso(at),'guard_service_unavailable',at,details={'reason':reason,'scope':'classroom'})
    for attempt in attempts:
        state=ensure_attempt(attempt)
        if state.guard_session_id and not attempt.finished_at:
            state.guard_state,state.guard_reason='unknown',reason
            state.guard_checked_at=at


def collect_test(config):
    version, actor_id = config.version, config.configured_by
    room_id = config.guard_room_id if config.require_guard else None
    # Briefly reconcile historical observations at submission, without accepting
    # any new browser contact or events after the attempt's finish timestamp.
    active=db.or_(Attempt.finished_at.is_(None),Attempt.finished_at>=now()-timedelta(seconds=60))
    attempts=db.session.execute(db.select(Attempt).where(Attempt.test_id==config.test_id,active)).scalars().all()
    if not attempts:return
    data,error=None,None
    initial_states={row.attempt_id:row.guard_session_id for row in db.session.execute(
        db.select(AttemptPresence).where(AttemptPresence.attempt_id.in_([a.id for a in attempts]))).scalars()}
    if room_id:
        # Never create/flush rows or hold row locks while waiting on Guard.
        sessions=list(dict.fromkeys(value for value in initial_states.values() if value))
        try:
            if len(sessions)>200:raise guard_client.GuardUnavailable('too_many_bindings')
            since=min(attempt.started_at for attempt in attempts)
            data=guard_client.call('snapshot',actor_id,room_id=room_id,
                                   session_ids=sessions,since=utc_iso(since))
        except guard_client.GuardUnavailable as failure:
            error=failure.reason
    # Match the lock order used by binding/configuration and attempt submission.
    db.session.execute(db.select(Test).where(Test.id==config.test_id).with_for_update()).scalar_one()
    config=db.session.execute(db.select(PresenceConfig).where(PresenceConfig.test_id==config.test_id)
        .execution_options(populate_existing=True)).scalar_one()
    if not config.enabled or config.version!=version:
        db.session.rollback();return
    attempts=db.session.execute(db.select(Attempt).where(Attempt.test_id==config.test_id,active)
        .order_by(Attempt.id).execution_options(populate_existing=True).with_for_update()).scalars().all()
    for attempt in attempts:update_exam_gaps(attempt,now())
    if room_id:
        try:
            if error:raise guard_client.GuardUnavailable(error)
            # A malformed response cannot leave partially applied evidence behind.
            with db.session.begin_nested():
                stable=[]
                for attempt in attempts:
                    state=db.session.get(AttemptPresence,attempt.id,populate_existing=True)
                    if (state.guard_session_id if state else None)==initial_states.get(attempt.id):stable.append(attempt)
                ingest_guard(config,stable,data,now())
            for row in db.session.execute(db.select(PresenceEvent).where(PresenceEvent.test_id==config.test_id,
                PresenceEvent.kind=='guard_service_unavailable',PresenceEvent.ended_at.is_(None))).scalars():row.ended_at=now()
        except (guard_client.GuardUnavailable,ValueError,KeyError,TypeError) as error:
            mark_guard_unavailable(config,attempts,getattr(error,'reason','invalid_guard_response'),now())
    db.session.commit()


def finish_monitoring(attempt):
    """Close intervals at submission; a late client may never extend the evidence."""
    update_review_evidence(attempt)
    for row in db.session.execute(db.select(PresenceEvent).where(PresenceEvent.attempt_id==attempt.id,
        PresenceEvent.ended_at.is_(None))).scalars():
        row.ended_at=max(row.started_at,attempt.finished_at)
        row.details={**row.details,'closed_by':'attempt_finished'}


def event_view(row):
    return {'id':row.id,'attempt_id':row.attempt_id,'kind':row.kind,'started_at':utc_iso(row.started_at),
        'detected_at':utc_iso(row.detected_at),'last_confirmed_at':utc_iso(row.last_confirmed_at),
        'ended_at':utc_iso(row.ended_at),'exam_continued_at':utc_iso(row.exam_continued_at),
        'review_required':row.review_required,'reviewed_at':utc_iso(row.reviewed_at),
        'review_note':row.review_note,'details':row.details}


def settings_view(config):
    return {'guard_configured': guard_client.configured(),
            'config': {'enabled': config.enabled if config else True,
                       'require_guard': bool(config and config.require_guard),
                       'room_id': config.guard_room_id if config else None,
                       'room_name': config.guard_room_name if config else None,
                       'version': config.version if config else 0}}


def snapshot(test):
    at=now();config=db.session.get(PresenceConfig,test.id)
    attempts=db.session.execute(db.select(Attempt).where(Attempt.test_id==test.id)).scalars().all()
    rows={row.attempt_id:row for row in db.session.execute(db.select(AttemptPresence).where(AttemptPresence.attempt_id.in_([a.id for a in attempts]))).scalars()}
    events=db.session.execute(db.select(PresenceEvent).where(PresenceEvent.test_id==test.id,
        PresenceEvent.attempt_id.is_(None)).order_by(PresenceEvent.started_at.desc()).limit(50)).scalars().all()
    awaiting_review = db.and_(PresenceEvent.review_required.is_(True), PresenceEvent.reviewed_at.is_(None))
    counts = {
        attempt_id: (total, reviews, guard_admitted)
        for attempt_id, total, reviews, guard_admitted in db.session.execute(
            db.select(
                PresenceEvent.attempt_id, db.func.count(),
                db.func.sum(db.case((awaiting_review, 1), else_=0)),
                db.func.max(db.case((guard_admission_event(), 1), else_=0)),
            ).where(PresenceEvent.test_id == test.id, PresenceEvent.attempt_id.is_not(None))
            .group_by(PresenceEvent.attempt_id)
        )
    }
    result=[]
    for attempt in attempts:
        state=rows.get(attempt.id);exam=exam_status(attempt,at)
        total, reviews, guard_admitted = counts.get(attempt.id, (0, 0, 0))
        current=state.guard_state if state else 'unbound'
        if state and state.guard_checked_at and at-state.guard_checked_at>timedelta(seconds=GUARD_TTL) and not attempt.finished_at:current='unknown'
        result.append({'attempt_id':attempt.id,'guard_admitted':bool(guard_admitted),'exam':exam,'guard':{'state':current,
            'reason':state.guard_reason if state else None,'since':utc_iso(state.guard_since) if state else None,
            'last_confirmed_at':utc_iso(state.guard_last_confirmed_at) if state else None,
            'checked_at':utc_iso(state.guard_checked_at) if state else None,
            'bound':bool(state and state.guard_session_id),'history_complete':state.history_complete if state else True,
            'binding_confirmed_at':utc_iso(state.binding_confirmed_at) if state else None},
            'review_count':reviews or 0,'event_count':total})
    return {'server_time':utc_iso(at),'heartbeat_ttl_seconds':HEARTBEAT_TTL,**settings_view(config),
            'attempts':result,'classroom_events':[event_view(row) for row in events if row.attempt_id is None]}
