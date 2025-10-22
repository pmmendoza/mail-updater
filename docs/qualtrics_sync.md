# Qualtrics Participant Sync

_Last updated: 2025-10-21_

The Qualtrics roster sync is the canonical way to populate and maintain `mail.db.participants`.

## Fields
- `email` — participant contact address (required)
- `did` — decentralised identifier associated with the study (required)
- `status` — defaults to `active`; manual overrides in mail.db remain authoritative
- `type` — participant type (`pilot`, `prolific`, `admin`, `test`)
- `language` — optional language code (defaults to `en`)
- `feed_url` — **required**; identifies the feed assigned to the participant

Rows missing either DID, email, or `feed_url` are written to a quarantine CSV (see below).

## Running the sync

```
python -m app.cli sync-participants
# or run via Make (honours SURVEY_FILTER env/arg):
make sync-participants
```

- The command runs **manually** (no scheduled job yet).
- Qualtrics survey selection can be narrowed with `--survey-filter` (regex).
- Successful runs upsert into `mail.db`, then re-export `data/participants.csv` for audit.

## Quarantine handling
- Invalid or incomplete records are written to `data/qualtrics_quarantine.csv`.
- The CLI prints how many unique DIDs were quarantined and where the file lives.
- Fix the source data (or edit the CSV) and rerun the sync; quarantined rows are ignored until corrected.

## Troubleshooting
- Ensure `QUALTRICS_BASE_URL` and `QUALTRICS_API_TOKEN` are present in `.env`.
- On API errors, the CLI raises `QualtricsSyncError` with the Qualtrics response.
- If the quarantine file continues to populate, verify that the Qualtrics survey includes the `feed_url` field.
- Rosters remain available via `python -m app.cli participant import-csv` if manual fixes are needed.

## Manual roster edits
- Prefer manipulating participants through CLI helpers (`participant set-status`, `participant import-csv`).
- The CSV (`data/participants.csv`) is now a read-only audit export; mail.db stores the source of truth.
- After manual changes, rerun `validate-participants` before sending mail.

## Legacy R script parity notes
- The retired `participants-updater.R` script fetched the same Qualtrics surveys using `QUALTRICS_API_KEY`; the Python CLI expects `QUALTRICS_API_TOKEN` but otherwise mirrors the workflow.
- Fallback logic that synthesised Prolific email addresses (e.g., `<PROLIFIC_ID>@email.prolific.com`) and tagged those rows as `type="prolific"` now lives in `_rows_from_responses`.
- Manual roster overrides (status, admin type) still take precedence—`_merge_participants` keeps existing mail.db metadata unless a new participant is discovered.
- The Python flow adds a mandatory `feed_url` field; responses missing DID/email/feed URL are written to the quarantine CSV instead of being silently dropped.
- To regenerate the legacy CSV-only output, the CLI can run with `--survey-filter` and `mail_db_path` pointing at a temp SQLite file; it will produce the merged CSV while keeping the database in sync.
