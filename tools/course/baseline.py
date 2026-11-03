import json, random, statistics as st, sys
sys.path.insert(0,'.')
from backtest import sim, D
rows=json.load(open('bt_trades.json'))
random.seed(7)
cache={}
def days(t):
    if t not in cache: cache[t]=json.load(open(D+t+'.json'))['d']
    return cache[t]
def stats(R):
    bs=sorted(st.mean(random.choices(R,k=len(R))) for _ in range(1000))
    return f"n={len(R)} win={sum(x>0 for x in R)/len(R):.0%} E={st.mean(R):+.2f}R median={st.median(R):+.2f} CI95=[{bs[25]:+.2f},{bs[975]:+.2f}]"
for v in 'LC':
    rs=[r for r in rows if r['v']==v and r['how']!='open']
    R=[r['R'] for r in rs]; Rc=[min(x,10) for x in R]
    print(v,'raw   ',stats(R)); print(v,'cap10 ',stats(Rc))
    print(v,'top R', sorted(R)[-5:])
    base=[]
    for r in rs:
        d=days(r['t']); k=random.randrange(150, len(d)-20)
        fill=d[k][1]; risk=(r['fill']-r['sl'])/r['fill']; rr=(r['tp']-r['fill'])/(r['fill']-r['sl'])
        sl=fill*(1-risk); tp=fill+rr*(fill-sl)
        res=sim(d,k,fill,sl,tp)
        if res and res[3]!='open': base.append(min(res[1],10))
    print(v,'random-entry baseline same tickers & same SL/TP geometry (cap10):',stats(base))
    by={}
    for r in rs: by.setdefault(r['date'][:4],[]).append(min(r['R'],10))
    print(v,'by year', {y:(len(x),round(st.mean(x),2)) for y,x in sorted(by.items())})
