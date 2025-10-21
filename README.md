# NEWSFLOWS Mail Updater (MVP)

This directory contains a minimal, working example of the mail updater pipeline. It calculates participant progress from the Bluesky compliance database and generates individualized daily emails. The implementation is deliberately lean so we can iterate toward the full project brief.

## Quickstart

1. **Install dependencies**
   ```bash
   cd mail-updater
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install -r requirements.txt
   ```
2. **Create configuration**
   ```bash
   cp .env.template .env
   # edit .env with your Greenhost SMTP credentials or leave SMTP_DRY_RUN=true
   python scripts/create_compliance_fixture.py  # optional sample database
   # set COMPLIANCE_DB_PATH=data/fixtures/compliance_fixture.db for local testing
   # set PARTICIPANTS_CSV_PATH=data/participants.csv to use the bundled roster sample
   ```
3. **Prepare participant data**
   - Create `data/participants.csv` (relative to the repository root) with columns:
     `email,did,status,type`.
   - Seed a row for the study admin (see `data/participants.csv` for an example).
   - Optionally run `python -m app.cli sync-participants` to pull the latest roster
     from Qualtrics once credentials are in place.
4. **Run the CLI**
   ```bash
   python -m app.cli aggregate            # show per-participant status
   python -m app.cli preview --user-did did:example:123
   python -m app.cli send-daily --dry-run # writes .eml files to outbox/
   python -m app.cli validate-participants # confirm roster entries have data
   ```

### Local smoke test with bundled fixtures

Generate the sample compliance database and exercise the CLI without touching
production assets:

```bash
python scripts/create_compliance_fixture.py
COMPLIANCE_DB_PATH=data/fixtures/compliance_fixture.db \
PARTICIPANTS_CSV_PATH=data/participants.csv \
python -m app.cli validate-participants

COMPLIANCE_DB_PATH=data/fixtures/compliance_fixture.db \
PARTICIPANTS_CSV_PATH=data/participants.csv \
python -m app.cli send-daily --dry-run
```

These commands should report zero duplicates, confirm all participants have
activity, and emit a dry-run email under `outbox/`.

## Project layout

- `app/config.py` — loads settings from `.env` and provides defaults.
- `app/compliance_snapshot.py` — computes 14-day study window metrics per participant.
- `app/participants.py` — CSV loader for participant contact details.
- `app/qualtrics_sync.py` — Qualtrics API client and roster synchronisation helpers.
- `app/email_renderer.py` — renders Jinja templates into text/HTML content.
- `app/mailer.py` — handles dry-run output and SMTP delivery (when enabled).
- `app/cli.py` — Click commands for aggregation, preview, and sending.
- `app/templates/email/` — plain text and HTML email templates.
- `scripts/mvp_check.sh` — quick smoke test (aggregate + dry-run send).
- `participants-updater.R` — legacy tidyverse helper (kept as reference only).
- `docs/architecture.md` — detailed architecture notes with mermaid diagram of data flow.

### Qualtrics participant sync

The project includes a lightweight Qualtrics integration that calls the v3 REST
API directly. Set the following environment variables in `.env`:

```
QUALTRICS_BASE_URL=vuamsterdam.eu.qualtrics.com
QUALTRICS_API_TOKEN=<your token>
QUALTRICS_SURVEY_FILTER=NEWSFLOWS_pretreat_v1.0   # optional regex
```

Then run the CLI entry point:

```bash
python -m app.cli sync-participants
```

The command talks directly to the Qualtrics export endpoints, merges responses
from matching surveys, keeps existing participant metadata when available, and
validates that the resulting file matches the `email,did,status,type` schema used
throughout the pipeline.

## Testing

Run the quality gates from the repository root:

```bash
make lint   # ruff + mypy + black
make test   # pytest suite
```

The tests exercise the compliance snapshot logic, participant CSV invariants, and
the Qualtrics API client (with HTTP interactions mocked in unit tests).

## Next steps

- Migrate participant/contact state into `mail.db` for persistence.
- Share compliance aggregation helpers with the `compliance-tracker` project.
- Harden SMTP delivery (retries, threading headers) and add bounce suppression.
- Expand localization support once translations are ready.

Refer to `Next_Iteration_Sprints.md` for the detailed roadmap.
