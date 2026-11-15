"""Regenerates schemas/*.schema.json. Edit this file, then run: python scripts/build_schemas.py"""
import json, os
OUT=os.path.join(os.path.dirname(os.path.abspath(__file__)),'..','schemas')
R=lambda n:{"$ref":f"common.schema.json#/$defs/{n}"}
def S(title,desc,props,req):
    return {"$schema":"https://json-schema.org/draft/2020-12/schema","$id":f"{title}.schema.json","title":title,"description":desc,"type":"object","properties":props,"required":req,"additionalProperties":False}
def obj(props,req=None,extra=False): return {"type":"object","properties":props,"required":req or list(props),"additionalProperties":extra}
def arr(x): return {"type":"array","items":x}
nstr={"type":["string","null"]}; nnum={"type":["number","null"]}; nint={"type":["integer","null"]}; s={"type":"string"}; b={"type":"boolean"}; i={"type":"integer"}; n={"type":"number"}
failures=arr(obj({"source":s,"url":nstr,"error":s}))
common={"$schema":"https://json-schema.org/draft/2020-12/schema","$id":"common.schema.json","title":"common","$defs":{
 "sport":{"enum":["nfl","nba"]},
 "run_id":{"type":"string","pattern":"^(nfl|nba)_\\d{4}-\\d{2}-\\d{2}_[a-z0-9_]+$","description":"e.g. nfl_2026-11-15_sunday"},
 "timestamp":{"type":"string","format":"date-time","description":"ISO 8601 with offset, e.g. 2026-11-15T09:30:00-05:00"},
 "team":{"type":"string","pattern":"^[A-Z]{2,3}$","description":"nflverse / NBA abbreviation, e.g. NYG, LA, LV"},
 "game_id":{"type":"string","pattern":"^(\\d{4}_\\d{2}_[A-Z]{2,3}_[A-Z]{2,3}|\\d{8}_[A-Z]{2,3}_[A-Z]{2,3})$","description":"NFL: season_week_AWAY_HOME (nflverse), e.g. 2026_10_WAS_NYG. NBA: YYYYMMDD_AWAY_HOME."},
 "book":{"enum":["draftkings","fanduel","betmgm","caesars","espnbet","fanatics","bet365","hardrockbet","user_provided"],"description":"Sportsbooks only. Prediction markets and exchanges (Kalshi, Polymarket, Novig...) are not allowed."},
 "american_odds":{"type":"integer","anyOf":[{"minimum":100},{"maximum":-100}]},
 "prob":{"type":"number","minimum":0,"maximum":1},
 "source":obj({"name":s,"url":nstr,"fetched_at":R("timestamp"),"verbatim":{"type":"boolean","description":"true = number copied from page text; false = from a summary or unlabeled table (treat as unverified)"}}),
 "agent_status":{"enum":["pending","running","done","failed","skipped"]}}}
manifest=S("manifest","Written by the Manager at the start of a run and updated as agents finish. One per run folder.",{
 "run_id":R("run_id"),"sport":R("sport"),"season":i,"week":nint,"slate":s,"run_type":{"enum":["scheduled","on_demand"]},"created_at":R("timestamp"),
 "games":arr(obj({"game_id":R("game_id"),"away":R("team"),"home":R("team"),"kickoff_et":R("timestamp"),"venue":s,"status":{"enum":["scheduled","in_progress","final","postponed"]}})),
 "byes":arr(R("team")),
 "agents":{"type":"object","additionalProperties":obj({"status":R("agent_status"),"started_at":{"type":["string","null"]},"finished_at":{"type":["string","null"]},"output":nstr,"error":nstr})},
 "notes":arr(s)},["run_id","sport","season","week","slate","run_type","created_at","games","byes","agents","notes"])
line_row=obj({"game_id":R("game_id"),"book":R("book"),"market":{"enum":["h2h","spreads","totals","h2h_h1","spreads_h1","totals_h1","h2h_q1","spreads_q1","totals_q1","team_totals","first_to_score","race_to","other_special"]},
 "side":{"type":"string","description":"Team abbreviation, 'over', 'under', 'yes' or 'no'"},"team":{"anyOf":[R("team"),{"type":"null"}],"description":"For team_totals / race_to: which team"},"point":nnum,"price":R("american_odds"),"label":nstr,"source":R("source")})
prop_row=obj({"game_id":R("game_id"),"player_name":s,"team":{"anyOf":[R("team"),{"type":"null"}]},"market":{"type":"string","description":"The Odds API market key, e.g. player_anytime_td, player_tds_over, player_pass_yds, player_rush_yds, player_reception_yds, player_receptions, player_rush_reception_yds, player_1st_half_td, player_2nd_half_td, player_points, player_points_rebounds_assists"},
 "side":{"enum":["over","under","yes"]},"line":nnum,"price":R("american_odds"),"book":R("book"),"alt":b,"source":R("source")})
