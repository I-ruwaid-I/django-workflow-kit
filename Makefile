.PHONY: help install test lint format typecheck build docs dev

PYTHON ?= python

help: ## Show available targets
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  %-12s %s\n", $$1, $$2}'

install: ## Install the package with development extras
	$(PYTHON) -m pip install -e ".[dev]"

test: ## Run the test suite
	$(PYTHON) -m pytest

coverage: ## Run tests with coverage report
	$(PYTHON) -m coverage run -m pytest
	$(PYTHON) -m coverage report

lint: ## Lint and check formatting
	$(PYTHON) -m ruff check .
	$(PYTHON) -m ruff format --check .

format: ## Format code with Ruff
	$(PYTHON) -m ruff format .
	$(PYTHON) -m ruff check --fix .

typecheck: ## Run the MyPy type checker
	$(PYTHON) -m mypy workflow_kit

build: ## Build distribution packages
	$(PYTHON) -m build

migrate: ## Create migrations for the test project
	$(PYTHON) tests/test_project/manage.py makemigrations

pre-commit: ## Install pre-commit hooks
	pre-commit install