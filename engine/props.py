"""
props.py — Player props engine.
Pulls real ESPN gamelogs, calculates hit rates, trends, averages.
Covers NBA, NFL, MLB, NHL.
"""

import statistics as st
from engine.stats import get_team_roster, get_player_gamelog

# ── Sport-specific prop definitions ──────────────────────────────────────────

PROP_DEFS = {
    "nba": [
        {"key": "PTS",  "label": "Points",        "over_lines": [10, 15, 20, 25, 30]},
        {"key": "REB",  "label": "Rebounds",       "over_lines": [4, 6, 8, 10, 12]},
        {"key": "AST",  "label": "Assists",        "over_lines": [3, 5, 7, 9]},
        {"key": "3PM",  "label": "Three-Pointers", "over_lines": [1, 2, 3, 4]},
        {"key": "STL",  "label": "Steals",         "over_lines": [1, 2]},
        {"key": "BLK",  "label": "Blocks",         "over_lines": [1, 2]},
    ],
    "nfl": [
        {"key": "PYDS", "label": "Passing Yards",   "over_lines": [150, 200, 250, 300, 350]},
        {"key": "RYDS", "label": "Rushing Yards",   "over_lines": [30, 50, 75, 100]},
        {"key": "RECYDS","label": "Receiving Yards","over_lines": [30, 50, 75, 100]},
        {"key": "REC",  "label": "Receptions",      "over_lines": [2, 4, 5, 6]},
        {"key": "PTD",  "label": "Pass TDs",        "over_lines": [1, 2]},
    ],
    "mlb": [
        {"key": "H",    "label": "Hits",            "over_lines": [0.5, 1.5]},
        {"key": "RBI",  "label": "RBI",             "over_lines": [0.5, 1.5]},
        {"key": "HR",   "label": "Home Runs",       "over_lines": [0.5]},
        {"key": "TB",   "label": "Total Bases",     "over_lines": [1.5, 2.5]},
        {"key": "SO",   "label": "Strikeouts (P)",  "over_lines": [4, 5, 6, 7]},
    ],
    "nhl": [
        {"key": "G",    "label": "Goals",           "over_lines": [0.5]},
        {"key": "A",    "label": "Assists",         "over_lines": [0.5]},
        {"key": "PTS",  "label": "Points",          "over_lines": [0.5, 1.5]},
        {"key": "SOG",  "label": "Shots on Goal",   "over_lines": [1.5, 2.5]},
        {"key": "SV",   "label": "Saves",           "over_lines": [20, 25, 30]},
    ],
}

# ESPN gamelog stat label mappings
STAT_MAP = {
    "nba": {"PTS":"points","REB":"rebounds","AST":"assists",
            "3PM":"threePointFieldGoalsMade","STL":"steals","BLK":"blocks"},
    "nfl": {"PYDS":"passingYards","RYDS":"rushingYards",
            "RECYDS":"receivingYards","REC":"receptions","PTD":"passingTouchdowns"},
    "mlb": {"H":"hits","RBI":"RBI","HR":"homeRuns","TB":"totalBases","SO":"strikeouts"},
    "nhl": {"G":"goals","A":"assists","PTS":"points","SOG":"shots","SV":"saves"},
}


# ── Parse ESPN gamelog ────────────────────────────────────────────────────────

def _parse_gamelog(raw: dict, sport: str) -> list[dict]:
    """
    Returns list of {stat_key: value} dicts, one per game (most recent first).
    """
    smap = STAT_MAP.get(sport, {})
    if not smap or not raw:
        return []

    # Find stat labels
    labels = []
    for src in ["labels", "columnHeaders"]:
        if raw.get(src):
            labels = raw[src]
            break

    if not labels:
        # Try deeper path
        cats = raw.get("seasonTypes", [{}])[0].get("categories", [])
        if cats:
            labels = cats[0].get("labels", [])

    if not labels:
        return []

    # Get events
    events = []
    for st_type in raw.get("seasonTypes", []):
        for cat in st_type.get("categories", []):
            for ev in cat.get("events", []):
                stats = ev.get("stats", [])
                if stats:
                    game = {}
                    for i, label in enumerate(labels):
                        if i < len(stats):
                            try:
                                game[label] = float(stats[i])
                            except Exception:
                                game[label] = 0.0
                    if game:
                        events.append(game)

    # Most recent first
    return list(reversed(events))


def _stat_values(games: list[dict], espn_key: str) -> list[float]:
    vals = []
    for g in games:
        v = g.get(espn_key)
        if v is not None:
            vals.append(float(v))
    return vals


