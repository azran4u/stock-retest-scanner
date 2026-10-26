// 'כללים' page (Eyal 2026-10-26): what FinViz screens, what PASS / WAIT / FAIL mean, needs-drawing, the unfit mark,
// bot drawing rules and sizing. Numbers come from app/data/rules.json (srs_app/rules.py reads them from the code the
// nightly runs), so the page never drifts from the rules; only the Hebrew wording lives here.
const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const n = (x: unknown, d = 2) => { const v = Number(x); return Number.isFinite(v) ? String(+v.toFixed(d)) : '?'; };
const L = (x: unknown) => `<bdi dir="ltr">${esc(x)}</bdi>`;

export interface RulesJson {
  generated_at?: string;
  screener?: { url?: string; filters?: { code: string; he: string }[]; universe?: string };
  core?: string[]; wait?: string[];
  t?: Record<string, any>; bot?: Record<string, any>;
}

/** Hebrew text for each report filter, built from the thresholds */
export function filterText(code: string, t: Record<string, any>): string {
  const m: Record<string, string> = {
    f_dollar_vol: `מחזור דולרי ממוצע ${n(t.avg_vol_days, 0)} יום ≥ ${L('$' + n((t.dollar_vol_min ?? 0) / 1e6, 0) + 'M')}`,
    f_no_earnings_14d: `אין דוחות ב-${n(t.earnings_blackout_days, 0)} הימים הקרובים (תאריך לא ידוע = לא עובר)`,
    f_history: `היסטוריה של ≥ ${n(t.min_weekly_bars, 0)} נרות שבועיים (~3 שנים)`,
    f_rr: `יש לונג שנספר (שלי או של הבוט אחרי אישור) עם R:R ≥ ${n(t.rr_min)} — מחושב מחדש באפליקציה בכל שינוי שרטוט`,
    f_no_red_vol_week: `אין נר שבועי אדום בריא (גוף ≥ ${n((t.red_vol_body_min ?? 0) * 100, 0)}% מהטווח) עם מחזור יומי ממוצע מעל ממוצע ${n(t.red_vol_avg_days, 0)} הימים שלפניו בשבוע האחרון שנסגר`,
    f_from_above: `החזרה לאזור מלמעלה: הסגירה השבועית האחרונה מחוץ לאזור (${n(t.from_above_lookback_w, 0)} שבועות אחורה, סבולת ${n(t.from_above_tol_atr)} ATR) הייתה מעל האזור`,
    f_no_inv_hammer: `הנר השבועי האחרון שנסגר אינו פטיש הפוך (פתיל עליון ≥ ${n(t.inv_hammer_upper_min)}× הגוף, פתיל תחתון ≤ ${n((t.inv_hammer_lower_max ?? 0) * 100, 0)}% מהטווח)`,
  };
  return m[code] || esc(code);
}

