"""Конвертация прямых, обратных и кросс-курсов с проверкой TTL."""

from collections import deque
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    StorageError,
    ValutaTradeError,
)
from valutatrade_hub.core.utils import (
    create_ttl_cache,
    iso_utc,
    number,
    parse_time,
    utc_now,
)
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


@dataclass(frozen=True)
class RateQuote:
    """Одна единица from_currency стоит rate единиц to_currency."""

    from_currency: str
    to_currency: str
    rate: float
    updated_at: str
    source: str


def is_fresh(timestamp: str, ttl: int, now: datetime | None = None) -> bool:
    """Будущие метки и измерения старше TTL не считаются свежими."""
    age = ((now or utc_now()) - parse_time(timestamp)).total_seconds()
    return 0 <= age <= ttl


def resolve_rate(
    snapshot: dict, from_code: str, to_code: str, ttl: int | None = None
) -> RateQuote:
    """Найти кратчайший путь по курсам; TTL проверяется для каждого ребра."""
    origin, target = get_currency(from_code).code, get_currency(to_code).code
    if origin == target:
        return RateQuote(origin, target, 1.0, iso_utc(), "identity")
    graph = {}
    try:
        pairs = snapshot["pairs"]
        if not isinstance(pairs, dict):
            raise ValueError("pairs должен быть объектом")
        for pair, entry in pairs.items():
            left, right = pair.split("_")
            left, right = get_currency(left).code, get_currency(right).code
            rate = number(entry["rate"], label="rate")
            stamp = parse_time(entry["updated_at"])
            if ttl is not None and not is_fresh(entry["updated_at"], ttl):
                continue
            source = str(entry.get("source", "unknown"))
            graph.setdefault(left, []).append((right, rate, stamp, source))
            graph.setdefault(right, []).append((left, Decimal(1) / rate, stamp, source))
    except (KeyError, TypeError, ValueError, AttributeError, ValutaTradeError) as error:
        raise StorageError(f"Некорректный формат rates.json: {error}") from error
    queue = deque([(origin, Decimal(1), None, ())])
    seen = {origin}
    while queue:
        code, accumulated, oldest, sources = queue.popleft()
        for neighbor, rate, timestamp, source in graph.get(code, []):
            if neighbor in seen:
                continue
            result = accumulated * rate
            updated = min(oldest, timestamp) if oldest else timestamp
            new_sources = (*sources, source)
            if neighbor == target:
                return RateQuote(
                    origin,
                    target,
                    float(number(result)),
                    iso_utc(updated),
                    ", ".join(dict.fromkeys(new_sources)),
                )
            seen.add(neighbor)
            queue.append((neighbor, result, updated, new_sources))
    raise ApiRequestError(
        f"Курс {origin}→{target} недоступен или устарел. Выполните update-rates"
    )


class RateService:
    """Читать локальный снимок, кэшировать через замыкание и обновлять по TTL."""

    def __init__(self, db=None, refresh_callback=None):
        self.db = db or DatabaseManager()
        self.settings = SettingsLoader()
        self.refresh_callback = refresh_callback
        self._cached, self.clear_cache = create_ttl_cache(5)

    def snapshot(self) -> dict:
        """Кэшировать чтение только до изменения атомарно заменяемого файла."""
        path = self.db.path("rates")
        try:
            stat = path.stat()
            key = (str(path), stat.st_ino, stat.st_mtime_ns, stat.st_size)
        except FileNotFoundError:
            key = (str(path), None)
        except OSError as error:
            raise StorageError(f"Не удалось проверить кэш курсов: {error}") from error
        return self._cached(key, lambda: self.db.read("rates"))

    def get_rate(
        self, from_code: str, to_code: str, *, refresh: bool = True
    ) -> RateQuote:
        """Вернуть свежий курс; один раз обновить источники при промахе кэша."""
        origin, target = get_currency(from_code).code, get_currency(to_code).code
        ttl = self.settings.get("RATES_TTL_SECONDS")
        try:
            return resolve_rate(self.snapshot(), origin, target, ttl)
        except ApiRequestError:
            if not refresh:
                raise
        try:
            if self.refresh_callback is not None:
                self.refresh_callback()
            else:
                from valutatrade_hub.parser_service.updater import build_updater

                build_updater().run_update()
        except ApiRequestError:
            pass
        self.clear_cache()
        return resolve_rate(self.snapshot(), origin, target, ttl)
