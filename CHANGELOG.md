## PREPARE-COMMIT — 2025-10-20 19:06 (agent)
- branch: main
- files: app/cli.py, scripts/create_compliance_fixture.py, data/fixtures/compliance_fixture.db, tests/test_compliance_snapshot.py, README.md, .env.template, docs/implementation-plan.md
- summary: Added participant validation CLI, compliance snapshot tests, fixture generator, and documentation updates for MVP workflows.
- tests: make lint; make test; python -m app.cli validate-participants; python -m app.cli send-daily --dry-run
- next: human → review changes, commit, and plan next iteration

## PREPARE-COMMIT — 2025-10-21 14:30 (agent)
- branch: main
- files: app/cli.py, app/config.py, app/email_renderer.py, app/bounce_scanner.py, app/mail_db/operations.py, app/templates/email/daily_progress*.j2, docs/operations.md, docs/email_templates.md, docs/mail_db_schema.md, README.md, tests/test_cli_status.py, tests/test_bounce_scanner.py, tests/test_email_renderer.py
- summary: Added status CLI and bounce scanner, refreshed mail.db helpers, introduced non-compliance email variant, and updated docs/tests to support the new workflows.
- tests: make lint; make test
- next: human → review diff, commit locally, and push or open PR
