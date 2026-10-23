#!/usr/bin/env python
# Vendored verbatim from /workspace/drawing-learn (2026-10-23) for srs_app.bot_drawings + the golden test;
# only the data paths below are env-configurable (SRS_HIST_CACHE, SRS_TV_DRAWINGS). Research outputs are not vendored.
"""
Infer Eyal's weekly drawing rules (support rectangle + Long Position) from
/workspace/stock-screener/tv_drawings.json and validate them hold-out style.

ADD-ONLY research script: reads tv_drawings.json, hist_cache.pkl, imports
helpers from stock_screen.py; writes only into /workspace/drawing-learn/.

Outputs:
  features.csv      per-ticker features of the actual drawings
  predictions.csv   predicted vs actual levels (train/test/all, errors in ATR & %)
  rules.json        learned parameters
  report.md         written by this script (numbers) - narrative appended manually
  plots/*.png       actual vs predicted comparison charts
"""
import json, sys, itertools
from pathlib import Path
import numpy as np, pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))  # repo root: stock_screen.py
from stock_screen import to_weekly, atr_series  # read-only reuse

OUT = Path(__file__).resolve().parent  # vendored: research outputs are not written in production
import os
H = pd.read_pickle(os.environ.get("SRS_HIST_CACHE", "/workspace/hist_cache.pkl"))
D = json.load(open(os.environ.get("SRS_TV_DRAWINGS", "/workspace/stock-screener/tv_drawings.json")))
PROV = pd.read_csv(OUT / "provenance.csv").set_index("t") if (OUT / "provenance.csv").exists() else None
# drawings that are byte-identical to an earlier bot proposal (zone+entry+SL+TP): not Eyal's own geometry
BOT_EXACT = {"AMAT", "CLH"}
LOOKBACK_HI = 26          # recent swing high = max High in last 26 weeks
MAX_AGE = 160             # how far back to look for broken resistance


