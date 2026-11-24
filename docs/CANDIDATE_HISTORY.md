# Candidate repeats and direction flips

The OI **Candidates** page highlights stocks that keep passing the scanner, and
flags a stock that has turned from SHORT to LONG. Everything is computed from
`scan_candidates`; no extra table and no FYERS call.

## Definitions

All comparisons are **relative to the row's own scan**, so the flags are correct
when you filter the page to an older scan. Only `scan_type = 'OI'` scans take
part; pattern candidates carry no direction and are ignored.

| Flag | Meaning |
| --- | --- |
| `in_previous_scan` | The same symbol appears in the scan run immediately before this row's scan. Two scans on the same day count; the "previous scan" is the closest earlier scan run. |
| `in_last_2_days` | The same symbol appears in a scan on one of the two previous **scan days** — the two most recent earlier IST dates that had an OI scan. A scan day is a date with scans, not a calendar day. |
| `previous_direction` | The symbol's latest direction on those two previous scan days, when that scan had exactly one direction for it. |
| `short_to_long` | The row is LONG and `previous_direction` is SHORT. |
| `previous_seen_at` | Start time of the most recent earlier scan that contained the symbol (previous scan or previous scan days). |

A stock can satisfy both repeat flags at once; the UI then shows `2 scans` and
`2 days` together. A flip shows `SHORT → LONG` as well.

## API

`GET /api/v1/admin/candidates` gains an optional `repeat` parameter:

| `repeat` | Rows returned |
| --- | --- |
| omitted | unchanged |
| `last_2_scans` | `in_previous_scan = true` |
| `last_2_days` | `in_last_2_days = true` |
| `short_to_long` | `short_to_long = true` |

Any other value is rejected with `422`. Every candidate in the list response —
and in `GET /admin/candidates/{id}` — now carries a `history` object:

```json
"history": {
  "in_previous_scan": true,
  "in_last_2_days": true,
  "previous_direction": "SHORT",
  "short_to_long": true,
  "previous_seen_at": "2026-11-11T04:30:00Z"
}
```

Approve/reject/publish responses leave `history` null; only the list and detail
endpoints compute it.

## Why the filter runs in Python

Whether a row repeats depends on the other scans of the same symbol. Expressing
that as portable SQL across SQLite and Postgres is not worth it at this size, so
`candidate_service.list_candidates` loads only `id/scan_id/symbol/direction` for
the rows matching the other filters, applies the repeat test in Python, then
loads the full rows for the requested page. `total` and pagination stay exact.

## UI

`admin/app/(dashboard)/candidates/page.tsx`:

* **Repeats** select — `Any history`, `In last 2 scans`, `In last 2 scan days`,
  `SHORT → LONG`.
* **History** column — `2 scans`, `2 days`, and `SHORT → LONG` badges, with a
  tooltip that names the earlier scans and the last-seen time.
* A one-line note under the filters explains the active repeat filter.

## Tests

`backend/tests/test_candidate_history.py` covers both repeat flags, the
same-day second scan, the flip, the exclusion of pattern scans, API annotation,
filtering, pagination and validation.
