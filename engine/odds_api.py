"""
odds_api.py
============
Single source of truth. The Odds API only. No ESPN.

What The Odds API gives us:
  - Every game (NBA, NFL, MLB, NHL, EPL, etc.)
  - H2H moneylines from every bookmaker
  - Spreads (point handicap)
  - Totals (over/under)
  - Player props: points, rebounds, assists, threes, blocks,
    steals, PRA, pass yards, rush yards, strikeouts, etc.
  - All updated every few minutes by the API

What we do with it:
  - Compare prices across books → find best odds
  - Find value: one book offering > 3% above market median
  - Find arb: combined implied prob < 100% across books
  - Build parlays from value picks

QUOTA WARNING:
  Free tier = 500 requests/month.
  - Each sport/endpoint call = 1 request
  - Cache everything aggressively
  - Never auto-refresh the frontend
  - Player props = 1 request per market batch per game (expensive)
"""

import time
import statistics
import requests

BASE = "https://api.the-odds-api.com/v4"

# ── All supported sports ──────────────────────────────────────────────────────
SPORTS = {
    "nba":    "basketball_nba",
    "nfl":    "americanfootball_nfl",
    "mlb":    "baseball_mlb",
    "nhl":    "icehockey_nhl",
    "epl":    "soccer_epl",
    "laliga": "soccer_spain_la_liga",
    "mls":    "soccer_usa_mls",
}
# ── Player prop markets per sport (from official Odds API docs) ───────────────
PROP_MARKETS = {
    "nba": [
        # Core
        "player_points", "player_rebounds", "player_assists",
        "player_threes", "player_blocks", "player_steals",
        # Combos
        "player_points_rebounds_assists", "player_points_rebounds",
        "player_points_assists", "player_rebounds_assists",
        "player_blocks_steals", "player_turnovers",
        # Special
        "player_first_basket", "player_double_double",
    ],
    "nfl": [
        "player_pass_yds", "player_pass_tds", "player_pass_completions",
        "player_rush_yds", "player_rush_attempts",
        "player_reception_yds", "player_receptions",
        "player_anytime_td", "player_rush_reception_yds",
        "player_pass_rush_reception_yds", "player_sacks",
    ],
    "mlb": [
        "pitcher_strikeouts", "pitcher_hits_allowed", "pitcher_earned_runs",
        "pitcher_outs",
        "batter_hits", "batter_total_bases", "batter_rbis",
        "batter_home_runs", "batter_runs_scored", "batter_walks",
        "batter_hits_runs_rbis",
    ],
    "nhl": [
        "player_shots_on_goal", "player_goals", "player_assists",
        "player_points", "player_blocked_shots",
        "player_power_play_points", "player_total_saves",
        "player_goal_scorer_anytime",
    ],
    "epl":    ["player_goal_scorer_anytime", "player_shots_on_target", "player_shots", "player_assists"],
    "laliga": ["player_goal_scorer_anytime", "player_shots_on_target", "player_shots", "player_assists"],
    "ucl":    ["player_goal_scorer_anytime", "player_shots_on_target", "player_shots", "player_assists"],
    "mls":    ["player_goal_scorer_anytime", "player_shots_on_target", "player_shots", "player_assists"],
}

