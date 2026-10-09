/* Shared filter definitions + filter UI for index.html (charts) and table.html (report table).
 * Single source of truth: both pages render the same ANDed filter checkboxes from FILTERS,
 * evaluate earnings live the same way and export the same TradingView watchlist format.
 * Thresholds documented in RULES.md; values computed in report_filters.py. */
(function (global) {
"use strict";
// Filter definitions (thresholds documented in RULES.md; values set in report_filters.py CONFIG)
// Labels may be functions of the live grade parameters P = {earnDays, minDollarVolM, smoothN, rrX}
const FILTERS = [
  { col: "f_dollar_vol",      label: P => `$vol ≥ $${P.minDollarVolM}M (30d)`, core: true, must: true, tip: "30-day average dollar volume ≥ V (dollar_vol_30d; V = the $vol input, default $50M — recomputed live)" },
  { col: "f_short_float",     label: "short float < 5%",      core: true, must: true, tip: "FinViz short float < 5% (short_float_pct). Missing → false" },
  { col: "f_no_earnings_14d", label: P => `no earnings ≤${P.earnDays}d`, core: true, must: true, tip: "Next earnings NOT within E days (E = the earnings-days input, default 14) — computed live from the stored earnings_date (today, Asia/Jerusalem). Unknown / already-passed date → false" },
  { col: "f_history",         label: "history ≥ 3y",          core: true, must: true, tip: "≥ 150 weekly bars (weekly_bars)" },
  { col: "f_rr",              label: "TV R:R ≥ 2",            core: true, must: true, tip: "TradingView drawing that counts (user-owned or approved bot drawing) AND TradingView Long Position R:R ≥ 2. No drawing / not checked / bot drawing awaiting review → fails. Part of status=PASS (Grok sync)" },
  { col: "f_technical",       label: "technical (weekly uptrend)", core: false, must: true, tip: "Clear weekly uptrend: recent 26w high ≥ 1 weekly ATR above the prior 2.5y high, ≥ 50% higher highs / higher lows over 78w (strength-3 swings, current-pullback lows ignored), 30w EMA higher than 26w ago. Empty with < 130 weekly bars. Must-have for a grade; not part of status" },
  { col: "f_must_haves",      label: "all must-haves", core: false, group: "Grade", tip: "All 9 must-haves pass (FinViz list, short float < 5%, no earnings ≤ E days, $vol ≥ V, history ≥ 3y, tradable with account, technical, price near zone, TV R:R ≥ 2) = the stock gets a grade A/B/C/D" },
  { col: "f_weekly_reversal", label: "E1 weekly reversal (5w)",  core: false, group: "Evidence", ev: 1, short: "W-rev", tip: "E1: reversal-shape weekly candle (hammer/engulfing/strong_close/rejection, shape only) in the last 5 completed weeks" },
  { col: "f_daily_reversal",  label: "E2 daily reversal (10d)",  core: false, group: "Evidence", ev: 2, short: "D-rev", tip: "E2: reversal-shape daily candle (same shapes, shape only) in the last 10 completed sessions" },
  { col: "ev_first_reaction", label: "E3 first reaction",        core: false, group: "Evidence", ev: 3, short: "1st reaction", tip: "E3: in the current pullback (after the highest weekly high of the last 52 weeks) a weekly low ≤ zone top, followed by a LATER weekly close ≥ zone top + 0.5 weekly ATR(14). TV zone needed" },
  { col: "ev_double_bottom",  label: "E4 daily double bottom",   core: false, group: "Evidence", ev: 4, short: "dbl bottom", tip: "E4: after the pullback high, a daily low ≤ zone top (1st touch), then a daily high ≥ zone top + 1 daily ATR(14) (push), then a 2nd touch: a daily low ≤ zone top in the last 10 sessions OR the latest close within 1 daily ATR of the zone; not broken (close ≥ zone bottom − 1 daily ATR). TV zone needed" },
  { col: "f_smooth_streak",   label: P => `E5 smooth pullback ≥${P.smoothN}w`, core: false, group: "Evidence", ev: 5, short: P => `smooth ≥${P.smoothN}w`, tip: "E5: ≥ N consecutive smooth weekly candles back from the last completed week (smooth_streak_weeks; N = the smooth-weeks input, default 5 — recomputed live)" },
  { col: "f_rr_x",            label: P => `E6 TV R:R ≥ ${P.rrX}`, core: false, group: "Evidence", ev: 6, short: P => `R:R ≥${P.rrX}`, tip: "E6: TV R:R ≥ X from a drawing that counts (X = the R:R input, default 3; the must-have is ≥ 2)" },
  { col: "ev_ma_support",     label: "E7 MA support",            core: false, group: "Evidence", ev: 7, short: "MA", tip: "E7: SMA 50/100/150/200 (daily): latest daily low ≤ SMA + 1 daily ATR and latest close ≥ SMA, AND the same SMA held as support before (≥ 1 earlier touch in the ~2 years before the last 20 sessions: came from above, low ≤ SMA + 1 ATR, close ≥ SMA, local low, then a close ≥ SMA + 2 ATR within 20 sessions)" },
  { col: "ev_fib",            label: "E8 fib confluence",        core: false, group: "Evidence", ev: 8, short: "fib", tip: "E8: the TV zone (± 0.25 weekly ATR) contains the 0.382 / 0.5 / 0.618 retracement of the latest weekly swing: swing high = highest weekly high of the last 52 weeks, swing low = lowest weekly low in the 52 weeks up to it. TV zone needed" },
  { col: "tv_found",          label: "TV drawing found",      core: false, group: "TradingView", tip: "Zone rectangle + Long Position drawing found on the user's TradingView chart (read-only daily read; tv_found = yes)" },
  { col: "needs_drawing",     label: "needs drawing",         core: false, group: "TradingView", tip: "$vol + short float + no earnings ≤14d + history all pass, but no TradingView drawing at all (not found, or not read yet; tickers with a bot drawing are excluded and show as review needed) — grok_needs_drawing_target. Not part of status" },
  { col: "f_bot_review",      label: "bot drawing — review needed", core: false, group: "TradingView", tip: "The bot drew the Rectangle + Long Position for this ticker (bot_drawings.json); it does NOT count toward f_rr / PASS / Grok until you approve it (approved_bot_drawings.json). Editing its levels on TradingView makes it yours" },
  { col: "f_tradable",        label: "tradable with account", core: false, group: "TradingView", must: true, tip: "Drawn tickers with shares ≥ 1 under the current position-sizing settings (client-side, live). Must-have for a grade; not part of status" },
  { col: "f_not_tradable",    label: "not tradable (account limits)", core: false, group: "TradingView", tip: "Drawn tickers where the sizing gives 0 shares (1 share risks more than max risk %, or costs more than max position %). Not part of status" },
  { col: "f_tv_stale",        label: "drawing may be obsolete", core: false, group: "TradingView", tip: "Drawn tickers whose drawing may be obsolete: broken (any price — daily low — below the drawn SL since the read date), target hit (close ≥ TP) or far (close > zone top + 3 weekly ATR). Informational, not part of status" },
  { col: "f_near_zone",       label: "price near zone (≤1 ATR)", core: false, group: "TradingView", must: true, tip: "TV drawings only: latest daily close inside the TV zone or within 1 × weekly ATR(14) of its nearest edge. Empty (fails) when there is no drawing. Must-have for a grade; not part of status" },
];
const CORE = FILTERS.filter(f => f.core).map(f => f.col);
// The 9 must-haves (1 = in the FinViz list is true for every report row): a grade needs all of them
const MUST = ["f_short_float", "f_no_earnings_14d", "f_dollar_vol", "f_history", "f_tradable", "f_technical", "f_near_zone", "f_rr"];
const MUST_LABEL = { f_short_float: "short float ≥ 5%", f_no_earnings_14d: P => `earnings ≤${P.earnDays}d / unknown`,
  f_dollar_vol: P => `$vol < $${P.minDollarVolM}M`, f_history: "history < 3y", f_tradable: "not tradable with account",
  f_technical: "not technical", f_near_zone: "not near zone", f_rr: "no counted TV R:R ≥ 2" };
const EVIDENCE = FILTERS.filter(f => f.ev).sort((a, b) => a.ev - b.ev);
const GRADES = ["A", "B", "C", "D"];
const EARNINGS_BLACKOUT_DAYS = 14;  // default E

// ---- live grade parameters (E, V, N, X), shared by both pages (localStorage srs_grade_params_v1) ----
const PARAMS_KEY = "srs_grade_params_v1";
const PARAM_DEFAULTS = { earnDays: 14, minDollarVolM: 50, smoothN: 5, rrX: 3 };
const PARAM_FIELDS = [
  { k: "earnDays", label: "E: no earnings (days)", step: "1", min: "0", tip: "Must-have: no earnings within E days (default 14). Drives the earnings filter" },
  { k: "minDollarVolM", label: "V: min $vol ($M)", step: "5", min: "0", tip: "Must-have: 30-day average dollar volume ≥ V million (default 50). Drives the $vol filter" },
  { k: "smoothN", label: "N: smooth weeks", step: "1", min: "0", tip: "E5: smooth pullback ≥ N weeks (default 5). Drives the smooth-pullback filter" },
  { k: "rrX", label: "X: TV R:R for E6", step: "0.1", min: "0", tip: "E6: TV R:R ≥ X (default 3; the must-have is ≥ 2)" },
];
const _pnum = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };
function loadParams() {
  try {
    const s = JSON.parse(localStorage.getItem(PARAMS_KEY) || "{}") || {};
    const out = Object.assign({}, PARAM_DEFAULTS);
    for (const f of PARAM_FIELDS) { const n = _pnum(s[f.k]); if (n !== null && n >= 0) out[f.k] = n; }
    return out;
  } catch (_) { return Object.assign({}, PARAM_DEFAULTS); }
}
function saveParams(p) { try { localStorage.setItem(PARAMS_KEY, JSON.stringify(p)); } catch (_) {} }
function resetParams() { try { localStorage.removeItem(PARAMS_KEY); } catch (_) {} }
const labelOf = (f, P) => typeof f === "function" ? f(P || loadParams()) : (typeof f.label === "function" ? f.label(P || loadParams()) : f.label);
const textOf = (v, P) => typeof v === "function" ? v(P || loadParams()) : v;

/** Mount the E / V / N / X inputs into `el`; onChange(params) after every edit. */
function mountParams(el, onChange) {
  const P = loadParams();
  el.classList.add("grade-bar");
  el.innerHTML = `<span class="gb-title" title="Grade = how much reversal evidence (E1–E8) a stock has at its zone, only for stocks passing all 9 must-haves. A = all 8, B = 1 missing, C = 2 missing, D = 3+ missing, – = a must-have fails">Grade settings</span>` +
    PARAM_FIELDS.map(f => `<label class="gb" title="${f.tip}">${f.label}<input type="number" data-gp="${f.k}" step="${f.step}" min="${f.min}" value="${P[f.k]}"/></label>`).join("");
  const read = () => {
    const cur = loadParams();
    el.querySelectorAll("input[data-gp]").forEach(i => { const n = _pnum(i.value); if (n !== null && n >= 0) cur[i.dataset.gp] = n; });
    return cur;
  };
  el.addEventListener("input", ev => { if (ev.target.matches("input[data-gp]")) { const cur = read(); saveParams(cur); onChange(cur); } });
  const sync = () => { const cur = loadParams(); el.querySelectorAll("input[data-gp]").forEach(i => { i.value = cur[i.dataset.gp]; }); };
  el._srsSync = sync;
  window.addEventListener("storage", ev => { if (ev.key !== PARAMS_KEY) return; sync(); onChange(loadParams()); });
  return { sync };
}

/** Recompute the live flags on every row (call after enrichEarningsLive + the sizing flags):
 *  f_no_earnings_14d / earnings_blackout (E), f_dollar_vol (V), f_smooth_streak (N), f_rr_x (X),
 *  f_must_haves, mh_failed (labels), ev_count, ev_missing, grade (A/B/C/D, "-" = a must-have fails). */
function applyLive(rows, P) {
  P = P || loadParams();
  for (const r of rows) {
    if ("earnings_date" in r) {
      const d = liveDaysToEarnings(r.earnings_date);
      const ok = d !== null && d >= 0 && d >= P.earnDays;
      r.earnings_blackout = d !== null && d >= 0 && d < P.earnDays;
      if ("f_no_earnings_14d" in r) r.f_no_earnings_14d = ok ? "True" : "False";
    }
    if ("dollar_vol_30d" in r && "f_dollar_vol" in r) {
      const v = _pnum(r.dollar_vol_30d);
      r.f_dollar_vol = v !== null && v >= P.minDollarVolM * 1e6 ? "True" : "False";
    }
    if ("smooth_streak_weeks" in r && "f_smooth_streak" in r) {
      const n = _pnum(r.smooth_streak_weeks);
      r.f_smooth_streak = n !== null && n >= P.smoothN ? "True" : "False";
    }
    if ("tv_rr" in r) {
      const x = _pnum(r.tv_rr);
      r.f_rr_x = isTrueFlag(r.f_rr) && x !== null && x >= P.rrX ? "True" : "False";
    }
    if (!("ev_fib" in r)) { r.grade = ""; r.f_must_haves = ""; continue; }  // older schema: no grade
    const failed = MUST.filter(c => !isTrueFlag(r[c]));
    r.mh_failed = failed.map(c => textOf(MUST_LABEL[c], P)).join(", ");
    r.f_must_haves = failed.length ? "False" : "True";
    const missing = EVIDENCE.filter(f => !isTrueFlag(r[f.col]));
    r.ev_count = EVIDENCE.length - missing.length;
    r.ev_missing = missing.map(f => "E" + f.ev).join(",");
    r.grade = failed.length ? "-" : (missing.length === 0 ? "A" : missing.length === 1 ? "B" : missing.length === 2 ? "C" : "D");
  }
  return rows;
}
const GRADE_RANK = { A: 0, B: 1, C: 2, D: 3, "-": 4, "": 5 };

/** Tooltip text per evidence item (includes the MA / fib level names). */
function evidenceTip(r, f, P) {
  const yes = isTrueFlag(r[f.col]);
  const head = `E${f.ev} ${labelOf(f, P).replace(/^E\d+ /, "")}: ${yes ? "present" : "missing"}`;
  const d = {
    1: r.weekly_reversal_kind ? `${r.weekly_reversal_kind} week of ${r.weekly_reversal_date}` : "no reversal-shape weekly candle in the last 5 weeks",
    2: r.daily_reversal_kind ? `${r.daily_reversal_kind} on ${r.daily_reversal_date}` : "no reversal-shape daily candle in the last 10 sessions",
    3: r.ev_first_reaction_detail || "no TV zone",
    4: r.ev_double_bottom_detail || "no TV zone",
    5: `smooth streak ${r.smooth_streak_weeks || "n/a"} weeks (needs ≥ ${P.smoothN})`,
    6: `TV R:R ${r.tv_rr || "n/a"}${isTrueFlag(r.f_rr) ? "" : " (not a counted drawing)"} (needs ≥ ${P.rrX})`,
    7: (r.ev_ma_support_mas ? r.ev_ma_support_mas + " — " : "") + (r.ev_ma_support_detail || "n/a"),
    8: (r.ev_fib_levels ? "fib " + r.ev_fib_levels + " — " : "") + (r.ev_fib_detail || "no TV zone"),
  }[f.ev];
  return `${head} — ${d}`;
}

/** Compact present / missing evidence chips (+ grade badge / failing must-haves when wanted). */
function evidenceChips(r, P) {
  P = P || loadParams();
  if (!("ev_fib" in r)) return "";
  return `<span class="evchips">` + EVIDENCE.map(f => {
    const yes = isTrueFlag(r[f.col]);
    let lab = textOf(f.short, P);
    if (f.ev === 7 && yes && r.ev_ma_support_mas) lab = "MA " + r.ev_ma_support_mas.replace(/SMA/g, "");
    if (f.ev === 8 && yes && r.ev_fib_levels) lab = "fib " + r.ev_fib_levels;
    return `<span class="evc ${yes ? "yes" : "no"}" title="${escA(evidenceTip(r, f, P))}">${yes ? "✓" : "✗"} ${escA(lab)}</span>`;
  }).join("") + `</span>`;
}
function gradeBadge(r, big) {
  const g = r.grade;
  if (!g) return "";
  const tip = g === "-" ? `No grade — must-have fails: ${r.mh_failed}` :
    `Grade ${g}: ${r.ev_count}/8 evidence items` + (r.ev_missing ? ` (missing ${r.ev_missing})` : " (all present)");
  return `<span class="grade g${g === "-" ? "x" : g}${big ? " big" : ""}" title="${escA(tip)}">${g === "-" ? "–" : g}</span>`;
}
const escA = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/"/g, "&quot;").replace(/</g, "&lt;").replace(/>/g, "&gt;");

function isTrueFlag(val) {
  return val === true || ["true", "1", "yes"].includes(String(val).toLowerCase());
}

function todayJerusalemISO() {
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Jerusalem", year: "numeric", month: "2-digit", day: "2-digit"
  }).format(new Date());
}

