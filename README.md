# ValutaTrade Hub

`finalproject_Chechurov_M26-555` — учебное консольное приложение для виртуального
валютного кошелька. Реализованы все этапы ТЗ: модели, торговые сценарии, CLI,
JSON-хранилища, иерархия валют, исключения, синглтоны, логирование и Parser Service.
Приложение симулирует сделки; операции используют виртуальные средства.

Импортируемый пакет — `valutatrade_hub`, дистрибутив —
`finalproject-chechurov-m26-555` (имя нормализовано `uv`).

## Установка

Требования: Python **3.13+**, `uv`, Git. Поддерживаемая платформа — macOS/Linux:
для разбора команд используется `shlex`, для блокировок файлов — `fcntl`.

Склонируйте репозиторий и установите пакет:

```bash
git clone https://github.com/vladimirch-afk/finalproject_Chechurov_M26-555.git
cd finalproject_Chechurov_M26-555
uv sync --locked
uv run --locked valutatrade
```

Если `uv` не установлен, его можно подготовить в отдельном окружении:

```bash
python3 -m venv .venv-uv
.venv-uv/bin/python -m pip install uv
export PATH="$PWD/.venv-uv/bin:$PATH"
uv sync --locked
```

Зависимости приложения: `prettytable`, `requests`. Зависимость разработки: `ruff`.
Версии зафиксированы в `uv.lock`. Активация `.venv` для `uv run` не нужна.

Альтернативные способы запуска:

```bash
uv run --locked python main.py
uv run --locked python -m valutatrade_hub
uv run --locked valutatrade --help
uv run --locked valutatrade --version
```

## Быстрый сценарий

Без аргументов открывается интерактивная оболочка. Последовательно введите:

```text
register --username alice --password demo-pass
login --username alice --password demo-pass
show-portfolio
deposit --amount 10000
update-rates --source coingecko
buy --currency BTC --amount 0.001
sell --currency BTC --amount 0.0005
show-portfolio
get-rate --from USD --to BTC
history
exit
```

Команды `register` и `login` без `--password` запрашивают пароль скрыто, если ввод
идёт из терминала. Пароли в примерах учебные. CLI понимает имена в кавычках:
`register --username "Alice Example"`. `help buy` показывает параметры команды.
Ошибочные команды не закрывают интерактивную оболочку.

Регистрация создаёт **пустой портфель**. `deposit` пополняет виртуальный USD-счёт.
Покупка списывает `amount × rate` USD и зачисляет `amount` покупаемой валюты;
продажа списывает валюту и зачисляет выручку в USD. `amount` — количество валюты,
а не её стоимость. USD служит расчётной валютой, его пополняют через `deposit`.
Комиссий и внешних платёжных операций нет.

Сессия хранится в памяти одного процесса. Пользователи, портфели и история
сохраняются между запусками, но вход нужно выполнить заново. Однократный запуск
подходит для публичных команд, например:

```bash
uv run --locked valutatrade update-rates --source coingecko
uv run --locked valutatrade show-rates --top 2
```

## Команды

| Команда | Аргументы | Вход |
| --- | --- | --- |
| `register` | `--username`, необязательный `--password` | нет |
| `login` | `--username`, необязательный `--password` | нет |
| `logout` | — | нет |
| `change-password` | необязательный `--new-password` | да |
| `deposit` | `--amount` в USD | да |
| `show-portfolio` | необязательный `--base`, по умолчанию USD | да |
| `buy` / `sell` | `--currency`, `--amount` | да |
| `get-rate` | `--from`, `--to` | нет |
| `update-rates` | необязательный `--source coingecko\|exchangerate` | нет |
| `show-rates` | необязательные `--currency`, `--top`, `--base` | нет |
| `history` | необязательный `--limit`, по умолчанию 20 | да |
| `currencies` | — | нет |
| `help` | необязательное имя команды | нет |
| `version`, `exit`, `quit` | — | нет |

Поддерживаются USD, EUR, GBP, RUB, BTC, ETH, SOL. Коды нормализуются в верхний
регистр, допустимы 2–5 латинских букв. Суммы должны быть положительными конечными
числами; `NaN`, `Infinity`, `bool`, строки и отрицательные значения отклоняются.
Арифметика балансов выполняется через `Decimal`, JSON хранит числовые остатки
в формате ТЗ. Это учебная модель без требований банковского бухгалтерского учёта.

`show-rates --top N` выводит N самых дорогих **криптовалют**, сортируя их по цене
в выбранной базе. `show-rates` читает кэш без обращения к сети и помечает
устаревшие строки. `get-rate` и оценка портфеля используют свежие прямые,
обратные и кросс-курсы; курс валюты к самой себе равен 1.

Примеры ошибок:

```text
Сначала выполните login
Пароль должен быть не короче 4 символов
Недостаточно средств: доступно 0.04 BTC, требуется 1.0 BTC
Неизвестная валюта 'ABC'. Список валют: currencies; справка: help get-rate
```

## Parser Service и ключи