PROP_LABELS = {
    "player_points": "Points", "player_rebounds": "Rebounds",
    "player_assists": "Assists", "player_threes": "3-Pointers",
    "player_blocks": "Blocks", "player_steals": "Steals",
    "player_points_rebounds_assists": "Pts+Reb+Ast",
    "player_points_rebounds": "Pts+Reb", "player_points_assists": "Pts+Ast",
    "player_rebounds_assists": "Reb+Ast", "player_blocks_steals": "Blk+Stl",
    "player_turnovers": "Turnovers", "player_first_basket": "First Basket",
    "player_double_double": "Double-Double",
    "player_pass_yds": "Pass Yards", "player_pass_tds": "Pass TDs",
    "player_pass_completions": "Completions", "player_rush_yds": "Rush Yards",
    "player_rush_attempts": "Rush Attempts", "player_reception_yds": "Rec Yards",
    "player_receptions": "Receptions", "player_anytime_td": "Anytime TD",
    "player_rush_reception_yds": "Rush+Rec Yds",
    "player_pass_rush_reception_yds": "Pass+Rush+Rec Yds",
    "player_sacks": "Sacks",
    "pitcher_strikeouts": "Strikeouts", "pitcher_hits_allowed": "Hits Allowed",
    "pitcher_earned_runs": "Earned Runs", "pitcher_outs": "Outs",
    "batter_hits": "Hits", "batter_total_bases": "Total Bases",
    "batter_rbis": "RBIs", "batter_home_runs": "Home Runs",
    "batter_runs_scored": "Runs Scored", "batter_walks": "Walks",
    "batter_hits_runs_rbis": "Hits+Runs+RBIs",
    "player_shots_on_goal": "Shots on Goal", "player_goals": "Goals",
    "player_blocked_shots": "Blocked Shots", "player_total_saves": "Saves",
    "player_power_play_points": "PP Points",
    "player_goal_scorer_anytime": "Anytime Goalscorer",
    "player_shots_on_target": "Shots on Target", "player_shots": "Shots",
}

# ── Cache — aggressive to protect quota ──────────────────────────────────────
_cache: dict = {}
TTL_ODDS  = 1800     # 30 minutes
TTL_PROPS = 21600    # 6 hours  


def _get(url: str, params: dict, ttl: int):
    key = url + str(sorted(params.items()))
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < ttl:
        return _cache[key]["data"]
    try:
        r = requests.get(url, params=params, timeout=12)
        used      = r.headers.get("x-requests-used", "?")
        remaining = r.headers.get("x-requests-remaining", "?")
        print(f"[OddsAPI] {params.get('markets','events')} | used:{used} remaining:{remaining}")
        if r.status_code in (401, 429):

            if remaining == "0" or r.status_code == 401:
                print("[OddsAPI] OUT OF QUOTA — using cached data")

            # KEEP OLD CACHE INSTEAD OF WIPING IT
            if key in _cache:
                return _cache[key]["data"]

            return []

        if r.status_code == 422:

            # KEEP OLD CACHE
            if key in _cache:
                return _cache[key]["data"]

            return []
        r.raise_for_status()
        data = r.json()
        _cache[key] = {"data": data, "ts": now}
        return data
    except Exception as e:
        print(f"[OddsAPI] ERROR: {e}")
        return None


# ── Public fetch functions ────────────────────────────────────────────────────

def get_odds(api_key: str, sport: str, markets: str = "h2h,spreads,totals") -> list:
    """H2H + spreads + totals from all books for all games in a sport."""
    slug = SPORTS.get(sport, sport)
    return _get(f"{BASE}/sports/{slug}/odds", {
        "apiKey": api_key, "regions": "us",
        "markets": markets, "oddsFormat": "decimal", "dateFormat": "iso",
    }, TTL_ODDS) or []


def get_event_props(api_key: str, sport: str, event_id: str) -> dict:
    """
    ALL player prop markets for one specific game.
    Batches markets into groups of 4 to save quota.
    Returns: {player_name: [list of prop dicts]}
    """
    markets_list = PROP_MARKETS.get(sport, [])
    if not markets_list:
        return {}

    slug     = SPORTS.get(sport, sport)
    raw_list = []
    BATCH    = 4  # 4 markets per call

    for i in range(0, len(markets_list), BATCH):
        batch = ",".join(markets_list[i:i + BATCH])
        data  = _get(
            f"{BASE}/sports/{slug}/events/{event_id}/odds",
            {"apiKey": api_key, "regions": "us", "markets": batch,
             "oddsFormat": "decimal", "dateFormat": "iso"},
            TTL_PROPS,
        )
        if data and isinstance(data, dict):
            raw_list.append(data)

    return _parse_props(raw_list)


