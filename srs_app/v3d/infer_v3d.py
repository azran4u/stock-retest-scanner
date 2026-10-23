#!/usr/bin/env python
# Vendored verbatim from /workspace/drawing-learn (2026-10-23) for srs_app.bot_drawings + the golden test;
# only the data paths below are env-configurable (SRS_HIST_CACHE, SRS_TV_DRAWINGS). Research outputs are not vendored.
"""
v3d: base = v3b levels + hybrid scoring (current best), with
 (1) Eyal's refined SL: a level price 'should not get to'. Relevant candles = the current pullback (since the recent
     26w high) + candles of the last `L` weeks whose LOW sits near / just under the zone (zb - X*ATR <= low <= zt).
     Candidate SL = just below (-0.1%) the lowest relevant low below entry. Accepted only if risk (entry - SL) is within
     [lo, hi] x weekly Wilder ATR ('lowest' mode: only the lowest low is tried; 'fit' mode: the lowest low that fits the
     band). Otherwise / when unclear: SL = entry - 1.0 weekly ATR (DEFAULT).
     Used both as predicted SL and in the v3b broken check (weekly close below the zone's own SL -> broken; wicks below
     it count if wick_n is set). SL params are fitted on HIS zones+entries of the training folds (pure SL-placement fit).
 (2) MOG-A-motivated zone rules (tuned in CV, can be switched off):
     body_piv: 1 = support pivots must be pivots of candle BODIES (a low defined only by a long wick is no candidate),
               2 = same for retest pivots (body tops); 0 = off (v3b).
     long_wick: reject a support pivot whose own lower wick is > k ATR (body far above the low); 99 = off.
     close_n: a level is invalid if >= close_n weekly closes (since breakout/pivot, before grace) are below its bottom.
Variants: main = new SL + zone rules (hybrid scoring); 'sl only' = new SL, zone rules off.
ADD-ONLY: imports v1/v2/v3 modules read-only; writes v3d_* files, report_v3d.md, plots_v3d/.
"""
import json, sys, itertools, time
from pathlib import Path
from functools import lru_cache
import numpy as np, pandas as pd
import infer as V1
import infer_v2 as V2
import infer_v3 as V3

OUT = Path(__file__).resolve().parent  # vendored: research outputs are not written in production
D = V3.D
FIXED = dict(s_min=3, r_min=0.0, wick_cap=0.5, max_h=1.2, btol=0.0, wick_thru=0.0, merge_d=-1.0, w_conf=0.0, w_clar=0.0)
SL_GRID = dict(L=[0, 13, 26, 52], X=[0.25, 0.5, 0.75, 1.0], lo=[0.6, 0.7, 0.8, 0.9], hi=[1.1, 1.2, 1.3, 1.5],
               mode=["lowest", "fit"])
ZGRID = dict(grace=[0, 1, 2, 3], wick_n=[1, 2, 3, 99], body_piv=[0, 1, 2], long_wick=[99, 0.5, 0.75], close_n=[99, 2, 3])
SL_PAD = 0.001
SLK = list(SL_GRID)


@lru_cache(maxsize=None)
def sl_d(t, read_date, zb, zt, e, L, X, lo, hi, mode):
    C = V1.ctx(t, read_date)
    A, Aw, n, l = C["atr"], C["atr_w"], C["n"], C["l"]
    js = set(range(C["ihi"] + 1, n))                                       # current pullback candles
    if L:
        js |= {j for j in range(max(0, n - L), n) if zb - X * A <= l[j] <= zt}
    cands = sorted(l[j] * (1 - SL_PAD) for j in js if l[j] * (1 - SL_PAD) < e)
    band = [x for x in cands if lo * Aw <= e - x <= hi * Aw]
    if cands:
        if mode == "lowest" and band and band[0] == cands[0]:
            return float(cands[0]), "wick_low"
        if mode == "fit" and band:
            return float(band[0]), "wick_low"
    return float(e - 1.0 * Aw), "default_1atr"


def slp(P):
    return tuple(P[k] for k in SLK)


# ---------------- SL rule on HIS zones / entries
def sl_his(learn, S):
    out = []
    for t in learn:
        v = D[t]; A = V1.ctx(t, v["read_date"])["atr"]
        sl, src = sl_d(t, v["read_date"], v["zone_bottom"], v["zone_top"], v["entry"], *S)
        out.append(dict(ticker=t, sl=v["sl"], p_sl=sl, src=src, err_atr=(sl - v["sl"]) / A))
    return pd.DataFrame(out)


def sl_score(df):
    a = df.err_atr.abs()
    return (a <= 0.15).mean() - 0.5 * a.median()


def fit_sl(train):
    best = None
    for combo in itertools.product(*SL_GRID.values()):
        sc = sl_score(sl_his(train, combo))
        if best is None or sc > best[0] + 1e-9:
            best = (sc, combo)
    return best[1]


