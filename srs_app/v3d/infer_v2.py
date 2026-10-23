#!/usr/bin/env python
# Vendored verbatim from /workspace/drawing-learn (2026-10-23) for srs_app.bot_drawings + the golden test;
# only the data paths below are env-configurable (SRS_HIST_CACHE, SRS_TV_DRAWINGS). Research outputs are not vendored.
"""
v2 zone rules from Eyal's own explanation (RETEST vs BACK-TO-SUPPORT), evaluated vs v1.
ADD-ONLY: reads tv_drawings.json / hist_cache.pkl, reuses helpers from infer.py (v1) and stock_screen.py,
writes only to /workspace/drawing-learn/ (v2_* files, plots_v2/).
"""
import json, sys, itertools
from pathlib import Path
import numpy as np, pandas as pd
import infer as V1                      # v1 helpers (ctx, pivots, iou, zdist, fit/evaluate, plot)

OUT = Path(__file__).resolve().parent  # vendored: research outputs are not written in production
D = V1.D
BOT_EXACT = {"AMAT", "CLH", "AMGN"}     # AMGN: new exact bot match (zone+entry+SL+TP) found in provenance_v2.csv
# v1 trade formulas, fixed (same for v1 and v2 so only the zone logic differs)
ENTRY_BELOW_TOP, RISK_ATR_W, TP_OFF = 0.13, 1.0, -0.09
LOOKBACK = 160

DEFAULT = dict(k=3, tol=0.15, w_react=0.5, thr=2.0, react_win=8, min_touch=3, break_tol=0.15, min_react=0.0,
               touch_back=26, use_touch=1, left=0)
from functools import lru_cache


def touches(C, x, tol_abs, i_lo):
    """# weekly candles from i_lo..now whose wick tip or body edge is within tol of level x"""
    h, l, bt, bb = C["h"][i_lo:], C["l"][i_lo:], C["bt"][i_lo:], C["bb"][i_lo:]
    m = (np.abs(h - x) <= tol_abs) | (np.abs(l - x) <= tol_abs) | (np.abs(bt - x) <= tol_abs) | (np.abs(bb - x) <= tol_abs)
    return int(m.sum())


def best_level(C, lo, hi, tol_abs, i_lo, fallback, min_touch):
    """level in [lo, hi] (from candle H/L/BT/BB values) with the most touches; replaces the wick fallback only
    if it has strictly more touches than the fallback AND >= min_touch"""
    vals = np.r_[C["h"][i_lo:], C["l"][i_lo:], C["bt"][i_lo:], C["bb"][i_lo:]]
    vals = np.unique(np.round(vals[(vals >= lo) & (vals <= hi)], 6))
    fb_n = touches(C, fallback, tol_abs, i_lo)
    best, bn = fallback, fb_n
    for x in vals:
        nt = touches(C, x, tol_abs, i_lo)
        if nt > bn:
            best, bn = float(x), nt
    if best != fallback and bn < min_touch:
        return fallback, fb_n
    return best, bn


def pivots_lr(a, left, right, kind="hi"):
    """pivot with a long LEFT window (a 'clear' high = highest for `left` weeks before it) and `right` weeks after"""
    out = []
    for i in range(len(a)):
        lo, hi = max(0, i - left), min(len(a), i + right + 1)
        if hi - i - 1 < 1:
            continue
        seg = a[lo:hi]
        if (kind == "hi" and a[i] >= seg.max()) or (kind == "lo" and a[i] <= seg.min()):
            out.append(i)
    return out


