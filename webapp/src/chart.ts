// lightweight-charts candles + volume, with an SVG overlay for zones / long positions and touch handles.
import {
  createChart, CandlestickSeries, HistogramSeries, LineSeries, CrosshairMode, LineStyle,
  type IChartApi, type ISeriesApi, type IPriceLine, type Time,
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
  /** Fib edit: an anchor handle / end line was dropped at bar time `time` (current timeframe) and price `price`, exactly
   *  where it was released (no snapping, Eyal 2026-10-30). */
  onFibDrop?(which: 'low' | 'high', time: string, price: number): void;
  /** live while dragging (the Fib lines follow before the drop is saved) */
  onFibMove?(which: 'low' | 'high', time: string, price: number): void;
  /** Fib drawing tool (startFibDraw): live preview from the first anchor to the pointer */
  onFibDraft?(a: FibPt, b: FibPt): void;
}
/** One earnings report marker (Eyal 2026-10-28). d = report date; future = the next known date (est = estimated). */
export interface EarnMark { d: string; t: 'bmo' | 'amc' | null; e: number | null; a: number | null; s: number | null; future?: boolean; est?: boolean }
const ddmmyyyy = (d: string) => `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}`;
export function earnTip(m: EarnMark): string {
  const tm = m.t === 'bmo' ? 'לפני הפתיחה' : m.t === 'amc' ? 'אחרי הסגירה' : '';
  const head = `<b>${m.future ? 'דוח הבא' : 'דוח'} <bdi dir="ltr">${ddmmyyyy(m.d)}</bdi></b>${m.future && m.est ? ' (משוער)' : ''}${tm ? ' · ' + tm : ''}`;
  let eps = '';
  if (m.a != null && m.e != null) {
    const beat = m.a > m.e ? 'עקפה' : m.a < m.e ? 'פספסה' : 'בדיוק בצפי';
    eps = `<div><bdi dir="ltr">EPS ${m.a.toFixed(2)}</bdi> מול צפי <bdi dir="ltr">${m.e.toFixed(2)}</bdi> · <span class="${m.a >= m.e ? 'up' : 'dn'}">${beat}${m.s != null ? ` <bdi dir="ltr">(${m.s > 0 ? '+' : ''}${m.s.toFixed(1)}%)</bdi>` : ''}</span></div>`;
  } else if (m.a != null) eps = `<div><bdi dir="ltr">EPS ${m.a.toFixed(2)}</bdi> (אין צפי)</div>`;
  else if (m.e != null) eps = `<div>צפי <bdi dir="ltr">EPS ${m.e.toFixed(2)}</bdi></div>`;
  else if (!m.future) eps = '<div class="muted">אין נתוני EPS</div>';
  return head + eps;
}
export interface FibPt { time: string; price: number }
export interface FibEdit { low: { time: string; price: number } | null; high: { time: string; price: number } | null }

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
  private tipEl: HTMLDivElement;
  earnings: EarnMark[] = [];
  private earnTipIdx: number | null = null;
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
    this.tipEl = document.createElement('div');
    this.tipEl.className = 'etip';
    this.tipEl.hidden = true;
    this.tipEl.dir = 'rtl';
    host.appendChild(this.tipEl);
    // earnings markers: hover (mouse) shows the details; tap toggles them (touch); tap elsewhere closes
    this.svg.addEventListener('pointerover', (e) => {
      if (e.pointerType !== 'mouse') return;
      const g = (e.target as Element).closest('g.earn') as SVGGElement | null;
      if (g) this.showEarnTip(+g.dataset.i!);
    });
    // (the overlay is re-rendered while hovering, so pointerout can land on a detached node: track moves on the host)
    host.addEventListener('pointermove', (e) => {
      if (e.pointerType === 'mouse' && this.earnTipIdx != null && !(e.target as Element).closest?.('g.earn')) this.showEarnTip(null);
    });
    host.addEventListener('pointerleave', (e) => { if (e.pointerType === 'mouse' && this.earnTipIdx != null) this.showEarnTip(null); });
    // Fib drawing tool (Eyal 2026-10-30, like TradingView): press = first anchor (the low), drag, release = second anchor
    // (the target); a click without dragging sets the first anchor and the next click the second. Raw price / time of
    // the pointer, no snapping. While the tool is on the chart does not pan / zoom (touch: no page scroll either).
    host.addEventListener('pointerdown', (e) => this.onFibDrawDown(e), true);
    this.svg.addEventListener('pointerdown', (e) => this.onPointerDown(e));
    // own tap detection (lightweight-charts swallows quick 2nd taps as double-tap)
    let down: { x: number; y: number; t: number } | null = null;
    host.addEventListener('pointerdown', (e) => {
      if (!(e.target as Element).closest('g.earn') && this.earnTipIdx != null) this.showEarnTip(null);
      down = (e.target as Element).closest('g.h, g.tag, g.fh, g.earn') ? null : { x: e.clientX, y: e.clientY, t: Date.now() };
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

  // ---- indicators (Eyal 2026-10-24): daily SMA 50/100/150/200 + Fibonacci retracement ----
  private maSeries = new Map<number, ISeriesApi<'Line'>>();
  private fibLines: IPriceLine[] = [];
  private fibAnchorS: ISeriesApi<'Line'> | null = null;
  private legendEl: HTMLDivElement | null = null;
  private extraLevels: number[] = [];
  /** Fib edit mode (Eyal 2026-10-24; no snapping since 2026-10-30): draggable anchor handles + end lines. */
  fibEdit: FibEdit | null = null;
  private fibDrag: 'low' | 'high' | null = null;
  private fibDraw: { onDone: (a: FibPt, b: FibPt) => void; a: FibPt | null } | null = null;
  get fibDrawing() { return !!this.fibDraw; }
  /** Fib drawing tool on: the next press on the chart sets the first anchor, the release (or next click) the second. */
  startFibDraw(onDone: (a: FibPt, b: FibPt) => void) {
    this.fibDraw = { onDone, a: null };
    this.host.classList.add('fibdrawmode');
    this.chart.applyOptions({ handleScroll: false, handleScale: false });
    this.lastKey = '';
  }
  cancelFibDraw() {
    if (!this.fibDraw) return;
    this.fibDraw = null;
    this.host.classList.remove('fibdrawmode');
    this.chart.applyOptions({ handleScroll: true, handleScale: true });
    this.lastKey = '';
  }
  /** raw chart point under a client position (null outside the price pane) */
  private ptAt(clientX: number, clientY: number, clamp = false): FibPt | null {
    const r = this.host.getBoundingClientRect();
    let x = clientX - r.left, y = clientY - r.top;
    if (clamp) { x = Math.max(0, Math.min(this.paneW() - 1, x)); y = Math.max(0, Math.min(this.paneH() - 1, y)); }
    else if (x < 0 || y < 0 || x > this.paneW() || y > this.paneH()) return null;
    const price = this.priceAt(y), time = this.dateAt(x);
    return price == null || !time ? null : { time, price };
  }
  private onFibDrawDown(e: PointerEvent) {
    const fd = this.fibDraw; if (!fd) return;
    const p0 = this.ptAt(e.clientX, e.clientY); if (!p0) return; // price / time axis: ignore
    e.preventDefault(); e.stopImmediatePropagation();
    const x0 = e.clientX, y0 = e.clientY;
    const first = !fd.a;
    if (first) fd.a = p0;
    let last: FibPt = p0;
    const move = (ev: PointerEvent) => {
      ev.preventDefault();
      const p = this.ptAt(ev.clientX, ev.clientY, true); if (!p || !fd.a) return;
      last = p; this.cb.onFibDraft?.(fd.a, p);
    };
    const up = (ev: PointerEvent) => {
      window.removeEventListener('pointermove', move, true); window.removeEventListener('pointerup', up, true); window.removeEventListener('pointercancel', up, true);
      ev.stopImmediatePropagation();
      const p = this.ptAt(ev.clientX, ev.clientY, true) ?? last;
      const dragged = Math.hypot(ev.clientX - x0, ev.clientY - y0) > 6;
      if (first && !dragged) return; // a click: first anchor set, wait for the second click
      const a = fd.a!;
      this.cancelFibDraw();
      if (a.price === p.price) return;
      fd.onDone(a, p);
    };
    window.addEventListener('pointermove', move, { passive: false, capture: true });
    window.addEventListener('pointerup', up, true);
    window.addEventListener('pointercancel', up, true);
  }
  setFibEdit(e: FibEdit | null) { if (this.fibDrag) return; this.fibEdit = e ? JSON.parse(JSON.stringify(e)) : null; this.lastKey = ''; }
  /** Moving averages to show: [{n, color, data}] (data already in the timeframe's bar times); [] hides all. */
  setMAs(mas: { n: number; color: string; data: { time: string; value: number }[] }[]) {
    const want = new Set(mas.map((m) => m.n));
    for (const [n, se] of this.maSeries) if (!want.has(n)) { this.chart.removeSeries(se); this.maSeries.delete(n); }
    for (const m of mas) {
      let se = this.maSeries.get(m.n);
      if (!se) {
        se = this.chart.addSeries(LineSeries, { color: m.color, lineWidth: 2, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false, title: '' });
        this.maSeries.set(m.n, se);
      }
      se.setData(m.data.map((x) => ({ time: x.time as Time, value: x.value })));
    }
    if (!this.legendEl) { this.legendEl = document.createElement('div'); this.legendEl.className = 'malegend'; this.host.appendChild(this.legendEl); }
    this.legendEl.innerHTML = mas.map((m) => { const v = m.data[m.data.length - 1]?.value; return `<span style="color:${m.color}">MA${m.n}${v != null ? ' ' + v.toFixed(2) : ''}</span>`; }).join('');
    this.legendEl.hidden = !mas.length;
  }
  /** Fibonacci retracement low -> high: 0 / 0.382 / 0.5 / 0.618 / 1 price lines (key levels bold) + dashed anchor line. */
  setFib(f: { low: number; high: number; lowTime: string; highTime: string } | null, fit = true) {
    for (const pl of this.fibLines) this.candles.removePriceLine(pl);
    this.fibLines = [];
    if (this.fibAnchorS) { this.chart.removeSeries(this.fibAnchorS); this.fibAnchorS = null; }
    this.extraLevels = [];
    if (!f) { if (fit) this.fitLevels(); return; }
    const lv: [number, string, number, LineStyle][] = [
      [0, 'rgba(178,181,190,.7)', 1, LineStyle.Dashed], [0.382, '#4dd0e1', 2, LineStyle.Solid], [0.5, '#ffca28', 2, LineStyle.Solid],
      [0.618, '#ff7043', 2, LineStyle.Solid], [1, 'rgba(178,181,190,.7)', 1, LineStyle.Dashed]];
    for (const [x, color, w, st] of lv) {
      const price = f.high - x * (f.high - f.low);
      this.extraLevels.push(price);
      this.fibLines.push(this.candles.createPriceLine({ price, color, lineWidth: w as 1 | 2, lineStyle: st, axisLabelVisible: true, title: `Fib ${x}` }));
    }
    this.fibAnchorS = this.chart.addSeries(LineSeries, { color: 'rgba(178,181,190,.55)', lineWidth: 1, lineStyle: LineStyle.Dashed, priceLineVisible: false, lastValueVisible: false, crosshairMarkerVisible: false });
    if (f.lowTime < f.highTime) this.fibAnchorS.setData([{ time: f.lowTime as Time, value: f.low }, { time: f.highTime as Time, value: f.high }]);
    if (fit) this.fitLevels();
  }

  /** Earnings report markers (past + next); [] hides them. */
  setEarnings(ms: EarnMark[]) {
    this.earnings = ms.slice().sort((a, b) => (a.d < b.d ? -1 : 1));
    this.showEarnTip(null);
    this.lastKey = '';
  }
  private showEarnTip(i: number | null) {
    this.earnTipIdx = i;
    const m = i == null ? null : this.earnings[i];
    if (!m) { this.tipEl.hidden = true; this.earnTipIdx = null; this.lastKey = ''; return; }
    this.tipEl.innerHTML = earnTip(m);
    this.tipEl.hidden = false;
    this.lastKey = '';
    this.placeEarnTip();
  }
  private placeEarnTip() {
    const i = this.earnTipIdx; if (i == null || this.tipEl.hidden) return;
    const m = this.earnings[i]; let x = m ? this.X(m.d) : null;
    if (m?.future && x != null && x > this.paneW() - 10) x = this.paneW() - 12;
    if (x == null) { this.tipEl.hidden = true; return; }
    const W = this.paneW(), H = this.paneH(), w = this.tipEl.offsetWidth, h = this.tipEl.offsetHeight;
    Object.assign(this.tipEl.style, { left: Math.max(4, Math.min(W - w - 4, x - w / 2)) + 'px', top: Math.max(4, H - 26 - h) + 'px' });
  }

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
    lv.push(...this.extraLevels.filter((x) => Number.isFinite(x)));
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
      this.chart.priceScale('right').width(), JSON.stringify(this.fibEdit), this.fibDrag, this.earnings.length, this.earnings[0]?.d, this.earnTipIdx, this.weekly].join('|');
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
    // the overlay also covers the price axis (only the Fib end strips take pointer events there: Eyal grabs a Fib line
    // "from the side", at its price label); drawings still use the pane width W
    this.svg.setAttribute('width', String(W + psW));
    this.svg.setAttribute('height', String(H));
    this.svg.setAttribute('viewBox', `0 0 ${W + psW} ${H}`);
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
    type R = { x: number; y: number; w: number; h: number };
    const obst: R[] = []; // visible handle / tag rects that price labels must not cover
    const hit = (a: R, b: R) => a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h;
    const handle = (id: string, key: HandleKey, x: number, y: number | null, color: string) => {
      if (y == null || y < -20 || y > H + 20) return;
      const yy = Math.max(10, Math.min(H - 10, y));
      obst.push(key === 't_start' ? { x: x - 6, y: yy - 16, w: 12, h: 32 } : { x: x - 11, y: yy - 11, w: 22, h: 22 });
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
        const rrTxt = pre + 'R:R ' + (q != null ? q.toFixed(2) : '—');
        s += tag(x2 - 4, this.Y(d.target), rrTxt, sel ? '#26a69a' : '#2a2e39', d.id);
        const yt0 = this.Y(d.target);
        if (yt0 != null) { const w = rrTxt.length * 6.4 + 12; obst.push({ x: Math.max(2, Math.min(W - w - 2, x2 - 4 - w)), y: yt0 - 9, w, h: 18 }); }
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
        s += this.longLabels(d, x1, W, H, obst, hit);
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
    // Fib anchor handles (edit mode): low = circle under the candle's low wick, high = over the high wick
    if (this.fibEdit) {
      // grab the Fib 1 (low) / 0 (high) line anywhere along the chart: a 16px transparent strip, under the handles
      for (const which of ['low', 'high'] as const) {
        const a = this.fibEdit[which]; if (!a) continue;
        const y = this.Y(a.price);
        if (y == null || y < 0 || y > H) continue;
        const hl = this.fibDrag === which;
        handles.push(`<g class="fh fl${hl ? ' dragging' : ''}" data-fk="${which}"><rect x="0" y="${y - 10}" width="${W + psW}" height="20" fill="transparent"/>` +
          `<line class="flh" x1="0" x2="${W}" y1="${y}" y2="${y}" stroke="#fff" stroke-width="3" stroke-opacity="${hl ? 0.5 : 0}"/></g>`);
      }
      for (const which of ['low', 'high'] as const) {
        const a = this.fibEdit[which]; if (!a) continue;
        let x = this.X(a.time); const y = this.Y(a.price);
        if (x == null || y == null || y < -20 || y > H + 20) continue;
        x = Math.max(10, Math.min(W - 10, x)); // anchor scrolled out of view: keep the handle grabbable at the edge
        const col = which === 'low' ? '#26a69a' : '#ef5350';
        const [yName, yPx] = which === 'low' ? [y + 35, y + 22] : [y - 27, y - 14];
        const drag = this.fibDrag === which;
        handles.push(`<g class="fh${drag ? ' dragging' : ''}" data-fk="${which}"><circle cx="${x}" cy="${y}" r="22" fill="transparent"/>` +
          `<circle class="fhdot" cx="${x}" cy="${y}" r="${drag ? 10 : 8}" fill="${col}" stroke="#fff" stroke-width="2"/>` +
          `<text x="${x}" y="${yName}" text-anchor="middle" style="font-size:11px;font-weight:600">${which === 'low' ? 'שפל' : 'שיא'}</text>` +
          `<text x="${x}" y="${yPx}" text-anchor="middle" direction="ltr" style="font-size:11px">${a.price.toFixed(2)}</text></g>`);
      }
    }
    this.svg.innerHTML = this.earnMarkersSvg(W, H) + s + guide + handles.join('');
    this.placeEarnTip();
  }

  /** 'E' badges along the bottom of the price pane: filled (green = beat, red = miss, grey = no EPS) on the candle /
   *  week of each past report, hollow dashed on the next known date in the future area. */
  private earnMarkersSvg(W: number, H: number): string {
    if (!this.earnings.length || !this.bars.length) return '';
    const y = H - 12;
    let out = '', nextSvg = '';
    this.earnings.forEach((m, i) => {
      let x = this.X(m.d);
      // the next report beyond the visible future area: pinned to the right edge with an arrow (still tappable)
      const pinned = !!m.future && x != null && x > W - 10;
      if (pinned) x = W - 12;
      if (x == null || x < -8 || x > W + 8) return;
      const col = m.future ? '#f7c948' : m.a != null && m.e != null ? (m.a >= m.e ? '#26a69a' : '#ef5350') : '#787b86';
      const on = this.earnTipIdx === i;
      const svg = `<g class="earn${m.future ? ' next' : ''}${pinned ? ' pinned' : ''}${on ? ' on' : ''}" data-i="${i}" data-d="${m.d}"><circle cx="${x}" cy="${y}" r="15" fill="transparent"/>` +
        (on ? `<line x1="${x}" x2="${x}" y1="0" y2="${y - 8}" stroke="${col}" stroke-width="1" stroke-dasharray="3 3" stroke-opacity=".7"/>` : '') +
        (m.future
          ? `<circle cx="${x}" cy="${y}" r="7.5" fill="#131722" stroke="${col}" stroke-width="1.5" stroke-dasharray="2.5 1.5"/><text x="${x}" y="${y + 3.5}" text-anchor="middle" class="et" style="fill:${col}">E</text>` +
            (pinned ? `<path d="M${x + 9} ${y - 4} L${x + 12.5} ${y} L${x + 9} ${y + 4}" fill="none" stroke="${col}" stroke-width="1.5"/>` : '')
          : `<circle cx="${x}" cy="${y}" r="7.5" fill="${col}" stroke="#131722" stroke-width="1"/><text x="${x}" y="${y + 3.5}" text-anchor="middle" class="et">E</text>`) + '</g>';
      if (m.future) nextSvg += svg; else out += svg;
    });
    return nextSvg + out; // past reports painted last: on top of a pinned next marker they overlap
  }

  /** TP / Entry / SL price labels on a long. Each label tries a few slots (inside the box next to its edge, the other
   *  side of the edge, then right of the handles / left of the box) and a smaller font / shorter text, and takes the
   *  first slot that overlaps no handle, tag or other label. */
  private longLabels(d: Drawing, x1: number, W: number, H: number, obst: { x: number; y: number; w: number; h: number }[],
    hit: (a: any, b: any) => boolean): string {
    if (d.entry == null) return '';
    const E = +d.entry, ye = this.Y(E), yt = this.Y(d.target), ys = this.Y(d.stop);
    const m = (x: number) => '$' + x.toFixed(2);
    const pct = (x: number) => (E > 0 ? (x / E * 100).toFixed(1) + '%' : '');
    type L = { cls: string; color: string; full: string; short: string; edge: number | null; first: 'above' | 'below' };
    const labels: L[] = [];
    if (d.target != null) {
      const g = +d.target - E;
      labels.push({ cls: 'lbl-tp', color: '#5fd4c6', full: `TP ${m(+d.target)} (${g >= 0 ? '+' : '-'}${m(Math.abs(g))}, ${pct(g)})`, short: `TP ${m(+d.target)}`, edge: yt, first: 'below' });
    }
    labels.push({ cls: 'lbl-entry', color: '#d1d4dc', full: `Entry ${m(E)}`, short: `E ${m(E)}`, edge: ye, first: 'above' });
    if (d.stop != null) {
      const r = E - +d.stop;
      labels.push({ cls: 'slsz', color: '#ff8a87', full: `SL ${m(r)} (${pct(r)})`, short: `SL ${m(r)}`, edge: ys, first: 'above' });
    }
    const variants = [{ fs: 10.5, cw: 6.1, k: 'full' }, { fs: 9, cw: 5.3, k: 'full' }, { fs: 9, cw: 5.3, k: 'short' }] as const;
    const placed: { x: number; y: number; w: number; h: number }[] = [];
    let out = '';
    for (const l of labels) {
      if (l.edge == null || l.edge < -30 || l.edge > H + 30) continue;
      const e = l.edge;
      type P = { x: number; y: number; w: number; h: number; fs: number; txt: string };
      let best = null as P | null;
      let fallback = null as P | null;
      search: for (const v of variants) {
        const txt = v.k === 'full' ? l.full : l.short;
        const w = txt.length * v.cw + 8, h = v.fs + 4;
        const above = e - 11 - h, below = e + 11;
        // near the edge first (inside / outside), then stacked further out (short boxes: labels fan out)
        const ys2 = l.first === 'above' ? [above, below] : [below, above];
        for (let n = 1; n <= 3; n++) ys2.push(...(l.cls === 'slsz' ? [below + n * (h + 2)] : l.cls === 'lbl-tp' ? [above - n * (h + 2)] : [above - n * (h + 2), below + n * (h + 2)]));
        const xs2 = [x1 + 8, ...obst.filter((o) => o.y < e + 12 && o.y + o.h > e - 12).map((o) => o.x + o.w + 4), x1 - w - 4];
        for (const y of ys2) for (const x0 of xs2) {
          const x = Math.max(2, Math.min(W - w - 2, x0));
          const r = { x, y, w, h };
          if (y < 0 || y + h > H) continue;
          fallback ??= { ...r, fs: v.fs, txt };
          if (obst.some((o) => hit(r, o)) || placed.some((o) => hit(r, o))) continue;
          best = { ...r, fs: v.fs, txt }; break search;
        }
      }
      const b = best ?? fallback;
      if (!b) continue;
      placed.push(b);
      out += `<g class="plbl ${l.cls}"><rect x="${b.x}" y="${b.y}" width="${b.w}" height="${b.h}" rx="3" fill="rgba(19,23,34,.6)"/>` +
        `<text x="${b.x + 4}" y="${b.y + b.h - 3.5}" style="fill:${l.color};font-size:${b.fs}px">${esc(b.txt)}</text></g>`;
    }
    return out;
  }

  // ---- interaction ----
  private onPointerDown(e: PointerEvent) {
    const t = e.target as Element;
    const eg = t.closest('g.earn') as SVGGElement | null;
    if (eg) { e.stopPropagation(); const i = +eg.dataset.i!; this.showEarnTip(e.pointerType === 'mouse' || this.earnTipIdx !== i ? i : null); return; }
    const fh = t.closest('g.fh') as SVGGElement | null;
    if (fh && this.fibEdit) {
      e.preventDefault(); e.stopPropagation();
      const which = fh.dataset.fk as 'low' | 'high';
      const isLine = fh.classList.contains('fl');
      this.fibDrag = which;
      this.host.classList.add('fibdragging');
      this.chart.applyOptions({ handleScroll: false, handleScale: false });
      const move = (ev: PointerEvent) => {
        ev.preventDefault();
        const cur = this.fibEdit?.[which]; if (!cur) return;
        const p = this.ptAt(ev.clientX, ev.clientY, true); if (!p) return;
        // exactly where the pointer is (no snapping); an end line dragged from the side only changes the price
        this.fibEdit![which] = { time: isLine ? cur.time : p.time, price: p.price };
        this.cb.onFibMove?.(which, this.fibEdit![which]!.time, p.price);
        this.lastKey = '';
      };
      const up = () => {
        window.removeEventListener('pointermove', move); window.removeEventListener('pointerup', up); window.removeEventListener('pointercancel', up);
        this.chart.applyOptions({ handleScroll: true, handleScale: true });
        this.fibDrag = null; this.lastKey = '';
        this.host.classList.remove('fibdragging');
        const a = this.fibEdit?.[which];
        if (a) this.cb.onFibDrop?.(which, a.time, a.price);
      };
      window.addEventListener('pointermove', move, { passive: false });
      window.addEventListener('pointerup', up);
      window.addEventListener('pointercancel', up);
      return;
    }
    let h = t.closest('g.h') as SVGGElement | null;
    if (h) {
      e.preventDefault(); e.stopPropagation();
      // overlapping hit areas (thin zone: the 44px targets of top and bottom overlap) -> the handle whose visible
      // centre is nearest to the pointer wins, not simply the one painted last (2026-10-24: chart is the only editor)
      let best = Infinity;
      this.svg.querySelectorAll<SVGGElement>('g.h').forEach((g) => {
        const vis = g.lastElementChild as SVGGraphicsElement | null; if (!vis) return;
        const b = vis.getBoundingClientRect();
        if (Math.abs(e.clientX - (b.left + b.width / 2)) > 26 || Math.abs(e.clientY - (b.top + b.height / 2)) > 30) return;
        const dd = Math.hypot(e.clientX - (b.left + b.width / 2), e.clientY - (b.top + b.height / 2));
        if (dd < best) { best = dd; h = g; }
      });
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
