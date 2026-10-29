"""JSON Lines журналы действий и парсера с ротацией."""

import json
import logging
from logging.handlers import RotatingFileHandler

from valutatrade_hub.core.exceptions import StorageError
from valutatrade_hub.core.utils import iso_utc
from valutatrade_hub.infra.settings import SettingsLoader


class JsonFormatter(logging.Formatter):
    """Форматировать событие в одну JSON-строку без аргументов вызова."""

    def format(self, record):
        """Добавить UTC timestamp и только явно переданный контекст."""
        payload = {
            "timestamp": iso_utc(),
            "level": record.levelname,
            "message": record.getMessage(),
            **getattr(record, "event", {}),
        }
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings=None) -> None:
    """Подключить отдельные ротируемые файлы без дублирования обработчиков."""
    settings = settings or SettingsLoader()
    try:
        directory = settings.get("LOG_DIR")
        directory.mkdir(parents=True, exist_ok=True)
        for name, filename in [("actions", "actions.log"), ("parser", "parser.log")]:
            logger = logging.getLogger(f"valutatrade.{name}")
            destination = directory / filename
            logger.setLevel(settings.get("LOG_LEVEL"))
            logger.propagate = False
            if any(
                getattr(handler, "baseFilename", None) == str(destination)
                for handler in logger.handlers
            ):
                continue
            for handler in logger.handlers[:]:
                logger.removeHandler(handler)
                handler.close()
            handler = RotatingFileHandler(
                destination,
                maxBytes=settings.get("LOG_MAX_BYTES"),
                backupCount=settings.get("LOG_BACKUP_COUNT"),
                encoding="utf-8",
            )
            handler.setFormatter(JsonFormatter())
            logger.addHandler(handler)
    except OSError as error:
        raise StorageError(f"Не удалось открыть журналы: {error}") from error
