// Weinstein stage analysis page (#/stages, 'שלבים', Eyal 2026-11-13). Data: stages.json + stages_spark.json from
// srs_app/stages.py (own FinViz screen + weekly history; separate from the retest scanner). Every stock gets a stage
// 1-4 + sub-stage + the module-3 identification checks of its stage (✓ / ✗) so Eyal can verify the classification;
// 2A = new stage-2 breakout. Rules come from his masterclass page; the thresholds are printed on the page.

export interface Check { k: string; ok: boolean | null; he: string }
export interface Plan { kind: 'breakout' | 'trigger'; entry: number; stop: number; swing_low: number; target: number | null; target_src: string | null; risk_pct: number | null; rr: number | null; shares: number | null; overhead: number | null }
export interface StageRow {
  t: string; n: string; ex: string; sec: string; ind: string; etf: string | null; etf_stage: number | null; etf_rs: number | null;
  mcap_b: number | null; inst: number | null; dv_m: number | null; earn: string | null; earn_td: number | null;
  stage: 1 | 2 | 3 | 4; sub: string; score: number; conf: 'high' | 'med' | 'low'; checks: Check[]; week: string;
  close: number; ma30: number; slope: number; slope_cls: string; pct_ma: number; rs: number | null; rs_prev: number | null; rs_up: boolean | null;
  hh: boolean | null; hl: boolean | null; prior: string; flat_w: number; crosses13: number; hi52: number; pct_hi52: number; at_hi52: boolean; weeks: number;
  bo: null | { week: string; weeks_ago: number; level: number; base_weeks: number; base_low: number; vol_ratio: number | null; close_pos: number | null; holding: boolean; vol_ok: boolean; pct_above: number | null };
  base?: { top: number; low: number; weeks: number; dist_pct: number };
  plan?: Plan; pre: Check[]; pre_ok: boolean; entry: Check[]; entry_ok: boolean;
}
export interface EtfStage { name: string; stage: number; sub: string; score: number; conf: string; close: number; ma30: number; slope: number; pct_ma: number; rs: number | null; rs_up: boolean | null; week: string; checks: Check[] }
export interface StagesDoc {
  version: number; generated_at: string; week: string; rules: Record<string, number>; screens: Record<string, string>;
  finviz_totals: Record<string, { total: number; read: number }>; skipped: Record<string, number>;
  pre_he: Record<string, string>; market: Record<string, EtfStage>; sectors: Record<string, EtfStage>; strong_sectors: string[]; counts: Record<string, number>; rows: StageRow[];
}
export interface StSpark { w0: string; lo: number; hi: number; n: number; q: string; ma: string }

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const f = (x: unknown, d = 2) => (x == null || x === '' || Number.isNaN(+x!) ? '—' : (+x!).toFixed(d));
const sg = (x: number | null | undefined, d = 1) => (x == null ? '—' : (x > 0 ? '+' : '') + x.toFixed(d));
const ddmm = (iso?: string | null) => (iso && iso.length >= 10 ? `${iso.slice(8, 10)}/${iso.slice(5, 7)}` : '—');

