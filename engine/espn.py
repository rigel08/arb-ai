"""
espn.py — Real standings, leaders, brackets, scores.
ESPN unofficial API — free, no key, updates live.

This handles everything ESPN is good at:
  - League tables (soccer)
  - Conference standings (NBA/NFL/NHL/MLB)  
  - Stat leaders (top scorers, passers, etc)
  - Playoff brackets / knockout rounds
  - Live scores & schedules

The Odds API handles: odds, props, value bets.
"""

import time
import requests

ESPN = "https://site.api.espn.com/apis/site/v2/sports"
ESPN2 = "https://site.api.espn.com/apis/v2/sports"

LEAGUE_MAP = {
    "nfl":        ("football",   "nfl"),
    "nba":        ("basketball", "nba"),
    "mlb":        ("baseball",   "mlb"),
    "nhl":        ("hockey",     "nhl"),
    "epl":        ("soccer",     "eng.1"),
    "laliga":     ("soccer",     "esp.1"),
    "ucl":        ("soccer",     "uefa.champions"),
    "mls":        ("soccer",     "usa.1"),
    "bundesliga": ("soccer",     "ger.1"),
    "serie_a":    ("soccer",     "ita.1"),
    "ligue_1":    ("soccer",     "fra.1"),
}

_cache: dict = {}
TTL_SCORES    = 60     # 1 min — scores update frequently
TTL_STANDINGS = 1800   # 30 min — standings don't change often
TTL_LEADERS   = 3600   # 1 hour — stat leaders
TTL_BRACKET   = 600    # 10 min — bracket/knockout

HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArbAI/1.0)"}


def _get(url: str, params: dict = None, ttl: int = 60) -> dict:
    key = url + str(sorted((params or {}).items()))
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < ttl:
        return _cache[key]["data"]
    try:
        r = requests.get(url, params=params, timeout=10, headers=HEADERS)
        r.raise_for_status()
        data = r.json()
        _cache[key] = {"data": data, "ts": now}
        return data
    except Exception as e:
        print(f"[ESPN] {url}: {e}")
        return {}


def _path(sport: str):
    return LEAGUE_MAP.get(sport, ("football", "nfl"))


# ── SCOREBOARD ────────────────────────────────────────────────────────────────

def get_scoreboard(sport: str) -> list:
    s, l = _path(sport)
    data = _get(f"{ESPN}/{s}/{l}/scoreboard", ttl=TTL_SCORES)
    events = data.get("events", [])
    games  = []
    for ev in events:
        try:
            comp   = (ev.get("competitions") or [{}])[0]
            comps  = comp.get("competitors", [])
            home_c = next((c for c in comps if c.get("homeAway") == "home"), comps[0] if comps else {})
            away_c = next((c for c in comps if c.get("homeAway") == "away"), comps[1] if len(comps)>1 else {})
            status = ev.get("status", {})
            state  = status.get("type", {}).get("state", "pre")
            detail = status.get("type", {}).get("shortDetail", "")
            period = status.get("period", 0)
            clock  = status.get("displayClock", "")

            def team_info(c):
                t = c.get("team", {})
                return {
                    "id":     t.get("id", ""),
                    "name":   t.get("displayName", t.get("name", "TBD")),
                    "abbr":   t.get("abbreviation", ""),
                    "logo":   t.get("logo", ""),
                    "color":  t.get("color", "1A2035"),
                    "score":  c.get("score", ""),
                    "record": (c.get("records") or [{}])[0].get("summary", ""),
                    "winner": c.get("winner", False),
                }

            odds_r   = (comp.get("odds") or [{}])[0] if comp.get("odds") else {}
            broadcast = next((b.get("names", [""])[0] for b in comp.get("broadcasts", []) if b.get("names")), "")

            games.append({
                "id":        ev.get("id", ""),
                "name":      ev.get("name", ""),
                "date":      ev.get("date", ""),
                "status":    state,
                "detail":    detail,
                "period":    period,
                "clock":     clock,
                "home":      team_info(home_c),
                "away":      team_info(away_c),
                "venue":     comp.get("venue", {}).get("fullName", ""),
                "broadcast": broadcast,
                "espn_line": odds_r.get("overUnder", ""),
                "espn_spread": odds_r.get("spread", ""),
            })
        except Exception as e:
            print(f"[ESPN scoreboard] {e}")
    return games


# ── STANDINGS ────────────────────────────────────────────────────────────────

