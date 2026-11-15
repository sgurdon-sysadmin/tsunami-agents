#!/usr/bin/env bash
# Rebuilds the Nov 12 2026 WAS@NYG run from scratch and checks it.
# Expected with house rules (FanDuel only, plus-money only): every bet is FanDuel and +100 or longer;
# Isaiah Likely anytime TD scores 37.2% Hit (same as the hand-scored report) at FanDuel +200.
set -e
cd "$(dirname "$0")/.."
R=runs/nfl/2026-11-12_thursday
FEED=${1:-tests/nfl_2026-11-12_feed.json}
rm -f $R/odds.json $R/injuries.json $R/models.json $R/stats.json $R/scored.json $R/events.jsonl
python scripts/feed_to_odds.py $R "$FEED" 2026-11-12T19:40:00-05:00
python tests/thursday_fixture.py $R
python scripts/analyst.py $R
python scripts/scorer.py $R
python scripts/validate.py $R
python - <<'PY'
import json
bets = json.load(open("runs/nfl/2026-11-12_thursday/scored.json"))["bets"]
assert all(b["book"] == "fanduel" and b["price"] >= 100 for b in bets), "house rules broken"
b = next(b for b in bets if b["subject"] == "Isaiah Likely" and b["market"] == "player_anytime_td")
assert b["hit_pct"] == 0.372 and b["price"] == 200, b
print(f"PASS: {len(bets)} bets, all FanDuel plus-money; Likely anytime TD 37.2% at +200 (edge {b['edge']:+})")
PY
