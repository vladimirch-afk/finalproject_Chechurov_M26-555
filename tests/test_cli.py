"""Пользовательские сценарии проходят через настоящий парсер команд."""

import io
from contextlib import redirect_stdout
from unittest.mock import patch

from tests.support import IsolatedTestCase
from valutatrade_hub.cli.interface import ConsoleApp


class CliTests(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.app = ConsoleApp(self.service)

    def execute(self, command):
        import shlex

        output = io.StringIO()
        with redirect_stdout(output):
            code = self.app.execute(shlex.split(command))
        return code, output.getvalue()

    def test_full_cli_cycle(self):
        commands = [
            (
                'register --username "alice example" --password secret-pass',
                "зарегистрирован",
            ),
            ('login --username "alice example" --password secret-pass', "Вы вошли"),
            ("deposit --amount 10000", "пополнен"),
            ("buy --currency btc --amount 0.05", "Покупка выполнена"),
            ("sell --currency BTC --amount 0.01", "Продажа выполнена"),
            ("show-portfolio --base EUR", "ИТОГО"),
            ("get-rate --from USD --to BTC", "Обратный курс"),
            ("show-rates --top 2", "BTC_USD"),
            ("show-rates --currency RUB", "RUB_USD"),
            ("history", "BUY"),
        ]
        for command, expected in commands:
            code, output = self.execute(command)
            self.assertEqual(code, 0, output)
            self.assertIn(expected, output)

    def test_friendly_errors(self):
        for command, expected in [
            ("buy --currency BTC --amount 1", "Сначала выполните login"),
            ("get-rate --from ABC --to USD", "Неизвестная валюта"),
            ("get-rate --from USD", "required"),
            ("show-rates --top 0", "положительным"),
            ("unknown", "invalid choice"),
        ]:
            with self.subTest(command=command):
                code, output = self.execute(command)
                self.assertEqual(code, 1)
                self.assertIn(expected, output)
                self.assertNotIn("Traceback", output)

    def test_help_does_not_exit_shell(self):
        self.assertEqual(self.execute("help buy")[0], 0)
        self.assertFalse(self.app.should_exit)
        self.assertEqual(self.execute("version")[0], 0)

    def test_repl_survives_quotes_parse_errors_and_eof(self):
        output = io.StringIO()
        with (
            patch(
                "builtins.input", side_effect=['"unclosed', "buy", "version", EOFError]
            ),
            redirect_stdout(output),
        ):
            self.assertEqual(self.app.run(), 0)
        self.assertIn("Ошибка синтаксиса", output.getvalue())
        self.assertIn("ValutaTrade Hub 0.1.0", output.getvalue())

    def test_update_partial_success_status(self):
        with patch.object(
            self.service,
            "update_rates",
            return_value={
                "updated": 3,
                "last_refresh": "now",
                "errors": ["source unavailable"],
            },
        ):
            code, text = self.execute("update-rates")
        self.assertEqual(code, 1)
        self.assertIn("source unavailable", text)