@lru_cache(maxsize=None)
def raw_levels(t, read_date, kind, k, tol, min_touch, touch_back, use_touch=1, left=0):
    L = max(k, left)
    """all swing levels of one type, most recent first, with geometry + significance (cached per param subset)"""
    C = V1.ctx(t, read_date)
    A, n, h, l, c, bt, bb = C["atr"], C["n"], C["h"], C["l"], C["c"], C["bt"], C["bb"]
    tl = tol * A
    i_lo = max(0, n - LOOKBACK)
    out = []
    if kind == "retest":
        # "high candle" = local max of body top (red or green) or of wick high; zone bottom = its body top
        piv = sorted(set(pivots_lr(bt, L, k)) | set(pivots_lr(h, L, k)))
        for i in sorted([i for i in piv if i_lo <= i < C["ihi"]], reverse=True):
            # use the candle with the highest body top within +-1 week as "the high candle"
            js = range(max(0, i - 1), min(n, i + 2))
            j = max(js, key=lambda q: bt[q])
            hi_w = float(h[max(js, key=lambda q: h[q])])
            zb = float(bt[j])
            if not (c[i + 1:] > hi_w).any():                 # never closed above -> not broken resistance
                continue
            if C["rh"] - hi_w < 0.5 * A:                      # this is the recent high itself
                continue
            zt, nt = best_level(C, zb + 0.02 * A, hi_w + tl, tl, max(i_lo, i - touch_back), hi_w, min_touch if use_touch else 10**9)
            seg = l[i + 1:i + 1 + 8]
            react = (hi_w - seg.min()) / A if len(seg) else 0.0
            out.append((i, zb, zt, nt, react))
    else:
        piv = sorted(set(pivots_lr(l, L, k, "lo")) | set(pivots_lr(bb, L, k, "lo")))
        for i in sorted([i for i in piv if i >= i_lo], reverse=True):
            js = range(max(0, i - 1), min(n, i + 2))
            j = min(js, key=lambda q: bb[q])
            lo_w = float(l[min(js, key=lambda q: l[q])])
            zt = float(bb[j])
            if not (h[i + 1:] > zt + A).any():                # must have climbed up from it
                continue
            zb, nt = best_level(C, lo_w - tl, zt - 0.02 * A, tl, max(i_lo, i - touch_back), lo_w, min_touch if use_touch else 10**9)
            seg = h[i + 1:i + 1 + 8]
            react = (seg.max() - lo_w) / A if len(seg) else 0.0
            out.append((i, zb, zt, nt, react))
    # de-duplicate neighbours (same cluster)
    ded, last_i = [], None
    for r in out:
        if last_i is not None and abs(r[0] - last_i) <= 1:
            continue
        ded.append(r); last_i = r[0]
    return tuple(ded)


def candidates(C, P, kind, t, read_date):
    A, c = C["atr"], C["c"]
    last = c[-1]
    res = []
    for (i, zb, zt, nt, react) in raw_levels(t, read_date, kind, P["k"], P["tol"], P["min_touch"], P["touch_back"], P["use_touch"], P["left"]):
        if react < P["min_react"]:                         # not a "clear" swing
            continue
        if zb > last + P["break_tol"] * A:                 # level above current price: not approaching it
            continue
        pb = c[max(C["ihi"], i) + 1:]
        if len(pb) and pb.min() < zb - P["break_tol"] * A: # current pullback already closed below it -> broken
            continue
        res.append(dict(kind=kind, zb=zb, zt=zt, i=i, touches=nt, react=react))
    return res


def predict_v2(t, read_date, P):
    C = V1.ctx(t, read_date)
    A, last = C["atr"], C["c"][-1]
    picks = []
    for kind in ("retest", "support"):
        cs = candidates(C, P, kind, t, read_date)
        if cs:
            picks.append(cs[0])                    # most recent valid level of that type
    override = False
    if not picks:
        zb = C["pb_low"]; zt = zb + 0.33 * A; kind = "fallback_pullback_low"; ch = dict(touches=0, react=0, i=-1)
    else:
        for p in picks:
            p["dist"] = max(0.0, last - p["zt"]) / A
            p["sig"] = p["touches"] + P["w_react"] * p["react"]
        picks.sort(key=lambda p: p["dist"])        # nearest below price first (reached first on the way down)
        ch = picks[0]
        if len(picks) == 2 and picks[1]["sig"] - picks[0]["sig"] >= P["thr"]:
            ch, override = picks[1], True
        zb, zt, kind = ch["zb"], ch["zt"], ch["kind"]
    if zt <= zb:
        zt = zb + 0.05 * A
    e = zt - ENTRY_BELOW_TOP * A
    sl = min(e - RISK_ATR_W * C["atr_w"], C["pb_low"] - 0.01)   # keep SL below the pullback low
    tp = C["bt26"] + TP_OFF * A
    rr = (tp - e) / (e - sl) if e > sl else np.nan
    return dict(p_zone_top=zt, p_zone_bottom=zb, p_entry=e, p_sl=sl, p_tp=tp, p_rr=rr, p_kind=kind,
                p_override=override, p_peak_age_w=C["n"] - 1 - ch["i"] if ch["i"] >= 0 else 0,
                p_touches=ch["touches"], p_react_atr=ch["react"], n_types=len(picks), atr=A, atr_w=C["atr_w"])


