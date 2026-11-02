"""Модели, сделки, курсы и целостность JSON-хранилища."""

import json
import math
import os
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

from tests.support import IsolatedTestCase
from valutatrade_hub.core.currencies import Currency, FiatCurrency, get_currency
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    AuthenticationError,
    CurrencyNotFoundError,
    InsufficientFundsError,
    StorageError,
    ValidationError,
)
from valutatrade_hub.core.models import Portfolio, User, Wallet
from valutatrade_hub.core.rates import RateService, resolve_rate
from valutatrade_hub.core.usecases import TradingService
from valutatrade_hub.core.utils import create_ttl_cache, iso_utc, utc_now
from valutatrade_hub.infra.database import DatabaseManager, atomic_write
from valutatrade_hub.infra.settings import SettingsLoader


class ModelTests(IsolatedTestCase):
    def test_user_roundtrip_and_password_change(self):
        user = User.create(1, "alice", "secret-pass")
        self.assertTrue(user.verify_password("secret-pass"))
        self.assertFalse(user.verify_password("wrong"))
        self.assertNotIn("hashed_password", user.get_user_info())
        self.assertNotIn("salt", user.get_user_info())
        restored = User.from_dict(user.to_dict())
        self.assertTrue(restored.verify_password("secret-pass"))
        old_salt = user.salt
        user.change_password("changed")
        self.assertNotEqual(old_salt, user.salt)
        self.assertFalse(user.verify_password("secret-pass"))
        self.assertTrue(user.verify_password("changed"))

    def test_user_validation_and_unique_salts(self):
        for name, password in [(" ", "1234"), ("alice", "123")]:
            with self.assertRaises(ValidationError):
                User.create(1, name, password)
        self.assertNotEqual(
            User.create(1, "a", "1234").salt, User.create(2, "b", "1234").salt
        )

    def test_wallet_rejects_invalid_numbers(self):
        wallet = Wallet("USD", 10)
        for value in [
            True,
            "1",
            None,
            -1,
            math.nan,
            math.inf,
            -math.inf,
            Decimal("1e-1000"),
        ]:
            with self.subTest(value=value), self.assertRaises(ValidationError):
                wallet.deposit(value)
            with self.subTest(balance=value), self.assertRaises(ValidationError):
                wallet.balance = value
        for value in [0, -1]:
            with self.assertRaises(ValidationError):
                wallet.withdraw(value)
        self.assertEqual(wallet.balance, 10)

    def test_wallet_decimal_arithmetic_and_overdraft(self):
        wallet = Wallet("usd", 0.3)
        wallet.withdraw(0.1)
        wallet.withdraw(0.2)
        self.assertEqual(wallet.balance, 0)
        with self.assertRaises(InsufficientFundsError):
            wallet.withdraw(1)
        self.assertIn("USD", wallet.get_balance_info())

    def test_portfolio_ownership_copy_and_total(self):
        self.seed()
        user = User.create(1, "alice", "1234")
        portfolio = Portfolio(user, rate_provider=self.rates.get_rate)
        wallet = portfolio.add_currency("BTC")
        wallet.deposit(0.1)
        self.assertIs(wallet, portfolio.add_currency("btc"))
        portfolio.wallets.clear()
        self.assertIs(portfolio.user, user)
        self.assertEqual(portfolio.get_total_value(), 6000)
        self.assertAlmostEqual(portfolio.get_total_value("EUR"), 6000 / 1.1)
        with self.assertRaises(AttributeError):
            portfolio.user = user

    def test_currency_factory_and_invariants(self):
        self.assertEqual(get_currency("usd").code, "USD")
        with self.assertRaises(CurrencyNotFoundError):
            get_currency("ABC")
        with self.assertRaises(ValidationError):
            get_currency("BT C")
        with self.assertRaises(TypeError):
            Currency("Example", "ABC")
        with self.assertRaises(ValidationError):
            FiatCurrency(" ", "USD", "United States")
        with self.assertRaises(ValidationError):
            FiatCurrency("Dollar", "usd", "United States")


