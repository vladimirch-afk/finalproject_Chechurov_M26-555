"""Доменные ошибки, безопасные для отображения пользователю."""


class ValutaTradeError(Exception):
    """Базовая ожидаемая ошибка приложения."""


class ValidationError(ValutaTradeError, ValueError):
    """Некорректный пользовательский ввод."""


class AuthenticationError(ValutaTradeError):
    """Ошибка входа или отсутствие активной сессии."""


class StorageError(ValutaTradeError):
    """Ошибка конфигурации, чтения или сохранения данных."""


class CurrencyNotFoundError(ValutaTradeError):
    """В реестре отсутствует запрошенная валюта."""

    def __init__(self, code: str):
        self.code = code
        super().__init__(f"Неизвестная валюта '{code}'")


class InsufficientFundsError(ValutaTradeError):
    """Списание превышает доступный баланс."""

    def __init__(self, available, required, code: str):
        self.available, self.required, self.code = available, required, code
        super().__init__(
            f"Недостаточно средств: доступно {available} {code}, "
            f"требуется {required} {code}"
        )


class ApiRequestError(ValutaTradeError):
    """Сбой внешнего источника или отсутствие свежего курса."""

    def __init__(self, reason: str):
        super().__init__(f"Ошибка при обращении к внешнему API: {reason}")
