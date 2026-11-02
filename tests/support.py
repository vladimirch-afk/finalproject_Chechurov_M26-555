"""Изолированные временные данные для тестов без внешней сети."""

import logging
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from valutatrade_hub.core.exceptions import ApiRequestError
from valutatrade_hub.core.rates import RateService
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.core.utils import iso_utc
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.storage import RatesStorage


class IsolatedTestCase(unittest.TestCase):
    """Каждый тест получает отдельные JSON и журналы."""

    def setUp(self):
        self.directory = tempfile.TemporaryDirectory(prefix="valutatrade-test-")
        root = Path(self.directory.name)
        config = root / "pyproject.toml"
        config.write_text("[tool.valutatrade]\nrates_ttl_seconds = 300\n")
        self.environment = patch.dict(
            os.environ,
            {
                "VALUTATRADE_CONFIG": str(config),
                "VALUTATRADE_DATA_DIR": str(root / "data"),
                "VALUTATRADE_LOG_DIR": str(root / "logs"),
                "VALUTATRADE_RATES_TTL": "300",
            },
        )
        self.environment.start()
        self.settings = SettingsLoader()
        self.settings.reload()
        configure_logging()
        self.db = DatabaseManager()
        self.rates = RateService(self.db, refresh_callback=self.offline)
        self.service = TradingService(self.db, self.rates)

    def tearDown(self):
        for name in ["actions", "parser"]:
            logger = logging.getLogger(f"valutatrade.{name}")
            for handler in logger.handlers[:]:
                handler.close()
                logger.removeHandler(handler)
        self.environment.stop()
        self.settings.reload()
        self.directory.cleanup()

    @staticmethod
    def offline():
        """В тестах недоступные котировки не вызывают настоящую сеть."""
        raise ApiRequestError("источник отключён тестом")

    def seed(self, rates=None, timestamp=None):
        """Записать известные котировки как измерения источника Fixture."""
        values = rates or {
            "BTC": 60000,
            "ETH": 3000,
            "SOL": 150,
            "EUR": 1.1,
            "GBP": 1.25,
            "RUB": 0.01,
        }
        records = [
            {
                "from_currency": code,
                "to_currency": "USD",
                "rate": value,
                "timestamp": timestamp or iso_utc(),
                "source": "Fixture",
            }
            for code, value in values.items()
        ]
        return RatesStorage(self.db).save(records)

    def login(self, username="alice"):
        """Зарегистрировать пользователя и открыть сессию."""
        self.service.register(username, "secret-pass")
        self.service.login(username, "secret-pass")
