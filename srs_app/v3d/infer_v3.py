#!/usr/bin/env python
# Vendored verbatim from /workspace/drawing-learn (2026-10-23) for srs_app.bot_drawings + the golden test;
# only the data paths below are env-configurable (SRS_HIST_CACHE, SRS_TV_DRAWINGS). Research outputs are not vendored.
"""
v3 drawing-rule inference: Eyal's reviewed rules (pivot clarity by fractal strength, proximity, merge,
strict broken check, long-wick cap, wick confirmation). ADD-ONLY: reuses infer.py (v1) and infer_v2.py helpers
read-only; writes only v3_* files, report_v3.md, plots_v3/.
Usage:  python infer_v3.py            (CV for v1, v2, hybrid, v3 on current data + report + plots)
"""
import json, sys, itertools, time
from pathlib import Path
from functools import lru_cache
import numpy as np, pandas as pd
import infer as V1
import infer_v2 as V2

OUT = Path(__file__).resolve().parent  # vendored: research outputs are not written in production
D = V1.D                               # same dict object V2 uses
BOT_EXACT = {"AMAT", "CLH", "AMGN"}
ENTRY_BELOW_TOP, RISK_ATR_W, TP_OFF = 0.13, 1.0, -0.09
LOOKBACK = 160
NFOLD = 5

# ---- rule 7: LNG relabel (user now agrees with the model zone); keep his drawn values for a side report
LNG_DRAWN = dict(D["LNG"])
LNG_AGREED = (269.7, 274.2)


def relabel_lng():
    C = V1.ctx("LNG", D["LNG"]["read_date"])
    zb, zt = LNG_AGREED
    e = zt - ENTRY_BELOW_TOP * C["atr"]
    sl = min(e - RISK_ATR_W * C["atr_w"], C["pb_low"] - 0.01)
    D["LNG"] = dict(LNG_DRAWN, zone_bottom=zb, zone_top=zt, entry=e, sl=sl, rr=(LNG_DRAWN["tp"] - e) / (e - sl))


# ------------------------------------------------------------------ v3 candidate generation
def strength(a, i, kind, cap=52):
    """fractal strength: # consecutive weekly candles on each side that are lower (highs) / higher (lows);
    returns (left, right)"""
    n = len(a)
    left = 0
    for j in range(i - 1, max(-1, i - 1 - cap), -1):
        if (kind == "hi" and a[j] < a[i]) or (kind == "lo" and a[j] > a[i]):
            left += 1
        else:
            break
    right = 0
    for j in range(i + 1, min(n, i + 1 + cap)):
        if (kind == "hi" and a[j] < a[i]) or (kind == "lo" and a[j] > a[i]):
            right += 1
        else:
            break
    return left, right


@lru_cache(maxsize=None)
def raw_v3(t, read_date, wick_cap):
    """all pivot levels (both types) with box, clarity and validity stats. Box edges: retest = body top -> wick high,
    support = wick low -> body bottom, with the wick edge capped at wick_cap ATR beyond the body (rule 5)."""
    C = V1.ctx(t, read_date)
    A, n, h, l, c, bt, bb = C["atr"], C["n"], C["h"], C["l"], C["c"], C["bt"], C["bb"]
    i_lo = max(0, n - LOOKBACK)
    out = []
    # ---- retest: pivot highs before the recent high
    for i in range(max(1, i_lo), C["ihi"]):
        sl_, sr_ = strength(h, i, "hi")
        bl_, br_ = strength(bt, i, "hi")
        s = max(min(sl_, sr_), min(bl_, br_))
        if s < 2:
            continue
        js = range(max(0, i - 1), min(n, i + 2))
        j = max(js, key=lambda q: bt[q])
        zb = float(bt[j])
        wick_hi = float(max(h[q] for q in js))
        zt = min(wick_hi, zb + wick_cap * A)
        zt = max(zt, zb + 0.05 * A)
        if C["rh"] - zt < 0.5 * A:
            continue
        bo = np.where(c[i + 1:] > zt)[0]
        if len(bo) == 0:
            continue
        ref = i + 1 + int(bo[0])           # breakout bar: from here on the level must hold as support
        out.append(_stats(C, "retest", i, ref, zb, zt, s, A))
    # ---- back to support: pivot lows price climbed from
    for i in range(max(1, i_lo), n - 1):
        sl_, sr_ = strength(l, i, "lo")
        bl_, br_ = strength(bb, i, "lo")
        s = max(min(sl_, sr_), min(bl_, br_))
        if s < 2:
            continue
        js = range(max(0, i - 1), min(n, i + 2))
        j = min(js, key=lambda q: bb[q])
        zt = float(bb[j])
        wick_lo = float(min(l[q] for q in js))
        zb = max(wick_lo, zt - wick_cap * A)
        zb = min(zb, zt - 0.05 * A)
        if not (h[i + 1:] > zt + A).any():
            continue
        out.append(_stats(C, "support", i, i + 1, zb, zt, s, A))
    return tuple(out)


