# Mail Updater — MVP Requirements

Last updated: 2025-10-20

## 1. Purpose & Scope

The MVP of the Mail Updater delivers automated daily progress emails to study participants based on engagement metrics stored in the Bluesky compliance database. The goal is to provide timely feedback, keep participants on track, and give the research team operational visibility.

## 2. Primary User Stories

### US-1 Research Operator sends daily summaries
- **As a** research operator  
- **I want** to run a CLI command that generates and sends all pending daily updates  
- **So that** participants stay informed without manual effort  
- **Acceptance**
  - `python -m app.cli send-daily` reads the configured participant roster and compliance database.
  - Dry-run mode writes `.eml` files; live mode uses the configured SMTP credentials.
  - CLI exits with non-zero status when any send fails and logs the failure reason.

### US-2 Operator previews participant email
- **As a** research operator  
- **I want** to preview an individual participant’s daily email  
- **So that** I can validate content before delivery  
- **Acceptance**
  - `python -m app.cli preview --user-did <DID>` prints the text template to stdout and exits with 0.
  - Command fails with descriptive error if DID is unknown or no activity exists.

### US-3 Operator validates roster health
- **As a** research operator  
- **I want** to confirm the roster only contains DIDs with compliance data  
- **So that** we catch onboarding issues early  
- **Acceptance**
  - `python -m app.cli validate-participants` reports duplicates or participants lacking compliance activity.
  - Failing validations exit non-zero and list impacted DIDs with email addresses.

### US-4 Automations refresh participant roster
- **As a** research operator  
- **I want** to sync the roster from Qualtrics surveys  
- **So that** manual CSV edits are minimized  
- **Acceptance**
  - `python -m app.cli sync-participants` refreshes the CSV, returns a summary of new/total participants, and validates schema.
  - Errors restore the previous CSV and exit non-zero.

## 3. Non-Functional Requirements

- **Reliability:** CLI commands must run deterministically offline using the compliance fixture; live runs depend only on SQLite + SMTP availability.
- **Security:** No secrets are committed; `.env` holds credentials and is outside version control. Credentials are only read at runtime.
- **Observability:** CLI writes send attempts to `outbox/send_log.jsonl` (dry-run or live) for audit.
- **Performance:** Generating and sending fewer than 100 daily emails must finish within 5 minutes on a laptop.

## 4. Dependencies

- **Compliance data:** SQLite database (`compliance.db` or fixture) with `feed_requests` and `engagements` tables.
- **Participant roster:** CSV with columns `email,did,status,type`.
- **SMTP:** Outbound credentials (currently Greenhost) supporting STARTTLS or SSL.
- **Qualtrics API:** token + base URL for survey exports.

## 5. Configuration Inputs

- `.env` must define:
  - `COMPLIANCE_DB_PATH`, `PARTICIPANTS_CSV_PATH`
  - `SMTP_*` values including `SMTP_FROM` with a full email address
  - `QUALTRICS_BASE_URL`, `QUALTRICS_API_TOKEN`, optional `QUALTRICS_SURVEY_FILTER`
- `data/fixtures/compliance_fixture.db` and `data/participants.csv` act as default local fixtures.

## 6. Acceptance Checklist

- [ ] `python -m app.cli send-daily --dry-run` produces `.eml` files for all active participants.
- [ ] `python -m app.cli preview --user-did <sample>` renders text output without error.
- [ ] `python -m app.cli validate-participants` reports “Roster validation successful” with fixture data.
- [ ] `python -m app.cli sync-participants` succeeds with mocked Qualtrics responses (pytest coverage).
- [ ] README documents setup, fixture usage, and CLI commands.
- [ ] CHANGELOG contains PREPARE-COMMIT entry for the sprint.

## 7. Open Questions

| ID | Topic | Owner | Notes |
|----|-------|-------|-------|
| Q1 | Should roster CSV migrate to a managed database (mail.db) before launch? | Philipp | Impacts ongoing edits & audit trail |
| Q2 | Do we need HTML emails or is text sufficient for MVP? | Research team | Template currently includes optional HTML |
| Q3 | What post-MVP KPIs must we track (delivery rate, engagement)? | Product | Drives future observability/metrics |

## 8. Risks & Mitigations

- **SMTP deliverability:** Mitigate by supporting dry-run mode and performing credential smoke tests.
- **Qualtrics survey schema drift:** Guard via CSV validation and tests; raise alerts when unexpected columns appear.
- **Participant onboarding gaps:** `validate-participants` command surfaces missing activity before daily sends.

