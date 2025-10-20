# NEWSFLOWS Mail Updater — Project Brief (for future LLMs)

**Purpose.** Send **daily, multilingual progress emails** to study participants (via Prolific relay or pilot email) summarizing their compliance with the study requirement: **≥10 active days within a 14-day window**. An **active day** = **≥1 feed retrieval** **and** **≥3 engagements** (like, comment, repost, quote; *reply may be added later*).

**Time logic.**

* All raw events are logged in **UTC**; compliance is computed in **Europe/Amsterdam**.
* **Study-day** runs **05:00 → 05:00** local. Emails are sent around **09:00** local.
* The 14-day window is **per-user**, anchored at the user’s **first feed retrieval**.
* Email states whether the participant is **on track** to reach 10/14.

**Data sources.**

* Existing **compliance.db** (read-only):

  * `feed_requests(requester_did, timestamp, ...)`
  * `feed_request_posts(request_id, post_uri, ...)`
  * `engagements(timestamp, did_engagement, engagement_type, post_uri, position_status, ...)`
* New **mail.db** (this project):

  * `participants(user_did, PROLIFIC_ID, pilot_email, feed_url, surveylang, include_in_emails, thread_message_id)`
  * `compliance_daily(user_did, study_day_date, retrievals, engagements, active_day, cumulative_active, on_track, computed_at)`
  * `email_outbox(..., status, smtp_response, payload_json, sent_at)`

**Messaging & deliverability.**

* One **personalized email per user per day** (no cohort BCC).
* **Threading:** first successful email’s `Message-ID` is stored; subsequent emails set `In-Reply-To/References` to keep a single conversation.
* **i18n:** Dutch, English, Czech, French. Language taken from `surveylang`.
* **From/Reply-To:** configurable; append each sent MIME to **IMAP “Sent”**.
* **Bounce handling:** IMAP polling marks hard bounces and **suppresses** future sends.

**Content.**

* Subject: **“Bluesky Feed Project: daily progress update”**.
* Body includes: completed **X/10**, **on-track** flag, 14-day grid (✅/⚪️), **today-so-far** hint, user’s **feed_url** (pin reminder), optional **payout link** placeholder.

**Options & knobs.**

* Engagement scope: `any` (default) or `matched` (only posts verified from assigned feed positions).
* CLI + optional **Flask dashboard** (preview, manual triggers, overview).
* **Dry-run** mode writes `.eml` files (no SMTP).

**Compliance & privacy.**

* Use Prolific relay (`PROLIFIC_ID@email.prolific.com`) or `pilot_email`.
* **Do not expose PROLIFIC_ID** in email body.
* Log minimal necessary data; maintain auditability/idempotency.


---

# 0) Tech stack & dependencies

**Python 3.11+**
Install (pick one of the two “send” stacks):

* Core: `SQLAlchemy`, `python-dotenv`, `pytz`, `python-dateutil`, `jinja2`, `Babel`, `click`
* Email (recommended): `smtplib` (stdlib) + `email` (stdlib)
* IMAP (append & bounces): `imaplib` (stdlib)
* Flask variant: `Flask`, `Flask-Babel`, `Werkzeug` (for basic auth), optionally `Flask-Login`
* Optional: `alembic` (migrations), `rich` (nice CLI output)

---

# 1) Project structure (both variants share this repo)

```
mail-updater/
├─ README.md
├─ .env.template
├─ requirements.txt            # or pyproject.toml
├─ mail.db/                    # sqlite file lives here (gitignored)
├─ data/
│  └─ participants.csv         # import source (gitignored)
├─ app/
│  ├─ __init__.py
│  ├─ config.py                # loads .env, typed settings
│  ├─ db.py                    # SQLAlchemy engine/session helpers
│  ├─ models.py                # SQLAlchemy table models (see DDL below)
│  ├─ i18n/
│  │  ├─ messages.pot
│  │  ├─ nl/LC_MESSAGES/messages.po
│  │  ├─ fr/LC_MESSAGES/messages.po
│  │  ├─ cs/LC_MESSAGES/messages.po
│  │  └─ en/LC_MESSAGES/messages.po
│  ├─ templates/
│  │  └─ email/
│  │     ├─ daily_progress.html.j2
│  │     └─ daily_progress.txt.j2
│  ├─ compliance/
│  │  ├─ rules.py              # 05:00 cutoff, “any|matched” engagement scope
│  │  └─ aggregate.py          # builds compliance_daily snapshots
│  ├─ mailer/
│  │  ├─ compose.py            # Jinja render + headers (threading)
│  │  ├─ send_smtp.py          # smtplib SMTP SSL/STARTTLS
│  │  ├─ imap_append.py        # append to “Sent”
│  │  └─ bounces.py            # IMAP polling, mark hard bounces
│  ├─ cli.py                   # Click commands (aggregate, send, preview, bounces)
│  └─ server.py                # Flask factory + admin blueprint (dashboard)
├─ scripts/
│  ├─ init_db.py               # create tables + indices
│  ├─ import_participants.py   # from data/participants.csv
│  ├─ backfill_snapshots.py    # rebuild compliance_daily from raw
│  └─ preview_one.py
├─ ops/
│  ├─ cron-example.txt
│  └─ launchd.mail-updater.plist
└─ .gitignore
```