def _stats(C, kind, i, ref, zb, zt, s, A):
    h, l, c, n = C["h"], C["l"], C["c"], C["n"]
    seg = (l[i + 1:i + 9] if kind == "retest" else h[i + 1:i + 9])
    react = ((h[i] - seg.min()) if kind == "retest" else (seg.max() - l[i])) / A if len(seg) else 0.0
    after_c = c[ref:]
    after_l = l[ref:]
    min_close_rel = float((after_c.min() - zb) / A) if len(after_c) else 9.0
    closes_rel = tuple(np.round((after_c - zb) / A, 4)) if len(after_c) else ()
    lows_rel = tuple(np.round((after_l - zb) / A, 4)) if len(after_l) else ()
    # rule 6: wick confirmations = later candles whose low dips into the box (or slightly under) but close above bottom
    conf = int(((after_l <= zt) & (after_l >= zb - 0.5 * A) & (after_c >= zb)).sum()) if len(after_c) else 0
    return dict(kind=kind, i=i, age=n - 1 - i, zb=zb, zt=zt, strength=s, react=float(react),
                min_close_rel=min_close_rel, closes_rel=closes_rel, lows_rel=lows_rel, conf=conf)


DEFAULT = dict(grace=0, s_min=4, r_min=1.0, btol=0.0, wick_thru=1.0, wick_n=2, wick_cap=0.75, merge_d=0.5,
               max_h=1.2, w_conf=0.25, w_clar=0.0)


def valid_levels(t, read_date, P):
    """grace: the drawing may have been made a few weeks before read_date (we only know when it was READ), so the
    approach/broken checks can ignore the last `grace` weekly bars (tuned in CV; 0 = strict as-of read_date)."""
    C = V1.ctx(t, read_date)
    A = C["atr"]
    g = int(P.get("grace", 0))
    ref_close = C["c"][-1 - g] if g < C["n"] else C["c"][-1]
    res = []
    for z in raw_v3(t, read_date, P["wick_cap"]):
        if z["strength"] < P["s_min"] or z["react"] < P["r_min"]:          # rule 1: clarity
            continue
        if z["zb"] > ref_close:                                              # must be below price (approaching)
            continue
        cr = z["closes_rel"][:len(z["closes_rel"]) - g] if g else z["closes_rel"]
        lr = z["lows_rel"][:len(z["lows_rel"]) - g] if g else z["lows_rel"]
        if len(cr) and min(cr) < -P["btol"]:                                 # rule 4: any close below bottom
            continue
        if sum(1 for x in lr if x < -P["wick_thru"]) >= P["wick_n"]:         # repeated wicks well through
            continue
        res.append(dict(z))
    return res


