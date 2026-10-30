"""Прикладные сценарии; ввод и форматирование остаются в CLI."""

from decimal import Decimal
from uuid import uuid4

from valutatrade_hub.core.currencies import (
    CryptoCurrency,
    get_currency,
    supported_currencies,
)
from valutatrade_hub.core.exceptions import (
    ApiRequestError,
    AuthenticationError,
    StorageError,
    ValidationError,
    ValutaTradeError,
)
from valutatrade_hub.core.models import Portfolio, User
from valutatrade_hub.core.rates import RateService, is_fresh, resolve_rate
from valutatrade_hub.core.utils import iso_utc, number
from valutatrade_hub.decorators import log_action
from valutatrade_hub.infra.database import DatabaseManager
from valutatrade_hub.infra.settings import SettingsLoader


class TradingService:
    """Сессия одного CLI; изменения портфелей выполняются под блокировкой БД."""

    def __init__(self, db=None, rates=None, updater_factory=None):
        self.db = db or DatabaseManager()
        self.updater_factory = updater_factory
        self.rates = rates or RateService(
            self.db, refresh_callback=lambda: self.update_rates()
        )
        self.settings = SettingsLoader()
        self.current_user = None

    def _users(self):
        try:
            users = [User.from_dict(row) for row in self.db.read("users")]
            if len({u.user_id for u in users}) != len(users) or len(
                {u.username for u in users}
            ) != len(users):
                raise ValueError("Повторяются имена или идентификаторы")
            return users
        except (
            KeyError,
            TypeError,
            AttributeError,
            ValueError,
            ValutaTradeError,
        ) as error:
            raise StorageError(f"Некорректные данные пользователей: {error}") from error

    def _require_login(self) -> User:
        if self.current_user is None:
            raise AuthenticationError("Сначала выполните login")
        return self.current_user

    def _portfolio(self):
        user = self._require_login()
        records = self.db.read("portfolios")
        try:
            matching = [row for row in records if row["user_id"] == user.user_id]
            if len(matching) != 1:
                raise ValueError("Портфель отсутствует или дублируется")
            portfolio = Portfolio.from_dict(matching[0], user, self.rates.get_rate)
            return portfolio, records
        except (
            KeyError,
            TypeError,
            AttributeError,
            ValueError,
            ValutaTradeError,
        ) as error:
            raise StorageError(f"Некорректный портфель: {error}") from error

    @log_action("REGISTER")
    def register(self, username: str, password: str) -> dict:
        """Создать пользователя и пустой портфель одной транзакцией."""
        if not isinstance(username, str) or not username.strip():
            raise ValidationError("Имя пользователя не может быть пустым")
        username = username.strip()
        with self.db.transaction():
            users = self._users()
            if any(user.username == username for user in users):
                raise ValidationError(f"Имя пользователя '{username}' уже занято")
            user = User.create(
                max((u.user_id for u in users), default=0) + 1, username, password
            )
            portfolios = self.db.read("portfolios")
            portfolios.append(Portfolio(user).to_dict())
            self.db.write_many(
                {
                    "users": [u.to_dict() for u in [*users, user]],
                    "portfolios": portfolios,
                }
            )
            return user.get_user_info()

    @log_action("LOGIN")
    def login(self, username: str, password: str) -> dict:
        """Открыть сессию после проверки пароля; не хранить пароль в сессии."""

        self.current_user = None
        if not isinstance(username, str) or not username.strip():
            raise ValidationError("Имя пользователя не может быть пустым")
        user = next((u for u in self._users() if u.username == username.strip()), None)
        if user is None:
            raise AuthenticationError(f"Пользователь '{username}' не найден")
        if not user.verify_password(password):
            raise AuthenticationError("Неверный пароль")
        self.current_user = user
        return user.get_user_info()

    def logout(self) -> None:
        """Закрыть текущую сессию."""
        self.current_user = None

    def change_password(self, new_password: str) -> None:
        """Изменить пароль активного пользователя и сохранить новый хеш."""
        user_id = self._require_login().user_id
        with self.db.transaction():
            users = self._users()
            user = next((u for u in users if u.user_id == user_id), None)
            if user is None:
                raise AuthenticationError("Пользователь больше не существует")
            user.change_password(new_password)
            self.db.write_many({"users": [u.to_dict() for u in users]})
            self.current_user = user

    def _save_operation(
        self, portfolio, portfolios, action, code, amount, rate, changes
    ):
        entry = {
            "id": str(uuid4()),
            "timestamp": iso_utc(),
            "user_id": portfolio.user_id,
            "username": portfolio.user.username,
            "action": action,
            "currency_code": code,
            "amount": float(amount),
            "rate": float(rate),
            "base": "USD",
            "usd_value": float(number(amount * rate)),
            "changes": changes,
        }
        history = self.db.read("transactions")
        history.append(entry)
        updated = [
            portfolio.to_dict() if row["user_id"] == portfolio.user_id else row
            for row in portfolios
        ]
        self.db.write_many({"portfolios": updated, "transactions": history})
        return entry

    @log_action("DEPOSIT", verbose=True)
    def deposit(self, amount: float) -> dict:
        """Пополнить USD-кошелёк виртуальными средствами для симуляции."""
        self._require_login()
        amount = number(amount)
        with self.db.transaction():
            portfolio, records = self._portfolio()
            wallet = portfolio.add_currency("USD")
            before = wallet.balance
            wallet.deposit(amount)
            return self._save_operation(
                portfolio,
                records,
                "DEPOSIT",
                "USD",
                amount,
                Decimal(1),
                {"USD": {"before": before, "after": wallet.balance}},
            )

    def _trade(self, action, currency_code, amount):
        self._require_login()
        code, amount = get_currency(currency_code).code, number(amount)
        if code == "USD":
            raise ValidationError(
                "USD — расчётная валюта. Для пополнения используйте deposit"
            )
        quote = self.rates.get_rate(code, "USD")
        rate = number(quote.rate)
        cost = number(amount * rate)
        with self.db.transaction():
            if not is_fresh(quote.updated_at, self.settings.get("RATES_TTL_SECONDS")):
                raise ApiRequestError(
                    "Курс устарел во время операции. Выполните update-rates"
                )
            portfolio, records = self._portfolio()
            asset = portfolio.get_wallet(code)
            if action == "SELL" and asset is None:
                raise ValidationError(
                    f"У вас нет кошелька '{code}'. Он создаётся при первой покупке"
                )
            asset = asset or portfolio.add_currency(code)
            usd = portfolio.add_currency("USD")
            before = {code: asset.balance, "USD": usd.balance}
            if action == "BUY":
                usd.withdraw(cost)
                asset.deposit(amount)
            else:
                asset.withdraw(amount)
                usd.deposit(cost)
            changes = {
                c: {"before": before[c], "after": w.balance}
                for c, w in [(code, asset), ("USD", usd)]
            }
            return self._save_operation(
                portfolio, records, action, code, amount, rate, changes
            )

    @log_action("BUY", verbose=True)
    def buy(self, currency_code: str, amount: float) -> dict:
        """Купить валюту с одновременным списанием стоимости в USD."""
        return self._trade("BUY", currency_code, amount)

    @log_action("SELL", verbose=True)
    def sell(self, currency_code: str, amount: float) -> dict:
        """Продать валюту и начислить выручку на USD-кошелёк."""
        return self._trade("SELL", currency_code, amount)

    def get_rate(self, from_code: str, to_code: str):
        """Получить актуальную котировку без требования входа."""
        return self.rates.get_rate(from_code, to_code)

    def update_rates(self, source: str | None = None) -> dict:
        """Запустить Parser Service по запросу пользователя."""
        from valutatrade_hub.parser_service.updater import build_updater

        factory = self.updater_factory or build_updater
        result = factory(source).run_update()
        self.rates.clear_cache()
        return result

    def show_portfolio(self, base: str | None = None) -> dict:
        """Получить строки портфеля и суммарную оценку в выбранной базе."""
        self._require_login()
        base = get_currency(base or self.settings.get("DEFAULT_BASE_CURRENCY")).code
        with self.db.transaction():
            portfolio, _ = self._portfolio()
        rows, total = [], Decimal(0)
        for code, wallet in sorted(portfolio.wallets.items()):
            value = number(wallet.balance, positive=False)
            if value:
                value *= number(self.rates.get_rate(code, base).rate)
            rows.append(
                {
                    "currency": code,
                    "balance": wallet.balance,
                    "value": float(number(value, positive=False)),
                }
            )
            total += value
        return {
            "username": portfolio.user.username,
            "base": base,
            "rows": rows,
            "total": float(number(total, positive=False)),
        }

    def history(self, limit: int = 20) -> list[dict]:
        """Вернуть последние операции только текущего пользователя."""
        user = self._require_login()
        if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1:
            raise ValidationError("limit должен быть положительным целым числом")
        try:
            return [
                row
                for row in self.db.read("transactions")
                if row["user_id"] == user.user_id
            ][-limit:][::-1]
        except (TypeError, KeyError) as error:
            raise StorageError("Некорректная история операций") from error

    def show_rates(self, currency=None, top=None, base=None) -> list[dict]:
        """Отфильтровать кэш без сети; помечать устаревшие значения."""
        base = get_currency(base or self.settings.get("DEFAULT_BASE_CURRENCY")).code
        code = get_currency(currency).code if currency else None
        if top is not None and (
            isinstance(top, bool) or not isinstance(top, int) or top < 1
        ):
            raise ValidationError("top должен быть положительным целым числом")
        snapshot = self.rates.snapshot()
        if not snapshot.get("pairs"):
            raise ValidationError("Локальный кеш курсов пуст. Выполните update-rates")
        rows = []
        for item in supported_currencies():
            if item.code == base or (code and item.code != code):
                continue
            if top is not None and not isinstance(item, CryptoCurrency):
                continue
            try:
                quote = resolve_rate(snapshot, item.code, base)
            except ApiRequestError:
                continue
            rows.append(
                {
                    "currency": item.code,
                    "base": base,
                    "rate": quote.rate,
                    "updated_at": quote.updated_at,
                    "source": quote.source,
                    "fresh": is_fresh(
                        quote.updated_at, self.settings.get("RATES_TTL_SECONDS")
                    ),
                }
            )
        if not rows:
            raise ValidationError(f"Курс для '{code or base}' не найден в кеше")
        rows.sort(
            key=(lambda row: (-row["rate"], row["currency"]))
            if top
            else lambda row: row["currency"]
        )
        return rows[:top] if top else rows
