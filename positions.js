// "My positions" (הפוזיציות שלי) — reads positions.json (managed by positions.py; prices refreshed by the daily export)
(function () {
  const NEAR = 0.5; // weekly ATR
  const f = (v, d = 2) => (v == null || isNaN(v) ? "—" : Number(v).toFixed(d));
  const sg = (v, d = 2) => (v == null ? "—" : (v >= 0 ? "+" : "") + Number(v).toFixed(d));
  const cls = v => (v == null ? "" : v >= 0 ? "pos-up" : "pos-dn");
  function calc(p) {
    const m = p.market || {}, c = m.close, e = p.entry_price, s = p.stop, t = p.target, a = m.weekly_atr;
    const o = { c, date: m.date, a };
    if (c == null) return o;
    o.pl = (c - e) * p.qty; o.plp = (c / e - 1) * 100;
    if (s != null && e !== s) {
      o.r = (c - e) / (e - s); o.sp = (c / s - 1) * 100; o.sa = a ? (c - s) / a : null;
      o.stopHit = (m.low ?? c) <= s; o.nearStop = a && ((m.low ?? c) - s) <= NEAR * a;
    }
    if (t != null) {
      o.tp = (t / c - 1) * 100; o.ta = a ? (t - c) / a : null;
      o.tgtHit = (m.high ?? c) >= t; o.nearTgt = a && (t - (m.high ?? c)) <= NEAR * a;
    }
    return o;
  }
  function chips(o) {
    const x = [];
    if (o.stopHit) x.push('<span class="pchip bad">stop hit</span>'); else if (o.nearStop) x.push('<span class="pchip bad">near stop</span>');
    if (o.tgtHit) x.push('<span class="pchip good">target hit</span>'); else if (o.nearTgt) x.push('<span class="pchip good">near target</span>');
    if (!x.length && o.c != null) x.push('<span class="pchip ok">in range</span>');
    return x.join(" ");
  }
  async function render(el, cardHref) {
    let j;
    try { j = await (await fetch("positions.json?t=" + Date.now())).json(); } catch (_) { el.innerHTML = ""; return; }
    const open = (j.positions || []).filter(p => (p.status || "open") === "open");
    const closed = (j.positions || []).filter(p => p.status === "closed");
    const rows = open.map(p => {
      const o = calc(p);
      return `<tr><td><a href="${cardHref(p.ticker)}">${p.ticker}</a>${p.exchange ? `<small> ${p.exchange}</small>` : ""}</td>
        <td>${p.entry_date}</td><td>${p.qty}</td><td>${f(p.entry_price)}</td><td>${f(p.stop)}</td><td>${f(p.target)}</td>
        <td>${f(o.c)}<small> ${o.date || ""}</small></td><td class="${cls(o.pl)}">${sg(o.pl)}</td><td class="${cls(o.plp)}">${sg(o.plp)}%</td>
        <td class="${cls(o.r)}">${sg(o.r)}R</td><td>${f(o.sp, 1)}% · ${f(o.sa)} ATR</td><td>${f(o.tp, 1)}% · ${f(o.ta)} ATR</td><td>${chips(o)}</td></tr>`;
    }).join("");
    const realized = closed.reduce((s, p) => s + (p.realized_pl || 0), 0);
    el.innerHTML = `<details open class="positions"><summary><b>My positions · הפוזיציות שלי</b> (${open.length} open${closed.length ? `, ${closed.length} closed, realized ${sg(realized)}$` : ""})
      <small> · prices ${j.updated_at ? "updated " + j.updated_at.replace("T", " ").slice(0, 16) : ""} · ATR = weekly ATR(14) · near = within ${NEAR} ATR (daily low/high)</small></summary>
      ${open.length ? `<div style="overflow-x:auto"><table class="ptab"><thead><tr><th>Ticker</th><th>Entry date</th><th>Qty</th><th>Entry</th><th>Stop</th><th>Target</th><th>Close</th><th>P/L $</th><th>P/L %</th><th>R</th><th>To stop</th><th>To target</th><th>Status</th></tr></thead><tbody>${rows}</tbody></table></div>` : "<div>No open positions.</div>"}
    </details>`;
  }
  const css = `.positions{margin:10px 0;padding:8px 10px;border:1px solid var(--accent,#58a6ff);border-radius:8px}
  .positions summary{cursor:pointer}.ptab{border-collapse:collapse;margin-top:6px;font-size:.85rem}
  .ptab th,.ptab td{padding:3px 8px;border-bottom:1px solid var(--border,#30363d);text-align:left;white-space:nowrap}
  .pos-up{color:var(--pass,#3fb950)}.pos-dn{color:var(--fail,#f85149)}
  .pchip{padding:1px 6px;border-radius:9px;font-size:.75rem;border:1px solid}.pchip.bad{color:#f85149}.pchip.good{color:#3fb950}.pchip.ok{color:#8b949e}`;
  const st = document.createElement("style"); st.textContent = css; document.head.appendChild(st);
  window.Positions = { render, calc };
})();
