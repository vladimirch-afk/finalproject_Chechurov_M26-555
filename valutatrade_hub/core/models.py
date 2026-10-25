"""Модель пользователя и безопасная сериализация учётных данных."""

import hashlib
import hmac
import re
import secrets
from datetime import UTC, datetime

from valutatrade_hub.core.exceptions import ValidationError
from valutatrade_hub.core.utils import iso_utc, parse_time, utc_now


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
