"""Минимальная командная оболочка для этапа подготовки проекта."""

import argparse
import shlex
from collections.abc import Sequence

from prettytable import PrettyTable

from valutatrade_hub import __version__


class ConsoleApp:
    """Оболочка с командами справки, версии и завершения работы."""

    def run(self) -> int:
        """Читать команды до exit, конца ввода или прерывания клавиатурой."""
        print("ValutaTrade Hub — консольный симулятор валютного кошелька.")
        print("Этап 1: окружение и структура готовы. Для справки введите help.")
        while True:
            try:
                line = input("valutatrade> ")
            except (EOFError, KeyboardInterrupt):
                print("\nДо свидания!")
                return 0

            try:
                tokens = shlex.split(line)
            except ValueError as error:
                print(f"Ошибка синтаксиса: {error}")
                continue

            if not tokens:
                continue
            if len(tokens) != 1:
                print("Эта команда не принимает аргументы. Введите help.")
                continue

            match tokens[0]:
                case "exit" | "quit":
                    print("До свидания!")
                    return 0
                case "help":
                    self.show_help()
                case "version":
                    print(f"ValutaTrade Hub {__version__}")
                case _:
                    print(f"Неизвестная команда '{tokens[0]}'. Введите help.")

    def show_help(self) -> None:
        """Показать команды, реализованные на этапе подготовки."""
        table = PrettyTable(["Команда", "Описание"])
        table.align = "l"
        table.add_rows(
            [
                ["help", "Показать справку"],
                ["version", "Показать версию приложения"],
                ["exit / quit", "Завершить работу"],
            ]
        )
        print(table)
        print("Регистрация, кошельки и торговые команды — следующие этапы проекта.")


def main(argv: Sequence[str] | None = None) -> int:
    """Обработать параметры запуска и открыть интерактивную оболочку."""
    parser = argparse.ArgumentParser(
        prog="valutatrade",
        description="ValutaTrade Hub — консольный симулятор валютного кошелька.",
        epilog="Этап 1: подготовка. Команды оболочки: help, version, exit.",
    )
    parser.add_argument(
        "--version", action="version", version=f"%(prog)s {__version__}"
    )
    parser.parse_args(argv)
    return ConsoleApp().run()
