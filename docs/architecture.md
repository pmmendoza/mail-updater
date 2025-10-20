# Mail Updater Architecture Overview

_Last updated: 2025-10-20_

## 1. High-Level Components

```
+-------------------+
| Qualtrics Surveys |---(API export)--+
+-------------------+                  |
                                       v
                                +--------------+
                                | Qualtrics    |
                                | Sync (CLI)   |
                                +--------------+
                                      |
                     +----------------+----------------+
                     |                                 |
               participants.csv                 data/fixtures/
                     |                           compliance_fixture.db
                     v                                 |
+---------------------------+                 +------------------------+
| Mail Updater CLI (Click) |<---------------+ | Compliance Snapshot    |
|  - aggregate             |                 | Engine (SQLAlchemy)     |
|  - preview               |                 | - feed_requests         |
|  - send-daily            |                 | - engagements           |
|  - validate-participants |                 +------------------------+
+------------+--------------+
             |
             v
    +----------------+
    | SMTP Delivery  |
    |  - dry-run     |
    |  - live send   |
    +--------+-------+
             |
             v
    outbox/*.eml & send_log.jsonl
```

## 2. Data Flow

1. **Qualtrics Sync** fetches survey responses using the v3 API, normalises the roster, and writes `data/participants.csv`.
2. **Validation** (`validate-participants`) ensures every DID has recent activity in the compliance database and flags duplicates. Participants without recent activity will fall back to a "needs data" template (planned) so messaging can adapt to compliance status.
3. **Compliance Snapshot** queries SQLite (`COMPLIANCE_DB_PATH`) to calculate 14-day window metrics per DID.
4. **Email Rendering** uses Jinja templates to produce text/HTML bodies.

5. **Delivery Layer** runs in dry-run (writes `.eml`) or live mode (SMTP) and records results in JSONL.

## 3. Technology Choices

| Area | Choice | Notes |
|------|--------|-------|
| Language | Python 3.11 | Aligns with existing research tooling. |
| CLI | Click | Provides composable commands with clear help output. |
| Database Access | SQLAlchemy (core) | Lightweight wrapper around SQLite. |
| Templates | Jinja2 | Shared with other Newsflows tooling. |
| Lint/Test | Ruff, Black, MyPy, Pytest | Configured via Makefile targets. |
| Deployment (target) | Manual cron / local automation | Default workflow runs locally; GitHub Actions cron remains an optional reference implementation. |

## 4. Configuration & Secrets

- `.env` (local dev) stores paths and credentials; production will move secrets into a secure store (e.g., environment variables in CI).
- Critical keys: `SMTP_*`, `QUALTRICS_*`, `COMPLIANCE_DB_PATH`, `PARTICIPANTS_CSV_PATH`.

## 5. Extensibility Roadmap

- Replace CSV roster with SQLite/REST source to avoid manual edits and support activity upserts (add CLI command to toggle participant status).
- Introduce REST API or webhook triggers for ad-hoc sends (optional; local CLI remains primary workflow).
- Add metrics export (Prometheus/StatsD) for observability.
- Provide a lightweight R wrapper around key CLI commands so the workflow can be invoked from R notebooks (post-MVP).

## 6. Risks & Mitigations

| Risk | Impact | Mitigation |
|------|--------|------------|
| Qualtrics schema changes | Roster sync fails | Validation + unit tests raise early alerts. |
| SMTP downtime | Emails not delivered | Dry-run + manual resend, plan for retry/backoff. |
| Compliance DB access issues | No snapshots | Fixture DB for diagnostics, alert when validation fails. |
| Secrets leakage | Security incident | Keep `.env` out of VCS, use secret store in production. |

## 7. Open Decisions

- Final hosting environment for scheduled sends: local cron/shell automation for MVP; revisit managed hosting later.
- Long-term storage for historical send logs: local storage (git-ignored) for MVP; evaluate cloud storage when scaling.
- Mechanism for user opt-out/escalations: defer to post-MVP; capture requirement for future iteration (support lagging-only or unsubscribe options).