function liveDaysToEarnings(earningsDate) {
  if (!earningsDate) return null;
  const ed = String(earningsDate).slice(0, 10);
  if (!/^\d{4}-\d{2}-\d{2}$/.test(ed)) return null;
  const today = todayJerusalemISO();
  const a = Date.parse(today + "T00:00:00Z");
  const b = Date.parse(ed + "T00:00:00Z");
  if (!Number.isFinite(a) || !Number.isFinite(b)) return null;
  return Math.round((b - a) / 86400000);
}

/** Earnings are evaluated LIVE from the stored absolute earnings_date (Asia/Jerusalem today):
 *  days_to_earnings, earnings_blackout and f_no_earnings_14d are recomputed; a date already
 *  in the past counts as unknown (false). `status` stays as of the report date. */
function enrichEarningsLive(rows) {
  return rows.map(r => {
    const out = Object.assign({}, r);
    const days = liveDaysToEarnings(out.earnings_date);
    if (days !== null) {
      out.days_to_earnings = days >= 0 ? days : "";
      out.earnings_known = days >= 0;
      const E = loadParams().earnDays;
      out.earnings_blackout = days >= 0 && days < E;
      if ("f_no_earnings_14d" in out) out.f_no_earnings_14d = days >= E;
    }
    return out;
  });
}

