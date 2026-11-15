# Tsunami Bets — Agent Contracts (Step 2)

Status: **v0.2** (Nov 15 2026). v0.2 added: per-player `why` on Medic boosts; red-zone target/carry shares, finishing, league baselines, defense TDs by position and similar-player records in stats.json; `prices_by_book`, `model_check`, `support`, `flags` on each scored bet; the prediction ledger. The schemas in `schemas/` are the source of truth; this page explains them.

## Run folder

```
runs/{sport}/{YYYY-MM-DD}_{slate}/      e.g. runs/nfl/2026-11-15_sunday/
  manifest.json    Manager     slate, games, agent statuses
  odds.json        Scout       game lines + props, one side per row
  injuries.json    Medic       statuses, starting QBs, trades, volume shifts, weather etc.
  models.json      Oracle      published model numbers (win %, projections, TD %)
  stats.json       analyst.py  game logs, red zone, defense ranks, team splits
  scored.json      scorer.py   every bet's Hit %, Implied %, Edge, boards, parlays
  audit.json       Auditor     problems found; "block" removes a bet
  events.jsonl     everyone    one line per step (feeds the visualization later)
  report.md        Publisher   the Notion report text
```

## Who reads what

| Writer | Reads | Writes |
|---|---|---|
| Manager | schedule | manifest.json |
| Scout | manifest | odds.json |
| Medic | manifest | injuries.json |
| Oracle | manifest | models.json |
| analyst.py | manifest, odds, injuries | stats.json |
| scorer.py | everything above | scored.json |
| Auditor | everything above | audit.json |
| Publisher | scored, audit, manifest, injuries | report.md → Notion + email |

Scout, Medic and Oracle run in parallel. Everything after them runs in order.

## Rules every agent follows

1. **Write only your own file.** Never edit another agent's file.
2. **Match the schema.** `python scripts/validate.py runs/...` must pass. The Manager runs it after each step and logs any failure in Run notes.
3. **One row = one side of one market at one book.** Never merge books. Same-book pairs are matched later by (game, player, market, line, book), which is how no-vig math gets both sides from the same book.
4. **Every number carries a source** with `url`, `fetched_at` and `verbatim` (`false` = from a summary or unlabeled table, so treat it as unverified).
5. **Agents never do math.** They copy numbers. analyst.py and scorer.py compute everything.
6. **Names, not IDs.** Agents write player names plus team. analyst.py turns names into nflverse `player_id`s; anything ambiguous goes to `unmatched` and is never guessed.
7. **Banned sources:** Kalshi, Polymarket, Novig and any exchange. The `book` list in the schema has no slot for them, so a file containing them fails validation.
8. **Failures are data.** A source that doesn't load goes in `failures`, not silence.
9. **IDs:** `run_id` = `nfl_2026-11-15_sunday`. NFL `game_id` = `2026_10_WAS_NYG` (season_week_AWAY_HOME, nflverse style). NBA `game_id` = `20261115_BOS_NYK`. Times are ISO 8601 with offset.

## File notes

- **odds.json**: `feed` records how old the odds file is and which markets it held (Run notes come from here). `lines_needed` is the Scout's list of good spots with no verified price.
- **injuries.json**: `volume_shifts` is where the 🔺 Injury Boost comes from: the Medic names who gains volume and by how much (0–6 points). `external` holds weather, travel, short week and so on (−3 to +3).
- **models.json**: `label_confirmed: false` when the page is unclear, such as anytime vs. first TD on Dimers. scorer.py prints a flag on those.
- **stats.json**: `last20` per player is what hit frequency is counted from. `defense` holds the Step 1B rankings. `teams` holds first-TD rates and points by quarter and half.
- **scored.json**: `adjustments` lists every change to Hit % with its type (research ±5 cap, injury, external ±3 cap) and reason. `boards` is decided by code using the README thresholds.
- **audit.json**: checks include wrong team, OUT player with a prop, stale line, projection that conflicts with recent games, price mismatch, banned source, small sample, missing pair. `block` drops the bet; `warn` prints next to it.
- **events.jsonl**: `{t, run_id, agent, status, step, msg, file}`, append-only. Statuses: idle, working, handoff, done, error.

## Scripts (step 3)

| Script | Reads | Writes | Notes |
|---|---|---|---|
| `feed_to_odds.py` | manifest + odds feed snapshot | odds.json | Free conversion of the Odds API feed; the Scout only adds what the feed lacks |
| `analyst.py` | manifest, odds, injuries, models | stats.json | Uses only games before the slate's week; caches nflverse downloads in `.cache/` for the day |
| `scorer.py` | everything above | scored.json + `ledger/predictions.csv` | All tunable numbers are in `CONFIG` at the top |
| `validate.py` | a run folder | — | Checks every file against the schemas |
| `config/settings.json` | — | — | House rules: which books, minimum price. Change rules here only |
| `build_schemas.py` | — | schemas/ | Edit this to change a format, then run it |

Test: `bash tests/run_thursday.sh` rebuilds the Nov 12 WAS@NYG run and must print `PASS` (all bets FanDuel plus-money; Likely anytime TD 37.2% at +200).

## Decisions (locked)

1. **Research adjustments (±5) are fixed rules in scorer.py:** defense rank for that stat vs. the position (top-5 +2, top-10 +1, bottom-10 −1, bottom-5 −2, flipped for unders); **red-zone leader** = 30%+ of the team's red-zone targets OR carries over the last 5 games (any position, at least 3 chances) → +2.
2. **Touchdown bets:** if a published model (Dimers etc.) exists it's the base and the rules above apply. If not, the **TD opportunity model** is the base (blended 50/50 with the book, labeled ESTIMATE), and the red-zone and matchup rules are NOT added again (they're inside the model). The TD model is also shown next to Dimers on every bet (`model_check`) for calibration.
3. **TD opportunity model:** team expected TDs (implied total × TD share of points ÷ 7) × player's share of red-zone chances (last 5) + long-TD credit from target share, × matchup (defense TDs allowed to the position vs. league, half-weighted) × finishing (red-zone TD rate vs. league over two seasons, half-weighted, needs 8+ chances) → Poisson.
4. **Injury boosts:** the Medic proposes 0–6 points per player with a written `why`; scorer.py applies them as-is.
5. **External factors (±3):** only when concretely reported.
6. **Hit frequency:** last 5 games, display only.
7. **History:** every run folder is kept; every scored bet goes into `ledger/predictions.csv` for grading.
8. **House rules (Nov 15 2026): FanDuel only, plus-money only.** Set in `config/settings.json` (`books`, `min_price`), read by every script and agent. Only FanDuel prices are collected, scored, shown, or used in parlays. Only +100 or longer is shown or considered. A minus price is still read when it is the other side of a FanDuel pair (needed for no-vig math) and a minus anytime TD is scored quietly to feed that player's 2+ TD number, but neither is ever shown. The Anchors board is effectively retired while this rule is on.
