# Intermediate Compliance Snapshot Store — Proposal

_Last updated: 2025-10-22_

## 1. Goals
- Persist per-participant, per-day compliance metrics directly inside `mail.db`.
- Allow inspection/debugging without repeatedly querying the raw compliance database.
- Support future dashboards and templated emails using study-aware compliance requirements.

## 2. Approach summary
- Introduce a new table **inside `mail.db`** to cache compliance monitoring metrics.
- Provide a CLI (e.g., `python -m app.cli cache-daily-snapshots`) that:
  1. Loads requirements from a YAML config (see §3).
  2. Accepts a `--study`/`study_label` argument determining which requirement set applies.
  3. Reuses existing snapshot helpers to populate the monitoring table.
- No scheduling yet; operators run the CLI manually after Qualtrics syncs or before reporting.

## 3. Configuration (YAML)
- Move non-secret `.env` values (timezone, window settings, etc.) into `config/settings.yml`.
- Secrets (tokens, credentials) remain in `.env`.
- Requirements section example:

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

- The CLI merges `defaults` with the chosen study overrides.
- Example invocations:
  ```bash
  python -m app.cli cache-daily-snapshots --study main
  python -m app.cli cache-daily-snapshots --study pilot --from 2025-10-01 --to 2025-10-15
  ```

## 4. Proposed table schema (`mail.db`)

```sql
CREATE TABLE IF NOT EXISTS compliance_monitoring (
    snapshot_date        DATE NOT NULL,
    user_did             TEXT NOT NULL,
    study_label          TEXT NOT NULL,
    retrievals           INTEGER NOT NULL,
    engagements          INTEGER NOT NULL,
    engagement_breakdown JSON NOT NULL,
    active_day           INTEGER NOT NULL, -- 0/1 per study requirements
    cumulative_active    INTEGER NOT NULL,
    cumulative_skip      INTEGER NOT NULL,
    computed_at          TIMESTAMP NOT NULL,
    PRIMARY KEY (snapshot_date, user_did, study_label)
);
```

- `study_label` links each row to the requirement set used for evaluation.
- `cumulative_active` / `cumulative_skip` are calculated relative to each participant’s `survey_completed_at` (already synced via Qualtrics).
- `engagement_breakdown` remains JSON (`{"like": 2, "reply": 1}`) for flexible reporting.
- Columns such as `required_active_days`, `on_track`, `window_days` are omitted for now (can be derived downstream).

## 5. CLI generation workflow
1. Read YAML config + `.env` secrets, merge defaults with the requested `study_label`.
2. Fetch participants (including `survey_completed_at`) from `mail.db`.
3. Use existing helpers (`compute_window_summary`, `get_daily_engagement_breakdown`) to build per-day data.
4. Evaluate compliance flags using the study-specific thresholds (e.g., min engagements, max skip span).
5. Upsert rows into `compliance_monitoring` for each `(snapshot_date, user_did, study_label)`.
6. Leave scheduling/manual triggering to operators for now.

## 6. Usage scenarios
- **Email templates:** load the latest cache rows; fall back to live computation if a participant/day is missing.
- **Dashboards/Shiny:** query `compliance_monitoring` to power charts (e.g., `SELECT * FROM compliance_monitoring WHERE study_label = 'main' ORDER BY snapshot_date DESC`).
- **Debugging:** quickly inspect a participant’s history without hitting the compliance source DB.

## 7. Next steps
1. Implement YAML config loading (non-secret `.env` items migrate to `config/settings.yml`).
2. Add migration to create `compliance_monitoring` table and expose new CLI command.
3. Extend Qualtrics sync to ensure `survey_completed_at` is always populated before caching.
4. Manually trial `cache-daily-snapshots` for `main`/`pilot` studies; document operational runbook.
5. Revisit scheduling once manual workflow is stable.