/** AND of the checked filters; checked grades ("grade:A" …) are ORed among themselves. */
function rowPasses(r, active) {
  const grades = [];
  for (const col of active) {
    if (col.startsWith("grade:")) { grades.push(col.slice(6)); continue; }
    if (!isTrueFlag(r[col])) return false;
  }
  return !grades.length || grades.includes(r.grade);
}

/** Filter columns present in a loaded CSV header (f_rr only when the TV columns exist). */
function availableFilters(headers) {
  const hdr = new Set(headers);
  // live-computed columns exist when their inputs are in the CSV
  if (hdr.has("tv_rr") && hdr.has("f_rr")) hdr.add("f_rr_x");
  if (hdr.has("tv_entry")) { hdr.add("f_tradable"); hdr.add("f_not_tradable"); }
  const out = new Set(FILTERS.map(f => f.col).filter(c => hdr.has(c) && (c !== "f_rr" || hdr.has("tv_found"))));
  if (hdr.has("ev_fib")) { out.add("f_must_haves"); GRADES.concat(["-"]).forEach(g => out.add("grade:" + g)); }
  return out;
}

function renderFilterBox(box, allRows, available, checked, onChange) {
  const P = loadParams();
  const groups = [
    ["Must-haves", FILTERS.filter(f => f.must)],
    ["Grade", FILTERS.filter(f => f.group === "Grade")],
    ["Evidence", EVIDENCE],
    ["TradingView", FILTERS.filter(f => f.group === "TradingView" && !f.must)],
  ];
  const chk = (col, label, tip, n, avail) => {
    const on = checked.has(col) && avail;
    return `<label class="fchk${on ? " on" : ""}${avail ? "" : " disabled"}" title="${escA(tip)}${avail ? "" : " — not in this report (older schema)"}">` +
      `<input type="checkbox" data-fcol="${col}" ${on ? "checked" : ""} ${avail ? "" : "disabled"}/>` +
      `${label} <span class="cnt">${n === null ? "n/a" : n}</span></label>`;
  };
  const gradeChips = GRADES.concat(["-"]).map(g => {
    const col = "grade:" + g, avail = available.has(col);
    const n = avail ? allRows.filter(r => r.grade === g).length : null;
    return chk(col, g === "-" ? "– (no grade)" : `<b class="grade g${g} sm">${g}</b>`,
      g === "-" ? "Stocks failing at least one must-have (no grade)" : `Grade ${g} (checked grades are ORed, then ANDed with the other filters)`, n, avail);
  }).join("");
  box.innerHTML = groups.map(([name, fs]) =>
    `<span class="grp">${name}</span>` + (name === "Grade" ? gradeChips : "") + fs.map(f => {
      const avail = available.has(f.col);
      const n = avail ? allRows.filter(r => isTrueFlag(r[f.col])).length : null;
      return chk(f.col, labelOf(f, P), f.tip, n, avail);
    }).join("")
  ).join("");
  box.querySelectorAll("input[data-fcol]").forEach(inp => {
    inp.addEventListener("change", () => {
      const c = inp.getAttribute("data-fcol");
      if (inp.checked) checked.add(c); else checked.delete(c);
      onChange();
    });
  });
}

