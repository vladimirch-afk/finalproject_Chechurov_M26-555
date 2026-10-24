"""Иерархия и единый реестр поддерживаемых валют."""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from valutatrade_hub.core.exceptions import CurrencyNotFoundError, ValidationError
from valutatrade_hub.core.utils import normalize_code, number


@dataclass(frozen=True)
class Currency(ABC):
    """Валюта с неизменяемыми именем и кодом."""

    name: str
    code: str

    def __post_init__(self):
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValidationError("Имя валюты не может быть пустым")
        if self.code != normalize_code(self.code):
            raise ValidationError("Код валюты должен быть в верхнем регистре")

    @abstractmethod
    def get_display_info(self) -> str:
        """Вернуть описание валюты для пользователя."""


@dataclass(frozen=True)
class FiatCurrency(Currency):
    """Фиатная валюта и её страна или зона эмиссии."""

    issuing_country: str

    def __post_init__(self):
        super().__post_init__()
        if (
            not isinstance(self.issuing_country, str)
            or not self.issuing_country.strip()
        ):
            raise ValidationError("Нужно указать страну или зону эмиссии")

    def get_display_info(self) -> str:
        """Описать фиатную валюту вместе с эмитентом."""
        return f"[FIAT] {self.code} — {self.name} (Issuing: {self.issuing_country})"


@dataclass(frozen=True)
class CryptoCurrency(Currency):
    """Криптовалюта, алгоритм и последняя известная капитализация."""

    algorithm: str
    market_cap: float = 0.0

    def __post_init__(self):
        super().__post_init__()
        if not isinstance(self.algorithm, str) or not self.algorithm.strip():
            raise ValidationError("Алгоритм не может быть пустым")
        number(self.market_cap, positive=False, label="market_cap")

    def get_display_info(self) -> str:
        """Описать алгоритм и капитализацию (0 означает отсутствие данных)."""
        return (
            f"[CRYPTO] {self.code} — {self.name} "
            f"(Algo: {self.algorithm}, MCAP: {self.market_cap:.2e})"
        )


_CURRENCIES = {
    currency.code: currency
    for currency in (
        FiatCurrency("US Dollar", "USD", "United States"),
        FiatCurrency("Euro", "EUR", "Eurozone"),
        FiatCurrency("Pound Sterling", "GBP", "United Kingdom"),
        FiatCurrency("Russian Ruble", "RUB", "Russia"),
        CryptoCurrency("Bitcoin", "BTC", "SHA-256"),
        CryptoCurrency("Ethereum", "ETH", "Proof of Stake"),
        CryptoCurrency("Solana", "SOL", "Proof of History / Proof of Stake"),
    )
}


def get_currency(code: str) -> Currency:
    """Найти валюту по коду или выбросить CurrencyNotFoundError."""
    normalized = normalize_code(code)
    if normalized not in _CURRENCIES:
        raise CurrencyNotFoundError(normalized)
    return _CURRENCIES[normalized]


def supported_currencies() -> tuple[Currency, ...]:
    """Вернуть валюты в алфавитном порядке кодов."""
    return tuple(_CURRENCIES[code] for code in sorted(_CURRENCIES))
