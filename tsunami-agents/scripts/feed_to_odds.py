"""Turn the tsunami-odds feed snapshot into odds.json (the Scout's file) with plain code.

Why: the feed is already structured, so converting it costs nothing. The Scout agent then
only researches what the feed doesn't have (game specials, receptions, 1H TD, missing games).

Usage: python scripts/feed_to_odds.py RUN_FOLDER path/to/nfl_latest.json [AS_OF_ISO_TIME for backtests]
Writes RUN_FOLDER/odds.json. The Scout appends extra rows to the same file afterwards.
"""
import sys, json, datetime
from common import load, save, event, now_et, settings, NFL_TEAMS, BOOK_KEYS

GAME_MARKETS = {"h2h", "spreads", "totals", "h2h_h1", "spreads_h1", "totals_h1", "h2h_q1", "spreads_q1",
                "totals_q1", "team_totals"}

def side_of(outcome_name, teams):
    n = outcome_name.lower()
    if n in ("over", "under", "yes", "no"):
        return n
    return teams.get(outcome_name, outcome_name)

def main(folder, feed_path, as_of=None):
    man = load(folder, "manifest.json")
    feed = json.loads(open(feed_path).read())
    run_id = man["run_id"]
    event(folder, run_id, "scout", "working", "feed", "Converting odds feed")
    allowed = set(settings()["books"])  # only collect books named in config/settings.json
    by_teams = {(g["away"], g["home"]): g["game_id"] for g in man["games"]}
    fetched = feed.get("fetched_at")
    age = None
    if fetched:
        t = datetime.datetime.fromisoformat(fetched.replace("Z", "+00:00"))
        ref = datetime.datetime.fromisoformat(as_of) if as_of else datetime.datetime.now(datetime.timezone.utc)
        age = round((ref - t).total_seconds() / 60)
    src = {"name": "tsunami-odds feed (The Odds API)", "url": "https://github.com/sgurdon-sysadmin/tsunami-odds",
           "fetched_at": (fetched or now_et()).replace("Z", "+00:00"), "verbatim": True}
    game_lines, props, seen = [], [], set()
    for g in feed.get("games", []):
        away, home = NFL_TEAMS.get(g["away_team"]), NFL_TEAMS.get(g["home_team"])
        gid = by_teams.get((away, home))
        if not gid:
            continue  # not in this run's slate
        seen.add(gid)
        teams = {g["away_team"]: away, g["home_team"]: home}
        for bm in g.get("bookmakers", []):
            book = BOOK_KEYS.get(bm["key"])
            if not book or book not in allowed:
                continue
            for m in bm.get("markets", []):
                if m["key"] not in GAME_MARKETS:
                    continue
                for o in m["outcomes"]:
                    team = teams.get(o.get("description")) if m["key"] == "team_totals" else None
                    game_lines.append({"game_id": gid, "book": book, "market": m["key"],
                                       "side": side_of(o["name"], teams), "team": team,
                                       "point": o.get("point"), "price": int(o["price"]), "label": None, "source": src})
        for bm in g.get("props", []):
            book = BOOK_KEYS.get(bm["key"])
            if not book or book not in allowed:
                continue
            for m in bm.get("markets", []):
                for o in m["outcomes"]:
                    side = o["name"].lower()
                    if side not in ("over", "under", "yes"):
                        continue
                    props.append({"game_id": gid, "player_name": o.get("description", ""), "team": None,
                                  "market": m["key"], "side": side, "line": o.get("point"),
                                  "price": int(o["price"]), "book": book,
                                  "alt": m["key"].endswith("_alternate"), "source": src})
    missing = [g["game_id"] for g in man["games"] if g["game_id"] not in seen and g["status"] == "scheduled"]
    out = {"run_id": run_id, "sport": man["sport"], "written_at": now_et(),
           "feed": {"fetched_at": fetched, "age_minutes": age, "stale": (age is None or age > 360) or bool(missing),
                    "games_missing": missing, "markets_in_feed": feed.get("prop_markets", "").split(",") if isinstance(feed.get("prop_markets"), str) else feed.get("prop_markets", [])},
           "game_lines": game_lines, "props": props, "lines_needed": [], "failures": []}
    save(folder, "odds.json", out)
    event(folder, run_id, "scout", "handoff", "feed", f"{len(game_lines)} game lines, {len(props)} props from feed", "odds.json")
    print(f"odds.json: {len(game_lines)} game lines, {len(props)} props, missing games: {missing or 'none'}, age {age} min")

if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2], sys.argv[3] if len(sys.argv) > 3 else None)
