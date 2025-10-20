## PREPARE-COMMIT — 2025-10-20 19:06 (agent)
- branch: main
- files: app/cli.py, scripts/create_compliance_fixture.py, data/fixtures/compliance_fixture.db, tests/test_compliance_snapshot.py, README.md, .env.template, docs/implementation-plan.md
- summary: Added participant validation CLI, compliance snapshot tests, fixture generator, and documentation updates for MVP workflows.
- tests: make lint; make test; python -m app.cli validate-participants; python -m app.cli send-daily --dry-run
- next: human → review changes, commit, and plan next iteration
