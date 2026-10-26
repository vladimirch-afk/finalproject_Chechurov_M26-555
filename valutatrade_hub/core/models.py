"""Модели пользователей, кошельков и портфелей с валидацией инвариантов."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime
from decimal import Decimal

from valutatrade_hub.core.currencies import get_currency
from valutatrade_hub.core.exceptions import InsufficientFundsError, ValidationError
from valutatrade_hub.core.utils import iso_utc, number, parse_time, utc_now


class User:
    """Пользователь; соль и SHA-256 реализуют учебное требование к паролям."""

    def __init__(self, user_id, username, hashed_password, salt, registration_date):
        if isinstance(user_id, bool) or not isinstance(user_id, int) or user_id < 1:
            raise ValidationError("user_id должен быть положительным целым числом")
        if not isinstance(hashed_password, str) or not re.fullmatch(
            "[0-9a-f]{64}", hashed_password
        ):
            raise ValidationError("Некорректный хеш пароля")
        if not isinstance(salt, str) or not salt:
            raise ValidationError("Соль не может быть пустой")
        if not isinstance(registration_date, datetime):
            raise ValidationError("registration_date должен быть datetime")
        self._user_id = user_id
        self.username = username
        self._hashed_password, self._salt = hashed_password, salt
        self._registration_date = registration_date.replace(
            tzinfo=registration_date.tzinfo or UTC
        ).astimezone(UTC)

    @classmethod
    def create(cls, user_id: int, username: str, password: str):
        """Создать пользователя со случайной солью и датой регистрации."""
        user = cls(user_id, username, "0" * 64, secrets.token_hex(16), utc_now())
        user.change_password(password)
        return user

    @property
    def user_id(self) -> int:
        """Неизменяемый идентификатор."""
        return self._user_id

    @property
    def username(self) -> str:
        """Имя пользователя."""
        return self._username

    @username.setter
    def username(self, value: str):
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Имя пользователя не может быть пустым")
        self._username = value.strip()

    @property
    def hashed_password(self) -> str:
        """Хеш для сериализации."""
        return self._hashed_password

    @property
    def salt(self) -> str:
        """Соль для восстановления пользователя из хранилища."""
        return self._salt

    @property
    def registration_date(self) -> datetime:
        """Дата регистрации в UTC."""
        return self._registration_date

    def get_user_info(self) -> dict:
        """Вернуть публичные данные без хеша и соли."""
        return {
            "user_id": self.user_id,
            "username": self.username,
            "registration_date": iso_utc(self.registration_date),
        }

    def change_password(self, new_password: str) -> None:
        """Проверить пароль и обновить его хеш с новой солью."""
        if not isinstance(new_password, str) or len(new_password) < 4:
            raise ValidationError("Пароль должен быть не короче 4 символов")
        self._salt = secrets.token_hex(16)
        self._hashed_password = hashlib.sha256(
            (new_password + self._salt).encode()
        ).hexdigest()

    def verify_password(self, password: str) -> bool:
        """Сравнить хеши за постоянное время."""
        if not isinstance(password, str):
            return False
        digest = hashlib.sha256((password + self.salt).encode()).hexdigest()
        return hmac.compare_digest(digest, self.hashed_password)

    def to_dict(self) -> dict:
        """Вернуть запись для users.json."""
        return {
            **self.get_user_info(),
            "hashed_password": self.hashed_password,
            "salt": self.salt,
        }

    @classmethod
    def from_dict(cls, record: dict):
        """Восстановить и проверить пользователя из JSON."""
        return cls(
            record["user_id"],
            record["username"],
            record["hashed_password"],
            record["salt"],
            parse_time(record["registration_date"]),
        )


class Wallet:
    """Остаток одной валюты; арифметика выполняется через Decimal."""

    def __init__(self, currency_code: str, balance=0.0):
        self._currency_code = get_currency(currency_code).code
        self.balance = balance

    @property
    def currency_code(self) -> str:
        """Неизменяемый код валюты кошелька."""
        return self._currency_code

    @property
    def balance(self) -> float:
        """Баланс в публичном числовом формате ТЗ."""
        return float(self._balance)

    @balance.setter
    def balance(self, value):
        self._balance = number(value, positive=False, label="balance")

    def deposit(self, amount: float) -> None:
        """Пополнить кошелёк положительным конечным числом."""
        self.balance = self._balance + number(amount)

    def withdraw(self, amount: float) -> None:
        """Списать средства, не допуская отрицательного остатка."""
        amount = number(amount)
        if amount > self._balance:
            raise InsufficientFundsError(self._balance, amount, self.currency_code)
        self.balance = self._balance - amount

    def get_balance_info(self) -> str:
        """Вернуть код валюты и баланс."""
        return f"{self.currency_code}: {self.balance:.8f}"

    def to_dict(self) -> dict:
        """Сериализовать кошелёк в JSON-совместимую структуру."""
        return {"currency_code": self.currency_code, "balance": self.balance}


class Portfolio:
    """Кошельки одного пользователя с внешним провайдером курсов."""

    def __init__(
        self, user: User, wallets: dict[str, Wallet] | None = None, rate_provider=None
    ):
        if not isinstance(user, User):
            raise ValidationError("Портфель должен принадлежать User")
        self._user, self._user_id = user, user.user_id
        self._wallets, self._rate_provider = dict(wallets or {}), rate_provider
        for code, wallet in self._wallets.items():
            if not isinstance(wallet, Wallet) or code != wallet.currency_code:
                raise ValidationError("Код кошелька не совпадает с ключом портфеля")

    @property
    def user(self) -> User:
        """Владелец; свойство не допускает перезапись."""
        return self._user

    @property
    def user_id(self) -> int:
        """Идентификатор владельца."""
        return self._user_id

    @property
    def wallets(self) -> dict[str, Wallet]:
        """Вернуть копию словаря кошельков."""
        return dict(self._wallets)

    def add_currency(self, currency_code: str) -> Wallet:
        """Создать кошелёк при отсутствии; повторный вызов сохраняет баланс."""
        code = get_currency(currency_code).code
        if code not in self._wallets:
            self._wallets[code] = Wallet(code)
        return self._wallets[code]

    def get_wallet(self, currency_code: str) -> Wallet | None:
        """Найти кошелёк по нормализованному коду."""
        return self._wallets.get(get_currency(currency_code).code)

    def get_total_value(self, base_currency: str = "USD") -> float:
        """Оценить ненулевые остатки по свежим курсам в выбранной базе."""
        from valutatrade_hub.core.rates import RateService

        base = get_currency(base_currency).code
        provider = self._rate_provider or RateService().get_rate
        total = Decimal(0)
        for code, wallet in self._wallets.items():
            if wallet.balance:
                total += number(wallet.balance) * number(provider(code, base).rate)
        return float(number(total, positive=False, label="total"))

    def to_dict(self) -> dict:
        """Сериализовать портфель и все кошельки."""
        return {
            "user_id": self.user_id,
            "wallets": {c: w.to_dict() for c, w in self._wallets.items()},
        }

    @classmethod
    def from_dict(cls, record: dict, user: User, rate_provider=None):
        """Восстановить портфель, проверив принадлежность и остатки."""
        if record["user_id"] != user.user_id or not isinstance(record["wallets"], dict):
            raise ValidationError("Некорректный владелец или структура портфеля")
        wallets = {}
        for code, data in record["wallets"].items():
            if data.get("currency_code", code) != code:
                raise ValidationError("Несогласованный код кошелька")
            wallets[code] = Wallet(code, data["balance"])
        return cls(user, wallets, rate_provider)
