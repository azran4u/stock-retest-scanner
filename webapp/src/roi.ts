// Roi's method analysis ("ניתוח של רועי והמלצה", Eyal 2026-11-23).
// Data lives in public.roi_analysis (owner-only RLS). Never ship the JSON under app/ or dist/:
// those folders are publicly reachable without login. This overlay is informational and must
// not change the scanner's PASS rules, R:R, or trade plan.

export type RoiRecKey = 'enter' | 'wait' | 'skip';

export interface RoiCheck {
  item: string;
  result: string; // ✔ / ✖ / ?
  detail: string;
}

export interface RoiMention {
  date: string | null;
  source: string;
  quote: string;
}

export interface RoiAnalysis {
  ticker: string;
  recommendation: string;
  rec_key: RoiRecKey;
  entry: number | null;
  stop: number | null;
  target: number | null;
  rr: number | null;
  rationale_he: string;
  checklist: RoiCheck[];
  roi_mentions: RoiMention[];
  as_of: string | null;
  price: number | null;
  price_date: string | null;
  trigger_he: string | null;
  scanner_report_date: string | null;
}

export const ROI_RECS: { key: RoiRecKey; label: string; cls: string; prefix: string }[] = [
  { key: 'enter', label: 'כניסה עכשיו', cls: 'b-roi-enter', prefix: 'כניסה עכשיו' },
  { key: 'wait', label: 'לחכות לאישור', cls: 'b-roi-wait', prefix: 'לחכות לאישור' },
  { key: 'skip', label: 'לדלג', cls: 'b-roi-skip', prefix: 'לדלג' },
];

export const ROI_REC_BY_KEY = Object.fromEntries(ROI_RECS.map((r) => [r.key, r])) as Record<RoiRecKey, typeof ROI_RECS[number]>;

export function recKeyOf(recommendation: string | null | undefined): RoiRecKey | null {
  const s = String(recommendation || '').trim();
  if (!s) return null;
  const hit = ROI_RECS.find((r) => s === r.key || s.startsWith(r.prefix) || s.startsWith(r.label));
  return hit ? hit.key : null;
}

export function recLabel(key: RoiRecKey | string | null | undefined, fallback?: string): string {
  if (key && key in ROI_REC_BY_KEY) return ROI_REC_BY_KEY[key as RoiRecKey].label;
  const k = recKeyOf(String(key || fallback || ''));
  return k ? ROI_REC_BY_KEY[k].label : (fallback || '');
}

export function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
}

const num = (v: unknown): number | null => {
  if (v == null || v === '') return null;
  const n = Number(v);
  return Number.isFinite(n) ? n : null;
};

const blank = (v: unknown): string | null => {
  const s = String(v ?? '').trim();
  return s ? s : null;
};

function parseChecklist(raw: unknown): RoiCheck[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((x) => ({
    item: String(x?.item ?? '').trim(),
    result: String(x?.result ?? '').trim() || '?',
    detail: String(x?.detail ?? '').trim(),
  })).filter((x) => x.item);
}

function parseMentions(raw: unknown): RoiMention[] {
  if (!Array.isArray(raw)) return [];
  return raw.map((x) => ({
    date: blank(x?.date),
    source: String(x?.source ?? '').trim(),
    quote: String(x?.quote ?? '').trim(),
  })).filter((x) => x.quote || x.source);
}

export function normalizeRoi(raw: any): RoiAnalysis | null {
  const ticker = String(raw?.ticker ?? '').trim().toUpperCase();
  if (!ticker) return null;
  const recommendation = String(raw?.recommendation ?? '').trim();
  const rec_key: RoiRecKey | null = recKeyOf(String(raw?.rec_key || '')) || recKeyOf(recommendation);
  if (!rec_key) return null;
  return {
    ticker,
    recommendation: recommendation || ROI_REC_BY_KEY[rec_key].label,
    rec_key,
    entry: num(raw?.entry),
    stop: num(raw?.stop),
    target: num(raw?.target),
    rr: num(raw?.rr),
    rationale_he: String(raw?.rationale_he ?? '').trim(),
    checklist: parseChecklist(raw?.checklist),
    roi_mentions: parseMentions(raw?.roi_mentions),
    as_of: blank(raw?.as_of),
    price: num(raw?.price),
    price_date: blank(raw?.price_date),
    trigger_he: blank(raw?.trigger_he),
    scanner_report_date: blank(raw?.scanner_report_date),
  };
}