export const STAGE_HE: Record<number, string> = { 1: 'שלב 1 · בסיס', 2: 'שלב 2 · עלייה', 3: 'שלב 3 · פסגה', 4: 'שלב 4 · ירידה' };
export const SUB_HE: Record<string, string> = {
  '2A': 'פריצה חדשה (2A)', '2': 'מגמה עולה', '2-ext': 'מתוחה מעל הממוצע (>35%)', '2-weak': 'מתחת לממוצע עולה (אזהרה)',
  '1A': 'בסיס מוקדם (<10 ש׳)', '1B': 'בסיס בוגר (≥10 ש׳)', '3': 'פסגה / הפצה', '4': 'מגמת ירידה', '4-late': 'מעל ממוצע יורד (אולי תחילת שלב 1)',
};
const CONF_HE: Record<string, string> = { high: 'ודאות גבוהה', med: 'ודאות בינונית', low: 'ודאות נמוכה' };
export type Tab = '2A' | '1' | '2' | '3' | '4' | 'novol';
export const TABS: [Tab, string][] = [['2A', 'פריצה לשלב 2 (חדשה)'], ['1', 'שלב 1'], ['2', 'שלב 2'], ['3', 'שלב 3'], ['4', 'שלב 4'], ['novol', 'פריצה בלי מחזור']];
export const SORTS: [string, string][] = [['rs', 'RS מנספילד'], ['rr', 'R:R'], ['vol', 'מחזור פריצה'], ['pct_ma', '% מהממוצע'], ['slope', 'שיפוע'], ['score', 'ודאות'], ['near', 'קרבה לפריצה'], ['t', 'סימול']];

export interface UiState { tab: Tab; q: string; sort: string; pre: boolean; ready: boolean; conf: 'all' | 'med' | 'high'; near: boolean; rulesOpen?: boolean }
export const UI_DEF: UiState = { tab: '2A', q: '', sort: 'rs', pre: false, ready: false, conf: 'all', near: false };

export function inTab(r: StageRow, tab: Tab): boolean {
  if (tab === '2A') return r.sub === '2A';
  if (tab === 'novol') return !!r.bo && r.bo.holding && !r.bo.vol_ok;
  return String(r.stage) === tab;
}
export function filterRows(rows: StageRow[], ui: UiState): StageRow[] {
  const q = ui.q.trim().toUpperCase();
  let out = rows.filter((r) => inTab(r, ui.tab));
  if (q) out = out.filter((r) => r.t.includes(q) || (r.n || '').toUpperCase().includes(q) || (r.sec || '').toUpperCase().includes(q) || (r.ind || '').toUpperCase().includes(q) || (r.etf || '') === q);
  if (ui.pre) out = out.filter((r) => r.pre_ok);
  if (ui.ready) out = out.filter((r) => r.entry_ok);
  if (ui.conf === 'high') out = out.filter((r) => r.conf === 'high');
  if (ui.conf === 'med') out = out.filter((r) => r.conf !== 'low');
  if (ui.near) out = out.filter((r) => r.base && r.base.dist_pct <= 5);
  const key = (r: StageRow): number | string => {
    switch (ui.sort) {
      case 'rr': return r.plan?.rr ?? -1e9;
      case 'vol': return r.bo?.vol_ratio ?? -1e9;
      case 'pct_ma': return r.pct_ma ?? -1e9;
      case 'slope': return r.slope ?? -1e9;
      case 'score': return r.score * 1000 + (r.rs ?? 0);
      case 'near': return -(r.base?.dist_pct ?? r.bo?.pct_above ?? 1e9);
      case 't': return r.t;
      default: return r.rs ?? -1e9;
    }
  };
  out.sort((a, b) => { const x = key(a), y = key(b); return typeof x === 'string' ? x.localeCompare(y as string) : (y as number) - (x as number); });
  return out;
}

const chk = (c: Check) => `<li class="${c.ok === true ? 'ok' : c.ok === false ? 'bad' : 'unk'}"><span class="ci">${c.ok === true ? '✓' : c.ok === false ? '✗' : '?'}</span>${esc(c.he)}</li>`;
export const stageBadge = (s: number, sub?: string) => `<span class="badge st st${s}">${esc(STAGE_HE[s] || 'שלב ' + s)}${sub ? ' · ' + esc(SUB_HE[sub] || sub) : ''}</span>`;

export function tvUrl(r: Pick<StageRow, 't' | 'ex'>) { return `https://www.tradingview.com/chart/?symbol=${encodeURIComponent((r.ex || '') + ':' + r.t.replace('-', '.'))}&interval=W`; }

