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
