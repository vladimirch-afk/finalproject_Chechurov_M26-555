UV ?= uv

.PHONY: help install run project lint format check test build clean demo scheduler

help:
	@echo "install — установить пакет и зависимости разработки"
	@echo "run / project — запустить CLI"
	@echo "lint — проверить Ruff; format — отформатировать код"
	@echo "check — проверить lock-файл, стиль, форматирование и тесты"
	@echo "build — собрать wheel и sdist; clean — удалить результаты сборки и кэш Ruff"
	@echo "test — выполнить тесты; demo — записать демо; scheduler — обновлять каждые 5 минут"

install:
	$(UV) sync --locked

run:
	$(UV) run --locked valutatrade

project: run

lint:
	$(UV) run --locked ruff check .

format:
	$(UV) run --locked ruff format .

check:
	$(UV) lock --check
	$(UV) run --locked ruff check .
	$(UV) run --locked ruff format --check .
	$(MAKE) test

test:
	$(UV) run --locked python -m unittest discover -s tests -v

demo:
	$(UV) run --locked python scripts/demo.py

scheduler:
	$(UV) run --locked python -m valutatrade_hub.parser_service.scheduler

build:
	$(UV) build

clean:
	rm -rf dist/ build/ .ruff_cache/
