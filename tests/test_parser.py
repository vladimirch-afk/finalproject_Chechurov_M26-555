"""Контракты API, независимость источников и история курсов."""

from datetime import timedelta
from unittest.mock import Mock, patch

import requests

from tests.support import IsolatedTestCase
from valutatrade_hub.core.exceptions import ApiRequestError, StorageError
from valutatrade_hub.core.utils import iso_utc, utc_now
from valutatrade_hub.parser_service.api_clients import (
    CoinGeckoClient,
    ExchangeRateApiClient,
)
from valutatrade_hub.parser_service.config import ParserConfig
from valutatrade_hub.parser_service.scheduler import run_scheduler
from valutatrade_hub.parser_service.storage import RatesStorage
from valutatrade_hub.parser_service.updater import RatesUpdater, build_updater


def session_with(data, status=200):
    """Подготовить HTTP-ответ без внешнего запроса."""
    session = Mock()
    response = session.get.return_value
    response.status_code = status
    response.headers = {"ETag": "test-etag"}
    response.json.return_value = data
    return session


class ClientTests(IsolatedTestCase):
    def test_coingecko_mapping_timeout_and_metadata(self):
        session = session_with(
            {
                "bitcoin": {"usd": 60000},
                "ethereum": {"usd": 3000},
                "solana": {"usd": 150},
            }
        )
        client = CoinGeckoClient(ParserConfig(), session)
        self.assertEqual(
            client.fetch_rates(), {"BTC_USD": 60000, "ETH_USD": 3000, "SOL_USD": 150}
        )
        kwargs = session.get.call_args.kwargs
        self.assertEqual(kwargs["params"]["ids"], "bitcoin,ethereum,solana")
        self.assertEqual(kwargs["timeout"], 10)
        self.assertEqual(client.metadata["BTC_USD"]["raw_id"], "bitcoin")
        self.assertEqual(client.metadata["BTC_USD"]["etag"], "test-etag")

    def test_exchange_inverts_actual_api_and_tz_example(self):
        for field in ["conversion_rates", "rates"]:
            with self.subTest(field=field):
                client = ExchangeRateApiClient(
                    ParserConfig(EXCHANGERATE_API_KEY="example-secret"),
                    session_with(
                        {
                            "result": "success",
                            "base_code": "USD",
                            field: {"EUR": 0.8, "GBP": 0.5, "RUB": 100},
                        }
                    ),
                )
                values = client.fetch_rates()
                self.assertEqual(
                    values, {"EUR_USD": 1.25, "GBP_USD": 2, "RUB_USD": 0.01}
                )

    def test_missing_key_does_not_send_request(self):
        session = Mock()
        client = ExchangeRateApiClient(ParserConfig(EXCHANGERATE_API_KEY=""), session)
        with self.assertRaisesRegex(ApiRequestError, "EXCHANGERATE_API_KEY"):
            client.fetch_rates()
        session.get.assert_not_called()

    def test_http_error_codes(self):
        for status in [401, 403, 429, 500]:
            with (
                self.subTest(status=status),
                self.assertRaisesRegex(ApiRequestError, str(status)),
            ):
                CoinGeckoClient(session=session_with({}, status)).fetch_rates()

    def test_network_error_does_not_leak_key(self):
        for failure in [
            requests.exceptions.Timeout("timeout"),
            requests.exceptions.ConnectionError("https://example-secret/latest/USD"),
        ]:
            session = Mock()
            session.get.side_effect = failure
            client = ExchangeRateApiClient(
                ParserConfig(EXCHANGERATE_API_KEY="example-secret"), session
            )
            with self.assertRaises(ApiRequestError) as caught:
                client.fetch_rates()
            self.assertNotIn("example-secret", str(caught.exception))

    def test_invalid_json_and_nonobject_response(self):
        session = session_with({})
        session.get.return_value.json.side_effect = ValueError("invalid JSON")
        with self.assertRaises(ApiRequestError):
            CoinGeckoClient(session=session).fetch_rates()
        with self.assertRaises(ApiRequestError):
            CoinGeckoClient(session=session_with([])).fetch_rates()

    def test_missing_negative_nan_and_string_prices(self):
        for value in [None, -1, 0, float("nan"), True, "100"]:
            with self.subTest(value=value), self.assertRaises(ApiRequestError):
                CoinGeckoClient(
                    ParserConfig(CRYPTO_CURRENCIES=("BTC",)),
                    session_with({"bitcoin": {"usd": value}}),
                ).fetch_rates()
        with self.assertRaises(ApiRequestError):
            CoinGeckoClient(session=session_with({})).fetch_rates()

    def test_provider_error_and_wrong_base(self):
        for payload in [
            {"result": "error", "error-type": "invalid-key"},
            {"result": "success", "base_code": "EUR", "conversion_rates": {}},
        ]:
            with self.subTest(payload=payload), self.assertRaises(ApiRequestError):
                ExchangeRateApiClient(
                    ParserConfig(EXCHANGERATE_API_KEY="secret"), session_with(payload)
                ).fetch_rates()

    def test_secret_not_in_config_repr(self):
        self.assertNotIn(
            "private-value", repr(ParserConfig(EXCHANGERATE_API_KEY="private-value"))
        )


