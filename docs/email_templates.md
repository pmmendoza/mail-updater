# Email Template Variants

_Last updated: 2025-10-20_

## 1. Daily Progress (On-Track)
Same as current template; no changes required.

## 2. Daily Progress (Needs Activity)
```
Subject: Quick check-in on your Bluesky activity

Dear {{ participant.first_name or "participant" }},

We noticed there hasn't been any activity recorded for your Bluesky feed today. No worries—there's still plenty of time to catch up. To stay on track, please:

1. Open the curated Bluesky feed at least once today.
2. Engage with at least one news post (like, repost, or reply).

If you're having trouble accessing the feed or believe this is a mistake, reply to this email and we'll help investigate.

Thanks for staying engaged!

Warm regards,
The Newsflows Research Team
```

## 3. Daily Progress (Inactive >2 Days)
```
Subject: Let's get you back on track!

Hi {{ participant.first_name or "there" }},

It looks like we've missed you for the past couple of days. To continue participating in the study, please log in to the Bluesky feed and interact with at least one news post today.

Remember, the goal is:
- Use the feed daily
- Engage with at least one news post per day

If you need a break or want to pause updates, let us know by replying to this email—we're happy to adjust.

Thank you for contributing to our research!

Best,
The Newsflows Research Team
```

## 4. Notes
- Templates assume future support for `first_name` personalization (fallback to generic text).
- Rendering logic should choose template based on compliance snapshot (e.g., zero activity for 1 day vs 2+ days).
- Add translation work once localization resumes.
