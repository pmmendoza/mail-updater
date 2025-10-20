# Mail Updater — Next Iteration Roadmap

This roadmap builds on the MVP and guides the next development cycle toward a production-ready daily mail pipeline. Each sprint is scoped to deliver tangible improvements while keeping the system deployable between releases.

## Sprint 1 — Persistence & Auditability
- Introduce a lightweight SQLite database (`mail.db`) with migrations to persist participants, daily compliance snapshots, and email outbox records.
- Implement upsert logic in the CLI to refresh participant entries from CSV while preserving per-user overrides (e.g., include flags, language tweaks).
- Record every send attempt in the outbox table with status, timestamps, and rendered payload metadata to enable replay and audit trails.
- Add automated tests covering migration application and send logging.

## Sprint 2 — Shared Compliance Logic
- Create a shared aggregation module (`compliance_tracker/analytics.py` or similar) that encapsulates 14-day window math and active-day determination.
- Refactor the MVP snapshot step in mail-updater to call the shared helper and remove duplicate SQL queries.
- Document the API of the new module for reuse by other tooling (R scripts, dashboards).
- Add regression tests comparing analytics outputs against known fixtures to guard future schema or rule changes.

## Sprint 3 — Email Delivery Hardening
- Replace the MVP dry-run-only sender with configurable SMTP delivery, keeping the dry-run option.
- Add support for threading headers (`Message-ID`, `In-Reply-To`) stored per participant to maintain conversation continuity.
- Implement exponential backoff and retry handling for transient SMTP failures; surface final status in CLI output and outbox records.
- Extend templates to allow per-language variants; prepare Babel extraction workflow even if translations arrive later.

## Sprint 4 — Monitoring & Operations
- Introduce structured logging (JSON or key=value) for CLI commands to ease cron/launchd monitoring.
- Provide a `status` CLI command that summarizes latest send outcomes, suppression counts, and data freshness.
- Package sample cron and launchd configurations referencing the new commands, including log rotation guidance.
- Draft operational runbook sections in the README covering routine tasks and recovery scenarios (replays, participant corrections).

## Sprint 5 — Bounce Handling & Suppression
- Implement IMAP polling for bounce folders, parsing DSNs to identify failing recipient addresses.
- Automatically flip `include_in_emails` (or suppression flag) in the participant table when a hard bounce is detected.
- Record bounce events in the outbox log and expose them in the status command/dashboard (if present).
- Add end-to-end tests or scripted simulations for bounce handling to confirm suppression behaviour.

## Deferred / Optional Enhancements
- Flask-based dashboard for manual previews and send triggers.
- Multilingual content with Babel translations and locale-aware formatting.
- Integration with payout link tracking once token issuance workflow is ready.
