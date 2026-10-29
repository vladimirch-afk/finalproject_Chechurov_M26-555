"""Декоратор структурированного логирования без записи паролей."""

import inspect
import logging
import time
from functools import wraps


def log_action(action: str, *, verbose: bool = False):
    """Логировать результат; исключения после записи пробрасываются дальше."""

    def decorate(function):
        signature = inspect.signature(function)

        @wraps(function)
        def wrapper(*args, **kwargs):
            bound = signature.bind(*args, **kwargs)
            bound.apply_defaults()
            service = bound.arguments.get("self")
            user = getattr(service, "current_user", None)
            attempted_username = bound.arguments.get("username")
            event = {
                "action": action,
                "user_id": user.user_id
                if user and attempted_username is None
                else None,
                "username": attempted_username
                if attempted_username is not None
                else (user.username if user else None),
            }
            for name in ("currency_code", "amount"):
                if name in bound.arguments:
                    event[name] = str(bound.arguments[name])
            logger = logging.getLogger("valutatrade.actions")
            started = time.perf_counter()
            try:
                result = function(*args, **kwargs)
            except Exception as error:
                event.update(
                    result="ERROR",
                    error_type=type(error).__name__,
                    error_message=str(error),
                )
                logger.info(action, extra={"event": event})
                raise
            if isinstance(result, dict):
                for name in ("rate", "base", "user_id", "username"):
                    if name in result:
                        event[name] = result[name]
                if verbose:
                    event["changes"] = result.get("changes", {})
            event.update(
                result="OK",
                duration_ms=round((time.perf_counter() - started) * 1000, 3),
            )
            logger.info(action, extra={"event": event})
            return result

        return wrapper

    return decorate