---

# 2) Configuration (.env)

```
TZ=Europe/Amsterdam
DB_PATH=./mail.db/mail.sqlite

# SMTP (Greenhost)
SMTP_HOST=smtp.greenhost.net
SMTP_PORT=465
SMTP_USER=...
SMTP_PASS=...
SENDER_ADDR=study@yourdomain.tld
SENDER_NAME=NEWSFLOWS Team
REPLY_TO=study@yourdomain.tld

# IMAP (for append & bounces)
IMAP_HOST=imap.greenhost.net
IMAP_PORT=993
IMAP_USER=...
IMAP_PASS=...
IMAP_SENT_FOLDER=Sent
IMAP_BOUNCES_MAILBOX=INBOX   # or a label/folder you prefer

# Business rules
SEND_HOUR_LOCAL=9            # 09:00 local target
CUTOFF_HOUR_LOCAL=5          # day runs 05:00→05:00
WINDOW_DAYS=14
REQUIRED_ACTIVE_DAYS=10
ENGAGEMENT_SCOPE=any         # any | matched

# Security (Flask admin)
ADMIN_USER=admin
ADMIN_PASS=choose-a-strong-one
```

---

# 3) Database schema (new **mail.db**; SQLite via SQLAlchemy)

**Participants (input from Qualtrics subset)**

```sql
CREATE TABLE IF NOT EXISTS participants (
  user_did TEXT PRIMARY KEY,
  PROLIFIC_ID TEXT,
  pilot_email TEXT,
  feed_url TEXT NOT NULL,
  surveylang TEXT NOT NULL,       -- Dutch | English | Czech | French
  include_in_emails INTEGER NOT NULL DEFAULT 1,
  thread_message_id TEXT          -- for inbox threading (seed stored here)
);
```

**Compliance snapshots (one row per user per study-day)**

```sql
CREATE TABLE IF NOT EXISTS compliance_daily (
  user_did TEXT NOT NULL,
  study_day_date DATE NOT NULL,   -- local day start (05:00 boundary)
  retrievals INTEGER NOT NULL,
  engagements INTEGER NOT NULL,
  active_day INTEGER NOT NULL,    -- 1 if retrievals>=1 && engagements>=3
  cumulative_active INTEGER NOT NULL,
  on_track INTEGER NOT NULL,
  computed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  PRIMARY KEY (user_did, study_day_date)
);
CREATE INDEX IF NOT EXISTS idx_cd_user ON compliance_daily(user_did);
```

**Email outbox (audit + idempotency)**

```sql
CREATE TABLE IF NOT EXISTS email_outbox (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  user_did TEXT NOT NULL,
  to_address TEXT NOT NULL,
  subject TEXT NOT NULL,
  body_html TEXT,
  body_text TEXT,
  payload_json TEXT,
  template_version TEXT,
  send_type TEXT NOT NULL,        -- 'daily' | 'manual' | 'seed'
  in_reply_to TEXT,               -- set for threaded replies
  references_hdr TEXT,            -- set for threading
  queued_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  sent_at TIMESTAMP,
  status TEXT,                    -- 'queued'|'sent'|'failed'|'skipped'
  smtp_response TEXT
);
```

> You’ll continue to read **raw** data from your existing `compliance.db` (`engagements`, `feed_requests`, `feed_request_posts`). This repo only *adds* `mail.db`.

---

# 4) Business rules (encapsulated in `rules.py`)

* **Study-day window:** local 05:00 → next 05:00 (Europe/Amsterdam).
  Quasi-code:

