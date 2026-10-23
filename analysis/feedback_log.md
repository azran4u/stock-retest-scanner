# Bot drawing feedback log

One entry per app feedback item on a bot drawing: what he said, the diagnosis against the candles, and the rule change (or why none was made).

## 2026-10-23 · QCOM · zone wrong (command 3, rule v3d-2026-10-23)

- **Bot drawing:** support zone 142.12–145.41 (pivot 2026-08-07), Long entry 143.35 / SL 124.67 (default 1 weekly ATR) / TP 247.32, R:R 5.57. Price 172.83 on 2026-10-22, so the zone sat 1.74 ATR below price.
- **His correction:** right after the feedback he drew his own zone 173.47–179.04 (start 2025-08-04): the Dec 2025 – Jan 2026 highs / bodies, reclaimed in Sep 2026 (closes 181.97, 201.97, 184.87) and now being retested (lows 171.0, 168.8, 171.1).
- **Diagnosis (two v3d branches):**
  1. *Broken-level check never forgets.* Every level near 173–181 (retest pivots 2025-11-07, 2025-12-19, 2026-01-09) is invalid in v3d because the Jul–Aug 2026 sell-off traded far below their SL (weekly lows 145.2 / 142.1). v3d has no notion of a level that broke and was then reclaimed.
  2. *Pullback anchored to the 26-week high.* `pb_low` = low since the 2026-05-29 high (257.56) = 142.12 and fib 38.2% = 205.35, so the selection score pulled toward the deep August low instead of the current pullback from the 2026-09-25 swing high (205.85).
- **Fix tried (not shipped):** (a) re-validate a broken level after ≥ 2 weekly closes back above its top; (b) re-anchor the pullback to the latest swing high; and fallback-only variants (use a reclaimed level only when the normal pick is > 1–1.5 ATR below price). On his 126 TV drawings: as a general rule mean IoU 0.409 → 0.374 (13 worse, 10 better); best fallback variant 0.409 → 0.404 and it breaks exact matches COP, MA, OXY, WTRG (IoU ≈ 1 → 0) while gaining FITB, INCY, PYPL, UMBF, VMI, WELL. QCOM itself only reaches 176.95–180.62 (IoU 0.29 vs his zone). Conflicts with his earlier drawings → rule left unchanged; asked him in chat.
- **Data actions:** bot zone already rejected by the app. He also dragged the bot Long (57a59897…) to entry 173.11 / SL 154.64 / TP 247.32 (R:R ≈ 4.0), which made it his (`source='user'`, `meta.bot_before` kept); left untouched, as is his zone. No redraw (his own drawing now exists, so the ticker is not a bot candidate).

## 2026-10-23 · CRGY · structure not suitable (command 4, rule v3d-2026-10-23)

- **Bot drawing:** retest zone 9.69–9.93 (pivot 2025-12-05, breakout 2026-02-13), Long entry 9.78 / SL 8.65 (default 1 weekly ATR) / TP 14.89. Price ≈ 13.3 on 2026-10-22, 2.96 ATR above the zone. Zone and Long were already set to `rejected` by the app.
- **Diagnosis:** the levels were not the problem; the ticker should never have been a bot candidate. `f_technical` (v2) only checks (1) the 26-week high vs the prior 2.5-year high (−0.15 ATR, passes the −1 ATR bar) and (2) the 30-week EMA rise over 26 weeks (+16.8%, passes ≥ 8%). Both only see the last half-year, the Jul → Sep 2026 run from 9 to 15.5. Over 3 years CRGY is a wide sideways range: 15.3 (Jan 2025) → 7.2 (Apr 2025) → 7.6–9 through Jan 2026 → 12.8 → 9.1 (Jul 2026) → 15.5 (Sep 2026), a double top at the range ceiling; 2-year return +16%, only 2/5 higher lows, and a log-trend R² of 0.019 (2y) / 0.007 (3y).
- **Fix (shipped, v2.1):** new technical condition: not a multi-year sideways range: log-trend R² ≥ 0.05 over 104 or 156 weeks (`report_filters.CONFIG tech_flat_r2_max / tech_flat_windows`). Golden set (his 131 labelled charts): no golden "up" chart that v2 passed is lost (closest CPAY 0.009 / 0.389 and SJM 0.097 / 0.001 still pass via the other window); accuracy not lower. Universe impact: 4 of 950 technical rows flip (CRGY, HURC, NODK, REPL); none of the other three has a bot drawing. Regression: `tests/test_technical_feedback.py` + fixture `tests/data/feedback_crgy_daily.csv.gz`.
- **Redraw:** none. CRGY is no longer technical (and under the 8-week structure exclusion), so it gets no new bot drawing; no other live bot drawing changes.