def v1_his(learn):
    rows = []
    for t in learn:
        v = D[t]; C = V1.ctx(t, v["read_date"])
        rows.append(dict(ticker=t, err_atr=(v["entry"] - C["atr_w"] - v["sl"]) / C["atr"]))
    return pd.DataFrame(rows)


# ---------------- levels
def zone_ok(z, C, P):
    i = z["i"]
    if P["body_piv"] >= 1 and z["kind"] == "support" and min(V3.strength(C["bb"], i, "lo")) < P["s_min"]:
        return False
    if P["body_piv"] >= 2 and z["kind"] == "retest" and min(V3.strength(C["bt"], i, "hi")) < P["s_min"]:
        return False
    if z["kind"] == "support" and (C["bb"][i] - C["l"][i]) / C["atr"] > P["long_wick"]:
        return False
    return True


def valid_levels_d(t, read_date, P):
    C = V1.ctx(t, read_date)
    A = C["atr"]
    g = int(P["grace"])
    ref_close = C["c"][-1 - g]
    res = []
    for z in V3.raw_v3(t, read_date, P["wick_cap"]):
        if z["strength"] < P["s_min"] or z["zb"] > ref_close or not zone_ok(z, C, P):
            continue
        e = z["zt"] - V3.ENTRY_BELOW_TOP * A
        sl, src = sl_d(t, read_date, z["zb"], z["zt"], e, *slp(P))
        sl_rel = (sl - z["zb"]) / A
        cr = z["closes_rel"][:len(z["closes_rel"]) - g] if g else z["closes_rel"]
        lr = z["lows_rel"][:len(z["lows_rel"]) - g] if g else z["lows_rel"]
        if len(cr) and min(cr) < sl_rel:
            continue
        if sum(1 for x in lr if x < sl_rel) >= P["wick_n"]:
            continue
        if sum(1 for x in cr if x < 0) >= P["close_n"]:
            continue
        res.append(dict(z, sl=sl, sl_src=src))
    return res


def predict(t, read_date, P):
    C = V1.ctx(t, read_date)
    A, last = C["atr"], C["c"][-1]
    zones = valid_levels_d(t, read_date, P)
    tp = C["bt26"] + V3.TP_OFF * A
    if not zones:
        zb = C["pb_low"]; zt = zb + 0.33 * A; e = zt - V3.ENTRY_BELOW_TOP * A
        sl, src = sl_d(t, read_date, zb, zt, e, *slp(P)); kind, age = "fallback", ""
    else:
        lo52 = V1.fib_anchor_low(C, 52)
        fib382 = C["rh"] - 0.382 * (C["rh"] - lo52)
        ch = min(zones, key=lambda z: 0.5 * V1.zdist(C["pb_low"], z["zb"] - 0.3 * A, z["zt"] + 0.3 * A) / A
                 + 0.6 * V1.zdist(last, z["zb"], z["zt"]) / A + 0.3 * abs((z["zb"] + z["zt"]) / 2 - fib382) / A)
        zb, zt, sl, src, kind, age = ch["zb"], ch["zt"], ch["sl"], ch["sl_src"], ch["kind"], ch["age"]
        e = zt - V3.ENTRY_BELOW_TOP * A
    rr = (tp - e) / (e - sl) if e > sl else np.nan
    return dict(p_zone_top=zt, p_zone_bottom=zb, p_entry=e, p_sl=sl, p_tp=tp, p_rr=rr, p_kind=kind,
                p_override=False, p_peak_age_w=age, p_sl_src=src, atr=A, atr_w=C["atr_w"])


def ev(ts, P):
    return pd.DataFrame([V2.score_row(t, predict(t, D[t]["read_date"], P)) for t in ts])


def fit(train, S, zrules=True):
    grid = dict(ZGRID)
    if not zrules:
        grid.update(body_piv=[0], long_wick=[99], close_n=[99])
    best = None
    for combo in itertools.product(*grid.values()):
        Q = dict(V3.DEFAULT, **FIXED, **dict(zip(SLK, S)), **dict(zip(grid, combo)))
        e = ev(train, Q)
        sc = e.zone_iou.mean() - 0.05 * e.zone_mid_err_atr.abs().median() - 0.05 * e.sl_err_atr.abs().median()
        if best is None or sc > best[0] + 1e-9:
            best = (sc, Q)
    return best[1]