# ---------------------------------------------------------------- helpers
def wilder_atr(w, n=14):
    h, l, c = w.High, w.Low, w.Close
    pc = c.shift()
    tr = pd.concat([h - l, (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1 / n, adjust=False).mean()


def pivots(a, k, kind="hi"):
    out = []
    for i in range(len(a)):
        lo, hi = max(0, i - k), min(len(a), i + k + 1)
        if hi - i - 1 < 1:  # need at least one bar to the right
            continue
        seg = a[lo:hi]
        if (kind == "hi" and a[i] >= seg.max()) or (kind == "lo" and a[i] <= seg.min()):
            out.append(i)
    return out


def weekly(t, read_date):
    d = H[t]
    d = d[d.index <= read_date]
    return to_weekly(d)


from functools import lru_cache


@lru_cache(maxsize=None)
def ctx(t, read_date):
    w = weekly(t, read_date)
    o, h, l, c = [w[x].values.astype(float) for x in ["Open", "High", "Low", "Close"]]
    n = len(w)
    bt, bb = np.maximum(o, c), np.minimum(o, c)
    atr = float(atr_series(w).iloc[-1])
    atr_w = float(wilder_atr(w).iloc[-1])
    ihi = n - LOOKBACK_HI + int(np.argmax(h[-LOOKBACK_HI:]))
    pb_low = float(l[ihi + 1:].min()) if ihi < n - 1 else float(l[-1])
    ma = {}
    for p in (10, 20, 30, 50):
        ma[f"sma{p}"] = float(w.Close.rolling(p).mean().iloc[-1])
        ma[f"ema{p}"] = float(w.Close.ewm(span=p, adjust=False).mean().iloc[-1])
    return dict(w=w, o=o, h=h, l=l, c=c, n=n, bt=bt, bb=bb, atr=atr, atr_w=atr_w, ihi=ihi,
                rh=float(h[ihi]), bt26=float(bt[-LOOKBACK_HI:].max()), pb_low=pb_low, ma=ma)


def fib_anchor_low(C, lb):
    i0 = max(0, C["ihi"] - lb)
    seg = C["l"][i0:C["ihi"] + 1]
    return float(seg.min())


def fvgs(C):
    """bullish 3-bar FVGs: Low[i] > High[i-2] -> gap [High[i-2], Low[i]]"""
    h, l, n = C["h"], C["l"], C["n"]
    return [(float(h[i - 2]), float(l[i]), i) for i in range(max(2, n - MAX_AGE), n) if l[i] > h[i - 2]]


def zdist(x, lo, hi):
    return 0.0 if lo <= x <= hi else (lo - x if x < lo else x - hi)


def iou(a0, a1, b0, b1):
    inter = max(0.0, min(a1, b1) - max(a0, b0))
    uni = max(a1, b1) - min(a0, b0)
    return inter / uni if uni > 0 else 0.0


# ---------------------------------------------------------------- 1. features
def features(t, v):
    C = ctx(t, v["read_date"])
    zt, zb, e, sl, tp = v["zone_top"], v["zone_bottom"], v["entry"], v["sl"], v["tp"]
    A, n, h, bt, bb, l, c = C["atr"], C["n"], C["h"], C["bt"], C["bb"], C["l"], C["c"]
    tol = 0.15 * A
    f = dict(ticker=t, read_date=v["read_date"], atr_sma14=A, atr_wilder14=C["atr_w"],
             zone_top=zt, zone_bottom=zb, entry=e, sl=sl, tp=tp, rr=v["rr"],
             bot_exact=t in BOT_EXACT)
    f["zone_h_atr"] = (zt - zb) / A
    f["zone_h_pct"] = (zt - zb) / zb * 100
    f["close_vs_zt_atr"] = (c[-1] - zt) / A
    f["weeks_since_recent_high"] = n - 1 - C["ihi"]
    f["pullback_low_vs_zb_atr"] = (C["pb_low"] - zb) / A
    f["pullback_low_in_zone_pm0.3atr"] = zb - 0.3 * A <= C["pb_low"] <= zt + 0.3 * A
    # prior swing highs (pivot k=3 on High or body top) before the recent high
    ph = sorted(set(pivots(h, 3)) | set(pivots(bt, 3)))
    ph = [i for i in ph if n - MAX_AGE <= i < C["ihi"] - 1]
    best = None
    for i in ph:
        d = min(abs(h[i] - zt), abs(bt[i] - zb), abs(h[i] - zb) + 0.0, abs(bt[i] - zt))
        if best is None or d < best[0]:
            best = (d, i)
    if best:
        d, i = best
        broke = bool((c[i + 1:C["ihi"] + 1] > h[i]).any())
        f["prior_swing_high_age_w"] = n - 1 - i
        f["prior_swing_high_H"] = h[i]
        f["prior_swing_high_BT"] = bt[i]
        f["zt_vs_swingH_atr"] = (zt - h[i]) / A
        f["zb_vs_swingBT_atr"] = (zb - bt[i]) / A
        f["zone_is_broken_resistance_loose"] = bool(d <= tol and broke)
    # strict: zone == [body top, wick high] of ONE broken pivot-high candle (either edge may come from a
    # neighbouring bar of the same peak cluster within +-2 weeks)
    strict = False
    for i in ph:
        if not (c[i + 1:C["ihi"] + 1] > h[i]).any():
            continue
        js = range(max(0, i - 2), min(n, i + 3))
        top_ok = any(abs(h[j] - zt) <= tol for j in js)
        bot_ok = any(abs(bt[j] - zb) <= tol for j in js)
        if top_ok and bot_ok:
            strict = True
            f["strict_peak_age_w"] = n - 1 - i
            break
    f["zone_is_broken_resistance_strict"] = strict
    # one edge = H or BT of a broken pivot (other edge free)
    f["zone_edge_on_broken_pivot"] = any(
        (c[i + 1:C["ihi"] + 1] > h[i]).any() and min(abs(h[i] - zt), abs(bt[i] - zb), abs(bt[i] - zt), abs(h[i] - zb)) <= tol
        for i in ph)
    # zone edge -> any candle H/BT within 0.15 ATR in the last 160w? (cluster of same peak)
    f["zt_matches_H_or_BT"] = bool(np.min(np.abs(np.r_[h[-MAX_AGE:], bt[-MAX_AGE:]] - zt)) <= tol)
    f["zb_matches_BT_or_H"] = bool(np.min(np.abs(np.r_[h[-MAX_AGE:], bt[-MAX_AGE:]] - zb)) <= tol)
    # swing lows
    pl = [i for i in pivots(l, 3, "lo") if i >= n - 52]
    below = [i for i in pl if l[i] < zb]
    if below:
        j = max(below)
        f["nearest_swing_low_below_zone"] = l[j]
        f["sl_vs_swing_low_atr"] = (sl - l[j]) / A
    f["sl_vs_pullback_low_atr"] = (sl - C["pb_low"]) / A
    f["sl_below_pullback_low"] = sl < C["pb_low"]
    # fib retracements of latest major swing (anchor low variants -> recent high)
    for lb in (26, 52, 104):
        lo = fib_anchor_low(C, lb)
        rng = C["rh"] - lo
        hits = []
        for r in (0.382, 0.5, 0.618):
            lvl = C["rh"] - r * rng
            if zb - 0.25 * A <= lvl <= zt + 0.25 * A:
                hits.append(str(r))
        f[f"fib{lb}_hits"] = ",".join(hits)
        f[f"zone_mid_retr{lb}"] = (C["rh"] - (zt + zb) / 2) / rng if rng > 0 else np.nan
    # MAs
    for k, val in C["ma"].items():
        f[f"{k}_vs_zmid_atr"] = (val - (zt + zb) / 2) / A
        f[f"{k}_in_zone"] = zb - 0.25 * A <= val <= zt + 0.25 * A
    # FVG overlap
    fv = [g for g in fvgs(C) if g[1] >= zb - 0.1 * A and g[0] <= zt + 0.1 * A]
    f["fvg_overlap"] = len(fv) > 0
    # entry
    f["entry_pos_in_zone"] = (e - zb) / (zt - zb) if zt > zb else np.nan
    f["entry_vs_zt_atr"] = (e - zt) / A
    # SL
    f["sl_below_zb_atr"] = (zb - sl) / A
    f["risk_atr_sma"] = (e - sl) / A
    f["risk_atr_wilder"] = (e - sl) / C["atr_w"]
    f["risk_pct"] = (e - sl) / e * 100
    # TP
    f["tp_vs_max_bodytop26_atr"] = (tp - C["bt26"]) / A
    f["tp_vs_recent_high_wick_atr"] = (tp - C["rh"]) / A
    f["tp_vs_ath_atr"] = (tp - h.max()) / A
    lo52 = fib_anchor_low(C, 52)
    f["tp_vs_ext1272_atr"] = (tp - (C["rh"] + 0.272 * (C["rh"] - lo52))) / A
    f["tp_vs_measured_move_atr"] = (tp - (zt + (C["rh"] - zt))) / A  # == rh, kept for completeness
    f["rr_calc"] = (tp - e) / (e - sl)
    return f


# ---------------------------------------------------------------- 2/3. predictor
DEFAULT = dict(k=3, w_pb=1.0, w_close=0.3, w_fib=0.3, w_ema=0.0, fb_pen=1.0, min_drop_atr=0.5,
               entry_mode="below_top", entry_frac=0.6, entry_below_top_atr=0.13,
               risk_atr_w=1.0, tp_off_atr=-0.09, fb_height_atr=0.33)


def predict(t, read_date, P):
    C = ctx(t, read_date)
    A, n, h, bt, l, c = C["atr"], C["n"], C["h"], C["bt"], C["l"], C["c"]
    lo52 = fib_anchor_low(C, 52)
    fib382 = C["rh"] - 0.382 * (C["rh"] - lo52)
    ema30 = C["ma"]["ema30"]

    def score(zb, zt):
        mid = (zb + zt) / 2
        return (P["w_pb"] * zdist(C["pb_low"], zb - 0.3 * A, zt + 0.3 * A) / A
                + P["w_close"] * zdist(c[-1], zb, zt) / A
                + P["w_fib"] * abs(mid - fib382) / A
                + P["w_ema"] * abs(mid - ema30) / A)

    cands = []
    ph = sorted(set(pivots(h, P["k"])) | set(pivots(bt, P["k"])))
    for i in ph:
        if not (n - MAX_AGE <= i < C["ihi"] - 1):
            continue
        zb, zt = float(bt[i]), float(h[i])
        if zt - zb < 0.08 * A:
            zt = zb + 0.08 * A
        if not (c[i + 1:C["ihi"] + 1] > zt).any():      # must have been broken (weekly close above)
            continue
        if C["rh"] - zt < P["min_drop_atr"] * A:          # real pullback room below the recent high
            continue
        cands.append((score(zb, zt), zb, zt, "broken_resistance", n - 1 - i))
    hgt = P["fb_height_atr"] * A
    zb = C["pb_low"]                                       # fallback 1: support on the pullback low
    cands.append((P["fb_pen"] + score(zb, zb + hgt), zb, zb + hgt, "pullback_low", 0))
    zb = fib382 - hgt / 2                                  # fallback 2: fib 0.382 box
    cands.append((P["fb_pen"] + score(zb, zb + hgt), zb, zb + hgt, "fib382", 0))
    s, zb, zt, kind, age = min(cands, key=lambda x: x[0])
    e = entry_rule(zb, zt, A, P)
    sl = e - P["risk_atr_w"] * C["atr_w"]
    tp = C["bt26"] + P["tp_off_atr"] * A
    rr = (tp - e) / (e - sl) if e > sl else np.nan
    return dict(p_zone_top=zt, p_zone_bottom=zb, p_entry=e, p_sl=sl, p_tp=tp, p_rr=rr,
                p_kind=kind, p_peak_age_w=age, atr=A, atr_w=C["atr_w"])


def entry_rule(zb, zt, A, P):
    if P["entry_mode"] == "below_top":
        return zt - P["entry_below_top_atr"] * A
    return zb + P["entry_frac"] * (zt - zb)


def evaluate(tickers, P):
    rows = []
    for t in tickers:
        v = D[t]
        p = predict(t, v["read_date"], P)
        A = p["atr"]
        r = dict(ticker=t, **{k: v[k] for k in ["zone_top", "zone_bottom", "entry", "sl", "tp", "rr"]}, **p)
        r["zone_iou"] = iou(v["zone_bottom"], v["zone_top"], p["p_zone_bottom"], p["p_zone_top"])
        r["zone_overlap"] = r["zone_iou"] > 0
        amid = (v["zone_top"] + v["zone_bottom"]) / 2
        pmid = (p["p_zone_top"] + p["p_zone_bottom"]) / 2
        r["zone_mid_err_atr"] = (pmid - amid) / A
        for a, b in [("zone_top", "p_zone_top"), ("zone_bottom", "p_zone_bottom"), ("entry", "p_entry"),
                     ("sl", "p_sl"), ("tp", "p_tp")]:
            r[f"{a}_err_atr"] = (p[b] - v[a]) / A
            r[f"{a}_err_pct"] = (p[b] - v[a]) / v[a] * 100
        r["rr_err"] = p["p_rr"] - v["rr"]
        # component checks: each rule applied to Eyal's OWN upstream levels
        e_c = entry_rule(v["zone_bottom"], v["zone_top"], A, P)
        r["comp_entry_err_atr"] = (e_c - v["entry"]) / A           # entry rule given actual zone
        sl_c = v["entry"] - P["risk_atr_w"] * p["atr_w"]
        r["comp_sl_err_atr"] = (sl_c - v["sl"]) / A                # SL rule given actual entry
        r["comp_rr"] = (p["p_tp"] - v["entry"]) / (v["entry"] - sl_c)
        rows.append(r)
    return pd.DataFrame(rows)


def summary(df):
    return dict(
        n=len(df),
        zone_overlap=f"{int(df.zone_overlap.sum())}/{len(df)}",
        zone_iou_mean=round(df.zone_iou.mean(), 2),
        zone_mid_within_0_5atr=f"{int((df.zone_mid_err_atr.abs() <= 0.5).sum())}/{len(df)}",
        med_abs_zone_mid_err_atr=round(df.zone_mid_err_atr.abs().median(), 2),
        med_abs_entry_err_atr=round(df.entry_err_atr.abs().median(), 2),
        med_abs_sl_err_atr=round(df.sl_err_atr.abs().median(), 2),
        med_abs_tp_err_atr=round(df.tp_err_atr.abs().median(), 2),
        med_abs_entry_err_pct=round(df.entry_err_pct.abs().median(), 2),
        med_abs_sl_err_pct=round(df.sl_err_pct.abs().median(), 2),
        med_abs_tp_err_pct=round(df.tp_err_pct.abs().median(), 2),
        med_abs_rr_err=round(df.rr_err.abs().median(), 2),
        comp_med_abs_entry_err_atr=round(df.comp_entry_err_atr.abs().median(), 2),
        comp_med_abs_sl_err_atr=round(df.comp_sl_err_atr.abs().median(), 2),
        comp_sl_within_0_15atr=f"{int((df.comp_sl_err_atr.abs() <= 0.15).sum())}/{len(df)}",
        tp_within_0_15atr=f"{int((df.tp_err_atr.abs() <= 0.15).sum())}/{len(df)}",
        rr_ge2_agree=f"{int(((df.p_rr >= 2) == (df.rr >= 2)).sum())}/{len(df)}",
    )


def fit(train, F):
    """Scalar rules = medians of training features; zone-selection weights = small grid search on train only."""
    Ft = F[F.ticker.isin(train)]
    P = dict(DEFAULT)
    P["entry_frac"] = float(Ft.entry_pos_in_zone.median())
    P["entry_below_top_atr"] = float(-Ft.entry_vs_zt_atr.median())
    # pick the entry formulation with lower spread on train
    P["entry_mode"] = "below_top" if Ft.entry_vs_zt_atr.std() < (Ft.entry_pos_in_zone * Ft.zone_h_atr).std() else "frac"
    P["risk_atr_w"] = float(Ft.risk_atr_wilder.median())
    P["tp_off_atr"] = float(Ft.tp_vs_max_bodytop26_atr.median())
    P["fb_height_atr"] = float(Ft.zone_h_atr.median())
    grid = dict(w_pb=[0.0, 0.5, 1.0], w_close=[0.0, 0.3, 0.6], w_fib=[0.0, 0.3, 0.6, 1.0],
                w_ema=[0.0, 0.3, 0.6], fb_pen=[0.5, 1.0, 1.5], k=[2, 3])
    best = None
    keys = list(grid)
    for combo in itertools.product(*[grid[k] for k in keys]):
        Q = dict(P, **dict(zip(keys, combo)))
        ev = evaluate(train, Q)
        sc = ev.zone_iou.mean() - 0.1 * ev.zone_mid_err_atr.abs().median()
        if best is None or sc > best[0] + 1e-9:
            best = (sc, Q)
    return best[1]


# ---------------------------------------------------------------- plots
def plot(t, row, path, weeks=80):
    sys.path.append(str(OUT / "_libs"))
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    w = weekly(t, D[t]["read_date"]).iloc[-weeks:]
    fig, ax = plt.subplots(figsize=(11, 5.5))
    x = np.arange(len(w))
    for i, (o, h, l, c) in enumerate(w[["Open", "High", "Low", "Close"]].values):
        col = "#26a69a" if c >= o else "#ef5350"
        ax.vlines(i, l, h, color=col, lw=0.8)
        ax.add_patch(plt.Rectangle((i - 0.35, min(o, c)), 0.7, max(abs(c - o), 1e-9), color=col))
    xr = len(w) + 6
    ax.axhspan(row.zone_bottom, row.zone_top, xmin=0, xmax=1, color="royalblue", alpha=0.25, label="actual zone")
    ax.axhspan(row.p_zone_bottom, row.p_zone_top, color="orange", alpha=0.25, label="predicted zone")
    for lvl, ls, lab, col in [(row.entry, "-", "entry", "royalblue"), (row.sl, "-", "SL", "royalblue"),
                              (row.tp, "-", "TP", "royalblue"), (row.p_entry, "--", "p entry", "darkorange"),
                              (row.p_sl, "--", "p SL", "darkorange"), (row.p_tp, "--", "p TP", "darkorange")]:
        ax.hlines(lvl, len(w) - 1, xr, colors=col, linestyles=ls, lw=1.4)
        ax.text(xr + 0.3, lvl, f"{lab} {lvl:.2f}", fontsize=7, color=col, va="center")
    ax.set_xlim(-1, xr + 9)
    ticks = list(range(0, len(w), 10))
    ax.set_xticks(ticks)
    ax.set_xticklabels([w.index[i].strftime("%Y-%m") for i in ticks], fontsize=8)
    ax.set_title(f"{t} weekly — actual (blue, R:R {row.rr:.2f}) vs predicted (orange, R:R {row.p_rr:.2f}, {row.p_kind}); "
                 f"zone IoU {row.zone_iou:.2f}", fontsize=9)
    ax.legend(loc="upper left", fontsize=8)
    ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(path, dpi=110)
    plt.close(fig)


# ---------------------------------------------------------------- main
def main():
    found = sorted(t for t, v in D.items() if v.get("found"))
    F = pd.DataFrame([features(t, D[t]) for t in found])
    F.round(4).to_csv(OUT / "features.csv", index=False)

    learn = [t for t in found if t not in BOT_EXACT]
    test = [t for i, t in enumerate(learn) if i % 3 == 2]          # deterministic ~1/3 hold-out
    train = [t for t in learn if t not in test]
    P = fit(train, F)
    json.dump(dict(params=P, train=train, test=test, bot_exact_excluded=sorted(BOT_EXACT)),
              open(OUT / "rules.json", "w"), indent=2)

    ev_tr, ev_te, ev_all = evaluate(train, P), evaluate(test, P), evaluate(found, P)
    for df, s in [(ev_tr, "train"), (ev_te, "test"), (ev_all, "all")]:
        df.insert(1, "split", s)
    ev_all["split"] = ["bot_exact" if t in BOT_EXACT else ("test" if t in test else "train") for t in ev_all.ticker]
    pd.concat([ev_tr, ev_te]).round(4).to_csv(OUT / "predictions_holdout.csv", index=False)
    ev_all.round(4).to_csv(OUT / "predictions_all.csv", index=False)

    # baseline: legacy stock_screen geometry rule-of-thumb (entry mid, TP=BT of latest swing) is in RULES; we
    # also report the pure "scalar" rules (SL/TP) that do not depend on zone choice.
    S = {s: summary(df) for s, df in [("train", ev_tr), ("test (held-out)", ev_te), ("all", ev_all),
                                      ("all excl. bot-exact", ev_all[~ev_all.ticker.isin(BOT_EXACT)])]}
    json.dump(S, open(OUT / "summary.json", "w"), indent=2)
    print(json.dumps(P, indent=1))
    print(pd.DataFrame(S).to_string())

    # 3-fold cross-validation: every non-bot ticker is predicted once by rules fit WITHOUT it
    cv = []
    for k in range(3):
        te = [t for i, t in enumerate(learn) if i % 3 == k]
        tr = [t for t in learn if t not in te]
        Pk = fit(tr, F)
        e = evaluate(te, Pk)
        e.insert(1, "split", f"cv_fold{k}")
        cv.append(e)
    cv = pd.concat(cv)
    cv.round(4).to_csv(OUT / "predictions_cv3.csv", index=False)
    S["3-fold CV (each ticker held out once)"] = summary(cv)
    json.dump(S, open(OUT / "summary.json", "w"), indent=2)
    print(pd.DataFrame(S).to_string())

    cols = ["ticker", "zone_bottom", "zone_top", "p_zone_bottom", "p_zone_top", "zone_iou", "zone_mid_err_atr",
            "entry", "p_entry", "entry_err_atr", "sl", "p_sl", "sl_err_atr", "tp", "p_tp", "tp_err_atr",
            "rr", "p_rr", "p_kind"]
    print(ev_te[cols].round(2).to_string())
    (OUT / "plots").mkdir(exist_ok=True)
    for t in sys.argv[1:] or []:
        r = ev_all[ev_all.ticker == t].iloc[0]
        plot(t, r, OUT / "plots" / f"{t}.png")
    return F, ev_tr, ev_te, ev_all, P, S


if __name__ == "__main__":
    main()
