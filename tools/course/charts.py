import json, sys, statistics as st
sys.path.insert(0, '/workspace/publish-stock-retest-scanner')
from srs_app import expert_zone as E
import matplotlib; matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.patches import Rectangle
D = '/workspace/publish-stock-retest-scanner/app/data/candles/'
BG, FG, GRID = '#131722', '#d1d4dc', '#2a2e39'
UP, DN = '#26a69a', '#ef5350'
plt.rcParams.update({'font.size': 10, 'text.color': FG, 'axes.labelcolor': FG, 'xtick.color': FG, 'ytick.color': FG,
                     'axes.edgecolor': GRID, 'figure.facecolor': BG, 'axes.facecolor': BG})
META = {}

def daily(t): return json.load(open(D + t + '.json'))['d']
def state(t, asof=None):
    d = daily(t)
    if asof: d = [r for r in d if r[0] <= asof]
    return E.find(d, asof=asof or d[-1][0])

def ma30(W):
    out = []
    for i in range(len(W)):
        out.append(sum(x['close'] for x in W[i-29:i+1]) / 30 if i >= 29 else None)
    return out

def candles(ax, bars, w=0.6):
    for i, b in enumerate(bars):
        o, h, l, c = b['open'], b['high'], b['low'], b['close']
        col = UP if c >= o else DN
        ax.plot([i, i], [l, h], color=col, lw=1)
        ax.add_patch(Rectangle((i - w/2, min(o, c)), w, max(abs(c - o), (h - l) * 0.004), color=col))

def fig(title):
    f, ax = plt.subplots(figsize=(10, 5.2), dpi=100)
    ax.grid(color=GRID, lw=0.6); ax.set_title(title, color=FG, fontsize=12, loc='left')
    ax.yaxis.tick_right()
    return f, ax

