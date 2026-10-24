// Stock overview ("סקירה", Eyal 2026-10-24: "for every PASS stock add a short Hebrew overview: sector, latest
// reports, analyst recommendations, main recent news"). Rows live in Supabase public.ticker_research (owner-only
// RLS; written by the bot: nightly for PASS tickers + starred-stock research). Shown on the stock page of ANY
// ticker that has a row. Text is the bot's Hebrew summary: one topic per line, "נושא: ..." -> bold topic.

export interface Research {
  ticker: string;
  summary_he: string | null;
  data: Record<string, any> | null;
  sources: string[] | null;
  updated_at: string | null;
}

const esc = (s: unknown) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
const ddmmyy = (iso: string | null | undefined) => {
  if (!iso) return '';
  const d = new Date(iso);
  return Number.isNaN(+d) ? '' : d.toLocaleDateString('he-IL', { timeZone: 'Asia/Jerusalem', day: 'numeric', month: 'numeric', year: '2-digit' });
};
const host = (u: string) => { try { return new URL(u).hostname.replace(/^www\./, ''); } catch { return u; } };

/** escape + isolate Latin / number runs ("$17.3B", "EPS $1.22", "Q4 FY26") in <bdi> so they read correctly inside Hebrew */
const LTR_RUN = /[A-Za-z0-9$€£][A-Za-z0-9$€£%.,+\-–/&'’·×]*(?:[ ]+[A-Za-z0-9$€£(][A-Za-z0-9$€£%.,+\-–/&'’·×)]*)*/g;
export function isoLtr(text: string): string {
  let out = '', i = 0;
  for (const m of text.matchAll(LTR_RUN)) {
    const run = m[0].replace(/[\s.,:;(·\-–]+$/, '');   // trailing punctuation stays in the Hebrew flow
    if (!run) continue;
    out += esc(text.slice(i, m.index)) + `<bdi>${esc(run)}</bdi>`;
    i = m.index! + run.length;
  }
  return out + esc(text.slice(i));
}

/** one line -> <p>; a short leading "topic:" (<= 24 chars, before the first colon) is bolded */
export function researchLines(summary: string): { head: string | null; body: string }[] {
  return summary.split(/\n+/).map((l) => l.trim()).filter(Boolean).map((l) => {
    const m = /^([^:\n]{1,24}):\s*(.*)$/.exec(l);
    return m ? { head: m[1], body: m[2] } : { head: null, body: l };
  });
}

export function researchHtml(r: Research | undefined, open: boolean): string {
  if (!r || !r.summary_he) return '';
  const lines = researchLines(r.summary_he)
    .map((x) => `<p>${x.head ? `<b>${isoLtr(x.head)}:</b> ` : ''}${isoLtr(x.body)}</p>`).join('');
  const srcs = (r.sources || []).filter((u) => /^https?:\/\//.test(u));
  const src = srcs.length
    ? `<details class="rs-src"><summary class="muted small">מקורות (${srcs.length})</summary><ul>${srcs.map((u) => `<li><a href="${esc(u)}" target="_blank" rel="noopener" dir="ltr">${esc(host(u))}</a></li>`).join('')}</ul></details>`
    : '';
  return `<details class="research" id="research" ${open ? 'open' : ''}>
    <summary><h3>סקירה</h3><span class="muted small">עודכן ${esc(ddmmyy(r.updated_at))}</span></summary>
    <div class="rs-body small">${lines}</div>${src}
  </details>`;
}
