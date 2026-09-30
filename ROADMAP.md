# Adwatch roadmap

Implemented: exact-Page watchlists, per-country schedules, durable scans, quiet baselines, ID-based new-ad alerts, scan health/recovery, email/Telegram outbox retries, gallery search/filters, saved examples/notes, copy grouping, CSV export, authenticated dashboard, Docker Compose, backups, and regression/integration/browser tests.

Useful next extensions after real monitoring experience:

- User-defined product/offer tags and a weekly digest grouped by those tags.
- Explicit creative/copy revision history for ads that reuse the same Library ID.
- A supported alternate data provider for Pages that remain unreadable, selected by the operator.
- Permission-aware team accounts and per-user saved lists.
- Versioned database migrations before a schema-changing release.
- Optional media archiving with a defined retention policy and storage limit.

Avoid automated budget/profitability claims or inferred stopped-ad notifications based only on absence from a partial scan.
