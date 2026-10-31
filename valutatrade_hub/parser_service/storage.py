"""Последние курсы и история измерений с дедупликацией."""

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    StorageError,
    ValidationError,
    ValutaTradeError,
)
from valutatrade_hub.core.utils import iso_utc, number, parse_time
from valutatrade_hub.infra.database import DatabaseManager


class RatesStorage:
    """Обновлять снимок только более свежими измерениями."""

    def __init__(self, db=None):
        self.db = db or DatabaseManager()

    def save(self, records: list[dict]) -> dict:
        """Сохранить проверенные измерения и вернуть число обновлённых пар."""
        normalized = []
        try:
            for record in records:
                left = get_currency(record["from_currency"]).code
                right = get_currency(record["to_currency"]).code
                if left == right:
                    raise ValueError("Измерение должно связывать разные валюты")
                stamp = iso_utc(parse_time(record["timestamp"]))
                source = record["source"]
                if not isinstance(source, str) or not source:
                    raise ValueError("Не задан источник измерения")
                normalized.append(
                    {
                        **record,
                        "id": f"{left}_{right}_{stamp}",
                        "from_currency": left,
                        "to_currency": right,
                        "timestamp": stamp,
                        "rate": float(number(record["rate"])),
                    }
                )
        except (KeyError, TypeError, ValueError, ValutaTradeError) as error:
            raise StorageError(f"Некорректное измерение курса: {error}") from error
        with self.db.transaction():
            snapshot, history = self.db.read("rates"), self.db.read("exchange_rates")
            try:
                pairs = snapshot["pairs"]
                if not isinstance(pairs, dict):
                    raise TypeError("pairs должен быть объектом")
                ids = {row["id"] for row in history}
                changed = set()
                for record in normalized:
                    pair = f"{record['from_currency']}_{record['to_currency']}"
                    previous = pairs.get(pair)
                    if previous is None or parse_time(record["timestamp"]) > parse_time(
                        previous["updated_at"]
                    ):
                        pairs[pair] = {
                            "rate": record["rate"],
                            "updated_at": record["timestamp"],
                            "source": record["source"],
                        }
                        changed.add(pair)
                    if record["id"] not in ids:
                        history.append(record)
                        ids.add(record["id"])
                if changed:
                    snapshot["last_refresh"] = iso_utc()
                if normalized:
                    self.db.write_many({"rates": snapshot, "exchange_rates": history})
                return {
                    "updated": len(changed),
                    "last_refresh": snapshot.get("last_refresh"),
                }
            except (KeyError, TypeError, ValueError, ValidationError) as error:
                raise StorageError(f"Некорректное хранилище курсов: {error}") from error
