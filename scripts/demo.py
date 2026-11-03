"""Воспроизводимое демо: реальный CLI и локальные HTTP-ответы двух API."""

import argparse
import io
import json
import os
import shlex
import threading
import time
from contextlib import redirect_stdout
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from tempfile import TemporaryDirectory

from valutatrade_hub.cli.interface import ConsoleApp
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.infra.settings import SettingsLoader
from valutatrade_hub.logging_config import configure_logging
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.updater import RatesUpdater


class DemoApiHandler(BaseHTTPRequestHandler):
    """Контролируемые API-ответы; данные намеренно учебные, не рыночные."""

    crypto_failure = False

    def do_GET(self):
        """Вернуть JSON в реальном формате поставщика или HTTP 429."""
        if self.path.startswith("/crypto"):
            if self.crypto_failure:
                self.send_response(429)
                self.end_headers()
                return
            payload = {
                coin: {"usd": value, "last_updated_at": int(time.time())}
                for coin, value in [
                    ("bitcoin", 60000),
                    ("ethereum", 3000),
                    ("solana", 150),
                ]
            }
        else:
            payload = {
                "result": "success",
                "base_code": "USD",
                "conversion_rates": {"EUR": 0.8, "GBP": 0.75, "RUB": 100},
            }
        raw = json.dumps(payload).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)

    def log_message(self, *_args):
        """Не смешивать HTTP-диагностику с записью терминала."""


class Recorder:
    """Записать вывод выполненных команд в asciinema v2 и обычный текст."""

    def __init__(self, app):
        self.app, self.events, self.text, self.position = app, [], [], 0.0

    def run(self, command, expected=0):
        """Исполнить команду и проверить её код результата перед записью."""
        stream = io.StringIO()
        with redirect_stdout(stream):
            code = self.app.execute(shlex.split(command))
        if code != expected:
            raise RuntimeError(
                f"Демо-команда завершилась неожиданно: {command}\n{stream.getvalue()}"
            )
        self.text.append(f"valutatrade> {command}\n{stream.getvalue()}")
        self.events.append(
            [self.position, "o", f"\x1b[1;36mvalutatrade> {command}\x1b[0m\r\n"]
        )
        self.position += 0.8
        for line in stream.getvalue().splitlines():
            self.events.append([round(self.position, 3), "o", line + "\r\n"])
            self.position += 0.08
        self.position += 0.6

    def save(self, directory):
        """Сохранить воспроизводимую терминальную запись и расшифровку."""
        directory.mkdir(parents=True, exist_ok=True)
        header = {
            "version": 2,
            "width": 132,
            "height": 32,
            "timestamp": int(time.time()),
            "title": "ValutaTrade Hub: CLI + local API fixtures",
            "env": {"TERM": "xterm-256color"},
        }
        content = [
            json.dumps(header),
            *(json.dumps(event, ensure_ascii=False) for event in self.events),
        ]
        (directory / "session.cast").write_text(
            "\n".join(content) + "\n", encoding="utf-8"
        )
        intro = (
            "ДЕМОНСТРАЦИЯ: оба API заменены локальным HTTP-сервером.\n"
            "Все команды исполняются настоящими CLI, usecases и requests-клиентами.\n"
            "Цены фиксированные учебные; рыночные запросы не выполняются.\n\n"
        )
        (directory / "session.txt").write_text(
            intro + "\n".join(self.text), encoding="utf-8"
        )


def main(argv=None):
    """Создать демонстрацию, не изменяя пользовательские JSON и ключи."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=Path("demo"))
    args = parser.parse_args(argv)
    server = ThreadingHTTPServer(("127.0.0.1", 0), DemoApiHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    saved = {
        key: os.environ.get(key)
        for key in [
            "VALUTATRADE_DATA_DIR",
            "VALUTATRADE_LOG_DIR",
            "VALUTATRADE_CONFIG",
            "VALUTATRADE_RATES_TTL",
        ]
    }
    try:
        with TemporaryDirectory(prefix="valutatrade-demo-") as temporary:
            root = Path(temporary)
            config_file = root / "pyproject.toml"
            config_file.write_text("[tool.valutatrade]\n")
            os.environ.update(
                VALUTATRADE_DATA_DIR=str(root / "data"),
                VALUTATRADE_LOG_DIR=str(root / "logs"),
                VALUTATRADE_CONFIG=str(config_file),
                VALUTATRADE_RATES_TTL="300",
            )
            SettingsLoader().reload()
            configure_logging()
            base = f"http://127.0.0.1:{server.server_port}"
            config = ParserConfig(
                EXCHANGERATE_API_KEY="demo-key",
                COINGECKO_API_KEY="",
                COINGECKO_URL=f"{base}/crypto",
                EXCHANGERATE_API_URL=f"{base}/fiat",
            )

            def factory(source=None):
                clients = {
                    "coingecko": CoinGeckoClient(config),
                    "exchangerate": ExchangeRateApiClient(config),
                }
                return RatesUpdater([clients[source]] if source else clients.values())

            app = ConsoleApp(TradingService(updater_factory=factory))
            recorder = Recorder(app)
            for command in [
                "register --username alice --password demo-pass",
                "login --username alice --password demo-pass",
                "show-portfolio",
                "deposit --amount 10000",
                "update-rates",
                "show-rates --top 2",
                "show-rates --currency RUB",
                "buy --currency BTC --amount 0.05",
                "sell --currency BTC --amount 0.01",
                "show-portfolio",
                "show-portfolio --base EUR",
                "get-rate --from USD --to BTC",
                "history",
            ]:
                recorder.run(command)
            for command in [
                "sell --currency BTC --amount 1",
                "get-rate --from ABC --to USD",
                "buy --currency BTC --amount nan",
            ]:
                recorder.run(command, expected=1)
            DemoApiHandler.crypto_failure = True
            recorder.run("update-rates", expected=1)
            recorder.run("logout")
            recorder.run("buy --currency BTC --amount 0.01", expected=1)
            recorder.run("exit")
            recorder.save(args.output)
    finally:
        DemoApiHandler.crypto_failure = False
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        SettingsLoader().reload()
    print(
        f"Демо сохранено: {args.output / 'session.cast'} "
        f"и {args.output / 'session.txt'}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
