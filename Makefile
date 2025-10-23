SHELL := /bin/bash

VENV_DIR := .venv
PYTHON := $(VENV_DIR)/bin/python
REQUIREMENTS_STAMP := $(VENV_DIR)/.requirements.stamp
DEV_REQUIREMENTS_STAMP := $(VENV_DIR)/.requirements-dev.stamp
USER_CONFIG := user_config.yml
DEFAULT_CONFIG := app/default_config.yml
PARTICIPANTS_CSV := data/participants.csv
PARTICIPANTS_HEADER := "email,did,status,type,feed_url,survey_completed_at,prolific_id,study_type,audit_timestamp"

.PHONY: setup setup\:dev sync-env lint test sync-participants

setup: $(REQUIREMENTS_STAMP) $(USER_CONFIG) $(PARTICIPANTS_CSV)
	@python3 scripts/sync_env.py
	@echo "Virtual environment ready."
	@echo "Activate it with: source $(VENV_DIR)/bin/activate"

setup\:dev: setup $(DEV_REQUIREMENTS_STAMP)

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

$(DEV_REQUIREMENTS_STAMP): requirements.dev.txt $(REQUIREMENTS_STAMP)
	@echo "Installing development dependencies..."
	@source $(VENV_DIR)/bin/activate && \
		pip install --disable-pip-version-check --requirement requirements.dev.txt && \
		touch $(DEV_REQUIREMENTS_STAMP)

$(USER_CONFIG):
	@if [ ! -f "$@" ]; then \
		cp $(DEFAULT_CONFIG) $@ && \
		echo "Created $@ from template. Please customise it before running the CLI."; \
	fi

$(PARTICIPANTS_CSV):
	@if [ ! -f "$@" ]; then \
		mkdir -p $(dir $@) && \
		printf '%s\n' $(PARTICIPANTS_HEADER) > $@ && \
		echo "Created $@ stub with header."; \
	fi

lint: $(DEV_REQUIREMENTS_STAMP)
	$(VENV_DIR)/bin/ruff check app tests scripts
	$(VENV_DIR)/bin/mypy app
	$(VENV_DIR)/bin/black --check app tests scripts

test: $(DEV_REQUIREMENTS_STAMP)
	$(VENV_DIR)/bin/pytest

SURVEY_FILTER ?=

ifdef SURVEY_FILTER
SYNC_SURVEY_FLAG := --survey-filter $(SURVEY_FILTER)
endif

sync-participants: $(REQUIREMENTS_STAMP)
	@if [ -z "$$QUALTRICS_BASE_URL" ] || [ -z "$$QUALTRICS_API_TOKEN" ]; then \
		echo "QUALTRICS_BASE_URL and QUALTRICS_API_TOKEN must be set before running this target."; \
		exit 1; \
	fi
	$(VENV_DIR)/bin/python -m app.cli sync-participants $(SYNC_SURVEY_FLAG)