def merge(levels, P, A):
    """rule 3: union candidate boxes whose price gap <= merge_d ATR (chain), capped at max_h ATR height"""
    if not levels:
        return []
    if P["merge_d"] < 0:                     # no merging at all (single pivot boxes; neighbours de-duplicated)
        out, seen = [], []
        for z in sorted(levels, key=lambda z: -z["zt"]):
            if any(abs(z["zb"] - a) < 1e-9 and abs(z["zt"] - b) < 1e-9 for a, b in seen):
                continue
            seen.append((z["zb"], z["zt"]))
            out.append(dict(z, age=str(z["age"]), n_merged=1))
        return out
    lv = sorted(levels, key=lambda z: -z["zt"])
    groups = [[lv[0]]]
    for z in lv[1:]:
        g = groups[-1]
        gb = min(x["zb"] for x in g)
        gt = max(x["zt"] for x in g)
        gap = gb - z["zt"]
        if gap <= P["merge_d"] * A and max(gt, z["zt"]) - min(gb, z["zb"]) <= P["max_h"] * A:
            g.append(z)
        else:
            groups.append([z])
    out = []
    for g in groups:
        out.append(dict(kind="+".join(sorted(set(x["kind"] for x in g))), zb=min(x["zb"] for x in g),
                        zt=max(x["zt"] for x in g), strength=max(x["strength"] for x in g),
                        react=max(x["react"] for x in g), conf=sum(x["conf"] for x in g),
                        age=",".join(str(x["age"]) for x in g), n_merged=len(g)))
    return out


def predict_v3(t, read_date, P):
    C = V1.ctx(t, read_date)
    A, last = C["atr"], C["c"][-1]
    zones = merge(valid_levels(t, read_date, P), P, A)
    if zones:
        def score(z):  # rule 2: proximity (first met going down) minus confirmation / clarity bonuses
            return (max(0.0, last - z["zt"]) / A - P["w_conf"] * min(z["conf"], 4)
                    - P["w_clar"] * min(z["strength"], 26) / 26 * 4)
        ch = min(zones, key=score)
        zb, zt, kind = ch["zb"], ch["zt"], ch["kind"]
    else:
        zb = C["pb_low"]; zt = zb + 0.33 * A; kind = "fallback"; ch = dict(age="", strength=0, conf=0, n_merged=0)
    e = zt - ENTRY_BELOW_TOP * A
    sl = min(e - RISK_ATR_W * C["atr_w"], C["pb_low"] - 0.01)
    tp = C["bt26"] + TP_OFF * A
    rr = (tp - e) / (e - sl) if e > sl else np.nan
    return dict(p_zone_top=zt, p_zone_bottom=zb, p_entry=e, p_sl=sl, p_tp=tp, p_rr=rr, p_kind=kind,
                p_override=False, p_peak_age_w=ch["age"], p_strength=ch["strength"], p_conf=ch["conf"],
                p_merged=ch["n_merged"], atr=A, atr_w=C["atr_w"])


def predict_v3h(t, read_date, P, w_pb=0.5, w_close=0.6, w_fib=0.3):
    """variant: v3 valid/merged zones, chosen with the v1/hybrid proximity score (pullback low, close, fib .382)"""
    C = V1.ctx(t, read_date)
    A, last = C["atr"], C["c"][-1]
    zones = merge(valid_levels(t, read_date, P), P, A)
    p = predict_v3(t, read_date, P)
    if not zones:
        return p
    lo52 = V1.fib_anchor_low(C, 52)
    fib382 = C["rh"] - 0.382 * (C["rh"] - lo52)
    ch = min(zones, key=lambda z: w_pb * V1.zdist(C["pb_low"], z["zb"] - 0.3 * A, z["zt"] + 0.3 * A) / A
             + w_close * V1.zdist(last, z["zb"], z["zt"]) / A + w_fib * abs((z["zb"] + z["zt"]) / 2 - fib382) / A)
    e = ch["zt"] - ENTRY_BELOW_TOP * A
    sl = min(e - RISK_ATR_W * C["atr_w"], C["pb_low"] - 0.01)
    p.update(p_zone_top=ch["zt"], p_zone_bottom=ch["zb"], p_entry=e, p_sl=sl, p_rr=(p["p_tp"] - e) / (e - sl),
             p_kind=ch["kind"], p_peak_age_w=ch["age"], p_strength=ch["strength"], p_conf=ch["conf"], p_merged=ch["n_merged"])
    return p


def eval_v3(ts, P):
    return pd.DataFrame([V2.score_row(t, predict_v3(t, D[t]["read_date"], P)) for t in ts])


