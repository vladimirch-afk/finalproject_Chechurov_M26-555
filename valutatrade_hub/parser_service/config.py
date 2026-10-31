"""Настройки источников; ключи считываются при создании конфигурации."""

import os
from dataclasses import dataclass, field
from pathlib import Path

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.utils import number
from valutatrade_hub.infra.settings import SettingsLoader


@dataclass
class ParserConfig:
    """Все URL, валюты, таймауты и пути Parser Service в одном месте."""

    EXCHANGERATE_API_KEY: str = field(
        default_factory=lambda: os.getenv("EXCHANGERATE_API_KEY", ""), repr=False
    )
    COINGECKO_API_KEY: str = field(
        default_factory=lambda: os.getenv("COINGECKO_API_KEY", ""), repr=False
    )
    COINGECKO_URL: str = "https://api.coingecko.com/api/v3/simple/price"
    EXCHANGERATE_API_URL: str = "https://v6.exchangerate-api.com/v6"
    BASE_CURRENCY: str = "USD"
    FIAT_CURRENCIES: tuple[str, ...] = ("EUR", "GBP", "RUB")
    CRYPTO_CURRENCIES: tuple[str, ...] = ("BTC", "ETH", "SOL")
    CRYPTO_ID_MAP: dict[str, str] = field(
        default_factory=lambda: {
            "BTC": "bitcoin",
            "ETH": "ethereum",
            "SOL": "solana",
        }
    )
    REQUEST_TIMEOUT: float = 10
    RATES_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("RATES_FILE_PATH")
    )
    HISTORY_FILE_PATH: Path = field(
        default_factory=lambda: SettingsLoader().get("EXCHANGE_RATES_FILE_PATH")
    )

    def __post_init__(self):
        self.BASE_CURRENCY = get_currency(self.BASE_CURRENCY).code
        number(self.REQUEST_TIMEOUT, label="REQUEST_TIMEOUT")
