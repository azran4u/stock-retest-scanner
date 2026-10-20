"""Grid search of srs.trend parameters on the golden set.
Ranked by balanced accuracy (the set is 116 up / 14 not-up), then accuracy.
Run: python tools/tune_trend.py [top_n]"""
import itertools
import sys

from srs.golden import evaluate, load_cases, load_daily

cases, daily = load_cases(), load_daily()
grid = dict(pivot_k=[2, 3, 4, 5], min_sep_weeks=[1, 4, 8, 12], price=["wick", "body"],
            lookback_weeks=[104, 156], provisional=[True, False], break_close=[True, False],
            pullback=["ignore", "confirmed", "judge"], min_step_atr=[0.0, 0.5])
res = []
for vals in itertools.product(*grid.values()):
    p = dict(zip(grid, vals))
    e = evaluate(p, cases, daily)
    res.append((e["balanced_accuracy"], e["accuracy"], p, e))
res.sort(key=lambda x: (-x[0], -x[1]))
for ba, acc, p, e in res[: int(sys.argv[1]) if len(sys.argv) > 1 else 25]:
    print(f"bal {ba:.3f} acc {acc:.3f} tp {e['tp']} fn {e['fn']} fp {e['fp']} tn {e['tn']}  {p}")
