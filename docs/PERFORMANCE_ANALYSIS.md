# Day-wise Performance Analysis

The performance page answers one question: **after the OI scanner filtered a
stock, did the underlying actually move the way the scanner guessed?**

It is a read-only analysis layer. It never changes a scan, a candidate, a
signal, or a score, and it never calls FYERS while someone is looking at the
page.

---

## 1. What counts as a "filtered stock"

Every row in `scan_candidates` is already the output of the OI scanner's filters
— a stock only gets stored if it passed them. The performance report defaults to
**all** candidates, not just the ones an admin approved or published: the goal is
to measure the filter itself, and approval limits the sample for no analytical
reason. The **Stock set** switch can narrow the same numbers to approved
(`APPROVED`/`PUBLISHED`/`EXPIRED`) or not-approved (`PENDING`/`REJECTED`)
candidates, so the two groups can be compared.

Only `ScanRun.scan_type = 'OI'` rows are included. Pattern-scanner candidates
live in a different table and are ignored.

Candidates are grouped by the **IST calendar date** of `scanned_at`.

### Repeated scans on the same day

If the scanner ran more than once on a day and picked the same stock twice, the
latest scan is the entry price. The day reports how many rows were collapsed in
`duplicates_collapsed`, so a stock is never counted twice in one day.

---

## 2. The metric

```
return_pct(D+n) = sign(direction) * (close(D+n) - scan_ltp) / scan_ltp * 100
```

* `scan_ltp` is the spot the OI scanner stored when it filtered the stock. It is
  the only price this project recorded at scan time.
* `close(D+n)` is the **close of the n-th completed trading session after the
  scan day**, taken from the daily candle cache.
* `sign(direction)` is `+1` for `LONG` and `-1` for `SHORT`, so a short that
  falls and a long that rises both produce a positive number.
* Values are rounded to 2 decimal places.

Per day and offset the report also returns `n`, `avg_return_pct`,
`win_rate_pct` (share of strictly positive returns), `best_return_pct` and
`worst_return_pct`. The "All days" totals pool every stock across every scan day
per offset.

### Intraday highest and lowest (D+1 … D+4)

The return formula uses closes, but each stock row also carries an intraday
extreme summary built from the candle cache's `high` and `low`:

* `highest` — the **highest high** over the first four forward sessions, with
  its D+n and price. This is the best possible exit for a **LONG**.
* `lowest` — the **lowest low** over the same four sessions. This is the best
  possible exit for a **SHORT**.
* `best_long_return_pct` = `(highest - scan_ltp) / scan_ltp * 100`.
* `best_short_return_pct` = `(scan_ltp - lowest) / scan_ltp * 100`.
* `favourable_role` is `long` for a LONG row and `short` for a SHORT row;
  `favourable_return_pct` is the matching best return and `adverse_return_pct`
  is the other extreme (the worst point). `favourable` is true when the row's
  own best point was still above `scan_ltp`.
* `window` is how many sessions the summary covered, capped at 4 even when the
  report shows more D+n columns.

If the stock has no cached candles in the window, every extreme is `null`
rather than zero.

### Which sessions count

The trading calendar is derived from the benchmark index
(`PERFORMANCE_BENCHMARK_SYMBOL`, default `NSE:NIFTY50-INDEX`) in the candle
cache. Weekends and exchange holidays are therefore skipped automatically, and
one stock's missing candle cannot shift everyone else's D+1.

Only **completed** sessions are used: any date on or after today (IST) is
excluded, so the still-forming candle of the current session never becomes a
forward return. A scan day with no completed following session is reported as
`pending`.

---

## 3. Where the prices come from

There is no stored price history for ordinary candidates, so daily closes are
cached on demand in `instrument_candles` by an admin-triggered backfill.

```
admin: "Refresh candle data"
  -> POST /api/v1/admin/performance/backfill
       -> symbols = filtered symbols of the window + benchmark
       -> CandleBackfillRun(status=PENDING) with per-symbol progress
       -> BackgroundTasks: run_backfill_job()
            -> GET /history (resolution=D) chunked over the date range
            -> normalize_candles() -> per-date OHLCV
            -> upsert into instrument_candles
```

* Requests are paced (`PERFORMANCE_HISTORY_PAUSE_SECONDS`, default 1.3s) for the
  FYERS Standard plan's 50 history requests/minute.
