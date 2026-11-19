import requests
import time
from datetime import datetime

# -----------------------------
# TEAM IDS (extendable)
# -----------------------------
TEAM_IDS = {
    "nba": {
        "los angeles lakers": 13,
        "golden state warriors": 9,
        "boston celtics": 2,
        "miami heat": 14,
        "chicago bulls": 4,
        "cleveland cavaliers": 5,
        "new york knicks": 18,
        "philadelphia 76ers": 20,
        "phoenix suns": 21,
        "dallas mavericks": 6,
        "denver nuggets": 7,
        "oklahoma city thunder": 25,
    },
    "nfl": {},
    "mlb": {},
    "nhl": {},
}

# -----------------------------
# CACHE (TTL)
# -----------------------------
_cache = {}
CACHE_TTL = 120


# -----------------------------
# NORMALIZATION
# -----------------------------
def normalize(name: str):
    return name.lower().replace(".", "").replace("-", " ").strip()


def fuzzy_match(team_name, team_map):
    target = normalize(team_name)

    # exact
    if target in team_map:
        return team_map[target]

    # fallback: last word match (Lakers, Bulls, etc.)
    short = target.split()[-1]

    for k, v in team_map.items():
        if short in k:
            return v

    return None


# -----------------------------
# MAIN FUNCTION
# -----------------------------
def get_recent_games(team_name, sport="nba"):
    sport = sport.lower()
    team_key = normalize(team_name)
    cache_key = f"{sport}:{team_key}"

    now = time.time()

    # ✅ CACHE CHECK
    if cache_key in _cache:
        if now - _cache[cache_key]["time"] < CACHE_TTL:
            return _cache[cache_key]["data"]

    team_map = TEAM_IDS.get(sport, {})
    team_id = fuzzy_match(team_key, team_map)

    if not team_id:
        return []

    url = f"https://site.api.espn.com/apis/site/v2/sports/{'basketball/nba' if sport=='nba' else sport}/teams/{team_id}/schedule"

    try:
        res = requests.get(url, timeout=5)
        data = res.json()

        games = []

        for game in data.get("events", []):

            # ✅ ONLY completed
            if not game["status"]["type"]["completed"]:
                continue

            comp = game["competitions"][0]["competitors"]

            home = comp[0]
            away = comp[1]

            home_name = normalize(home["team"]["displayName"])
            away_name = normalize(away["team"]["displayName"])

            home_score = int(home.get("score", 0))
            away_score = int(away.get("score", 0))

            date = game.get("date")

            if team_key in home_name:
                win = home_score > away_score
                opponent = away["team"]["displayName"]

            elif team_key in away_name:
                win = away_score > home_score
                opponent = home["team"]["displayName"]

            else:
                continue

            games.append({
                "date": date,
                "result": "W" if win else "L",
                "opponent": opponent
            })

        # ✅ SORT BY DATE (important fix)
        games.sort(
            key=lambda x: datetime.fromisoformat(x["date"].replace("Z", "+00:00")),
            reverse=True
        )

        last5 = games[:5]

        result = {
            "form": [g["result"] for g in last5],
            "wins": sum(1 for g in last5 if g["result"] == "W"),
            "losses": sum(1 for g in last5 if g["result"] == "L"),
            "games": last5
        }

        # ✅ CACHE SAVE
        _cache[cache_key] = {
            "time": now,
            "data": result
        }

        return result

    except:
        return []