GRID = dict(grace=[0, 1, 2, 3], s_min=[2, 3, 4, 6], r_min=[0.0, 1.0], btol=[0.0, 0.1, 0.25], wick_thru=[0.25, 0.5, 1.0],
            wick_cap=[0.5, 0.75, 99.0], merge_d=[-1.0, 0.0, 0.5], w_conf=[0.0, 0.15, 0.3],
            w_clar=[0.0, 0.5, 0.75, 1.0])


def fit_v3(train):
    best = None
    keys = list(GRID)
    for combo in itertools.product(*[GRID[k] for k in keys]):
        Q = dict(DEFAULT, **dict(zip(keys, combo)))
        ev = eval_v3(train, Q)
        sc = ev.zone_iou.mean() - 0.05 * ev.zone_mid_err_atr.abs().median()
        if best is None or sc > best[0] + 1e-9:
            best = (sc, Q)
    return best[1]


def main():
    relabel_lng()
    found = sorted(t for t, v in D.items() if v.get("found"))
    learn = [t for t in found if t not in BOT_EXACT]
    folds = [[t for i, t in enumerate(learn) if i % NFOLD == k] for k in range(NFOLD)]
    F = pd.DataFrame([V1.features(t, D[t]) for t in found])
    res = {k: [] for k in ["v1", "v2", "hybrid", "v3", "v3_hybrid_scoring"]}
    fold_params = []
    t0 = time.time()
    for k, te in enumerate(folds):
        tr = [t for t in learn if t not in te]
        P1 = V1.fit(tr, F)
        P1.update(entry_mode="below_top", entry_below_top_atr=ENTRY_BELOW_TOP, risk_atr_w=RISK_ATR_W, tp_off_atr=TP_OFF)
        res["v1"].append(V1.evaluate(te, P1).assign(fold=k))
        P2 = V2.fit_v2(tr)
        res["v2"].append(V2.eval_v2(te, P2).assign(fold=k))
        res["hybrid"].append(pd.DataFrame([V2.score_row(t, V2.predict_hybrid(t, D[t]["read_date"], dict(P2, min_react=0.0)))
                                           for t in te]).assign(fold=k))
        P3 = fit_v3(tr)
        fold_params.append({kk: P3[kk] for kk in GRID})
        res["v3"].append(eval_v3(te, P3).assign(fold=k))
        res["v3_hybrid_scoring"].append(pd.DataFrame([V2.score_row(t, predict_v3h(t, D[t]["read_date"], P3)) for t in te]).assign(fold=k))
        print(f"fold {k} done {time.time()-t0:.0f}s  v3 params {fold_params[-1]}", flush=True)
    res = {k: pd.concat(v) for k, v in res.items()}
    P_all = fit_v3(learn)
    ev_all = eval_v3(learn, P_all)
    S = {f"{k} (5-fold CV)": V2.summary(v) for k, v in res.items()}
    S["v3 fit on all (in-sample)"] = V2.summary(ev_all)
    # LNG vs his drawn zone (side report)
    lng = res["v3"][res["v3"].ticker == "LNG"].iloc[0]
    lng_drawn_iou = V1.iou(LNG_DRAWN["zone_bottom"], LNG_DRAWN["zone_top"], lng.p_zone_bottom, lng.p_zone_top)
    json.dump(dict(summary=S, fold_params=fold_params, params_all=P_all, excluded=sorted(BOT_EXACT),
                   lng=dict(agreed=LNG_AGREED, drawn=[LNG_DRAWN["zone_bottom"], LNG_DRAWN["zone_top"]],
                            v3_cv_zone=[lng.p_zone_bottom, lng.p_zone_top], iou_vs_agreed=lng.zone_iou,
                            iou_vs_drawn=lng_drawn_iou)),
              open(OUT / "v3_summary.json", "w"), indent=2, default=str)
    for k, v in res.items():
        v.round(4).to_csv(OUT / f"v3_cv_{k}.csv", index=False)
    ev_all.round(4).to_csv(OUT / "v3_predictions_fit_all.csv", index=False)
    print(pd.DataFrame(S).to_string())
    print(P_all)


