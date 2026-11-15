"""Shared helpers for Tsunami scripts: run folders, events, odds math, team names."""
import json, math, pathlib, datetime, re, unicodedata
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
REPO = pathlib.Path(__file__).resolve().parent.parent

def settings():
    """House rules from config/settings.json (books to use, minimum price)."""
    return json.loads((REPO / "config" / "settings.json").read_text())

def now_et():
    return datetime.datetime.now(ET).replace(microsecond=0).isoformat()

def load(folder, name, default=None):
    p = pathlib.Path(folder) / name
    if not p.exists():
        if default is not None:
            return default
        raise FileNotFoundError(f"{p} is missing")
    return json.loads(p.read_text())

def save(folder, name, data):
    p = pathlib.Path(folder) / name
    p.write_text(json.dumps(data, indent=2, default=str))
    return p

def event(folder, run_id, agent, status, step, msg, file=None):
    """Append one line to events.jsonl (feeds the visualization later)."""
    line = {"t": now_et(), "run_id": run_id, "agent": agent, "status": status, "step": step, "msg": msg, "file": file}
    with open(pathlib.Path(folder) / "events.jsonl", "a") as f:
        f.write(json.dumps(line) + "\n")

# ---------- odds math ----------
def implied(odds):
    """American odds -> implied probability (with the book's fee)."""
    return (-odds) / (-odds + 100) if odds < 0 else 100 / (odds + 100)

def decimal(odds):
    return 1 + (100 / -odds if odds < 0 else odds / 100)

def american(dec):
    return round((dec - 1) * 100) if dec >= 2 else round(-100 / (dec - 1))

def no_vig(side_odds, other_odds):
    a, b = implied(side_odds), implied(other_odds)
    return a / (a + b)

def poisson_any(lam):
    return 1 - math.exp(-lam)

def poisson_2plus(lam):
    return 1 - math.exp(-lam) * (1 + lam)

def lam_from_any(p):
    p = min(max(p, 1e-6), 0.999)
    return -math.log(1 - p)

def normal_over(mean, sd, line):
    from statistics import NormalDist
    return 1 - NormalDist(mean, sd).cdf(line)

# ---------- names ----------
SUFFIX = re.compile(r"\b(jr|sr|ii|iii|iv|v)\b")
def norm_name(name):
    """'Harold Fannin Jr.' -> 'harold fannin'; 'A.J. Brown' -> 'aj brown'."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower()
    s = s.replace(".", "").replace("'", "").replace("-", " ")
    s = SUFFIX.sub("", s)
    return " ".join(s.split())

NFL_TEAMS = {
 "Arizona Cardinals": "ARI", "Atlanta Falcons": "ATL", "Baltimore Ravens": "BAL", "Buffalo Bills": "BUF",
 "Carolina Panthers": "CAR", "Chicago Bears": "CHI", "Cincinnati Bengals": "CIN", "Cleveland Browns": "CLE",
 "Dallas Cowboys": "DAL", "Denver Broncos": "DEN", "Detroit Lions": "DET", "Green Bay Packers": "GB",
 "Houston Texans": "HOU", "Indianapolis Colts": "IND", "Jacksonville Jaguars": "JAX", "Kansas City Chiefs": "KC",
 "Las Vegas Raiders": "LV", "Los Angeles Chargers": "LAC", "Los Angeles Rams": "LA", "Miami Dolphins": "MIA",
 "Minnesota Vikings": "MIN", "New England Patriots": "NE", "New Orleans Saints": "NO", "New York Giants": "NYG",
 "New York Jets": "NYJ", "Philadelphia Eagles": "PHI", "Pittsburgh Steelers": "PIT", "San Francisco 49ers": "SF",
 "Seattle Seahawks": "SEA", "Tampa Bay Buccaneers": "TB", "Tennessee Titans": "TEN", "Washington Commanders": "WAS",
}
BOOK_KEYS = {"draftkings": "draftkings", "fanduel": "fanduel", "betmgm": "betmgm", "williamhill_us": "caesars",
             "caesars": "caesars", "espnbet": "espnbet", "fanatics": "fanatics", "bet365": "bet365",
             "hardrockbet": "hardrockbet"}
