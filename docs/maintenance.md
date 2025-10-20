# Mail Updater Maintenance & Deployment Checklist

Last updated: 2025-10-20

## 1. Release Readiness Checklist
- [ ] CHANGELOG contains PREPARE-COMMIT entry describing changes.
- [ ] README/operations docs updated for new behavior.
- [ ] `make lint` and `make test` pass.
- [ ] SMTP smoke test succeeds with production credentials.
- [ ] Qualtrics sync tested against staging survey.
- [ ] Dry-run send produces expected `.eml` files.
- [ ] Stakeholders sign off on participant communications.

## 2. Deployment Steps (future)
1. Update `.env` or secret store with production configuration.
2. Package code (git tag or container image) once tests pass.
3. Deploy to target host (to be determined: cron job, serverless, etc.).
4. Run validation and dry-run commands.
5. Enable scheduled execution (cron/systemd/github actions) once verified.

## 3. Versioning & Rollback
- Tag releases as `vYYYY.MM.DD` once shipped.
- Keep previous release tarball or image for quick rollback.
- Maintain historical CSV roster snapshots in secure storage.

## 4. Support & Escalation
- First-line support: research operator on duty.
- Escalation path: engineering lead → infrastructure lead → product owner.
- Log incidents in shared tracker (TBD) with timestamps, DID, error cause, mitigation.

## 5. Maintenance Windows
- Schedule updates outside participant send window (before 05:00 cutoff).
- Notify stakeholders before downtime exceeding 15 minutes.

## 6. Future Improvements
- Automate deployment via CI/CD pipeline.
- Add health checks and synthetic tests to monitor send success rate.
- Implement automated backups for compliance and participant data.