if __name__ == "__main__" and len(sys.argv) == 1:
    main()


# ------------------------------------------------------------------ report (python infer_v3.py report)
REVIEWED = ["THC", "ST", "LH", "BAX", "IEX", "FTI", "STLD", "IESC", "CPAY", "CAH", "MOG-A", "LNG",
            "FIX", "URI", "MUSA", "WSM", "CGNX"]


def miss_reason(t, P, p_zb, p_zt):
    v = D[t]
    C = V1.ctx(t, v["read_date"])
    A = C["atr"]
    g = int(P.get("grace", 0))
    ref_close = C["c"][-1 - g]
    best = None
    for z in raw_v3(t, v["read_date"], P["wick_cap"]):
        io = V1.iou(v["zone_bottom"], v["zone_top"], z["zb"], z["zt"])
        if best is None or io > best[0]:
            best = (io, z)
    if best is None or best[0] < 0.3:
        return "no single pivot box matches his zone (edges from other candles / wider cluster)"
    io, z = best
    cr = z["closes_rel"][:len(z["closes_rel"]) - g] if g else z["closes_rel"]
    lr = z["lows_rel"][:len(z["lows_rel"]) - g] if g else z["lows_rel"]
    k = f"his {z['kind']} pivot ({z['age']}w, strength {z['strength']})"
    if z["strength"] < P["s_min"]:
        return f"{k} not clear enough (strength < {P['s_min']})"
    if z["zb"] > ref_close:
        return f"{k} is above the price → rule says price is not approaching it"
    if len(cr) and min(cr) < -P["btol"]:
        return f"{k} counted as broken: a weekly close {min(cr):+.2f} ATR below its bottom"
    nw = sum(1 for x in lr if x < -P["wick_thru"])
    if nw >= P["wick_n"]:
        return f"{k} counted as broken: {nw} wicks > {P['wick_thru']} ATR through it"
    if p_zt > z["zt"]:
        return f"{k} valid but a nearer clear level ({p_zb:.2f}–{p_zt:.2f}) was taken first (proximity)"
    return f"{k} valid but a lower level scored better (confirmation/clarity bonus)"


