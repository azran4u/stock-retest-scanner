// lightweight-charts candles + volume, with an SVG overlay for zones / long positions and touch handles.
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, CrosshairMode,
  type IChartApi, type ISeriesApi, type Time,
} from 'lightweight-charts';
import type { Bar, Drawing } from './types';
import { rr } from './data';

export type HandleKey = 'zone_top' | 'zone_bottom' | 'entry' | 'stop' | 'target' | 't_start' | 't_end';

/** Default Long Position width (bars of the current timeframe) when a row has no t_end anchor. */
export const LONG_W_BARS = 20;
const PRICE_KEYS: HandleKey[] = ['zone_top', 'zone_bottom', 'entry', 'stop', 'target'];
const DAY = 86400000;
const addDays = (d: string, n: number) => new Date(Date.parse(d + 'T00:00:00Z') + n * DAY).toISOString().slice(0, 10);
const mondayOf = (d: string) => { const t = new Date(d + 'T00:00:00Z'); return addDays(d, -((t.getUTCDay() + 6) % 7)); };
const isWeekday = (d: string) => { const w = new Date(d + 'T00:00:00Z').getUTCDay(); return w !== 0 && w !== 6; };

export interface ChartCallbacks {
  onSelect(id: string | null): void;
  onDragMove(d: Drawing): void;
  onDragEnd(id: string, patch: Partial<Drawing>): void;
  onTap(price: number, date: string): void;
}

const SVGNS = 'http://www.w3.org/2000/svg';
const r2 = (x: number) => Math.round(x * 100) / 100;
const esc = (s: string) => s.replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]!));

export class ChartView {
  chart: IChartApi;
  candles: ISeriesApi<'Candlestick'>;
  vol: ISeriesApi<'Histogram'>;
  volMa: ISeriesApi<'Line'>;
  svg: SVGSVGElement;
  bars: Bar[] = [];
  drawings: Drawing[] = [];
  selected: string | null = null;
  editable = true;
  weekly = true;
  private atrEl: HTMLDivElement;
  private atrVal: number | null = null;
  private dragging: { id: string; key: HandleKey } | null = null;
  private lastKey = '';
  private raf = 0;

  constructor(private host: HTMLElement, private cb: ChartCallbacks) {
    host.style.position = 'relative';
    this.chart = createChart(host, {
      autoSize: true,
      layout: { background: { color: '#131722' }, textColor: '#b2b5be', fontSize: 11, attributionLogo: false },
      grid: { vertLines: { color: '#1e222d' }, horzLines: { color: '#1e222d' } },
      rightPriceScale: { borderColor: '#2a2e39', scaleMargins: { top: 0.08, bottom: 0.22 } },
      timeScale: { borderColor: '#2a2e39', rightOffset: 8, barSpacing: 7 },
      crosshair: { mode: CrosshairMode.Normal },
      localization: { locale: 'en-US' },
    });
    this.candles = this.chart.addSeries(CandlestickSeries, {
      upColor: '#26a69a', downColor: '#ef5350', borderVisible: false, wickUpColor: '#26a69a', wickDownColor: '#ef5350',
    });
    this.vol = this.chart.addSeries(HistogramSeries, { priceScaleId: 'vol', priceFormat: { type: 'volume' }, lastValueVisible: false, priceLineVisible: false });
    // 30-bar SMA of volume, same 'vol' scale (weekly bars in weekly view, daily in daily)
    this.volMa = this.chart.addSeries(LineSeries, {
      priceScaleId: 'vol', color: '#ffd600', lineWidth: 1, priceLineVisible: false, lastValueVisible: false,
      crosshairMarkerVisible: false, priceFormat: { type: 'volume' },
    });
    this.chart.priceScale('vol').applyOptions({ scaleMargins: { top: 0.82, bottom: 0 } });

    this.svg = document.createElementNS(SVGNS, 'svg') as SVGSVGElement;
    this.svg.classList.add('overlay');
    host.appendChild(this.svg);
    // weekly ATR, in the bottom-right corner box (under the price axis, right of the time axis)
    this.atrEl = document.createElement('div');
    this.atrEl.className = 'atrw';
    this.atrEl.hidden = true;
    host.appendChild(this.atrEl);
    this.svg.addEventListener('pointerdown', (e) => this.onPointerDown(e));
    // own tap detection (lightweight-charts swallows quick 2nd taps as double-tap)
    let down: { x: number; y: number; t: number } | null = null;
    host.addEventListener('pointerdown', (e) => {
      down = (e.target as Element).closest('g.h, g.tag') ? null : { x: e.clientX, y: e.clientY, t: Date.now() };
    }, true);
    host.addEventListener('pointerup', (e) => {
      if (!down || this.dragging) return;
      const moved = Math.hypot(e.clientX - down.x, e.clientY - down.y);
      const dt = Date.now() - down.t; down = null;
      if (moved > 10 || dt > 600) return;
      const r = host.getBoundingClientRect();
      const x = e.clientX - r.left, y = e.clientY - r.top;
      if (x > this.paneW() || y > this.paneH()) return; // price / time axis
      const price = this.priceAt(y), date = this.dateAt(x);
      if (price != null && date) this.cb.onTap(price, date);
    }, true);
    const loop = () => { this.renderIfChanged(); this.raf = requestAnimationFrame(loop); };
    this.raf = requestAnimationFrame(loop);
  }

