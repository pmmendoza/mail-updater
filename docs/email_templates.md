# Email Template Variants

_Last updated: 2025-10-21_

## 1. Daily Progress — Default
The existing `daily_progress` templates (text + HTML) continue to show the full 14-day window with a neutral tone. No changes required for participants who registered activity in the latest study day.

## 2. Daily Progress — No Activity Detected
New templates located at:
- `app/templates/email/daily_progress_noncompliant.txt.j2`
- `app/templates/email/daily_progress_noncompliant.html.j2`

They are automatically selected whenever the most recent study day contains **zero retrievals and zero engagements**. The copy emphasises the actions required to regain compliance and points participants to reply if they need support.

Key messaging points:
- Subject remains the same; body headline switches to “Bluesky Feed Project — Action Needed”.
- Includes a short checklist (open feed, interact with ≥3 posts, contact support if stuck).
- Reuses the 14-day snapshot table/list so participants can see historical context.
- Reassures participants that the message is generated automatically and shows the timestamp for the latest data pull.

## 3. Future Enhancements
- Add localization once additional languages are ready.
- Consider separate variants for multi-day inactivity (e.g., status digests) if research requires escalated phrasing.
- If participant names become available, we can personalise greetings while retaining the current fallback copy.
