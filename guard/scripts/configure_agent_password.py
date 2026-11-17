#!/usr/bin/env python3
"""Verify the LAN login, then save it only on this agent host, with mode 0600."""
import argparse
import getpass
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from guard_agent.rci import RciClient, RouterError
from guard_agent.transport import private_read, private_write


def main():
    parser = argparse.ArgumentParser(description="Настройка локального пароля LAN-агента Guard")
    parser.add_argument("--config", type=Path, required=True)
    args = parser.parse_args()
    try:
        config = private_read(args.config)
        password = getpass.getpass("Пароль роутера (ввод скрыт; на сервер не передаётся): ")
        client = RciClient(config["router_url"], config.get("username", "admin"), lambda: password)
        client.read("version")
        filename = args.config.resolve().with_suffix(".router-password")
        descriptor, temporary = tempfile.mkstemp(dir=filename.parent, prefix=".router-password-")
        try:
            with os.fdopen(descriptor, "w") as stream:
                stream.write(password + "\n")
            os.replace(temporary, filename)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        config["password_file"] = str(filename)
        private_write(args.config, config)
        print("Вход на роутер проверен. Пароль сохранён локально с правами 0600. Агент готов к запуску.")
        return 0
    except (RouterError, OSError, ValueError, KeyError) as exc:
        print("Ошибка: "+(str(exc) if isinstance(exc, RouterError) else type(exc).__name__), file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