def _parse_props(raw_list: list) -> dict:
    """
    Parse raw Odds API prop responses into clean player-keyed dict.
    Each player gets a list of props, each prop has:
      stat, line, best_over, best_under, best_over_book, best_under_book,
      market median, value edge %, all books comparison table
    """
    # {(player, market, line_str): {over: {book: price}, under: {book: price}}}
    raw: dict = {}

    for data in raw_list:
        if not data:
            continue
        for book in data.get("bookmakers", []):
            bname = book.get("title", "")
            for market in book.get("markets", []):
                mkey = market.get("key", "")
                for outcome in market.get("outcomes", []):
                    player = outcome.get("description", "")  # player name is here
                    name   = outcome.get("name", "")         # "Over" / "Under" / "Yes" / "No"
                    point  = outcome.get("point")            # the line e.g. 24.5
                    price  = outcome.get("price", 0)

                    if not player or not price:
                        continue

                    line_key = str(point) if point is not None else "yn"
                    key      = (player, mkey, line_key)

                    if key not in raw:
                        raw[key] = {
                            "player": player, "market": mkey,
                            "stat":   PROP_LABELS.get(mkey, mkey),
                            "line":   point, "is_yn": point is None,
                            "over": {}, "under": {}, "yes": {}, "no": {},
                        }

                    side = name.lower()
                    if side in raw[key]:
                        raw[key][side][bname] = float(price)

    # Build clean player dict
    players: dict = {}

    for (player, market, _), d in raw.items():
        best_over  = max(d["over"].values())  if d["over"]  else None
        best_under = max(d["under"].values()) if d["under"] else None
        best_yes   = max(d["yes"].values())   if d["yes"]   else None
        best_no    = max(d["no"].values())    if d["no"]    else None

        best_over_book  = max(d["over"],  key=d["over"].get)  if d["over"]  else None
        best_under_book = max(d["under"], key=d["under"].get) if d["under"] else None

        # Market median (remove vig reference point)
        med_over  = round(statistics.median(list(d["over"].values())),  3) if len(d["over"])  > 1 else best_over
        med_under = round(statistics.median(list(d["under"].values())), 3) if len(d["under"]) > 1 else best_under

        # Value edge: best odds vs median
        over_edge  = round((best_over  / med_over  - 1) * 100, 1) if best_over  and med_over  and med_over  > 0 else 0
        under_edge = round((best_under / med_under - 1) * 100, 1) if best_under and med_under and med_under > 0 else 0
        value_side = "over" if over_edge >= 3 else ("under" if under_edge >= 3 else None)

        num_books = max(len(d["over"]), len(d["under"]), len(d["yes"]), len(d["no"]))

        prop = {
            "market": market, "stat": d["stat"],
            "line": d["line"], "is_yn": d["is_yn"],
            "best_over": best_over, "best_under": best_under,
            "best_yes": best_yes,   "best_no": best_no,
            "best_over_book": best_over_book,
            "best_under_book": best_under_book,
            "med_over": med_over, "med_under": med_under,
            "over_edge": over_edge, "under_edge": under_edge,
            "value_side": value_side, "num_books": num_books,
            "all_over":  dict(sorted(d["over"].items(),  key=lambda x: -x[1])),
            "all_under": dict(sorted(d["under"].items(), key=lambda x: -x[1])),
            "all_yes":   dict(sorted(d["yes"].items(),   key=lambda x: -x[1])),
            "all_no":    dict(sorted(d["no"].items(),    key=lambda x: -x[1])),
        }

        if player not in players:
            players[player] = []
        players[player].append(prop)

    # Sort each player's props: value first, then by liquidity
    for p in players:
        players[p].sort(key=lambda x: (x["value_side"] is None, -x["num_books"]))

    return players


