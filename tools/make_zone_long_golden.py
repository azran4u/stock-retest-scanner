"""Golden cases for the bot-Long-follows-zone rule: Python srs_app.bot_drawings.long_from_zone on frozen daily bars
(3 years per ticker) -> tests/golden/zone_long_golden.json.gz. The TS mirror (webapp/src/botlong.ts) must agree
(webapp/test_botlong.mjs) and the Python rule must keep agreeing (tests/test_zone_long.py).
Usage: python tools/make_zone_long_golden.py   (reads /workspace/stock-screener/app_drawings.json + hist cache)"""
import gzip, json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import pandas as pd
from srs_app import bot_drawings as B

OUT = Path(__file__).resolve().parents[1] / "tests" / "golden" / "zone_long_golden.json.gz"
TICKERS = ["CXW", "CLMT", "QCOM", "HWC", "TWST", "RY", "SBLK", "U", "ARGX", "SMTC", "DELL", "ZM", "FDX", "KRYS", "HBAN"]


def frozen(t):
    d = B._rules()["V1"].H[t][["Open", "High", "Low", "Close", "Volume"]].dropna(subset=["Open", "High", "Low", "Close"])
    d = d[d.index >= d.index.max() - pd.Timedelta(days=3 * 365)].round(4)
    return d


def main():
    store = json.loads(Path("/workspace/stock-screener/app_drawings.json").read_text())
    V1 = B._rules()["V1"]
    daily, cases = {}, []
    for t in TICKERS:
        if t not in V1.H:
            continue
        d = frozen(t)
        daily[t] = [[str(i.date()), *[float(x) for x in r[:4]], float(r[4])] for i, r in zip(d.index, d.values)]
        raw = V1.H[t]
        V1.H[t] = d
        B._clear_caches()
        try:
            rec = store.get(t) or {}
            zt, zb = rec.get("zone_top"), rec.get("zone_bottom")
            if zt is None or zb is None:
                b = B.compute(t)
                zt, zb = b.get("zone_top"), b.get("zone_bottom")
            if zt is None:
                last = float(d["Close"].iloc[-1]); zt, zb = round(last * 0.95, 2), round(last * 0.93, 2)
            a = B.long_from_zone(t, zb, zt)["atr"]
            for k, (b0, t0) in enumerate([(zb, zt), (zb - 0.5 * a, zt - 0.5 * a), (zb + 0.4 * a, zt + 0.4 * a),
                                          (zb - 1.5 * a, zb - 1.0 * a)]):
                b0, t0 = round(b0, 2), round(t0, 2)
                r = B.long_from_zone(t, b0, t0)
                cases.append({"ticker": t, "variant": k, "zone_bottom": b0, "zone_top": t0, **r})
        finally:
            V1.H[t] = raw
            B._clear_caches()
    OUT.write_bytes(gzip.compress(json.dumps({"daily": daily, "cases": cases}, separators=(",", ":")).encode()))
    print(f"{OUT}: {len(cases)} cases, {len(daily)} tickers, "
          f"{sum(c['sl_src'] == 'wick_low' for c in cases)} wick_low / {sum(c['sl_src'] != 'wick_low' for c in cases)} default")


if __name__ == "__main__":
    main()