def get_standings(sport: str) -> dict:
    """
    Returns standings. Soccer = league table. US sports = conference standings.
    Format: {group_name: [{rank, team, record, pts, ...}]}
    """
    s, l = _path(sport)
    data = _get(f"{ESPN2}/{s}/{l}/standings", ttl=TTL_STANDINGS)

    result = {}
    is_soccer = s == "soccer"

    try:
        children = data.get("children", [])
        if not children:
            children = [data]

        for group in children:
            group_name = group.get("name", "Standings")
            standings  = group.get("standings", {})
            entries    = standings.get("entries", [])

            rows = []
            for entry in entries:
                team  = entry.get("team", {})
                stats = {s["name"]: s.get("displayValue", s.get("value", "")) 
                         for s in entry.get("stats", [])}

                row = {
                    "rank":   entry.get("note", {}).get("rank", len(rows)+1) 
                              if not is_soccer else stats.get("rank", len(rows)+1),
                    "team":   team.get("displayName", team.get("name", "")),
                    "abbr":   team.get("abbreviation", ""),
                    "logo":   team.get("logos", [{}])[0].get("href", "") if team.get("logos") else "",
                    "color":  team.get("color", ""),
                    # Soccer
                    "played": stats.get("gamesPlayed", stats.get("GP", "")),
                    "wins":   stats.get("wins", stats.get("W", "")),
                    "draws":  stats.get("ties", stats.get("D", stats.get("T", ""))),
                    "losses": stats.get("losses", stats.get("L", "")),
                    "gf":     stats.get("pointsFor", stats.get("GF", "")),
                    "ga":     stats.get("pointsAgainst", stats.get("GA", "")),
                    "gd":     stats.get("pointDifferential", stats.get("GD", "")),
                    "pts":    stats.get("points", stats.get("PTS", "")),
                    # US sports
                    "pct":    stats.get("winPercent", stats.get("PCT", "")),
                    "gb":     stats.get("gamesBehind", stats.get("GB", "")),
                    "streak": stats.get("streak", ""),
                    "home":   stats.get("Home", stats.get("homeRecord", "")),
                    "away":   stats.get("Away", stats.get("awayRecord", "")),
                    # Playoff position
                    "clinched": "x" in str(entry.get("note", {}).get("abbreviation", "")).lower(),
                    "note":    entry.get("note", {}).get("description", ""),
                }
                rows.append(row)

            if rows:
                result[group_name] = rows

    except Exception as e:
        print(f"[ESPN standings] {e}")

    return result


# ── STAT LEADERS ──────────────────────────────────────────────────────────────

def get_leaders(sport: str) -> dict:
    """
    Real stat leaders from ESPN.
    Returns {category_name: [{rank, player, team, stat, value}]}
    """
    s, l = _path(sport)
    data = _get(f"{ESPN}/{s}/{l}/leaders", ttl=TTL_LEADERS)

    result = {}
    try:
        for cat in data.get("categories", []):
            cat_name = cat.get("displayName", cat.get("name", ""))
            leaders  = []
            for i, entry in enumerate(cat.get("leaders", [])[:10]):
                athlete = entry.get("athlete", {})
                team    = entry.get("team", {})
                leaders.append({
                    "rank":   i + 1,
                    "player": athlete.get("displayName", athlete.get("fullName", "")),
                    "abbr":   team.get("abbreviation", ""),
                    "team":   team.get("displayName", ""),
                    "value":  entry.get("displayValue", str(entry.get("value", ""))),
                    "stat":   cat.get("abbreviation", cat_name),
                    "headshot": athlete.get("headshot", {}).get("href", "") 
                                if isinstance(athlete.get("headshot"), dict) 
                                else athlete.get("headshot", ""),
                })
            if leaders:
                result[cat_name] = leaders
    except Exception as e:
        print(f"[ESPN leaders] {e}")

    return result


# ── BRACKET / KNOCKOUT ────────────────────────────────────────────────────────

def get_bracket(sport: str) -> dict:
    """
    Playoff bracket for US sports. Knockout rounds for UCL/soccer.
    Returns structured bracket data.
    """
    s, l = _path(sport)

    # Try bracket endpoint
    data = _get(f"{ESPN}/{s}/{l}/scoreboard", params={"groups": "playoff"}, ttl=TTL_BRACKET)
    if not data:
        data = {}

    rounds   = {}
    events   = data.get("events", [])

    for ev in events:
        season_type = ev.get("season", {}).get("type", 0)
        if season_type not in (3, 4):  # 3=postseason, 4=offseason
            continue

        comp   = (ev.get("competitions") or [{}])[0]
        comps  = comp.get("competitors", [])
        round_name = ev.get("season", {}).get("slug", "Playoffs")

        matchup = {
            "id":     ev.get("id", ""),
            "date":   ev.get("date", ""),
            "status": ev.get("status", {}).get("type", {}).get("shortDetail", ""),
            "teams":  [],
        }

        for c in comps:
            t = c.get("team", {})
            matchup["teams"].append({
                "name":   t.get("displayName", ""),
                "abbr":   t.get("abbreviation", ""),
                "logo":   t.get("logo", ""),
                "seed":   c.get("curatedRank", {}).get("current", ""),
                "score":  c.get("score", ""),
                "winner": c.get("winner", False),
                "record": (c.get("records") or [{}])[0].get("summary", ""),
            })

        if round_name not in rounds:
            rounds[round_name] = []
        rounds[round_name].append(matchup)

    return rounds


# ── TEAM NEWS / INJURIES ──────────────────────────────────────────────────────

def get_news(sport: str, limit: int = 5) -> list:
    """Top news headlines for a sport from ESPN."""
    s, l = _path(sport)
    data = _get(f"{ESPN}/{s}/{l}/news", ttl=300)
    articles = data.get("articles", [])[:limit]
    return [{
        "headline":    a.get("headline", ""),
        "description": a.get("description", ""),
        "published":   a.get("published", ""),
        "link":        a.get("links", {}).get("web", {}).get("href", ""),
        "image":       (a.get("images") or [{}])[0].get("url", ""),
    } for a in articles]