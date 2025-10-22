# Mail Updater Operations Guide

Last updated: 2025-10-21

## 1. Environments
- **Local dev**: uses `.env`, fixture SQLite database, and dry-run SMTP mode.
- **Pilot/staging**: planned future environment with dedicated compliance DB replica and test SMTP inbox.
- **Production**: TBD; requires secure secret management and CI/CD integration.

## 2. Daily Runbook
0. Ensure the local environment is bootstrapped:
   ```bash
   make setup            # once per checkout or after requirements change
   source .venv/bin/activate
   python -m app.cli migrate-mail-db
   ```
   Re-run `make sync-env` whenever `.env.template` changes.
1. Confirm `.env` has valid `COMPLIANCE_DB_PATH`, `PARTICIPANTS_CSV_PATH`, and SMTP credentials.
2. Run validation:
   ```bash
   python -m app.cli validate-participants
   ```
3. Execute dry-run (optional):
   ```bash
   python -m app.cli send-daily --dry-run
   ```
4. Execute live send (once ready):
   ```bash
   python -m app.cli send-daily
   ```
5. Review log file `outbox/send_log.jsonl` for errors.

## 2.1 Roster & mail.db alignment
- Run `make sync-participants` (or `python -m app.cli sync-participants`) to upsert roster data into `mail.db`, then rewrite `data/participants.csv` as a backup view so legacy tooling keeps working. Pass `SURVEY_FILTER=regex` to target specific Qualtrics surveys.
- Manual status changes made with `python -m app.cli participant set-status` remain untouched by the sync; Qualtrics data only updates contact metadata unless a brand-new participant is created.
- The `participant set-status` command also exports the latest roster back to CSV so legacy tooling sees the updated status immediately.
- After any sync run, rerun `validate-participants` to confirm roster and compliance data stay consistent.
- The roster CSV now includes a `feed_url` column; keep it populated (Qualtrics sync will fill it automatically).
- See [`docs/qualtrics_sync.md`](qualtrics_sync.md) for field definitions, quarantine handling, and troubleshooting tips.

## 2.2 Bounce handling
- Configure IMAP access in `.env` (`IMAP_HOST`, `IMAP_PORT`, `IMAP_USERNAME`, `IMAP_PASSWORD`, `IMAP_MAILBOX`, `IMAP_USE_SSL`).
- Run `python -m app.cli bounces-scan` to ingest Delivery Status Notifications (DSNs). Each matched recipient updates the latest `send_attempts` row, flips the participant to `inactive`, and appends a note to the JSONL log.
- Use `--keep-unseen` if you want to leave processed messages unread for manual inspection.
- Review unmatched recipients reported by the command and reconcile them (e.g., update participant emails or investigate false positives).
- Use `python -m app.cli participant import-csv` once to bootstrap mail.db from
  the legacy CSV roster; subsequent runs keep CSV exports in sync automatically.

## 3. Monitoring & Alerts (planned)
- **Delivery dashboards**
  - Track send successes/failures via JSONL log ingestion or direct `send_attempts` queries (success rate, failure reasons, bounce counts).
  - Surface latency metrics (`rendered_at` vs `smtp_response`) once timestamps are captured; until then, approximate via CLI run time.
- Expose most recent sends with `python -m app.cli status --limit 20` for quick manual review.
- Use `app.compliance_snapshot.get_daily_engagement_breakdown` when building analytics dashboards; it returns retrieval counts and per-type engagement breakdowns per day.
- **Bounce alerts**
  - Schedule `python -m app.cli bounces-scan` (cron/systemd/GitHub Actions) to poll DSNs at least daily.
  - Emit notification (email/Slack) when `participants_updated` is non-empty; store unmatched recipients for manual triage.
- **Roster/Qualtrics monitoring**
  - Observe Qualtrics sync results (new participants vs. failures) and alert on high failure counts.
- **Connectivity**
  - Monitor SMTP/IMAP connectivity and credential expiration (e.g., simple TCP/LOGIN probes with alerting).