  destroy() { cancelAnimationFrame(this.raf); this.chart.remove(); }

  /** Weekly ATR shown in the bottom-right corner (always weekly, whatever the timeframe). */
  setAtr(v: number | null) {
    this.atrVal = v;
    this.atrEl.hidden = v == null;
    this.atrEl.innerHTML = v == null ? '' : `<span>ATR(W)</span><b>${v.toFixed(2)}</b>`;
    this.lastKey = '';
  }

  setBars(bars: Bar[], visible: number, weekly = true) {
    this.bars = bars;
    this.weekly = weekly;
    this.candles.setData(bars.map((b) => ({ time: b.time as Time, open: b.open, high: b.high, low: b.low, close: b.close })));
    this.vol.setData(bars.map((b) => ({ time: b.time as Time, value: b.volume, color: b.close >= b.open ? 'rgba(38,166,154,.45)' : 'rgba(239,83,80,.45)' })));
    const ma: { time: Time; value: number }[] = [];
    let sum = 0;
    for (let i = 0; i < bars.length; i++) {
      sum += bars[i].volume;
      if (i >= 30) sum -= bars[i - 30].volume;
      if (i >= 29) ma.push({ time: bars[i].time as Time, value: sum / 30 });
    }
    this.volMa.setData(ma);
    const n = bars.length;
    this.chart.timeScale().setVisibleLogicalRange({ from: Math.max(0, n - visible), to: n + 6 });
    this.lastKey = '';
  }

  setDrawings(ds: Drawing[], selected: string | null) {
    if (this.dragging) return; // keep the drag copy until pointerup
    this.drawings = ds.map((d) => ({ ...d }));
    this.selected = selected;
    this.lastKey = '';
  }

  /** Make sure the price scale includes drawing levels (else a far target is off-screen). */
  fitLevels() {
    const lv: number[] = [];
    for (const d of this.drawings) [d.zone_top, d.zone_bottom, d.entry, d.stop, d.target].forEach((x) => x != null && lv.push(+x));
    this.candles.applyOptions({
      autoscaleInfoProvider: (orig: any) => {
        const r = orig();
        if (!r || !lv.length) return r;
        return { ...r, priceRange: { minValue: Math.min(r.priceRange.minValue, ...lv), maxValue: Math.max(r.priceRange.maxValue, ...lv) } };
      },
    });
  }

