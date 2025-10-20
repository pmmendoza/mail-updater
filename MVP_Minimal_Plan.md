# Minimal Mail Updater MVP Plan

## Objectives
- Deliver a repeatable script that generates participant progress summaries from `compliance.db` and emits a daily email (or `.eml` dry-run file) for each eligible participant.
- Validate the end-to-end path (data pull → compliance calculation → message render → send stub) so that we can iterate toward the full pipeline in the guideline.
- Keep the MVP lean while laying foundations (config structure, folder layout) that can evolve into the full-featured system.

## Assumptions & Constraints
- Python 3.11 is available; we can install Python deps locally but avoid touching system packages.
- `compliance.db` (or its replicas in `compliance-tracker`) remains the authoritative source for feed requests and engagements.
- Participant contact info can live in a lightweight CSV or SQLite table we control (`mail.db` or `data/participants.csv`).
- SMTP credentials may not be ready; MVP can support a dry-run mode that writes `.eml` files and logs to stdout.
- For the minimal example we can default to English messaging, with a plan to add Babel/i18n later.

## Dependencies & Integration Points
- Reuse `compliance-tracker/compliance_tracker/database.py` helpers to open the existing SQLite databases instead of duplicating connection logic.
- Consider adding a small aggregation helper to `compliance-tracker` (e.g., `compliance_tracker/analytics.py`) to produce the 14-day window metrics, so the mail-updater script calls a supported API rather than raw SQL.
- Share date boundary logic (05:00 local, 14-day rolling window) with the R script `src/get_engagement.R` or centralize in Python to keep rules consistent.

## Phase Plan
1. **Environment bootstrapping**
   - Create `mail-updater/README.md` documenting the MVP usage and config knobs (even if minimal).
   - Add `.env.example` (or reuse `.env.template`) with DB paths and SMTP dry-run flag.
   - Record required Python dependencies in `mail-updater/requirements.txt` (start with `SQLAlchemy`, `python-dateutil`, `pytz`, `jinja2`, `click`).
2. **Data access & aggregation**
   - Implement a Python module (e.g., `mail-updater/app/compliance_snapshot.py`) that:
     - Connects to `compliance.db`.
     - Calculates per-user daily metrics for the last 14 study days using the 05:00 cutoff.
     - Determines `active_day` (≥1 retrieval & ≥3 engagements) and on-track status.
   - Prefer delegating the SQL/logic to a helper inside `compliance_tracker` to keep business logic centralized; expose it as a function we can import.
   - Store or cache the resulting daily snapshots in memory for MVP (no write-back yet).
3. **Participant source**
   - Define a simple participants loader that reads `data/participants.csv` (columns: `user_did`, `email`, `language`, `include_in_emails`).
   - Provide a CLI command to validate participant rows against compliance data (warn on missing DID).
   - Optionally scaffold a minimal `mail.db` with just a `participants` table for the MVP if CSV proves too brittle.
4. **Email composition & delivery**
   - Create Jinja2 templates (`mail-updater/app/templates/email/daily_progress.{txt,html}.j2`) with English copy and placeholders for counts and on-track flag.
   - Build a composer function that maps snapshot data into template context and produces subject/body.
   - Implement a sender that supports:
     - Dry-run to write `.eml` files into `mail-updater/outbox/`.
     - Real send path using `smtplib` gated by config, but stubbed for MVP testing.
5. **Execution flow & CLI**
   - Develop a `click` CLI entry point (`mail-updater/app/cli.py`) with commands:
     - `aggregate` – run the snapshot computation and show summary stats.
     - `send-daily --dry-run` – load participants, fetch latest snapshot, render, and deliver via the configured channel.
     - `preview --user-did DID` – print a single email (text) for quick inspection.
   - Ensure commands exit cleanly and produce logs suitable for cron.
6. **Validation & observability**
   - Add unit tests (pytest) for the snapshot logic using in-memory SQLite fixtures.
   - Provide a smoke-test script (`scripts/mvp_check.sh`) that runs `aggregate` followed by a dry-run send for a test DID.
   - Log each send attempt to a CSV or JSONL for traceability until `email_outbox` is implemented.

## Deliverables & Exit Criteria
- Running `python -m app.cli send-daily --dry-run` produces email files for all `include_in_emails=1` participants with accurate progress numbers.
- Snapshot calculations match manual spot-checks against `compliance.db` for at least two users across edge cases (on-track, off-track).
- Configuration, templates, and CLI usage documented in `mail-updater/README.md`.

## Potential Deviations from Guideline
- Defer IMAP append and bounce-handling until after MVP validation.
- Limit copy to English during MVP; add Babel and translations in the follow-up iteration.
- Skip threading headers (`In-Reply-To`) for the very first version; ensure schema stores required IDs for future addition.

## Open Questions
- Should participant source of truth migrate to `mail.db` immediately, or is CSV acceptable for the pilot?
- Are there existing functions in `compliance_tracker` we must hook into for aggregation, or should we author a new shared helper?
- Do we have a sandbox SMTP account available for end-to-end testing, or should MVP rely entirely on dry-run `.eml` output?
- Is there a preferred naming/namespace convention for new shared modules between `mail-updater` and `compliance-tracker`?
