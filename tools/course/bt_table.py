import json, random, statistics as st
rows=[r for r in json.load(open('bt_trades.json')) if r['how']!='open']
ft=json.load(open('/workspace/cache/fund_types.json'))
fund=lambda t:(ft.get(t) or {}).get('type')=='fund'
random.seed(3)
def S(rs):
    R=[min(r['R'],10) for r in rs]
    if len(R)<20: return None
    bs=sorted(st.mean(random.choices(R,k=len(R))) for _ in range(1000))
    w=[x for x in R if x>0]; l=[x for x in R if x<=0]
    return dict(n=len(R),win=round(100*len(w)/len(R)),aw=round(st.mean(w),2),al=round(st.mean(l),2),E=round(st.mean(R),2),lo=round(bs[25],2),hi=round(bs[975],2))
groups=[('הכול',lambda r:True),('ציון ≥ 50',lambda r:r['score']>=50),('ציון < 35',lambda r:r['score']<35),('R:R ≥ 3',lambda r:r['rr']>=3),('R:R < 3',lambda r:r['rr']<3),
('בדיקה #1–2',lambda r:r['retest'] in('#1','#2')),('בדיקה #3+',lambda r:r['retest'] not in('#1','#2')),('פטיש שבועי על האזור',lambda r:r['ham']),('בלי פטיש',lambda r:not r['ham']),
('הייתה סגירה מתחת לאזור',lambda r:r['below']),('תעודות סל',lambda r:fund(r['t'])),('מניות',lambda r:not fund(r['t'])),('סיכון ≤ 5%',lambda r:r['risk_pct']<=5),('סיכון > 8%',lambda r:r['risk_pct']>8)]
out={v:[(g,S([r for r in rows if r['v']==v and f(r)])) for g,f in groups] for v in 'LC'}
json.dump(out,open('bt_table.json','w'),ensure_ascii=False)
for v in out: 
  for g,s in out[v]: print(v,g,s)
