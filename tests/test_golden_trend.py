"""Golden set: Eyal's manual uptrend labels (tests/golden_trend.yaml) on frozen price data.

Prints the confusion matrix and every misclassified ticker (run `pytest -s` to see it) and fails
only if accuracy drops below the recorded baseline, so parameter changes cannot silently regress."""
from srs.golden import confusion_text, evaluate
from srs.trend import TREND_DEFAULTS

BASELINE_ACCURACY = 0.79  # 0.800 with TREND_DEFAULTS on 2026-10-20 (104/130)


def test_golden_trend_accuracy():
    e = evaluate()
    print("\nsrs.trend golden set, params:", TREND_DEFAULTS)
    print(confusion_text(e))
    for r in e["rows"]:
        if r["pred"] is not None and r["pred"] != r["up"]:
            print(f"  MISS {r['ticker']:6s} label={'up' if r['up'] else 'not-up':6s} got={r['trend']:4s} "
                  f"asof={r['asof']}  {r['reason']}")
    assert not e["missing"], f"no data for {e['missing']}"
    assert e["accuracy"] >= BASELINE_ACCURACY
