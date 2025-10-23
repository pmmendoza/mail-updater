# Monitoring & Alerting Plan

_Last updated: 2025-10-21_

This document outlines the MVP approach for surfacing delivery metrics and bounce alerts derived from `mail.db.send_attempts`.

## Metrics
- **Daily success rate** — `sent` vs total attempts (query `fetch_recent_send_attempts` or aggregate in SQL).
- **Bounce volume** — count of attempts marked `failed` with `smtp_response` containing `bounced`.
- **Latency** — until we capture render/send timestamps, approximate by measuring CLI runtime and logging in the send log.
- **Roster health** — number of quarantined rows (from `qualtrics_quarantine.csv`) and inactive participants.

## Dashboards
- Initial implementation can live in a notebook or spreadsheet powered by SQL queries against mail.db.
- Example SQL (daily success rate):
  ```sql
  SELECT date(created_at) AS day,
         SUM(status = 'sent') AS sent,
         COUNT(*) AS total
  FROM send_attempts
  GROUP BY day
  ORDER BY day DESC;
  ```
- Use the new helper `get_daily_engagement_breakdown` for richer per-day engagement detail in analytics tools.

## Alerts
- Schedule `python -m app.cli bounces-scan` daily (cron/systemd). If `participants_updated` is non-empty, email/Slack the outcome.
- Monitor the quarantine CSV size; if it grows beyond a handful of entries, alert ops to investigate survey data quality.
- Future work: integrate with a central monitoring platform (Grafana/Looker) once infrastructure is ready.

## Next Steps
- Automate SQL queries using a lightweight notebook or dashboard.
- Extend logging to capture send latency timestamps and feed them into metrics.
- Evaluate long-term home (Grafana, Looker) once infrastructure team is ready.
- Draft a starter workbook:
  - Daily compliance snapshot vs send success (join `daily_snapshots` + `send_attempts`).
  - Bounce triage view listing participants from `qualtrics_quarantine.csv` and inactive roster entries.
  - Latency proxy chart using send CLI runtimes until precise timestamps land.

## Initial Workbook Queries (v0)

### Daily send outcomes
```sql
SELECT date(sa.created_at, 'unixepoch') AS day,
       SUM(sa.status = 'sent')          AS sent,
       SUM(sa.status != 'sent')         AS failures,
       COUNT(*)                        AS total
FROM send_attempts sa
GROUP BY day
ORDER BY day DESC
LIMIT 30;
```

- Export this table to the workbook as the primary KPI (success rate = `sent / total`).
- Join with `daily_snapshots` on `user_did` and `day` when comparative compliance metrics are required.

### Bounce / quarantine triage
```sql
WITH latest_status AS (
    SELECT p.user_did,
           p.email,
           p.status,
           MAX(sa.created_at) AS last_attempt_at,
           MAX(sa.status) KEEP (DENSE_RANK LAST ORDER BY sa.created_at) AS last_attempt_status
    FROM participants p
    LEFT JOIN send_attempts sa ON sa.participant_id = p.participant_id
    GROUP BY p.user_did, p.email, p.status
)
SELECT ls.user_did,
       ls.email,
       ls.status,
       ls.last_attempt_status,
       qa.email AS quarantined_email,
       qa.feed_url
FROM latest_status ls
LEFT JOIN read_csv_auto('data/qualtrics_quarantine.csv') qa
       ON qa.did = ls.user_did
WHERE ls.status != 'active' OR qa.did IS NOT NULL
ORDER BY ls.last_attempt_at DESC;
```

- If DuckDB is not available, replicate the CSV join by loading the quarantine file into the analytics workbook tab and performing a manual lookup.
- Highlight rows where `quarantined_email` is populated to triage survey data quality issues.

### Latency proxy chart

Until precise render/send timestamps are emitted, record CLI runtimes via the operator log:

1. Wrap `make send-daily` in a shell script that prints `RUN_START`/`RUN_END` timestamps.
2. Append the delta to `outbox/send_log.jsonl` under a `run_duration_seconds` field.
3. Chart the metric alongside success rate to monitor spikes that may indicate SMTP slowness.

Document the chosen workbook tool (e.g., DuckDB notebook, Google Sheet) and assign an owner for upkeep once the queries are populated.
