# Intermediate Compliance Snapshot Store — Proposal

_Last updated: 2025-10-22_

## 1. Goals
- Provide a durable, queryable record of daily compliance metrics per participant.
- Support inspection/debugging without rerunning adhoc SQL against the live compliance database.
- Feed future monitoring dashboards (Shiny, Grafana, etc.) and email rendering from a consistent source.

## 2. Design options

### Option A — SQLite table inside `mail.db`
- **Description:** add a table (e.g., `daily_snapshots_cache`) to the existing `mail.db` managed by the updater.
- **Pros:** easy to access from existing Python code; can reuse migrations framework; no new dependency.
- **Cons:** `mail.db` grows over time; updater process is responsible for keeping cache fresh (e.g., nightly job).

### Option B — Separate analytics SQLite (or DuckDB) store
- **Description:** maintain a dedicated `analytics.db` (SQLite or DuckDB) under `data/derived/` populated by a scheduled job.
- **Pros:** isolates analytics workload; DuckDB offers powerful SQL for dashboards; can be regenerated from raw compliance DB.
- **Cons:** additional file to manage; still needs scheduling; duplication of data between stores.

### Option C — Push to external warehouse (e.g., Postgres/BigQuery)
- **Description:** export snapshots to a central warehouse managed by analytics/infra.
- **Pros:** ready for enterprise dashboards/alerting; supports role-based access; scalable.
- **Cons:** higher operational overhead; requires secure connectivity and ETL tooling; overkill for current MVP.

## 3. Recommended approach
- **Phase 1:** adopt **Option A** (table inside `mail.db`). It keeps everything self-contained and works with existing migrations/tests.
- **Phase 2:** once analytics tooling matures, backfill the same schema into an `analytics.db` or external warehouse.

## 4. Proposed table schema (Phase 1)

```sql
CREATE TABLE IF NOT EXISTS daily_snapshots_cache (
    snapshot_date      DATE NOT NULL,
    user_did           TEXT NOT NULL,
    retrievals         INTEGER NOT NULL,
    engagements        INTEGER NOT NULL,
    engagement_breakdown JSON NOT NULL,
    active_day         INTEGER NOT NULL, -- 0/1
    cumulative_active  INTEGER NOT NULL,
    on_track           INTEGER NOT NULL, -- 0/1
    window_days        INTEGER NOT NULL,
    required_active_days INTEGER NOT NULL,
    computed_at        TIMESTAMP NOT NULL,
    PRIMARY KEY (snapshot_date, user_did)
);
```

- `engagement_breakdown` stored as JSON text (per-type counts).
- Populate via a nightly CLI (`python -m app.cli cache-daily-snapshots`) that reuses `compute_window_summary` and `get_daily_engagement_breakdown`.

> A: All good so far;
> 

## 5. Usage
- Email rendering can read from cache if available; fall back to live computation when cache is stale.
- Monitoring notebooks can `SELECT * FROM daily_snapshots_cache WHERE snapshot_date >= DATE('now', '-14 day');`.
- Timestamps allow verifying freshness before dashboards refresh.

## 6. Next steps
1. Add migrations + CLI command to generate the cache.
2. Schedule the cache job (cron/GitHub Actions) after Qualtrics sync completes.
3. Evaluate Option B once the Shiny dashboard is live and requires historical backfill.
