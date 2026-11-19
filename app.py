from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
from engine.parlay import get_picks

from data.fetch import fetch_odds
from data.extract import extract_data
from data.normalize import normalize_data
from engine.matcher import group_matches
from engine.arbitrage import find_arbitrage
from engine.value import find_value_bets
from engine.stats import get_scoreboard, get_game_summary, parse_game, parse_game_with_form
from engine.predictor import predict_game
from engine.props import get_game_props
from engine.parlay import get_picks
from engine.stake_fetch import (
    fetch_stake_odds, get_live_events,
    get_all_events_flat, get_best_value,
    STAKE_SPORTS, SPORT_TO_STAKE,
)

from chat_router import router as chat_router

# The live-odds endpoints use The Odds API key (see config.py)
try:
    from config import STAKE_TOKEN
except ImportError:
    STAKE_TOKEN = None

app = FastAPI(title="ArbAI", version="3.1")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

ESPN_SPORTS = ["nfl", "nba", "mlb", "nhl", "epl", "laliga", "ucl", "mls"]


# ── Internal helpers ──────────────────────────────────────────────────────────

def _require_stake():
    if not STAKE_TOKEN:
        raise HTTPException(
            status_code=503,
            detail="ODDS_API_KEY is not set. Add it to .env (see .env.example)."
        )
    return STAKE_TOKEN


def _odds_pipeline(sport: str, stake: float):
    try:
        raw  = fetch_odds(sport=sport)
        extr = extract_data(raw)
        norm = normalize_data(extr)
        grp  = group_matches(norm)
        return find_arbitrage(grp, total_stake=stake), find_value_bets(grp), grp
    except Exception:
        return [], [], {}


# ── EXISTING ENDPOINTS (unchanged) ───────────────────────────────────────────

@app.get("/api/opportunities")
def get_opportunities(sport: str = Query("nfl"), total_stake: float = Query(1000)):
    try:
        arbs, vals, _ = _odds_pipeline(sport, total_stake)
        return {"sport": sport, "arbitrage": arbs, "value_bets": vals}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/games")
def get_all_games(sport: str = Query("nfl")):
    try:
        events = get_scoreboard(sport)
        if not events:
            return {"sport": sport, "count": 0, "games": []}
        games = []
        with ThreadPoolExecutor(max_workers=8) as ex:
            futures = {ex.submit(parse_game_with_form, e, sport): e for e in events}
            for fut in as_completed(futures):
                g = fut.result()
                if g:
                    games.append(g)
        games.sort(key=lambda g: g.get("date", ""))
        try:
            _, vals, _ = _odds_pipeline(sport, 1000)
            vms = {v["match"].lower() for v in vals}
        except Exception:
            vms = set()
        for g in games:
            key = f"{g['away']['name']} vs {g['home']['name']}".lower()
            g["has_value"] = any(
                key in m or m in key or
                g["away"]["name"].lower() in m or
                g["home"]["name"].lower() in m
                for m in vms
            )
        return {"sport": sport, "count": len(games), "games": games}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/game/{sport}/{game_id}")
def get_game_detail(sport: str, game_id: str, bankroll: float = Query(1000)):
    try:
        raw    = get_game_summary(sport, game_id)
        events = get_scoreboard(sport)
        event  = next((e for e in events if str(e.get("id","")) == str(game_id)), None)
        if not event:
            raise HTTPException(status_code=404, detail="Game not found")
        game = parse_game_with_form(event, sport)
        home_id, away_id     = game["home"]["id"], game["away"]["id"]
        home_name, away_name = game["home"]["name"], game["away"]["name"]
        try:    ou_line = float(game.get("espn_odds",{}).get("over_under") or 0) or None
        except: ou_line = None
        prediction = predict_game(sport, home_id, away_id, home_name, away_name, ou_line)
        props      = get_game_props(sport, home_id, away_id)
        try:
            arbs, vals, _ = _odds_pipeline(sport, bankroll)
            key = f"{away_name} vs {home_name}".lower()
            game_arbs = [a for a in arbs if key in a.get("match","").lower()]
            game_vals = [v for v in vals  if key in v.get("match","").lower()]
        except Exception:
            game_arbs, game_vals = [], []
        box = {}
        try:
            for comp in (raw.get("competitions") or []):
                for c in comp.get("competitors", []):
                    tid = c.get("id","")
                    stats = c.get("statistics", [])
                    if stats:
                        box[tid] = [{"name":s.get("name",""),"value":s.get("displayValue","")} for s in stats[:14]]
        except Exception:
            pass
        return {"game":game, "prediction":prediction, "props":props,
                "arbitrage":game_arbs, "value_bets":game_vals, "box_score":box}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/picks")
