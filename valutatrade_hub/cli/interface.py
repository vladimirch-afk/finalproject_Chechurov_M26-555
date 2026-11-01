"""Разбор команд и представление результатов без торговой логики."""

import argparse
import getpass
import shlex
import sys
from collections.abc import Sequence

from prettytable import PrettyTable

from valutatrade_hub import __version__
from valutatrade_hub.core.currencies import supported_currencies
from valutatrade_hub.core.exceptions import (
    CurrencyNotFoundError,
    ValidationError,
    ValutaTradeError,
)
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.logging_config import configure_logging


class CommandParser(argparse.ArgumentParser):
    """Ошибки аргументов не завершают интерактивную сессию."""

    def error(self, message):
        """Перевести ошибку argparse в пользовательское исключение."""
        raise ValidationError(f"{message}. Введите help для справки")


def build_parser() -> CommandParser:
    """Создать единый набор команд для REPL и однократного запуска."""
    parser = CommandParser(
        prog="valutatrade", description="ValutaTrade Hub — виртуальный валютный кошелёк"
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    commands = parser.add_subparsers(dest="command")
    for name, description in [("register", "Регистрация"), ("login", "Вход")]:
        command = commands.add_parser(name, help=description)
        command.add_argument("--username", required=True)
        command.add_argument(
            "--password", help="Если пропущен, пароль запрашивается скрыто"
        )
    commands.add_parser("logout", help="Закрыть сессию")
    portfolio = commands.add_parser("show-portfolio", help="Кошельки и общая стоимость")
    portfolio.add_argument("--base")
    for name in ["buy", "sell"]:
        trade = commands.add_parser(
            name, help="Купить валюту" if name == "buy" else "Продать валюту"
        )
        trade.add_argument("--currency", required=True)
        trade.add_argument("--amount", type=float, required=True)
    deposit = commands.add_parser("deposit", help="Пополнить виртуальный USD-кошелёк")
    deposit.add_argument("--amount", type=float, required=True)
    rate = commands.add_parser("get-rate", help="Получить свежий курс")
    rate.add_argument("--from", dest="from_code", required=True)
    rate.add_argument("--to", dest="to_code", required=True)
    update = commands.add_parser("update-rates", help="Обновить курсы из API")
    update.add_argument("--source", choices=["coingecko", "exchangerate"])
    rates = commands.add_parser("show-rates", help="Посмотреть локальный кеш курсов")
    rates.add_argument("--currency")
    rates.add_argument("--top", type=int)
    rates.add_argument("--base")
    history = commands.add_parser("history", help="История своих операций")
    history.add_argument("--limit", type=int, default=20)
    change = commands.add_parser("change-password", help="Изменить пароль")
    change.add_argument("--new-password")
    help_command = commands.add_parser("help", help="Справка по командам")
    help_command.add_argument("topic", nargs="?")
    commands.add_parser("currencies", help="Поддерживаемые валюты")
    for name in ["version", "exit", "quit"]:
        commands.add_parser(name)
    return parser


def display_table(headers, rows) -> None:
    """Вывести строки в таблице PrettyTable."""
    table = PrettyTable(headers)
    table.align = "l"
    table.add_rows(rows)
    print(table)


def read_password(value: str | None) -> str:
    """Принять явно заданный пароль или запросить его без эха в терминале."""
    if value is not None:
        return value
    if not sys.stdin.isatty():
        raise ValidationError("Для пакетного ввода укажите --password / --new-password")
    try:
        return getpass.getpass("Пароль: ")
    except EOFError as error:
        raise ValidationError("Ввод пароля прерван") from error


class ConsoleApp:
    """Интерактивная оболочка с сессией, живущей до выхода из приложения."""

    def __init__(self, service=None):
        self.service = service or TradingService()
        self.parser = build_parser()
        self.should_exit = False

    def run(self) -> int:
        """Читать команды; ошибки отдельной команды не завершают REPL."""
        print("ValutaTrade Hub — виртуальный валютный кошелёк. Введите help.")
        while not self.should_exit:
            try:
                line = input("valutatrade> ")
            except (EOFError, KeyboardInterrupt):
                print("\nДо свидания!")
                break
            try:
                tokens = shlex.split(line)
            except ValueError as error:
                print(f"Ошибка синтаксиса: {error}")
                continue
            if tokens:
                self.execute(tokens)
        return 0

    def execute(self, tokens: Sequence[str]) -> int:
        """Разобрать команду, вызвать сценарий и отобразить результат."""
        try:
            args = self.parser.parse_args(tokens)
            return self._dispatch(args)
        except SystemExit as error:
            return int(error.code or 0)
        except CurrencyNotFoundError as error:
            print(f"{error}. Список валют: currencies; справка: help get-rate")
        except ValutaTradeError as error:
            print(error)
        return 1

    def _dispatch(self, args) -> int:
        service, command = self.service, args.command
        match command:
            case "help":
                if args.topic:
                    self.parser.parse_args([args.topic, "--help"])
                else:
                    self.parser.print_help()
            case "register":
                user = service.register(args.username, read_password(args.password))
                print(
                    f"Пользователь '{user['username']}' зарегистрирован "
                    f"(id={user['user_id']}). Войдите: login "
                    f"--username {shlex.quote(user['username'])}"
                )
            case "login":
                user = service.login(args.username, read_password(args.password))
                print(f"Вы вошли как '{user['username']}'")
            case "logout":
                service.logout()
                print("Вы вышли из системы")
            case "change-password":
                service.change_password(read_password(args.new_password))
                print("Пароль изменён")
            case "deposit":
                result = service.deposit(args.amount)
                print(f"Виртуальный счёт пополнен: {result['amount']:,.2f} USD")
            case "buy" | "sell":
                result = getattr(service, command)(args.currency, args.amount)
                title = "Покупка" if command == "buy" else "Продажа"
                print(
                    f"{title} выполнена: {result['amount']:.8f} "
                    f"{result['currency_code']} по курсу {result['rate']:.8f} "
                    f"USD/{result['currency_code']}"
                )
                display_table(
                    ["Валюта", "Было", "Стало"],
                    [
                        [code, f"{values['before']:.8f}", f"{values['after']:.8f}"]
                        for code, values in result["changes"].items()
                    ],
                )
                print(f"Стоимость / выручка: {result['usd_value']:,.2f} USD")
            case "show-portfolio":
                result = service.show_portfolio(args.base)
                print(
                    f"Портфель пользователя '{result['username']}' "
                    f"(база: {result['base']}):"
                )
                if not result["rows"]:
                    print(
                        "Портфель пуст. Пополните виртуальный счёт: "
                        "deposit --amount 10000"
                    )
                else:
                    display_table(
                        ["Валюта", "Баланс", result["base"]],
                        [
                            [
                                row["currency"],
                                f"{row['balance']:.8f}",
                                f"{row['value']:,.2f}",
                            ]
                            for row in result["rows"]
                        ],
                    )
                print(f"ИТОГО: {result['total']:,.2f} {result['base']}")
            case "get-rate":
                quote = service.get_rate(args.from_code, args.to_code)
                print(
                    f"Курс {quote.from_currency}→{quote.to_currency}: "
                    f"{quote.rate:.10g} (обновлено: {quote.updated_at}; {quote.source})"
                )
                print(
                    f"Обратный курс {quote.to_currency}→{quote.from_currency}: "
                    f"{1 / quote.rate:.10g}"
                )
            case "update-rates":
                result = service.update_rates(args.source)
                print(
                    f"Курсы обновлены: {result['updated']}. "
                    f"Последнее обновление: {result['last_refresh']}"
                )
                if result["errors"]:
                    print("Обновление завершено с ошибками источников:")
                    for message in result["errors"]:
                        print(f"- {message}")
                    print("Подробности: parser.log в каталоге журналов")
                    return 1
            case "show-rates":
                rows = service.show_rates(args.currency, args.top, args.base)
                display_table(
                    ["Пара", "Курс", "Обновлено (UTC)", "Источник", "Статус"],
                    [
                        [
                            f"{r['currency']}_{r['base']}",
                            f"{r['rate']:.10g}",
                            r["updated_at"],
                            r["source"],
                            "актуален" if r["fresh"] else "устарел: update-rates",
                        ]
                        for r in rows
                    ],
                )
            case "history":
                rows = service.history(args.limit)
                if not rows:
                    print("История операций пуста")
                else:
                    display_table(
                        [
                            "Время (UTC)",
                            "Операция",
                            "Валюта",
                            "Количество",
                            "Стоимость USD",
                        ],
                        [
                            [
                                r["timestamp"],
                                r["action"],
                                r["currency_code"],
                                f"{r['amount']:.8f}",
                                f"{r['usd_value']:,.2f}",
                            ]
                            for r in rows
                        ],
                    )
            case "currencies":
                for currency in supported_currencies():
                    print(currency.get_display_info())
            case "version":
                print(f"ValutaTrade Hub {__version__}")
            case "exit" | "quit":
                self.should_exit = True
                print("До свидания!")
            case _:
                self.parser.print_help()
        return 0


def main(argv: Sequence[str] | None = None) -> int:
    """Открыть REPL без аргументов или выполнить одну команду."""
    try:
        configure_logging()
        app = ConsoleApp()
        tokens = list(sys.argv[1:] if argv is None else argv)
        return app.execute(tokens) if tokens else app.run()
    except ValutaTradeError as error:
        print(error)
        return 1
    except KeyboardInterrupt:
        return 130
