# NEWSFLOWS Mail Updater (MVP)

This directory contains a minimal, working example of the mail updater pipeline. It calculates participant progress from the Bluesky compliance database and generates individualized daily emails. The implementation is deliberately lean so we can iterate toward the full project brief.

## Quickstart

1. **Bootstrap the environment**
   ```bash
   cd mail-updater
   make setup
   source .venv/bin/activate
   ```
   `make setup` creates the virtualenv, installs Python dependencies, refreshes `.env` from the template, and scaffolds `user_config.yml` if it is missing. Re-run `make sync-env` whenever `.env.template` changes.
2. **Review configuration**
   ```bash
   # edit user_config.yml for non-secret settings (paths, mailer defaults, requirements)
   # edit .env for secrets (SMTP/IMAP passwords, Qualtrics token, etc.)
   python scripts/create_compliance_fixture.py  # optional sample database
   # set COMPLIANCE_DB_PATH=data/fixtures/compliance_fixture.db for local testing
   # set PARTICIPANTS_CSV_PATH=data/participants.csv to use the bundled roster sample
   ```
3. **Prepare participant data**
   - Create `data/participants.csv` (relative to the repository root) with columns:
     `email,did,status,type,feed_url`.
   - Seed a row for the study admin (see `data/participants.csv` for an example).
   - Once `mail.db` is populated (e.g., via the Qualtrics sync), CLI commands will
     automatically read participants from the database and use the CSV only as a
     fallback or export for manual edits.
   - To migrate an existing CSV roster into the database, run
     `python -m app.cli participant import-csv` (re-exports the canonical CSV
     afterwards).
   - Optionally run `python -m app.cli sync-participants` to pull the latest roster
     from Qualtrics once credentials are in place.
4. **Run the CLI**
   ```bash
   python -m app.cli aggregate            # show per-participant status
   python -m app.cli preview --user-did did:example:123
   python -m app.cli send-daily --dry-run # writes .eml files to outbox/
   python -m app.cli validate-participants # confirm roster entries have data
   python -m app.cli participant set-status --user-did did:example:123 --status inactive --reason "manual hold"
   python -m app.cli status --limit 10 --user-did did:example:123
   python -m app.cli bounces-scan --keep-unseen
   ```

The status command updates `mail.db` first and then re-exports `data/participants.csv` so older tooling stays in sync.

> For development workflows (linting/tests), install tooling with `make setup:dev` after the initial `make setup`.

### IMAP bounce handling

Add the following entries to `.env` to enable automated bounce suppression:

```
IMAP_HOST=imap.example.com
IMAP_PORT=993
IMAP_USERNAME=<imap user>
IMAP_PASSWORD=<imap password>
IMAP_MAILBOX=INBOX  # or the folder where DSNs land
IMAP_USE_SSL=true
```

Run `python -m app.cli bounces-scan` to poll the mailbox. The command extracts the bounced recipient, marks the latest send attempt as failed in `mail.db`, and flips the participant status to `inactive` so future sends are suppressed.

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
- `docs/qualtrics_sync.md` — roster sync field reference, manual run workflow, and quarantine procedures.
- `docs/monitoring.md` — guidelines for deriving metrics/alerts from `send_attempts` and bounce data.

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
# or
make sync-participants              # honours QUALTRICS_* env vars and optional SURVEY_FILTER
```

- Each run rewrites both `mail.db` (source of truth) and `data/participants.csv` (audit export). Any rows that fail validation are written to `../data/qualtrics_quarantine.csv` next to the repo’s `data/` folder; we intentionally keep the file so operators can inspect and fix the source survey data before re-running the sync.
- Field-to-column resolution is controlled by `qualtrics_field_mapping.csv`. Update that mapping if you rename survey questions (e.g., switching to `email_pilot`); the sync will try those keys first and fall back to heuristics.
- Provide explicit survey IDs via `user_config.yml` (`qualtrics.survey_ids`) or the CLI (`--survey-id`, repeatable) when working with multiple country-specific surveys. If no IDs are supplied, the optional `--survey-filter` (or YAML `survey_filter`) falls back to regex matching.

### Configuration reference

- Non-secret defaults live in `app/default_config.yml`; user-specific overrides belong in `user_config.yml`.
- Secrets (SMTP/IMAP passwords, Qualtrics API token, etc.) stay in `.env`.
- Requirements for compliance monitoring are defined under the `requirements` tree in the YAML config. Example:

  ```yml
  requirements:
    defaults:
      min_active_days: 10
      min_engagement: 3
      min_retrievals: 1
      max_skip_days: 4
      max_skip_span: 2
      day_cut_off: "05:00"
    main:
      survey_id: SV_6u0qynofAHvYSz4
    pilot:
      survey_id: SV_6u0qynofAHvYSz4
      min_active_days: 3
      max_skip_days: 0
      max_skip_span: 0
  ```

- The CLI merges `defaults` with the requested study label (`--study pilot`, etc.), enabling per-survey compliance thresholds.

The command talks directly to the Qualtrics export endpoints, merges responses
from matching surveys, upserts the roster into `mail.db` (preserving manual status
overrides), and rewrites `data/participants.csv` as a mirror of the database.
It validates that the resulting file matches the `email,did,status,type` schema
used throughout the pipeline.

## Testing

Run the quality gates from the repository root:

```bash
make lint   # ruff + mypy + black
make test   # pytest suite
```

The tests exercise the compliance snapshot logic, participant CSV invariants, and
the Qualtrics API client (with HTTP interactions mocked in unit tests).

## Database Setup

Initialise or upgrade the local `mail.db` schema before running features that
interact with the SQLite store:

```bash
python -m app.cli migrate-mail-db
```

The command respects the `MAIL_DB_PATH` environment variable (defaults to
`./mail.db/mail.sqlite`) and creates the parent directory if needed.

## Next steps

- Migrate participant/contact state into `mail.db` for persistence.
- Share compliance aggregation helpers with the `compliance-tracker` project.
- Harden SMTP delivery (retries, threading headers) and add bounce suppression.
- Expand localization support once translations are ready.

Refer to `Next_Iteration_Sprints.md` for the detailed roadmap.
