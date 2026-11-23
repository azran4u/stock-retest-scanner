// Lives archive page (#/lives, לייבים): Cycles Trading community recordings.
// Data comes from public.lives (owner-only RLS). A static JSON under app/ or dist/ would be
// publicly reachable without login — the site is a static SPA and auth is client-side — so
// this private content is never written into the production build. Demo/dev may inject
// window.__demoLives or, in Vite dev only, fetch /lives-dev.json.

export type LiveArchive = 'students' | 'community';
export type LivesSort = 'date' | 'mentor';
export type HasSummary = '' | 'yes' | 'no';

export interface Live {
  youtube_id: string;
  link: string;
  archive: LiveArchive;
  live_date: string | null;
  post_date: string;
  post_time: string | null;
  mentor: string;
  title: string;
  summary_link: string | null;
  stocks: string[];
  topics: string | null;
  notes: string | null;
  display_date: string;
}

export interface LivesFilters {
  q: string;
  mentor: string;
  archive: '' | LiveArchive;
  hasSummary: HasSummary;
  sort: LivesSort;
}

export const LIVES_UI_DEF: LivesFilters = { q: '', mentor: '', archive: '', hasSummary: '', sort: 'date' };
export const MENTOR_UNKNOWN = 'לא צוין';

export const ARCHIVE_HE: Record<LiveArchive, string> = { community: 'קהילה', students: 'תלמידים' };

export function esc(s: unknown): string {
  return String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]!));
}

function blankToNull(s: unknown): string | null {
  const t = String(s ?? '').trim();
  return t ? t : null;
}

export function parseStocks(raw: unknown): string[] {
  if (Array.isArray(raw)) return raw.map((x) => String(x).trim()).filter(Boolean);
  return String(raw ?? '').trim().split(/\s+/).filter(Boolean);
}

export function displayDateOf(row: { live_date?: string | null; post_date?: string | null }): string {
  return blankToNull(row.live_date) || blankToNull(row.post_date) || '';
}

export function formatLiveDate(iso: string): string {
  const m = /^(\d{4})-(\d{2})-(\d{2})$/.exec(iso || '');
  return m ? `${m[3]}.${m[2]}.${m[1]}` : (iso || '—');
}

export function normalizeLive(raw: any): Live | null {
  const youtube_id = String(raw?.youtube_id ?? '').trim();
  const link = String(raw?.link ?? '').trim();
  if (!youtube_id && !link) return null;
  const archive: LiveArchive = raw?.archive === 'students' ? 'students' : 'community';
  const live_date = blankToNull(raw?.live_date);
  const post_date = blankToNull(raw?.post_date) || live_date || '';
  const mentor = blankToNull(raw?.mentor) || MENTOR_UNKNOWN;
  const title = String(raw?.title ?? '').trim() || 'הקלטת לייב';
  const stocks = parseStocks(raw?.stocks);
  const display_date = blankToNull(raw?.display_date) || displayDateOf({ live_date, post_date });
  return {
    youtube_id: youtube_id || link,
    link: link || (youtube_id ? `https://youtu.be/${youtube_id}` : ''),
    archive, live_date, post_date, post_time: blankToNull(raw?.post_time),
    mentor, title, summary_link: blankToNull(raw?.summary_link),
    stocks, topics: blankToNull(raw?.topics), notes: blankToNull(raw?.notes),
    display_date,
  };
}

export function normalizeLives(raw: any[]): Live[] {
  const out: Live[] = [];
  const seen = new Set<string>();
  for (const r of raw || []) {
    const row = normalizeLive(r);
    if (!row) continue;
    if (seen.has(row.youtube_id)) continue;
    seen.add(row.youtube_id);
    out.push(row);
  }
  return out;
}

function normQ(s: string): string {
  return s.trim().toLowerCase();
}

export function matchesLive(row: Live, f: LivesFilters): boolean {
  if (f.mentor && row.mentor !== f.mentor) return false;
  if (f.archive && row.archive !== f.archive) return false;
  if (f.hasSummary === 'yes' && !row.summary_link) return false;
  if (f.hasSummary === 'no' && row.summary_link) return false;
  const q = normQ(f.q);
  if (q) {
    const hay = [row.title, row.mentor, row.stocks.join(' ')].join('\n').toLowerCase();
    if (!hay.includes(q)) return false;
  }
  return true;
}