CoinGecko получает цены по ID `bitcoin`, `ethereum`, `solana`. Публичный запрос
может требовать ключ или ограничиваться провайдером; при наличии Demo API-ключа
задайте `COINGECKO_API_KEY` — клиент передаёт его в заголовке.
Для ExchangeRate-API нужен собственный ключ:

```bash
export EXCHANGERATE_API_KEY='ваш-ключ'
# При необходимости:
export COINGECKO_API_KEY='ваш-demo-ключ'
uv run --locked valutatrade
```

Ключи читаются из окружения при создании `ParserConfig`. `.env.example` — шаблон;
файл `.env` сам по себе **не загружается**, значения нужно экспортировать.
Настоящие ключи в Git не добавляются. Тексты сетевых ошибок не содержат URL,
в котором ExchangeRate-API передаёт ключ.

Внутри интерактивной сессии:

```text
update-rates
update-rates --source coingecko
update-rates --source exchangerate
show-rates --currency RUB
show-rates --top 2
show-rates --base EUR
```

`BaseApiClient.fetch_rates()` возвращает `{FROM_TO: rate}`. Клиенты проверяют
HTTP-статус, JSON, наличие цен и положительные конечные значения; таймаут —
10 секунд. В реальном ExchangeRate-API используется поле `conversion_rates`,
поддерживается также `rates` из примера ТЗ. Котировки источника USD→EUR
инвертируются в EUR→USD. Успешный HTTP-ответ не маскирует ошибку API в JSON.

Если один источник упал, другой продолжает обновляться. Результат содержит
количество обновлённых пар и список ошибок. При полном сбое старые данные
сохраняются; ошибка отображается пользователю. В однократном CLI код 0 означает
успех, 1 — ожидаемую ошибку или частичное обновление; Ctrl+C возвращает 130.

Для отдельного процесса периодического обновления:

```bash
uv run --locked python -m valutatrade_hub.parser_service.scheduler --interval 300
# Только криптовалюты:
uv run --locked python -m valutatrade_hub.parser_service.scheduler --source coingecko
```

Планировщик работает на переднем плане до Ctrl+C. Сетевой сбой не останавливает
следующую итерацию. Автозапуск в системе и публикация данных не выполняются.

