SHELL := /bin/bash

VENV_DIR := .venv
PYTHON := $(VENV_DIR)/bin/python
REQUIREMENTS_STAMP := $(VENV_DIR)/.requirements.stamp

.PHONY: setup sync-env lint test

setup: $(REQUIREMENTS_STAMP)
	@python3 scripts/sync_env.py
	@echo "Virtual environment ready."
	@echo "Activate it with: source $(VENV_DIR)/bin/activate"

sync-env:
	@python3 scripts/sync_env.py

$(PYTHON):
	python3 -m venv $(VENV_DIR)

$(REQUIREMENTS_STAMP): requirements.txt $(PYTHON)
	@echo "Installing Python dependencies..."
	@source $(VENV_DIR)/bin/activate && \
		pip install --upgrade pip && \
		pip install --disable-pip-version-check --requirement requirements.txt && \
		touch $(REQUIREMENTS_STAMP)

lint: $(REQUIREMENTS_STAMP)
	$(VENV_DIR)/bin/ruff check app tests scripts
	$(VENV_DIR)/bin/mypy app
	$(VENV_DIR)/bin/black --check app tests scripts

test: $(REQUIREMENTS_STAMP)
	$(VENV_DIR)/bin/pytest
