"""Writes the agent outputs from the Nov 12 2026 WAS@NYG hand-run into a run folder,
so the scripts can be tested on a game we already scored by hand.
Usage: python tests/thursday_fixture.py runs/nfl/2026-11-12_thursday   (run feed_to_odds.py first)"""
import sys, json, pathlib
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "scripts"))
from common import load, save
F = sys.argv[1]; G = "2026_10_WAS_NYG"; T = "2026-11-12T19:40:00-05:00"
src = lambda n, u=None, v=True: {"name": n, "url": u, "fetched_at": T, "verbatim": v}
SAO = src("ScoresAndOdds props", "https://www.scoresandodds.com/nfl/props/rushing-yards")
odds = load(F, "odds.json")
extra = [  # Scout additions: yardage props the feed didn't have (Thursday's ScoresAndOdds/DK numbers)
 ("J.J. McCarthy","NYG","player_pass_yds","under",211.5,-111,"draftkings"),("J.J. McCarthy","NYG","player_pass_yds","over",204.5,-115,"bet365"),
 ("Jayden Daniels","WAS","player_pass_yds","over",201.5,100,"betmgm"),("Jayden Daniels","WAS","player_rush_yds","over",37.5,-111,"draftkings"),
 ("Rachaad White","WAS","player_rush_yds","over",35.5,-140,"fanatics"),("Cam Skattebo","NYG","player_rush_yds","under",64.5,-115,"hardrockbet"),
 ("Devin Singletary","NYG","player_rush_yds","over",23.5,-108,"draftkings"),("Austin Ekeler","WAS","player_rush_yds","over",29.5,-113,"fanduel"),
 ("Malik Nabers","NYG","player_reception_yds","over",63.5,-115,"bet365"),("Isaiah Likely","NYG","player_reception_yds","over",45.5,-113,"draftkings"),
 ("Stefon Diggs","WAS","player_reception_yds","over",35.5,-125,"fanatics"),("Antonio Williams","WAS","player_reception_yds","over",38.5,-110,"draftkings"),
 ("Chig Okonkwo","WAS","player_reception_yds","over",32.5,-135,"betmgm"),
 ("Malik Nabers","NYG","player_receptions","over",5.5,-141,"caesars"),("Malik Nabers","NYG","player_receptions","under",5.5,111,"caesars")]
for n,t,m,s,l,p,b in extra:
    odds["props"].append({"game_id":G,"player_name":n,"team":t,"market":m,"side":s,"line":l,"price":p,"book":b,"alt":False,"source":SAO})
odds["lines_needed"].append({"game_id":G,"player_name":"Isaiah Likely","markets":["player_2nd_half_td"],"reason":"5 of 6 TDs in 2H","sources_tried":["odds feed","ScoresAndOdds","DK Network"]})
save(F, "odds.json", odds)
save(F, "injuries.json", {"run_id": odds["run_id"], "sport": "nfl", "written_at": T,
 "starters": [{"team":"NYG","pos":"QB","player_name":"J.J. McCarthy","confirmed":True,"note":"Jaxson Dart out for season"},
              {"team":"WAS","pos":"QB","player_name":"Jayden Daniels","confirmed":True,"note":None}],
 "players": [{"player_name":"Terry McLaurin","team":"WAS","pos":"WR","status":"ir","injury":"season-ending","practice":[],"game_day_inactive":True,"source":src("DK Network")},
             {"player_name":"Treylon Burks","team":"WAS","pos":"WR","status":"active","injury":None,"practice":["DNP","LP","DNP"],"game_day_inactive":None,"source":src("SportsBettingDime")},
             {"player_name":"Cam Skattebo","team":"NYG","pos":"RB","status":"active","injury":"hamstring","practice":["LP","FP","FP"],"game_day_inactive":None,"source":src("SportsBettingDime")}],
 "volume_shifts": [{"team":"WAS","out_player":"Terry McLaurin","reason":"WR1 out for the season",
   "beneficiaries":[{"player_name":"Stefon Diggs","role":"red_zone","boost_points":2,"why":"Already leads WAS in red-zone targets; McLaurin's 4 RZ targets move mostly to him"},
                    {"player_name":"Antonio Williams","role":"targets","boost_points":1,"why":"83-84% snaps the last 2 games as the new WR2"}]}],
 "transactions": [], "external": [], "failures": [{"source":"Hogs Haven","url":None,"error":"robots.txt disallowed"}]})
pm = [("Isaiah Likely","NYG",.332),("Cam Skattebo","NYG",.369),("Malik Nabers","NYG",.338),("Rachaad White","WAS",.302),("Stefon Diggs","WAS",.284),("Jayden Daniels","WAS",.242)]
proj = [("J.J. McCarthy","NYG","pass_yds",207),("Jayden Daniels","WAS","pass_yds",201),("Jayden Daniels","WAS","rush_yds",37),("Rachaad White","WAS","rush_yds",43),
        ("Cam Skattebo","NYG","rush_yds",60),("Devin Singletary","NYG","rush_yds",28),("Austin Ekeler","WAS","rush_yds",37),("Malik Nabers","NYG","rec_yds",71),
        ("Isaiah Likely","NYG","rec_yds",47),("Stefon Diggs","WAS","rec_yds",40),("Antonio Williams","WAS","rec_yds",41),("Chig Okonkwo","WAS","rec_yds",38),("Malik Nabers","NYG","receptions",5.7)]
save(F, "models.json", {"run_id": odds["run_id"], "sport": "nfl", "written_at": T,
 "game_models": [{"game_id":G,"source":"dimers","win_prob_home":.571,"win_prob_away":.429,"proj_home_pts":21,"proj_away_pts":20,"url":"https://www.dimers.com/nfl/predictions/2026_10_nyg_was"}],
 "player_models": [{"game_id":G,"player_name":n,"team":t,"source":"dimers","stat":"anytime_td","value_type":"probability","value":v,"label_confirmed":False,"url":None} for n,t,v in pm]
   + [{"game_id":G,"player_name":n,"team":t,"source":"scoresandodds","stat":s,"value_type":"projection","value":v,"label_confirmed":True,"url":None} for n,t,s,v in proj],
 "failures": []})
print("fixture written")
