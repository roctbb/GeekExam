"""Readable, room-scoped audit pages with a fixed time boundary while paging."""
from datetime import datetime
from math import ceil

from .models import db, AuditEvent, Device, NetworkSession, Router, User
from .policy import parse_time, stamp
from .security import ApiError, now


TITLES = {
    'room.created': 'Кабинет добавлен',
    'room.policy_changed': 'Настройки кабинета изменены',
    'room.members_changed': 'Список доступа к кабинету изменён',
    'room.teachers_changed': 'Доступ преподавателей изменён',
    'router.created': 'Роутер добавлен',
    'router.updated': 'Настройки роутера изменены',
    'router.browser_proof_configured': 'Автопривязка GeekExam настроена',
    'agent.enrollment_created': 'Создан код подключения агента',
    'agent.enrolled': 'Агент подключён к Guard',
    'session.portal_authenticated': 'Вход в Wi-Fi через Coding Projects',
    'session.portal_logged_out': 'Выход из сети',
    'session.manually_confirmed': 'Пользователь привязан к устройству',
    'session.browser_lan_proved': 'Устройство подтверждено для GeekExam',
    'session.revoked': 'Сетевая авторизация отозвана',
    'student.access_changed': 'Доступ ученика изменён',
    'student.access_revoked': 'Индивидуальное правило ученика снято',
    'device.override_changed': 'Исключение устройства сохранено',
    'device.override_revoked': 'Исключение устройства удалено',
    'exam.restriction_set': 'Учебный режим включён из GeekExam',
    'exam.restriction_released': 'Ограничение GeekExam снято',
}


def number(args, name, default, maximum):
    value = args.get(name, str(default))
    if not value.isascii() or not value.isdecimal() or len(value) > 7 or not 1 <= int(value) <= maximum:
        raise ApiError('invalid_pagination')
    return int(value)


def audit_page(room_id, args):
    page, size = number(args, 'page', 1, 1000000), number(args, 'page_size', 20, 100)
    group = args.get('group', 'all')
    if group not in {'all', 'actions', 'reports'}:
        raise ApiError('invalid_audit_group')
    until = args.get('until') or now().isoformat(timespec='microseconds')+'Z'
    try:
        if len(until) > 40 or datetime.fromisoformat(until.replace('Z', '+00:00')).tzinfo is None:
            raise ValueError()
        cutoff = parse_time(until)
    except (ValueError, TypeError, OverflowError):
        raise ApiError('invalid_audit_boundary') from None
    query = db.select(AuditEvent).where(AuditEvent.room_id == room_id, AuditEvent.created_at <= cutoff)
    if group == 'actions':
        query = query.where(AuditEvent.event != 'policy.reported')
    elif group == 'reports':
        query = query.where(AuditEvent.event == 'policy.reported')
    total = db.session.scalar(db.select(db.func.count()).select_from(query.subquery()))
    pages = max(1, ceil(total/size))
    page = min(page, pages)
    items = db.session.execute(query.order_by(AuditEvent.created_at.desc(), AuditEvent.id.desc())
                               .offset((page-1)*size).limit(size)).scalars().all()
    return {'items': describe(items), 'total': total, 'page': page, 'page_size': size,
            'pages': pages, 'until': until}


def describe(items):
    targets = {item.target_id for item in items}
    bindings = {row.id: row for row in db.session.execute(
        db.select(NetworkSession).where(NetworkSession.id.in_(targets))).scalars()}
    device_ids = {row.device_id for row in bindings.values()} | targets
    user_ids = {item.actor_id for item in items if item.actor_id} | {row.user_id for row in bindings.values()}
    for item in items:
        details = item.details or {}
        if details.get('device_id'): device_ids.add(details['device_id'])
        if details.get('user_id'): user_ids.add(details['user_id'])
        user_ids.update(details.get('teacher_ids', []))
    devices = {row.id: row for row in db.session.execute(db.select(Device).where(Device.id.in_(device_ids))).scalars()}
    users = {row.id: row.name for row in db.session.execute(db.select(User).where(User.id.in_(user_ids))).scalars()}
    routers = {row.id: row.name for row in db.session.execute(db.select(Router).where(Router.id.in_(targets))).scalars()}
    result = []
    for item in items:
        details = item.details or {}
        binding = bindings.get(item.target_id)
        device = devices.get(details.get('device_id') or (binding.device_id if binding else item.target_id))
        subject = users.get(details.get('user_id') or (binding.user_id if binding else None))
        saved = details.get('context', {})
        # Old entries have no IP snapshot; do not present today's DHCP address as historical evidence.
        context = [saved.get('user', subject), saved.get('device', device.name if device else None),
                   saved.get('ip'), saved.get('router', routers.get(item.target_id))]
        title, tone = TITLES.get(item.event, 'Событие Guard'), 'neutral'
        if item.event == 'room.policy_changed':
            mode = 'Учебный режим включён' if details.get('manual_restriction') else 'Учебный режим выключен'
            if details.get('changes') == ['manual_restriction']:
                title = mode
            else:
                context.append(mode)
        elif item.event == 'room.teachers_changed':
            context.append(', '.join(users.get(key, 'Удалённый пользователь') for key in details.get('teacher_ids', []))
                           or 'Управление доступно только администраторам')
        elif item.event == 'student.access_changed':
            context.append({'full': 'Полный интернет', 'platform_only': 'Только учебные сервисы'}.get(details.get('profile')))
        elif item.event == 'student.access_revoked':
            context.append('Доступ снова определяется режимом кабинета')
        elif item.event == 'device.override_changed':
            context.append(details.get('reason'))
        elif item.event == 'policy.reported':
            title, tone = ('Правила применены', 'success') if details.get('verified') else ('Применение правил не подтверждено', 'warning')
            if details.get('error'):
                title, tone = 'Ошибка применения правил', 'danger'
            if details.get('revision') is not None:
                context.append('Версия '+str(details['revision']))
        result.append({'id': item.id, 'event': item.event, 'target_id': item.target_id, 'details': details,
                       'title': title, 'description': ' · '.join(dict.fromkeys(str(x) for x in context if x)),
                       'tone': tone, 'actor': users.get(item.actor_id, 'Удалённый пользователь') if item.actor_id else 'Агент роутера',
                       'created_at': stamp(item.created_at)})
    return result