## 2026-10-23 · HWC · zone wrong (command 5, rule v3d-2026-10-23)

- **Bot drawing:** support zone 62.44–63.27 (pivot 2026-05-15), Long entry 62.77 / SL 58.94 (default 1 weekly ATR) / TP 78.91, R:R 4.2. Price 73.48 on 2026-10-22, 2.7 ATR above the zone.
- **His correction:** zone 72.53–73.60 (start 2026-01-26: the Feb 2026 high 73.83 / close 72.83, then support Jun–Oct 2026 with weekly lows 72.98, 72.55, 72.97, 72.60, 72.16). He dragged the bot Long to entry 72.92 / SL 69.69 / TP 78.84 (R:R 1.83), which made it his.
- **Diagnosis:** v3d had both levels near 72.5–73.8 (2026-02-06 retest, clarity 19; 2026-08-07 support) but dropped them as broken because of one daily bar: 2026-10-14 O 70.59 / H 71.91 / L 65.47 / C 71.87 on normal volume (741k), with neighbouring lows 71.81 and 72.00. A lone 6-point wick that closed back at the high (most likely a bad print). The same wick set `pullback_low` = 65.47, pulling the pick further down. His SL 69.69 sits above that wick, so he ignores it.
- **Fix (shipped, v3d-2026-10-23c):** level selection runs on spike-cleaned lows (`despike_lows`: low > 3 × 20-day median true range below both neighbours' lows, open and close in the top quarter of the bar → clipped to min(open, close)). The obsolete check (`low_since`) still uses raw lows, per his rule that any wick below the SL breaks a drawing. New HWC golden case + unit test; all earlier golden cases pass. On his 129 TV zone drawings only 4 tickers have such a spike before the read date (EWBC, PRI, ROK, TTEK) and none of their picks changes. Live bot drawings: only ARGX has a spike, its SL moves 769.86 → 769.95 (not redrawn, immaterial).
- **New bot pick for HWC:** support 72.80–72.97 (pivot 2026-08-07), Long entry 72.53 / SL 69.03 / TP 78.94, R:R 1.84, close to his own Long (72.92 / 69.69 / 78.84, R:R 1.83).
- **Data actions:** bot zone was already rejected by the app; his zone and Long left untouched. No bot redraw, since HWC now has his own drawing and is no longer a bot candidate.

## 2026-10-23 · TWST · zone wrong (command 6, rule v3d-2026-10-23)

- **Bot drawing:** retest zone 100.00–105.47 (pivot = the 2026-07-03 high, breakout 2026-08-07), Long entry 101.93 / SL 80.51 (wick low) / TP 191.01, R:R 4.2. Price 135.47 on 2026-10-22, 1.1 ATR above the zone (weekly ATR ≈ 27; TWST ran 25 → 219.7 in 14 months, high 2026-10-09).
- **His correction:** right after the feedback he drew his own zone 115.7–121.2 (start 2026-07-13): the Aug–Sep 2026 base after the 2026-08-07 breakout candle (close 115.67; weekly lows 113.18, 115.28, 120.19 on 2026-09-11; opens 116.91, 121.38), i.e. the last higher low before the October high. No Long, no note.
- **Diagnosis (v3d branch):** the 2026-09-11 swing low (zone 120.02–121.38) is a raw candidate, but its clarity is 2 (only two higher weekly lows / body bottoms to its left before the 2026-08-21 low 115.28), below `s_min` = 3, so it is skipped (and `zone_ok` body-pivot check fails too). Nothing else exists between 105.47 and the price, so the score picked the July high retest. Under the v3e work in progress (reclaim + swing anchor, not yet committed) the pick would be the 2026-08-21 high retest 145.59–155.44, above the current price — also not his zone.
- **Fix tried (not shipped):** let the last swing low before the 26-week high count with clarity 2 (body clarity ≥ 2, not broken). On his drawings it lowers mean IoU (54-drawing fit set 0.343 → 0.328; 114 app TV/user zones 0.261 → 0.258) and breaks CSX (0.81 → 0), PFG (0.40 → 0), RPRX (0.80 → 0); and it still does not reach his TWST zone (scoring keeps 145.59–155.44). Cause is clear but no rule found that fixes TWST without breaking earlier drawings → rule unchanged; asked him in chat. Experiment: `/workspace/twst_fb/exp.py`.
- **Data actions:** bot zone already rejected by the app; the bot Long (fc87c125…, built on that zone) also set to `rejected` so TWST stops counting toward PASS. His zone left untouched. No bot redraw (his own drawing exists). For reference, the v3d Long rules on his zone give entry 117.66 / SL 96.22 (wick low, 0.95 weekly ATR) / TP 191.01, R:R 3.4 — not drawn.

## 2026-10-23 · QCOM follow-up · rule v3e shipped (he approved it in chat)

- **Decision:** he approved the reclaim + swing-anchor change from the QCOM diagnosis and accepted that COP, MA, OXY and WTRG move away from his drawings.
- **Rule (v3e-2026-10-23, `srs_app/bot_drawings.py` `valid_levels` / `pullback_anchor`):**
  - (a) A level that broke (a weekly close or low under its SL) and was then reclaimed by ≥ 2 weekly closes above its top is valid again. Breaks are checked only from the reclaim on.
  - (b) The current pullback is measured from the latest swing high: a high ≥ 2 ATR above the 26-week pullback low, followed by ≥ 1 ATR of decline.
  - Guard (TWST): a reclaimed level the price has fallen back under is skipped (zone bottom ≤ close + 0.3 weekly ATR). Without it, TWST picked 145.59–155.44 above its 135.47 close.
  - Kept: the v3d-c spike-wick cleaning (HWC) and the 3-ATR far cap.
- **QCOM:** retest 176.95–180.62 (pivot 2025-12-19, reclaimed 2026-09-11), entry 178.56 / SL 160.04 / TP 247.32, R:R 3.71.
  - It overlaps his 173.47–179.04 (IoU 0.29). The v3d pick was 142.12–145.41 (IoU 0).
  - Not drawn: his own drawing exists.
- **Regression:**
  - QCOM: golden case with `his_zone` + `test_qcom_reclaimed_level_and_swing_anchor`.
  - TWST: `test_twst_reclaimed_level_above_price_not_picked` (the reclaimed 145.59–155.44 is never picked).
  - QCOM and TWST price history added to the fixture.
  - 30 of 56 golden drawings changed; the old v3d values are kept under `v3d`.
- **Match score** (zone IoU vs his TV drawings at their read dates, production compute):
  - All 126: mean IoU 0.401 → 0.334.
  - His own 99 (owner user): mean IoU 0.331 → 0.334; IoU ≥ 0.3: 45 → 46; IoU ≥ 0.9: 11 → 8.
  - The drop on all 126 comes from the bot's own approved TV drawings, which equal v3d by construction: ALSN, COP, EHC, ELV, EW, MA, OXY, PKG, VLTO, VRSN.
  - His own drawings that got worse: DASH 1.0 → 0, WTRG 0.91 → 0, WAB 0.90 → 0.48, CHE 0.39 → 0, FWONK 0.58 → 0, LFUS 0.60 → 0, ROK 0.46 → 0.
  - His own drawings that got better: FITB 0 → 0.76, IESC 0 → 0.58, INCY 0 → 0.21, PYPL 0 → 0.63, SWK 0 → 0.55, VMI 0 → 0.66, VRTX 0 → 0.77, WELL 0 → 0.51. Also WSM 0.19 → 0.81.
  - Variants tried and not shipped:
    - Guard on every level: 0.321–0.325.
    - Reclaim without the swing anchor: QCOM 166.86–169.98, which does not overlap his zone.
- **Policy change (2026-10-23, from him):** his old TV/user zones may be stale and the bot decides where the zone is, so they are a soft reference, not a regression veto. Score deltas are reported, they do not block a fix.
- **Added with it: `LAST_HL` (TWST, cmd 6):** the last higher low (support pivot) before the latest 26-week high counts with clarity 2 (body clarity ≥ 2, below the price, never broken).
  - TWST: 120.02–121.38 (2026-09-11 swing low), overlapping his 115.7–121.2. Bot Long entry 117.84 / SL 95.30 / TP 191.01, R:R 3.25. Inserted as a Long only; his zone row is untouched. Regression: `test_twst_last_higher_low_counts_with_clarity_2`.
  - Match score with LAST_HL: all 126 0.334 → 0.318; his own 99 0.334 → 0.314; IoU ≥ 0.3 46 → 43. It costs CSX 0.81 → 0, PFG 0.40 → 0, RPRX 0.80 → 0 (old drawings, soft reference).
  - Golden: CSX, PFG, DGX, THG also change (33 of 57 golden drawings now differ from v3d).
  - Live redraws from LAST_HL:
    - PTGX 105.98–107.00 (R:R 4.22) → 130.63–135.78, entry 134.17 / SL 122.50 / TP 154.00, R:R 1.70.
    - RVMD 192.25–193.82 (R:R 1.08) → 178.07–184.43, entry 181.97 / SL 164.65 / TP 208.32, R:R 1.52.
    - SMTC 103.10–114.22 (R:R 3.06) → 115.00–119.63, entry 115.93 / SL 89.41 / TP 192.32, R:R 2.88.
- **Redraw** (live bot drawings whose zone differs between v3d and v3e on the same data): EW, S, SDGR, U, VOD, VRSN, ZM.
  - Old rows were set to `obsolete` with `meta.obsolete.why`; new rows were inserted with rule_version v3e-2026-10-23.
  - TWST: its bot zone and Long were already rejected; see LAST_HL above for the new bot Long.
  - No new candidate gets a drawing: BMO and RY are still > 3 ATR above their nearest level, and DFTX has a data issue.

## 2026-10-23 · rule v4: touch-count zone scoring + recency (his principles, shipped)

- **His principles:**
  - The primary zone criterion is the touch count: how many weekly (and daily) closes or wicks reached the zone.
  - Among viable zones, prefer the support / resistance that is recent in time.
  - His old drawings are a soft reference, not a veto. The bot decides the zone.
- **Rule** (`srs_app/bot_drawings.py`, `ZONE_SCORING = "touches"`):
  - Touch: a bar whose close, low or high lies inside zone ± 0.25 weekly ATR. Consecutive touching bars count as one touch. Weekly touches are counted over the last 52 weeks; daily touches are the tie-breaker.
  - Score = weekly touches − 3 × (ATR from the close down to the zone top) − 6 × (pivot age in years).
  - Pivot clarity ≥ 2 is only a sanity check (it used to be a hard ≥ 3 skip, which dropped TWST). The v3e reclaim / swing anchor / reclaimed-not-above-price guard and the 3-ATR far cap stay.
- **Weights** come from a sweep (lookback 52/104/156 weeks × proximity 1.5/3 × recency 1/3/6 per year). 52 / 3 / 6 is one of only two sets that keep TWST, QCOM and HWC on his current zones, and it has the better soft match on his old drawings of the two. With a 156-week lookback the raw touch count picks old bases (TWST 52.78–54.14, QCOM 150.54–151.55).
- **Validation** (touch counts of the chosen zone; weekly / daily touches, pivot age):
  - TWST: 120.02–121.38. 2 weekly / 2 daily touches, pivot 6 weeks old. His zone is 115.7–121.2. Candidates with more touches were older and further away: 52.78–54.14 has 8 touches but is 97 weeks old and 2.98 ATR below.
  - QCOM: reclaimed 176.95–180.62. 7 / 12 touches. His zone is 173.47–179.04.
  - HWC: 72.80–72.97. 5 / 14 touches, pivot 11 weeks old. His zone is 72.53–73.60.
  - CNO (golden, 2026-10-02): 52.66–53.34 vs his 52.43–53.22. This was far-capped under v3d-b.
- **Soft match vs his old TV drawings** (mean zone IoU at their read dates), v3d → v4:
  - All 126: 0.401 → 0.282.
  - His own 99: 0.331 → 0.258; IoU ≥ 0.3: 45 → 36.
  - Reported, not blocking (policy).
- **Golden:** 39 of 57 stored drawings now differ from v3d (old values kept under `v3d`; `touches_w` stored per row). Tests added: `test_touch_count_and_recency` and `test_touch_meta_stored`.
- **Redraw:** 28 live bot drawings whose zone moved by > 0.5% of price. Old rows were set to `obsolete` with `meta.obsolete.why`, and new rows were inserted under v4: ABCL, ALSN, ARGX, BAP, CLMT, DELL, DXCM, ESS, EW, EWTX, HPE, MSI, OKE, PENG, PKG, RLAY, RS, RVMD, S, SDGR, SMTC, TGTX, TXG, U, UNM, VOD, VRSN, ZM.
- **New drawing:** RY 188.79–191.91 (support pivot 2026-10-09, 2 / 3 touches), entry 190.85 / SL 183.36 / TP 215.83, R:R 3.33. It was far-capped under v3e.
- **TWST:** the bot Long (entry 117.84 / SL 95.30 / TP 191.01) is unchanged, because the v4 pick is the same zone. His zone row is untouched.
