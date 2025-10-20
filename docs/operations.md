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
1. **Continuous Integration**: GitHub Actions workflow runs `make lint` and `make test` on every pull request; ~~upload dry-run `.eml` artifacts for inspection.~~
~~2. **Artifact Packaging**: Build a Docker image (or Python package) tagged with commit SHA and `latest`; embed templates and CLI entrypoint ~~.
~~3. **Scheduled Deployment**: GitHub Actions cron job (e.g., `0 5 * * *`) or systemd timer performs validation and send-daily using secrets injected at runtime.~~
4. **Approvals**: Require manual approval before enabling live send in new environments; keep dry-run as default guardrail.
5. **Rollback**: Re-run previous image or git SHA; keep fixtures handy to reproduce issues locally.

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
- **Local dev**: .env managed manually; never commit secrets.
- **CI**: GitHub Secrets or Vault provide SMTP/Qualtrics tokens; jobs export them as env vars.
- **Production**: use cloud secret manager (e.g., AWS Secrets Manager); rotate credentials quarterly.
- Ownership: SMTP (Operations), Qualtrics (Research), compliance DB (Data Engineering).

## 11. Scheduled Send Workflow Prototype
- Configure GitHub Actions cron to run dry-run daily; require manual approval step before live send.
- Provide fallback instructions for running the CLI on a managed VM with cron/systemd.
- Log job output to shared Slack channel or issue tracker for audit.
