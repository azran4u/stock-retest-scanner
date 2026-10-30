// Data layer: Supabase (real) or in-memory (demo mode, ?demo=1, for screenshots / offline tests).
import { createClient, type SupabaseClient, type Session } from '@supabase/supabase-js';
import type { Command, Drawing, Feedback, Label, TvDrawing, Watch } from './types';
import { normPosition, type Position } from './positions';
import type { Research } from './research';
import type { StockList } from './lists';

export const SUPABASE_URL = 'https://wkkdblnykgolqijzagva.supabase.co';
export const SUPABASE_KEY = 'sb_publishable_yjtRuTIx0PrxQcdnlfU_Dw_IcJDxi4D';
export const OWNER_EMAIL = 'azran4u@gmail.com';

export type Table = 'drawings' | 'labels' | 'commands' | 'watchlist' | 'positions' | 'stock_lists';
export type ChangeFn = (table: Table, event: 'INSERT' | 'UPDATE' | 'DELETE', row: any, old: any) => void;

export interface Api {
  demo: boolean;
  session(): Promise<{ email: string | null }>;
  onAuth(fn: (email: string | null) => void): void;
  sendLink(email: string): Promise<void>;
  verifyCode(email: string, code: string): Promise<void>;
  signOut(): Promise<void>;
  /** data file (index.json, candles/T.json ...) from the private bucket 'app-data'; demo: undefined (local data/) */
  dataFetch?(path: string): Promise<Response>;
  /** Google sign-in (Eyal 2026-10-30). Shown only when the project's Google provider is on (auth settings), or ?google=1 */
  googleEnabled(): Promise<boolean>;
  signInGoogle(): Promise<void>;
  /** his own stock lists (table stock_lists, owner-only RLS) */
  loadLists(): Promise<StockList[]>;
  saveList(l: StockList): Promise<void>;
  deleteList(id: string): Promise<void>;
  loadDrawings(): Promise<Drawing[]>;
  insertDrawing(d: Partial<Drawing>): Promise<Drawing>;
  updateDrawing(id: string, patch: Partial<Drawing>): Promise<void>;
  deleteDrawing(id: string): Promise<void>;
  loadLabels(): Promise<Label[]>;
  upsertLabel(l: Label): Promise<void>;
  loadCommands(): Promise<Command[]>;
  addCommand(ticker: string | null, text: string, kind?: string, payload?: Record<string, any> | null): Promise<Command>;
  addFeedback(f: Feedback): Promise<void>;
  loadWatch(): Promise<Watch[]>;
  addWatch(ticker: string): Promise<void>;
  removeWatch(ticker: string): Promise<void>;
  /** open positions (read-only; owner-only RLS; mirrored from positions.json by positions.py supabase-sql) */
  loadPositions(): Promise<Position[]>;
  /** stock overviews (read-only; owner-only RLS; written by the bot) */
  loadResearch(): Promise<Research[]>;
  subscribe(fn: ChangeFn): void;
}

function check<T>(r: { data: T; error: any }): T {
  if (r.error) throw new Error(r.error.message || String(r.error));
  return r.data;
}

