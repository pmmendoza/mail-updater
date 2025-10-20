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
- [ ] Add health checks and synthetic tests to monitor send success rate.
- [ ] Add a dashboard that allows for both a detailed inspection of certain participants by did, as well as a general overview to track compliance and email notifications. Show compliance in continuous metrics, not binaries (e.g., for the engagement on a day not yes/no but rather how many engagements).
- [ ] Compliance criteria are exposed as environment variables to allow meaningful adjustments. E.g.,:
	- max_skip_span = how many days participants are allowed to skip in a row.
	- min_active_days = how many days participants have to have been active.
	Active day definitions
	- min_engagement = how many engagements are required for the definition 'active day'
	- min_retrievals = how many retrievals are required for the definition 'active day'