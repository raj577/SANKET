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

export interface Scan {
  id: string;
  started_at: string;
  completed_at: string | null;
  status: string;
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
  tracking_enabled: boolean;
  poll_interval_seconds: number;
  active_signals: number;
  last_price_update: string | null;
}
