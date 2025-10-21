# mail.db Schema (v1)

_Last updated: 2025-10-21_

## 1. Goals
- Provide a durable source of truth for participant roster, status flags, and notification preferences.
- Track daily compliance summaries and send history in a structured form.
- Maintain compatibility with existing CSV workflow during transition.

## 2. Entity Overview

| Table | Purpose |
|-------|---------|
| `participants` | Master roster of study participants with contact + status metadata. |
| `participant_status_history` | Audit table for status changes (active/inactive, unsubscribed). |
| `daily_snapshots` | Compliance metrics per participant per study day (mirrors CSV calculations). |
| `send_attempts` | Records each email/dry-run attempt with SMTP outcome. |
| `metadata` | Key-value store for schema version and migration bookkeeping. |

## 3. Table Definitions

### 3.1 participants
```sql
CREATE TABLE participants (
    participant_id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_did TEXT NOT NULL UNIQUE,
    email TEXT NOT NULL,
    type TEXT DEFAULT 'pilot',             -- pilot | prolific | admin | test
    status TEXT DEFAULT 'active',          -- active | inactive | unsubscribed
    language TEXT DEFAULT 'en',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_participants_status ON participants(status);
```

**Status semantics**
- `active`: participant receives regular updates.
- `inactive`: participant is temporarily paused (bounce, manual hold, etc.).
- `unsubscribed`: participant opted out; keep record for auditing.

### 3.2 participant_status_history
```sql
CREATE TABLE participant_status_history (
    history_id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL REFERENCES participants(participant_id),
    old_status TEXT,
    new_status TEXT,
    reason TEXT,
    changed_by TEXT,
    changed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 3.3 daily_snapshots
```sql
CREATE TABLE daily_snapshots (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL REFERENCES participants(participant_id),
    study_day DATE NOT NULL,
    retrievals INTEGER DEFAULT 0,
    engagements INTEGER DEFAULT 0,
    active_day INTEGER DEFAULT 0,
    cumulative_active INTEGER DEFAULT 0,
    on_track INTEGER DEFAULT 0,
    computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    UNIQUE(participant_id, study_day)
);
CREATE INDEX idx_daily_snapshots_day ON daily_snapshots(study_day);
```

### 3.4 send_attempts
```sql
CREATE TABLE send_attempts (
    attempt_id INTEGER PRIMARY KEY AUTOINCREMENT,
    participant_id INTEGER NOT NULL REFERENCES participants(participant_id),
    message_type TEXT NOT NULL,          -- daily_update, onboarding, etc.
    mode TEXT NOT NULL,                  -- dry-run | live
    status TEXT NOT NULL,                -- sent | failed | skipped
    smtp_response TEXT,
    template_version TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
CREATE INDEX idx_send_attempts_status ON send_attempts(status);
```

### 3.5 metadata
```sql
CREATE TABLE metadata (
    key TEXT PRIMARY KEY,
    value TEXT
);
INSERT INTO metadata(key, value) VALUES ('schema_version', '1');
```

## 4. Migration Strategy
1. **Version 1**: Create tables listed above using the provided migration helper (`python -m app.cli migrate-mail-db`, wraps `scripts/migrations/001_init_mail_db.py`).
2. **Bootstrap**: Import existing `data/participants.csv` into `participants` table; mark status as `active` unless the CSV indicates otherwise.
3. **Sync loop**: CLI writes new snapshots/send attempts to mail.db while continuing to read compliance metrics from `compliance.db`.
4. **CSV deprecation**: Once confidence is built, replace CSV read path with mail.db queries (with fallback export for manual editing).

### 4.1 Roster synchronisation decision
- Qualtrics sync should **upsert directly into `mail.db.participants`** while continuing to export `data/participants.csv` as a human-auditable backup.
- New DIDs create a fresh row with `status='active'`; existing rows only update contact fields (`email`, `type`, `language`) and leave `status` untouched so manual overrides applied via `python -m app.cli participant set-status` remain authoritative.
- Any status values present in the Qualtrics payload are ignored for existing records; the sync uses them only when seeding brand-new participants.
- After the upsert, the CSV export mirrors the latest mail.db roster (including preserved statuses) to keep legacy tooling in lockstep.

### 4.2 Send attempt persistence plan
- Every render/send operation will insert a row into `send_attempts` **before** dispatch with `status='queued'`, capturing the participant, `message_type` (e.g., `daily_update`), `mode` (`dry-run` vs `live`), and the template hash/version.
- Upon completion the CLI/mail sender updates that row to `status='sent'`, `status='failed'`, or `status='skipped'`, populating `smtp_response` (or failure reason).
- Dry-run deliveries still write `mode='dry-run'` and attach the path to the `.eml` artefact inside `smtp_response` so the audit trail is uniform across environments.
- Bounce handling reuses the existing row: the IMAP poller writes `status='failed'` with reason `bounced` and flips the participant status to `inactive` (see §4.1).
- A lightweight helper in `app/mail_db.operations` exposes `record_send_attempt()`, `update_send_attempt()`, `fetch_recent_send_attempts()`, and `mark_send_attempt_bounced()` so the CLI, status views, and bounce scanner all share the same persistence logic.

## 5. CLI & API Implications
- New CLI command: `python -m app.cli participant set-status --user-did <DID> --status inactive --reason 'manual review'`.
- Validation command reads from mail.db when available; fallback to CSV during migration.
- Qualtrics sync should upsert into `participants` while preserving status overrides.

## 6. Open Questions
- Should we normalise language/participant type into lookup tables? (Deferred unless values expand.)
- Where to store unsubscribe preferences (boolean flag vs separate table)? For now, use `status='unsubscribed'`.
- Do we need soft deletion? Use status `inactive` to keep history.
>A: I'm happy with your choices.


## 7. Next Steps
1. Review schema with stakeholders.
2. Implement migration script + simple ORM layer (SQLModel/SQLAlchemy).
3. Update CLI commands to read/write mail.db while keeping CSV export command for manual edits.
4. Extend unit tests to cover mail.db operations using in-memory SQLite.