def predict_hybrid(t, read_date, P, w_pb=0.5, w_close=0.6, w_fib=0.3):
    """v2 candidate generation (both types, Eyal's validity rules) + v1-style proximity scoring instead of
    recency/nearest; weights fixed to the v1 fit (no new tuning)."""
    C = V1.ctx(t, read_date)
    A, last = C["atr"], C["c"][-1]
    lo52 = V1.fib_anchor_low(C, 52)
    fib382 = C["rh"] - 0.382 * (C["rh"] - lo52)
    best = None
    for kind in ("retest", "support"):
        for rank, z in enumerate(candidates(C, P, kind, t, read_date)):
            zb, zt = z["zb"], max(z["zt"], z["zb"] + 0.05 * A)
            s = (w_pb * V1.zdist(C["pb_low"], zb - 0.3 * A, zt + 0.3 * A) / A + w_close * V1.zdist(last, zb, zt) / A
                 + w_fib * abs((zb + zt) / 2 - fib382) / A + 0.01 * rank)
            if best is None or s < best[0]:
                best = (s, z, zb, zt)
    p = predict_v2(t, read_date, P)
    if best is None:
        return p
    _, z, zb, zt = best
    e = zt - ENTRY_BELOW_TOP * A
    sl = min(e - RISK_ATR_W * C["atr_w"], C["pb_low"] - 0.01)
    p.update(p_zone_top=zt, p_zone_bottom=zb, p_entry=e, p_sl=sl, p_rr=(p["p_tp"] - e) / (e - sl), p_kind=z["kind"],
             p_override=False, p_peak_age_w=C["n"] - 1 - z["i"], p_touches=z["touches"])
    return p


def score_row(t, p):
    v = D[t]; A = p["atr"]
    r = dict(ticker=t, **{k: v[k] for k in ["zone_top", "zone_bottom", "entry", "sl", "tp", "rr"]}, **p)
    r["zone_iou"] = V1.iou(v["zone_bottom"], v["zone_top"], p["p_zone_bottom"], p["p_zone_top"])
    r["zone_overlap"] = r["zone_iou"] > 0
    r["zone_mid_err_atr"] = ((p["p_zone_top"] + p["p_zone_bottom"]) - (v["zone_top"] + v["zone_bottom"])) / 2 / A
    for a, b in [("zone_top", "p_zone_top"), ("zone_bottom", "p_zone_bottom"), ("entry", "p_entry"), ("sl", "p_sl"), ("tp", "p_tp")]:
        r[f"{a}_err_atr"] = (p[b] - v[a]) / A
        r[f"{a}_err_pct"] = (p[b] - v[a]) / v[a] * 100
    r["rr_err"] = p["p_rr"] - v["rr"]
    return r


def eval_v2(ts, P):
    return pd.DataFrame([score_row(t, predict_v2(t, D[t]["read_date"], P)) for t in ts])


def summary(df):
    return {"n": len(df),
            "zone overlap": f"{int(df.zone_overlap.sum())}/{len(df)}",
            "mean IoU": round(df.zone_iou.mean(), 2),
            "IoU>=0.5": f"{int((df.zone_iou >= 0.5).sum())}/{len(df)}",
            "med |zone-mid err| ATR": round(df.zone_mid_err_atr.abs().median(), 2),
            "med |entry err| ATR": round(df.entry_err_atr.abs().median(), 2),
            "med |SL err| ATR": round(df.sl_err_atr.abs().median(), 2),
            "med |TP err| ATR": round(df.tp_err_atr.abs().median(), 2),
            "med |entry err| %": round(df.entry_err_pct.abs().median(), 2),
            "med |SL err| %": round(df.sl_err_pct.abs().median(), 2),
            "med |R:R err|": round(df.rr_err.abs().median(), 2),
            "R:R>=2 agree": f"{int(((df.p_rr >= 2) == (df.rr >= 2)).sum())}/{len(df)}"}


GRID = dict(k=[3, 4], tol=[0.10, 0.20], break_tol=[0.15, 0.35], min_react=[0.0, 1.0, 2.0],
            w_react=[0.0, 0.5], thr=[2.0, 4.0, 99.0], use_touch=[0, 1])
