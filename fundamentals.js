/* Fundamentals analysis (analysis/analysis.json, written by fundamentals.py) for index.html + table.html.
 * Fundamentals.load() once; Fundamentals.get(ticker); Fundamentals.details(row) = collapsible card section;
 * Fundamentals.tip(row) = plain-text tooltip; Fundamentals.body(row) = full HTML (table expandable row). */
(function (global) {
"use strict";
let DATA = null;
const OPEN = new Set();  // card sections the user expanded (survive re-renders)
document.addEventListener("toggle", ev => {
  const d = ev.target; if (!d.matches || !d.matches("details.fund")) return;
  d.open ? OPEN.add(d.dataset.tk) : OPEN.delete(d.dataset.tk);
}, true);
const esc = v => String(v == null ? "" : v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;");
const STALE_DAYS = 14;

async function load() {
  if (DATA) return DATA;
  try { DATA = await (await fetch("analysis/analysis.json?t=" + Date.now())).json(); }
  catch (_) { DATA = { tickers: {} }; }
  return DATA;
}
const get = tk => (DATA && DATA.tickers && DATA.tickers[tk]) || null;
function ageDays(d) {
  const t = Date.parse(d + "T00:00:00Z"); if (!Number.isFinite(t)) return null;
  return Math.floor((Date.now() - t) / 864e5);
}
function freshness(e) {
  const a = ageDays(e.generated_at);
  return `<span class="fa-date${a !== null && a > STALE_DAYS ? " stale" : ""}" title="Analysis written ${esc(e.generated_at)}${e.grade_at_generation ? " (grade then: " + esc(e.grade_at_generation) + ")" : ""}; key stats from Yahoo Finance as of ${esc(e.metrics && e.metrics.as_of)}. Refresh: python fundamentals.py status">as of ${esc(e.generated_at)}${a !== null && a > STALE_DAYS ? " · stale" : ""}</span>`;
}
function body(r, inCard) {
  const e = get(r.ticker); if (!e) return "";
  const li = a => (a || []).map(x => `<li>${esc(x)}</li>`).join("");
  const news = (e.news || []).map(n => `<li><span class="fa-nd">${esc(n.date)}</span> ${esc(n.title)} <a href="${esc(n.url)}" target="_blank" rel="noopener">${esc(n.source || "source")}</a></li>`).join("");
  const srcs = (e.sources || []).map((s, i) => `<a href="${esc(s.url)}" target="_blank" rel="noopener" title="${esc(s.url)}">${esc(s.label || "[" + (i + 1) + "]")}</a>`).join(" · ");
  return `<div class="fa">
    <div class="fa-h"><b>${esc(e.name)}</b>${inCard ? "" : ` · ${esc(e.sector)} / ${esc(e.industry)} ${freshness(e)}`}</div>
    <div class="fa-biz">${esc(e.business)}</div>
    <div class="fa-sec">Latest news</div><ul class="fa-news">${news}</ul>
    <div class="fa-cols"><div><div class="fa-sec pro">Pros</div><ul>${li(e.pros)}</ul></div>
      <div><div class="fa-sec con">Cons / risks</div><ul>${li(e.cons)}</ul></div></div>
    <div class="fa-take"><b>Take:</b> ${esc(e.take)}</div>
    <div class="fa-src">Sources: ${srcs}</div></div>`;
}
function details(r) {
  const e = get(r.ticker); if (!e) return "";
  return `<details class="fund" data-tk="${esc(r.ticker)}"${OPEN.has(r.ticker) ? " open" : ""}><summary>Fundamentals <span class="fa-sum">${esc(e.sector)} · ${esc(e.industry)}</span> ${freshness(e)}</summary>${body(r, true)}</details>`;
}
function tip(r) {
  const e = get(r.ticker); if (!e) return "";
  return `${e.name} — ${e.sector} / ${e.industry} (analysis ${e.generated_at})\n${e.business}\n\nPros:\n${(e.pros || []).map(x => "+ " + x).join("\n")}\n\nCons:\n${(e.cons || []).map(x => "− " + x).join("\n")}\n\nTake: ${e.take}\n(click to expand with news + sources)`;
}
const CSS = `
  details.fund { margin-top:8px; border-top:1px solid var(--border); padding-top:6px; font-size:.8rem; }
  details.fund > summary { cursor:pointer; font-weight:650; color:var(--accent); list-style-position:inside; }
  details.fund .fa-sum { color:var(--muted); font-weight:400; font-size:.75rem; }
  .fa-date { color:var(--muted); font-weight:400; font-size:.7rem; border:1px solid var(--border); border-radius:999px; padding:0 6px; white-space:nowrap; cursor:help; }
  .fa-date.stale { color:#e3b341; border-color:rgba(210,153,34,.6); }
  .fa { line-height:1.4; margin-top:6px; }
  .fa ul { margin:2px 0 6px; padding-left:16px; }
  .fa li { margin:1px 0; }
  .fa-h { margin-bottom:3px; }
  .fa-biz { color:var(--muted); margin-bottom:4px; }
  .fa-sec { font-weight:650; font-size:.75rem; text-transform:uppercase; letter-spacing:.03em; color:var(--muted); }
  .fa-sec.pro { color:#7ee787; } .fa-sec.con { color:#ff9b94; }
  .fa-nd { color:var(--muted); font-variant-numeric:tabular-nums; }
  .fa-cols { display:grid; grid-template-columns:1fr 1fr; gap:8px; }
  .fa-take { margin:2px 0 4px; }
  .fa-src { color:var(--muted); font-size:.7rem; }
  .fa a { color:var(--accent); }
  .fa-btn { cursor:pointer; background:none; border:1px solid var(--border); color:var(--accent); border-radius:6px; padding:0 6px; font-size:.75rem; }
  tr.fundrow > td { background:var(--panel, #161b22); white-space:normal; max-width:none; }
  tr.fundrow .fa { max-width:1100px; }
  @media (max-width:520px) { .fa-cols { grid-template-columns:1fr; } }
`;
function injectCss() {
  if (document.getElementById("srs-fund-css")) return;
  const st = document.createElement("style"); st.id = "srs-fund-css"; st.textContent = CSS; document.head.appendChild(st);
}
global.Fundamentals = { load, get, body, details, tip, injectCss };
})(window);