export function normalizeRoiList(raw: any[]): RoiAnalysis[] {
  const out: RoiAnalysis[] = [];
  const seen = new Set<string>();
  for (const r of raw || []) {
    const row = normalizeRoi(r);
    if (!row || seen.has(row.ticker)) continue;
    seen.add(row.ticker);
    out.push(row);
  }
  return out;
}

export function formatRoiDate(iso: string | null | undefined): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || '');
  return m ? `${m[3]}.${m[2]}.${m[1]}` : (iso || '');
}

export function fmtRoiNum(x: number | null | undefined, d = 2): string {
  return x == null || Number.isNaN(+x) ? '—' : (+x).toFixed(d);
}

/** list-row badge: recommendation + Roi's R:R. Empty string when there is no analysis. */
export function roiBadgeHtml(row: RoiAnalysis | null | undefined): string {
  if (!row) return '';
  const meta = ROI_REC_BY_KEY[row.rec_key];
  const rr = row.rr != null ? ` · רועי R:R <bdi dir="ltr">${esc(fmtRoiNum(row.rr))}</bdi>` : '';
  return `<span class="badge b-roi ${meta.cls}" title="${esc(row.recommendation)}">${esc(meta.label)}${rr}</span>`;
}

function checkMark(result: string): { cls: string; glyph: string } {
  if (result === '✔') return { cls: 'ok', glyph: '✔' };
  if (result === '✖') return { cls: 'bad', glyph: '✖' };
  return { cls: 'unk', glyph: result || '?' };
}

/** expandable detail panel. Empty string when there is no analysis. */
export function roiPanelHtml(row: RoiAnalysis | null | undefined, open = true): string {
  if (!row) return '';
  const meta = ROI_REC_BY_KEY[row.rec_key];
  const asof = formatRoiDate(row.as_of);
  const levels = [
    ['כניסה', row.entry],
    ['סטופ', row.stop],
    ['יעד', row.target],
    ['R:R', row.rr],
  ].map(([lab, v]) => `<div class="roikv"><span>${lab}</span><b dir="ltr">${esc(fmtRoiNum(v as number | null))}</b></div>`).join('');
  const rationale = row.rationale_he ? `<p class="roi-rationale">${esc(row.rationale_he)}</p>` : '';
  const trigger = row.trigger_he ? `<p class="roi-trigger"><b>טריגר:</b> ${esc(row.trigger_he)}</p>` : '';
  const checks = row.checklist.length
    ? `<ul class="roi-check">${row.checklist.map((c) => {
        const m = checkMark(c.result);
        return `<li class="${m.cls}"><span class="ci" aria-hidden="true">${m.glyph}</span><div><b>${esc(c.item)}</b>${c.detail ? `<div class="muted small">${esc(c.detail)}</div>` : ''}</div></li>`;
      }).join('')}</ul>`
    : '';
  const quotes = row.roi_mentions.length
    ? `<div class="roi-quotes"><h4>אזכורים של רועי</h4>${row.roi_mentions.map((q) => {
        const when = formatRoiDate(q.date);
        const src = [when, q.source].filter(Boolean).join(' · ');
        return `<blockquote><p>${esc(q.quote)}</p>${src ? `<footer class="muted small">${esc(src)}</footer>` : ''}</blockquote>`;
      }).join('')}</div>`
    : '';
  const price = row.price != null
    ? `<span class="muted small">מחיר <bdi dir="ltr">${esc(fmtRoiNum(row.price))}</bdi>${row.price_date ? ` (${esc(formatRoiDate(row.price_date))})` : ''}</span>`
    : '';
  return `<details class="roibox" id="roiPanel" ${open ? 'open' : ''}>
    <summary><h3>ניתוח רועי</h3><span class="badge ${meta.cls}">${esc(meta.label)}</span>
      <span class="muted small">R:R <bdi dir="ltr">${esc(fmtRoiNum(row.rr))}</bdi>${asof ? ` · נכון ל-${esc(asof)}` : ''}</span></summary>
    <p class="muted small roinote">שיטת רועי — ניתוח והמלצה נפרדים מתוכנית הסורק. לא משנים את סטטוס PASS, את ה-R:R של האפליקציה או את כללי הכניסה.</p>
    <div class="roilevels">${levels}</div>
    ${price}
    ${rationale}
    ${trigger}
    ${checks}
    ${quotes}
  </details>`;
}