# note: a long-left-window "clear high" option (left=8/13/26) was tried and overfit (CV overlap 25/54); dropped


def fit_v2(train):
    best = None
    keys = list(GRID)
    for combo in itertools.product(*[GRID[k] for k in keys]):
        Q = dict(DEFAULT, **dict(zip(keys, combo)))
        ev = eval_v2(train, Q)
        sc = ev.zone_iou.mean() - 0.05 * ev.zone_mid_err_atr.abs().median()
        if best is None or sc > best[0] + 1e-9:
            best = (sc, Q)
    return best[1]


def v1_eval(ts, P1):
    ev = V1.evaluate(ts, P1)
    return ev


def main(nfold=5):
    found = sorted(t for t, v in D.items() if v.get("found"))
    learn = [t for t in found if t not in BOT_EXACT]
    folds = [[t for i, t in enumerate(learn) if i % nfold == k] for k in range(nfold)]
    F = pd.DataFrame([V1.features(t, D[t]) for t in found])
    F.round(4).to_csv(OUT / "v2_features_all.csv", index=False)

    # untuned v2 with Eyal's suggested defaults
    ev_def = eval_v2(learn, DEFAULT)
    cv2, cv1, cvh, fold_params = [], [], [], []
    for k, te in enumerate(folds):
        tr = [t for t in learn if t not in te]
        P2 = fit_v2(tr); fold_params.append({kk: P2[kk] for kk in GRID})
        e2 = eval_v2(te, P2); e2["fold"] = k; cv2.append(e2)
        P1 = V1.fit(tr, F)
        P1.update(entry_mode="below_top", entry_below_top_atr=ENTRY_BELOW_TOP, risk_atr_w=RISK_ATR_W, tp_off_atr=TP_OFF)
        e1 = V1.evaluate(te, P1); e1["fold"] = k; cv1.append(e1)
        eh = pd.DataFrame([score_row(t, predict_hybrid(t, D[t]["read_date"], dict(P2, min_react=0.0))) for t in te])
        cvh.append(eh)
    cv2, cv1, cvh = pd.concat(cv2), pd.concat(cv1), pd.concat(cvh)
    cvh.round(4).to_csv(OUT / "hybrid_predictions_cv.csv", index=False)
    P_all = fit_v2(learn)
    ev_all = eval_v2(learn, P_all)
    S = {"v1 (5-fold CV)": summary(cv1), "v2 defaults (no tuning)": summary(ev_def),
         "v2 (5-fold CV)": summary(cv2), "v2 fit on all (in-sample)": summary(ev_all),
         "hybrid v2-candidates + v1-scoring (5-fold CV)": summary(cvh)}
    S["v2 (5-fold CV)"]["override used"] = f"{int(cv2.p_override.sum())}/{len(cv2)}"
    S["v2 defaults (no tuning)"]["override used"] = f"{int(ev_def.p_override.sum())}/{len(ev_def)}"
    S["v2 fit on all (in-sample)"]["override used"] = f"{int(ev_all.p_override.sum())}/{len(ev_all)}"
    json.dump(dict(summary=S, fold_params=fold_params, params_all=P_all, excluded=sorted(BOT_EXACT)),
              open(OUT / "v2_summary.json", "w"), indent=2, default=str)
    cv2.round(4).to_csv(OUT / "v2_predictions_cv.csv", index=False)
    cv1.round(4).to_csv(OUT / "v1_predictions_cv_55.csv", index=False)
    ev_def.round(4).to_csv(OUT / "v2_predictions_defaults.csv", index=False)
    ev_all.round(4).to_csv(OUT / "v2_predictions_fit_all.csv", index=False)
    print(pd.DataFrame(S).to_string()); print(fold_params); print(P_all)
    m = cv2.merge(cv1[["ticker", "zone_iou", "p_zone_bottom", "p_zone_top"]].rename(
        columns={"zone_iou": "v1_iou", "p_zone_bottom": "v1_zb", "p_zone_top": "v1_zt"}), on="ticker")
    m.round(4).to_csv(OUT / "v2_vs_v1_per_ticker.csv", index=False)
    print(m[["ticker", "p_kind", "p_override", "zone_bottom", "zone_top", "p_zone_bottom", "p_zone_top", "zone_iou", "v1_iou",
             "p_peak_age_w", "p_touches"]].round(2).to_string())
    return m


if __name__ == "__main__":
    main()
