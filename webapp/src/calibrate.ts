// Trend calibration page (#/calibrate, 'כיול מגמה', Eyal 2026-10-26): ~60 tickers in three visible sections
// (clear uptrend / clearly not / unsure, from app/data/calibration.json) with a 3-year weekly candle chart (+ weekly
// EMA30), the bot's view and one-line reason, and his mark: 'מגמה עולה' / 'לא' / 'לא בטוח' + optional note, saved as
// label 'uptrend_mark' (value up / not / unsure, asof today). Point-in-time calibration data only: the marks never
// change f_technical (the uptrend is recomputed every night).
import { decodeSpark, type Spark } from './data';
import type { Label } from './types';

export interface CalRow { ticker: string; group: 'clear_up' | 'clear_not' | 'unsure'; bot_view: string; reason_he: string; sector?: string; industry?: string }
export const CAL_LABEL = 'uptrend_mark';
export const CAL_GROUPS: [CalRow['group'], string][] = [['clear_up', 'ברור שבמגמה עולה'], ['clear_not', 'ברור שלא'], ['unsure', 'מתלבט']];
export const CAL_MARKS: [string, string][] = [['up', 'מגמה עולה'], ['not', 'לא'], ['unsure', 'לא בטוח']];

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));

/** Latest mark per ticker (newest asof, then created_at). */
export function latestMarks(labels: Label[]): Map<string, Label> {
  const m = new Map<string, Label>();
  for (const l of labels) {
    if (l.label !== CAL_LABEL) continue;
    const b = m.get(l.ticker);
    if (!b || l.asof > b.asof || (l.asof === b.asof && (l.created_at || '') > (b.created_at || ''))) m.set(l.ticker, l);
  }
  return m;
}
export function progress(rows: CalRow[], labels: Label[]): { done: number; total: number } {
  const m = latestMarks(labels);
  return { done: rows.filter((r) => m.has(r.ticker)).length, total: rows.length };
}

export function calCardHtml(r: CalRow, mark?: Label): string {
  return `<li class="calcard" data-cal="${esc(r.ticker)}">
    <div class="r1"><a class="caltk" href="#/t/${encodeURIComponent(r.ticker)}" dir="ltr"><b>${esc(r.ticker)}</b></a>
      <span class="muted small">${esc(r.sector || '')}</span>
      ${mark ? `<span class="badge b-pass calmarked">סומן: ${esc(CAL_MARKS.find(([v]) => v === mark.value)?.[1] || mark.value)}</span>` : ''}</div>
    <canvas class="calchart" data-calchart="${esc(r.ticker)}" aria-label="גרף שבועי 3 שנים"></canvas>
    <div class="calbot small"><b>דעת הבוט:</b> ${esc(r.bot_view)} — ${esc(r.reason_he)}</div>
    <div class="calbtns">${CAL_MARKS.map(([v, t]) => `<button class="chip ${mark?.value === v ? 'on' : ''}" data-mark="${v}">${t}</button>`).join('')}</div>
    <input class="calnote" type="text" placeholder="הערה (לא חובה)" value="${esc(mark?.note || '')}" />
  </li>`;
}

export function calPageHtml(rows: CalRow[], labels: Label[]): string {
  const m = latestMarks(labels), p = progress(rows, labels);
  return `<div class="calhead"><span id="calprog" class="small">סומנו ${p.done}/${p.total}</span>
    <span class="muted small">הסימונים לכיול בלבד; המגמה נבדקת מחדש בכל שבוע.</span></div>` +
    CAL_GROUPS.map(([g, title]) => {
      const rs = rows.filter((r) => r.group === g);
      return `<section class="calsec" data-group="${g}"><h2>${title} <span class="muted small">(${rs.length})</span></h2>
        <ul class="callist">${rs.map((r) => calCardHtml(r, m.get(r.ticker))).join('')}</ul></section>`;
    }).join('');
}

/** EMA(n) of closes (seeded with the first close) - fallback when the spark carries no exported ema30. */
export function ema(c: number[], n = 30): number[] {
  const k = 2 / (n + 1), out: number[] = [];
  c.forEach((v, i) => out.push(i ? v * k + out[i - 1] * (1 - k) : v));
  return out;
}

/** Weekly candles (~3 years) + EMA30 on a canvas sized by CSS (aspect-ratio), drawn at device pixel ratio. */
export function drawCalChart(cv: HTMLCanvasElement, sp: Spark & { ema30?: string } | undefined) {
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!sp || !W || !H) { cv.classList.toggle('empty', !sp); return; }
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d')!; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const B = decodeSpark(sp), n = B.c.length;
  let e: (number | null)[];
  if (sp.ema30) {
    const q = atob(sp.ema30), k = (sp.hi - sp.lo) / 254;
    e = Array.from({ length: n }, (_, i) => (i < q.length && q.charCodeAt(i) !== 255 ? sp.lo + q.charCodeAt(i) * k : null));
  } else e = ema(B.c);
  const lo = B.lo - (B.hi - B.lo) * 0.03, hi = B.hi + (B.hi - B.lo) * 0.03;
  const top = 4, bot = H - 4, step = (W - 2) / n, bw = Math.max(1, step * 0.7);
  const Y = (p: number) => bot - ((p - lo) / ((hi - lo) || 1)) * (bot - top);
  for (let i = 0; i < n; i++) {
    g.fillStyle = B.c[i] >= B.o[i] ? '#26a69a' : '#ef5350';
    const x = 1 + i * step, cx = x + bw / 2;
    const yh = Y(B.h[i]), yl = Y(B.l[i]);
    g.fillRect(cx - 0.4, yh, 0.8, Math.max(0.8, yl - yh));
    const yo = Y(B.o[i]), yc = Y(B.c[i]);
    g.fillRect(x, Math.min(yo, yc), bw, Math.max(0.8, Math.abs(yc - yo)));
  }
  g.strokeStyle = '#ff9800'; g.lineWidth = 1.5; g.beginPath();
  let pen = false;
  e.forEach((v, i) => { if (v == null) { pen = false; return; } const x = 1 + i * step + bw / 2; pen ? g.lineTo(x, Y(v)) : g.moveTo(x, Y(v)); pen = true; });
  g.stroke();
  cv.dataset.drawn = '1';
}
