# Tsunami Bets — Agent Split Plan (progress tracker)

Goal: split the single-pass report into agents that hand off files, so it runs faster, costs less, and errors are caught at each handoff. Then let the system learn week to week until its TD probabilities track published models (Dimers) and real outcomes by ~week 7–8 of tracking. Visualization comes last.

| Step | What | Status |
|---|---|---|
| 1 | Create `tsunami-agents` GitHub repo (public): agents/, schemas/, scripts/, examples/, runs/ | ✅ Done (Nov 15 2026) |
| 2 | File contracts (schemas + validator + examples) | ✅ v0.2 (Nov 15 2026) |
| 3 | Math scripts: `feed_to_odds.py`, `analyst.py`, `scorer.py` (TD opportunity model + prediction ledger) + `config/settings.json` house rules | ✅ Built and tested (Nov 15 2026). Re-delivered with FanDuel-only / plus-only rules; user to upload |
| 3b | Memory: player notebooks, `grader.py` | ⏳ After step 7 (ledger already writes from step 3) |
| 4 | Agent briefs: Scout, Medic, Oracle, Auditor, Publisher | ⏳ Next |
| 5 | Manager (orchestrator) prompt | ⏳ |
| 6 | Side-by-side test vs. current prompt on a live game (time + usage) | ⏳ |
| 7 | Swap the scheduled task (only after user review) | ⏳ |
| 8 | Calibration: weekly compare model vs Dimers vs results; tune CONFIG | ⏳ (needs a few weeks of graded runs) |
| Later | Visualization (underwater lab, robots per agent, replay from events.jsonl, then Supabase live) | Parked |

## Pipeline
Manager → feed_to_odds.py → [Scout ‖ Medic ‖ Oracle] → analyst.py → scorer.py → Auditor → Publisher → (after games) grader.py

## House rules (config/settings.json)
- **FanDuel only** (no other sportsbooks for now).
- **Plus-money only** (+100 and longer). Minus bets are never shown or recommended; a minus price is only read as the other side of a FanDuel pair for no-vig math, and minus anytime TDs are scored quietly to feed 2+ TD numbers.
- Consequences: Anchors board retired while the rule is on; parlays are FanDuel-only plus-money legs; yardage props need FanDuel alternate lines (e.g. 60+, 80+ yards) to produce plus prices — candidate to add `player_reception_yds_alternate` etc. to the odds feed (already on the Nov 10 review list).

## Decisions (locked)
See `pipeline/CONTRACTS.md` → "Decisions (locked)". Summary:
- Fixed research rules (±5): defense rank by stat/position; red-zone leader = 30%+ of team red-zone targets OR carries, last 5 games, any position, 3+ chances.
- TD bets: Dimers base when available (+ rules); otherwise TD opportunity model blended 50/50 with book (ESTIMATE), no double counting. TD model always shown next to Dimers for calibration.
- Medic proposes 0–6 injury boost points per player with written reasoning.
- External ±3 only when reported. Hit frequency = last 5 games (display only).
- Every run folder kept; every scored bet logged to ledger/predictions.csv.
- Repo public; API key stays in GitHub Secrets.

## Step 3 test findings (Nov 12 WAS@NYG backtest)
- All books: Likely ATD 37.2% / +4.4 at DK +205 → Plus board (matches hand report).
- FanDuel-only, plus-only: 45 bets; Likely ATD 37.2% at FD +200 → edge +3.9, near miss (needs +4); Van Jefferson ATD +850 long shot (role based on only 2 games, flagged); Likely 2+ TDs +1800 edge +6.7 but Hit 12% (<15%).
- TD model vs Dimers: Skattebo 39.5 vs 36.9, Nabers 27.2 vs 33.8, White 31.9 vs 30.2, Diggs 26.3 vs 28.4, Daniels 23.3 vs 24.2, Likely 49.1 vs 33.2.
- Flags working: Ekeler projection vs last-5 avg; small-window roles.