class SupaApi implements Api {
  demo = false;
  sb: SupabaseClient;
  constructor() {
    this.sb = createClient(SUPABASE_URL, SUPABASE_KEY, {
      auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true, flowType: 'implicit' },
    });
  }
  async session() {
    const { data } = await this.sb.auth.getSession();
    return { email: data.session?.user?.email ?? null };
  }
  onAuth(fn: (email: string | null) => void) {
    this.sb.auth.onAuthStateChange((_e, s: Session | null) => fn(s?.user?.email ?? null));
  }
  async sendLink(email: string) {
    const redirect = location.origin + import.meta.env.BASE_URL;
    check(await this.sb.auth.signInWithOtp({ email, options: { emailRedirectTo: redirect, shouldCreateUser: true } }));
  }
  async verifyCode(email: string, code: string) {
    check(await this.sb.auth.verifyOtp({ email, token: code.trim(), type: 'email' }));
  }
  async signOut() { await this.sb.auth.signOut(); }
  async dataFetch(path: string) {
    const { data } = await this.sb.auth.getSession();
    const tok = data.session?.access_token;
    if (tok) {
      try {
        const r = await fetch(`${SUPABASE_URL}/storage/v1/object/authenticated/app-data/${path}`, { headers: { Authorization: 'Bearer ' + tok, apikey: SUPABASE_KEY }, cache: 'no-cache' });
        if (r.ok) return r;
      } catch { /* network: fall through */ }
    }
    // transition only: the static copy on the old host (removed once the repo is private)
    return fetch(import.meta.env.BASE_URL + 'data/' + path, { cache: 'no-cache' });
  }
  async googleEnabled() {
    if (new URLSearchParams(location.search).has('google')) return true;
    try {
      const r = await fetch(SUPABASE_URL + '/auth/v1/settings', { headers: { apikey: SUPABASE_KEY } });
      return !!(await r.json())?.external?.google;
    } catch { return false; }
  }
  async signInGoogle() {
    // only the owner account is allowed: login_hint pre-selects it; the server rejects any other new user
    // (trigger srs_owner_only_signup on auth.users) and RLS on every table checks the JWT email.
    const redirectTo = location.origin + import.meta.env.BASE_URL;
    check(await this.sb.auth.signInWithOAuth({ provider: 'google', options: { redirectTo, queryParams: { login_hint: OWNER_EMAIL, prompt: 'select_account' } } }) as any);
  }
  async loadLists() {
    return (check(await this.sb.from('stock_lists').select('*').order('pos').order('created_at')) as any[]).map(normList);
  }
  async saveList(l: StockList) {
    const { builtin: _b, ...row } = l;
    check(await this.sb.from('stock_lists').upsert({ ...row, updated_at: new Date().toISOString() }, { onConflict: 'id' }));
  }
  async deleteList(id: string) { check(await this.sb.from('stock_lists').delete().eq('id', id)); }
  async loadDrawings() {
    return check(await this.sb.from('drawings').select('*').not('status', 'in', '(obsolete,deleted)').order('created_at')) as Drawing[];
  }
  async insertDrawing(d: Partial<Drawing>) {
    return check(await this.sb.from('drawings').insert(d).select().single()) as Drawing;
  }
  async updateDrawing(id: string, patch: Partial<Drawing>) {
    check(await this.sb.from('drawings').update({ ...patch, updated_at: new Date().toISOString() }).eq('id', id));
  }
  // soft delete: the row stays (status 'deleted') so a re-import never resurrects it
  async deleteDrawing(id: string) { await this.updateDrawing(id, { status: 'deleted' }); }
  async loadLabels() {
    return check(await this.sb.from('labels').select('*').order('asof').order('created_at')) as Label[];
  }
  async upsertLabel(l: Label) {
    check(await this.sb.from('labels').upsert(l, { onConflict: 'ticker,label,asof' }));
  }
  async loadCommands() {
    return check(await this.sb.from('commands').select('*').order('created_at', { ascending: false }).limit(500)) as Command[];
  }
  async addCommand(ticker: string | null, text: string, kind = 'command', payload: Record<string, any> | null = null) {
    return check(await this.sb.from('commands').insert({ ticker, text, kind, payload }).select().single()) as Command;
  }
  async addFeedback(f: Feedback) { check(await this.sb.from('drawing_feedback').insert(f)); }
  async loadWatch() { return check(await this.sb.from('watchlist').select('*').order('added_at')) as Watch[]; }
  async addWatch(ticker: string) { check(await this.sb.from('watchlist').upsert({ ticker }, { onConflict: 'ticker' })); }
  async removeWatch(ticker: string) { check(await this.sb.from('watchlist').delete().eq('ticker', ticker)); }
  async loadPositions() {
    return (check(await this.sb.from('positions').select('*').eq('status', 'open').order('entry_date')) as any[]).map(normPosition);
  }
  async loadResearch() {
    return check(await this.sb.from('ticker_research').select('ticker,summary_he,data,sources,updated_at')) as Research[];
  }
  subscribe(fn: ChangeFn) {
    const ch = this.sb.channel('srs-app');
    for (const t of ['drawings', 'labels', 'commands', 'watchlist', 'positions', 'stock_lists'] as Table[]) {
      ch.on('postgres_changes' as any, { event: '*', schema: 'public', table: t },
        (p: any) => fn(t, p.eventType, p.new, p.old));
    }
    ch.subscribe();
  }
}

