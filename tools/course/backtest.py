"""Exploratory, in-sample backtest of the expert-v7 trade on the app's candle universe (course module 10 only)."""
import json, sys, glob, os
sys.path.insert(0, '/workspace/publish-stock-retest-scanner')
from srs_app import expert_zone as E
from multiprocessing import Pool
D = '/workspace/publish-stock-retest-scanner/app/data/candles/'

def sim(days, k0, fill, sl, tp, risk=None):
    """daily rows from index k0 (fill day included, fill at given price); returns (exit, R, days_held, outcome)"""
    risk = risk or (fill - sl)
    if risk <= 0: return None
    for j in range(k0, len(days)):
        d, o, h, l, c = days[j][:5]
        if j > k0:
            if o <= sl: return (o, (o-fill)/risk, j-k0, 'sl_gap')
            if o >= tp: return (o, (o-fill)/risk, j-k0, 'tp_gap')
        if l <= sl: return (sl, -1.0, j-k0, 'sl')
        if h >= tp: return (tp, (tp-fill)/risk, j-k0, 'tp')
    c = days[-1][4]
    return (c, (c-fill)/risk, len(days)-k0, 'open')

def run(path):
    t = os.path.basename(path)[:-5]
    try: d = json.load(open(path))['d']
    except Exception: return []
    W = E.weekly(d)
    idx = {r[0]: i for i, r in enumerate(d)}
    out = []; busy_until = {'L': '', 'C': ''}
    for i in range(40, len(W) - 1):
        last = W[i]['days'][-1][0]
        cut = d[:idx[last] + 1]
        z = E.find(cut, asof=last)
        if not z.get('ok'): continue
        tr = z['trade']; e, sl, tp = tr['entry'], tr['sl'], tr['tp']
        if tp <= e or sl >= e: continue
        nxt = W[i + 1]['days']
        meta = dict(t=t, week=W[i]['time'], score=z['score'], rr=tr['rr'], risk_pct=tr['risk_pct'],
                    dist=z['dist_atr'], retest=next((f['val'] for f in z['factors'] if f['k']=='retest'), ''),
                    ham=len(z.get('hammers', [])) > 0, below=bool(z.get('closes_below_k')))
        # L: resting limit at the entry during the next week
        if nxt[0][0] > busy_until['L']:
            for r in nxt:
                if r[3] <= e:
                    fill = min(r[1], e); k0 = idx[r[0]]
                    if fill <= sl: break
                    res = sim(d, k0, fill, sl, tp, risk=e - sl)
                    if res:
                        out.append(dict(meta, v='L', date=r[0], fill=fill, sl=sl, tp=tp, R=res[1], held=res[2], how=res[3]))
                        busy_until['L'] = d[min(len(d)-1, k0 + res[2])][0]
                    break
        # C: confirmation = completed week touched the zone top and closed above it -> buy next open
        w = W[i]
        if w['low'] <= e and w['close'] > e and nxt[0][0] > busy_until['C']:
            k0 = idx[nxt[0][0]]; fill = nxt[0][1]
            if fill > sl:
                res = sim(d, k0, fill, sl, tp)
                if res:
                    out.append(dict(meta, v='C', date=nxt[0][0], fill=fill, sl=sl, tp=tp, R=res[1], held=res[2], how=res[3]))
                    busy_until['C'] = d[min(len(d)-1, k0 + res[2])][0]
    return out

if __name__ == '__main__':
    files = sorted(glob.glob(D + '*.json'))
    with Pool(8) as p: rows = [x for r in p.map(run, files) for x in r]
    json.dump(rows, open('/workspace/course/bt_trades.json', 'w'))
    print(len(rows))
