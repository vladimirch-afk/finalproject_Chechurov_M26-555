"""Оркестрация независимых источников и сохранение измерений."""

import logging

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    ValidationError,
    ValutaTradeError,
)
from valutatrade_hub.core.utils import iso_utc, number, parse_time
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.storage import RatesStorage


class RatesUpdater:
    """Последовательно опрашивать источники, сохраняя успехи при частичном сбое."""

    def __init__(self, clients, storage=None):
        self.clients = list(clients)
        self.storage = storage or RatesStorage()
        self.logger = logging.getLogger("valutatrade.parser")

    def run_update(self) -> dict:
        """Вернуть updated/errors/last_refresh; все источники упали → исключение."""
        self.logger.info("Starting rates update")
        records, errors = [], []
        for client in self.clients:
            try:
                rates = client.fetch_rates()
                if not isinstance(rates, dict) or not rates:
                    raise ApiRequestError(f"{client.source}: пустой ответ")
                batch = []
                for pair, value in rates.items():
                    left, right = pair.split("_")
                    left, right = get_currency(left).code, get_currency(right).code
                    if left == right:
                        raise ApiRequestError(
                            f"{client.source}: одинаковые валюты пары"
                        )
                    timestamp = iso_utc(
                        parse_time(getattr(client, "observed_at", None) or iso_utc())
                    )
                    batch.append(
                        {
                            "from_currency": left,
                            "to_currency": right,
                            "rate": float(number(value)),
                            "timestamp": timestamp,
                            "source": client.source,
                            "meta": getattr(client, "metadata", {}).get(pair, {}),
                        }
                    )
                records.extend(batch)
                self.logger.info(
                    "Source updated",
                    extra={"event": {"source": client.source, "count": len(batch)}},
                )
            except (ValutaTradeError, ValueError, TypeError, AttributeError) as error:
                message = str(error)
                errors.append(message)
                self.logger.error(
                    "Source failed",
                    extra={"event": {"source": client.source, "error": message}},
                )
        if not records:
            raise ApiRequestError("; ".join(errors) or "нет источников")
        result = self.storage.save(records)
        self.logger.info(
            "Update finished", extra={"event": {**result, "errors": errors}}
        )
        return {**result, "errors": errors}


def build_updater(source: str | None = None) -> RatesUpdater:
    """Собрать Parser Service, выбрав все источники или один по имени."""
    config = ParserConfig()
    factories = {"coingecko": CoinGeckoClient, "exchangerate": ExchangeRateApiClient}
    if source is not None and source not in factories:
        raise ValidationError("Источник: coingecko или exchangerate")
    selected = [source] if source else factories
    return RatesUpdater([factories[name](config) for name in selected])
