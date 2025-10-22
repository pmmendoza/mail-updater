## COMMITTED — 2025-10-22 11:30 (agent)
- commit: f17d7e4
- files: Makefile, README.md, docs/operations.md, docs/qualtrics_sync.md, tests/test_qualtrics_sync.py
- summary: Added a `make sync-participants` helper and tightened Qualtrics CSV/quarantine tests while documenting the new entry point for operators.
- tests: make lint; make test

## PREPARE-COMMIT — 2025-10-22 11:16 (agent)
- branch: feat/mail-db-daily-engagement-20251022
- files: app/compliance_snapshot.py, scripts/create_compliance_fixture.py, data/fixtures/compliance_fixture.db, tests/test_compliance_snapshot.py, README.md, docs/operations.md, docs/monitoring.md, docs/qualtrics_sync.md
- summary: Added daily engagement breakdown helper with fixture/test coverage, refreshed Qualtrics/operations docs, and shifted quickstart + fixtures to the Make-based workflow.
- tests: make lint; make test; python -m app.cli migrate-mail-db; python -m app.cli participant import-csv; python -m app.cli aggregate; python -m app.cli send-daily --dry-run; python -m app.cli status --limit 10; python -m app.cli validate-participants
- next: human → review bundle, commit, and push

## PREPARE-COMMIT — 2025-10-20 19:06 (agent)
- branch: main
- files: app/cli.py, scripts/create_compliance_fixture.py, data/fixtures/compliance_fixture.db, tests/test_compliance_snapshot.py, README.md, .env.template, docs/implementation-plan.md
- summary: Added participant validation CLI, compliance snapshot tests, fixture generator, and documentation updates for MVP workflows.
- tests: make lint; make test; python -m app.cli validate-participants; python -m app.cli send-daily --dry-run
- next: human → review changes, commit, and plan next iteration

## COMMITTED — 2025-10-21 19:36 (agent)
- commit: f372ee5
- files: app/cli.py, app/config.py, app/email_renderer.py, app/bounce_scanner.py, app/mail_db/operations.py, app/participants.py, app/templates/email/daily_progress*.j2, docs/operations.md, docs/email_templates.md, docs/mail_db_schema.md, README.md, CHANGELOG.md, tests/test_cli_status.py, tests/test_bounce_scanner.py, tests/test_email_renderer.py, tests/test_participants.py
- summary: Added status CLI and bounce scanner, refreshed mail.db helpers, introduced non-compliance email variant, and made participants loader prefer mail.db with supporting docs/tests.
- tests: make lint; make test

## PREPARE-COMMIT — 2025-10-21 19:48 (agent)
- branch: main
- files: app/cli.py, app/participants.py, README.md, docs/operations.md, tests/test_cli_participant.py, tests/test_participants.py
- summary: Added `participant import-csv` command and made all CLI commands read participants from mail.db with CSV fallback; docs/tests updated accordingly.
- tests: make lint; make test
- next: human → review changes, commit, push
