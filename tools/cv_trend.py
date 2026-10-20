"""Leave-one-out check of the trend-parameter choice (is the tuned accuracy overfit?).
For each golden case: pick the best params (balanced accuracy, ties -> simpler = earlier in the
grid) on the other 129 cases, then predict the held-out case. Run: python tools/cv_trend.py"""
import itertools

import numpy as np

from srs.golden import evaluate, load_cases, load_daily

cases, daily = load_cases(), load_daily()
grid = [dict(pivot_k=k, min_sep_weeks=s, pullback=m) for m, k, s in
        itertools.product(["ignore", "confirmed", "judge"], [2, 3, 4, 5], [4, 8, 10, 12, 16])]
y = np.array([c["up"] for c in cases])
P = np.array([[r["pred"] for r in evaluate(p, cases, daily)["rows"]] for p in grid])  # grid x cases


def bal(pred, lab):
    pos, neg = lab, ~lab
    return ((pred & pos).sum() / pos.sum() + (~pred & neg).sum() / neg.sum()) / 2


hits = []
for i in range(len(cases)):
    m = np.ones(len(cases), bool); m[i] = False
    best = max(range(len(grid)), key=lambda g: (bal(P[g, m], y[m]), -g))
    hits.append(P[best, i] == y[i])
hits = np.array(hits)
print(f"LOO accuracy {hits.mean():.3f}; not-up recall {hits[~y].mean():.3f}; up recall {hits[y].mean():.3f}")
