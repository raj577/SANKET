# AVWAP / Pattern Scanner

The AVWAP pattern scanner is a **second, independent scan type** in the backend.
It detects contract-start AVWAP touch/hugging/consolidation/reclaim patterns on
NSE futures contracts and stores each detection as a reviewable candidate.

It was ported from the standalone `fyers-avwap-scanner` project. The detector
rules, thresholds, ATR/body-ratio/tolerance filters and classification order are
**the original ones** — nothing was re-tuned. The only deliberate differences are
transport (the scanner reuses this project's existing `FyersClient`) and
persistence (detections are stored in this project's database).

The OI scanner is untouched: no OI scoring, thresholds, CSV columns or API
contracts changed. The two scanners share only the FYERS HTTP client and generic
admin infrastructure (auth, audit log, scan runs).

---

## 1. Module layout

```
backend/app/scanner/patterns/
  __init__.py            public exports
  models.py              Instrument, PatternConfig, DetectedPattern, ScanReport
  detector.py            PatternDetector (touch/hugging/consolidation/reclaim)
  engine.py              enrich_frame(), scan_instruments()
  candles.py             normalize_candles(), drop_incomplete_candles()
  history.py             FYERS history + NSE futures instrument master
  indicators/
    avwap.py             contract-start AVWAP (+ distance helper)
    vwap.py              session VWAP (resets per IST trading day)
    atr.py               Wilder ATR

backend/app/services/pattern_scan_service.py   scan lifecycle, persistence, review
backend/app/api/admin.py                       admin endpoints
backend/app/models/scan.py                     ScanRun.scan_type/timeframe, PatternCandidate
backend/migrations/versions/c4a91d2f7b30_add_pattern_scanner.py
admin/app/(dashboard)/scans/page.tsx           "AVWAP / Pattern Scanner" card + modal
admin/lib/types.ts                             pattern/scan types
backend/tests/test_patterns_*.py               pattern tests
backend/tests/test_oi_regression.py            OI regression guards
```

Nothing in `app/scanner/patterns/` imports the OI scanner, and the OI scanner
does not import the pattern package.

---

## 2. Data flow

```
admin request
  -> pattern_scan_service.create_scan()            ScanRun(scan_type=AVWAP_PATTERN)
  -> BackgroundTasks: run_scan_job()
       -> resolve instruments (explicit symbols or current-expiry futures universe)
       -> PatternHistoryService.fetch()            FYERS /history, chunked, epoch range
       -> normalize_candles()                      tz-aware, sorted, deduplicated
       -> drop_incomplete_candles()                completed bars only (15:30 IST session close)
       -> enrich_frame()                           avwap + session_vwap + atr
       -> PatternDetector.detect()                 pattern or None
       -> persist PatternCandidate rows + ScanRun execution metadata
```

The full history of the contract is requested (default lookback of 120 days,
which is longer than an NSE futures contract can live). The **first available
candle is the AVWAP anchor**, so the AVWAP is cumulative from contract start and
is never reset at session boundaries. Session VWAP is computed separately and
only used by optional filters and chart context.

Requests use `cont_flag="0"` so candles belong to the specific contract, not a
continuous series. Successive history calls are spaced by
`PATTERN_HISTORY_PAUSE_SECONDS` (default 1.3 s ≈ 46 requests/minute, under the
FYERS Standard plan limit of 50/minute); a 429 is retried after a 60-second
pause so one exhausted minute does not fail a symbol. The last chunk also
absorbs a 1-day tail so a lookback that is an exact multiple of the chunk size
never produces a zero-width `range_from == range_to` request that FYERS rejects.
A window with no candles comes back as `s="no_data"`; that is treated as an
empty range, so a recently listed contract whose first chunk predates its first
candle still scans its newer chunk.

---

## 3. Detection rules (original thresholds)

Candles are eligible when, for the AVWAP at that bar:

| Rule | Default | Meaning |
|---|---|---|
| `max_close_above_pct` | `0.005` (0.5%) | Close at most 0.5% above AVWAP |
| `max_close_below_pct` | `0.002` (0.2%) | Close at most 0.2% below AVWAP |
| `max_low_below_pct` | `0.003` (0.3%) | Low not more than 0.3% below AVWAP |
| `max_body_ratio` | `0.35` | Body / range ≤ 0.35 (small candle) |
| `max_candle_range_atr` | `2.0` | Range ≤ 2 × ATR **when ATR is valid** |
| `min_candles` / `max_candles` | `1` / `5` | Pattern length window |
| `max_window_range_pct` | `0.02` (2%) | Whole pattern must be this narrow vs AVWAP |
| `touch_tolerance_pct` | `0.001` (0.1%) | "Touched" tolerance |
| `consolidation_min_candles` | `3` | Minimum bars for consolidation |
| `consolidation_range_pct` | `0.01` (1%) | Consolidation window width |
| `hugging_min_candles` | `2` | Minimum bars for hugging |

ATR is Wilder's ATR(14) and is `NaN` until 14 true ranges exist. While it is
invalid the ATR range cap is skipped (also original behaviour).

The detector evaluates the **right edge** of the series: the last candle must
qualify, then the longest contiguous run of qualifying candles (at most
`max_candles`) is taken, shortening from the oldest side until the whole window
is within `max_window_range_pct`.

### Classifications

Evaluated in this exact order:

1. **`AVWAP RECLAIM`** — ≥ 2 candles, an earlier close was below AVWAP, and the
   final close is above it.
2. **`AVWAP CONSOLIDATION`** — ≥ 3 candles and window range ≤ 1% of AVWAP.
3. **`AVWAP HUGGING`** — ≥ 2 candles.
4. **`AVWAP TOUCH`** — a single candle, or the window touched AVWAP within the
   touch tolerance; otherwise `AVWAP HUGGING`.

There is **no confidence score**: the original detector has none, and none is
invented here.

Optional filters (off by default, kept at their original defaults):
`require_close_above_avwap`, `require_close_above_vwap`, `below_reference`
(`off`/`avwap`/`vwap`/`either`), `below_candle`
(`previous`/`second_previous`/`either`), `allowed_patterns`.

---

## 4. Persistence and migration

Migration `c4a91d2f7b30` (`down_revision = 9f3c1a7b2d10`):

* `scan_runs.scan_type` — `NOT NULL`, server default `'OI'`; existing rows
  therefore read as `OI` with no data migration.
* `scan_runs.timeframe` — nullable, for list display (`5`, `15`, `60`, `D`).
* `pattern_candidates` — new table, foreign key to `scan_runs.id`
  (`ON DELETE CASCADE`), with status and pattern-type check constraints and
  indexes on `scan_id`, `status`, `pattern_type`, `symbol`.
* The existing `scan_candidates` (OI) table is **not** altered.

`pattern_candidates` columns: `scan_id`, `symbol`, `underlying`, `expiry`,
`timeframe`, `pattern_type`, `candle_count`, `last_price`, `avwap`,
`distance_pct`, `avg_body_ratio`, `max_body_ratio`, `window_range_pct`,
`touched`, `atr`, `anchor_at`, `pattern_start`, `pattern_end`, `status`,
`reason`, `detector_metadata` (the detector's full metadata as JSON), `id`,
`created_at`.

Review statuses: `PENDING`, `APPROVED`, `REJECTED`, `PUBLISHED`, `EXPIRED`.
Approve/reject writes an admin audit-log entry. Pattern candidates are
**review-only** and are not published as OI signals.

---

## 5. Admin API

All endpoints require an admin bearer token.

### Start a scan

`POST /api/v1/admin/scans/pattern` → `202 Accepted`

```json
{
  "symbols": ["NSE:NIFTY26NOVFUT"],
  "timeframe": "60",
  "include_index": true,
  "current_expiry_only": true
}
```

| Field | Notes |
|---|---|
| `symbols` | Optional. Full FYERS symbols (`NSE:...FUT`) or bare underlyings (`NIFTY`, `BANKNIFTY`). Omit to scan the current-expiry NSE futures universe. Deduplicated; validated against `[A-Z0-9:_.-]`; maximum `PATTERN_MAX_SYMBOLS` (25). |
| `timeframe` | Optional. Defaults to `PATTERN_DEFAULT_TIMEFRAME` (`60`). Allowed: `PATTERN_TIMEFRAMES` (`5,15,60,D`). |
| `include_index` | Include NIFTY/BANKNIFTY/FINNIFTY/MIDCPNIFTY/NIFTYNXT50 futures. |
| `current_expiry_only` | Only the nearest non-expired expiry per underlying. |

Errors: `401` unauthenticated, `409` when FYERS is not configured, `422` for an
unsupported timeframe, an invalid symbol or too many symbols.

The response body is the normal `ScanOut` with `scan_type = "AVWAP_PATTERN"` and
`timeframe` set; the run then progresses in the background.

### List scans

`GET /api/v1/admin/scans`

* Defaults to `scan_type=OI`, so the pre-existing OI listing contract is
  unchanged.
* The pattern card requests `?scan_type=AVWAP_PATTERN`.

### Scan detail

`GET /api/v1/admin/scans/{scan_id}` — for a pattern run the detail adds:

* `pattern_config` — the detector configuration used for the run.
* `pattern_summary` — match count, resolved instruments, error count and
  per-classification counts.
* `pattern_candidates[]` — instrument, timeframe, pattern type, detection
  timestamp, AVWAP, last price, distance %, body-ratio/window-range values, ATR,
  touch flag, review status, and `detector_metadata` (start/end indexes, anchor
  timestamp, ATR, etc.). No confidence field.
* `pattern_progress` — the live progress snapshot:
  `{state, processed, total, percent, matched, failed, pending}`. `state` is
  `queued`, `running` or `finished`, so a running scan can be polled every couple
  of seconds without touching the OI endpoints.
* `pattern_symbols[]` — one row per requested instrument:
  `{symbol, underlying, expiry, status, pattern_type, message, candles, last_price}`.
  `status` is one of `PENDING`, `SCANNING`, `MATCHED`, `NO_PATTERN`, `NO_DATA`,
  `SKIPPED` or `ERROR`. Symbols that fail to resolve are listed first as `ERROR`
  with the resolution message.

For an OI run these fields stay `null`/empty.

### Live progress

The background job persists the symbol list before the first candle request, then
updates it after every instrument (one short commit per symbol). Progress lives in
`scanner_config.progress` / `scanner_config.symbols`, so it survives a backend
restart and is returned by the same detail endpoint. `percent` is derived from
`processed / total`; the scan counters (`total_symbols`, `successful_symbols`,
`failed_symbols`, `last_progress_symbol`) are updated at the same time.

### Review

* `GET /api/v1/admin/pattern-candidates?scan_id=&status=&pattern_type=`
* `POST /api/v1/admin/pattern-candidates/{id}/approve`
* `POST /api/v1/admin/pattern-candidates/{id}/reject` — body `{"reason": "..."}`

`409` for a published/expired candidate, `404` for an unknown id.

### Execution metadata

Every run persists `scanner_config` with the detector settings and an
`execution` block: start/finish timestamps, duration in ms, instruments
requested/resolved, match count, per-symbol errors, resolution errors,
classification counts and per-symbol candle ranges. Fatal failures are recorded
in `execution.fatal_error` with `scan.status = FAILED`.

---

## 6. Admin UI

`/scans` now shows two independent cards:

* the unchanged **OI scans** card (queued OI runs + scan-run table), and
* **AVWAP / Pattern Scanner** — symbol textarea (blank = current-expiry futures
  universe), timeframe selector (5/15/60/daily), *Run pattern scan*, a live
  progress bar with the per-symbol list, and a separate pattern scan-run list.

The live panel appears as soon as a run is queued and polls the scan detail every
two seconds while the run is `PENDING`/`RUNNING`. It shows the percentage,
processed/total, matched/failed/pending counts, and a scrollable symbol table
(symbol, expiry, status, classification, candle count, last price, note). The
panel is also rendered in the detail modal for any historical run, and a running
scan found in the list is adopted automatically after a page reload.

The modal shows status, timeframe, instrument counts, detected-pattern counts by
classification, the candidate table (last price, AVWAP, distance, ATR, detection
time, review status) with Approve/Reject buttons, plus the detector configuration
and execution metadata. Pattern scans never appear in the OI table and pattern
counts never appear in the OI dashboard metrics.

---

## 7. Configuration

| Setting | Default | Purpose |
|---|---|---|
| `PATTERN_DEFAULT_TIMEFRAME` | `60` | Timeframe when the request omits one |
| `PATTERN_TIMEFRAMES` | `5,15,60,D` | Accepted timeframes |
| `PATTERN_LOOKBACK_DAYS` | `120` | History depth requested per contract |
| `PATTERN_HISTORY_CHUNK_DAYS` | `60` | FYERS history chunk size |
| `PATTERN_HISTORY_PAUSE_SECONDS` | `1.3` | Minimum gap between FYERS history requests (46/min, under the 50/min plan limit) |
| `PATTERN_MAX_SYMBOLS` | `25` | Maximum explicit symbols per run |
| `PATTERN_INSTRUMENT_MASTER_URL` | `https://public.fyers.in/sym_details/NSE_FO.csv` | NSE F&O master |
| `PATTERN_INSTRUMENT_CACHE_TTL_SECONDS` | `3600` | Instrument-master cache lifetime |

FYERS must be connected (`FYERS_APP_ID` + a stored/`FYERS_ACCESS_TOKEN` token)
before a pattern scan can start; otherwise the endpoint returns `409`. The
scanner makes market-data calls only.

---

## 8. Tests

```powershell
cd backend
..\.venv\Scripts\python.exe -m pytest -q
```

Pattern coverage:

| File | What it locks down |
|---|---|
| `test_patterns_detector.py` | Ported detector suite: 1–5 candle detection, every classification, tolerance/ATR/body rejections, optional close/below filters, config validation, default thresholds, metadata shape (no confidence/score) |
| `test_patterns_indicators.py` | AVWAP known values/anchor/zero volume, contract-start vs session VWAP, ATR NaN window, completed-candle logic, normalization (epoch ms/s, sorting, dedupe, invalid rows) |
| `test_patterns_history.py` | Chunked FYERS fetch, epoch/ISO ranges, clipping, single-day tail merge, request pacing, retry vs auth-failure, no-data, insufficient candles, instrument-master parsing/filtering, symbol resolution |
| `test_patterns_persistence.py` | Scan creation, candidate persistence and metadata, classification round-trips, PARTIAL/FAILED paths, expired contracts, auth abort, summary counts, per-symbol progress (`MATCHED`/`NO_PATTERN`/`NO_DATA`/`SKIPPED`/`ERROR`) and stopped-run handling |
| `test_patterns_api.py` | Admin auth, provider-not-configured 409, request validation, 202 lifecycle, OI/pattern list split, detail payload with `pattern_progress`/`pattern_symbols`, approve/reject, OI publish guard, audit entry |
| `test_patterns_migration.py` | Real Alembic upgrade/downgrade on SQLite: existing OI row survives with `scan_type='OI'`, new columns/table, OI tables untouched |
| `test_oi_regression.py` | OI CSV counts (8 long / 7 short), OI pipeline publish, OI list/overview isolation, pattern runs create no OI candidates |
| `test_fyers_client.py` | `s="no_data"` treated as an empty history range, real errors still raised, blank messages carry the FYERS status/code, non-history endpoints still reject `no_data` |

Current result: **204 passed**.

---

## 9. Known limitations

* FYERS Standard plan allows **50 history requests per minute**. A full
  current-expiry universe run (224 contracts, two ~60-day chunks each) therefore
  takes roughly ten to twenty minutes at the default
  `PATTERN_HISTORY_PAUSE_SECONDS=1.3`. The job retries a 429 after 60 seconds, so
  an exhausted quota delays the scan instead of failing the symbol, but it does
  not raise the plan limit.
* Run **one pattern scan at a time**. Two concurrent runs share the same
  50/minute quota and will stall each other with repeated 60-second 429 backoffs.
* Live verification from the local stack: a two-contract scan fetched 373
  completed candles each and returned `NO_PATTERN`; a 12-contract scan completed
  with 0 errors while the progress bar advanced 8% → 100%; a full 224-contract
  current-expiry run finished `PARTIAL` with 2 detections
  (`COCHINSHIP` AVWAP CONSOLIDATION, `SOLARINDS` AVWAP TOUCH), 210 `NO_PATTERN`,
  and 12 contracts whose first 60-day chunk was empty. That empty chunk was
  fixed: FYERS replies `s="no_data"` for a window with no candles, which is now
  treated as an empty range instead of an error, and a re-scan of all 12
  contracts completed with 0 errors (83–211 candles each).
* The instrument master is downloaded from FYERS at runtime; if that CSV shape
  changes, `parse_instrument_master` reports `InstrumentMasterError` rather than
  guessing.
* Detection uses completed candles only. During a session the newest bar is
  dropped until it completes (final 15:15–15:30 bar completes at 15:30 IST).
* Matches are written to `pattern_candidates` when the run finishes, while the
  per-symbol progress list is updated continuously. If the backend is killed
  mid-run, the symbol list can show `MATCHED` with no candidate row; the scan is
  marked `FAILED` on the next startup cleanup.
* Pattern candidates are review-only; there is no publishing path and no
  confidence score by design.