```python
from datetime import datetime, timedelta
import pytz

def local_day_bucket(ts_utc, cutoff_hour_local=5, tz_name="Europe/Amsterdam"):
    tz = pytz.timezone(tz_name)
    dt_local = ts_utc.astimezone(tz)
    # Shift so that 05:00 is the boundary:
    shifted = dt_local - timedelta(hours=cutoff_hour_local)
    day = shifted.date()  # study_day_date
    start = tz.localize(datetime(day.year, day.month, day.day, cutoff_hour_local, 0, 0))
    end = start + timedelta(days=1)
    return start, end, day
```

* **Active day:** `retrievals >= 1` **AND** `engagements >= 3`
* **Engagement scope:**

  * `any`: count all events with `engagement_type in {"like","comment","repost","quote","reply"}`
  * `matched`: limit to rows where `position_status='matched'` **OR** join with the day’s `feed_request_posts` for that user to ensure posts came from assigned feed
* **Window totals:** 14 days rolling from **per-user first retrieval** (first `feed_requests` row for that DID, using day boundary above)
* **On-track:**

  ```
  active_so_far = cumulative_active up to “yesterday” (05:00 boundary)
  days_elapsed = number of study days elapsed in the 14-day window
  days_left = WINDOW_DAYS - days_elapsed
  need = max(0, REQUIRED_ACTIVE_DAYS - active_so_far)
  on_track = (need <= days_left)
  ```

---

# 5) Aggregator (`aggregate.py`)

Quasi-code (SQLAlchemy + your raw DB):

```python
def compute_or_update_snapshots(raw_db_path, mail_db_session, cutoff_hour_local, scope):
    # 1) Load participants to know *who* to compute for
    parts = session.query(Participants).filter_by(include_in_emails=1).all()
    for p in parts:
        # 2) Determine study_start = first feed_requests for user
        first_req = first_feed_request_for_user(raw_db_path, p.user_did)
        if not first_req:
            continue  # hasn’t started yet
        # 3) Build 14 study-day windows from study_start up to “yesterday”
        days = iter_study_days(first_req.ts_utc, cutoff_hour_local)
        for d in days:
            retrievals = count_retrievals(raw_db_path, p.user_did, d.start, d.end)
            engagements = count_engagements(raw_db_path, p.user_did, d.start, d.end, scope)
            active = int(retrievals >= 1 and engagements >= 3)
            cumulative = previous_cumulative(mail_db_session, p.user_did, d.prev_date) + active
            days_elapsed = min(WINDOW_DAYS, d.index+1)
            days_left = WINDOW_DAYS - days_elapsed
            need = max(0, REQUIRED_ACTIVE_DAYS - cumulative)
            on_track = int(need <= days_left)
            upsert_compliance_daily(mail_db_session, p.user_did, d.date, retrievals, engagements, active, cumulative, on_track)
```

> Provide small helper queries for raw tables (`feed_requests`, `engagements`) by `(user_did, ts range)`.

---

# 6) i18n / l10n

* **Language field:** `surveylang` ∈ {Dutch, English, Czech, French}. Map to locale codes:
  `{'Dutch':'nl', 'English':'en', 'Czech':'cs', 'French':'fr'}`
* **Babel extraction:** Mark template strings with `_('...')`.
  Build/update catalogs:

  ```
  pybabel extract -F babel.cfg -o app/i18n/messages.pot .
  pybabel init -i app/i18n/messages.pot -d app/i18n -l nl
  pybabel init -i app/i18n/messages.pot -d app/i18n -l fr
  pybabel init -i app/i18n/messages.pot -d app/i18n -l cs
  pybabel init -i app/i18n/messages.pot -d app/i18n -l en
  # (later use pybabel update ...)
  pybabel compile -d app/i18n
  ```
* **Stand-alone or Flask:**

  * CLI: use `Babel.support.Translations.load(...)` and pass to Jinja `Environment` as `globals`/`filters`.
  * Flask: `Flask-Babel` with `@babel.localeselector` returning user’s locale for preview.

---

# 7) Email templates (HTML + text)

`templates/email/daily_progress.html.j2` (excerpt with keys)