/** Client-side sizing flags (f_tradable / f_not_tradable): drawn rows only, else "". */
function sizingFlags(r, st) {
  const z = global.Sizing ? global.Sizing.compute(r, st) : null;
  return { z, f_tradable: z ? (z.shares >= 1 ? "True" : "False") : "", f_not_tradable: z ? (z.shares === 0 ? "True" : "False") : "" };
}

function tvSymbolOf(r) {
  const m = String(r.tradingview_url || "").match(/symbol=([^&]+)/);
  if (m) return decodeURIComponent(m[1]).toUpperCase();
  return String(r.ticker || "").trim().toUpperCase().replace(/-/g, ".");
}

/** EXCHANGE:TICKER for rows (dedup, keep order). `symFn` defaults to the row's TradingView link. */
function tvSymbolsForRows(rows, symFn) {
  const seen = new Set(), out = [];
  for (const r of rows) {
    let sym = symFn ? symFn(r) : tvSymbolOf(r);
    if (!sym) sym = String(r.ticker || "").trim().toUpperCase().replace(/-/g, ".");
    if (sym && !seen.has(sym)) { seen.add(sym); out.push(sym); }
  }
  return out;
}

/** TradingView "Import list" format: .txt, comma-separated symbols with exchange prefix. */
function downloadWatchlist(syms, prefix, dateLabel) {
  if (!syms.length) return;
  const blob = new Blob([syms.join(",") + "\n"], { type: "text/plain" });
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = `${prefix}_${dateLabel}_${syms.length}.txt`;
  document.body.appendChild(a);
  a.click();
  setTimeout(() => { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

const CSS = `
  .filters { display:flex; flex-wrap:wrap; gap:8px 14px; align-items:center; margin-top:12px; }
  .filters .grp { color: var(--muted); font-size: 0.75rem; text-transform: uppercase; letter-spacing: .04em; margin-right: 2px; }
  label.fchk { flex-direction: row; align-items: center; gap: 6px; cursor: pointer; user-select: none;
    background: var(--panel); border: 1px solid var(--border); border-radius: 999px; padding: 5px 10px; color: var(--text); font-size: 0.82rem; }
  label.fchk.on { border-color: var(--accent); background: rgba(88,166,255,0.12); }
  label.fchk.disabled { opacity: 0.4; cursor: not-allowed; }
  label.fchk input { accent-color: var(--accent); width: 14px; height: 14px; margin: 0; }
  label.fchk .cnt { color: var(--muted); font-size: 0.75rem; }
  .grade-bar { display:flex; flex-wrap:wrap; gap:10px; align-items:flex-end; margin:10px 0 0; padding:8px 12px; background:var(--panel); border:1px solid var(--border); border-radius:8px; }
  .grade-bar .gb-title { font-weight:600; font-size:.85rem; align-self:center; margin-right:4px; cursor:help; }
  .grade-bar label.gb { display:flex; flex-direction:column; gap:3px; color:var(--muted); font-size:.75rem; }
  .grade-bar input { width:96px; background:var(--bg); color:var(--text); border:1px solid var(--border); border-radius:6px; padding:4px 6px; }
  .grade { display:inline-flex; align-items:center; justify-content:center; min-width:1.6em; height:1.6em; padding:0 .35em; border-radius:6px;
    font-weight:800; font-size:.85rem; border:1px solid var(--border); color:var(--muted); cursor:help; vertical-align:middle; }
  .grade.big { min-width:2.1em; height:2.1em; font-size:1.25rem; border-radius:8px; }
  .grade.sm { min-width:1.3em; height:1.3em; font-size:.75rem; }
  .grade.gA { background:#1f6f3a; color:#fff; border-color:#3fb950; }
  .grade.gB { background:rgba(63,185,80,.25); color:#7ee787; border-color:rgba(63,185,80,.6); }
  .grade.gC { background:rgba(210,153,34,.22); color:#e3b341; border-color:rgba(210,153,34,.6); }
  .grade.gD { background:rgba(248,81,73,.15); color:#ff9b94; border-color:rgba(248,81,73,.5); }
  .grade.gx { background:transparent; color:var(--muted); border-style:dashed; }
  .evchips { display:inline-flex; flex-wrap:wrap; gap:3px; }
  .evc { font-size:.7rem; padding:0 6px; border-radius:999px; border:1px solid var(--border); white-space:nowrap; cursor:help; }
  .evc.yes { color:#7ee787; border-color:rgba(63,185,80,.5); background:rgba(63,185,80,.1); }
  .evc.no { color:var(--muted); opacity:.7; text-decoration:line-through; }
  .mhfail { color:var(--muted); font-size:.72rem; }
  td .evchips { flex-wrap:nowrap; }
`;
function injectCss() {
  if (document.getElementById("srs-filters-css")) return;
  const st = document.createElement("style");
  st.id = "srs-filters-css";
  st.textContent = CSS;
  document.head.appendChild(st);
}

global.SrsFilters = { FILTERS, CORE, MUST, EVIDENCE, GRADES, GRADE_RANK, PARAM_DEFAULTS, loadParams, saveParams, resetParams,
  mountParams, applyLive, labelOf, evidenceChips, evidenceTip, gradeBadge, EARNINGS_BLACKOUT_DAYS, isTrueFlag, todayJerusalemISO, liveDaysToEarnings,
  enrichEarningsLive, rowPasses, availableFilters, renderFilterBox, sizingFlags, tvSymbolsForRows,
  downloadWatchlist, injectCss };
})(window);