export function compareLives(a: Live, b: Live, sort: LivesSort): number {
  if (sort === 'mentor') {
    const m = a.mentor.localeCompare(b.mentor, 'he');
    if (m) return m;
  }
  // date: newest first; same day -> later post_time first
  const d = (b.display_date || '').localeCompare(a.display_date || '');
  if (d) return d;
  const t = (b.post_time || '').localeCompare(a.post_time || '');
  if (t) return t;
  return a.title.localeCompare(b.title, 'he') || a.youtube_id.localeCompare(b.youtube_id);
}

export function filterLives(rows: Live[], f: LivesFilters): Live[] {
  return rows.filter((r) => matchesLive(r, f)).sort((a, b) => compareLives(a, b, f.sort));
}

export function mentorsOf(rows: Live[]): string[] {
  return [...new Set(rows.map((r) => r.mentor))].sort((a, b) => a.localeCompare(b, 'he'));
}

export function livesToolbarHtml(f: LivesFilters, count: number, total: number, mentors: string[]): string {
  const opt = (value: string, label: string, cur: string) =>
    `<option value="${esc(value)}" ${cur === value ? 'selected' : ''}>${esc(label)}</option>`;
  return `
  <div class="filters lives-filters">
    <input id="lvQ" type="search" placeholder="חיפוש לפי כותרת, מנטור או טיקר" value="${esc(f.q)}" enterkeyhint="search" />
    <div class="lives-frow">
      <label class="sortlab"><span>מנטור:</span>
        <select id="lvMentor" aria-label="סינון לפי מנטור">
          ${opt('', 'הכל', f.mentor)}
          ${mentors.map((m) => opt(m, m, f.mentor)).join('')}
        </select>
      </label>
      <label class="sortlab"><span>ארכיון:</span>
        <select id="lvArchive" aria-label="סינון לפי ארכיון">
          ${opt('', 'הכל', f.archive)}
          ${opt('community', ARCHIVE_HE.community, f.archive)}
          ${opt('students', ARCHIVE_HE.students, f.archive)}
        </select>
      </label>
      <label class="sortlab"><span>סיכום:</span>
        <select id="lvSum" aria-label="סינון לפי דף סיכום">
          ${opt('', 'הכל', f.hasSummary)}
          ${opt('yes', 'עם דף סיכום', f.hasSummary)}
          ${opt('no', 'בלי דף סיכום', f.hasSummary)}
        </select>
      </label>
      <label class="sortlab"><span>מיון:</span>
        <select id="lvSort" aria-label="מיון">
          ${opt('date', 'תאריך (חדש → ישן)', f.sort)}
          ${opt('mentor', 'מנטור', f.sort)}
        </select>
      </label>
    </div>
    <div class="sortrow"><span class="muted small" id="lvCount">${count} מתוך ${total} לייבים</span></div>
  </div>`;
}

function linkCell(href: string | null, label: string, dataLabel: string): string {
  if (!href) return `<td data-label="${esc(dataLabel)}"><span class="muted">—</span></td>`;
  return `<td data-label="${esc(dataLabel)}"><a class="lv-link" href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(label)}</a></td>`;
}

export function liveRowHtml(row: Live): string {
  const stocks = row.stocks.length
    ? `<span class="lv-stocks" dir="ltr">${row.stocks.map((t) => `<span class="badge">${esc(t)}</span>`).join(' ')}</span>`
    : `<span class="muted">—</span>`;
  return `<tr class="lv-row">
    <td class="lv-date" data-label="תאריך" dir="ltr">${esc(formatLiveDate(row.display_date))}</td>
    <td class="lv-mentor" data-label="מנטור">${esc(row.mentor)}</td>
    <td class="lv-title" data-label="כותרת">${esc(row.title)}</td>
    <td class="lv-arch" data-label="ארכיון"><span class="badge">${esc(ARCHIVE_HE[row.archive])}</span></td>
    ${linkCell(row.link, 'הקלטה', 'הקלטה')}
    ${linkCell(row.summary_link, 'סיכום', 'סיכום')}
    <td class="lv-stocks-td" data-label="מניות">${stocks}</td>
  </tr>`;
}

export function livesTableHtml(rows: Live[]): string {
  if (!rows.length) return `<div id="lvBody" class="center muted">אין לייבים שתואמים את הסינון</div>`;
  return `<div id="lvBody" class="lives-wrap">
    <table class="lives-table">
      <thead>
        <tr>
          <th>תאריך</th><th>מנטור</th><th>כותרת</th><th>ארכיון</th>
          <th>הקלטה</th><th>סיכום</th><th>מניות</th>
        </tr>
      </thead>
      <tbody>${rows.map(liveRowHtml).join('')}</tbody>
    </table>
  </div>`;
}