export function cardHtml(r: StageRow, maxRisk: number, preHe: Record<string, string> = {}): string {
  const p = r.plan, bo = r.bo;
  const risk = p ? p.entry - p.stop : 0;
  const shares = p && risk > 0 ? Math.floor(maxRisk / risk) : null;
  const kv = (k: string, v: string, cls = '') => `<div class="skv ${cls}"><span>${k}</span><b dir="ltr">${v}</b></div>`;
  return `<li class="stcard" data-st="${esc(r.t)}">
  <div class="r1"><a class="sttk" href="${tvUrl(r)}" target="_blank" rel="noopener" dir="ltr"><b>${esc(r.t)}</b></a>
    ${stageBadge(r.stage, r.sub)} <span class="badge conf-${r.conf}" title="${r.score}/4 תנאי זיהוי">${CONF_HE[r.conf]} ${r.score}/4</span>
    ${r.entry_ok ? '<span class="badge b-pass">מוכנה לכניסה</span>' : ''}${r.pre_ok ? '' : '<span class="badge b-off">נפסלת בסינון המקדים</span>'}</div>
  <div class="small muted stname">${esc(r.n)} · ${esc(r.sec)} / ${esc(r.ind)} · ${esc(r.ex)}${r.etf ? ` · <span class="badge st${r.etf_stage ?? 0}">${esc(r.etf)} שלב ${r.etf_stage ?? '?'} · RS ${sg(r.etf_rs)}</span>` : ''}</div>
  <canvas class="stchart" data-stchart="${esc(r.t)}" aria-label="גרף שבועי שנתיים + 30W SMA"></canvas>
  <div class="skvs">
    ${kv('סגירה שבועית', '$' + f(r.close))}${kv('30W SMA', '$' + f(r.ma30))}
    ${kv('שיפוע 5 ש׳', sg(r.slope) + '%', r.slope_cls === 'up' ? 'pos' : r.slope_cls === 'down' ? 'neg' : '')}${kv('מהממוצע', sg(r.pct_ma) + '%')}
    ${kv('Mansfield RS', `${sg(r.rs)} ${r.rs_up == null ? '' : r.rs_up ? '↑' : '↓'}`, (r.rs ?? 0) > 0 ? 'pos' : 'neg')}${kv('משיא 52 ש׳', sg(r.pct_hi52) + '%')}
    ${bo ? kv('רמת פריצה', '$' + f(bo.level)) + kv('מחזור פריצה', f(bo.vol_ratio, 1) + 'x', bo.vol_ok ? 'pos' : 'neg') + kv('שבוע פריצה', `${ddmm(bo.week)} (לפני ${bo.weeks_ago} ש׳)`) + kv('מעל הפריצה', sg(bo.pct_above) + '%') + kv('בסיס', bo.base_weeks + ' ש׳') : ''}
    ${r.base ? kv('תקרת בסיס', '$' + f(r.base.top)) + kv('רצפת בסיס', '$' + f(r.base.low)) + kv('עד הפריצה', sg(r.base.dist_pct) + '%') : ''}
    ${kv('דוח', r.earn ? `${ddmm(r.earn)}${r.earn_td != null ? ` (${r.earn_td} ימ״ס)` : ''}` : '—')}${kv('$ מחזור יומי', r.dv_m != null ? '$' + f(r.dv_m, 0) + 'M' : '—')}${kv('מוסדיים', r.inst != null ? f(r.inst, 0) + '%' : '—')}
  </div>
  ${p ? `<div class="stplan"><b>${p.kind === 'breakout' ? 'עסקה (קנייה בפריצה / ב-Pullback הראשון)' : 'טריגר Buy-Stop מעל הבסיס'}</b>
    <div class="skvs">${kv(p.kind === 'breakout' ? 'כניסה (סגירה אחרונה)' : 'כניסה (טריגר)', '$' + f(p.entry))}${kv('סטופ', '$' + f(p.stop) + (p.risk_pct != null ? ` (${f(p.risk_pct, 1)}%)` : ''))}
    ${kv('יעד ראשון', p.target ? '$' + f(p.target) + (p.target_src === 'measured' ? ' (מהלך מדוד)' : ' (התנגדות)') : '—')}${kv('R:R', p.rr != null ? '1:' + f(p.rr) : '—', p.rr != null && p.rr >= 3 ? 'pos' : 'neg')}
    ${kv(`מניות בסיכון $${f(maxRisk, 0)}`, shares ? `${shares} ($${f(shares * p.entry, 0)})` : 'הסטופ רחב מדי')}</div></div>` : ''}
  <details class="stchk"><summary>תנאי זיהוי ${esc(STAGE_HE[r.stage])} (${r.score}/4)${r.entry.length ? ` · תנאי כניסה ${r.entry.filter((c) => c.ok).length}/${r.entry.length}` : ''} · סינון מקדים ${r.pre.filter((c) => c.ok !== false).length}/${r.pre.length}</summary>
    <h4>זיהוי השלב</h4><ul class="cks">${r.checks.map(chk).join('')}</ul>
    ${r.entry.length ? `<h4>תנאי כניסה</h4><ul class="cks">${r.entry.map(chk).join('')}</ul>` : ''}
    <h4>סינון מקדים</h4><ul class="cks">${r.pre.map((c) => chk({ ...c, he: c.he || preHe[c.k] || c.k })).join('')}</ul>
    <p class="small muted">שבוע ${ddmm(r.week)} · ${r.weeks} שבועות נתונים · מגמה קודמת: ${r.prior === 'down' ? 'ירידה' : 'עלייה'} · ממוצע שטוח ${r.flat_w} ש׳ · <a href="https://finviz.com/quote.ashx?t=${encodeURIComponent(r.t)}&p=w" target="_blank" rel="noopener">FinViz</a> · <a href="${tvUrl(r)}" target="_blank" rel="noopener">TradingView</a></p>
  </details>
</li>`;
}

