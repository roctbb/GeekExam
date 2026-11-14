"""Admission rules shared by teacher configuration and execution snapshots."""
import math
import re

MODES = {'text', 'code', 'files', 'project', 'repository'}

def default_language(check_type, cfg, ui=None):
    return cfg.get('lang', (ui or {}).get('lang', 'python' if check_type == 'docker' else 'text'))


def validate_executor_config(question):
    if question['check_type'] not in ('docker', 'ai'): return
    cfg = question.get('check_config') or {}
    for key, minimum, maximum in (('max_files', 1, 100), ('max_file_bytes', 1, 52428800), ('max_total_bytes', 1, 52428800)):
        if key in cfg and (type(cfg[key]) is not int or not minimum <= cfg[key] <= maximum):
            raise ValueError(f'{key}: недопустимое ограничение')
    if 'submission_modes' in cfg and (not isinstance(cfg['submission_modes'], list) or not cfg['submission_modes']
        or any(not isinstance(mode, str) or mode not in MODES for mode in cfg['submission_modes'])):
        raise ValueError('Недопустимые способы сдачи')
    if 'allowed_extensions' in cfg and (not isinstance(cfg['allowed_extensions'], list) or len(cfg['allowed_extensions']) > 50
        or any(not isinstance(ext, str) or not re.fullmatch('[a-z0-9]{1,12}', ext) for ext in cfg['allowed_extensions'])):
        raise ValueError('Недопустимые расширения файлов')
    language = default_language(question['check_type'], cfg, question.get('ui_config'))
    if not isinstance(language, str) or not 1 <= len(language) <= 20: raise ValueError('Недопустимый язык')
    languages = cfg.get('allowed_languages', [language])
    if not isinstance(languages, list) or not languages or len(languages) > 20 or language not in languages:
        raise ValueError('Недопустимый список языков')
    if any(not isinstance(lang, str) or not 1 <= len(lang) <= 20 for lang in languages): raise ValueError('Недопустимый язык')
    if question['check_type'] == 'docker' and any(lang not in ('python', 'cpp', 'brainfuck') for lang in languages):
        raise ValueError('Тесты поддерживают Python, C++ и Brainfuck')
    if cfg.get('entrypoint'):
        from executor_service import safe_path
        safe_path(cfg['entrypoint'])
    for key in ('prompt', 'private_instructions', 'reference_answer'):
        if key in cfg and (not isinstance(cfg[key], str) or len(cfg[key]) > 200000): raise ValueError('Слишком большой текст проверки')
    if question['check_type'] != 'docker': return
    tests = cfg.get('tests')
    if not isinstance(tests, list) or not 1 <= len(tests) <= 200: raise ValueError('Требуется от 1 до 200 тестов')
    total = 0
    for test in tests:
        if not isinstance(test, dict): raise ValueError('Неверный тест')
        if 'hidden' in test and type(test['hidden']) is not bool: raise ValueError('hidden должен быть логическим значением')
        for key in ('input', 'expected'):
            value = test.get(key, '')
            if not isinstance(value, (str, int, float)) or isinstance(value, bool): raise ValueError('Недопустимое содержимое теста')
            size = len(str(value).encode())
            if size > 33554432: raise ValueError('Поле теста превышает 32 МиБ')
            total += size
        for settings in (cfg, test):
            for key, factor in (('time_limit', 1), ('time_limit_ms', .001)):
                if key in settings and (type(settings[key]) not in (int, float) or not math.isfinite(settings[key])
                        or not 0 < settings[key] * factor <= 30): raise ValueError('Лимит времени должен быть от 0 до 30 секунд')
    if total > 268435456: raise ValueError('Тесты превышают 256 МиБ')
