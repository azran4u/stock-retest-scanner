// TradingView symbol 'EXCHANGE:SYMBOL' for the copy button (Eyal 2026-10-27). The export stores row.tv_symbol from
// TradingView's own scanner (srs_app/tv_symbols.py, e.g. NYSE:SNX, AMEX:SPY, CBOE:ARKK, NYSE:BRK.B); fallbacks: the
// exchange in the report tradingview_url, else the bare ticker (TradingView resolves a bare US ticker by itself).

const KNOWN = new Set(['NASDAQ', 'NYSE', 'AMEX', 'CBOE', 'BATS']);
const ALIAS: Record<string, string> = { NYSEARCA: 'AMEX', ARCA: 'AMEX', NYSEAMERICAN: 'AMEX' };

/** class shares as TradingView writes them: BRK-B / BRK/B -> BRK.B */
export const tvName = (t: string) => String(t || '').trim().toUpperCase().replace(/[-/]/g, '.');

export function tvSymbol(r: { ticker: string; tv_symbol?: string | null; tradingview_url?: string | null } | string): string {
  const row = typeof r === 'string' ? { ticker: r } as { ticker: string; tv_symbol?: string | null; tradingview_url?: string | null } : r;
  if (row.tv_symbol && /^[A-Z]+:[A-Z0-9.]+$/.test(row.tv_symbol)) return row.tv_symbol;
  const m = /symbol=([A-Za-z]+)(?::|%3A)/.exec(row.tradingview_url || '');
  const ex = m ? m[1].toUpperCase() : '';
  const e2 = ALIAS[ex] || ex;
  return KNOWN.has(e2) ? `${e2}:${tvName(row.ticker)}` : tvName(row.ticker);
}

/** comma-separated list (TradingView watchlist 'add symbol' / import accepts it) */
export const tvList = (rows: Parameters<typeof tvSymbol>[0][]) => rows.map(tvSymbol).join(',');

/** Copy text: Clipboard API, else a selected textarea + execCommand('copy'). true = copied. */
export async function copyText(text: string): Promise<boolean> {
  try {
    if (navigator.clipboard && window.isSecureContext) { await navigator.clipboard.writeText(text); return true; }
  } catch { /* fall through */ }
  const ta = document.createElement('textarea');
  ta.value = text; ta.setAttribute('readonly', ''); ta.style.cssText = 'position:fixed;top:0;left:0;opacity:0;font-size:16px';
  document.body.appendChild(ta); ta.focus(); ta.select(); ta.setSelectionRange(0, text.length);
  let ok = false; try { ok = document.execCommand('copy'); } catch { ok = false; }
  ta.remove();
  return ok;
}
