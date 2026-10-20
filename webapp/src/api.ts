// Data layer: Supabase (real) or in-memory (demo mode, ?demo=1, for screenshots / offline tests).
import { createClient, type SupabaseClient, type Session } from '@supabase/supabase-js';
import type { Command, Drawing, Label } from './types';

export const SUPABASE_URL = 'https://wkkdblnykgolqijzagva.supabase.co';
export const SUPABASE_KEY = 'sb_publishable_yjtRuTIx0PrxQcdnlfU_Dw_IcJDxi4D';
export const OWNER_EMAIL = 'azran4u@gmail.com';

export type Table = 'drawings' | 'labels' | 'commands';
export type ChangeFn = (table: Table, event: 'INSERT' | 'UPDATE' | 'DELETE', row: any, old: any) => void;

export interface Api {
  demo: boolean;
  session(): Promise<{ email: string | null }>;
  onAuth(fn: (email: string | null) => void): void;
  sendLink(email: string): Promise<void>;
  verifyCode(email: string, code: string): Promise<void>;
  signOut(): Promise<void>;
  loadDrawings(): Promise<Drawing[]>;
  insertDrawing(d: Partial<Drawing>): Promise<Drawing>;
  updateDrawing(id: string, patch: Partial<Drawing>): Promise<void>;
  deleteDrawing(id: string): Promise<void>;
  loadLabels(): Promise<Label[]>;
  upsertLabel(l: Label): Promise<void>;
  loadCommands(): Promise<Command[]>;
  addCommand(ticker: string, text: string): Promise<Command>;
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
  async loadDrawings() {
    return check(await this.sb.from('drawings').select('*').neq('status', 'obsolete').order('created_at')) as Drawing[];
  }
  async insertDrawing(d: Partial<Drawing>) {
    return check(await this.sb.from('drawings').insert(d).select().single()) as Drawing;
  }
  async updateDrawing(id: string, patch: Partial<Drawing>) {
    check(await this.sb.from('drawings').update({ ...patch, updated_at: new Date().toISOString() }).eq('id', id));
  }
  async deleteDrawing(id: string) { check(await this.sb.from('drawings').delete().eq('id', id)); }
  async loadLabels() {
    return check(await this.sb.from('labels').select('*').order('asof').order('created_at')) as Label[];
  }
  async upsertLabel(l: Label) {
    check(await this.sb.from('labels').upsert(l, { onConflict: 'ticker,label,asof' }));
  }
  async loadCommands() {
    return check(await this.sb.from('commands').select('*').order('created_at', { ascending: false }).limit(500)) as Command[];
  }
  async addCommand(ticker: string, text: string) {
    return check(await this.sb.from('commands').insert({ ticker, text }).select().single()) as Command;
  }
  subscribe(fn: ChangeFn) {
    const ch = this.sb.channel('srs-app');
    for (const t of ['drawings', 'labels', 'commands'] as Table[]) {
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
  seq = 1;
  constructor(loggedIn: boolean) { this.email = loggedIn ? OWNER_EMAIL : null; }
  async session() { return { email: this.email }; }
  onAuth(fn: (e: string | null) => void) { this.authFns.push(fn); }
  async sendLink(_e: string) { /* demo */ }
  async verifyCode(email: string) { this.email = email; this.authFns.forEach((f) => f(email)); }
  async signOut() { this.email = null; this.authFns.forEach((f) => f(null)); }
  emit(t: Table, e: 'INSERT' | 'UPDATE' | 'DELETE', row: any, old: any) { this.changeFns.forEach((f) => f(t, e, row, old)); }
  async loadDrawings() { return this.drawings.map((d) => ({ ...d })); }
  async insertDrawing(d: Partial<Drawing>) {
    const row = { zone_top: null, zone_bottom: null, entry: null, stop: null, target: null, t_start: null, t_end: null,
      source: 'user', status: 'active', note: null, ...d, id: crypto.randomUUID(), created_at: new Date().toISOString() } as Drawing;
    this.drawings.push(row); this.emit('drawings', 'INSERT', { ...row }, null); return { ...row };
  }
  async updateDrawing(id: string, patch: Partial<Drawing>) {
    const d = this.drawings.find((x) => x.id === id); if (!d) return;
    Object.assign(d, patch); this.emit('drawings', 'UPDATE', { ...d }, { id });
  }
  async deleteDrawing(id: string) {
    this.drawings = this.drawings.filter((x) => x.id !== id); this.emit('drawings', 'DELETE', null, { id });
  }
  async loadLabels() { return [...this.labels]; }
  async upsertLabel(l: Label) {
    this.labels = this.labels.filter((x) => !(x.ticker === l.ticker && x.label === l.label && x.asof === l.asof));
    const row = { ...l, created_at: new Date().toISOString() }; this.labels.push(row); this.emit('labels', 'INSERT', row, null);
  }
  async loadCommands() { return [...this.commands]; }
  async addCommand(ticker: string, text: string) {
    const c: Command = { id: this.seq++, ticker, text, status: 'pending', reply: null, created_at: new Date().toISOString(), done_at: null };
    this.commands.unshift(c); this.emit('commands', 'INSERT', c, null); return c;
  }
  subscribe(fn: ChangeFn) { this.changeFns.push(fn); }
}

export function makeApi(): Api {
  const q = new URLSearchParams(location.search);
  if (q.has('demo')) {
    const api = new MemApi(q.get('demo') !== 'login');
    (window as any).__demoApi = api;
    return api;
  }
  return new SupaApi();
}
