export type Role = "ADMIN" | "USER";

export interface User {
  id: string;
  name: string;
  email: string;
  role: Role;
  is_active: boolean;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export type ScanType = "OI" | "AVWAP_PATTERN";

export interface Scan {
  id: string;
  started_at: string;
  completed_at: string | null;
  status: string;
  scan_type: ScanType;
  timeframe: string | null;
  total_symbols: number;
  successful_symbols: number;
  failed_symbols: number;
  long_candidates_count: number;
  short_candidates_count: number;
  csv_filename: string | null;
  csv_storage_path: string | null;
  csv_size_bytes: number | null;
  csv_saved_at: string | null;
  csv_checksum_sha256: string | null;
  scanner_version: string | null;
  candidates_processed: boolean;
  last_progress_symbol: string | null;
  trigger: string | null;
  error_message: string | null;
  created_at: string;
}

export interface ScanDetail extends Scan {
  scanner_config: Record<string, unknown> | null;
  warnings: string[];
  pattern_config: Record<string, unknown> | null;
  pattern_summary: PatternSummary | null;
  pattern_candidates: PatternCandidate[];
  pattern_progress: PatternProgress | null;
  pattern_symbols: PatternSymbolProgress[];
}

/** Progress bar state for one pattern run. */
export interface PatternProgress {
  state: "queued" | "running" | "finished";
  processed: number;
  total: number;
  percent: number;
  matched: number;
  failed: number;
  pending: number;
}

export type PatternSymbolStatus =
  | "PENDING"
  | "SCANNING"
  | "MATCHED"
  | "NO_PATTERN"
  | "NO_DATA"
  | "SKIPPED"
  | "ERROR";

/** One row of the per-instrument progress list. */
export interface PatternSymbolProgress {
  symbol: string;
  underlying: string | null;
  expiry: string | null;
  status: PatternSymbolStatus;
  pattern_type: PatternCandidate["pattern_type"] | null;
  message: string | null;
  candles: number | null;
  last_price: string | null;
}

/**
 * One AVWAP pattern detection. The detector has no confidence score, so none
 * is exposed here.
 */
export interface PatternCandidate {
  id: string;
  scan_id: string;
  symbol: string;
  underlying: string | null;
  expiry: string | null;
  timeframe: string;
  pattern_type: "AVWAP TOUCH" | "AVWAP HUGGING" | "AVWAP CONSOLIDATION" | "AVWAP RECLAIM";
  candle_count: number;
  last_price: string;
  avwap: string;
  distance_pct: string;
  avg_body_ratio: string;
  max_body_ratio: string;
  window_range_pct: string;
  touched: boolean;
  atr: string | null;
  anchor_at: string | null;
  pattern_start: string | null;
  pattern_end: string | null;
  status: "PENDING" | "APPROVED" | "REJECTED" | "PUBLISHED" | "EXPIRED";
  reason: string;
  detector_metadata: Record<string, unknown> | null;
  created_at: string;
}

export interface PatternSummary {
  timeframe: string | null;
  matches: number;
  instruments_resolved: number;
  errors: number;
  classification_counts: Record<string, number>;
}

export interface CandidateHistory {
  /** The stock also passed the scan run immediately before this row's scan. */
  in_previous_scan: boolean;
  /** The stock passed a scan on one of the two previous scan days. */
  in_last_2_days: boolean;
  /** Latest direction on those two previous scan days, when unambiguous. */
  previous_direction: "LONG" | "SHORT" | null;
  /** The two previous scan days ended SHORT and this row is LONG. */
  short_to_long: boolean;
  /** Most recent earlier scan that contained the stock. */
  previous_seen_at: string | null;
}

export interface Candidate {
  id: string;
  scan_id: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  scan_ltp: string;
  score: string;
  grade: string;
  reason: string;
  confirmation_count: number;
  scanned_at: string;
  status: "PENDING" | "APPROVED" | "REJECTED" | "PUBLISHED" | "EXPIRED";
  created_at: string;
  history?: CandidateHistory | null;
}

export interface Signal {
  id: string;
  candidate_id: string;
  symbol: string;
  direction: "LONG" | "SHORT";
  scan_ltp: string;
  entry_price: string;
  target_price: string;
  stop_loss: string | null;
  current_ltp: string | null;
  price_updated_at: string | null;
  published_at: string;
  target_hit_at: string | null;
  stoploss_hit_at: string | null;
  closed_at: string | null;
  status: string;
  created_by: string | null;
  updated_at: string;
  pnl_percent: number | null;
  target_progress_percent: number | null;
  signal_move_percent: number | null;
  target_reached: boolean;
  price_freshness: "LIVE" | "DELAYED" | "STALE" | "UNKNOWN";
}

export interface PricePoint {
  id: number;
  ltp: string;
  captured_at: string;
  event_type: string;
}

export interface SignalDetail extends Signal {
  reason: string | null;
  grade: string | null;
  score: string | null;
  scan_timestamp: string | null;
  price_history: PricePoint[];
}

export interface Archive {
  scan_id: string;
  status: string;
  started_at: string;
  csv_filename: string | null;
  csv_storage_path: string | null;
  csv_size_bytes: number | null;
  csv_checksum_sha256: string | null;
  csv_saved_at: string | null;
  download_url: string | null;
}

export interface DashboardOverview {
  today_scans: number;
  total_scanned_stocks: number;
  successful_scans: number;
  failed_scans: number;
  long_candidates: number;
  short_candidates: number;
  pending_approvals: number;
  published_signals: number;
  active_signals: number;
  target_hits: number;
  stoploss_hits: number;
  csv_archive_count: number;
  collector_status: string;
  fyers_status: string;
  market_data_provider: string;
  market_data_status: string;
  stream_transport: string;
}

export interface AuditLog {
  id: string;
  user_id: string | null;
  user_email: string | null;
  action: string;
  entity_type: string;
  entity_id: string | null;
  details: Record<string, unknown> | null;
  created_at: string;
}

export type SettingsMap = Record<string, Record<string, unknown>>;

export interface SettingsResponse {
  settings: SettingsMap;
}

export interface MarketStatus {
  provider: string;
  configured: boolean;
  stream_ready: boolean;
  transport: string;
  tracking_enabled: boolean;
  poll_interval_seconds: number;
  active_signals: number;
  last_price_update: string | null;
}

/**
 * Secret-free FYERS authentication status from
 * `GET /api/v1/market/fyers/status`. The access token is never part of it.
 */
export interface FyersStatus {
  token_file: string;
  encryption_configured: boolean;
  credentials_configured: boolean;
  token_present: boolean;
  token_valid: boolean;
  expires_at: string | null;
  authenticated_at: string | null;
  seconds_remaining: number | null;
  source: string | null;
  reauth_required: boolean;
  expires_soon: boolean;
  error: string | null;
  provider: string;
  app_id: string | null;
  redirect_uri: string;
  login_available: boolean;
  market_data_configured: boolean;
  stream_ready: boolean;
}

/** Day-wise performance of the OI scanner's filtered candidates. */

export type PerformanceCoverage = "COMPLETE" | "PARTIAL" | "PENDING" | "NO_DATA";

export interface PerformanceOffset {
  offset: number;
  trade_date: string | null;
  n: number;
  avg_return_pct: number | null;
  win_rate_pct: number | null;
  best_return_pct: number | null;
  worst_return_pct: number | null;
}

export interface PerformanceExtreme {
  /** 1-based forward session (D+n), only from the first four sessions. */
  offset: number | null;
  trade_date: string | null;
  price: string | null;
}

export interface PerformanceHighLow {
  /** How many forward sessions the extremes cover (at most 4). */
  window: number;
  /** Highest intraday high — the best exit for a long. */
  highest: PerformanceExtreme;
  /** Lowest intraday low — the best exit for a short. */
  lowest: PerformanceExtreme;
  best_long_return_pct: number | null;
  best_short_return_pct: number | null;
  actual_direction: "LONG" | "SHORT";
  /** Which extreme matches the row's own direction. */
  favourable_role: "long" | "short";
  favourable_return_pct: number | null;
  adverse_return_pct: number | null;
  /** True when the favourable extreme still beat scan_ltp. */
  favourable: boolean | null;
}

export interface PerformanceSymbol {
  candidate_id: string;
  scan_id: string;
  symbol: string;
  provider_symbol: string;
  direction: "LONG" | "SHORT";
  grade: string;
  score: string;
  scan_ltp: string;
  scanned_at: string;
  candidate_status: string;
  coverage: PerformanceCoverage;
  /** One close per forward session, aligned with the day's `offsets`. */
  closes: (string | null)[];
  /** Intraday high per forward session, aligned with `closes`. */
  highs: (string | null)[];
  /** Intraday low per forward session, aligned with `closes`. */
  lows: (string | null)[];
  /** Direction-adjusted % return per forward session. */
  returns_pct: (number | null)[];
  /** Highest high / lowest low over D+1..D+4, and the direction fit. */
  high_low?: PerformanceHighLow | null;
}

export interface PerformanceDay {
  day: string;
  scans: number;
  filtered: number;
  long_count: number;
  short_count: number;
  duplicates_collapsed: number;
  /** True when candles exist but no completed session follows this scan day. */
  pending: boolean;
  offsets: PerformanceOffset[];
  symbols: PerformanceSymbol[];
}

export interface PerformanceReport {
  date_from: string;
  date_to: string;
  forward_days: number;
  /** Which stock set the numbers describe. */
  status_filter: "all" | "approved" | "not_approved";
  benchmark_symbol: string;
  generated_at: string;
  days: PerformanceDay[];
  totals: {
    filtered: number;
    scan_days: number;
    offsets: PerformanceOffset[];
  };
  cache: {
    data_from: string | null;
    data_to: string | null;
    candles: number;
    symbols: number;
    last_fetched_at: string | null;
  };
  missing_symbols: string[];
  pending_days: number;
}

export interface CandleBackfillSymbol {
  symbol: string;
  state: "PENDING" | "FETCHING" | "FETCHED" | "NO_DATA" | "ERROR" | "SKIPPED";
  candles: number;
  message: string | null;
}

export interface CandleBackfill {
  run_id: string;
  status: "PENDING" | "RUNNING" | "COMPLETED" | "PARTIAL" | "FAILED";
  state: "queued" | "running" | "finished";
  range_from: string;
  range_to: string;
  started_at: string;
  completed_at: string | null;
  total_symbols: number;
  processed_symbols: number;
  failed_symbols: number;
  candles_written: number;
  percent: number;
  fetched: number;
  no_data: number;
  pending: number;
  current: string | null;
  error_message: string | null;
  symbols: CandleBackfillSymbol[];
}