# ── Parse raw Odds API event into a clean game dict ───────────────────────────

def parse_event(ev: dict, sport: str) -> dict:
    """
    Turns one raw Odds API event into a clean dict with:
    - Teams, start time, live status
    - H2H: best odds + all books for home/away/draw
    - Spreads: best line per side
    - Totals: best O/U line
    - Arb detection
    - Value pick detection (>3% above market median)
    """
    from datetime import datetime, timezone

    home = ev.get("home_team", "Home")
    away = ev.get("away_team", "Away")

    start = ev.get("commence_time", "")
    live  = False
    try:
        dt   = datetime.fromisoformat(start.replace("Z", "+00:00"))
        live = dt <= datetime.now(timezone.utc)
    except Exception:
        pass

    h2h   = {"home": {}, "away": {}, "draw": {}}
    sprd  = {"home": {}, "away": {}}
    tots  = {"over": {}, "under": {}}

    for book in ev.get("bookmakers", []):
        bn = book.get("title", "")
        for mkt in book.get("markets", []):
            k = mkt.get("key", "")
            for o in mkt.get("outcomes", []):
                nm = o.get("name", "")
                pr = float(o.get("price", 0))
                pt = o.get("point")
                if not pr:
                    continue
                if k == "h2h":
                    if nm == home:      h2h["home"][bn] = pr
                    elif nm == away:    h2h["away"][bn] = pr
                    elif nm == "Draw":  h2h["draw"][bn] = pr
                elif k == "spreads":
                    if nm == home:      sprd["home"][bn] = {"odds": pr, "point": pt}
                    elif nm == away:    sprd["away"][bn] = {"odds": pr, "point": pt}
                elif k == "totals":
                    nl = nm.lower()
                    if nl == "over":    tots["over"][bn]  = {"odds": pr, "point": pt}
                    elif nl == "under": tots["under"][bn] = {"odds": pr, "point": pt}

    def _best(d):   return max(d.values()) if d else None
    def _bbook(d):  return max(d, key=d.get) if d else None
    def _med(d):    return round(statistics.median(list(d.values())), 3) if len(d) > 1 else (list(d.values())[0] if d else None)

    h_best = _best(h2h["home"]); a_best = _best(h2h["away"]); d_best = _best(h2h["draw"])
    h_med  = _med(h2h["home"]);  a_med  = _med(h2h["away"])

    # Arb detection
    arb = None
    if h_best and a_best:
        legs = [(home, h_best, _bbook(h2h["home"])), (away, a_best, _bbook(h2h["away"]))]
        if d_best:
            legs.append(("Draw", d_best, _bbook(h2h["draw"])))
        arb_sum = sum(1 / l[1] for l in legs)
        if arb_sum < 1.0:
            arb = {
                "profit_pct": round((1 - arb_sum) / arb_sum * 100, 2),
                "legs": [{"outcome": l[0], "odds": l[1], "bookmaker": l[2]} for l in legs],
            }

    # Value pick
    h_edge = round((h_best / h_med - 1) * 100, 1) if h_best and h_med else 0
    a_edge = round((a_best / a_med - 1) * 100, 1) if a_best and a_med else 0
    value_pick = None
    if h_edge >= 3:
        conf = "HIGH" if h_edge >= 7 else "MEDIUM" if h_edge >= 4 else "LOW"
        value_pick = {"team": home, "side": "home", "odds": h_best,
                      "book": _bbook(h2h["home"]), "edge": h_edge, "confidence": conf}
    elif a_edge >= 3:
        conf = "HIGH" if a_edge >= 7 else "MEDIUM" if a_edge >= 4 else "LOW"
        value_pick = {"team": away, "side": "away", "odds": a_best,
                      "book": _bbook(h2h["away"]), "edge": a_edge, "confidence": conf}

    # Best total line
    total_line = None
    if tots["over"]:
        pts = [v["point"] for v in tots["over"].values() if v.get("point")]
        if pts:
            total_line = max(set(pts), key=pts.count)

    # Best spread per side
    best_spread = {}
    for side in ("home", "away"):
        if sprd[side]:
            best_book = max(sprd[side], key=lambda b: sprd[side][b]["odds"])
            best_spread[side] = {
                "book": best_book,
                "odds": sprd[side][best_book]["odds"],
                "point": sprd[side][best_book]["point"],
            }

    return {
        "id":          ev.get("id", ""),
        "sport":       sport,
        "league":      ev.get("sport_title", ""),
        "home":        home,
        "away":        away,
        "start_time":  start,
        "live":        live,
        "num_books":   len(ev.get("bookmakers", [])),
        "h2h": {
            "home": {"all": h2h["home"], "best": h_best, "best_book": _bbook(h2h["home"]), "median": h_med},
            "away": {"all": h2h["away"], "best": a_best, "best_book": _bbook(h2h["away"]), "median": a_med},
            "draw": {"all": h2h["draw"], "best": d_best, "best_book": _bbook(h2h["draw"]), "median": _med(h2h["draw"])},
        },
        "totals":      {"line": total_line, "over": tots["over"], "under": tots["under"]},
        "spreads":     best_spread,
        "arb":         arb,
        "value_pick":  value_pick,
    }


