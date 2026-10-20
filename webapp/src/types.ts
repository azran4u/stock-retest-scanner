export type Kind = 'zone' | 'long' | 'line' | 'note';
export type DStatus = 'active' | 'review' | 'approved' | 'rejected' | 'obsolete';

export interface Drawing {
  id: string;
  ticker: string;
  kind: Kind;
  zone_top: number | null;
  zone_bottom: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  t_start: string | null;
  t_end: string | null;
  source: 'user' | 'bot';
  status: DStatus;
  note: string | null;
  created_at?: string;
  updated_at?: string;
}

export interface Label {
  ticker: string;
  label: string;
  value: string;
  note: string | null;
  asof: string;
  created_at?: string;
}

export interface Command {
  id: number;
  ticker: string | null;
  text: string;
  status: 'pending' | 'done' | 'error';
  reply: string | null;
  created_at: string;
  done_at: string | null;
}

export interface TvDrawing {
  ticker: string;
  source: 'tv';
  owner: string | null;
  zone_top: number | null;
  zone_bottom: number | null;
  entry: number | null;
  stop: number | null;
  target: number | null;
  rr: number | null;
  read_date: string | null;
}

export interface Row {
  ticker: string;
  status: string;
  badges: string[];
  current_price?: number | null;
  tv_rr?: number | null;
  tv_zone_top?: number | null;
  tv_zone_bottom?: number | null;
  tv_zone_dist_atr?: number | null;
  tv_source?: string | null;
  tv_stale?: string | null;
  tv_stale_detail?: string | null;
  days_to_earnings?: number | null;
  weekly_atr?: number | null;
  hammer_rr?: number | null;
  hammer_score?: number | null;
  hammer_calm_weeks?: number | null;
  hammer_entry?: number | null;
  hammer_sl?: number | null;
  hammer_tp?: number | null;
  last_week_reversal_kind?: string | null;
  f_technical?: boolean | null;
  has_candles?: boolean;
  tradingview_url?: string | null;
  [k: string]: unknown;
}

export interface Bar { time: string; open: number; high: number; low: number; close: number; volume: number }
