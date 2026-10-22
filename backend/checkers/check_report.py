def test_report(data, config):
    """Summarize runner details without disclosing private inputs or expected outputs."""
    comment = data.get('comment') or ''
    details = data.get('details')
    compilation_errors = [str(item['error']) for item in details or []
                          if isinstance(item, dict) and item.get('error')
                          and item.get('error_type') == 'compilation_error'] if isinstance(details, list) else []
    if compilation_errors or data.get('error_type') == 'compilation_error' or data.get('verdict') == 'compilation_error':
        diagnostics = '\n'.join(compilation_errors) or comment or data.get('stderr') or ''
        return 'Ошибка компиляции\n' + str(diagnostics)[:8000]
    if not isinstance(details, list):
        return comment
    tests = config.get('tests', [])
    lines = [comment] if comment else []
    for i, result in enumerate(details):
        if not isinstance(result, dict):
            continue
        name = tests[i].get('name', f'Тест {i + 1}') if i < len(tests) else f'Тест {i + 1}'
        if result.get('ok'):
            status = 'пройден'
        elif result.get('error'):
            error = str(result['error'])
            lowered = error.lower()
            if 'unusable' in lowered or 'stopped' in lowered or 'остановлен' in lowered:
                status = 'не выполнен: контейнер остановлен после предыдущей ошибки'
            elif 'timeout' in lowered or 'timed out' in lowered or 'времен' in lowered:
                status = 'превышен лимит времени'
            elif 'output' in lowered and ('limit' in lowered or 'large' in lowered) or 'вывод' in lowered:
                status = 'превышен лимит вывода'
            else:
                status = 'ошибка выполнения: ' + error[-700:]
        else:
            status = 'неверный ответ'
        lines.append(f'{i + 1}. {name}: {status}')
    return '\n'.join(lines)