# ── Picks: value bets + arb + parlays from parsed games ──────────────────────

def find_value(games: list, bankroll: float = 1000) -> dict:
    value_picks, arb_picks = [], []

    for g in games:
        vp = g.get("value_pick")
        if vp:
            pct   = 0.15 if vp["confidence"] == "HIGH" else 0.10 if vp["confidence"] == "MEDIUM" else 0.05
            side  = "home" if vp["side"] == "home" else "away"
            all_b = g["h2h"][side]["all"]
            value_picks.append({
                "game":       f"{g['away']} vs {g['home']}",
                "league":     g["league"], "sport": g["sport"],
                "pick":       f"{vp['team']} to Win",
                "team":       vp["team"], "odds": vp["odds"],
                "bookmaker":  vp["book"], "edge_pct": vp["edge"],
                "confidence": vp["confidence"],
                "stake":      round(bankroll * pct),
                "all_books":  all_b, "live": g["live"],
            })

        if g.get("arb"):
            arb_picks.append({
                "game":       f"{g['away']} vs {g['home']}",
                "league":     g["league"], "sport": g["sport"],
                "profit_pct": g["arb"]["profit_pct"],
                "legs":       g["arb"]["legs"], "live": g["live"],
            })

    value_picks.sort(key=lambda x: -x["edge_pct"])
    arb_picks.sort(key=lambda x: -x["profit_pct"])

    # Parlays
    seen, unique = set(), []
    for p in value_picks:
        if p["game"] not in seen:
            seen.add(p["game"]); unique.append(p)

    parlays = []
    top = unique[:6]
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            o = round(top[i]["odds"] * top[j]["odds"], 2)
            s = round(bankroll * 0.05)
            parlays.append({"legs": [top[i], top[j]], "odds": o,
                            "stake": s, "payout": round(s * o, 2),
                            "profit": round(s * o - s, 2)})
    for i in range(min(5, len(top))):
        for j in range(i + 1, min(5, len(top))):
            for k in range(j + 1, min(5, len(top))):
                o = round(top[i]["odds"] * top[j]["odds"] * top[k]["odds"], 2)
                s = round(bankroll * 0.03)
                parlays.append({"legs": [top[i], top[j], top[k]], "odds": o,
                                "stake": s, "payout": round(s * o, 2),
                                "profit": round(s * o - s, 2)})
    parlays.sort(key=lambda x: -x["profit"])

    return {
        "value_picks": value_picks,
        "arb_picks":   arb_picks,
        "parlays":     parlays[:5],
    }