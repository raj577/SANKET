export interface User {
  id: string;
  name: string;
  email: string;
  role: "ADMIN" | "USER";
  is_active: boolean;
  created_at: string;
}

export interface Page<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
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

export interface SignalSummary {
  total: number;
  active: number;
  target_hit: number;
  stoploss_hit: number;
  expired: number;
  cancelled: number;
  today_published: number;
  yesterday_published: number;
  target_hits_today: number;
  target_hits_yesterday: number;
  last_price_update: string | null;
}
