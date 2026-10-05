/* Shared filter definitions + filter UI for index.html (charts) and table.html (report table).
 * Single source of truth: both pages render the same ANDed filter checkboxes from FILTERS,
 * evaluate earnings live the same way and export the same TradingView watchlist format.
 * Thresholds documented in RULES.md; values computed in report_filters.py. */
(function (global) {
"use strict";
// Filter definitions (thresholds documented in RULES.md; values set in report_filters.py CONFIG)
const FILTERS = [
  { col: "f_dollar_vol",      label: "$vol ≥ $50M (30d)",     core: true,  tip: "30-day average dollar volume ≥ $50M (dollar_vol_30d)" },
  { col: "f_short_float",     label: "short float < 5%",      core: true,  tip: "FinViz short float < 5% (short_float_pct). Missing → false" },
  { col: "f_no_earnings_14d", label: "no earnings ≤14d",      core: true,  tip: "Next earnings NOT within 14 days — computed live from the stored earnings_date (today, Asia/Jerusalem). Unknown / already-passed date → false" },
  { col: "f_history",         label: "history ≥ 3y",          core: true,  tip: "≥ 150 weekly bars (weekly_bars)" },
  { col: "f_rr",              label: "TV R:R ≥ 2",            core: true, tip: "TradingView drawing found AND TradingView Long Position R:R ≥ 2. No drawing / not checked → fails.. Part of status=PASS (Grok sync)" },
  { col: "f_smooth_streak",   label: "smooth streak ≥5w",     core: false, tip: "≥ 5 consecutive smooth weekly candles back from the last completed week (smooth_streak_weeks)" },
  { col: "f_weekly_reversal", label: "weekly reversal (5w)",  core: false, tip: "Reversal-shape weekly candle (hammer/engulfing/strong_close/rejection, no zone gate) in the last 5 completed weeks" },
  { col: "f_daily_reversal",  label: "daily reversal (10d)",  core: false, tip: "Reversal-shape daily candle (same shapes, no zone gate) in the last 10 completed sessions" },
  { col: "f_technical",       label: "technical (weekly uptrend)", core: false, tip: "Clear weekly uptrend: recent 26w high ≥ 1 weekly ATR above the prior 2.5y high, ≥ 50% higher highs / higher lows over 78w (strength-3 swings, current-pullback lows ignored), 30w EMA higher than 26w ago. Empty with < 130 weekly bars. Informational, not part of status" },
  { col: "tv_found",          label: "TV drawing found",      core: false, group: "TradingView", tip: "Zone rectangle + Long Position drawing found on the user's TradingView chart (read-only daily read; tv_found = yes)" },
  { col: "needs_drawing",     label: "needs drawing",         core: false, group: "TradingView", tip: "$vol + short float + no earnings ≤14d + history all pass, but no TradingView drawing at all (not found, or not read yet; tickers with a bot drawing are excluded and show as review needed) — grok_needs_drawing_target. Not part of status" },
  { col: "f_bot_review",      label: "bot drawing — review needed", core: false, group: "TradingView", tip: "The bot drew the Rectangle + Long Position for this ticker (bot_drawings.json); it does NOT count toward f_rr / PASS / Grok until you approve it (approved_bot_drawings.json). Editing its levels on TradingView makes it yours" },
  { col: "f_tradable",        label: "tradable with account", core: false, group: "TradingView", tip: "Drawn tickers with shares ≥ 1 under the current position-sizing settings (client-side, live). Not part of status" },
  { col: "f_not_tradable",    label: "not tradable (account limits)", core: false, group: "TradingView", tip: "Drawn tickers where the sizing gives 0 shares (1 share risks more than max risk %, or costs more than max position %). Not part of status" },
  { col: "f_tv_stale",        label: "drawing may be obsolete", core: false, group: "TradingView", tip: "Drawn tickers whose drawing may be obsolete: broken (any price — daily low — below the drawn SL since the read date), target hit (close ≥ TP) or far (close > zone top + 3 weekly ATR). Informational, not part of status" },
  { col: "f_near_zone",       label: "price near zone (≤1 ATR)", core: false, group: "TradingView", tip: "TV drawings only: latest daily close inside the TV zone or within 1 × weekly ATR(14) of its nearest edge. Empty (fails) when there is no drawing. Not part of status" },
];
const CORE = FILTERS.filter(f => f.core).map(f => f.col);
const EARNINGS_BLACKOUT_DAYS = 14;

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
      out.earnings_blackout = days >= 0 && days < EARNINGS_BLACKOUT_DAYS;
      if ("f_no_earnings_14d" in out) out.f_no_earnings_14d = days >= EARNINGS_BLACKOUT_DAYS;
    }
    return out;
  });
}

function rowPasses(r, active) {
  for (const col of active) if (!isTrueFlag(r[col])) return false;
  return true;
}

/** Filter columns present in a loaded CSV header (f_rr only when the TV columns exist). */
function availableFilters(headers) {
  const hdr = new Set(headers);
  return new Set(FILTERS.map(f => f.col).filter(c => hdr.has(c) && (c !== "f_rr" || hdr.has("tv_found"))));
}

function renderFilterBox(box, allRows, available, checked, onChange) {
  const groups = [
    ["Core (PASS)", FILTERS.filter(f => f.core)],
    ["Extra", FILTERS.filter(f => !f.core && !f.group)],
    ["TradingView", FILTERS.filter(f => f.group === "TradingView")],
  ];
  box.innerHTML = groups.map(([name, fs]) =>
    `<span class="grp">${name}</span>` + fs.map(f => {
      const avail = available.has(f.col);
      const n = avail ? allRows.filter(r => isTrueFlag(r[f.col])).length : null;
      const on = checked.has(f.col) && avail;
      return `<label class="fchk${on ? " on" : ""}${avail ? "" : " disabled"}" title="${f.tip}${avail ? "" : " — not in this report (older schema)"}">` +
        `<input type="checkbox" data-fcol="${f.col}" ${on ? "checked" : ""} ${avail ? "" : "disabled"}/>` +
        `${f.label} <span class="cnt">${n === null ? "n/a" : n}</span></label>`;
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
`;
function injectCss() {
  if (document.getElementById("srs-filters-css")) return;
  const st = document.createElement("style");
  st.id = "srs-filters-css";
  st.textContent = CSS;
  document.head.appendChild(st);
}

global.SrsFilters = { FILTERS, CORE, EARNINGS_BLACKOUT_DAYS, isTrueFlag, todayJerusalemISO, liveDaysToEarnings,
  enrichEarningsLive, rowPasses, availableFilters, renderFilterBox, sizingFlags, tvSymbolsForRows,
  downloadWatchlist, injectCss };
})(window);