// ---- demo (in-memory, nothing leaves the browser) ----
class MemApi implements Api {
  demo = true;
  email: string | null = null;
  authFns: ((e: string | null) => void)[] = [];
  changeFns: ChangeFn[] = [];
  drawings: Drawing[] = [];
  labels: Label[] = [];
  commands: Command[] = [];
  watch: Watch[] = [];
  seq = 1;
  constructor(loggedIn: boolean) { this.email = loggedIn ? OWNER_EMAIL : null; }
  async session() { return { email: this.email }; }
  onAuth(fn: (e: string | null) => void) { this.authFns.push(fn); }
  async sendLink(_e: string) { /* demo */ }
  async verifyCode(email: string) { this.email = email; this.authFns.forEach((f) => f(email)); }
  async signOut() { this.email = null; this.authFns.forEach((f) => f(null)); }
  async googleEnabled() { return new URLSearchParams(location.search).has('google'); }
  async signInGoogle() { this.email = OWNER_EMAIL; this.authFns.forEach((f) => f(OWNER_EMAIL)); }
  lists: StockList[] = [];
  async loadLists() { return this.lists.map((l) => ({ ...l, tickers: [...l.tickers] })); }
  async saveList(l: StockList) {
    const i = this.lists.findIndex((x) => x.id === l.id), row = { ...l, tickers: [...l.tickers], updated_at: new Date().toISOString() };
    if (i >= 0) this.lists[i] = row; else this.lists.push({ ...row, created_at: row.updated_at });
    this.emit('stock_lists', i >= 0 ? 'UPDATE' : 'INSERT', { ...row }, null);
  }
  async deleteList(id: string) { this.lists = this.lists.filter((l) => l.id !== id); this.emit('stock_lists', 'DELETE', null, { id }); }
  emit(t: Table, e: 'INSERT' | 'UPDATE' | 'DELETE', row: any, old: any) { this.changeFns.forEach((f) => f(t, e, row, old)); }
  async loadDrawings() { return this.drawings.filter((d) => d.status !== 'deleted' && d.status !== 'obsolete').map((d) => ({ ...d })); }
  async insertDrawing(d: Partial<Drawing>) {
    const row = { zone_top: null, zone_bottom: null, entry: null, stop: null, target: null, t_start: null, t_end: null,
      source: 'user', status: 'active', note: null, ...d, id: crypto.randomUUID(), created_at: new Date().toISOString() } as Drawing;
    this.drawings.push(row); this.emit('drawings', 'INSERT', { ...row }, null); return { ...row };
  }
  async updateDrawing(id: string, patch: Partial<Drawing>) {
    const d = this.drawings.find((x) => x.id === id); if (!d) return;
    Object.assign(d, patch); this.emit('drawings', 'UPDATE', { ...d }, { id });
  }
  async deleteDrawing(id: string) { await this.updateDrawing(id, { status: 'deleted' }); }
  async loadWatch() { return [...this.watch]; }
  async addWatch(ticker: string) {
    if (this.watch.some((w) => w.ticker === ticker)) return;
    const w = { ticker, note: null, added_at: new Date().toISOString() }; this.watch.push(w); this.emit('watchlist', 'INSERT', w, null);
  }
  async removeWatch(ticker: string) { this.watch = this.watch.filter((w) => w.ticker !== ticker); this.emit('watchlist', 'DELETE', null, { ticker }); }
  /** demo: seed with the TradingView export, mapped like srs_app/import_tv.py */
  seedTv(tv: Record<string, TvDrawing>) {
    for (const [t, d] of Object.entries(tv)) {
      const status = d.owner === 'bot' ? 'review' : 'active';
      const base = { ticker: t, source: 'tv' as const, status: status as any, note: `TV ${d.owner || ''} read ${d.read_date || '?'}`, t_start: null, t_end: null, created_at: new Date().toISOString() };
      if (d.zone_top != null && d.zone_bottom != null)
        this.drawings.push({ ...base, id: crypto.randomUUID(), kind: 'zone', zone_top: d.zone_top, zone_bottom: d.zone_bottom, entry: null, stop: null, target: null, tv_key: `${t}:zone` });
      if (d.entry != null && d.stop != null && d.target != null)
        this.drawings.push({ ...base, id: crypto.randomUUID(), kind: 'long', zone_top: null, zone_bottom: null, entry: d.entry, stop: d.stop, target: d.target, tv_key: `${t}:long` });
    }
  }
  async loadLabels() { return [...this.labels]; }
  async upsertLabel(l: Label) {
    this.labels = this.labels.filter((x) => !(x.ticker === l.ticker && x.label === l.label && x.asof === l.asof));
    const row = { ...l, created_at: new Date().toISOString() }; this.labels.push(row); this.emit('labels', 'INSERT', row, null);
  }
  async loadCommands() { return [...this.commands]; }
  feedback: Feedback[] = [];
  async addFeedback(f: Feedback) { this.feedback.push({ ...f }); }
  async addCommand(ticker: string | null, text: string, kind = 'command', payload: Record<string, any> | null = null) {
    const c: Command = { id: this.seq++, ticker, text, status: 'pending', reply: null, created_at: new Date().toISOString(), done_at: null, kind, payload };
    this.commands.unshift(c); this.emit('commands', 'INSERT', c, null); return c;
  }
  // demo: tests inject made-up positions with addInitScript (window.__demoPositions); nothing real is in the bundle
  async loadPositions() { return (((window as any).__demoPositions || []) as any[]).filter((p) => (p.status ?? 'open') === 'open').map(normPosition); }
  // demo: tests inject made-up overviews (window.__demoResearch)
  async loadResearch() { return [...(((window as any).__demoResearch || []) as Research[])]; }
  subscribe(fn: ChangeFn) { this.changeFns.push(fn); }
}

const normList = (r: any): StockList => ({ id: r.id, name: r.name, kind: r.kind === 'dynamic' ? 'dynamic' : 'static', tickers: Array.isArray(r.tickers) ? r.tickers : [],
  criteria: r.criteria || null, pos: +r.pos || 0, created_at: r.created_at, updated_at: r.updated_at });

export function makeApi(): Api {
  const q = new URLSearchParams(location.search);
  if (q.has('demo')) {
    const api = new MemApi(q.get('demo') !== 'login');
    (window as any).__demoApi = api;
    return api;
  }
  return new SupaApi();
}