odds=S("odds","Written by the Scout. One row = one side of one market at one book. Same-book pairs are matched later by (game_id, player_name, market, line, book).",{
 "run_id":R("run_id"),"sport":R("sport"),"written_at":R("timestamp"),
 "feed":obj({"fetched_at":{"type":["string","null"]},"age_minutes":nnum,"stale":b,"games_missing":arr(R("game_id")),"markets_in_feed":arr(s)}),
 "game_lines":arr(line_row),"props":arr(prop_row),
 "lines_needed":arr(obj({"game_id":R("game_id"),"player_name":nstr,"markets":arr(s),"reason":s,"sources_tried":arr(s)})),
 "failures":failures},["run_id","sport","written_at","feed","game_lines","props","lines_needed","failures"])
injuries=S("injuries","Written by the Medic. Statuses, starting QBs, trades, who gains volume, and external factors.",{
 "run_id":R("run_id"),"sport":R("sport"),"written_at":R("timestamp"),
 "starters":arr(obj({"team":R("team"),"pos":s,"player_name":s,"confirmed":b,"note":nstr})),
 "players":arr(obj({"player_name":s,"team":R("team"),"pos":s,"status":{"enum":["out","doubtful","questionable","probable","active","inactive","ir","suspended","exempt"]},"injury":nstr,"practice":arr({"enum":["DNP","LP","FP","-"]}),"game_day_inactive":{"type":["boolean","null"]},"source":R("source")})),
 "volume_shifts":arr(obj({"team":R("team"),"out_player":s,"beneficiaries":arr(obj({"player_name":s,"role":{"enum":["targets","carries","red_zone","minutes","usage","snaps"]},"boost_points":{"type":"number","minimum":0,"maximum":6},"why":{"type":"string","minLength":10,"description":"Why this player gains volume and why this many points"}})),"reason":s})),
 "transactions":arr(obj({"player_name":s,"from_team":{"type":["string","null"]},"to_team":{"type":["string","null"]},"date":nstr,"source":R("source")})),
 "external":arr(obj({"game_id":R("game_id"),"factor":{"enum":["weather","travel","international","short_week","coaching","locker_room","trade_rumor","other"]},"detail":s,"affects":s,"adjustment_points":{"type":"number","minimum":-3,"maximum":3},"source":R("source")})),
 "failures":failures},["run_id","sport","written_at","starters","players","volume_shifts","transactions","external","failures"])
models=S("models","Written by the Oracle. Published model numbers only, never prediction-market prices.",{
 "run_id":R("run_id"),"sport":R("sport"),"written_at":R("timestamp"),
 "game_models":arr(obj({"game_id":R("game_id"),"source":{"enum":["dimers","espn","numberfire","ftn","scoresandodds","other"]},"win_prob_home":{"anyOf":[R("prob"),{"type":"null"}]},"win_prob_away":{"anyOf":[R("prob"),{"type":"null"}]},"proj_home_pts":nnum,"proj_away_pts":nnum,"url":nstr})),
 "player_models":arr(obj({"game_id":R("game_id"),"player_name":s,"team":{"anyOf":[R("team"),{"type":"null"}]},"source":{"enum":["dimers","espn_clay","numberfire","ftn","scoresandodds","other"]},
   "stat":{"type":"string","description":"anytime_td, first_td, two_plus_td, pass_yds, rush_yds, rec_yds, rush_rec_yds, receptions, points, rebounds, assists, pra, pa, pr, threes"},
   "value_type":{"enum":["probability","projection"]},"value":n,"label_confirmed":{"type":"boolean","description":"false if the page is unclear (e.g. anytime vs first TD)"},"url":nstr})),
 "failures":failures},["run_id","sport","written_at","game_models","player_models","failures"])
