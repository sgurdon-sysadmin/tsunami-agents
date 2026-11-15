# Tsunami Bets — Agent Contracts (Step 2)

Status: **DRAFT v0.1 — under review** (Nov 15 2026). The schemas in `schemas/` are the source of truth; this page explains them.

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

## Open decisions (to settle before step 3)

1. **Research adjustments (the ±5).** Option A: scorer.py applies fixed rules from stats.json, e.g. "defense top-5 vs. position → +2; top red-zone share → +2". Option B: a judgment step writes them. *Recommendation: A, so it's repeatable and the Auditor can check it.*
2. **Who sets injury boost points?** Draft: the Medic proposes 0–6 in `volume_shifts`; scorer.py applies them as-is.
3. **Runs history.** Commit every run folder to the repo (good for results tracking later) or keep only the latest?
