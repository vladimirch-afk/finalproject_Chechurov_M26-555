UV ?= uv

.PHONY: help install run project lint format check build clean

help:
	@echo "install — установить пакет и зависимости разработки"
	@echo "run / project — запустить CLI"
	@echo "lint — проверить Ruff; format — отформатировать код"
	@echo "check — проверить lock-файл, стиль и форматирование"
	@echo "build — собрать wheel и sdist; clean — удалить результаты сборки и кэш Ruff"

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

build:
	$(UV) build

clean:
	rm -rf dist/ build/ .ruff_cache/
