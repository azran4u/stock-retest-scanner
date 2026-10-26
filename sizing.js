/* Client-side position sizing shared by index.html (charts) and table.html.
 * Settings persisted in localStorage (key srs_sizing_v1), shared by both pages.
 * shares = floor(min(account*risk%/(entry-sl), account*pos%/entry)); 0 if entry <= sl.
 * Only for rows with a TradingView drawing (tv_found = yes, tv_entry / tv_sl / tv_tp). */
(function () {
  const KEY = "srs_sizing_v1";
  const DEFAULTS = { account: 5000, riskPct: 1.1, posPct: 15 };  // max risk $55 per trade (Eyal 2026-10-26; was 1% = $50)
  const FIELDS = [
    { k: "account", label: "Account $", step: "100", min: "0" },
    { k: "riskPct", label: "Max risk %", step: "0.1", min: "0" },
    { k: "posPct", label: "Max position %", step: "1", min: "0" },
  ];
  const num = v => { const n = parseFloat(v); return Number.isFinite(n) ? n : null; };

  function load() {
    try {
      const s = JSON.parse(localStorage.getItem(KEY) || "{}");
      const out = { ...DEFAULTS };
      for (const f of FIELDS) { const n = num(s[f.k]); if (n !== null && n >= 0) out[f.k] = n; }
      if (num(s.riskPct) === 1 && out.account === 5000 && !s.r55) out.riskPct = DEFAULTS.riskPct; // the old saved default 1% -> 1.1% ($55)
      return out;
    } catch (_) { return { ...DEFAULTS }; }
  }
  function save(s) { try { localStorage.setItem(KEY, JSON.stringify({ ...s, r55: 1 })); } catch (_) {} }

  /** {shares, cost, risk, profit, cap} or null when the row has no TV drawing. */
  function compute(row, s) {
    s = s || load();
    if (!row) return null;
    // TV drawing levels; otherwise the last-week hammer levels (display only)
    const tv = row.tv_found === "yes";
    if (!tv && !(row.f_last_week_reversal === "True" && num(row.hammer_entry) !== null)) return null;
    const entry = num(tv ? row.tv_entry : row.hammer_entry), sl = num(tv ? row.tv_sl : row.hammer_sl), tp = num(tv ? row.tv_tp : row.hammer_tp);
    if (entry === null || sl === null || tp === null || entry <= 0) return null;
    const perShare = entry - sl;
    if (perShare <= 0) return { shares: 0, cost: 0, risk: 0, profit: 0, cap: "entry ≤ SL" };
    const byRisk = s.account * s.riskPct / 100 / perShare;
    const bySize = s.account * s.posPct / 100 / entry;
    const shares = Math.max(0, Math.floor(Math.min(byRisk, bySize) + 1e-9));
    return {
      shares,
      cost: shares * entry,
      risk: shares * perShare,
      profit: shares * (tp - entry),
      cap: byRisk <= bySize ? "risk" : "size",
    };
  }

  const money = v => (v === null || v === undefined || v === "") ? "" :
    (v < 0 ? "−$" : "$") + Math.abs(Math.round(v)).toLocaleString("en-US");

  /** Render the settings bar into `el`; onChange(settings) after every edit / reset. */
  function mount(el, onChange) {
    const s = load();
    el.classList.add("sizing-bar");
    el.innerHTML = `<span class="sz-title" title="Position sizing for tickers with a TradingView drawing: shares = floor(min(account×risk% ÷ (entry−SL), account×position% ÷ entry))">Position sizing</span>` +
      FIELDS.map(f => `<label class="sz">${f.label}<input type="number" data-sz="${f.k}" step="${f.step}" min="${f.min}" value="${s[f.k]}"/></label>`).join("") +
      `<button type="button" class="btn sz-reset" title="Reset to 5000 / 1% / 15%">Reset</button>`;
    const read = () => {
      const cur = load();
      el.querySelectorAll("input[data-sz]").forEach(i => { const n = num(i.value); if (n !== null && n >= 0) cur[i.dataset.sz] = n; });
      return cur;
    };
    el.addEventListener("input", ev => { if (ev.target.matches("input[data-sz]")) { const cur = read(); save(cur); onChange(cur); } });
    el.querySelector(".sz-reset").addEventListener("click", () => {
      save({ ...DEFAULTS });
      el.querySelectorAll("input[data-sz]").forEach(i => { i.value = DEFAULTS[i.dataset.sz]; });
      onChange(load());
    });
    window.addEventListener("storage", ev => {  // the other page changed the settings
      if (ev.key !== KEY) return;
      const cur = load();
      el.querySelectorAll("input[data-sz]").forEach(i => { i.value = cur[i.dataset.sz]; });
      onChange(cur);
    });
  }

  window.Sizing = { KEY, DEFAULTS, load, save, compute, money, mount };
})();