class TradingTests(IsolatedTestCase):
    def setUp(self):
        super().setUp()
        self.seed()
        self.login()

    def test_full_cycle_usd_settlement_and_persistence(self):
        self.assertEqual(self.service.show_portfolio()["rows"], [])
        self.service.deposit(10000)
        self.service.buy("BTC", 0.05)
        result = self.service.sell("BTC", 0.01)
        self.assertEqual(result["changes"]["BTC"]["after"], 0.04)
        self.assertEqual(result["changes"]["USD"]["after"], 7600)
        self.assertEqual(self.service.show_portfolio()["total"], 10000)
        other = TradingService(self.db, self.rates)
        other.login("alice", "secret-pass")
        self.assertEqual(other.show_portfolio()["total"], 10000)
        self.assertEqual(len(other.history()), 3)

    def test_failed_buy_does_not_create_wallet_or_history(self):
        before = self.db.read("portfolios")
        with self.assertRaises(InsufficientFundsError):
            self.service.buy("BTC", 1)
        self.assertEqual(self.db.read("portfolios"), before)
        self.assertEqual(self.service.history(), [])

    def test_failed_sell_and_bad_amount_leave_state_unchanged(self):
        self.service.deposit(100)
        self.service.buy("EUR", 10)
        before = self.db.read("portfolios")
        for code, amount in [
            ("EUR", 11),
            ("BTC", 1),
            ("EUR", -1),
            ("USD", 1),
            ("EUR", math.nan),
        ]:
            with (
                self.subTest(code=code, amount=amount),
                self.assertRaises((InsufficientFundsError, ValidationError)),
            ):
                self.service.sell(code, amount)
            self.assertEqual(self.db.read("portfolios"), before)

    def test_duplicate_and_invalid_password_do_not_write(self):
        before = self.db.read("users")
        with self.assertRaises(ValidationError):
            self.service.register("alice", "1234")
        with self.assertRaises(ValidationError):
            self.service.register("bob", "123")
        self.assertEqual(self.db.read("users"), before)
        self.assertNotIn("secret-pass", self.db.path("users").read_text())

    def test_authentication_and_history_isolation(self):
        self.service.deposit(10)
        self.service.logout()
        for operation in [
            lambda: self.service.buy("BTC", 1),
            self.service.show_portfolio,
            lambda: self.service.deposit(1),
            self.service.history,
        ]:
            with self.assertRaises(AuthenticationError):
                operation()
        with self.assertRaises(AuthenticationError):
            self.service.login("alice", "wrong")
        self.assertIsNone(self.service.current_user)
        self.service.register("bob", "1234")
        self.service.login("bob", "1234")
        self.assertEqual(self.service.history(), [])

    def test_password_change_persists(self):
        self.service.change_password("new-pass")
        self.service.logout()
        with self.assertRaises(AuthenticationError):
            self.service.login("alice", "secret-pass")
        self.service.login("alice", "new-pass")

    def test_log_success_failure_and_password_redaction(self):
        self.service.deposit(10)
        with self.assertRaises(InsufficientFundsError):
            self.service.buy("BTC", 100)
        text = (self.settings.get("LOG_DIR") / "actions.log").read_text()
        rows = [json.loads(line) for line in text.splitlines()]
        self.assertTrue(
            any(row["result"] == "ERROR" and row["action"] == "BUY" for row in rows)
        )
        self.assertTrue(
            any(row["result"] == "OK" and row["action"] == "DEPOSIT" for row in rows)
        )
        self.assertNotIn("secret-pass", text)
        self.assertNotIn("password", text)

    def test_threaded_deposits_are_not_lost(self):
        with ThreadPoolExecutor(max_workers=8) as pool:
            list(pool.map(lambda _: self.service.deposit(1), range(24)))
        self.assertEqual(self.service.show_portfolio()["total"], 24)
        self.assertEqual(len(self.service.history(100)), 24)

    def test_process_deposits_are_not_lost(self):
        commands = (
            "login --username alice --password secret-pass\n"
            + "deposit --amount 1\n" * 4
            + "exit\n"
        )

        def worker(_):
            result = subprocess.run(
                [sys.executable, "-m", "valutatrade_hub"],
                input=commands,
                capture_output=True,
                text=True,
                env=os.environ.copy(),
                timeout=20,
            )
            self.assertEqual(result.returncode, 0, result.stderr)

        with ThreadPoolExecutor(max_workers=3) as pool:
            list(pool.map(worker, range(3)))
        self.assertEqual(self.service.show_portfolio()["total"], 12)