def main():
    V3.relabel_lng()
    learn = [t for t in sorted(D) if D[t].get("found") and t not in V3.BOT_EXACT]
    folds = [[t for i, t in enumerate(learn) if i % V3.NFOLD == k] for k in range(V3.NFOLD)]
    t0 = time.time()
    # ---- (1) SL on his zones: in-sample best + 5-fold CV
    rows = []
    for combo in itertools.product(*SL_GRID.values()):
        d = sl_his(learn, combo); a = d.err_atr.abs()
        rows.append(dict(zip(SLK, combo), med_abs_err_atr=round(a.median(), 3), within_0_15=int((a <= 0.15).sum()),
                         within_0_30=int((a <= 0.30).sum()), n_wick_low=int((d.src == "wick_low").sum())))
    grid_his = pd.DataFrame(rows).sort_values(["within_0_15", "med_abs_err_atr"], ascending=[False, True])
    grid_his.to_csv(OUT / "v3d_sl_grid_on_his_zones.csv", index=False)
    v1h = v1_his(learn); v1a = v1h.err_atr.abs()
    sl_cv, sl_fold = [], []
    for k, te in enumerate(folds):
        S = fit_sl([t for t in learn if t not in te]); sl_fold.append(S)
        sl_cv.append(sl_his(te, S).assign(fold=k))
    sl_cv = pd.concat(sl_cv)
    sl_cv.merge(v1h.rename(columns={"err_atr": "v1_err_atr"}), on="ticker").round(4).to_csv(OUT / "v3d_sl_on_his_zones_cv.csv", index=False)
    a = sl_cv.err_atr.abs()
    his = dict(v1=dict(med=round(v1a.median(), 3), w15=int((v1a <= 0.15).sum()), w30=int((v1a <= 0.30).sum())),
               v3d_cv=dict(med=round(a.median(), 3), w15=int((a <= 0.15).sum()), w30=int((a <= 0.30).sum()),
                           n_wick_low=int((sl_cv.src == "wick_low").sum())),
               v3d_best_in_sample=grid_his.iloc[0].to_dict(), fold_sl_params=sl_fold)
    print("SL on his zones", his, f"{time.time()-t0:.0f}s", flush=True)

    # ---- (2) pipeline CV
    res = {"v3d_main": [], "v3d_sl_only": []}; fps = {k: [] for k in res}
    for k, te in enumerate(folds):
        tr = [t for t in learn if t not in te]
        for name, zr in (("v3d_main", True), ("v3d_sl_only", False)):
            P = fit(tr, sl_fold[k], zr)
            fps[name].append({kk: P[kk] for kk in list(ZGRID) + SLK})
            res[name].append(ev(te, P).assign(fold=k))
        print("fold", k, f"{time.time()-t0:.0f}s", fps["v3d_main"][-1], fps["v3d_sl_only"][-1], flush=True)
    res = {k: pd.concat(v) for k, v in res.items()}
    for k, v in res.items():
        v.round(4).to_csv(OUT / f"v3d_cv_{k}.csv", index=False)
    base = {"hybrid": pd.read_csv(OUT / "v3_cv_hybrid.csv"), "v3b_hybrid": pd.read_csv(OUT / "v3b_cv_v3b_hybrid_scoring.csv")}
    named = [("hybrid (CV)", base["hybrid"]), ("v3b + hybrid scoring (CV)", base["v3b_hybrid"]),
             ("v3d main: new SL + zone rules (CV)", res["v3d_main"]), ("v3d new SL only (CV)", res["v3d_sl_only"])]
    S = {}
    for name, df in named:
        S[name] = V2.summary(df)
        S[name]["SL within 0.15 ATR"] = f"{int((df.sl_err_atr.abs() <= 0.15).sum())}/{len(df)}"
        S[name]["SL within 0.30 ATR"] = f"{int((df.sl_err_atr.abs() <= 0.30).sum())}/{len(df)}"
    json.dump(dict(summary=S, sl_on_his_zones=his, fold_params=fps, fixed=FIXED), open(OUT / "v3d_summary.json", "w"),
              indent=2, default=str)

    m = res["v3d_main"].set_index("ticker"); s = res["v3d_sl_only"].set_index("ticker")
    h = base["hybrid"].set_index("ticker"); bh = base["v3b_hybrid"].set_index("ticker")
    T = pd.DataFrame({"reviewed": [t in V3.REVIEWED for t in m.index], "zone_bottom": m.zone_bottom, "zone_top": m.zone_top,
                      "main_zb": m.p_zone_bottom.round(2), "main_zt": m.p_zone_top.round(2), "main_kind": m.p_kind,
                      "main_iou": m.zone_iou.round(3), "main_mid_err_atr": m.zone_mid_err_atr.round(2),
                      "sl": m.sl, "main_sl": m.p_sl.round(2), "main_sl_src": m.p_sl_src, "main_sl_err_atr": m.sl_err_atr.round(2),
                      "rr": m.rr.round(2), "main_rr": m.p_rr.round(2),
                      "slonly_iou": s.zone_iou.round(3), "v3b_hyb_iou": bh.zone_iou.round(3),
                      "v3b_hyb_sl_err_atr": bh.sl_err_atr.round(2), "hybrid_iou": h.zone_iou.round(3), "fold": m.fold})
    T.index.name = "ticker"
    T.to_csv(OUT / "v3d_per_ticker_table.csv")

    def md(df):
        df = df.reset_index()
        o = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
        for _, r in df.iterrows():
            o.append("| " + " | ".join(f"{x:.2f}" if isinstance(x, float) else str(x) for x in r.values) + " |")
        return "\n".join(o)
    rv = T.loc[V3.REVIEWED]
    miss = T[T.main_iou < 0.3]
    new_vs_bh = T[(T.main_iou < 0.3) & (T.v3b_hyb_iou >= 0.3)].index.tolist()
    gain_vs_bh = T[(T.main_iou >= 0.3) & (T.v3b_hyb_iou < 0.3)].index.tolist()
    new_vs_h = T[(T.main_iou < 0.3) & (T.hybrid_iou >= 0.3)].index.tolist()
    gain_vs_h = T[(T.main_iou >= 0.3) & (T.hybrid_iou < 0.3)].index.tolist()
    cols = ["zone_bottom", "zone_top", "main_zb", "main_zt", "main_kind", "main_iou", "sl", "main_sl", "main_sl_src",
            "main_sl_err_atr", "slonly_iou", "v3b_hyb_iou", "hybrid_iou"]
    txt = f"""# v3d — SL at the level price 'should not get to' (nearby wick lows, ~1 ATR band, default entry − 1 ATR) + long-wick zone rules

`infer_v3d.py`. Base v3b levels + hybrid scoring. n = 54 (AMAT, CLH, AMGN excluded), same 5 folds, LNG vs agreed 269.7–274.2.
Merge off, clarity ≥ 3, wick cap 0.5 ATR. SL params fitted on HIS zones/entries of training folds; zone params tuned in CV
(objective mean IoU − 0.05·med|mid err| − 0.05·med|SL err|). Baselines: `v3_cv_hybrid.csv`, `v3b_cv_v3b_hybrid_scoring.csv`.

## SL rule on HIS zones + entries
- v1 (entry − 1.0 ATR): median |err| {his['v1']['med']} ATR, within 0.15: {his['v1']['w15']}/54, within 0.30: {his['v1']['w30']}/54
- v3d (5-fold CV): median {his['v3d_cv']['med']} ATR, within 0.15: {his['v3d_cv']['w15']}/54, within 0.30: {his['v3d_cv']['w30']}/54 (wick-low SL used {his['v3d_cv']['n_wick_low']}/54)
- v3d best in-sample: {his['v3d_best_in_sample']}
- fold SL params (L, X, lo, hi, mode): {sl_fold}

## Metrics (5-fold CV)

{md(pd.DataFrame(S))}

Fold params: {json.dumps(fps)}

## 17 reviewed: main {int((rv.main_iou >= 0.3).sum())}/17; SL-only {int((rv.slonly_iou >= 0.3).sum())}/17; v3b+hybrid {int((rv.v3b_hyb_iou >= 0.3).sum())}/17; hybrid {int((rv.hybrid_iou >= 0.3).sum())}/17

{md(rv[cols])}

## MOG-A: main {T.loc['MOG-A', 'main_zb']}–{T.loc['MOG-A', 'main_zt']} (IoU {T.loc['MOG-A', 'main_iou']}), his 344.29–353.61

## Changes (main)
- vs v3b+hybrid: new misses {', '.join(new_vs_bh) or 'none'}; gained {', '.join(gain_vs_bh) or 'none'}
- vs hybrid: new misses {', '.join(new_vs_h) or 'none'}; gained {', '.join(gain_vs_h) or 'none'}
- remaining disagreements (IoU < 0.3), {len(miss)}/54: {', '.join(miss.index)}

## All tickers

{md(T[cols].sort_values('main_iou', ascending=False))}
"""
    open(OUT / "report_v3d.md", "w").write(txt)
    sys.path.append(str(OUT / "_libs"))
    (OUT / "plots_v3d").mkdir(exist_ok=True)
    for t in ["MOG-A", "CAH", "VRTX", "BPOP", "ST", "IEX"]:
        V1.plot(t, m.loc[t].copy(), OUT / "plots_v3d" / f"{t}.png")
    print(pd.DataFrame(S).to_string())
    print(rv[cols].to_string())
    print("MOG-A", T.loc["MOG-A", cols].to_dict())
    print("new vs bh", new_vs_bh, "gain", gain_vs_bh, "new vs h", new_vs_h, "gain", gain_vs_h, "misses", list(miss.index))


if __name__ == "__main__":
    main()
