"""scorer.py — turns odds + injuries + models + stats into scored.json. Plain code, no agent.

Order of work for every bet:
  1. Group prices: one bet = (game, player/team, market, side, line). Keep every book's price.
  2. Starting Hit % (base): model > no-vig (both sides, same book) > ESTIMATE.
     TD bets with no model use the TD opportunity model, blended with the book.
  3. Adjustments, each with a reason: research (fixed rules, cap ±5), injury boost (Medic), external (cap ±3).
  4. Implied %, Edge, hit frequency (last 5 games), boards, parlays, near misses.
  5. Append every bet to ledger/predictions.csv so results can be graded later.

All tunable numbers live in CONFIG so calibration can change them without touching the logic.
Usage: python scripts/scorer.py RUN_FOLDER
"""
import sys, csv, math, pathlib, datetime, itertools
from statistics import NormalDist, mean
from common import (load, save, event, now_et, settings, implied, decimal, american, no_vig, poisson_any,
                    poisson_2plus, lam_from_any, normal_over, norm_name)

CONFIG = {
    "boards": {"plus": {"min_price": 100, "min_edge": 4, "min_hit": 0.30},
               "long_shot": {"min_price": 300, "min_edge": 5, "min_hit": 0.15},
               "anchor": {"min_hit": 0.70, "min_edge": 0}},
    "sd": {"pass_yds": (0.25, 45), "rush_yds": (0.45, 15), "reception_yds": (0.55, 15), "rush_reception_yds": (0.45, 18)},
    "game_sd": {"margin": 13.5, "total": 10.0, "team_total": 7.0},
    "research_cap": 5, "external_cap": 3,
    "rules": {"def_top5": 2, "def_top10": 1, "def_bottom5": -2, "def_bottom10": -1,
              "rz_leader_share": 0.30, "rz_leader_min_chances": 3, "rz_leader_points": 2},
    "td_model": {"rz_td_share": 0.75,        # share of team TDs that start inside the 20
                 "long_td_pass_share": 0.60,  # share of other TDs that are passing TDs
                 "matchup_weight": 0.5, "finishing_weight": 0.5, "finishing_min_opps": 8,
                 "book_blend": 0.5},          # ESTIMATE = blend * book + (1 - blend) * TD model
    "estimate_book_blend": 0.5,               # yardage ESTIMATE when no projection and no pair
    "near_miss_min_edge": 2.0,
}
MARKET_INFO = {  # market -> (section, stat key in last20, defense stat)
    "player_pass_yds": ("passing_yds", "pass_yds", "passing_yards"),
    "player_rush_yds": ("rush_rec_yds", "rush_yds", "rushing_yards"),
    "player_reception_yds": ("rush_rec_yds", "rec_yds", "receiving_yards"),
    "player_receptions": ("rush_rec_yds", "receptions", "receptions"),
    "player_rush_reception_yds": ("rush_rec_yds", "rush_rec", "receiving_yards"),
}
MODEL_STAT = {"player_pass_yds": "pass_yds", "player_rush_yds": "rush_yds", "player_reception_yds": "rec_yds",
              "player_receptions": "receptions", "player_rush_reception_yds": "rush_rec_yds"}
SD_KEY = {"player_pass_yds": "pass_yds", "player_rush_yds": "rush_yds", "player_reception_yds": "reception_yds",
          "player_rush_reception_yds": "rush_reception_yds"}
SIGN = {"over": 1, "yes": 1, "under": -1}

def kickoff_slot(ko):
    t = datetime.datetime.fromisoformat(ko)
    if t.weekday() == 6:
        return "Sunday early" if t.hour < 14 else "Sunday late"
    return "Weekday"

