"""
stats.py — ESPN unofficial API fetcher.
Free, no key needed. NFL, NBA, MLB, NHL, EPL, La Liga, UCL, MLS.

Key fix: get_team_form() fetches REAL schedule data per team.
parse_game() now includes win_pct derived from moneyline odds.
"""

import requests
import time
import statistics as st
from concurrent.futures import ThreadPoolExecutor, as_completed

ESPN     = "https://site.api.espn.com/apis/site/v2/sports"
ESPN_WEB = "https://site.web.api.espn.com/apis/common/v3/sports"

LEAGUE_MAP = {
    "nfl":    ("football",   "nfl"),
    "nba":    ("basketball", "nba"),
    "mlb":    ("baseball",   "mlb"),
    "nhl":    ("hockey",     "nhl"),
    "epl":    ("soccer",     "eng.1"),
    "laliga": ("soccer",     "esp.1"),
    "ucl":    ("soccer",     "uefa.champions"),
    "mls":    ("soccer",     "usa.1"),
}

_cache: dict = {}
HEADERS = {"User-Agent": "Mozilla/5.0 (compatible; ArbAI/1.0)"}


def _get(url: str, params: dict = None, ttl: int = 30) -> dict:
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
        print(f"[ESPN] {url} → {e}")
        return {}


def _path(sport: str):
    return LEAGUE_MAP.get(sport, ("football", "nfl"))


# ── Moneyline → implied win probability ──────────────────────────────────────

def ml_to_prob(ml) -> float | None:
    """Convert American moneyline to implied win probability (0–1)."""
    try:
        ml = float(str(ml).replace("+", "").strip())
        if ml == 0:
            return None
        if ml > 0:
            return round(100 / (ml + 100), 4)
        else:
            return round(abs(ml) / (abs(ml) + 100), 4)
    except Exception:
        return None


# ── Form from real schedule ───────────────────────────────────────────────────

def get_team_form(sport: str, team_id: str, n: int = 5) -> dict:
    """
    Fetch last n completed results for a team from ESPN team schedule.
    Returns real W/L array, avg score, form label. Cached 10 min.
    """
    if not team_id:
        return _empty_form()

    s, l = _path(sport)
    data  = _get(f"{ESPN}/{s}/{l}/teams/{team_id}/schedule", ttl=600)
    events = data.get("events", [])

    results, scores = [], []

    for event in reversed(events[-30:]):
        try:
            comp  = (event.get("competitions") or [{}])[0]
            comps = comp.get("competitors", [])
            me    = next((c for c in comps if str(c.get("id", "")) == str(team_id)), None)
            if not me:
                continue

            # Must be a completed game
            status = event.get("status", {}).get("type", {})
            if not status.get("completed", False):
                continue

            score = me.get("score", "")
            won   = me.get("winner", False)

            results.append("W" if won else "L")
            try:
                scores.append(float(score))
            except Exception:
                pass

            if len(results) >= n:
                break
        except Exception:
            continue

    wins   = results.count("W")
    played = len(results)
    avg    = round(st.mean(scores), 1) if scores else 0.0

    if played == 0:
        return _empty_form()

    if wins >= 4:
        label, color = "Excellent", "green"
    elif wins >= 3:
        label, color = "Good", "green"
    elif wins >= 2:
        label, color = "Average", "amber"
    else:
        label, color = "Poor", "red"

    return {
        "results":    results,
        "wins":       wins,
        "losses":     played - wins,
        "played":     played,
        "avg_score":  avg,
        "form_label": label,
        "form_color": color,
    }


def _empty_form() -> dict:
    return {"results": [], "wins": 0, "losses": 0, "played": 0,
            "avg_score": 0.0, "form_label": "Unknown", "form_color": "grey"}


# ── Scoreboard ────────────────────────────────────────────────────────────────

def get_scoreboard(sport: str) -> list:
    s, l = _path(sport)
    return _get(f"{ESPN}/{s}/{l}/scoreboard").get("events", [])


def get_game_summary(sport: str, game_id: str) -> dict:
    s, l = _path(sport)
    return _get(f"{ESPN}/{s}/{l}/summary", {"event": game_id})


def get_team_schedule(sport: str, team_id: str) -> list:
    if not team_id:
        return []
    s, l = _path(sport)
    return _get(f"{ESPN}/{s}/{l}/teams/{team_id}/schedule", ttl=600).get("events", [])


def get_player_gamelog(sport: str, player_id: str) -> dict:
    if not player_id or sport not in LEAGUE_MAP:
        return {}
    s, l = _path(sport)
    return _get(f"{ESPN_WEB}/{s}/{l}/athletes/{player_id}/gamelog", ttl=3600)


def get_team_roster(sport: str, team_id: str) -> list:
    if not team_id or sport not in ("nba", "nfl", "mlb", "nhl"):
        return []
    s, l = _path(sport)
    data = _get(f"{ESPN}/{s}/{l}/teams/{team_id}/roster", ttl=3600)
    players = []
    for item in data.get("athletes", []):
        if isinstance(item, dict) and "items" in item:
            for p in item["items"]:
                cp = _clean_player(p)
                if cp:
                    players.append(cp)
        elif isinstance(item, dict) and item.get("id"):
            cp = _clean_player(item)
            if cp:
                players.append(cp)
    return players


def _clean_player(p: dict) -> dict | None:
    if not p.get("id"):
        return None
    return {
        "id":       p["id"],
        "name":     p.get("displayName", p.get("fullName", "Unknown")),
        "position": p.get("position", {}).get("abbreviation", ""),
        "jersey":   p.get("jersey", ""),
        "headshot": p.get("headshot", {}).get("href", ""),
    }