export function topDownHtml(d: StagesDoc): string {
  const m = (k: string, e?: EtfStage) => e ? `<div class="mk"><b dir="ltr">${k}</b> ${stageBadge(e.stage, e.sub)}<span class="small muted">RS <span dir="ltr">${sg(e.rs)}</span> · מה-30W <span dir="ltr">${sg(e.pct_ma)}%</span></span></div>` : '';
  const secs = Object.entries(d.sectors).sort((a, b) => (b[1].rs ?? -99) - (a[1].rs ?? -99));
  return `<section class="topdown"><div class="mkts"><span class="small muted">שוק כללי:</span>${['SPY', 'QQQ', 'IWM'].map((k) => m(k, d.market[k])).join('')}</div>
  <details class="secs"><summary>חוזק סקטורים (תעודות סל, לפי RS) · חזקים: ${d.strong_sectors.map(esc).join(', ') || 'אין סקטור בשלב 2 עם RS חיובי'}</summary>
  <div class="tbl"><table><tr><th>תעודה</th><th>סקטור</th><th>שלב</th><th>RS</th><th>שיפוע</th><th>מ-30W</th></tr>
  ${secs.map(([k, e]) => `<tr class="${d.strong_sectors.includes(k) ? 'strong' : ''}"><td dir="ltr"><b>${k}</b>${d.strong_sectors.includes(k) ? ' ★' : ''}</td><td>${esc(e.name)}</td><td>${stageBadge(e.stage, e.sub)}</td><td dir="ltr">${sg(e.rs)} ${e.rs_up == null ? '' : e.rs_up ? '↑' : '↓'}</td><td dir="ltr">${sg(e.slope)}%</td><td dir="ltr">${sg(e.pct_ma)}%</td></tr>`).join('')}
  </table></div></details></section>`;
}

