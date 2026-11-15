"""analyst.py — builds stats.json from nflverse data. Plain code, no agent.

What it does (and which part of the prompt it replaces):
  1. Matches player names from odds/injuries/models to nflverse IDs (name + team). Unclear -> 'unmatched'.
  2. Last 20 game logs per player (hit frequency, 1H/2H TD splits, scored team's first TD).
  3. Red-zone role over the player's last 5 games: share of ALL team chances inside the 20 and 5 (TD model),
     share of red-zone TARGETS and red-zone CARRIES separately (the 30% red-zone leader rule), and overall target share.
  4. Finishing: TDs per red-zone opportunity over this season + last season.
  5. Defense ranks by position (Step 1B), TDs allowed by position, and "similar player" records:
     players with 3+ red-zone chances against this defense, and how many scored.
  6. Team splits: first-TD rates, points by quarter and half.

Only games BEFORE the slate's week are used, so backtests are honest.
Usage: python scripts/analyst.py RUN_FOLDER
"""
import sys, pathlib, datetime
import polars as pl
from common import load, save, event, now_et, norm_name

CACHE = pathlib.Path(__file__).resolve().parent.parent / ".cache"
POS = ["QB", "RB", "WR", "TE"]
DEF_CATS = {"QB": ["completions", "passing_yards", "passing_tds", "rushing_yards", "rushing_tds"],
            "RB": ["rushing_yards", "rushing_tds", "receptions", "receiving_yards", "receiving_tds"],
            "WR": ["receptions", "receiving_yards", "receiving_tds"],
            "TE": ["receptions", "receiving_yards", "receiving_tds"]}

def cached(name, seasons, loader):
    """Download once per day, then reuse (the play-by-play file is large)."""
    CACHE.mkdir(exist_ok=True)
    f = CACHE / f"{name}_{'-'.join(map(str, seasons))}_{datetime.date.today()}.parquet"
    if f.exists():
        return pl.read_parquet(f)
    for old in CACHE.glob(f"{name}_{'-'.join(map(str, seasons))}_*.parquet"):
        old.unlink()
    df = loader(seasons)
    df.write_parquet(f)
    return df