class UpdateAndHistoryTests(IsolatedTestCase):
    def test_partial_success_keeps_other_source(self):
        good = Mock(source="Good", observed_at=iso_utc(), metadata={})
        good.fetch_rates.return_value = {"BTC_USD": 60000}
        bad = Mock(source="Bad")
        bad.fetch_rates.side_effect = ApiRequestError("network failure")
        result = RatesUpdater([bad, good], RatesStorage(self.db)).run_update()
        self.assertEqual(result["updated"], 1)
        self.assertEqual(len(result["errors"]), 1)
        self.assertIn("BTC_USD", self.db.read("rates")["pairs"])
        self.assertEqual(len(self.db.read("exchange_rates")), 1)

    def test_total_failure_does_not_replace_cache(self):
        self.seed()
        before = self.db.read("rates")
        bad = Mock(source="Bad")
        bad.fetch_rates.side_effect = ApiRequestError("network failure")
        with self.assertRaises(ApiRequestError):
            RatesUpdater([bad], RatesStorage(self.db)).run_update()
        self.assertEqual(self.db.read("rates"), before)

    def test_merge_newer_wins_and_history_deduplicates(self):
        self.seed({"BTC": 60000})
        snapshot = self.db.read("rates")
        timestamp = snapshot["pairs"]["BTC_USD"]["updated_at"]
        record = {
            "from_currency": "BTC",
            "to_currency": "USD",
            "rate": 1,
            "timestamp": timestamp,
            "source": "Duplicate",
        }
        storage = RatesStorage(self.db)
        self.assertEqual(storage.save([record])["updated"], 0)
        self.assertEqual(len(self.db.read("exchange_rates")), 1)
        record["timestamp"] = iso_utc(utc_now() - timedelta(days=1))
        self.assertEqual(storage.save([record])["updated"], 0)
        self.assertEqual(self.db.read("rates")["pairs"]["BTC_USD"]["rate"], 60000)
        self.assertEqual(len(self.db.read("exchange_rates")), 2)
        self.seed({"ETH": 3000})
        self.assertIn("BTC_USD", self.db.read("rates")["pairs"])
        self.assertIn("ETH_USD", self.db.read("rates")["pairs"])

    def test_invalid_measurement_never_written(self):
        self.seed()
        before = self.db.read("rates")
        with self.assertRaises(StorageError):
            RatesStorage(self.db).save(
                [
                    {
                        "from_currency": "BTC",
                        "to_currency": "USD",
                        "rate": -1,
                        "timestamp": iso_utc(),
                        "source": "Invalid",
                    }
                ]
            )
        self.assertEqual(self.db.read("rates"), before)

    def test_source_selection(self):
        self.assertEqual(
            [c.source for c in build_updater("coingecko").clients], ["CoinGecko"]
        )
        self.assertEqual(
            [c.source for c in build_updater("exchangerate").clients],
            ["ExchangeRate-API"],
        )
        self.assertEqual(len(build_updater().clients), 2)

    def test_scheduler_continues_after_api_failure(self):
        updater = Mock()
        updater.run_update.side_effect = [ApiRequestError("offline"), {"updated": 1}]
        sleep = Mock()
        with patch(
            "valutatrade_hub.parser_service.scheduler.build_updater",
            return_value=updater,
        ):
            run_scheduler(interval=1, iterations=2, sleep=sleep)
        self.assertEqual(updater.run_update.call_count, 2)
        sleep.assert_called_once_with(1)

    def test_invalid_source_batch_does_not_discard_other_source(self):
        for pair, timestamp in [("ABC_USD", iso_utc()), ("BTC_USD", "broken")]:
            with self.subTest(pair=pair, timestamp=timestamp):
                bad = Mock(source="Bad", observed_at=timestamp, metadata={})
                bad.fetch_rates.return_value = {pair: 1}
                good = Mock(source="Good", observed_at=iso_utc(), metadata={})
                good.fetch_rates.return_value = {"ETH_USD": 3000}
                result = RatesUpdater([bad, good], RatesStorage(self.db)).run_update()
                self.assertEqual(len(result["errors"]), 1)
                self.assertIn("ETH_USD", self.db.read("rates")["pairs"])