* A rate-limit answer is retried once after
  `PERFORMANCE_RATE_LIMIT_BACKOFF_SECONDS` (default 60s) instead of failing the
  symbol.
* An expired/rejected token **aborts the run immediately** and marks every
  remaining symbol `ERROR` with the reason; it does not retry hundreds of times.
* The upsert *updates* existing rows, so a candle fetched mid-session is replaced
  by the final close on the next refresh.
* One run at a time. A run left `RUNNING` by a restart is failed automatically
  once it is older than `PERFORMANCE_STALE_RUN_MINUTES`, so it cannot block the
  next refresh forever.

Symbol states: `PENDING`, `FETCHING`, `FETCHED`, `NO_DATA`, `ERROR`, `SKIPPED`.
Run states: `PENDING`, `RUNNING`, `COMPLETED`, `PARTIAL`, `FAILED`.

The report itself only reads `instrument_candles`, so it keeps working when the
FYERS token is expired — it just cannot show returns for symbols that are not
cached yet. Those are listed in `missing_symbols`.

---

## 4. API

All endpoints are admin-only (`require_admin`).

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/admin/performance` | Day-wise report for `date_from`/`date_to`/`forward_days` |
| `POST` | `/api/v1/admin/performance/backfill` | Start a candle refresh (202, returns the run) |
| `GET` | `/api/v1/admin/performance/backfill/latest` | Latest run, or `null` |
| `GET` | `/api/v1/admin/performance/backfill/{run_id}` | One run, for polling |

`GET /performance` accepts `include_symbols=false` to omit the per-stock rows
when only the aggregates are needed. Both dates default to "earliest candidate
→ today"; the window is capped at 366 days and `forward_days` at
`PERFORMANCE_MAX_FORWARD_DAYS`.

`status` chooses the stock set and defaults to `all`:

| `status` | Candidates included |
| --- | --- |
| `all` | Every filtered candidate, whatever its review status |
| `approved` | `APPROVED`, `PUBLISHED` and `EXPIRED` |
| `not_approved` | `PENDING` and `REJECTED` |

Anything else is rejected with `422`. The filter applies to the per-day rows and
to the totals, but **not** to the candle refresh: the cache is shared, so the
backfill still covers every symbol in the window regardless of the UI switch.

Response shape (abridged):

```json
{
  "date_from": "2026-11-09",
  "date_to": "2026-11-09",
  "forward_days": 5,
  "status_filter": "all",
  "benchmark_symbol": "NSE:NIFTY50-INDEX",
  "days": [
    {
      "day": "2026-11-09",
      "scans": 1,
      "filtered": 15,
      "long_count": 8,
      "short_count": 7,
      "duplicates_collapsed": 0,
      "pending": false,
      "offsets": [
        { "offset": 1, "trade_date": "2026-11-10", "n": 15,
          "avg_return_pct": 0.0, "win_rate_pct": 40.0,
          "best_return_pct": 1.2, "worst_return_pct": -1.2 }
      ],
      "symbols": [
        { "symbol": "DMART", "direction": "LONG", "scan_ltp": "3444.5000",
          "coverage": "COMPLETE", "closes": ["3450.0000", "..."],
          "highs": ["3462.0000", "..."], "lows": ["3431.0000", "..."],
          "returns_pct": [1.2, 1.55, 1.9, 2.25, 2.6],
          "high_low": {
            "window": 4,
            "highest": { "offset": 3, "trade_date": "2026-11-13", "price": "3521.0000" },
            "lowest":  { "offset": 1, "trade_date": "2026-11-11", "price": "3420.5000" },
            "best_long_return_pct": 2.22, "best_short_return_pct": 0.7,
            "actual_direction": "LONG", "favourable_role": "long",
            "favourable_return_pct": 2.22, "adverse_return_pct": -0.7,
            "favourable": true
          } }
      ]
    }
  ],
  "totals": { "filtered": 15, "scan_days": 1, "offsets": [ ] },
  "cache": { "data_from": "2026-11-10", "data_to": "2026-11-20",
             "candles": 144, "symbols": 16, "last_fetched_at": "..." },
  "missing_symbols": [],
  "pending_days": 0
}
```

---

## 5. Admin UI

`admin/app/(dashboard)/performance/page.tsx`, available from the sidebar as
**Performance**.

* Date window and forward-session selector (3/5/10).
* **Stock set** switch: *All stocks*, *Approved*, *Not approved*. It changes the
  query, so the stat cards, day rows and totals all describe the chosen set.
* Stat cards: filtered stocks, average D+1 return, D+1 win rate, D+3 win rate,
  candle cache coverage.
* One expandable row per scan day: scans, filtered count, long/short split, and
  for each D+n column the average return, sample size and win rate. The
  *All days* row repeats the same three numbers for the whole selection.
* Expanding a day lists every stock: direction, grade, score, scan LTP, the
  close and direction-adjusted return for each session (hover a D+n cell for
  that session's intraday high/low), plus a coverage badge (`COMPLETE`,
  `PARTIAL`, `PENDING`, `NO_DATA`).
* Two more columns per stock summarise the intraday extremes over D+1…D+4:
  **High · long** is the best exit for a long (`D+n · price · return`) and
  **Low · short** is the best exit for a short. **Signal fit** applies the
  stock's own direction to its favourable extreme — `LONG ✓ D+2` when the best
  point still beat the scan price, `LONG ✗ D+2` when it did not.
* *Refresh candle data* starts the backfill and polls the run, showing the same
  progress bar and per-symbol states as the pattern scanner.
* Warnings are shown for symbols with no cached candles, days still waiting for
  a completed session, a cache that ends before the requested window, and a
  FYERS token problem (with a pointer to Settings).

---

## 6. Configuration

| Setting | Default | Meaning |
| --- | --- | --- |
| `PERFORMANCE_FORWARD_DAYS` | `5` | Default number of forward sessions |
| `PERFORMANCE_MAX_FORWARD_DAYS` | `10` | Upper bound accepted by the API |
| `PERFORMANCE_DEFAULT_LOOKBACK_DAYS` | `30` | Window when no candidate exists yet |
| `PERFORMANCE_HISTORY_PAUSE_SECONDS` | `1.3` | Pause between history requests |
| `PERFORMANCE_HISTORY_CHUNK_DAYS` | `120` | Calendar days per history request |
| `PERFORMANCE_RATE_LIMIT_BACKOFF_SECONDS` | `60` | Wait before retrying a 429 |
| `PERFORMANCE_MAX_SYMBOLS_PER_RUN` | `400` | Safety cap on one refresh |
| `PERFORMANCE_BENCHMARK_SYMBOL` | `NSE:NIFTY50-INDEX` | Defines the trading calendar |
| `PERFORMANCE_STALE_RUN_MINUTES` | `30` | When a stuck run is failed |

---

## 7. Storage and migration

`backend/migrations/versions/b7d3e9c14a20_add_candle_cache.py` (revises
`c4a91d2f7b30`) adds two tables and changes nothing else:

* `instrument_candles` — one row per symbol per completed date
  (`open/high/low/close/volume`, `source`, `fetched_at`), unique on
  `(symbol, trade_date)`.
* `candle_backfill_runs` — run status, range, counters and per-symbol `progress`.

In development the startup hook (`Base.metadata.create_all`) creates the tables
automatically; in production run `alembic upgrade head`.

---

## 8. Limitations (read these before trusting a number)

1. **`scan_ltp` is a snapshot, not a fill.** Returns measure "spot at scan time
   → later close", not an executable P&L. Slippage, option premiums, expiry and
   position sizing are out of scope.
2. **The backfill needs a valid FYERS token.** Without one the page still loads
   but shows `missing_symbols`; nothing is invented.
3. **Symbols are mapped with the same rule as the LTP tracker**
   (`app/market_data/symbols.py`): indices to their FYERS index symbol, every
   other underlying to `NSE:<SYMBOL>-EQ`. A renamed or delisted stock will show
   as `NO_DATA`.
4. **`NO_DATA` is reported, never interpolated.** A gap stays a gap.
5. **Zero returns are not wins.** `win_rate_pct` counts strictly positive
   returns only.
6. **Coverage is per offset.** A stock can be `PARTIAL` when only some forward
   sessions are cached yet.

---

## 9. Tests

| File | Covers |
| --- | --- |
| `backend/tests/test_performance.py` | Direction adjustment, weekend/holiday alignment, today's candle exclusion, dedupe, missing data, pattern isolation, API validation |
| `backend/tests/test_candle_cache.py` | Normalization, chunking (incl. the one-day tail), pacing, 429 retry, auth abort, upsert of a partial candle, run lifecycle, progress, API round-trip |
| `backend/tests/test_candle_migration.py` | Upgrade creates both tables, OI data survives, downgrade removes only the new tables |