def report():
    sys.path.append(str(OUT / "_libs"))
    J = json.load(open(OUT / "v3_summary.json"))
    relabel_lng()
    learn = [t for t in sorted(D) if D[t].get("found") and t not in BOT_EXACT]
    cv = {k: pd.read_csv(OUT / f"v3_cv_{k}.csv").set_index("ticker") for k in ["v1", "v2", "hybrid", "v3", "v3_hybrid_scoring"]}
    v3 = cv["v3"]
    rows = []
    for t in learn:
        r = v3.loc[t]
        P = dict(DEFAULT, **J["fold_params"][int(r.fold)])
        why = miss_reason(t, P, r.p_zone_bottom, r.p_zone_top) if r.zone_iou < 0.3 else ""
        rows.append(dict(ticker=t, reviewed=t in REVIEWED, v3_type=r.p_kind, v3_pivot_age_w=r.p_peak_age_w,
                         v3_strength=r.p_strength, zone_bottom=r.zone_bottom, zone_top=r.zone_top,
                         v3_zone_bottom=round(r.p_zone_bottom, 2), v3_zone_top=round(r.p_zone_top, 2),
                         v3_iou=round(r.zone_iou, 3), v3_zone_mid_err_atr=round(r.zone_mid_err_atr, 2),
                         v3_entry_err_atr=round(r.entry_err_atr, 2), v3_sl_err_atr=round(r.sl_err_atr, 2),
                         v3_tp_err_atr=round(r.tp_err_atr, 2), rr=round(r.rr, 2), v3_rr=round(r.p_rr, 2),
                         hybrid_iou=round(cv["hybrid"].loc[t].zone_iou, 3), v2_iou=round(cv["v2"].loc[t].zone_iou, 3),
                         v1_iou=round(cv["v1"].loc[t].zone_iou, 3), fold=int(r.fold), v3_miss_reason=why))
    T = pd.DataFrame(rows)
    T.to_csv(OUT / "v3_per_ticker_table.csv", index=False)
    S = pd.DataFrame(J["summary"]).reset_index().rename(columns={"index": "metric"})

    def md(df):
        out = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
        for _, r in df.iterrows():
            out.append("| " + " | ".join(f"{x:.2f}" if isinstance(x, float) else str(x) for x in r.values) + " |")
        return "\n".join(out)
    rv = T[T.reviewed].set_index("ticker").loc[REVIEWED].reset_index()
    rv_tab = pd.DataFrame({"ticker": rv.ticker, "his zone": [f"{a:.2f}–{b:.2f}" for a, b in zip(rv.zone_bottom, rv.zone_top)],
                           "v3 zone (CV)": [f"{a:.2f}–{b:.2f}" for a, b in zip(rv.v3_zone_bottom, rv.v3_zone_top)],
                           "v3 type": rv.v3_type, "v3 IoU": rv.v3_iou, "match (IoU≥0.3)": np.where(rv.v3_iou >= 0.3, "yes", "no"),
                           "v2 IoU": rv.v2_iou, "hybrid IoU": rv.hybrid_iou, "why (if miss)": rv.v3_miss_reason})
    new_vs_v2 = T[(T.v3_iou < 0.3) & (T.v2_iou >= 0.3)]
    new_vs_h = T[(T.v3_iou < 0.3) & (T.hybrid_iou >= 0.3)]
    gained_vs_h = T[(T.v3_iou >= 0.3) & (T.hybrid_iou < 0.3)]
    misses = T[T.v3_iou < 0.3][["ticker", "v3_iou", "v3_miss_reason"]]
    full = T[["ticker", "v3_type", "zone_bottom", "zone_top", "v3_zone_bottom", "v3_zone_top", "v3_iou", "hybrid_iou", "v2_iou",
              "v3_zone_mid_err_atr"]].sort_values("v3_iou", ascending=False)
    L = J["lng"]
    PA = J["params_all"]
    rng = lambda k: "/".join(str(fp[k]) for fp in J["fold_params"])
    txt = f"""# v3 drawing rules (Eyal's review of the misses) — results

Script `infer_v3.py` (reuses v1/v2 helpers read-only). n = {len(learn)} drawings (excluded bot-seeded: {', '.join(J['excluded'])}).
All five methods were re-run **here on the same, current data and the same 5 folds** (several drawings were re-read since v2,
and LNG is relabelled), so v1/v2/hybrid numbers differ slightly from the v2 report. Entry/SL/TP = v1 formulas for all methods.
**LNG** is scored against the agreed zone {L['agreed'][0]}–{L['agreed'][1]} (his drawn {L['drawn'][0]}–{L['drawn'][1]}): v3 CV zone
{L['v3_cv_zone'][0]:.2f}–{L['v3_cv_zone'][1]:.2f}, IoU vs agreed {L['iou_vs_agreed']:.2f}, vs drawn {L['iou_vs_drawn']:.2f}.

## Metrics (5-fold CV unless noted)

{md(S)}

Fold-tuned v3 parameters: {json.dumps(J['fold_params'])}

## Final v3 rule text (plain words; values = all-data fit, fold range in brackets)
1. Weekly candles. Candidate levels = **pivot highs** (retest) and **pivot lows** (back to support) of the last ~3 years.
2. **Clarity = fractal strength**: count the lower candles (high) / higher candles (low) on each side; strength = the smaller count.
   Clear if strength ≥ **{PA['s_min']}** [{rng('s_min')}]. Minimum move away after the pivot: {PA['r_min']} ATR [{rng('r_min')}].
3. **Box**: retest = high candle's body top → wick high; support = wick low → low candle's body bottom; a **wick longer than {PA['wick_cap']} ATR**
   [{rng('wick_cap')}] past the body is capped there (long wicks never set the edge).
4. **Valid**: a high must have been closed above later; a low must have been rallied from (>1 ATR); the box must be below price. **Broken** (skip to the next
   level down) if any weekly close since the breakout (highs) / since the pivot (lows) is below the box bottom by more than **{PA['btol']} ATR** [{rng('btol')}],
   or **{PA['wick_n']}+ wicks go more than {PA['wick_thru']} ATR through it** [{rng('wick_thru')}]. These checks ignore the **last {PA['grace']} weekly bars**
   [{rng('grace')}], because we only know when a drawing was *read*, not when it was drawn (several of his zones were closed through only in the last 1–2 weeks: ADP, GL).
5. **Choose**: score = distance from price down to the box top (ATR) − {PA['w_conf']} [{rng('w_conf')}] × wick confirmations (later wicks into the box that closed above it, max 4)
   − {PA['w_clar']} [{rng('w_clar')}] × clarity (strength/26 × 4, capped) → lowest score wins. With clarity weight > 0 a much clearer level a bit further down can beat an unclear nearer one (FTI/STLD style).
6. **Merge close pivots** (gap ≤ 0 / 0.5 ATR) is implemented but CV chose **{PA['merge_d']}** [{rng('merge_d')}] (−1 = never merge; 0 = merge only overlapping boxes).
7. Entry = box top − 0.13 ATR; SL = min(entry − 1.0 weekly ATR, below the pullback low); TP = highest weekly body top of 26w − 0.09 ATR (unchanged).

## Reviewed tickers

{md(rv_tab)}

## New misses introduced by v3
- vs v2 (v2 IoU ≥ 0.3, v3 < 0.3): {', '.join(f"{r.ticker} ({r.v2_iou:.2f}→{r.v3_iou:.2f})" for r in new_vs_v2.itertuples()) or 'none'}
- vs hybrid (hybrid ≥ 0.3, v3 < 0.3): {', '.join(f"{r.ticker} ({r.hybrid_iou:.2f}→{r.v3_iou:.2f})" for r in new_vs_h.itertuples()) or 'none'}
- gained vs hybrid (v3 ≥ 0.3, hybrid < 0.3): {', '.join(f"{r.ticker} ({r.hybrid_iou:.2f}→{r.v3_iou:.2f})" for r in gained_vs_h.itertuples()) or 'none'}

## All v3 misses (IoU < 0.3) with the likely reason

{md(misses)}

## All tickers

{md(full)}

## Plots (`plots_v3/`, blue = Eyal, orange = v3 CV prediction)
Good: MOG-A, FTI, THC. Bad: CPAY, ST.

## Caveats
- n = 54, ~11 per fold: ±3 tickers is noise. Compare v3 to the hybrid with that in mind (see metrics table).
- Drawing dates are unknown (only read dates); the 2-bar grace is a proxy for that and the biggest single "rule" gain came from it.
- Rule 4 (strict broken) and some of his zones conflict: e.g. VRTX/ITW zones were closed through by 0.2–0.6 ATR after the breakout, yet he uses them.
- Merge (rule 3) is implemented (`merge_d`) but CV did not choose it; CPAY/CAH would need a merge that does not also widen IEX-type zones.
- Fold-to-fold parameter differences (clarity weight, grace) mean some reviewed tickers flip between folds; per-ticker results are from the fold in which the ticker was held out.
- Dividend-adjusted yfinance prices vs TradingView (~0.1–0.4 %); recent high = max High of 26 weeks.
"""
    open(OUT / "report_v3.md", "w").write(txt)
    (OUT / "plots_v3").mkdir(exist_ok=True)
    for t in ["MOG-A", "FTI", "THC", "CPAY", "ST", "IEX", "LNG", "CAH"]:
        r = v3.loc[t].copy()
        r["ticker"] = t
        V1.plot(t, r, OUT / "plots_v3" / f"{t}.png")
    print(rv_tab.to_string()); print(misses.to_string())
    print("new vs v2", new_vs_v2.ticker.tolist(), "new vs hyb", new_vs_h.ticker.tolist(), "gained vs hyb", gained_vs_h.ticker.tolist())


if __name__ == "__main__" and len(sys.argv) > 1 and sys.argv[1] == "report":
    report()