def main(folder):
    man = load(folder, "manifest.json"); odds = load(folder, "odds.json"); stats = load(folder, "stats.json")
    inj = load(folder, "injuries.json", {"players": [], "volume_shifts": [], "external": []})
    mod = load(folder, "models.json", {"game_models": [], "player_models": []})
    run_id = man["run_id"]; C = CONFIG
    H = settings(); BOOKS, MIN_PRICE = H["books"], H["min_price"]  # house rules (config/settings.json)
    odds = {**odds, "props": [r for r in odds["props"] if r["book"] in BOOKS],
            "game_lines": [r for r in odds["game_lines"] if r["book"] in BOOKS]}
    event(folder, run_id, "scorer", "working", "score", "Scoring bets")
    games = {g["game_id"]: g for g in man["games"]}
    players = {(norm_name(a), p["team"]): p for p in stats["players"] for a in p["aliases"]}
    by_name = {}
    for p in stats["players"]:
        for a in p["aliases"]:
            by_name.setdefault(norm_name(a), []).append(p)
    def find_player(name, team, gid):
        n = norm_name(name)
        if team and (n, team) in players:
            return players[(n, team)]
        cands = [p for p in by_name.get(n, []) if p["team"] in (games[gid]["away"], games[gid]["home"])]
        return cands[0] if len(cands) == 1 else None
    status = {(norm_name(p["player_name"]), p["team"]): p["status"] for p in inj["players"]}
    boosts = {}
    for v in inj["volume_shifts"]:
        for b in v["beneficiaries"]:
            boosts[(norm_name(b["player_name"]), v["team"])] = (b["boost_points"], f"{v['out_player']} out: {b['why']}")
    defense = {(d["team"], d["pos"], d["stat"]): d for d in stats["defense"]}
    def_td = {(d["team"], d["pos"]): d for d in stats["defense_td"]}
    similar = {(d["team"], d["pos"]): d for d in stats["defense_vs_similar"]}
    L = stats["league"]

    # ---------- team expected points ----------
    def implied_totals(gid):
        g = games[gid]; lines = [x for x in odds["game_lines"] if x["game_id"] == gid]
        for book in BOOKS:
            sp = [x for x in lines if x["book"] == book and x["market"] == "spreads" and x["side"] == g["home"]]
            to = [x for x in lines if x["book"] == book and x["market"] == "totals" and x["side"] == "over"]
            if sp and to:
                home_spread, total = sp[0]["point"], to[0]["point"]
                return {g["home"]: total / 2 - home_spread / 2, g["away"]: total / 2 + home_spread / 2, "book": book}
        gm = [m for m in mod["game_models"] if m["game_id"] == gid and m["proj_home_pts"] is not None]
        if gm:
            return {g["home"]: gm[0]["proj_home_pts"], g["away"]: gm[0]["proj_away_pts"], "book": "model"}
        return None
    team_pts = {gid: implied_totals(gid) for gid in games}

    # ---------- TD opportunity model ----------
    def td_model(p, gid):
        tp = team_pts.get(gid)
        if not tp or p["pos"] not in L["tds_per_team_game_by_pos"]:
            return None, None
        T = C["td_model"]; rz = p["red_zone"]
        opp_team = games[gid]["home"] if p["team"] == games[gid]["away"] else games[gid]["away"]
        team_tds = tp[p["team"]] * L["td_points_share"] / 7
        lam0 = team_tds * T["rz_td_share"] * rz["share_in20"] + team_tds * (1 - T["rz_td_share"]) * T["long_td_pass_share"] * rz["target_share"]
        d = def_td.get((opp_team, p["pos"])); lg = L["tds_per_team_game_by_pos"][p["pos"]]
        m = min(max(1 + T["matchup_weight"] * ((d["tds_per_game"] / lg) - 1), 0.6), 1.6) if d and lg else 1.0
        f = 1.0; fin = p["finishing"]; lr = L["rz_td_rate_by_pos"].get(p["pos"])
        if fin["rz_opps"] >= T["finishing_min_opps"] and fin["rate"] is not None and lr:
            f = min(max(1 + T["finishing_weight"] * (fin["rate"] / lr - 1), 0.7), 1.4)
        lam = lam0 * m * f
        detail = (f"TD model: team {tp[p['team']]:.1f} pts → {team_tds:.2f} TDs; {rz['share_in20']:.0%} of RZ chances, "
                  f"{rz['target_share']:.0%} of targets (last {rz['window_games']}); matchup ×{m:.2f}; finishing ×{f:.2f}; λ={lam:.2f}")
        return lam, detail

    def model_prob(name, team, gid, stat):
        vals = [m["value"] for m in mod["player_models"] if m["game_id"] == gid and m["stat"] == stat
                and norm_name(m["player_name"]) == norm_name(name) and (not m.get("team") or not team or m["team"] == team)]
        srcs = [m for m in mod["player_models"] if m["game_id"] == gid and m["stat"] == stat and norm_name(m["player_name"]) == norm_name(name)]
        return (mean(vals), srcs) if vals else (None, [])

    # ---------- group prices into bets ----------
    groups = {}
    for r in odds["props"]:
        if r["market"] == "player_tds_over" and r["line"] == 0.5 and r["side"] == "over":
            r = {**r, "market": "player_anytime_td", "side": "yes", "line": None}  # same bet, different label
        key = (r["game_id"], r["player_name"], r["market"], r["side"], r["line"])
        groups.setdefault(key, {"rows": [], "team": r.get("team")})["rows"].append(r)
    for r in odds["game_lines"]:
        subj = r["team"] or ("Game" if r["side"] in ("over", "under") else r["side"])
        key = (r["game_id"], subj, r["market"], r["side"], r["point"])
        groups.setdefault(key, {"rows": [], "team": r.get("team") or (r["side"] if r["side"] not in ("over", "under", "yes", "no") else None), "game": True})["rows"].append(r)

    def other_side(key, book):
        gid, subj, market, side, line = key
        opp = {"over": "under", "under": "over"}.get(side)
        if market in ("h2h", "h2h_h1", "h2h_q1"):
            g = games[gid]; opp_team = g["home"] if side == g["away"] else g["away"]
            k2 = (gid, opp_team, market, opp_team, None)
        elif market in ("spreads", "spreads_h1", "spreads_q1"):
            g = games[gid]; opp_team = g["home"] if side == g["away"] else g["away"]
            k2 = (gid, opp_team, market, opp_team, -line if line is not None else None)
        elif opp:
            k2 = (gid, subj, market, opp, line)
        else:
            return None
        for r in groups.get(k2, {"rows": []})["rows"]:
            if r["book"] == book:
                return r["price"]
        return None

    bets, anytime_final = [], {}
    # anytime TDs first (2+ TD bets need the final anytime number)
    order = sorted(groups.items(), key=lambda kv: 0 if (kv[0][2] == "player_anytime_td" or (kv[0][2] == "player_tds_over" and kv[0][4] == 0.5)) else 1)
    for n, (key, grp) in enumerate(order):
        gid, subj, market, side, line = key
        if gid not in games or games[gid]["status"] != "scheduled":
            continue
        rows = grp["rows"]; prices = {}
        for r in rows:
            if r["book"] not in prices or decimal(r["price"]) > decimal(prices[r["book"]]):
                prices[r["book"]] = r["price"]
        book = next(b for b in BOOKS if b in prices)  # first preferred book that prices this bet
        price = prices[book]; best_b = max(prices, key=lambda b: decimal(prices[b]))
        # House rule: plus-money only. Minus bets are still scored quietly (a minus anytime TD feeds the
        # player's 2+ TD number, and a minus side gives the "other side" for no-vig math) but never shown.
        hidden = price < MIN_PRICE
        is_game = grp.get("game", False)
        flags, support, adjustments = [], [], []
        if any(not r["source"]["verbatim"] for r in rows):
            flags.append("price from a summary or unlabeled table — verify")
        p = None if is_game else find_player(subj, grp["team"], gid)
        team = p["team"] if p else grp["team"]
        g = games[gid]; opp = (g["home"] if team == g["away"] else g["away"]) if team in (g["away"], g["home"]) else None
        is_any = market == "player_anytime_td" or (market == "player_tds_over" and line == 0.5)
        is_multi = market == "player_tds_over" and line and line >= 1.5
        base = method = detail = None; model_check = None

        # ---- 1. starting Hit % ----
        if is_game:
            gm = [m for m in mod["game_models"] if m["game_id"] == gid]
            if market == "h2h" and gm and gm[0]["win_prob_home"] is not None:
                base = gm[0]["win_prob_home"] if side == g["home"] else gm[0]["win_prob_away"]
                method, detail = "model", f"{gm[0]['source']} win probability"
            elif market in ("spreads", "totals") and gm and gm[0]["proj_home_pts"] is not None and line is not None:
                ph, pa = gm[0]["proj_home_pts"], gm[0]["proj_away_pts"]
                if market == "totals":
                    po = normal_over(ph + pa, C["game_sd"]["total"], line); base = po if side == "over" else 1 - po
                    detail = f"Normal total μ={ph+pa}, σ={C['game_sd']['total']}"
                else:
                    margin = (ph - pa) if side == g["home"] else (pa - ph)
                    base = 1 - NormalDist(margin, C["game_sd"]["margin"]).cdf(-line)  # covers if margin + line > 0
                    detail = f"Normal margin μ={margin:+.1f}, σ={C['game_sd']['margin']}"
                method = "model"
            else:
                o = other_side(key, book)
                if o is not None:
                    base, method, detail = no_vig(price, o), "no_vig", f"No-vig from {book} both sides"
        elif is_any:
            mp, srcs = model_prob(subj, team, gid, "anytime_td")
            lam, tdd = td_model(p, gid) if p else (None, None)
            model_check = poisson_any(lam) if lam is not None else None
            if mp is not None:
                base, method = mp, "model"
                detail = f"{', '.join(sorted({s['source'] for s in srcs}))} {mp:.1%}" + (f" | {tdd} → {model_check:.1%}" if tdd else "")
                support.append(f"Model ({', '.join(sorted({s['source'] for s in srcs}))})")
                if any(not s["label_confirmed"] for s in srcs):
                    flags.append("model label unconfirmed (anytime vs first TD)")
            elif lam is not None:
                bl = C["td_model"]["book_blend"]
                base = bl * implied(price) + (1 - bl) * model_check
                method, detail = "estimate", f"ESTIMATE: {bl:.0%} book ({implied(price):.1%}) + {1-bl:.0%} {tdd} → {model_check:.1%}"
        elif is_multi:
            if (gid, subj) in anytime_final:
                lam = lam_from_any(anytime_final[(gid, subj)])
                base = poisson_2plus(lam) if line == 1.5 else 1 - math.exp(-lam) * (1 + lam + lam * lam / 2)
                method, detail = "model", f"Poisson from final anytime Hit % (λ={lam:.2f})"
        elif market in MARKET_INFO and p:
            proj, srcs = model_prob(subj, team, gid, MODEL_STAT[market])
            o = other_side(key, book)
            if proj is not None and line is not None:
                if market == "player_receptions":
                    cdf = sum(math.exp(-proj) * proj ** k / math.factorial(k) for k in range(int(math.floor(line)) + 1))
                    po = 1 - cdf; detail = f"Poisson μ={proj:.1f} ({', '.join(sorted({s['source'] for s in srcs}))})"
                else:
                    f_, mn = C["sd"][SD_KEY[market]]; sd = max(f_ * proj, mn)
                    po = normal_over(proj, sd, line); detail = f"Normal μ={proj:.1f}, σ={sd:.1f} ({', '.join(sorted({s['source'] for s in srcs}))})"
                base = po if side == "over" else 1 - po; method = "model"
            elif o is not None:
                base, method, detail = no_vig(price, o), "no_vig", f"No-vig from {book} both sides"
            elif line is not None:
                stat = MARKET_INFO[market][1]; l5 = p["last20"][-5:]
                vals = [(x["rush_yds"] + x["rec_yds"]) if stat == "rush_rec" else x[stat] for x in l5]
                if vals:
                    mu = mean(vals); f_, mn = C["sd"].get(SD_KEY.get(market, "reception_yds"), (0.55, 15)); sd = max(f_ * mu, mn)
                    po = normal_over(mu, sd, line); own = po if side == "over" else 1 - po; bl = C["estimate_book_blend"]
                    base = bl * implied(price) + (1 - bl) * own; method = "estimate"
                    detail = f"ESTIMATE: {bl:.0%} book + {1-bl:.0%} last-5 average {mu:.1f}"
        if base is None:
            continue  # nothing honest to say about this bet -> it goes to Lines needed / not scored
        if p and (is_any or is_multi) and p["red_zone"]["window_games"] < 3:
            flags.append(f"Role based on only {p['red_zone']['window_games']} recent game(s) with this team")
        if p and market in MARKET_INFO and method == "model" and line is not None:
            stat = MARKET_INFO[market][1]
            vals = [(x["rush_yds"] + x["rec_yds"]) if stat == "rush_rec" else x[stat] for x in p["last20"][-5:]]
            proj_used, _ = model_prob(subj, team, gid, MODEL_STAT[market])
            if vals and proj_used and abs(proj_used - mean(vals)) / max(proj_used, 1) > 0.40:
                flags.append(f"Projection {proj_used:g} vs last-5 average {mean(vals):.1f} — projection may be off")

        # ---- 2. adjustments ----
        sgn = SIGN.get(side, 1)
        if p:
            research = []
            if market in MARKET_INFO and opp:
                d = defense.get((opp, p["pos"], MARKET_INFO[market][2]))
                if d:
                    research.append(("def", d["rank"], f"{opp} allows the {d['rank']}{'th' if 10<=d['rank']%100<=20 else {1:'st',2:'nd',3:'rd'}.get(d['rank']%10,'th')} most {MARKET_INFO[market][2].replace('_',' ')} to {p['pos']}s ({d['per_game']}/gm)"))
            if (is_any or is_multi) and method == "model" and opp:  # TD model already includes these when it's the base
                d = def_td.get((opp, p["pos"]))
                if d:
                    research.append(("def", d["rank"], f"{opp} allows the #{d['rank']} most TDs to {p['pos']}s ({d['tds_per_game']}/gm)"))
                rz = p["red_zone"]; R = C["rules"]
                chances = rz["targets_in20"] + rz["carries_in20"]
                role = max(rz["rz_target_share"], rz["rz_carry_share"])
                if role >= R["rz_leader_share"] and chances >= R["rz_leader_min_chances"]:
                    kind = "targets" if rz["rz_target_share"] >= rz["rz_carry_share"] else "carries"
                    adjustments.append({"type": "research", "points": R["rz_leader_points"],
                                        "reason": f"Red-zone leader: {role:.0%} of team's {kind} inside the 20 (last {rz['window_games']})"})
                    support.append("Red-zone leader")
            R = C["rules"]
            for _, rk, why in research:
                pts = R["def_top5"] if rk <= 5 else R["def_top10"] if rk <= 10 else R["def_bottom5"] if rk >= 28 else R["def_bottom10"] if rk >= 23 else 0
                if pts:
                    adjustments.append({"type": "research", "points": pts * sgn, "reason": why})
                    if pts * sgn > 0:
                        support.append("Defense matchup")
            bp = boosts.get((norm_name(subj), team))
            if bp:
                adjustments.append({"type": "injury", "points": bp[0] * sgn, "reason": f"🔺 {bp[1]}"})
                support.append("Injury boost")
            st = status.get((norm_name(subj), team))
            if st in ("out", "ir", "suspended", "inactive", "exempt"):
                flags.append(f"Player listed {st.upper()} but has a posted line")
            elif st in ("doubtful", "questionable"):
                flags.append(f"Player {st}")
            if is_any and model_check is not None and method == "model" and abs(model_check - base) >= 0.10:
                flags.append(f"TD model ({model_check:.0%}) and published model ({base:.0%}) disagree by 10+ points")
        rsum = sum(a["points"] for a in adjustments if a["type"] == "research")
        if abs(rsum) > C["research_cap"]:
            scale = C["research_cap"] / abs(rsum)
            for a in adjustments:
                if a["type"] == "research":
                    a["points"] = round(a["points"] * scale, 2)
        ext = [x for x in inj.get("external", []) if x["game_id"] == gid and x["affects"] in (team, "game")]
        esum = max(min(sum(x["adjustment_points"] for x in ext), C["external_cap"]), -C["external_cap"])
        if ext and esum:
            adjustments.append({"type": "external", "points": esum * sgn, "reason": "; ".join(x["detail"] for x in ext)})
        hit = min(max(base + sum(a["points"] for a in adjustments) / 100, 0.01), 0.99)
        if is_any:
            anytime_final[(gid, subj)] = hit if (gid, subj) not in anytime_final or book == BOOKS[0] else anytime_final[(gid, subj)]
        if hidden:
            continue
        imp = implied(price); edge = round((hit - imp) * 100, 1)

        # ---- 3. hit frequency, last 5 games ----
        hits = games_n = 0
        if p:
            l5 = p["last20"][-5:]
            for x in l5:
                if is_any: ok = x["tds"] >= 1
                elif is_multi: ok = x["tds"] > line
                elif market in MARKET_INFO and line is not None:
                    stat = MARKET_INFO[market][1]; v = (x["rush_yds"] + x["rec_yds"]) if stat == "rush_rec" else x[stat]
                    ok = v > line if side == "over" else v < line
                else: continue
                games_n += 1; hits += ok
        streak = "5/5 — check whether the line has moved up (line has caught up?)" if games_n == 5 and hits == 5 else None
        if p and is_any:
            sim = similar.get((opp, p["pos"]))
            if sim and sim["players"] and sim["scored"] / sim["players"] >= 0.5:
                support.append(f"Similar {p['pos']}s vs {opp}: {sim['scored']}/{sim['players']} with 3+ RZ chances scored")

        # ---- 4. boards ----
        B = C["boards"]; boards = []
        backed = method == "model" or len(set(support)) >= 2
        blocked = any("listed OUT" in f or "listed IR" in f for f in flags)
        if not blocked:
            if price >= B["plus"]["min_price"] and edge >= B["plus"]["min_edge"] and hit >= B["plus"]["min_hit"] and backed: boards.append("plus")
            if price >= B["long_shot"]["min_price"] and edge >= B["long_shot"]["min_edge"] and hit >= B["long_shot"]["min_hit"]: boards.append("long_shot")
            if price < 0 and hit >= B["anchor"]["min_hit"] and edge >= B["anchor"]["min_edge"]: boards.append("anchor")
        section = "game_specials" if is_game else "anytime_td" if is_any else "multi_td" if is_multi else MARKET_INFO.get(market, ("rush_rec_yds",))[0]
        bets.append({"bet_id": f"b{len(bets)+1:03d}", "game_id": gid, "section": section, "player_id": p["player_id"] if p else None,
                     "subject": subj, "team": team if team in (g["away"], g["home"]) else None, "opp": opp, "market": market, "side": side, "line": line,
                     "book": book, "price": price, "best_price": {"book": best_b, "price": prices[best_b]},
                     "other_side_price": other_side(key, book), "base_pct": round(base, 4), "hit_method": method, "method_detail": detail,
                     "adjustments": adjustments, "hit_pct": round(hit, 4), "implied_pct": round(imp, 4), "edge": edge,
                     "hit_freq": {"hits": hits, "games": games_n, "expected": round(imp * games_n, 1), "small_sample": games_n < 2},
                     "streak_note": streak, "boards": boards, "kickoff_et": g["kickoff_et"], "prices_by_book": prices,
                     "model_check": round(model_check, 4) if model_check is not None else None,
                     "support": sorted(set(support)), "flags": flags})

    # ---------- 5. parlays (one book per parlay) ----------
    parlays = []
    pool = [b for b in bets if b["boards"]]
    for slot in ["Sunday early", "Sunday late", "Weekday"]:
        legs = [b for b in pool if kickoff_slot(b["kickoff_et"]) == slot]
        if len([b for b in legs if set(b["boards"]) & {"plus", "long_shot"}]) < 1 or len(legs) < 2:
            continue
        options = []
        for bk in sorted({bk for b in legs for bk in b["prices_by_book"]}):
            cand = sorted([b for b in legs if bk in b["prices_by_book"]], key=lambda b: -b["edge"])
            chosen, used = [], set()
            for b in cand:
                k = (b["game_id"], b["subject"], b["market"])
                if k in used: continue
                chosen.append(b); used.add(k)
                if len(chosen) == 3: break
            if len(chosen) >= 2 and any(set(b["boards"]) & {"plus", "long_shot"} for b in chosen):
                dec = math.prod(decimal(b["prices_by_book"][bk]) for b in chosen)
                options.append({"slot": slot, "legs": [b["bet_id"] for b in chosen], "book": bk,
                                "combined_hit_pct": round(math.prod(b["hit_pct"] for b in chosen), 4), "decimal_odds": round(dec, 2),
                                "american_odds": american(dec),
                                "correlation_note": "Legs share a game — outcomes are linked" if len({b["game_id"] for b in chosen}) < len(chosen) else None})
        # Preferred-book version first, then the best-paying other allowed book with the same legs (never mix books)
        dk = [o for o in options if o["book"] == BOOKS[0]]
        parlays += dk
        same = [o for o in options if o["book"] != BOOKS[0] and (not dk or o["legs"] == dk[0]["legs"])]
        if same:
            best = max(same, key=lambda o: o["decimal_odds"])
            if not dk or best["decimal_odds"] > dk[0]["decimal_odds"]:
                parlays.append(best)

    # ---------- 6. near misses ----------
    nm = sorted([b for b in bets if not b["boards"] and b["edge"] >= C["near_miss_min_edge"] and b["price"] >= 100], key=lambda b: -b["edge"])[:6]
    near = []
    for b in nm:
        B_ = C["boards"]; need = []
        if b["price"] >= B_["long_shot"]["min_price"]:  # judged as a long shot
            if b["edge"] < B_["long_shot"]["min_edge"]: need.append(f"edge +{b['edge']} (long shot needs +{B_['long_shot']['min_edge']})")
            if b["hit_pct"] < B_["long_shot"]["min_hit"]: need.append(f"Hit {b['hit_pct']:.0%} (long shot needs {B_['long_shot']['min_hit']:.0%})")
        else:                                           # judged as a Plus board bet
            if b["edge"] < B_["plus"]["min_edge"]: need.append(f"edge +{b['edge']} (needs +{B_['plus']['min_edge']})")
            if b["hit_pct"] < B_["plus"]["min_hit"]: need.append(f"Hit {b['hit_pct']:.0%} (needs {B_['plus']['min_hit']:.0%})")
            if b["hit_method"] != "model" and len(b["support"]) < 2: need.append("needs a model or 2 supporting stats")
        near.append({"bet_id": b["bet_id"], "missed_by": "; ".join(need), "news_that_changes_it": "Confirmed bigger role or a teammate ruled out"})

    out = {"run_id": run_id, "sport": man["sport"], "built_at": now_et(), "bets": bets, "parlays": parlays, "near_misses": near}
    save(folder, "scored.json", out)

    # ---------- 7. prediction ledger (graded later by grader.py) ----------
    repo = pathlib.Path(folder).resolve().parents[2]
    led = repo / "ledger" / "predictions.csv"; led.parent.mkdir(exist_ok=True)
    cols = ["run_id", "bet_id", "game_id", "kickoff_et", "player_id", "subject", "team", "market", "side", "line", "book", "price",
            "hit_pct", "implied_pct", "edge", "hit_method", "dimers_or_model_base", "td_model", "boards", "result", "graded_at"]
    old = [r for r in csv.DictReader(open(led))] if led.exists() else []
    old = [r for r in old if r["run_id"] != run_id]  # re-running a run replaces its rows
    with open(led, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader(); w.writerows(old)
        for b in bets:
            w.writerow({"run_id": run_id, "bet_id": b["bet_id"], "game_id": b["game_id"], "kickoff_et": b["kickoff_et"], "player_id": b["player_id"] or "",
                        "subject": b["subject"], "team": b["team"] or "", "market": b["market"], "side": b["side"], "line": "" if b["line"] is None else b["line"],
                        "book": b["book"], "price": b["price"], "hit_pct": b["hit_pct"], "implied_pct": b["implied_pct"], "edge": b["edge"],
                        "hit_method": b["hit_method"], "dimers_or_model_base": b["base_pct"], "td_model": b["model_check"] or "",
                        "boards": "|".join(b["boards"]), "result": "", "graded_at": ""})
    nb = {k: sum(k in b["boards"] for b in bets) for k in ("plus", "long_shot", "anchor")}
    event(folder, run_id, "scorer", "handoff", "score", f"{len(bets)} bets: {nb['plus']} plus, {nb['long_shot']} long shot, {nb['anchor']} anchors", "scored.json")
    print(f"scored.json: {len(bets)} bets | plus {nb['plus']} | long shot {nb['long_shot']} | anchors {nb['anchor']} | parlays {len(parlays)} | ledger {led.relative_to(repo)}")

if __name__ == "__main__":
    main(sys.argv[1])