```html
<h2>{{ _('Bluesky Feed Project: daily progress update') }}</h2>
<p>{{ _('We count study days from %(start)s to %(end)s Amsterdam time.',
        start=cutoff_window_start, end=cutoff_window_end) }}</p>

<p>
  {{ _('Completed') }}: <strong>{{ completed }}/{{ required }}</strong>
  {% if on_track %} ✅ {{ _('You are on track.') }}
  {% else %} ⚠️ {{ _('You need %(need)s more active days.', need=need) }} {% endif %}
</p>

<table border="1" cellpadding="6" cellspacing="0">
  <tr>
    {% for d in days %}
    <td style="text-align:center">
      <div>{{ d.label }}</div>
      <div>{% if d.active %}✅{% else %}⚪️{% endif %}</div>
      <div>{{ _('R') }}: {{ d.retrievals }} / {{ _('E') }}: {{ d.engagements }}</div>
    </td>
    {% endfor %}
  </tr>
</table>

<p>
  {{ _('Today so far') }}:
  {{ _('Retrievals') }} {{ today.retrievals }},
  {{ _('Engagements') }} {{ today.engagements }}.
  {% if today_hint %}<em>{{ today_hint }}</em>{% endif %}
</p>

<p>
  <a href="{{ feed_url }}" style="display:inline-block;padding:10px 14px;border:1px solid #333;text-decoration:none;">
    {{ _('Open your assigned feed') }}
  </a>
  <br><small>{{ _('Tip: pin the feed in the Bluesky app for quick access.') }}</small>
</p>

{% if payout_link %}
<p><a href="{{ payout_link }}">{{ _('Claim today’s check-in') }}</a></p>
{% endif %}

<p><small>{{ _('This update is sent around %(time)s. Questions? Reply to this email.',
                 time=send_time_hhmm) }}</small></p>
```

Plain-text template mirrors the same content.

---

# 8) Composing & threading (`compose.py`)

Quasi-code:

```python
from email.message import EmailMessage
from email.utils import make_msgid, formataddr

def compose_daily_message(participant, payload, html_body, text_body, seed=False):
    msg = EmailMessage()
    msg['Subject'] = "Bluesky Feed Project: daily progress update"
    msg['From'] = formataddr((SENDER_NAME, SENDER_ADDR))
    msg['To'] = to_address_for(participant)  # PROLIFIC relay else pilot_email
    msg['Reply-To'] = REPLY_TO

    msg.set_content(text_body)
    msg.add_alternative(html_body, subtype='html')

    # Threading: seed vs reply
    if seed or not participant.thread_message_id:
        message_id = make_msgid(domain=SENDER_ADDR.split('@')[-1])
        msg['Message-ID'] = message_id
        in_reply_to = None
    else:
        msg['In-Reply-To'] = participant.thread_message_id
        msg['References']  = participant.thread_message_id

    return msg
```

* After sending the **first** email successfully, store its `Message-ID` in `participants.thread_message_id`. All subsequent messages include `In-Reply-To/References` so clients keep one conversation thread.

---

# 9) Sending via SMTP & appending via IMAP

`smtplib` send:

```python
import smtplib, ssl

def send_via_smtp(msg):
    ctx = ssl.create_default_context()
    with smtplib.SMTP_SSL(SMTP_HOST, SMTP_PORT, context=ctx) as smtp:
        smtp.login(SMTP_USER, SMTP_PASS)
        resp = smtp.send_message(msg)
    return str(resp)  # capture for logging
```

IMAP append to “Sent”:

```python
import imaplib, datetime

def imap_append_sent(raw_bytes):
    with imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT) as imap:
        imap.login(IMAP_USER, IMAP_PASS)
        imap.append(IMAP_SENT_FOLDER, '\\Seen', imaplib.Time2Internaldate(datetime.datetime.now().timetuple()), raw_bytes)
```

**Flow:** compose → queue in `email_outbox` → send → append to Sent → update `email_outbox` with `sent_at`, `status='sent'`, `smtp_response`.

---

# 10) Bounces (IMAP polling) & suppression

`bounces.py` pseudo:

```python
def poll_bounces_and_mark_suppressed():
    m = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
    m.login(IMAP_USER, IMAP_PASS)
    m.select(IMAP_BOUNCES_MAILBOX)
    typ, ids = m.search(None, '(FROM "MAILER-DAEMON" OR SUBJECT "Undelivered" OR HEADER "Content-Type" "delivery-status")')
    for msg_id in ids[0].split():
        typ, data = m.fetch(msg_id, '(RFC822)')
        eml = email.message_from_bytes(data[0][1])
        rcpt = extract_failed_rcpt(eml)               # parse DSN
        mark_participant_suppressed(rcpt)             # include_in_emails=0
        log_bounce(rcpt, raw_headers=eml.items())
        # Optionally move to "Bounces/Processed"
```

* **Policy:** on hard bounce, set `include_in_emails=0` and record a row in `email_outbox` as “failed: bounced”. You’ll see it in the dashboard.

