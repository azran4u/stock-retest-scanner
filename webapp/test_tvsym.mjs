// TradingView symbol for the copy button (src/tvsym.ts). Usage: node test_tvsym.mjs (exits 1 on any failure)
import { buildSync } from 'esbuild';
import { mkdtempSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
const out = join(mkdtempSync(join(tmpdir(), 'tvs-')), 't.mjs');
buildSync({ entryPoints: [new URL('./src/tvsym.ts', import.meta.url).pathname], bundle: true, format: 'esm', outfile: out, platform: 'node' });
const T = await import(out);
const ok = (c, m) => { if (!c) { console.log('FAIL', m); process.exitCode = 1; } else console.log('ok  ', m); };
const U = (s) => `https://www.tradingview.com/chart/?symbol=${s}`;
ok(T.tvSymbol({ ticker: 'SNX', tv_symbol: 'NYSE:SNX', tradingview_url: U('NASDAQ:SNX') }) === 'NYSE:SNX', 'export tv_symbol wins');
ok(T.tvSymbol({ ticker: 'PNC', tradingview_url: U('NYSE:PNC') }) === 'NYSE:PNC', 'fallback: report url exchange');
ok(T.tvSymbol({ ticker: 'SPY', tradingview_url: U('NYSEARCA%3ASPY') }) === 'AMEX:SPY', 'NYSE Arca -> AMEX');
ok(T.tvSymbol({ ticker: 'BRK-B', tradingview_url: U('NYSE:BRK-B') }) === 'NYSE:BRK.B', 'class share dot (url fallback)');
ok(T.tvSymbol({ ticker: 'CRD-A' }) === 'CRD.A', 'unknown exchange: bare TV name');
ok(T.tvSymbol({ ticker: 'X', tv_symbol: 'bad value' }) === 'X', 'malformed tv_symbol ignored');
ok(T.tvSymbol('mog-a') === 'MOG.A', 'string input');
ok(T.tvList([{ ticker: 'SNX', tv_symbol: 'NYSE:SNX' }, { ticker: 'ARKK', tv_symbol: 'CBOE:ARKK' }, 'QQQ']) === 'NYSE:SNX,CBOE:ARKK,QQQ', 'comma list');