class RateAndStorageTests(IsolatedTestCase):
    def test_direct_inverse_cross_identity(self):
        self.seed()
        self.assertEqual(self.rates.get_rate("BTC", "USD").rate, 60000)
        self.assertAlmostEqual(self.rates.get_rate("USD", "BTC").rate, 1 / 60000)
        self.assertAlmostEqual(self.rates.get_rate("BTC", "EUR").rate, 60000 / 1.1)
        self.assertEqual(self.rates.get_rate("SOL", "SOL").rate, 1)

    def test_stale_quotes_are_rejected_and_listed_as_stale(self):
        self.seed(timestamp=iso_utc(utc_now() - timedelta(minutes=10)))
        with self.assertRaisesRegex(ApiRequestError, "устарел"):
            self.rates.get_rate("BTC", "USD")
        self.assertFalse(self.service.show_rates(currency="BTC")[0]["fresh"])

    def test_cross_rate_rejects_one_stale_leg(self):
        self.seed({"BTC": 60000})
        self.seed({"EUR": 1.1}, iso_utc(utc_now() - timedelta(minutes=10)))
        with self.assertRaises(ApiRequestError):
            self.rates.get_rate("BTC", "EUR", refresh=False)

    def test_refresh_callback_and_cache_invalidation(self):
        rates = RateService(self.db, refresh_callback=lambda: self.seed({"BTC": 100}))
        self.assertEqual(rates.get_rate("BTC", "USD").rate, 100)
        self.seed({"BTC": 200})
        self.assertEqual(rates.get_rate("BTC", "USD").rate, 200)

    def test_filters_and_crypto_top(self):
        self.seed()
        rows = self.service.show_rates(top=2)
        self.assertEqual([row["currency"] for row in rows], ["BTC", "ETH"])
        self.assertEqual(self.service.show_rates(currency="RUB")[0]["currency"], "RUB")
        self.assertAlmostEqual(
            self.service.show_rates(currency="BTC", base="EUR")[0]["rate"], 60000 / 1.1
        )
        with self.assertRaises(ValidationError):
            self.service.show_rates(top=0)

    def test_corrupt_json_is_preserved(self):
        self.db.read("users")
        self.db.path("users").write_text("broken JSON")
        with self.assertRaises(StorageError):
            self.service.register("bob", "1234")
        self.assertEqual(self.db.path("users").read_text(), "broken JSON")

    def test_recovery_after_interrupted_multifile_commit(self):
        self.db.read("users")
        original, failed = atomic_write, []

        def fail_once(path, payload):
            if path.name == "portfolios.json" and not failed:
                failed.append(True)
                raise StorageError("simulated disk failure")
            original(path, payload)

        with patch(
            "valutatrade_hub.infra.database.atomic_write", side_effect=fail_once
        ):
            with self.assertRaises(StorageError):
                self.service.register("alice", "1234")
        self.assertEqual(len(self.db.read("users")), 1)
        self.assertEqual(
            self.db.read("users")[0]["user_id"],
            self.db.read("portfolios")[0]["user_id"],
        )
        self.assertFalse((self.settings.get("DATA_DIR") / ".transaction.json").exists())

    def test_singletons_and_closure_cache(self):
        self.assertIs(SettingsLoader(), self.settings)
        self.assertIs(DatabaseManager(), self.db)
        times = [0]
        cached, clear = create_ttl_cache(5, clock=lambda: times[0])
        calls = []

        def load():
            calls.append(1)
            return {"value": len(calls)}

        self.assertEqual(cached("key", load)["value"], 1)
        cached("key", load)["value"] = 999
        self.assertEqual(cached("key", load)["value"], 1)
        times[0] = 6
        self.assertEqual(cached("key", load)["value"], 2)
        clear()
        self.assertEqual(cached("key", load)["value"], 3)

    def test_malformed_snapshot_is_domain_error(self):
        with self.assertRaises(StorageError):
            resolve_rate({"pairs": {"BTC_USD": {"rate": -1}}}, "BTC", "USD")

    def test_future_timestamp_is_not_used_for_trade(self):
        self.seed(timestamp=iso_utc(utc_now() + timedelta(hours=1)))
        with self.assertRaises(ApiRequestError):
            self.rates.get_rate("BTC", "USD", refresh=False)

    def test_invalid_ttl_configuration_is_reported(self):
        with patch.dict(os.environ, {"VALUTATRADE_RATES_TTL": "-1"}):
            with self.assertRaises(StorageError):
                self.settings.reload()

    def test_rotation_and_repeated_logging_configuration(self):
        import logging

        from valutatrade_hub.logging_config import configure_logging

        self.settings._values["LOG_MAX_BYTES"] = 512
        logger = logging.getLogger("valutatrade.actions")
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)
            handler.close()
        configure_logging(self.settings)
        configure_logging(self.settings)
        self.assertEqual(len(logger.handlers), 1)
        for _ in range(30):
            logger.info("Rotating test event", extra={"event": {"result": "OK"}})
        backups = list(self.settings.get("LOG_DIR").glob("actions.log.*"))
        self.assertEqual(len(backups), 3)