export function rulesHtml(d: StagesDoc, maxRisk: number): string {
  const R = d.rules;
  const scr = Object.entries(d.screens).map(([k, u]) => `<a href="${esc(u.replace('v=152', 'v=111'))}" target="_blank" rel="noopener">${k}</a>`).join(' · ');
  return `<div class="strules">
  <p><b>מקור:</b> דף המסטרקלאס של ויינשטיין ששלחת (מודולים 1–5) + הספר "Secrets for Profiting in Bull and Bear Markets". נרות שבועיים בלבד (סגירת יום שישי, שבוע שהושלם).</p>
  <h4>יקום (FinViz)</h4><p>NYSE + NASDAQ, מניות בלבד, מחיר &gt; $${R.hard_min_price}, מחזור יומי ממוצע &gt; 100K (=500K בשבוע). ${scr}. נקראו ${Object.values(d.finviz_totals || {}).map((x) => x.read).join(' + ')} מניות.</p>
  <h4>סיווג השלב (שבוע אחרון שהושלם)</h4><ul>
   <li>30W SMA = ממוצע פשוט של ${R.ma_weeks} סגירות שבועיות. שיפוע = שינוי הממוצע ב-${R.slope_lookback_w} שבועות: עולה &gt; +${R.slope_flat_pct}%, יורד &lt; −${R.slope_flat_pct}%, אחרת שטוח.</li>
   <li><b>שלב 2:</b> סגירה מעל ממוצע עולה. <b>שלב 4:</b> סגירה מתחת לממוצע יורד.</li>
   <li><b>ממוצע שטוח:</b> שלב 1 אם השיפוע הלא-שטוח האחרון (עד ${R.prior_trend_w} שבועות אחורה) היה יורד, שלב 3 אם היה עולה. בסיס בוגר (1B) = ממוצע שטוח ≥ ${R.min_base_w} שבועות.</li>
   <li>סגירה מתחת לממוצע עולה = שלב 2 "אזהרה"; סגירה מעל ממוצע יורד = שלב 4 "מאוחר" (אין לונג מעל ממוצע יורד).</li>
   <li><b>ודאות</b> = כמה מ-4 תנאי הזיהוי של השלב (מודול 3) מתקיימים: 4 גבוהה, 3 בינונית, ≤2 נמוכה. שיאים/שפלים = נקודות סווינג שבועיות (${R.pivot_w} נרות מכל צד) ב-52 שבועות.</li>
   <li><b>Mansfield RS</b> = ((מניה / S&amp;P 500) / SMA${R.rs_ma_weeks}(מניה / S&amp;P 500) − 1) × 100. "עולה" = גבוה מלפני ${R.rs_rising_w} שבועות.</li></ul>
  <h4>פריצה חדשה לשלב 2 (2A)</h4><ul>
   <li>התנגדות = השיא השבועי הגבוה ב-${R.base_window_w} השבועות שלפני שבוע הפריצה, אחרי לפחות ${R.min_base_w} סגירות שבועיות ברצף מתחתיה (בסיס).</li>
   <li>סגירה שבועית מעל ההתנגדות ומעל 30W SMA, הממוצע שטוח או עולה, באחד מ-${R.bo_max_weeks_ago + 1} השבועות האחרונים (חלון כניסה 1–3 שבועות).</li>
   <li>מחזור שבוע הפריצה ≥ ${R.vol_mult}x ממוצע ${R.vol_avg_w} השבועות שלפניו (פחות מזה = לשונית "פריצה בלי מחזור").</li>
   <li>הפריצה מחזיקה: הסגירה האחרונה עדיין מעל רמת הפריצה ומעל הממוצע.</li></ul>
  <h4>תנאי כניסה (מוצגים לכל מניה ✓/✗)</h4><ul>
   <li>סגירה חזקה: נר הפריצה ב-${100 - R.strong_close * 100}% העליונים של הטווח. באזור קנייה: עד ${R.buy_zone_pct}% מעל רמת הפריצה.</li>
   <li>סטופ = ${R.stop_buffer_pct}% מתחת לנמוך מבין שפל הסווינג האחרון (26 שבועות) ו-30W SMA.</li>
   <li>יעד ראשון = שיא סווינג מרכזי (${R.major_pivot_w} נרות מכל צד) ב-${R.overhead_w} השבועות האחרונים (18 חודשים, כמו בכלל ההתנגדות) הקרוב שגבוה ביותר מ-${R.target_min_gap_pct}% מהכניסה; אם אין (שיא 52 ש׳ / כל הזמנים) = מהלך מדוד: התנגדות + גובה הבסיס. R:R ≥ ${R.min_rr}.</li>
   <li>אוויר נקי: אין שיא סווינג מרכזי ב-${R.overhead_w} השבועות האחרונים (18 חודשים) בטווח ${R.overhead_pct}% מעל הכניסה.</li>
   <li>שוק כללי (SPY) לא בשלב 4; סקטור (תעודת הסל) בשלב 2 עם RS &gt; 0; Mansfield RS של המניה &gt; 0 ועולה; אין דוח ב-${R.earn_td} ימי המסחר הקרובים.</li>
   <li>שלב 1: טריגר Buy-Stop = תקרת הבסיס + $${R.entry_tick}, עם אותם כללי סטופ ויעד.</li>
   <li>כמות מניות = סיכון לעסקה ($${f(maxRisk, 0)} מהגדרות הגודל) ÷ (כניסה − סטופ).</li></ul>
  <h4>סינון מקדים</h4><ul><li>מחיר ≥ $${R.min_price} · מחזור יומי &gt; $${R.min_dollar_vol_m}M או &gt; 500K מניות בשבוע · מוסדיים ${R.inst_lo}%–${R.inst_hi}% · לא ביוטק מתחת ל-$${R.biotech_cap_b}B · ≥ ${R.min_weeks} שבועות. מניה שנפסלת עדיין מסווגת ומוצגת עם תג.</li></ul>
  <p class="small muted">ההנחיות של השלבים בדף שלך איכותיות (למשל "שיפוע קרוב ל-0°"); הספים המספריים כאן (±1% ב-5 שבועות, 26 שבועות בסיס, 10% אזור קנייה) הם הבחירה שלי לתרגום שלהן — תגיד אם לשנות.</p></div>`;
}