def main(folder):
    import nflreadpy as nfl
    man = load(folder, "manifest.json")
    run_id, S, W = man["run_id"], man["season"], man["week"]
    event(folder, run_id, "analyst", "working", "download", "Loading nflverse data")
    before = lambda df: df.filter((pl.col("season") < S) | ((pl.col("season") == S) & (pl.col("week") < W)))
    ps = before(cached("player_stats", [S - 1, S], nfl.load_player_stats).filter(pl.col("season_type") == "REG"))
    pbp = before(cached("pbp", [S - 1, S], nfl.load_pbp).filter(pl.col("season_type") == "REG"))
    ros = cached("rosters", [S], nfl.load_rosters)
    ros = ros.filter(pl.col("week") <= W).sort("week").group_by("gsis_id").last()
    ps = ps.with_columns((pl.col("rushing_tds") + pl.col("receiving_tds")).alias("tds"))

    slate_teams = {t for g in man["games"] for t in (g["away"], g["home"])}
    game_teams = {g["game_id"]: (g["away"], g["home"]) for g in man["games"]}

    # ---------- 1. who do we need? ----------
    odds = load(folder, "odds.json", {"props": []})
    inj = load(folder, "injuries.json", {"players": [], "starters": [], "volume_shifts": []})
    mod = load(folder, "models.json", {"player_models": []})
    wanted = {}
    for p in odds["props"]:
        wanted.setdefault(p["player_name"], set()).update([p["team"]] if p.get("team") else game_teams.get(p["game_id"], ()))
    for p in inj["players"] + inj["starters"]:
        wanted.setdefault(p["player_name"], set()).add(p["team"])
    for v in inj["volume_shifts"]:
        for b in v["beneficiaries"]:
            wanted.setdefault(b["player_name"], set()).add(v["team"])
    for m in mod["player_models"]:
        wanted.setdefault(m["player_name"], set()).update([m["team"]] if m.get("team") else game_teams.get(m["game_id"], ()))

    ros_idx = ros.select(["gsis_id", "full_name", "football_name", "team", "position"]).rows(named=True)
    last_team = ps.sort(["season", "week"]).group_by("player_id").last().select(["player_id", "player_display_name", "team", "position"]).rows(named=True)
    matched, unmatched = {}, []
    for name, teams in wanted.items():
        if any(k in name for k in ("D/ST", "Defense")):
            unmatched.append({"player_name": name, "team": None, "reason": "team defense (not a player)"}); continue
        n = norm_name(name)
        hits = {r["gsis_id"]: r for r in ros_idx if r["team"] in teams and n in (norm_name(r["full_name"] or ""), norm_name(f"{r['football_name']} {(r['full_name'] or '').split(' ', 1)[-1]}"))}
        if not hits:  # traded or roster lag: fall back to stats team
            hits = {r["player_id"]: {"gsis_id": r["player_id"], "full_name": r["player_display_name"], "team": r["team"], "position": r["position"]}
                    for r in last_team if r["team"] in teams and norm_name(r["player_display_name"]) == n}
        if len(hits) == 1:
            r = next(iter(hits.values()))
            matched[r["gsis_id"]] = {"name": name, "team": r["team"], "pos": r["position"], "aliases": sorted({name, r["full_name"]})}
        else:
            unmatched.append({"player_name": name, "team": "/".join(sorted(t for t in teams if t)) or None,
                              "reason": "no roster match" if not hits else f"{len(hits)} players share this name"})

    # ---------- 2. TD plays and per-game TD details ----------
    td = pbp.filter(pl.col("touchdown") == 1).sort(["game_id", "play_id"])
    td_half = td.with_columns(pl.when(pl.col("qtr") <= 2).then(pl.lit("1H")).otherwise(pl.lit("2H")).alias("half")) \
        .group_by(["game_id", "td_player_id", "half"]).agg(pl.len().alias("n"))
    team_first = td.filter(pl.col("td_team").is_not_null()).group_by(["game_id", "td_team"], maintain_order=True).first() \
        .select(["game_id", "td_team", "td_player_id"])
    half_map = {(r["game_id"], r["td_player_id"], r["half"]): r["n"] for r in td_half.rows(named=True)}
    first_set = {(r["game_id"], r["td_player_id"]) for r in team_first.rows(named=True)}

    # red-zone opportunity plays (carries + targets)
    opp = pbp.filter((pl.col("rush_attempt") == 1) | ((pl.col("pass_attempt") == 1) & pl.col("receiver_player_id").is_not_null())) \
        .with_columns(pl.coalesce(["rusher_player_id", "receiver_player_id"]).alias("pid"),
                      (pl.col("rush_attempt") == 1).alias("is_rush"),
                      ((pl.col("touchdown") == 1) & (pl.col("td_player_id") == pl.coalesce(["rusher_player_id", "receiver_player_id"]))).alias("pid_td"))
    rz = opp.filter(pl.col("yardline_100") <= 20)

    # ---------- 3. players ----------
    players = []
    for pid, info in matched.items():
        logs = ps.filter(pl.col("player_id") == pid).sort(["season", "week"]).tail(20)
        last20 = [{"season": r["season"], "week": r["week"], "opp": r["opponent_team"],
                   "pass_yds": r["passing_yards"] or 0, "rush_yds": r["rushing_yards"] or 0, "rec_yds": r["receiving_yards"] or 0,
                   "receptions": r["receptions"] or 0, "targets": r["targets"] or 0, "carries": r["carries"] or 0, "tds": r["tds"] or 0,
                   "tds_1h": half_map.get((r["game_id"], pid, "1H"), 0), "tds_2h": half_map.get((r["game_id"], pid, "2H"), 0),
                   "scored_team_first_td": (r["game_id"], pid) in first_set} for r in logs.rows(named=True)]
        # last 5 games played for the CURRENT team
        g5 = ps.filter((pl.col("player_id") == pid) & (pl.col("team") == info["team"])).sort(["season", "week"]).tail(5)["game_id"].to_list()
        tm_rz = rz.filter(pl.col("game_id").is_in(g5) & (pl.col("posteam") == info["team"]))
        mine = tm_rz.filter(pl.col("pid") == pid)
        in5_t, in5_m = tm_rz.filter(pl.col("yardline_100") <= 5), mine.filter(pl.col("yardline_100") <= 5)
        tm_tg = opp.filter(pl.col("game_id").is_in(g5) & (pl.col("posteam") == info["team"]) & ~pl.col("is_rush"))
        share = lambda a, b: round(a / b, 3) if b else 0.0
        fin = rz.filter(pl.col("pid") == pid)
        players.append({"player_id": pid, "player_name": info["name"], "team": info["team"], "pos": info["pos"] or "",
                        "aliases": info["aliases"], "last20": last20,
                        "red_zone": {"window_games": len(g5),
                                     "carries_in20": mine.filter(pl.col("is_rush")).height, "carries_in5": in5_m.filter(pl.col("is_rush")).height,
                                     "targets_in20": mine.filter(~pl.col("is_rush")).height, "targets_in5": in5_m.filter(~pl.col("is_rush")).height,
                                     "share_in20": share(mine.height, tm_rz.height), "share_in5": share(in5_m.height, in5_t.height),
                                     "rz_target_share": share(mine.filter(~pl.col("is_rush")).height, tm_rz.filter(~pl.col("is_rush")).height),
                                     "rz_carry_share": share(mine.filter(pl.col("is_rush")).height, tm_rz.filter(pl.col("is_rush")).height),
                                     "target_share": share(tm_tg.filter(pl.col("pid") == pid).height, tm_tg.height)},
                        "finishing": {"window": f"{S-1}-{S} regular season", "rz_opps": fin.height,
                                      "rz_tds": int(fin["pid_td"].sum() or 0), "rate": share(int(fin["pid_td"].sum() or 0), fin.height) if fin.height else None}})

    # ---------- 4. league baselines ----------
    pos_map = dict(zip(ps["player_id"].to_list(), ps["position"].to_list()))
    rz_pos = rz.with_columns(pl.col("pid").replace_strict(pos_map, default=None).alias("pos")).filter(pl.col("pos").is_in(POS)) \
        .group_by("pos").agg(pl.col("pid_td").mean().alias("rate"))
    cur = ps.filter(pl.col("season") == S)
    team_games = cur.select(["game_id", "team"]).unique().height
    td_col = {"QB": pl.col("rushing_tds"), "RB": pl.col("tds"), "WR": pl.col("receiving_tds"), "TE": pl.col("receiving_tds")}
    tds_pos = {p: round(float(cur.filter(pl.col("position") == p).select(td_col[p].sum()).item()) / team_games, 3) for p in POS}
    g26 = pbp.filter(pl.col("season") == S)
    finals = g26.group_by("game_id").agg(pl.col("total_home_score").max(), pl.col("total_away_score").max())
    pts = finals["total_home_score"].sum() + finals["total_away_score"].sum()
    td_pts = g26.filter(pl.col("touchdown") == 1).height * 6 + g26.filter(pl.col("extra_point_result") == "good").height \
        + 2 * g26.filter(pl.col("two_point_conv_result") == "success").height
    league = {"rz_td_rate_by_pos": {r["pos"]: round(r["rate"], 3) for r in rz_pos.rows(named=True)},
              "tds_per_team_game_by_pos": tds_pos, "td_points_share": round(td_pts / pts, 3) if pts else 0.78}

    # ---------- 5. defense ----------
    gp = cur.group_by("opponent_team").agg(pl.col("game_id").n_unique().alias("gp"))
    defense, defense_td = [], []
    for p, cols in DEF_CATS.items():
        a = cur.filter(pl.col("position") == p).group_by("opponent_team").agg([pl.col(c).sum() for c in cols] + [td_col[p].sum().alias("tdx")]).join(gp, on="opponent_team")
        for c in cols:
            r = a.with_columns((pl.col(c) / pl.col("gp")).alias("pg")).sort("pg", descending=True).with_row_index("rk", 1)
            vals = r["pg"].to_list()
            for row in r.filter(pl.col("opponent_team").is_in(list(slate_teams))).rows(named=True):
                defense.append({"team": row["opponent_team"], "pos": p, "stat": c, "per_game": round(row["pg"], 2),
                                "total": float(row[c]), "games": row["gp"], "rank": row["rk"], "tied": vals.count(row["pg"]) > 1})
        r = a.with_columns((pl.col("tdx") / pl.col("gp")).alias("pg")).sort("pg", descending=True).with_row_index("rk", 1)
        for row in r.filter(pl.col("opponent_team").is_in(list(slate_teams))).rows(named=True):
            defense_td.append({"team": row["opponent_team"], "pos": p, "tds_per_game": round(row["pg"], 3), "games": row["gp"], "rank": row["rk"]})

    # similar players: 3+ red-zone chances vs this defense this season
    similar = []
    rz_cur = rz.filter(pl.col("season") == S).with_columns(pl.col("pid").replace_strict(pos_map, default=None).alias("pos"))
    pg_ = rz_cur.group_by(["game_id", "week", "defteam", "pid", "pos"]).agg(pl.len().alias("opps"), pl.col("pid_td").sum().alias("tds"))
    names = dict(zip(ps["player_id"].to_list(), ps["player_display_name"].to_list()))
    for d in sorted(slate_teams):
        for p in POS:
            sub = pg_.filter((pl.col("defteam") == d) & (pl.col("pos") == p) & (pl.col("opps") >= 3)).sort("week")
            similar.append({"team": d, "pos": p, "min_rz_opps": 3, "players": sub.height, "scored": int((sub["tds"] > 0).sum()),
                            "examples": [f"Wk{r['week']} {names.get(r['pid'], r['pid'])}: {r['opps']} RZ chances, {r['tds']} TD" for r in sub.rows(named=True)][-6:]})

    # ---------- 6. teams ----------
    first = td.group_by("game_id", maintain_order=True).first().select(["game_id", "season", "home_team", "away_team", "td_team"])
    sc = g26.select(["game_id", "home_team", "away_team", "qtr", "total_home_score", "total_away_score"])
    teams_out = []
    for t in sorted(slate_teams):
        rates = {}
        for s_ in (S, S - 1):
            g = first.filter(((pl.col("home_team") == t) | (pl.col("away_team") == t)) & (pl.col("season") == s_))
            rates[s_] = round(g.filter(pl.col("td_team") == t).height / g.height, 3) if g.height else None
        agg = {"q1f": 0, "q1a": 0, "h1f": 0, "h1a": 0, "h2f": 0, "h2a": 0}; n = 0
        for gid in sc.filter((pl.col("home_team") == t) | (pl.col("away_team") == t))["game_id"].unique().to_list():
            g = sc.filter(pl.col("game_id") == gid); home = g["home_team"][0] == t
            at = lambda q: (g.filter(pl.col("qtr") <= q)["total_home_score"].max() or 0, g.filter(pl.col("qtr") <= q)["total_away_score"].max() or 0)
            q1, h1, fn = at(1), at(2), at(9)
            i = 0 if home else 1; n += 1
            agg["q1f"] += q1[i]; agg["q1a"] += q1[1 - i]; agg["h1f"] += h1[i]; agg["h1a"] += h1[1 - i]
            agg["h2f"] += fn[i] - h1[i]; agg["h2a"] += fn[1 - i] - h1[1 - i]
        avg = lambda k: round(agg[k] / n, 2) if n else 0
        teams_out.append({"team": t, "first_td_rate_this": rates[S], "first_td_rate_last": rates[S - 1],
                          "pts_1q_for": avg("q1f"), "pts_1q_against": avg("q1a"), "pts_1h_for": avg("h1f"),
                          "pts_1h_against": avg("h1a"), "pts_2h_for": avg("h2f"), "pts_2h_against": avg("h2a")})

    last_wk = int(cur["week"].max()) if cur.height else 0
    out = {"run_id": run_id, "sport": man["sport"], "built_at": now_et(), "data_through": {"season": S, "week": last_wk},
           "players": players, "defense": defense, "teams": teams_out, "unmatched": unmatched,
           "league": league, "defense_td": defense_td, "defense_vs_similar": similar}
    save(folder, "stats.json", out)
    event(folder, run_id, "analyst", "handoff", "stats", f"{len(players)} players matched, {len(unmatched)} unmatched", "stats.json")
    print(f"stats.json: {len(players)} players, {len(unmatched)} unmatched, data through {S} wk {last_wk}")
    for u in unmatched:
        print("  unmatched:", u)

if __name__ == "__main__":
    main(sys.argv[1])