def _hit_rate(vals: list[float], line: float) -> float:
    if not vals:
        return 0.0
    hits = sum(1 for v in vals if v > line)
    return round(hits / len(vals) * 100, 1)


def _trend(vals: list[float]) -> str:
    if len(vals) < 3:
        return "neutral"
    recent = st.mean(vals[:3])
    older  = st.mean(vals[3:6]) if len(vals) >= 6 else st.mean(vals)
    diff   = recent - older
    if diff > older * 0.10:
        return "up"
    elif diff < -older * 0.10:
        return "down"
    return "flat"


def _build_prop(stat_key: str, label: str, lines: list,
                all_vals: list[float], last5: list[float],
                last3: list[float]) -> list[dict]:
    if len(all_vals) < 3:
        return []

    avg_all  = round(st.mean(all_vals), 1)
    avg_l5   = round(st.mean(last5),   1) if last5  else avg_all
    avg_l3   = round(st.mean(last3),   1) if last3  else avg_all
    trend    = _trend(all_vals)

    props = []
    for line in lines:
        hr_all = _hit_rate(all_vals, line)
        hr_l5  = _hit_rate(last5,   line) if last5  else hr_all
        hr_l3  = _hit_rate(last3,   line) if last3  else hr_all

        if hr_all < 20 and hr_l5 < 20:
            continue  # boring prop

        recommendation = "over"  if hr_l5 >= 60 else "under" if hr_l5 <= 40 else "neutral"
        strength       = "strong" if abs(hr_l5 - 50) >= 25 else "moderate" if abs(hr_l5 - 50) >= 15 else "weak"

        props.append({
            "stat":           stat_key,
            "label":          label,
            "line":           line,
            "avg_all":        avg_all,
            "avg_last5":      avg_l5,
            "avg_last3":      avg_l3,
            "hit_rate_all":   hr_all,
            "hit_rate_last5": hr_l5,
            "hit_rate_last3": hr_l3,
            "trend":          trend,
            "recommendation": recommendation,
            "strength":       strength,
            "games_analyzed": len(all_vals),
        })
    return props


# ── Main entry point ──────────────────────────────────────────────────────────

def get_player_props(sport: str, team_id: str, limit: int = 8) -> list[dict]:
    """
    Returns top player props for a team with real ESPN gamelog data.
    """
    if sport not in PROP_DEFS:
        return []

    smap     = STAT_MAP.get(sport, {})
    prop_defs = PROP_DEFS[sport]
    roster    = get_team_roster(sport, team_id)

    if not roster:
        return []

    results = []

    for player in roster[:12]:  # Check top 12 players
        pid  = player.get("id")
        name = player.get("name", "Unknown")
        pos  = player.get("position", "")

        raw_log = get_player_gamelog(sport, pid)
        if not raw_log:
            continue

        games = _parse_gamelog(raw_log, sport)
        if len(games) < 3:
            continue

        for pdef in prop_defs:
            espn_key = smap.get(pdef["key"])
            if not espn_key:
                continue

            all_vals = _stat_values(games,       espn_key)
            last5    = _stat_values(games[:5],   espn_key)
            last3    = _stat_values(games[:3],   espn_key)

            if len(all_vals) < 3:
                continue

            built = _build_prop(
                pdef["key"], pdef["label"], pdef["over_lines"],
                all_vals, last5, last3
            )

            for prop in built:
                if prop["strength"] in ("strong", "moderate"):
                    results.append({
                        "player_id":  pid,
                        "player":     name,
                        "position":   pos,
                        "headshot":   player.get("headshot", ""),
                        **prop,
                    })

    # Sort by strength and hit rate
    priority = {"strong": 0, "moderate": 1, "weak": 2}
    results.sort(key=lambda x: (priority[x["strength"]], -abs(x["hit_rate_last5"] - 50)))

    return results[:limit]


def get_game_props(sport: str, home_id: str, away_id: str) -> dict:
    """Get props for both teams in a game."""
    home_props = get_player_props(sport, home_id)
    away_props = get_player_props(sport, away_id)

    # Merge and tag
    for p in home_props:
        p["side"] = "home"
    for p in away_props:
        p["side"] = "away"

    all_props = home_props + away_props
    all_props.sort(key=lambda x: ({"strong":0,"moderate":1,"weak":2}[x["strength"]], -abs(x["hit_rate_last5"]-50)))

    return {
        "home": home_props,
        "away": away_props,
        "top":  all_props[:10],
    }