  // ---- coordinates ----
  private idxOf(date: string | null): number {
    if (!date || !this.bars.length) return -1;
    let lo = 0, hi = this.bars.length - 1, ans = 0;
    while (lo <= hi) { const m = (lo + hi) >> 1; if (this.bars[m].time <= date) { ans = m; lo = m + 1; } else hi = m - 1; }
    return ans;
  }
  private X(date: string | null): number | null {
    const l = this.logicalOf(date);
    if (l == null) return null;
    const x = this.chart.timeScale().logicalToCoordinate(l as any);
    return x == null ? null : x;
  }
  /** Bar index (logical) of a date. Dates after the last bar are extrapolated into the future
   *  (weekly: +7 days per bar; daily: one bar per weekday), so anchors to the right of the last candle stay put. */
  logicalOf(date: string | null): number | null {
    const n = this.bars.length;
    if (!date || !n) return null;
    const last = this.bars[n - 1].time;
    if (date <= last) return this.idxOf(date);
    if (this.weekly) return n - 1 + Math.round((Date.parse(mondayOf(date)) - Date.parse(mondayOf(last))) / (7 * DAY));
    let k = 0;
    for (let d = addDays(last, 1); d <= date && k < 5000; d = addDays(d, 1)) if (isWeekday(d)) k++;
    return n - 1 + k;
  }
  /** Inverse of logicalOf: the date of bar index l (future bars get synthetic weekly / weekday dates). */
  dateOfLogical(l: number): string | null {
    const n = this.bars.length;
    if (!n) return null;
    const i = Math.max(0, Math.round(l));
    if (i <= n - 1) return this.bars[i].time;
    const last = this.bars[n - 1].time;
    if (this.weekly) return addDays(mondayOf(last), 7 * (i - (n - 1)));
    let d = last, k = 0;
    while (k < i - (n - 1)) { d = addDays(d, 1); if (isWeekday(d)) k++; }
    return d;
  }
  /** Date that is `bars` bars after `date` in the current timeframe. */
  shiftDate(date: string, bars: number): string | null {
    const l = this.logicalOf(date);
    return l == null ? null : this.dateOfLogical(l + bars);
  }
  /** Time anchor of a long position in bar indices: start (default right of the last candle) and end (default start + LONG_W_BARS). */
  longSpan(d: Drawing): { s: number; e: number } {
    const n = this.bars.length;
    const s = this.logicalOf(d.t_start) ?? n;
    let e = this.logicalOf(d.t_end) ?? s + LONG_W_BARS;
    if (e < s + 1) e = s + 1;
    return { s, e };
  }
  /** Anchor dates for a long (what gets persisted when a legacy row without anchors is edited). */
  longAnchor(d: Drawing): { t_start: string | null; t_end: string | null } {
    const { s, e } = this.longSpan(d);
    return { t_start: this.dateOfLogical(s), t_end: this.dateOfLogical(e) };
  }
  private Y(p: number | null | undefined): number | null {
    if (p == null) return null;
    const y = this.candles.priceToCoordinate(+p);
    return y == null ? null : y;
  }
  priceAt(y: number): number | null { const p = this.candles.coordinateToPrice(y); return p == null ? null : r2(p); }
  dateAt(x: number): string | null {
    const l = this.chart.timeScale().coordinateToLogical(x);
    if (l == null || !this.bars.length) return null;
    return this.dateOfLogical(l); // right of the last candle -> future date
  }
  private paneW(): number { return this.chart.timeScale().width(); }
  private paneH(): number { return this.chart.paneSize(0).height; }

  // ---- rendering ----
  private renderIfChanged() {
    if (!this.bars.length) return;
    const lr = this.chart.timeScale().getVisibleLogicalRange();
    const key = [lr?.from, lr?.to, this.Y(this.bars[this.bars.length - 1].close), this.Y((this.bars[this.bars.length - 1].close) * 1.1),
      this.paneW(), this.paneH(), this.selected, JSON.stringify(this.drawings), this.dragging?.key, this.atrVal,
      this.chart.priceScale('right').width()].join('|');
    if (key === this.lastKey) return;
    this.lastKey = key;
    this.render();
  }