## 4. CI/CD & Deployment Automation Plan
1. **Continuous Integration**: GitHub Actions workflow runs `make lint` and `make test` on every pull request; artifacts (e.g., dry-run `.eml`) can be attached manually when needed.
2. **Artifact Packaging**: For now, rely on git checkout + virtualenv on the operator's machine. Container packaging is optional future work.
3. **Scheduled Deployment**: Default approach is a local cron/systemd timer on the operator laptop or research VM. Keep a reference GitHub Actions workflow for later automation, but do not trigger it by default.
4. **Approvals**: Require manual approval before enabling live send in any automated schedule; keep dry-run as default guardrail.
5. **Rollback**: Re-run previous git SHA; keep fixture data handy to reproduce issues locally.
6. **Metrics & Logging Enhancements**:
   - Track proportion of successful deliveries vs failures using `send_log.jsonl` and planned mail.db `send_attempts` table.
   - Record delivery latency (compute timestamps at render vs SMTP send).
   - Summarise metrics weekly and review with stakeholders (automation TBD).
   - Backlog: integrate with Grafana/Looker once infrastructure is ready.

## 5. Incident Response
- **Validation failure**: review CLI output, cross-check participant roster for typos, fix compliance data.
- **SMTP failure**: re-run `python scripts/create_compliance_fixture.py` (if local) or contact mail provider; use dry-run to prevent repeated failures.
- **Qualtrics sync failure**: check `QUALTRICS_*` env vars; the CLI keeps a backup of the previous CSV.

## 6. Checklist Before Sending Live Email
- [ ] `.env` points at production compliance database and roster.
- [ ] SMTP smoke test (`python scripts/smtp_smoke_test.py` – TBD) passes.
- [ ] `python -m app.cli validate-participants` returns success.
- [ ] `python -m app.cli send-daily --dry-run` output looks correct.
- [ ] Stakeholder approves email copy and schedule.

## 7. Post-Run Tasks
- Archive generated `.eml` files or push to secure storage.
- File a ticket for any send failures with participant DID and error.

## 8. Change Management
- Create PREPARE-COMMIT entries in `CHANGELOG.md` every sprint.
- Require code review for Qualtrics sync or compliance logic changes.
- Document behavioral changes in README and operations guide before merging.

## 9. Future Enhancements
- Centralized logging/metrics (e.g., Grafana, CloudWatch).
- Automated reminder for manual onboarding steps.
- Integration tests running nightly with fixture data.

## 10. Secrets & Environment Provisioning
- **Local dev**: `.env` managed manually; never commit secrets. Provide `.env.template` for required keys.
- **Staging/CI**: GitHub Secrets or Vault inject SMTP/Qualtrics tokens and DB paths; jobs export them as env vars for CLI runs.
- **Production**: store secrets in cloud secret manager (e.g., AWS Secrets Manager); rotate credentials quarterly and audit access.
- **Ownership**: SMTP (Operations), Qualtrics token (Research), compliance DB (Data Engineering). Document ownership in shared runbook.
- **Provisioning**: add onboarding checklist ensuring new operators receive credentials via secure channel and update cron jobs.

## 11. Scheduled Send Workflow Prototype
- Primary path: local cron job (example below) that triggers dry-run, review, then optional live send.
- Optional path: GitHub Actions workflow (disabled by default) for remote execution once infrastructure is ready.
- Log job outcome and send log summary to research Slack channel or shared tracker.

Example local crontab entry (dry-run at 05:05 local time):

```
5 5 * * * cd /path/to/mail-updater \
  && source .venv/bin/activate \
  && COMPLIANCE_DB_PATH=/path/to/compliance.db \
  && PARTICIPANTS_CSV_PATH=/path/to/participants.csv \
  && python -m app.cli send-daily --dry-run
```

After reviewing the generated `.eml` files, rerun without `--dry-run` when ready.

## Appendix: Local smoke test recipe
Use the bundled fixtures to rehearse the full flow without production data:

```bash
make setup
source .venv/bin/activate
python scripts/create_compliance_fixture.py
COMPLIANCE_DB_PATH=data/fixtures/compliance_fixture.db \
PARTICIPANTS_CSV_PATH=data/participants.csv \
python -m app.cli migrate-mail-db
COMPLIANCE_DB_PATH=data/fixtures/compliance_fixture.db \
PARTICIPANTS_CSV_PATH=data/participants.csv \
python -m app.cli participant import-csv
COMPLIANCE_DB_PATH=data/fixtures/compliance_fixture.db \
PARTICIPANTS_CSV_PATH=data/participants.csv \
python -m app.cli send-daily --dry-run
```

This generates fresh engagement data (including per-type breakdowns), primes `mail.db`, and drops dry-run `.eml` files into `outbox/` for review.
