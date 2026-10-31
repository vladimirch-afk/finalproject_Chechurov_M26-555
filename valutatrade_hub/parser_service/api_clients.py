"""Унифицированные HTTP-клиенты с безопасной обработкой ошибок API."""

import time
from abc import ABC, abstractmethod

import requests

from valutatrade_hub.core.exceptions import ApiRequestError, ValidationError
from valutatrade_hub.core.utils import iso_utc, number
from valutatrade_hub.parser_service.config import ParserConfig


class BaseApiClient(ABC):
    """Источник курсов в формате {FROM_TO: положительное число}."""

    source = "unknown"

    def __init__(self, config=None, session=None):
        self.config = config or ParserConfig()
        self.session = session or requests.Session()
        self.metadata = {}
        self.observed_at = None

    @abstractmethod
    def fetch_rates(self) -> dict[str, float]:
        """Получить и проверить курсы, выбрасывая ApiRequestError при сбое."""

    def _request(self, url, *, params=None, headers=None):
        started = time.perf_counter()
        try:
            response = self.session.get(
                url, params=params, headers=headers, timeout=self.config.REQUEST_TIMEOUT
            )
            if response.status_code != 200:
                descriptions = {
                    401: "неверный API-ключ",
                    403: "доступ запрещён",
                    429: "превышен лимит запросов; повторите позже",
                }
                reason = descriptions.get(response.status_code, "источник недоступен")
                raise ApiRequestError(
                    f"{self.source}: HTTP {response.status_code}, {reason}"
                )
            data = response.json()
            if not isinstance(data, dict):
                raise ValueError("ожидался JSON-объект")
        except requests.exceptions.Timeout as error:
            raise ApiRequestError(f"{self.source}: превышен таймаут") from error
        except requests.exceptions.RequestException as error:
            raise ApiRequestError(f"{self.source}: сетевая ошибка") from error
        except ValueError as error:
            raise ApiRequestError(f"{self.source}: некорректный JSON") from error
        self.observed_at = iso_utc()
        self.metadata = {}
        meta = {
            "request_ms": round((time.perf_counter() - started) * 1000, 3),
            "status_code": response.status_code,
            "etag": response.headers.get("ETag"),
        }
        return data, meta


class CoinGeckoClient(BaseApiClient):
    """Получение цен криптовалют по их CoinGecko ID."""

    source = "CoinGecko"

    def fetch_rates(self) -> dict[str, float]:
        """Запросить все настроенные криптовалюты одним HTTP-запросом."""
        config = self.config
        try:
            mapping = {
                code: config.CRYPTO_ID_MAP[code] for code in config.CRYPTO_CURRENCIES
            }
        except KeyError as error:
            raise ApiRequestError(
                "CoinGecko: отсутствует соответствие CRYPTO_ID_MAP"
            ) from error
        headers = (
            {"x-cg-demo-api-key": config.COINGECKO_API_KEY}
            if config.COINGECKO_API_KEY
            else {}
        )
        data, meta = self._request(
            config.COINGECKO_URL,
            params={
                "ids": ",".join(mapping.values()),
                "vs_currencies": config.BASE_CURRENCY.lower(),
                "include_last_updated_at": "true",
            },
            headers=headers,
        )
        rates = {}
        try:
            for code, raw_id in mapping.items():
                entry = data[raw_id]
                pair = f"{code}_{config.BASE_CURRENCY}"
                rates[pair] = float(
                    number(entry[config.BASE_CURRENCY.lower()], label="rate")
                )
                self.metadata[pair] = {
                    **meta,
                    "raw_id": raw_id,
                    "provider_updated_at": entry.get("last_updated_at"),
                }
        except (KeyError, TypeError, ValidationError, AttributeError) as error:
            raise ApiRequestError(
                "CoinGecko: неполные или некорректные цены"
            ) from error
        return rates


class ExchangeRateApiClient(BaseApiClient):
    """Получение фиатных курсов и перевод к направлению валюта→база."""

    source = "ExchangeRate-API"

    def fetch_rates(self) -> dict[str, float]:
        """Инвертировать USD→EUR из API в EUR→USD для локального кэша."""
        config = self.config
        if not config.EXCHANGERATE_API_KEY:
            raise ApiRequestError("ExchangeRate-API: задайте EXCHANGERATE_API_KEY")
        url = (
            f"{config.EXCHANGERATE_API_URL}/{config.EXCHANGERATE_API_KEY}"
            f"/latest/{config.BASE_CURRENCY}"
        )
        data, meta = self._request(url)
        if data.get("result") != "success":
            messages = {
                "invalid-key": "неверный ключ",
                "inactive-account": "аккаунт не активирован",
                "quota-reached": "исчерпана квота",
                "unsupported-code": "неподдерживаемая база",
            }
            reason = messages.get(data.get("error-type"), "ошибка ответа API")
            raise ApiRequestError(f"ExchangeRate-API: {reason}")
        if data.get("base_code") != config.BASE_CURRENCY:
            raise ApiRequestError(
                "ExchangeRate-API: ответ содержит другую базовую валюту"
            )
        rates = {}
        try:
            values = data.get("conversion_rates", data.get("rates"))
            for code in config.FIAT_CURRENCIES:
                if code == config.BASE_CURRENCY:
                    continue
                pair = f"{code}_{config.BASE_CURRENCY}"
                rates[pair] = float(number(1 / number(values[code], label="rate")))
                self.metadata[pair] = {
                    **meta,
                    "provider_updated_at": data.get("time_last_update_utc"),
                }
        except (KeyError, TypeError, ValidationError) as error:
            raise ApiRequestError(
                "ExchangeRate-API: неполные или некорректные курсы"
            ) from error
        return rates
