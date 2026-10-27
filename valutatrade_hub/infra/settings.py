"""Единая конфигурация из pyproject.toml и переменных окружения."""

import os
import threading
import tomllib
from pathlib import Path
from typing import Any

from valutatrade_hub.core.exceptions import StorageError


class SettingsLoader:
    """Singleton: __new__ выбран ради простоты и явного контроля экземпляра."""

    _instance = None
    _lock = threading.RLock()

    def __new__(cls):
        with cls._lock:
            if cls._instance is None:
                instance = super().__new__(cls)
                instance.reload()
                cls._instance = instance
            return cls._instance

    def reload(self) -> None:
        """Перечитать настройки, в том числе изменения окружения."""
        config_path = Path(os.getenv("VALUTATRADE_CONFIG", "pyproject.toml")).resolve()
        config = {}
        try:
            if config_path.exists():
                with config_path.open("rb") as stream:
                    config = tomllib.load(stream).get("tool", {}).get("valutatrade", {})
            elif "VALUTATRADE_CONFIG" in os.environ:
                raise StorageError(f"Файл конфигурации не найден: {config_path}")
            root = config_path.parent
            data = Path(
                os.getenv("VALUTATRADE_DATA_DIR", config.get("data_dir", "data"))
            )
            data = (
                data.resolve() if "VALUTATRADE_DATA_DIR" in os.environ else root / data
            )
            logs = Path(
                os.getenv(
                    "VALUTATRADE_LOG_DIR", config.get("log_dir", data.parent / "logs")
                )
            )
            raw_ttl = os.getenv(
                "VALUTATRADE_RATES_TTL", config.get("rates_ttl_seconds", 300)
            )
            if isinstance(raw_ttl, bool) or not isinstance(raw_ttl, (str, int)):
                raise ValueError("TTL должен быть целым числом")
            ttl = int(raw_ttl)
            if ttl < 0:
                raise ValueError("TTL не может быть отрицательным")
            level = str(config.get("log_level", "INFO")).upper()
            if level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
                raise ValueError("Некорректный уровень логирования")
            self._values = {
                "DATA_DIR": data.resolve(),
                "LOG_DIR": (root / logs).resolve(),
                "RATES_TTL_SECONDS": ttl,
                "DEFAULT_BASE_CURRENCY": config.get("default_base_currency", "USD"),
                "LOG_LEVEL": level,
                "LOG_FORMAT": "json",
                "LOG_MAX_BYTES": 1_048_576,
                "LOG_BACKUP_COUNT": 3,
            }
            for filename in (
                "users",
                "portfolios",
                "rates",
                "exchange_rates",
                "transactions",
            ):
                self._values[f"{filename.upper()}_FILE_PATH"] = (
                    data.resolve() / f"{filename}.json"
                )
        except (OSError, ValueError, TypeError, AttributeError) as error:
            raise StorageError(f"Не удалось загрузить конфигурацию: {error}") from error

    def get(self, key: str, default: Any = None) -> Any:
        """Вернуть значение параметра; имена параметров нечувствительны к регистру."""
        return self._values.get(key.upper(), default)
