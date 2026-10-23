# Bot drawing feedback log

One entry per app feedback item on a bot drawing: what he said, the diagnosis against the candles, and the rule change (or why none was made).

## 2026-10-23 · QCOM · zone wrong (command 3, rule v3d-2026-10-23)

- **Bot drawing:** support zone 142.12–145.41 (pivot 2026-08-07), Long entry 143.35 / SL 124.67 (default 1 weekly ATR) / TP 247.32, R:R 5.57. Price 172.83 on 2026-10-22, so the zone sat 1.74 ATR below price.
- **His correction:** right after the feedback he drew his own zone 173.47–179.04 (start 2025-08-04): the Dec 2025 – Jan 2026 highs / bodies, reclaimed in Sep 2026 (closes 181.97, 201.97, 184.87) and now being retested (lows 171.0, 168.8, 171.1).
- **Diagnosis (two v3d branches):**
  1. *Broken-level check never forgets.* Every level near 173–181 (retest pivots 2025-11-07, 2025-12-19, 2026-01-09) is invalid in v3d because the Jul–Aug 2026 sell-off traded far below their SL (weekly lows 145.2 / 142.1). v3d has no notion of a level that broke and was then reclaimed.
  2. *Pullback anchored to the 26-week high.* `pb_low` = low since the 2026-05-29 high (257.56) = 142.12 and fib 38.2% = 205.35, so the selection score pulled toward the deep August low instead of the current pullback from the 2026-09-25 swing high (205.85).
- **Fix tried (not shipped):** (a) re-validate a broken level after ≥ 2 weekly closes back above its top; (b) re-anchor the pullback to the latest swing high; and fallback-only variants (use a reclaimed level only when the normal pick is > 1–1.5 ATR below price). On his 126 TV drawings: as a general rule mean IoU 0.409 → 0.374 (13 worse, 10 better); best fallback variant 0.409 → 0.404 and it breaks exact matches COP, MA, OXY, WTRG (IoU ≈ 1 → 0) while gaining FITB, INCY, PYPL, UMBF, VMI, WELL. QCOM itself only reaches 176.95–180.62 (IoU 0.29 vs his zone). Conflicts with his earlier drawings → rule left unchanged; asked him in chat.
- **Data actions:** bot zone already rejected by the app; the bot Long built on it (57a59897…) set to `rejected` so it no longer counts toward PASS. His zone left untouched. No redraw (his own drawing now exists, so the ticker is not a bot candidate).
