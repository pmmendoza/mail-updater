# Mail Updater Operations Guide

Last updated: 2025-10-20

## 1. Environments
- **Local dev**: uses `.env`, fixture SQLite database, and dry-run SMTP mode.
- **Pilot/staging**: planned future environment with dedicated compliance DB replica and test SMTP inbox.
- **Production**: TBD; requires secure secret management and CI/CD integration.

## 2. Daily Runbook
1. Ensure `.env` has valid `COMPLIANCE_DB_PATH`, `PARTICIPANTS_CSV_PATH`, and SMTP credentials.
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

## 3. Monitoring & Alerts (planned)
- Track send successes/failures via JSONL log ingestion (e.g., into a dashboard).
- Monitor SMTP connectivity and credential expiration.
- Observe Qualtrics sync results (new participants vs. failures).

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
