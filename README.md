# ValutaTrade Hub

Учебный проект `finalproject_Chechurov_M26-555`: консольное приложение для
виртуального валютного кошелька, учёта портфеля и симуляции торговли фиатными
валютами и криптовалютами. Исходники оформлены как устанавливаемый Python-пакет
`valutatrade_hub`; имя дистрибутива — `finalproject-chechurov-m26-555`
(нормализовано `uv`).

## Текущий этап

Выполнен этап **1. Подготовка**: окружение `uv`, зависимости, Ruff, Git,
сборка пакета, структура каталогов и минимальная интерактивная оболочка.
Доступны команды `help`, `version`, `exit` и `quit`, а также параметры запуска
`--help` и `--version`. Разбор строк оболочки выполняется через `shlex`.

Модули последующих этапов содержат docstrings с назначением. Классы `User`,
`Wallet`, `Portfolio`, торговые команды, синглтоны, логирование и Parser Service
пока не реализованы. JSON-файлы содержат пустые начальные данные.

## Окружение и установка

Нужны Python **3.13+**, Git и `uv`. Основная версия разработки закреплена в
`.python-version` как `3.13`. Активация окружения для `uv run` не требуется.

Если `uv` ещё не установлен, можно установить его в отдельное окружение
(пример для macOS/Linux, команды выполняются в корне проекта):

```bash
python3 -m venv .venv-uv
.venv-uv/bin/python -m pip install uv
export PATH="$PWD/.venv-uv/bin:$PATH"
```

Затем установите проект и зависимости:

```bash
uv --version
uv sync --locked
```

`uv sync` создаёт `.venv/` и устанавливает пакет в режиме разработки.
Зависимость приложения — `prettytable`, зависимость разработки — `ruff`.
`argparse`, `shlex`, `json` и `time` входят в стандартную библиотеку Python.
`uv.lock` хранится в Git для воспроизводимой установки.

В этой рабочей папке `uv` также подготовлен в `../../work/tools/bin/uv`.
Чтобы воспользоваться им без дополнительной установки, из корня проекта:

```bash
export PATH="$(cd ../../work/tools/bin && pwd):$PATH"
uv sync --locked
```

## Запуск

```bash
uv run --locked valutatrade
uv run --locked valutatrade --help
uv run --locked valutatrade --version
```

Альтернативные точки входа запускают ту же оболочку:

```bash
uv run --locked python main.py
uv run --locked python -m valutatrade_hub
```

Пример сеанса текущего этапа:

```text
valutatrade> help
valutatrade> version
ValutaTrade Hub 0.1.0
valutatrade> exit
До свидания!
```

## Структура

```text
finalproject_Chechurov_M26-555/
├── data/
│   ├── users.json
│   ├── portfolios.json
│   ├── rates.json
│   └── exchange_rates.json
├── valutatrade_hub/
│   ├── __init__.py
│   ├── __main__.py
│   ├── logging_config.py
│   ├── decorators.py
│   ├── core/
│   │   ├── __init__.py
│   │   ├── models.py
│   │   ├── usecases.py
│   │   ├── utils.py
│   │   ├── currencies.py
│   │   └── exceptions.py
│   ├── infra/
│   │   ├── __init__.py
│   │   ├── settings.py
│   │   └── database.py
│   ├── parser_service/
│   │   ├── __init__.py
│   │   ├── config.py
│   │   ├── api_clients.py
│   │   ├── updater.py
│   │   ├── storage.py
│   │   └── scheduler.py
│   └── cli/
│       ├── __init__.py
│       └── interface.py
├── main.py
├── Makefile
├── pyproject.toml
├── uv.lock
├── README.md
├── .python-version
├── .env.example
└── .gitignore
```

Используется плоская структура пакета из ТЗ. Для Hatchling явно указан
`valutatrade_hub`, поэтому имя каталога проекта не влияет на импорт.
CLI отвечает за ввод и вывод; будущая бизнес-логика размещается в `core`,
работа с JSON и настройками — в `infra`, внешние API — в `parser_service`.

## Качество кода и сборка

```bash
make install
make check
make build
make run
```

Можно выполнять команды напрямую:

```bash
uv lock --check
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ruff format .
uv build
```

Ruff настроен в `pyproject.toml`: Python 3.13, длина строки 88, проверки
PEP8, ошибок Python, импортов, типичных ошибок и современного синтаксиса.
`make help` показывает все цели. `make clean` удаляет `dist/`, `build/`
и `.ruff_cache/`.

Сборка создаёт wheel и исходный архив в `dist/`. Wheel содержит Python-пакет
и команду `valutatrade`; исходный архив дополнительно содержит начальные JSON,
Makefile, `main.py`, конфигурацию и lock-файл. В дальнейшей реализации
изменяемые пользовательские данные должны храниться вне установленного пакета.

Проверка wheel в отдельном окружении без установки в глобальный Python:

```bash
uv venv /tmp/valutatrade-wheel-check
uv pip install --python /tmp/valutatrade-wheel-check/bin/python dist/*.whl
/tmp/valutatrade-wheel-check/bin/valutatrade --version
```

## Git и рабочий процесс

Выбран GitHub Flow: стабильная ветка `main`, отдельная ветка для каждой задачи,
осмысленные коммиты после завершения подраздела. Локальный репозиторий уже
инициализирован; удалённый репозиторий можно подключить позднее.

Пример работы над следующим этапом:

```bash
git switch -c feat/core-models
# Реализуйте модели, затем выполните проверки.
make check
git add valutatrade_hub/core/models.py
git commit -m "feat: implement user wallet and portfolio models"
```

После проверки изменений ветку объединяют с `main`, через pull request при
наличии удалённого репозитория. `.gitignore` исключает окружения, результаты
сборки, кэши, логи и локальные `.env`. Файл `uv.lock` отслеживается.

## Следующие этапы по ТЗ

1. **Core и CLI:** модели с валидацией, хеширование паролей с солью,
   регистрация, вход, портфель, покупка, продажа и получение курса.
2. **Инфраструктура:** иерархия валют, доменные исключения, SettingsLoader,
   DatabaseManager, логирование с ротацией и декоратор операций.
3. **Parser Service:** клиенты API, обновление кэша и истории, атомарная запись,
   команды `update-rates` и `show-rates`.
4. **Демонстрация:** полный торговый сценарий и обработка ошибок.

Для будущего Parser Service предусмотрен `.env.example` с
`EXCHANGERATE_API_KEY`. Автоматическая загрузка `.env` пока отсутствует;
реализация будет получать ключ из переменных окружения.
`data/rates.json` подготовлен в итоговом формате `pairs` / `last_refresh`,
`data/exchange_rates.json` — как список исторических записей.
TTL курсов (ориентир из ТЗ — 300 секунд) будет задаваться в SettingsLoader.