def get_recent_results(schedule: list, team_id: str, n: int = 5) -> dict:
    """Parse last n completed results from a pre-fetched schedule list."""
    results, scores = [], []
    for event in reversed(schedule[-20:]):
        try:
            comp  = (event.get("competitions") or [{}])[0]
            comps = comp.get("competitors", [])
            me    = next((c for c in comps if str(c.get("id", "")) == str(team_id)), None)
            opp   = next((c for c in comps if str(c.get("id", "")) != str(team_id)), None)
            if not me or not opp:
                continue
            if not event.get("status", {}).get("type", {}).get("completed", False):
                continue
            try:
                scores.append(float(me.get("score") or 0))
            except Exception:
                pass
            results.append("W" if me.get("winner", False) else "L")
            if len(results) >= n:
                break
        except Exception:
            continue

    wins   = results.count("W")
    played = len(results)
    avg    = round(st.mean(scores), 1) if scores else 0.0
    if played == 0:
        return _empty_form()

    return {
        "results":    results,
        "wins":       wins,
        "losses":     played - wins,
        "played":     played,
        "avg_score":  avg,
        "form_label": "Excellent" if wins >= 4 else "Good" if wins >= 3 else "Average" if wins >= 2 else "Poor",
        "form_color": "green"     if wins >= 4 else "green" if wins >= 3 else "amber"  if wins >= 2 else "red",
    }


# ── parse_game — now includes real win_pct from moneyline ────────────────────

def parse_game(event: dict, sport: str, fetch_form: bool = False) -> dict:
    """
    Turn raw ESPN event into a clean game dict.
    Set fetch_form=True to include real W/L form.
    """

    try:
        if not event:
            return {}

        comp = (event.get("competitions") or [{}])[0]

        comps = comp.get("competitors") or []

        home_c = next(
            (c for c in comps if c.get("homeAway") == "home"),
            comps[0] if comps else {}
        )

        away_c = next(
            (c for c in comps if c.get("homeAway") == "away"),
            comps[1] if len(comps) > 1 else {}
        )

        status = event.get("status") or {}

        state = (
            status.get("type", {}) or {}
        ).get("state", "pre")

        # ✅ SAFE ODDS HANDLING
        odds_list = comp.get("odds") or []

        first_odds = odds_list[0] if odds_list else {}

        odds_r = first_odds or {}

        def _team(c):
            c = c or {}

            t = c.get("team") or {}

            return {
                "id": t.get("id", ""),
                "name": t.get("displayName", t.get("name", "TBD")),
                "short": t.get("abbreviation", ""),
                "logo": t.get("logo", ""),
                "color": t.get("color", "333344"),
                "alt": t.get("alternateColor", "666688"),
                "score": c.get("score", ""),
                "record": (c.get("records") or [{}])[0].get("summary", ""),
                "winner": c.get("winner", False),
                "form": [],
            }

        home = _team(home_c)
        away = _team(away_c)

        # ── Real win probability from moneyline ──────────────────────────

        home_ml = (
            (odds_r.get("homeTeamOdds") or {}).get("moneyLine")
        )

        away_ml = (
            (odds_r.get("awayTeamOdds") or {}).get("moneyLine")
        )

        home_prob = ml_to_prob(home_ml)
        away_prob = ml_to_prob(away_ml)

        if home_prob and away_prob:
            total = home_prob + away_prob

            home_win_pct = round((home_prob / total) * 100, 1)
            away_win_pct = round((away_prob / total) * 100, 1)

        elif home_prob:
            home_win_pct = round(home_prob * 100, 1)
            away_win_pct = round((1 - home_prob) * 100, 1)

        else:
            home_win_pct = None
            away_win_pct = None

        # ── Real form ────────────────────────────────────────────────────

        if fetch_form and home["id"] and away["id"]:

            with ThreadPoolExecutor(max_workers=2) as ex:

                fh = ex.submit(get_team_form, sport, home["id"])
                fa = ex.submit(get_team_form, sport, away["id"])

                home_form = fh.result() or {}
                away_form = fa.result() or {}

            home["form"] = home_form.get("results", [])
            away["form"] = away_form.get("results", [])

            home["form_label"] = home_form.get("form_label", "")
            away["form_label"] = away_form.get("form_label", "")

            home["avg_score"] = home_form.get("avg_score", 0)
            away["avg_score"] = away_form.get("avg_score", 0)

        return {
            "id": event.get("id", ""),
            "sport": sport,
            "name": event.get("name", ""),
            "date": event.get("date", ""),
            "status": state,

            "status_detail": (
                status.get("type", {}) or {}
            ).get("shortDetail", ""),

            "home": home,
            "away": away,

            "venue": (
                comp.get("venue") or {}
            ).get("fullName", ""),

            "broadcast": next(
                (
                    b.get("names", [""])[0]
                    for b in comp.get("broadcasts", [])
                    if b.get("names")
                ),
                ""
            ),

            "home_win_pct": home_win_pct,
            "away_win_pct": away_win_pct,

            "espn_odds": {
                "home_ml": home_ml,
                "away_ml": away_ml,
                "over_under": odds_r.get("overUnder", ""),
                "spread": odds_r.get("spread", ""),

                "provider": (
                    odds_r.get("provider") or {}
                ).get("name", "ESPN BET"),
            },
        }

    except Exception as e:
        print(f"[parse_game] {e}")
        return {}

def parse_game_with_form(event: dict, sport: str) -> dict:
    """Convenience wrapper — always fetches real form."""
    return parse_game(event, sport, fetch_form=True)