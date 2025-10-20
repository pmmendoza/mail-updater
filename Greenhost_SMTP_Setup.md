# Greenhost SMTP Setup Guide

Follow these steps to configure the mail-updater project to send emails through Greenhost.

## 1. Gather credentials from Greenhost
- Log in to the Greenhost control panel and create (or locate) the mailbox dedicated to the study emails.
- Note the following details:
  - SMTP hostname (typically `mail.greenhost.net`).
  - SMTP port supporting STARTTLS (usually `587`) or SSL (usually `465`).
  - Mailbox username (full email address) and password.
  - Optional: IMAP hostname/port if you plan to append sent mail or poll for bounces later.

## 2. Update environment configuration
1. Copy `.env.template` to `.env` if you have not already.
2. Edit the following keys in `mail-updater/.env` (create them if missing):
   ```
   SMTP_HOST=mail.greenhost.net
   SMTP_PORT=587
   SMTP_USE_SSL=false            # set true if you prefer port 465
   SMTP_USERNAME=your-mailbox@domain
   SMTP_PASSWORD=your-mailbox-password
   SMTP_FROM=Bluesky Feed Project <your-mailbox@domain>
   SMTP_REPLY_TO=research-team@domain
   SMTP_DRY_RUN=false            # switch to true to keep writing .eml files only
   ```
3. (Optional for later phases) add IMAP settings so the sender can append to "Sent" and poll bounces:
   ```
   IMAP_HOST=mail.greenhost.net
   IMAP_PORT=993
   IMAP_USERNAME=your-mailbox@domain
   IMAP_PASSWORD=your-mailbox-password
   IMAP_SENT_MAILBOX=Sent
   IMAP_BOUNCES_MAILBOX=INBOX/Bounces
   ```

## 3. Verify connectivity locally
- Run `python -m app.cli send-daily --dry-run` to generate messages without contacting SMTP; confirm the rendered emails look correct.
- Temporarily set `SMTP_DRY_RUN=false` and run `python -m app.cli preview --user-did <DID> --send-test you@example.com` (or equivalent command once implemented) to deliver a single test email.
- Monitor the CLI output for successful connection/authentication. If authentication fails, double-check the password and whether Greenhost requires app-specific passwords.

## 4. Security notes
- Store `.env` outside version control (already covered by `.gitignore`).
- Rotate the mailbox password periodically and update `.env` accordingly.
- If running from cron/launchd, ensure the environment loading mechanism exposes these variables securely (e.g., using `direnv`, systemd EnvironmentFile, or sourcing `.env` via wrapper script).
