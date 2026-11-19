"""
stake_fetch.py — Live odds using The Odds API.
Replaced StakeAPI (SSL issues on macOS/Python 3.13).
Same interface — app.py and odds.html need zero changes.

Covers all major sports with real live + upcoming odds.
"""

import time
import requests

BASE = "https://api.the-odds-api.com/v4"

# All sports we want to show in the odds dashboard
# Key = our internal slug (matches the sport tabs in odds.html)
# Value = The Odds API sport key
SPORT_MAP = {
    "football":           "soccer_epl",
    "american-football":  "americanfootball_nfl",
    "basketball":         "basketball_nba",
    "baseball":           "baseball_mlb",
    "ice-hockey":         "icehockey_nhl",
    "mma":                "mma_mixed_martial_arts",
    "tennis":             "tennis_atp_wimbledon",   # changes by tournament
    "soccer-laliga":      "soccer_spain_la_liga",
    "soccer-ucl":         "soccer_uefa_champions_league",
    "soccer-bundesliga":  "soccer_germany_bundesliga",
    "soccer-serie-a":     "soccer_italy_serie_a",
    "soccer-mls":         "soccer_usa_mls",
    "soccer-ligue1":      "soccer_france_ligue_one",
}
STAKE_SPORTS = SPORT_MAP
SPORT_TO_STAKE = SPORT_MAP

SPORT_LABELS = {
    "football":           "Soccer — EPL",
    "american-football":  "NFL / American Football",
    "basketball":         "NBA / Basketball",
    "baseball":           "MLB / Baseball",
    "ice-hockey":         "NHL / Ice Hockey",
    "mma":                "MMA / UFC",
    "tennis":             "Tennis",
    "soccer-laliga":      "La Liga",
    "soccer-ucl":         "Champions League",
    "soccer-bundesliga":  "Bundesliga",
    "soccer-serie-a":     "Serie A",
    "soccer-mls":         "MLS",
    "soccer-ligue1":      "Ligue 1",
}

_cache: dict = {}
TTL = 30   # 30s cache — be respectful of API quota


def _fetch_sport(api_key: str, slug: str, odds_key: str) -> list[dict]:
    """Fetch odds for one sport from The Odds API."""
    cache_key = f"odds_{slug}"
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key]["ts"] < TTL:
        return _cache[cache_key]["data"]

    try:
        url = f"{BASE}/sports/{odds_key}/odds"
        params = {
            "apiKey":      api_key,
            "regions":     "us,uk,eu",
            "markets":     "h2h",
            "oddsFormat":  "decimal",
            "dateFormat":  "iso",
        }
        r = requests.get(url, params=params, timeout=10)

        if r.status_code == 422:
            # Sport not currently in season / no events
            _cache[cache_key] = {"data": [], "ts": now}
            return []

        r.raise_for_status()
        raw = r.json()
        events = [_parse_event(ev, slug) for ev in raw]
        events = [e for e in events if e]

        _cache[cache_key] = {"data": events, "ts": now}
        return events

    except Exception as e:
        print(f"[odds:{slug}] {e}")
        return []


def _parse_event(ev: dict, slug: str) -> dict | None:
    """Turn raw Odds API event into our standard format."""
    try:
        home = ev.get("home_team", "")
        away = ev.get("away_team", "")

        # Find h2h market with best odds per outcome
        outcomes_map = {}  # outcome_name → best decimal odds seen

        for book in ev.get("bookmakers", [])[:6]:
            for market in book.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                for o in market.get("outcomes", []):
                    name  = o.get("name", "")
                    price = float(o.get("price", 0))
                    if name and price > 0:
                        if name not in outcomes_map or price > outcomes_map[name]:
                            outcomes_map[name] = price

        if not outcomes_map:
            return None

        # Build outcomes list — home, draw, away order
        ORDER = {home: 0, "Draw": 1, away: 2}
        outcomes = []
        for name, odds in outcomes_map.items():
            implied = round(100 / odds, 2) if odds > 0 else 0
            outcomes.append({
                "name":         name,
                "odds":         round(odds, 3),
                "implied_prob": implied,
            })
        outcomes.sort(key=lambda x: ORDER.get(x["name"], 5))

        # Margin
        total_implied = sum(1 / o["odds"] for o in outcomes if o["odds"] > 0)
        margin = round((total_implied - 1) * 100, 2)

        # Is live?
        from datetime import datetime, timezone
        start = ev.get("commence_time", "")
        is_live = False
        try:
            dt = datetime.fromisoformat(start.replace("Z", "+00:00"))
            is_live = dt <= datetime.now(timezone.utc)
        except Exception:
            pass

        home_odds = outcomes_map.get(home)
        away_odds = outcomes_map.get(away)
        draw_odds = outcomes_map.get("Draw")

        return {
            "id":          ev.get("id", ""),
            "sport_slug":  slug,
            "sport_label": SPORT_LABELS.get(slug, slug),
            "league":      ev.get("sport_title", ""),
            "home":        home,
            "away":        away,
            "match":       f"{home} vs {away}",
            "start_time":  start,
            "status":      "live" if is_live else "upcoming",
            "live":        is_live,
            "outcomes":    outcomes,
            "margin":      margin,
            "home_odds":   home_odds,
            "away_odds":   away_odds,
            "draw_odds":   draw_odds,
            "bookmakers":  len(ev.get("bookmakers", [])),
        }
    except Exception as e:
        print(f"[parse_event] {e}")
        return None


def _get_all_sports(api_key: str) -> list[dict]:
    """Fetch list of currently active sports from The Odds API."""
    cache_key = "sports_list"
    now = time.time()
    if cache_key in _cache and now - _cache[cache_key]["ts"] < 300:
        return _cache[cache_key]["data"]
    try:
        r = requests.get(f"{BASE}/sports", params={"apiKey": api_key}, timeout=8)
        r.raise_for_status()
        data = r.json()
        _cache[cache_key] = {"data": data, "ts": now}
        return data
    except Exception:
        return []


def fetch_stake_odds(api_key: str, sport_slug: str = None) -> dict:
    """
    Main entry point. Returns dict keyed by sport_slug → list of events.
    Fetches concurrently using threads.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed

    slugs = [sport_slug] if sport_slug and sport_slug in SPORT_MAP else list(SPORT_MAP.keys())

    result = {}
    with ThreadPoolExecutor(max_workers=6) as ex:
        futures = {
            ex.submit(_fetch_sport, api_key, slug, SPORT_MAP[slug]): slug
            for slug in slugs
        }
        for fut in as_completed(futures):
            slug = futures[fut]
            try:
                result[slug] = fut.result()
            except Exception:
                result[slug] = []

    return result


def get_live_events(api_key: str, sport_slug: str = None) -> list[dict]:
    data = fetch_stake_odds(api_key, sport_slug)
    live = []
    for events in data.values():
        live.extend(e for e in events if e["live"])
    live.sort(key=lambda x: x["sport_label"])
    return live


def get_all_events_flat(api_key: str, sport_slug: str = None) -> list[dict]:
    data = fetch_stake_odds(api_key, sport_slug)
    flat = []
    for events in data.values():
        flat.extend(events)
    flat.sort(key=lambda x: (not x["live"], x["margin"] or 99))
    return flat


def get_best_value(api_key: str, sport_slug: str = None, top_n: int = 20) -> list[dict]:
    flat = get_all_events_flat(api_key, sport_slug)
    with_margin = [e for e in flat if e["margin"] is not None]
    with_margin.sort(key=lambda x: x["margin"])
    return with_margin[:top_n]