def xt(ax, bars, n=8):
    step = max(1, len(bars) // n)
    ax.set_xticks(range(0, len(bars), step)); ax.set_xticklabels([bars[i]['time'][:7] if 'time' in bars[i] else bars[i]['d'][:10] for i in range(0, len(bars), step)], fontsize=8)

def hline(ax, y, x0, x1, col, lab, ls='-', lw=1.4):
    ax.plot([x0, x1], [y, y], color=col, ls=ls, lw=lw)
    ax.text(x1 + 0.3, y, f' {lab} {y:.2f}', color=col, va='center', fontsize=8.5)

def weekly_chart(name, t, title, asof=None, start=None, end=None, z=None, trade=True, show_ma=True, marks=(), extra=None, ma_color_slope=False):
    d = daily(t)
    if end: d = [r for r in d if r[0] <= end]
    W = E.weekly(d); M = ma30(W)
    z = z or state(t, asof)
    i0 = 0
    if start: i0 = next(i for i, w in enumerate(W) if w['time'] >= start)
    bars = W[i0:]; m = M[i0:]
    f, ax = fig(title)
    candles(ax, bars)
    if show_ma:
        if ma_color_slope:
            for i in range(1, len(m)):
                if m[i] and m[i-1]:
                    gi = i0 + i; prev = M[gi-4] if gi >= 4 else None
                    col = '#4caf50' if prev and M[gi] >= prev else '#f44336'
                    ax.plot([i-1, i], [m[i-1], m[i]], color=col, lw=2.2)
        else:
            ax.plot(range(len(m)), [x if x else float('nan') for x in m], color='#ffb74d', lw=1.6, label='MA30W')
    idx = {w['time']: i for i, w in enumerate(bars)}
    n = len(bars)
    if z and z.get('ok'):
        xs = idx.get(z['base_start'], 0)
        ax.add_patch(Rectangle((xs, z['bottom']), n - xs + 1, z['top'] - z['bottom'], color='#2962ff', alpha=0.28))
        ax.text(xs, z['top'], f" zone {z['bottom']:.2f}-{z['top']:.2f}", color='#82b1ff', fontsize=8.5, va='bottom')
        if z.get('breakout_week') in idx:
            bi = idx[z['breakout_week']]
            ax.annotate('breakout\n(weekly close > R)', (bi, bars[bi]['high']), xytext=(bi - 6, bars[bi]['high'] + (z['atr_w'] * 2)),
                        color='#ffeb3b', fontsize=8.5, arrowprops=dict(arrowstyle='->', color='#ffeb3b'))
        if z.get('pivot_week') in idx:
            pi = idx[z['pivot_week']]
            ax.annotate('R = base top', (pi, bars[pi]['high']), xytext=(pi - 5, bars[pi]['high'] + z['atr_w'] * 1.5),
                        color='#82b1ff', fontsize=8.5, arrowprops=dict(arrowstyle='->', color='#82b1ff'))
        if trade and z.get('trade'):
            tr = z['trade']; x0 = max(0, n - 14)
            hline(ax, tr['tp'], x0, n, '#26a69a', 'TP')
            hline(ax, tr['entry'], x0, n, '#e0e0e0', 'Entry')
            hline(ax, tr['sl'], x0, n, '#ef5350', 'SL')
            META[name] = dict(t=t, asof=asof or d[-1][0], top=z['top'], bottom=z['bottom'], atr=z['atr_w'], score=z['score'], **{k: tr[k] for k in ('entry', 'sl', 'tp', 'rr', 'risk_pct')})
    for (wk, txt, col, where) in marks:
        if wk in idx:
            i = idx[wk]; y = bars[i]['low'] if where == 'low' else bars[i]['high']
            off = -1 if where == 'low' else 1
            ax.annotate(txt, (i, y), xytext=(i - 4, y + off * (bars[i]['high'] - bars[i]['low']) * 1.6), color=col, fontsize=8.5,
                        arrowprops=dict(arrowstyle='->', color=col))
    if extra: extra(ax, bars, idx, z)
    xt(ax, bars); ax.set_xlim(-1, n + 9)
    f.tight_layout(); f.savefig(f'/workspace/course/img/{name}.png', facecolor=BG); plt.close(f)

def below_marks(t, z, start_after, end=None, pct=False):
    d = daily(t)
    if end: d = [r for r in d if r[0] <= end]
    W = E.weekly(d); out = []; prev = False
    for w in W:
        if w['time'] <= start_after: continue
        if w['close'] < z['bottom'] * 0.97:
            out.append((w['time'], 'close >3% below = broken', '#ff8a80', 'low')); break
        if w['close'] < z['bottom']:
            if prev:
                out.append((w['time'], '2nd consecutive close below = broken', '#ff8a80', 'low')); break
            out.append((w['time'], 'close below (warning)', '#ffcc80', 'low')); prev = True
        else:
            prev = False
    return out

# 1 stage analysis
weekly_chart('stage_dal', 'DAL', 'DAL weekly - 30-week MA colored by slope (green = rising, red = falling)', start='2024-09-01', trade=False, ma_color_slope=True)
# 2 zone anatomy (ETF too)
weekly_chart('anatomy_cibr', 'CIBR', 'CIBR (ETF) weekly - expert zone v7 anatomy', start='2025-11-01')
# 3 multiple breakouts
z_old = state('DAL', '2026-02-13')
def dal_extra(ax, bars, idx, z):
    xs = idx.get(z_old['base_start'], 0)
    ax.add_patch(Rectangle((xs, z_old['bottom']), idx.get('2026-03-02', xs+10) - xs, z_old['top'] - z_old['bottom'], color='#ab47bc', alpha=0.35))
    ax.text(xs, z_old['bottom'], f" older zone {z_old['top']:.2f}", color='#ce93d8', fontsize=8.5, va='top')
weekly_chart('multi_dal', 'DAL', 'DAL weekly - a staircase of breakouts: v7 uses the newest valid one', start='2025-09-01', extra=dal_extra)
# 4 KBWB break (2 consecutive closes)
zk = state('KBWB', '2026-09-11')
weekly_chart('break_kbwb', 'KBWB', 'KBWB (ETF) weekly - zone of 2026-09-11, then two consecutive closes below = broken', z=zk, start='2026-01-01',
             marks=below_marks('KBWB', zk, zk['breakout_week']), trade=False)
META['break_kbwb'] = dict(t='KBWB', top=zk['top'], bottom=zk['bottom'])
# 5 SNX >3%
zs = state('SNX', '2026-06-26')
weekly_chart('break_snx', 'SNX', 'SNX weekly - zone of 2026-06-26, then a weekly close >3% below = broken', z=zs, start='2025-12-01',
             marks=below_marks('SNX', zs, zs['breakout_week']), trade=False)
META['break_snx'] = dict(t='SNX', top=zs['top'], bottom=zs['bottom'])
# 6 BHP single close below
zb = state('BHP')
weekly_chart('warn_bhp', 'BHP', 'BHP weekly - one close below the zone = warning only (-10 points), zone still valid', z=zb, start='2025-12-01',
             marks=below_marks('BHP', zb, zb['breakout_week']))
# 7 GL stop options
zg = state('GL'); dg = daily('GL')
rng = st.mean(r[2] - r[3] for r in dg[-22:]); kauf = dg[-1][3] - 2 * rng
def gl_extra(ax, bars, idx, z):
    n = len(bars); x0 = n - 14; e = z['trade']['entry']
    hline(ax, e * 0.92, x0, n, '#ff9800', 'IBD -8%', ls='--', lw=1)
    hline(ax, e - z['atr_w'], x0 - 6, x0 + 4, '#ce93d8', '1 ATR(W)', ls=':', lw=1)
    hline(ax, kauf, x0 - 26, x0 - 16, '#80deea', 'Kaufman 2x22d', ls=':', lw=1)
weekly_chart('sl_gl', 'GL', 'GL weekly - stop options: structure (v7) vs 1 ATR vs IBD 8% vs Kaufman', z=zg, start='2025-12-01', extra=gl_extra)
META['sl_gl'].update(kaufman=round(kauf, 2), ibd8=round(zg['trade']['entry'] * 0.92, 2), atr1=round(zg['trade']['entry'] - zg['atr_w'], 2))
# 8 SWK target hit
zw = state('SWK', '2026-08-28')
def swk_extra(ax, bars, idx, z):
    mm = z['trade'].get('tp_mm')
    if mm: hline(ax, mm, len(bars) - 22, len(bars) - 15, '#a5d6a7', 'measured move', ls='--', lw=1)
weekly_chart('tp_swk', 'SWK', 'SWK weekly - zone/trade of 2026-08-28; TP = post-breakout high, reached later', z=zw, start='2026-01-01', extra=swk_extra)
META['tp_swk'] = dict(t='SWK', asof='2026-08-28', **{k: zw['trade'][k] for k in ('entry', 'sl', 'tp', 'rr', 'risk_pct')}, tp_mm=zw['trade'].get('tp_mm'))
# 9 ASB hammers
za = state('ASB', '2026-09-11')
dA = daily('ASB'); WA = E.weekly(dA)
hm = [(w['time'], 'hammer' , '#ffeb3b', 'low') for w in WA if w['time'] > za['breakout_week'] and E.hammer_shape(w['open'], w['high'], w['low'], w['close']) and E.touches(w['low'], w['close'], za['top'], za['bottom'], za['atr_w'])]
weekly_chart('hammer_asb', 'ASB', 'ASB weekly - hammers on the zone (2026-09-11 state), then the rally', z=za, start='2026-01-01', marks=hm)
META['hammer_asb'] = dict(t='ASB', hammers=[h[0] for h in hm], **{k: za['trade'][k] for k in ('entry', 'sl', 'tp', 'rr')})
# 10 ETF VBK
weekly_chart('etf_vbk', 'VBK', 'VBK (ETF) weekly - a calm ETF retest', start='2025-09-01')
# 11 daily UNF
def daily_chart(name, t, title, sessions=70):
    z = state(t); d = daily(t)[-sessions:]
    bars = [dict(d=r[0], open=r[1], high=r[2], low=r[3], close=r[4]) for r in d]
    f, ax = fig(title); candles(ax, bars)
    n = len(bars)
    ax.add_patch(Rectangle((0, z['bottom']), n + 1, z['top'] - z['bottom'], color='#2962ff', alpha=0.28))
    tr = z['trade']
    hline(ax, tr['entry'], n - 10, n, '#e0e0e0', 'Entry'); hline(ax, tr['sl'], n - 10, n, '#ef5350', 'SL')
    hs = []
    for i, b in enumerate(bars):
        s = E.hammer_shape(b['open'], b['high'], b['low'], b['close'])
        if s and b['low'] <= z['top'] + 0.5 * z['atr_w']:
            ax.annotate('H' if s == 'H' else 'h', (i, b['low']), xytext=(i, b['low'] - (b['high'] - b['low']) * 1.5), color='#ffeb3b', ha='center', fontsize=9,
                        arrowprops=dict(arrowstyle='->', color='#ffeb3b')); hs.append(b['d'])
    xt(ax, bars); ax.set_xlim(-1, n + 9)
    f.tight_layout(); f.savefig(f'/workspace/course/img/{name}.png', facecolor=BG); plt.close(f)
    META[name] = dict(t=t, hammers=hs, top=z['top'], bottom=z['bottom'], **{k: tr[k] for k in ('entry', 'sl', 'tp', 'rr')})
daily_chart('daily_unf', 'UNF', 'UNF daily - zone from the weekly chart, daily hammers (H / h) as the trigger')
daily_chart('daily_gl', 'GL', 'GL daily - looking for the entry on the daily timeframe')
# 12 backtest R distribution
rows = [r for r in json.load(open('/workspace/course/bt_trades.json')) if r['how'] != 'open']
f, axs = plt.subplots(1, 2, figsize=(10, 4.2), dpi=100)
for ax, v, lab in zip(axs, 'LC', ['L: limit at the zone top', 'C: buy after weekly close back above']):
    R = [max(-2, min(r['R'], 8)) for r in rows if r['v'] == v]
    ax.hist(R, bins=40, color='#2962ff'); ax.axvline(st.mean([min(r['R'], 10) for r in rows if r['v'] == v]), color='#ffeb3b', ls='--')
    ax.set_title(f'{lab} (n={len(R)})', color=FG, fontsize=10); ax.grid(color=GRID, lw=0.5); ax.set_xlabel('R multiple')
f.tight_layout(); f.savefig('/workspace/course/img/bt_hist.png', facecolor=BG); plt.close(f)
json.dump(META, open('/workspace/course/img/meta.json', 'w'), indent=1)
print(json.dumps(META, indent=1))