gamelog=obj({"season":i,"week":i,"opp":s,"pass_yds":n,"rush_yds":n,"rec_yds":n,"receptions":n,"targets":n,"carries":n,"tds":n,"tds_1h":nint,"tds_2h":nint,"scored_team_first_td":{"type":["boolean","null"]}})
stats=S("stats","Written by analyst.py (code, not an agent). This is the ONLY place player names become player_ids; ambiguous names go to unmatched, never guessed.",{
 "run_id":R("run_id"),"sport":R("sport"),"built_at":R("timestamp"),"data_through":obj({"season":i,"week":i}),
 "players":arr(obj({"player_id":s,"player_name":s,"team":R("team"),"pos":s,"aliases":arr(s),"last20":arr(gamelog),
   "red_zone":obj({"window_games":i,"carries_in20":i,"carries_in5":i,"targets_in20":i,"targets_in5":i,"share_in20":n,"share_in5":n,"rz_target_share":n,"rz_carry_share":n,"target_share":n}),"finishing":obj({"window":s,"rz_opps":i,"rz_tds":i,"rate":nnum})})),
 "defense":arr(obj({"team":R("team"),"pos":s,"stat":s,"per_game":n,"total":n,"games":i,"rank":i,"tied":b})),
 "teams":arr(obj({"team":R("team"),"first_td_rate_this":nnum,"first_td_rate_last":nnum,"pts_1q_for":n,"pts_1q_against":n,"pts_1h_for":n,"pts_1h_against":n,"pts_2h_for":n,"pts_2h_against":n})),
 "unmatched":arr(obj({"player_name":s,"team":{"type":["string","null"]},"reason":s})),"league":obj({"rz_td_rate_by_pos":{"type":"object","additionalProperties":n},"tds_per_team_game_by_pos":{"type":"object","additionalProperties":n},"td_points_share":n}),"defense_td":arr(obj({"team":R("team"),"pos":s,"tds_per_game":n,"games":i,"rank":i})),"defense_vs_similar":arr(obj({"team":R("team"),"pos":s,"min_rz_opps":i,"players":i,"scored":i,"examples":arr(s)}))},["run_id","sport","built_at","data_through","players","defense","teams","unmatched","league","defense_td","defense_vs_similar"])
adj=obj({"type":{"enum":["research","injury","external"]},"points":n,"reason":s})
bet=obj({"bet_id":s,"game_id":R("game_id"),"section":{"enum":["game_specials","anytime_td","multi_td","passing_yds","rush_rec_yds","combos","pra","pa","pr","threes"]},
 "player_id":nstr,"subject":{"type":"string","description":"Player name, team name, or 'Game'"},"team":{"anyOf":[R("team"),{"type":"null"}]},"opp":{"anyOf":[R("team"),{"type":"null"}]},
 "market":s,"side":s,"line":nnum,"book":R("book"),"price":R("american_odds"),"best_price":obj({"book":R("book"),"price":R("american_odds")}),"other_side_price":{"anyOf":[R("american_odds"),{"type":"null"}]},
 "base_pct":R("prob"),"hit_method":{"enum":["model","no_vig","estimate"]},"method_detail":s,"adjustments":arr(adj),"hit_pct":R("prob"),"implied_pct":R("prob"),"edge":{"type":"number","description":"hit_pct - implied_pct, in percentage points"},
 "hit_freq":obj({"hits":i,"games":i,"expected":n,"small_sample":b}),"streak_note":nstr,"boards":arr({"enum":["plus","long_shot","anchor"]}),"kickoff_et":R("timestamp"),"prices_by_book":{"type":"object","additionalProperties":R("american_odds")},"model_check":{"anyOf":[R("prob"),{"type":"null"}],"description":"TD opportunity model result, shown next to Dimers for calibration"},"support":arr(s),"flags":arr(s)})
scored=S("scored","Written by scorer.py (code). Every number here is computed, never typed by an agent.",{
 "run_id":R("run_id"),"sport":R("sport"),"built_at":R("timestamp"),"bets":arr(bet),
 "parlays":arr(obj({"slot":s,"legs":arr(s),"book":R("book"),"combined_hit_pct":R("prob"),"decimal_odds":n,"american_odds":R("american_odds"),"correlation_note":nstr})),
 "near_misses":arr(obj({"bet_id":s,"missed_by":s,"news_that_changes_it":s}))},["run_id","sport","built_at","bets","parlays","near_misses"])
audit=S("audit","Written by the Auditor. 'block' flags remove the bet before publishing; 'warn' flags print next to it.",{
 "run_id":R("run_id"),"written_at":R("timestamp"),"checks_run":arr(s),
 "flags":arr(obj({"flag_id":s,"severity":{"enum":["block","warn","info"]},"bet_id":nstr,"player_name":nstr,
   "check":{"enum":["wrong_team","player_out_with_prop","stale_line","projection_conflict","price_mismatch","banned_source","small_sample","missing_pair","duplicate","other"]},
   "detail":s,"evidence":arr(s),"action":{"enum":["drop_bet","keep_with_warning","recheck_price","none"]}})),
 "summary":obj({"blocked":i,"warned":i,"info":i})},["run_id","written_at","checks_run","flags","summary"])
event=S("event","One line of events.jsonl. Every agent and script appends; nobody edits. Feeds the visualization later.",{
 "t":R("timestamp"),"run_id":R("run_id"),"agent":{"enum":["manager","scout","medic","oracle","analyst","scorer","auditor","publisher"]},"status":{"enum":["idle","working","handoff","done","error"]},"step":s,"msg":s,"file":nstr},["t","run_id","agent","status","step","msg","file"])
for name,d in [("common",common),("manifest",manifest),("odds",odds),("injuries",injuries),("models",models),("stats",stats),("scored",scored),("audit",audit),("event",event)]:
    json.dump(d,open(f'{OUT}/{name}.schema.json','w'),indent=2)
print(os.listdir(OUT))
