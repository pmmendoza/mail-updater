# NEWSFLOWS Mail Updater (MVP)

This directory contains a minimal, working example of the mail updater pipeline. It calculates participant progress from the Bluesky compliance database and generates individualized daily emails. The implementation is deliberately lean so we can iterate toward the full project brief.

## Quickstart

1. **Install dependencies**
   ```bash
   cd mail-updater
   python3 -m venv .venv
   . .venv/bin/activate
   python -m pip install -r requirements.txt
   ```
2. **Create configuration**
   ```bash
   cp .env.template .env
   # edit .env with your Greenhost SMTP credentials or leave SMTP_DRY_RUN=true
   ```
3. **Prepare participant data**
   - Create `data/participants.csv` (relative to the repository root) with columns:
     `user_did,email,language,include_in_emails`.
   - Ensure the DIDs exist in the compliance database.
4. **Run the CLI**
   ```bash
   python -m app.cli aggregate            # show per-participant status
   python -m app.cli preview --user-did did:example:123
   python -m app.cli send-daily --dry-run # writes .eml files to outbox/
   ```

## Project layout

- `app/config.py` — loads settings from `.env` and provides defaults.
- `app/compliance_snapshot.py` — computes 14-day study window metrics per participant.
- `app/participants.py` — CSV loader for participant contact details.
- `app/email_renderer.py` — renders Jinja templates into text/HTML content.
- `app/mailer.py` — handles dry-run output and SMTP delivery (when enabled).
- `app/cli.py` — Click commands for aggregation, preview, and sending.
- `app/templates/email/` — plain text and HTML email templates.
- `scripts/mvp_check.sh` — quick smoke test (aggregate + dry-run send).

## Testing

Run the unit tests from the repository root:
```bash
pytest tests/test_compliance_snapshot.py
```
The tests build an in-memory SQLite database with sample feed requests and engagements to verify the window calculations.

## Next steps

- Migrate participant/contact state into `mail.db` for persistence.
- Share compliance aggregation helpers with the `compliance-tracker` project.
- Harden SMTP delivery (retries, threading headers) and add bounce suppression.
- Expand localization support once translations are ready.

Refer to `Next_Iteration_Sprints.md` for the detailed roadmap.
