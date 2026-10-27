"""JSON-хранилище: блокировка, атомарная запись и восстановление транзакций."""

import fcntl
import json
import os
import tempfile
import threading
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.infra.settings import SettingsLoader

DEFAULTS = {
    "users": [],
    "portfolios": [],
    "rates": {"pairs": {}, "last_refresh": None},
    "exchange_rates": [],
    "transactions": [],
}


def read_json(path: Path):
    """Прочитать JSON; повреждённые файлы не подменяются пустыми данными."""
    try:
        with path.open(encoding="utf-8") as stream:
            return json.load(stream)
    except (OSError, ValueError) as error:
        raise StorageError(f"Не удалось прочитать {path.name}: {error}") from error


def atomic_write(path: Path, payload) -> None:
    """Записать UTF-8 JSON через временный файл, fsync и os.replace."""
    temporary = None
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        content = json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False)
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", dir=path.parent, suffix=".tmp", delete=False
        ) as stream:
            temporary = Path(stream.name)
            stream.write(content + "\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError) as error:
        raise StorageError(f"Не удалось сохранить {path.name}: {error}") from error
    finally:
        if temporary is not None:
            temporary.unlink(missing_ok=True)


class DatabaseManager:
    """Singleton через __new__; одна точка доступа к JSON в процессе."""

    _instance = None
    _instance_lock = threading.RLock()

    def __new__(cls):
        with cls._instance_lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.settings = SettingsLoader()
                instance._mutex = threading.RLock()
                instance._local = threading.local()
                cls._instance = instance
            return cls._instance

    def path(self, name: str) -> Path:
        """Получить путь только к известному хранилищу."""
        if name not in DEFAULTS:
            raise StorageError(f"Неизвестное хранилище: {name}")
        return self.settings.get(f"{name}_file_path")

    @contextmanager
    def transaction(self):
        """Защитить чтение–изменение–запись от потоков и других процессов Unix."""
        with self._mutex:
            if getattr(self._local, "active", False):
                yield self
                return
            directory = self.settings.get("DATA_DIR")
            try:
                directory.mkdir(parents=True, exist_ok=True)
                with (directory / ".database.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX)
                    self._local.active = True
                    try:
                        self._recover()
                        for name, default in DEFAULTS.items():
                            if not self.path(name).exists():
                                atomic_write(self.path(name), default)
                        yield self
                    finally:
                        self._local.active = False
                        fcntl.flock(lock, fcntl.LOCK_UN)
            except OSError as error:
                raise StorageError(f"Ошибка доступа к данным: {error}") from error

    def _recover(self):
        journal = self.settings.get("DATA_DIR") / ".transaction.json"
        if journal.exists():
            updates = read_json(journal)
            if not isinstance(updates, dict) or not updates:
                raise StorageError("Повреждён журнал транзакций")
            for name, payload in updates.items():
                self._validate(name, payload)
            for name, payload in updates.items():
                atomic_write(self.path(name), payload)
            journal.unlink()

    def _validate(self, name, payload):
        self.path(name)
        if not isinstance(payload, type(DEFAULTS[name])):
            raise StorageError(f"Некорректный формат {name}.json")

    def read(self, name: str):
        """Прочитать независимый снимок данных под общей блокировкой."""
        with self.transaction():
            payload = read_json(self.path(name))
            self._validate(name, payload)
            return payload

    def write_many(self, updates: dict) -> None:
        """Сохранить несколько файлов с журналом для восстановления после сбоя."""
        if not updates:
            return
        with self.transaction():
            for name, payload in updates.items():
                self._validate(name, payload)
            journal = self.settings.get("DATA_DIR") / ".transaction.json"
            atomic_write(journal, deepcopy(updates))
            self._recover()
