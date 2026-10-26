"""app/data/rules.json for the app's 'כללים' page (Eyal 2026-10-26): the real thresholds, read from the code that runs
the nightly (stock_screen.py SCREENER_URL + constants, report_filters.CONFIG / CORE_FILTERS / WARN_FILTERS,
srs_app.bot_drawings constants), so the page never drifts from the rules. The Hebrew wording lives in the app
(webapp/src/rules.ts); only numbers / lists come from here."""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parent.parent

# FinViz screener filter codes -> Hebrew (unknown codes are shown as the raw code)
FV_HE = {
    "sh_price_o10": "מחיר מעל $10",
    "sh_price_o5": "מחיר מעל $5",
    "sh_price_o20": "מחיר מעל $20",
    "ta_sma50_pb": "מחיר מתחת לממוצע הנע 50 יומי (SMA50)",
    "ta_sma50_pa": "מחיר מעל הממוצע הנע 50 יומי (SMA50)",
    "ta_sma200_pa": "מחיר מעל הממוצע הנע 200 יומי (SMA200)",
    "ta_sma200_pb": "מחיר מתחת לממוצע הנע 200 יומי (SMA200)",
}


def screener_filters(stock_screen_py: Optional[Path] = None) -> Dict[str, Any]:
    """FinViz URL + its f= filter codes, parsed from stock_screen.py (the file the nightly runs)."""
    src = (stock_screen_py or ROOT / "stock_screen.py").read_text()
    m = re.search(r"SCREENER_URL\s*=\s*\(?((?:\s*\"[^\"]*\")+)", src)
    url = "".join(re.findall(r"\"([^\"]*)\"", m.group(1))) if m else ""
    f = re.search(r"[?&]f=([^&]*)", url)
    codes = [c for c in (f.group(1).split(",") if f else []) if c]
    return {"url": url, "filters": [{"code": c, "he": FV_HE.get(c, c)} for c in codes],
            "universe": "stocks + ETFs"}


SIZING_ACCOUNT_USD = 5000
SIZING_RISK_PCT = 1.1

def build_rules(stock_screen_py: Optional[Path] = None) -> Dict[str, Any]:
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    import report_filters as rf
    from srs_app import bot_drawings as bd
    C = rf.CONFIG
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "screener": screener_filters(stock_screen_py),
        "core": list(rf.CORE_FILTERS),
        "info": list(rf.WARN_FILTERS),  # not PASS gates (WAIT cancelled 2026-10-26)
        "t": {
            "dollar_vol_min": C["dollar_vol_min"], "avg_vol_days": C["avg_vol_days"],
            "earnings_blackout_days": C["earnings_blackout_days"], "min_weekly_bars": C["min_weekly_bars"],
            "earnings_est_cycle_days": rf.ss.EARN_EST_CYCLE_DAYS,
            "rr_min": C["rr_min"], "red_vol_body_min": C["red_vol_body_min"], "red_vol_avg_days": C["red_vol_avg_days"],
            "inv_hammer_upper_min": C["inv_hammer_upper_min"], "inv_hammer_lower_max": C["inv_hammer_lower_max"],
            "from_above_lookback_w": C["from_above_lookback_w"], "from_above_tol_atr": C["from_above_tol_atr"],
            "near_zone_atr_mult": C["near_zone_atr_mult"], "stale_far_atr": C["stale_far_atr"],
            "tech_newhi_atr": C["tech_newhi_atr"], "tech_ema_min_pct": C["tech_ema_min_pct"],
            "tech_ema_span": C["tech_ema_span"], "tech_recent_weeks": C["tech_recent_weeks"],
            "tech_newhi_lookback_weeks": C["tech_newhi_lookback_weeks"], "tech_flat_r2_max": C["tech_flat_r2_max"],
            "tech_flat_windows": list(C["tech_flat_windows"]), "tech_min_weekly_bars": C["tech_min_weekly_bars"],
            **{k: C[k] for k in ("tech_version", "tech_slow_ema_min_pct", "tech_slow_r2_min", "tech_vrec_ema26_min_pct",
                                 "tech_vrec_ema52_min_pct", "tech_vrec_newhi_atr", "tech_vrec_close_hi156_min",
                                 "tech_vrec_sma_weeks", "tech_vrec_sma_rise_weeks", "tech_cons_ema104_min_pct",
                                 "tech_cons_newhi_atr", "tech_cons_r2_min", "tech_range_r2_max",
                                 "tech_range_ema52_max_pct")},
            "min_smooth_streak_weeks": C["min_smooth_streak_weeks"],
            "reversal_kinds": list(C["reversal_kinds"]),
            "short_float_max_pct": C["short_float_max_pct"], "inst_own_min_pct": C["inst_own_min_pct"],
        },
        # Eyal 2026-10-26: max risk $55 per trade (account $5000 x 1.1%); the app's sizing.ts / dashboard sizing.js
        # defaults match; tradable = weekly ATR(14) per share < max risk
        "sizing": {"account_usd": SIZING_ACCOUNT_USD, "risk_pct": SIZING_RISK_PCT,
                   "max_risk_usd": round(SIZING_ACCOUNT_USD * SIZING_RISK_PCT / 100, 2)},
        "bot": {
            "rule_version": bd.RULE_VERSION, "long_w_bars": bd.LONG_W_BARS, "far_cap_atr": bd.FAR_CAP_ATR,
            "touch_tol_atr": bd.TOUCH_TOL_ATR, "zone_scoring": bd.ZONE_SCORING,
            "touch_lookback_w": bd.TOUCH_LOOKBACK_W, "from_above_lookback_w": bd.FROM_ABOVE_LOOKBACK_W,
            "v5_shift_atr": bd.V5_SHIFT_ATR, "v5_min_gain": bd.V5_MIN_GAIN,
            "entry_below_top_atr": 0.13, "tp_off_atr": 0.09, "sl_band_atr_w": [0.9, 1.2],
        },
    }


if __name__ == "__main__":
    import argparse
    import json
    ap = argparse.ArgumentParser()
    ap.add_argument("--stock-screen", default=None, help="stock_screen.py to read SCREENER_URL from")
    ap.add_argument("--out", default=str(ROOT / "app" / "data" / "rules.json"))
    a = ap.parse_args()
    Path(a.out).write_text(json.dumps(build_rules(Path(a.stock_screen) if a.stock_screen else None), ensure_ascii=False, separators=(",", ":")))
    print("wrote", a.out)