  render() {
    const W = this.paneW(), H = this.paneH();
    // ATR box fills the corner under the price axis
    const psW = this.chart.priceScale('right').width();
    const tsH = this.chart.timeScale().height();
    Object.assign(this.atrEl.style, { left: W + 'px', top: H + 'px', width: psW + 'px', height: tsH + 'px' });
    this.svg.setAttribute('width', String(W));
    this.svg.setAttribute('height', String(H));
    this.svg.setAttribute('viewBox', `0 0 ${W} ${H}`);
    let s = '';
    const clampX = (x: number | null, dflt: number) => Math.max(0, Math.min(W, x == null ? dflt : x));
    const box = (x1: number, x2: number, ya: number | null, yb: number | null, fill: string, stroke: string, dash = '') => {
      if (ya == null || yb == null) return '';
      const y = Math.min(ya, yb), h = Math.max(1, Math.abs(yb - ya));
      return `<rect x="${x1}" y="${y}" width="${Math.max(0, x2 - x1)}" height="${h}" fill="${fill}" stroke="${stroke}" stroke-width="1" ${dash ? `stroke-dasharray="${dash}"` : ''}/>`;
    };
    const line = (x1: number, x2: number, y: number | null, stroke: string, dash = '') =>
      y == null ? '' : `<line x1="${x1}" x2="${x2}" y1="${y}" y2="${y}" stroke="${stroke}" stroke-width="1.5" ${dash ? `stroke-dasharray="${dash}"` : ''}/>`;
    const tag = (x: number, y: number | null, text: string, color: string, id?: string) => {
      if (y == null) return '';
      const w = text.length * 6.4 + 12;
      const tx = Math.max(2, Math.min(W - w - 2, x - w));
      return `<g class="tag" ${id ? `data-sel="${id}"` : ''}><rect x="${tx}" y="${y - 9}" width="${w}" height="18" rx="4" fill="${color}"/>` +
        `<text x="${tx + w / 2}" y="${y + 4}" text-anchor="middle">${esc(text)}</text></g>`;
    };

    const handles: string[] = [];
    const handle = (id: string, key: HandleKey, x: number, y: number | null, color: string) => {
      if (y == null || y < -20 || y > H + 20) return;
      const yy = Math.max(10, Math.min(H - 10, y));
      handles.push(key === 't_start'
        ? `<g class="h" data-id="${id}" data-key="${key}"><rect x="${x - 22}" y="${yy - 26}" width="44" height="52" fill="transparent"/><rect x="${x - 4}" y="${yy - 14}" width="8" height="28" rx="3" fill="${color}" stroke="#fff" stroke-width="1.5"/></g>`
        : `<g class="h" data-id="${id}" data-key="${key}"><circle cx="${x}" cy="${yy}" r="22" fill="transparent"/><circle cx="${x}" cy="${yy}" r="8" fill="${color}" stroke="#fff" stroke-width="2"/></g>`);
    };

    for (const d of this.drawings) {
      const sel = d.id === this.selected;
      const bot = d.source === 'bot';
      const pre = d.source === 'tv' ? 'TV ' : bot ? 'BOT ' : '';
      const review = d.status === 'review';
      let x1 = clampX(this.X(d.t_start), 0);
      let x2 = clampX(d.t_end ? this.X(d.t_end) : null, W);
      let xs = x1; // unclamped left edge (for the start handle)
      if (d.kind === 'long') {
        // anchored to bars (time), not to screen pixels: moves with pan / zoom
        const sp = this.longSpan(d), ts = this.chart.timeScale();
        const a = ts.logicalToCoordinate(sp.s as any), b = ts.logicalToCoordinate(sp.e as any);
        if (a == null || b == null) continue;
        xs = a;
        x1 = Math.max(-2, Math.min(W + 2, a)); x2 = Math.max(-2, Math.min(W + 2, b));
        if (x2 - x1 < 1) { if (sel && this.editable) handle(d.id, 't_start', Math.max(8, Math.min(W - 8, a)), this.Y(d.entry), '#d1d4dc'); continue; }
      }
      const hx = Math.max(x1 + 24, Math.min(x2 - 30, x1 + (x2 - x1) * 0.6));
      const dash = review ? '6 4' : '';
      const sw = sel ? 2 : 1;
      if (d.kind === 'zone') {
        const fill = bot ? 'rgba(255,152,0,.16)' : 'rgba(41,98,255,.20)';
        const stroke = bot ? '#ff9800' : '#2962ff';
        s += box(x1, x2, this.Y(d.zone_top), this.Y(d.zone_bottom), fill, stroke, dash).replace('stroke-width="1"', `stroke-width="${sw}"`);
        s += tag(x2 - 4, this.Y(d.zone_top), pre + (review ? 'לבדיקה' : 'אזור'), sel ? stroke : '#2a2e39', d.id);
        if (sel && this.editable) {
          handle(d.id, 'zone_top', hx, this.Y(d.zone_top), stroke);
          handle(d.id, 'zone_bottom', hx, this.Y(d.zone_bottom), stroke);
          const ym = this.Y(((+(d.zone_top ?? 0)) + (+(d.zone_bottom ?? 0))) / 2);
          handle(d.id, 't_start', x1, ym, stroke);
        }
      } else if (d.kind === 'long') {
        s += box(x1, x2, this.Y(d.entry), this.Y(d.target), 'rgba(38,166,154,.22)', '#26a69a', dash).replace('stroke-width="1"', `stroke-width="${sw}"`);
        s += box(x1, x2, this.Y(d.stop), this.Y(d.entry), 'rgba(239,83,80,.22)', '#ef5350', dash).replace('stroke-width="1"', `stroke-width="${sw}"`);
        s += line(x1, x2, this.Y(d.entry), '#d1d4dc');
        const q = rr(d.entry, d.stop, d.target);
        s += tag(x2 - 4, this.Y(d.target), pre + 'R:R ' + (q != null ? q.toFixed(2) : '—'), sel ? '#26a69a' : '#2a2e39', d.id);
        // SL size per share (entry - SL), inside the red box next to the SL edge
        const ye = this.Y(d.entry), ys = this.Y(d.stop);
        if (d.entry != null && d.stop != null && ye != null && ys != null) {
          const risk = +d.entry - +d.stop;
          const txt = `SL $${risk.toFixed(2)}` + (+d.entry > 0 ? ` (${(risk / +d.entry * 100).toFixed(1)}%)` : '');
          const tw = txt.length * 6.3 + 8;
          const tx = Math.max(2, Math.min(W - tw - 2, x1 + 4));
          // inside the red box just above the SL edge (clear of the SL handle); below the edge if the box is too short
          const inside = Math.abs(ys - ye) >= 32;
          const ty = inside ? ys - 12 : ys + 22;
          if (ty > -10 && ty < H + 10)
            s += `<g class="slsz"><rect x="${tx - 3}" y="${ty - 11}" width="${tw}" height="14" rx="3" fill="rgba(19,23,34,.55)"/><text x="${tx + 1}" y="${ty}" style="fill:#ff8a87;font-size:10.5px">${esc(txt)}</text></g>`;
        }
        if (sel && this.editable) {
          // price handles in the visible middle of the box; time handles on the box edges, mid-height of the
          // green box (not on the entry line, so they never cover the Entry handle on a narrow box)
          const vx1 = Math.max(0, x1), vx2 = Math.min(W, x2), cx = Math.max(vx1 + 24, Math.min(vx2 - 24, vx1 + (vx2 - vx1) * 0.6));
          const ex = vx2 - vx1 >= 110 ? cx - 34 : cx + 34;
          handle(d.id, 'target', cx, this.Y(d.target), '#26a69a');
          handle(d.id, 'entry', ex, this.Y(d.entry), '#d1d4dc');
          handle(d.id, 'stop', cx, this.Y(d.stop), '#ef5350');
          const ty = d.entry != null && d.target != null ? this.Y((+d.entry + +d.target) / 2) : this.Y(d.entry);
          if (xs >= -10 && xs <= W + 10) handle(d.id, 't_start', Math.max(6, Math.min(W - 6, xs)), ty, '#d1d4dc');
          if (x2 > 0 && x2 < W) handle(d.id, 't_end', x2, ty, '#d1d4dc');
        }
      } else if (d.kind === 'line') {
        const y = this.Y(d.entry ?? d.zone_top);
        s += line(0, W, y, bot ? '#ff9800' : '#f7c948', dash);
        s += tag(W - 4, y, 'קו', '#2a2e39', d.id);
        if (sel && this.editable) handle(d.id, 'entry', W * 0.6, y, '#f7c948');
      }
    }
    // dashed guide across the whole chart at the price being dragged (removed on release)
    let guide = '';
    const dg = this.dragging;
    if (dg && PRICE_KEYS.includes(dg.key)) {
      const d = this.drawings.find((x) => x.id === dg.id);
      const v = d ? (d as any)[dg.key] : null;
      const y = this.Y(v);
      if (y != null) {
        const col = dg.key === 'stop' ? '#ef5350' : dg.key === 'target' ? '#26a69a' : '#d1d4dc';
        guide = `<g class="dragguide"><line x1="0" x2="${W}" y1="${y}" y2="${y}" stroke="${col}" stroke-width="1" stroke-dasharray="5 4"/></g>`;
      }
    }
    this.svg.innerHTML = s + guide + handles.join('');
  }