export function pageHtml(d: StagesDoc, ui: UiState, rows: StageRow[], maxRisk: number, limit: number): string {
  const cnt = (t: Tab) => d.rows.filter((r) => inTab(r, t)).length;
  return `${topDownHtml(d)}
  <div class="stfilters">
    <div class="chips" role="tablist">${TABS.map(([t, he]) => `<button class="chip ${ui.tab === t ? 'on' : ''}" data-tab="${t}">${he} <span class="cnt">${cnt(t)}</span></button>`).join('')}</div>
    <div class="strow"><input id="stq" type="search" placeholder="חיפוש סימול / חברה / סקטור" value="${esc(ui.q)}" />
      <label class="sortlab">מיון <select id="stsort">${SORTS.map(([k, he]) => `<option value="${k}" ${ui.sort === k ? 'selected' : ''}>${he}</option>`).join('')}</select></label></div>
    <div class="chips">
      <button class="chip ${ui.pre ? 'on' : ''}" data-tg="pre">עוברות סינון מקדים</button>
      <button class="chip ${ui.ready ? 'on' : ''}" data-tg="ready">מוכנות לכניסה (כל התנאים)</button>
      <button class="chip ${ui.conf === 'med' ? 'on' : ''}" data-conf="med">ודאות ≥3/4</button>
      <button class="chip ${ui.conf === 'high' ? 'on' : ''}" data-conf="high">ודאות 4/4</button>
      ${ui.tab === '1' ? `<button class="chip ${ui.near ? 'on' : ''}" data-tg="near">עד 5% מתקרת הבסיס</button>` : ''}
      <button class="chip" id="stcopy">העתק לרשימת TradingView</button>
    </div>
    <div class="small muted" id="stcount">${rows.length} מניות · שבוע ${ddmm(d.week)} · עודכן ${new Date(d.generated_at).toLocaleString('he-IL', { timeZone: 'Asia/Jerusalem', dateStyle: 'short', timeStyle: 'short' })}</div>
  </div>
  <ul class="stlist">${rows.slice(0, limit).map((r) => cardHtml(r, maxRisk, d.pre_he || {})).join('') || '<li class="center muted">אין מניות ברשימה הזו</li>'}</ul>
  ${rows.length > limit ? `<div class="center"><button id="stmore" class="ghost">הצג עוד (${rows.length - limit})</button></div>` : ''}
  <details class="strulesbox" ${ui.rulesOpen ? 'open' : ''}><summary>הכללים והספים</summary>${rulesHtml(d, maxRisk)}</details>`;
}

