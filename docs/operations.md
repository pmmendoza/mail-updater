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

## 4. Incident Response
- **Validation failure**: review CLI output, cross-check participant roster for typos, fix compliance data.
- **SMTP failure**: re-run `python scripts/create_compliance_fixture.py` (if local) or contact mail provider; use dry-run to prevent repeated failures.
- **Qualtrics sync failure**: check `QUALTRICS_*` env vars; the CLI keeps a backup of the previous CSV.

## 5. Checklist Before Sending Live Email
- [ ] `.env` points at production compliance database and roster.
- [ ] SMTP smoke test (`python scripts/smtp_smoke_test.py` – TBD) passes.
- [ ] `python -m app.cli validate-participants` returns success.
- [ ] `python -m app.cli send-daily --dry-run` output looks correct.
- [ ] Stakeholder approves email copy and schedule.

## 6. Post-Run Tasks
- Archive generated `.eml` files or push to secure storage.
- File a ticket for any send failures with participant DID and error.

## 7. Change Management
- Create PREPARE-COMMIT entries in `CHANGELOG.md` every sprint.
- Require code review for Qualtrics sync or compliance logic changes.
- Document behavioral changes in README and operations guide before merging.

## 8. Future Enhancements
- Centralized logging/metrics (e.g., Grafana, CloudWatch).
- Automated reminder for manual onboarding steps.
- Integration tests running nightly with fixture data.
