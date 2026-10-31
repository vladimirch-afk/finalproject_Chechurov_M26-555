"""Периодическое обновление: python -m valutatrade_hub.parser_service.scheduler."""

import argparse
import logging
import time

from valutatrade_hub.core.exceptions import ApiRequestError, ValutaTradeError
from valutatrade_hub.core.utils import number
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.updater import build_updater


def run_scheduler(
    interval: float = 300, source=None, *, iterations=None, sleep=time.sleep
):
    """Обновлять до Ctrl+C; iterations и sleep позволяют проверять без ожидания."""
    number(interval, label="interval")
    updater = build_updater(source)
    completed = 0
    while iterations is None or completed < iterations:
        try:
            updater.run_update()
        except ApiRequestError as error:
            logging.getLogger("valutatrade.parser").error(str(error))
        completed += 1
        if iterations is None or completed < iterations:
            sleep(interval)


def main(argv=None) -> int:
    """Разобрать параметры и запустить отдельный процесс обновления."""
    parser = argparse.ArgumentParser(description="Периодическое обновление курсов")
    parser.add_argument("--interval", type=float, default=300)
    parser.add_argument("--source", choices=["coingecko", "exchangerate"])
    args = parser.parse_args(argv)
    try:
        configure_logging()
        run_scheduler(args.interval, args.source)
    except KeyboardInterrupt:
        return 0
    except ValutaTradeError as error:
        print(error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
