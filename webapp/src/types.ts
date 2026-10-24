export type Kind = 'zone' | 'long' | 'line' | 'note';
export type DStatus = 'active' | 'review' | 'approved' | 'rejected' | 'obsolete' | 'deleted';

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
  source: 'user' | 'bot' | 'tv';
  status: DStatus;
  note: string | null;
  tv_key?: string | null;
  /** bot rows: {rule_version, why{...}}; bot rows he edited: + bot_before{levels}, edited_at */
  meta?: Record<string, any> | null;
  created_at?: string;
  updated_at?: string;
}

export interface Label {
  ticker: string;
  label: string;
  value: string;
  note: string | null;
  asof: string;
  until?: string | null;
  created_at?: string;
}

export interface Watch { ticker: string; note: string | null; added_at?: string }

export interface Command {
  id: number;
  ticker: string | null;
  text: string;
  status: 'pending' | 'done' | 'error';
  reply: string | null;
  created_at: string;
  done_at: string | null;
  /** 'command' (free text) | 'feedback' (bot drawing feedback, payload = FeedbackPayload) */
  kind?: string | null;
  payload?: Record<string, any> | null;
}

export type FeedbackCategory = 'structure' | 'zone' | 'position' | 'approved';
export interface Feedback {
  ticker: string;
  drawing_ids: string[];
  category: FeedbackCategory;
  note: string | null;
  before: Record<string, any> | null;
  after: Record<string, any> | null;
  rule_version: string | null;
  why: Record<string, any> | null;
  command_id?: number | null;
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
  /** WAIT rule (healthy red last completed week on above-average volume) */
  f_no_red_vol_week?: boolean | null;
  red_vol_week_date?: string | null;
  red_vol_body_pct?: number | null;
  red_vol_ratio?: number | null;
  red_vol_detail?: string | null;
  /** Eyal 2026-10-24 (USB): back in the zone from below = not interesting until a weekly close above the zone top */
  f_from_above?: boolean | null;
  from_above_side?: string | null;
  from_above_date?: string | null;
  from_above_detail?: string | null;
  /** last completed weekly closes (oldest first), for the live from-above check */
  wk_closes?: number[] | null;
  wk_closes_end?: string | null;
  has_candles?: boolean;
  /** FinViz sector / industry (export_data.attach_sectors); null = unknown */
  sector?: string | null;
  industry?: string | null;
  tv_entry?: number | null;
  tv_sl?: number | null;
  tv_tp?: number | null;
  tradingview_url?: string | null;
  [k: string]: unknown;
}

export interface Bar { time: string; open: number; high: number; low: number; close: number; volume: number }
