"""Валидация, UTC-время и кэширование через замыкание."""

import math
import re
import time
from copy import deepcopy
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from valutatrade_hub.core.exceptions import ValidationError


def normalize_code(code: str) -> str:
    """Нормализовать код валюты; принимать только 2–5 латинских букв."""
    if not isinstance(code, str) or not re.fullmatch(r"[A-Za-z]{2,5}", code):
        raise ValidationError("Код валюты: 2–5 латинских букв без пробелов")
    return code.upper()


def number(value, *, positive: bool = True, label: str = "amount") -> Decimal:
    """Проверить конечное число; исключить bool, строки, NaN и infinity."""
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValidationError(f"'{label}' должен быть числом")
    try:
        result = Decimal(str(value))
        valid = result.is_finite() and math.isfinite(float(result))
        valid = valid and (result == 0 or float(result) != 0)
        valid = valid and (result > 0 if positive else result >= 0)
    except (InvalidOperation, OverflowError, ValueError):
        valid = False
    if not valid:
        condition = "положительным" if positive else "неотрицательным"
        raise ValidationError(f"'{label}' должен быть {condition} конечным числом")
    return result


def utc_now() -> datetime:
    """Вернуть текущее время с UTC timezone."""
    return datetime.now(UTC)


def iso_utc(value: datetime | None = None) -> str:
    """Сериализовать момент времени в ISO 8601 UTC."""
    return (value or utc_now()).astimezone(UTC).isoformat().replace("+00:00", "Z")


def parse_time(value: str) -> datetime:
    """Прочитать ISO-дату; старые даты без timezone считать UTC."""
    if not isinstance(value, str):
        raise ValidationError("Некорректная метка времени")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return parsed.replace(tzinfo=parsed.tzinfo or UTC).astimezone(UTC)
    except ValueError as error:
        raise ValidationError("Некорректная метка времени") from error


def create_ttl_cache(ttl_seconds: float, clock=time.monotonic):
    """Вернуть пару замыканий: чтение кэша с loader и очистку кэша."""
    entries = {}

    def cached(key, loader):
        now = clock()
        for expired in list(entries):
            if now - entries[expired][0] >= ttl_seconds:
                del entries[expired]
        if key not in entries or now - entries[key][0] >= ttl_seconds:
            entries[key] = (now, deepcopy(loader()))
        return deepcopy(entries[key][1])

    def clear():
        entries.clear()

    return cached, clear