  // ---- interaction ----
  private onPointerDown(e: PointerEvent) {
    const t = e.target as Element;
    const h = t.closest('g.h') as SVGGElement | null;
    if (h) {
      e.preventDefault(); e.stopPropagation();
      const id = h.dataset.id!, key = h.dataset.key as HandleKey;
      this.dragging = { id, key };
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
      const rect = this.host.getBoundingClientRect();
      const d0 = this.drawings.find((x) => x.id === id);
      // a long without stored anchors gets them now (placed where it is drawn), so it stays put from here on
      if (d0?.kind === 'long' && (!d0.t_start || !d0.t_end)) Object.assign(d0, this.longAnchor(d0));
      const width = d0?.kind === 'long' ? (() => { const sp = this.longSpan(d0); return sp.e - sp.s; })() : 0;
      this.lastKey = '';
      const move = (ev: PointerEvent) => {
        ev.preventDefault();
        const d = this.drawings.find((x) => x.id === id); if (!d) return;
        const x = ev.clientX - rect.left, y = ev.clientY - rect.top;
        const l = this.chart.timeScale().coordinateToLogical(x);
        if (key === 't_start' && d.kind === 'long' && l != null) {
          // move the whole position along the time axis, keeping its width in bars
          const s = Math.round(l); d.t_start = this.dateOfLogical(s); d.t_end = this.dateOfLogical(s + width);
        } else if (key === 't_end' && l != null) {
          const s = this.logicalOf(d.t_start) ?? Math.round(l);
          d.t_end = this.dateOfLogical(Math.max(s + 1, Math.round(l)));
        } else if (key === 't_start') { const dt = this.dateAt(x); if (dt) d.t_start = dt; }
        else { const p = this.priceAt(y); if (p != null) (d as any)[key] = p; }
        this.cb.onDragMove({ ...d });
        this.lastKey = '';
      };
      const up = () => {
        window.removeEventListener('pointermove', move);
        window.removeEventListener('pointerup', up);
        window.removeEventListener('pointercancel', up);
        this.chart.applyOptions({ handleScroll: true, handleScale: true });
        const d = this.drawings.find((x) => x.id === id);
        this.dragging = null;
        if (!d) return;
        const patch: Partial<Drawing> = {};
        if (d.kind === 'zone' && d.zone_top != null && d.zone_bottom != null && +d.zone_top < +d.zone_bottom) {
          [d.zone_top, d.zone_bottom] = [d.zone_bottom, d.zone_top];
          patch.zone_top = d.zone_top; patch.zone_bottom = d.zone_bottom;
        } else (patch as any)[key] = (d as any)[key];
        if (d.kind === 'long') { patch.t_start = d.t_start; patch.t_end = d.t_end; }
        this.lastKey = '';
        this.cb.onDragEnd(id, patch);
      };
      window.addEventListener('pointermove', move, { passive: false });
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', up);
      return;
    }
    const tg = t.closest('g.tag') as SVGGElement | null;
    if (tg?.dataset.sel) { e.stopPropagation(); this.cb.onSelect(tg.dataset.sel === this.selected ? null : tg.dataset.sel); }
  }

}