def picks(sport: str = Query(None), bankroll: float = Query(1000)):
    """
    Best picks + top parlays from advanced parlay engine.
    """
    try:
        return get_picks(sport=sport, bankroll=bankroll)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── LIVE ODDS ENDPOINTS ────────────────────────────────────────────

@app.get("/api/live-odds")
def live_odds_all(sport: str = Query(None, description="Optional sport slug e.g. football, basketball")):
    """
    All sports live + upcoming odds from The Odds API.
    Returns dict keyed by sport slug → list of events with full odds.
    Optional ?sport= to filter to one sport.
    """
    token = _require_stake()
    try:
        slug = SPORT_TO_STAKE.get(sport, sport) if sport else None
        data = fetch_stake_odds(token, slug)
        # Summary stats per sport
        summary = {}
        for s, events in data.items():
            live_count = sum(1 for e in events if e["live"])
            summary[s] = {
                "label":      STAKE_SPORTS.get(s, s),
                "total":      len(events),
                "live":       live_count,
                "upcoming":   len(events) - live_count,
                "events":     events,
            }
        return {
            "source": "The Odds API",
            "sports": summary,
            "total_events": sum(len(v) for v in data.values()),
            "total_live":   sum(1 for v in data.values() for e in v if e["live"]),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/live-odds/{sport_slug}")
def live_odds_sport(sport_slug: str):
    """
    Odds for one specific sport slug (football, basketball, tennis, ice-hockey, etc.)
    """
    token = _require_stake()
    try:
        data   = fetch_stake_odds(token, sport_slug)
        events = data.get(sport_slug, [])
        live   = [e for e in events if e["live"]]
        upcoming = [e for e in events if not e["live"]]
        return {
            "source":     "The Odds API",
            "sport":      sport_slug,
            "label":      STAKE_SPORTS.get(sport_slug, sport_slug),
            "live":       live,
            "upcoming":   upcoming,
            "total":      len(events),
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/live-odds-flat")
def live_odds_flat(sport: str = Query(None), live_only: bool = Query(False)):
    """
    Flat list of all events sorted: live first, then by lowest margin.
    Best for the odds dashboard grid.
    """
    token = _require_stake()
    try:
        slug = SPORT_TO_STAKE.get(sport, sport) if sport else None
        if live_only:
            events = get_live_events(token, slug)
        else:
            events = get_all_events_flat(token, slug)
        return {
            "source": "The Odds API",
            "count":  len(events),
            "events": events,
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/value-odds")
def value_odds(sport: str = Query(None), top: int = Query(20)):
    """
    Events with lowest bookmaker margin — best value for bettors.
    """
    token = _require_stake()
    try:
        slug = SPORT_TO_STAKE.get(sport, sport) if sport else None
        best = get_best_value(token, slug, top_n=top)
        return {"source": "The Odds API", "count": len(best), "events": best}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/sports-list")
def sports_list():
    """All supported sport slugs and their display labels."""
    return {"sports": [{"slug": k, "label": v} for k, v in STAKE_SPORTS.items()]}


@app.get("/api/dashboard")
def get_dashboard():
    result = {}
    for s in ESPN_SPORTS:
        try:
            events = get_scoreboard(s)
            games  = [g for e in events[:4] if (g := parse_game(e, s))]
            arbs, vals, _ = _odds_pipeline(s, 1000)
            result[s] = {"games": games[:4], "arb_count": len(arbs),
                         "value_count": len(vals),
                         "best_arb": arbs[0] if arbs else None,
                         "best_value": vals[0] if vals else None}
        except Exception:
            result[s] = {"games":[],"arb_count":0,"value_count":0,
                         "best_arb":None,"best_value":None}
    return result


app.include_router(chat_router)

# Serve the dashboard pages from the same origin: open http://127.0.0.1:8000/
app.mount("/", StaticFiles(directory=Path(__file__).parent / "frontend", html=True), name="frontend")