---

# 11) CLI commands (`cli.py` with Click)

* `aggregate-daily` — compute/refresh snapshots (catch-up safe)
* `send-daily [--dry-run] [--test-to you@..]` — send to all eligible
* `send-one --user-did DID [--dry-run]`
* `preview --user-did DID --format html|text` — print to stdout or write `.eml`
* `bounces-scan` — IMAP scan and suppress

Usage example:

```
python -m app.cli aggregate-daily
python -m app.cli preview --user-did did:plc:... --format html
python -m app.cli send-daily --dry-run
python -m app.cli send-daily
python -m app.cli bounces-scan
```

---

# 12) Flask admin dashboard (`server.py`)

* **Auth:** HTTP Basic (admin/pass from .env)
* **Routes:**

  * `GET /admin/overview` — table of participants with: completed/required, on_track, last sent status, bounce flag
  * `GET /admin/preview?user_did=...` — renders HTML preview in browser
  * `POST /admin/send-daily?dry=1` — manual trigger (queues & sends)
  * `POST /admin/send-one?user_did=...` — manual one-off
  * `GET /admin/health` — DB + SMTP + IMAP quick checks
* **i18n:** `Flask-Babel` for preview; actual sending uses the CLI stack with Babel translations to keep the code paths aligned.

---

# 13) Scheduling

**Cron (Linux):**

```
# Aggregate at 05:05 (just after the day closes), then send at 09:00
5 5 * * *  cd /path/to/mail-updater && /usr/bin/python3 -m app.cli aggregate-daily >> logs/aggregate.log 2>&1
0 9 * * *  cd /path/to/mail-updater && /usr/bin/python3 -m app.cli send-daily   >> logs/send.log 2>&1
```

**launchd (macOS):** `ops/launchd.mail-updater.plist` with two separate jobs (05:05 and 09:00), `ProgramArguments` pointing to the CLI calls above.

---

# 14) README.md (drop-in content)

```markdown
# NEWSFLOWS Mail Updater

Daily, multilingual compliance updates for the Bluesky Feed Project. Sends one personalized email per participant, appends to IMAP “Sent”, and logs every send in SQLite.

## Features
- 05:00→05:00 local (Europe/Amsterdam) study-day boundary
- 10 / 14 active days target (active = ≥1 retrieval & ≥3 engagements)
- On-track math and 14-day grid in email
- Multilingual (NL/EN/CS/FR) via Babel/Flask-Babel
- Threaded emails (stable Subject + In-Reply-To)
- SMTP send (Greenhost), IMAP append to “Sent”, IMAP bounce scan
- CLI + optional Flask admin dashboard (preview, manual triggers)

## Quickstart
1. `cp .env.template .env` and set SMTP/IMAP/DB settings.
2. `python3 -m pip install -r requirements.txt`
3. `python scripts/init_db.py`
4. Put `data/participants.csv` with columns:
   - `user_did,PROLIFIC_ID,pilot_email,feed_url,surveylang,include_in_emails`
5. `python scripts/import_participants.py`
6. Build translations (`pybabel extract ... compile ...`) or start with English.
7. Run once:
   - `python -m app.cli aggregate-daily`
   - `python -m app.cli preview --user-did <DID> --format html`
   - `python -m app.cli send-one --user-did <DID> --dry-run`
8. Schedule daily runs (cron/launchd).

## Config knobs
- `CUTOFF_HOUR_LOCAL=5`, `SEND_HOUR_LOCAL=9`
- `WINDOW_DAYS=14`, `REQUIRED_ACTIVE_DAYS=10`
- `ENGAGEMENT_SCOPE=any|matched`

## Safety & compliance
- One email per user per day (idempotent checks in `email_outbox`)
- No cohort BCC, one personalized message per recipient
- DSN-based bounce suppression
- No PROLIFIC IDs shown in body; Prolific relay addresses used for sending
```

---

# 15) What you’ll still decide later (but already supported)

* Switch `ENGAGEMENT_SCOPE` to `matched` once your `position_status` joins are fully stable.
* Activate the **payout link** block by populating `payout_link` per user-day (single-use tokens).
* Add richer dashboard charts if helpful (e.g., cumulative actives across the cohort).

---

## Done — you can implement directly from this plan

If you want, I can also generate **starter code files** following this structure (without going all-in on implementation details): e.g., `config.py`, `models.py` (SQLAlchemy), and skeletons for the CLI and Flask routes, so your other LLM or you can fill in logic quickly.