export function renderRulesHtml(j: RulesJson | null, o: { maxRisk: number }): string {
  if (!j) return `<p class="muted">לא נמצא קובץ הכללים (data/rules.json). הוא נוצר בהרצה הלילית.</p>`;
  const t = j.t || {}, b = j.bot || {}, sc = j.screener || {};
  const core = j.core || [], wait = j.wait || [];
  const li = (xs: string[]) => `<ul>${xs.map((x) => `<li>${x}</li>`).join('')}</ul>`;
  const sec = (id: string, title: string, body: string) => `<section class="card rsec" id="r-${id}"><h3>${title}</h3>${body}</section>`;
  const fv = (sc.filters || []).map((f) => `${esc(f.he)} <span class="muted small">${L(f.code)}</span>`);
  const kindsHe: Record<string, string> = { hammer: 'פטיש', engulfing: 'בולע', strong_close: 'סגירה חזקה', rejection: 'דחייה (פתיל תחתון ארוך)' };
  return [
    `<p class="muted small">נוצר מהקוד שרץ בלילה · ${L((j.generated_at || '').slice(0, 10))}</p>`,
    sec('finviz', '1. מה מסונן ב-FinViz', li(fv) + `<p class="small muted">יקום: מניות + ETF. כל השאר נבדק אחר כך על כל מניה בנפרד. (הוסר ב-26/10/2026: "מחיר מעל SMA200".)</p>`
      + (sc.url ? `<p class="small"><a href="${esc(sc.url)}" target="_blank" rel="noopener" dir="ltr">הסריקה ב-FinViz ↗</a></p>` : '')),
    sec('pass', '2. PASS — כל התנאים חייבים להתקיים', li(core.map((c) => filterText(c, t)))
      + `<p class="small muted">מגמת עליה ראשית (טכנית) וסחירות לחשבון <b>אינן</b> תנאי ל-PASS — הן פילטרים נפרדים ברשימה.</p>`),
    sec('wait', '3. WAIT — ממתינה לסגירה', `<p>כל תנאי ה-PASS מתקיימים חוץ מאחד מאלה, על הנר השבועי האחרון שנסגר:</p>` + li(wait.map((c) => filterText(c, t)))
      + `<p class="small muted">חוזרת ל-PASS אם הנר השבועי הבא נסגר בלי לשבור את האזור.</p>`),
    sec('fail', '4. FAIL', `<p>כל מניה שלא עומדת באחד מתנאי ה-PASS (מעבר ל-WAIT). בכרטיס מופיעה הסיבה, למשל "אין לונג", "R:R 1.6 < ${n(t.rr_min)}", "חזרה לאזור מלמטה".</p>`),
    sec('tech', '5. מגמת עליה ראשית (טכנית)', li([
      `קרוב לשיא: השיא של ${n(t.tech_recent_weeks, 0)} השבועות האחרונים ≥ השיא של ${n(t.tech_newhi_lookback_weeks, 0)} השבועות שלפניו ${L(n(t.tech_newhi_atr) + ' ATR')}`,
      `ממוצע נע מעריכי ${n(t.tech_ema_span, 0)} שבועות עלה ≥ ${n(t.tech_ema_min_pct)}% ב-${n(t.tech_recent_weeks, 0)} שבועות`,
      `לא דשדוש רב-שנתי: R² ≥ ${n(t.tech_flat_r2_max)} ב-${(t.tech_flat_windows || []).join(' או ')} שבועות`,
      `נדרשים ≥ ${n(t.tech_min_weekly_bars, 0)} נרות שבועיים; ההחלטה שלי (לא טכנית) גוברת על החישוב`]) ),
    sec('need', '6. צריך שרטוט', `<p>מחזור, דוחות והיסטוריה תקינים + מגמת עליה ראשית, ואין שרטוט (או ששרטוט הבוט נדחה). לא חלק מ-PASS.</p>`),
    sec('unfit', '7. לא מתאימה לשיטה', `<p>סימון ידני ל-4 / 8 / 12 / 26 שבועות (ברירת מחדל 8) או עד תאריך, עם סיבה אופציונלית. עד אז: מוסתרת מהרשימה, לא נכנסת לשרטוט הבוט, ונחשבת "לא טכנית". בפילטר "לא מתאימות לשיטה" אפשר להציג רק אותן או גם אותן.</p>`),
    sec('bot', '8. כללי השרטוט של הבוט', li([
      `גרסה ${L(b.rule_version)}; מועמדות: מחזור + היסטוריה + בלי דוחות + טכנית, בלי שרטוט חי, לא "לא מתאימה", בלי משוב "מבנה" ב-${n(b.structure_exclude_weeks, 0)} השבועות האחרונים`,
      `האזור נבחר לפי מספר הנגיעות השבועיות (${n(b.touch_lookback_w, 0)} שבועות, סבולת ${n(b.touch_tol_atr)} ATR), עדיפות לרמה קרובה וחדשה`,
      `לא יותר מ-${n(b.far_cap_atr)} ATR שבועי מתחת למחיר; האזור חייב להיות מתחת למחיר`,
      `לונג: כניסה באמצע האזור, סטופ מתחת לפתיל העמוק (0.5–1 ATR), יעד בגוף נר השיא האחרון; אורך ${n(b.long_w_bars, 0)} נרות שבועיים`,
      `שרטוט של הבוט לא נספר ל-PASS עד שאני מאשר אותו; שבור / הגיע ליעד / רחוק → לא עדכני ושרטוט מחדש`]) ),
    sec('size', '9. גודל פוזיציה', `<p>סיכון מקסימלי לעסקה: <b>${L('$' + n(o.maxRisk))}</b> (חשבון × אחוז סיכון; ברירת מחדל $5000 × 1%). מניות = ⌊סיכון ÷ (כניסה − סטופ)⌋. "סחירה לחשבון" = ATR שבועי קטן מהסיכון המקסימלי.</p>`),
    sec('rev', '10. נרות היפוך (לפילטרים)', `<p>סוגים: ${(t.reversal_kinds || []).map((k: string) => kindsHe[k] || k).join(' · ')}. הפילטר בודק את הנר האחרון מכל סוג (יומי / שבועי) ב-X השבועות האחרונים, בלי תלות באזור. ברירת מחדל: פטיש + בולע.</p>`),
  ].join('');
}