Официальные контракты API:
[CoinGecko Simple Price](https://docs.coingecko.com/reference/simple-price),
[ExchangeRate-API Standard Requests](https://www.exchangerate-api.com/docs/standard-requests).

## Конфигурация и данные

`SettingsLoader` и `DatabaseManager` — синглтоны через `__new__` с блокировкой.
Настройки находятся в `[tool.valutatrade]` файла `pyproject.toml`:

```toml
[tool.valutatrade]
data_dir = "data"
log_dir = "logs"
rates_ttl_seconds = 300
default_base_currency = "USD"
log_level = "INFO"
```

Относительные пути отсчитываются от файла конфигурации. В установленном wheel,
где рядом нет `pyproject.toml`, используются значения по умолчанию относительно
текущего каталога. Необходимые JSON создаются при первой операции с хранилищем.
Для независимых экземпляров приложения укажите собственные каталоги:

```bash
export VALUTATRADE_DATA_DIR='/absolute/path/to/data'
export VALUTATRADE_LOG_DIR='/absolute/path/to/logs'
export VALUTATRADE_RATES_TTL=300
# Для явного файла конфигурации:
export VALUTATRADE_CONFIG='/absolute/path/to/pyproject.toml'
```

Секреты и пользовательские данные не записываются внутрь установленного пакета.

| Файл | Содержимое |
| --- | --- |
| `users.json` | id, имя, SHA-256 от пароля с солью, соль, ISO-дата регистрации |
| `portfolios.json` | портфель и кошельки каждого пользователя |
| `transactions.json` | журнал пополнений, покупок и продаж с остатками до/после |
| `rates.json` | `pairs` с rate/updated_at/source, общий `last_refresh` |
| `exchange_rates.json` | история измерений с уникальным id, временем и meta |

SHA-256 с солью реализован в соответствии с учебным ТЗ. `get_user_info()`
не возвращает хеш и соль, сравнение хешей выполняется через `hmac.compare_digest`.
При изменении пароля генерируется новая случайная соль.

Время в файлах и журналах — UTC. TTL считается от времени успешного получения
измерения, а не от времени запуска приложения. Время обновления у поставщика,
если оно доступно, записывается отдельно в `meta.provider_updated_at`.
Свежесть кросс-курса ограничивается самым старым из участвующих измерений.
При устаревшем или отсутствующем курсе Core один раз пытается обновить источники;
если свежего курса всё ещё нет, операция отклоняется с предложением `update-rates`.
Прошедшее TTL значение не используется для сделки.

Кэш чтения реализован **замыканием**. Атомарная замена файла инвалидирует его
по inode/mtime/size; TTL котировки проверяется независимо от кэша чтения.

`RatesStorage` обновляет пару только более новым `updated_at`, сохраняет другие
пары при частичном обновлении и дедуплицирует историю по паре и UTC-времени.
Пользовательские операции и обновления курсов защищены общей файловой блокировкой.
JSON записывается через временный файл, `fsync` и `os.replace`. Для нескольких
файлов сначала записывается журнал `.transaction.json`; после прерывания он
доигрывается перед следующим чтением. Операция с уже сохранённым журналом может
завершиться при восстановлении после сбоя. Повреждённые JSON не затираются пустыми.
Это локальное файловое хранилище для учебного приложения, не распределённая БД.

## Логирование

`logs/actions.log` и `logs/parser.log` используют JSON Lines, уровень INFO.
Ротация: 1 MiB на файл, 3 резервных копии. Повторная настройка не добавляет
дублирующиеся обработчики. Настройка DEBUG выполняется в `pyproject.toml`.

`@log_action` применяется к регистрации, входу, пополнению, покупке и продаже.
Записываются время, действие, пользователь, валюта, сумма, курс и база при наличии,
результат OK/ERROR, тип и текст ошибки. `verbose=True` добавляет остатки до/после.
Исключения после логирования пробрасываются в CLI. Пароли и полные аргументы
вызовов в журнал не попадают.

## Структура

```text
finalproject_Chechurov_M26-555/
├── data/                     # users, portfolios, rates, exchange_rates, transactions
├── valutatrade_hub/
│   ├── __init__.py
│   ├── __main__.py
│   ├── decorators.py
│   ├── logging_config.py
│   ├── core/
│   │   ├── models.py          # User, Wallet, Portfolio
│   │   ├── currencies.py      # Currency, FiatCurrency, CryptoCurrency, реестр
│   │   ├── exceptions.py
│   │   ├── rates.py           # TTL и конвертация
│   │   ├── usecases.py        # TradingService
│   │   └── utils.py           # валидация, UTC, замыкание кэша
│   ├── infra/
│   │   ├── settings.py        # SettingsLoader
│   │   └── database.py        # DatabaseManager, блокировки, JSON
│   ├── parser_service/
│   │   ├── config.py
│   │   ├── api_clients.py
│   │   ├── updater.py
│   │   ├── storage.py
│   │   └── scheduler.py
│   └── cli/interface.py       # аргументы и отображение
├── tests/                    # unittest, без запросов к внешним API
├── scripts/demo.py           # воспроизводимая запись CLI
├── demo/session.cast          # asciinema v2
├── demo/session.txt           # расшифровка
├── main.py
├── Makefile
├── pyproject.toml
├── uv.lock
├── .python-version
├── .env.example
└── .gitignore
```

В каждой директории Python-пакета есть `__init__.py`. CLI вызывает сценарии
Core; хранение и получение курсов отделены от ввода/вывода и моделей.

## Проверки, сборка и демо

```bash
make install
make check
make build
make demo
```

`make check` проверяет актуальность lock-файла, Ruff, форматирование и запускает
`unittest`. Покрываются модели, сессии, сохранение, сделки, TTL, кросс-курсы,
фильтры, ошибки API, частичный сбой, дедупликация, восстановление журнала,
параллельные операции потоков и процессов, отсутствие паролей в логах и CLI.
Внешние API в автоматических тестах заменены управляемыми ответами.

Отдельные команды:

```bash
uv run --locked python -m unittest discover -s tests -v
uv run --locked ruff check .
uv run --locked ruff format --check .
uv run --locked ruff format .
uv build
```

`make help` показывает цели, `make run` / `make project` запускает приложение,
`make clean` удаляет результаты сборки и кэш Ruff. В `dist/` создаются wheel
и исходный `.tar.gz`. В sdist включены данные, тесты, демо, README и lock-файл;
wheel содержит Python-пакет и команду `valutatrade`.

Проверка установки wheel вне режима разработки:

```bash
uv venv /tmp/valutatrade-wheel-check
uv pip install --python /tmp/valutatrade-wheel-check/bin/python dist/*.whl
cd /tmp
/tmp/valutatrade-wheel-check/bin/valutatrade --version
```

Демонстрация в `demo/session.cast` — готовая запись asciinema v2; её можно
воспроизвести установленным asciinema:

```bash
asciinema play demo/session.cast
```

Тот же вывод доступен в `demo/session.txt`. Чтобы записать заново:

```bash
make demo
```

Демо выполняет настоящий CLI, Core, JSON и HTTP-клиенты, но оба внешних API
заменены локальным HTTP-сервером с фиксированными учебными ценами. Регистрация,
вход, пополнение, buy/sell, портфель, get-rate, update-rates, show-rates,
история, недостаток средств, неизвестная валюта, NaN и частичный HTTP 429
показаны в одной записи. Пользовательские данные не меняются: используются
временные каталоги. Пример не выдаёт учебные цены за текущие рыночные.

## Git

Выбран GitHub Flow: `main` и отдельная ветка на задачу, осмысленные коммиты
по завершённым подразделам. Репозиторий:
[finalproject_Chechurov_M26-555](https://github.com/vladimirch-afk/finalproject_Chechurov_M26-555).
Сборки, окружения, кэши, логи и секреты исключены через `.gitignore`.

```bash
git switch -c feat/next-improvement
make check
git add путь/к/изменённому/файлу
git commit -m "feat: describe completed change"
```

Готовые изменения объединяются с `main` после проверки; при использовании
удалённого репозитория — через pull request.