/** Weekly candles + 30W SMA (orange) + breakout / trigger level (blue dashed) + stop (red dashed). */
export function drawStChart(cv: HTMLCanvasElement, sp: StSpark | undefined, r?: StageRow) {
  const W = cv.clientWidth, H = cv.clientHeight;
  if (!sp || !W || !H) return;
  const dpr = window.devicePixelRatio || 1;
  cv.width = Math.round(W * dpr); cv.height = Math.round(H * dpr);
  const g = cv.getContext('2d')!; g.setTransform(dpr, 0, 0, dpr, 0, 0); g.clearRect(0, 0, W, H);
  const b = atob(sp.q), k = (sp.hi - sp.lo) / 255, n = sp.n;
  const v = (i: number) => sp.lo + b.charCodeAt(i) * k;
  const mq = atob(sp.ma), mk = (sp.hi - sp.lo) / 254;
  const lines: [number, string][] = [];
  const lvl = r?.bo?.level ?? r?.base?.top; if (lvl) lines.push([lvl, '#5b8cff']);
  if (r?.plan?.stop) lines.push([r.plan.stop, '#ef5350']);
  let lo = sp.lo, hi = sp.hi; lines.forEach(([p]) => { lo = Math.min(lo, p); hi = Math.max(hi, p); });
  const pad = (hi - lo) * 0.04; lo -= pad; hi += pad;
  const step = (W - 2) / n, bw = Math.max(1, step * 0.7), Y = (p: number) => 3 + (1 - (p - lo) / ((hi - lo) || 1)) * (H - 6);
  for (let i = 0; i < n; i++) {
    const o = v(i * 4), h = v(i * 4 + 1), l = v(i * 4 + 2), c = v(i * 4 + 3);
    g.fillStyle = c >= o ? '#26a69a' : '#ef5350';
    const x = 1 + i * step, cx = x + bw / 2;
    g.fillRect(cx - 0.4, Y(h), 0.8, Math.max(0.8, Y(l) - Y(h)));
    g.fillRect(x, Math.min(Y(o), Y(c)), bw, Math.max(0.8, Math.abs(Y(c) - Y(o))));
  }
  g.strokeStyle = '#ff9800'; g.lineWidth = 1.6; g.beginPath(); let pen = false;
  for (let i = 0; i < n; i++) { const q = mq.charCodeAt(i); if (q === 255 || Number.isNaN(q)) { pen = false; continue; } const x = 1 + i * step + bw / 2, y = Y(sp.lo + q * mk); pen ? g.lineTo(x, y) : g.moveTo(x, y); pen = true; }
  g.stroke();
  g.setLineDash([4, 3]); g.lineWidth = 1;
  lines.forEach(([p, col]) => { g.strokeStyle = col; g.beginPath(); g.moveTo(0, Y(p)); g.lineTo(W, Y(p)); g.stroke(); });
  g.setLineDash([]);
  cv.dataset.drawn = '1';
}
