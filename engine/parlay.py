"""
parlay.py — Picks + parlay builder.
Uses REAL sportsbook odds from Odds API layer.
"""

import math
from concurrent.futures import ThreadPoolExecutor, as_completed

from config import API_KEY

from engine.stats import get_scoreboard, parse_game
from engine.predictor import predict_game
from engine.props import get_player_props

from engine.stake_fetch import get_all_events_flat
def _norm_team(name):
    return (
        (name or "")
        .lower()
        .replace("fc", "")
        .replace("cf", "")
        .replace("sc", "")
        .replace("city", "")
        .replace(".", "")
        .replace("-", " ")
        .replace("  ", " ")
        .strip()
    )


SPORTS = ["nba", "nfl", "mlb", "nhl", "epl", "laliga", "mls", "ucl"]

SPORT_NAMES = {
    "nfl": "NFL",
    "nba": "NBA",
    "mlb": "MLB",
    "nhl": "NHL",
    "epl": "EPL",
    "laliga": "La Liga",
    "ucl": "UCL",
    "mls": "MLS",
}


def _cap(s):
    return " ".join(w.capitalize() for w in (s or "").split())


def _pct_to_decimal(pct: float) -> float:
    pct = max(1.0, min(99.0, pct))
    return round(100 / pct, 3)


def _margin(pct: float) -> float:
    return abs(pct - 50.0)


def _conf_label(pct: float) -> str:
    m = _margin(pct)

    if m >= 18:
        return "HIGH"

    if m >= 8:
        return "MEDIUM"

    return "LOW"


def _winner_reason(team, pct, opp, h_form, a_form, is_home):

    parts = []

    fl = h_form.get("form_label", "") if is_home else a_form.get("form_label", "")

    if fl in ("Excellent", "Good"):

        wins = (h_form if is_home else a_form).get("wins", "?")
        played = (h_form if is_home else a_form).get("played", "?")

        parts.append(f"{team} in {fl.lower()} form ({wins}W/{played})")

    ofl = (a_form if is_home else h_form).get("form_label", "")

    if ofl == "Poor":
        parts.append(f"{opp} struggling recently")

    avg = (h_form if is_home else a_form).get("avg_score", 0)

    if avg:
        parts.append(f"averaging {avg} per game")

    parts.append(f"model gives {team} a {round(pct)}% chance")

    return ". ".join(parts).capitalize() + "."


def _ou_reason(exp_total, line, direction, pct):

    if direction == "over":

        return (
            f"Model projects {exp_total:.1f} total — "
            f"both teams trending towards high scoring. "
            f"{pct}% probability over {line}."
        )

    return (
        f"Model projects {exp_total:.1f} total — "
        f"defensive matchup expected. "
        f"{pct}% probability under {line}."
    )


def _scan_sport(sport: str, market_events) -> list[dict]:

    legs = []

    try:

        # ── FILTER ONLY SAME SPORT EVENTS ──────────────────

        sport_slug_map = {
            "nba": "basketball-nba",
            "nfl": "americanfootball-nfl",
            "mlb": "baseball-mlb",
            "nhl": "icehockey-nhl",
            "epl": "soccer-epl",
            "laliga": "soccer-laliga",
            "mls": "soccer-mls",
            "ucl": "soccer-ucl",
        }

        target_slug = sport_slug_map.get(sport, sport)

        same_sport_events = [
            ev for ev in market_events
            if target_slug in ev.get("sport_slug", "")
        ]

        print(f"[{sport}] matching against {len(same_sport_events)} events")

        # ── ESPN EVENTS ─────────────────────────────────────

        events = get_scoreboard(sport)

        events = [
            e for e in events
            if e.get("status", {}).get("type", {}).get("state", "pre")
            in ("pre", "in")
        ][:10]

        for event in events:

            game = parse_game(event, sport, fetch_form=False)

            if not game:
                continue

            home_id = game["home"]["id"]
            away_id = game["away"]["id"]

            home_name = game["home"]["name"]
            away_name = game["away"]["name"]

            if not home_id or not away_id:
                continue

            game_label = f"{away_name} vs {home_name}"

            slbl = SPORT_NAMES.get(sport, sport.upper())

            # ── MARKET MATCH ─────────────────────────────────

            market = {}

            home_l = _norm_team(home_name)
            away_l = _norm_team(away_name)

            for ev in same_sport_events:

                match_name = ev.get("match", "")

                if " vs " not in match_name:
                    continue

                h_raw, a_raw = match_name.split(" vs ")

                h = _norm_team(h_raw)
                a = _norm_team(a_raw)

                print("COMPARE:", home_l, away_l, "vs", h, a)

                direct_match = (
                    (home_l in h or h in home_l)
                    and
                    (away_l in a or a in away_l)
                )

                reverse_match = (
                    (home_l in a or a in home_l)
                    and
                    (away_l in h or h in away_l)
                )

                if direct_match or reverse_match:

                    market = ev

                    print("✅ MATCH FOUND:", match_name)

                    break

            # ── REAL ODDS ────────────────────────────────────

            home_odds = market.get("home_odds")
            away_odds = market.get("away_odds")
            draw_odds = market.get("draw_odds")

            print("ESPN:", home_name, "vs", away_name)
            print("MARKET:", market)
            print("HOME ODDS:", home_odds)
            print("AWAY ODDS:", away_odds)

            # ── O/U LINE ─────────────────────────────────────

            try:
                ou_raw = game.get("espn_odds", {}).get("over_under")
                ou_line = float(ou_raw) if ou_raw else None

            except Exception:
                ou_line = None

            # ── MODEL ────────────────────────────────────────

            try:

                pred = predict_game(
                    sport,
                    home_id,
                    away_id,
                    home_name,
                    away_name,
                    ou_line,
                )

            except Exception:
                continue

            hw = pred.get("home_win_pct", 50.0)
            aw = pred.get("away_win_pct", 50.0)

            draw = pred.get("draw_pct", 0.0)

            ou_data = pred.get("over_under", {})

            over_p = ou_data.get("over", 50.0)
            under_p = ou_data.get("under", 50.0)

            exp_h = pred.get("expected_home", 0)
            exp_a = pred.get("expected_away", 0)

            exp_tot = exp_h + exp_a

            h_form = pred.get("home_form", {})
            a_form = pred.get("away_form", {})

            conf = pred.get("confidence", 50)

            # ── GAME WINNER ─────────────────────────────────

            if hw >= aw:

                fav = home_name
                fav_pct = hw

                is_home = True

                real_odds = (
                    home_odds
                    or round(_pct_to_decimal(fav_pct) * 0.92, 2)
                )

            else:

                fav = away_name
                fav_pct = aw

                is_home = False

                real_odds = (
                    away_odds
                    or round(_pct_to_decimal(fav_pct) * 0.92, 2)
                )

            # ── DRAW PICK ───────────────────────────────────

            if draw > hw and draw > aw:

                legs.append({
                    "type": "game_winner",
                    "sport": sport,
                    "sport_lbl": slbl,
                    "game": game_label,

                    "pick": "Draw",
                    "team": "Draw",

                    "odds": (
                        draw_odds
                        or round(_pct_to_decimal(draw) * 0.92, 2)
                    ),

                    "win_pct": draw,
                    "margin": _margin(draw),

                    "confidence": conf,
                    "conf_label": _conf_label(draw),

                    "reason": (
                        f"Model favours a draw at "
                        f"{round(draw)}% — evenly matched sides."
                    ),

                    "form": {},

                    "exp_score": f"{exp_h}–{exp_a}",
                    "ou_line": ou_line,
                })

            else:

                legs.append({
                    "type": "game_winner",
                    "sport": sport,
                    "sport_lbl": slbl,

                    "game": game_label,

                    "pick": f"{fav} to Win",
                    "team": fav,

                    "odds": real_odds,

                    "win_pct": fav_pct,
                    "margin": _margin(fav_pct),

                    "confidence": conf,
                    "conf_label": _conf_label(fav_pct),

                    "reason": _winner_reason(
                        fav,
                        fav_pct,
                        away_name if is_home else home_name,
                        h_form,
                        a_form,
                        is_home,
                    ),

                    "form": h_form if is_home else a_form,

                    "exp_score": f"{exp_h}–{exp_a}",
                    "ou_line": ou_line,
                })

    except Exception as e:
        print(f"[scan_sport:{sport}] {e}")

    return legs


def _parlay_odds(legs):

    o = 1.0

    for leg in legs:
        o *= leg.get("odds", 1.91)

    return round(o, 2)


def _parlay_prob(legs):

    p = 1.0

    for leg in legs:
        p *= (leg.get("win_pct", 50) / 100)

    return round(p * 100, 1)


def _build_parlays(legs: list, bankroll: float) -> list:

    seen_games = set()

    unique = []

    for leg in sorted(
        legs,
        key=lambda x: x["margin"],
        reverse=True,
    ):

        gk = leg["game"]

        if gk not in seen_games:

            seen_games.add(gk)

            unique.append(leg)

    parlays = []

    top = unique[:8]

    # 2 LEG

    for i in range(len(top)):

        for j in range(i + 1, len(top)):

            combo = [top[i], top[j]]

            prob = _parlay_prob(combo)
            odds = _parlay_odds(combo)

            stake = round(bankroll * 0.05, 2)

            payout = round(stake * odds, 2)

            parlays.append({

                "legs": combo,

                "leg_count": 2,

                "odds": odds,

                "probability": prob,

                "confidence": min(
                    top[i]["confidence"],
                    top[j]["confidence"],
                ),

                "stake": stake,

                "payout": payout,

                "profit": round(payout - stake, 2),

                "label": (
                    f"{top[i]['sport_lbl']} + "
                    f"{top[j]['sport_lbl']}"
                ),
            })

    # 3 LEG

    for i in range(min(len(top), 6)):

        for j in range(i + 1, min(len(top), 6)):

            for k in range(j + 1, min(len(top), 6)):

                combo = [top[i], top[j], top[k]]

                prob = _parlay_prob(combo)
                odds = _parlay_odds(combo)

                stake = round(bankroll * 0.03, 2)

                payout = round(stake * odds, 2)

                parlays.append({

                    "legs": combo,

                    "leg_count": 3,

                    "odds": odds,

                    "probability": prob,

                    "confidence": min(
                        top[i]["confidence"],
                        top[j]["confidence"],
                        top[k]["confidence"],
                    ),

                    "stake": stake,

                    "payout": payout,

                    "profit": round(payout - stake, 2),

                    "label": (
                        f"{top[i]['sport_lbl']} + "
                        f"{top[j]['sport_lbl']} + "
                        f"{top[k]['sport_lbl']}"
                    ),
                })

    parlays.sort(
        key=lambda p: (
            p["probability"] * math.log(p["odds"] + 1)
        ),
        reverse=True,
    )

    return parlays[:6]


def get_picks(
    sport: str = None,
    bankroll: float = 1000,
) -> dict:

    sports_to_scan = [sport] if sport else SPORTS

    all_legs = []

    # FETCH ODDS API ONCE ONLY
    market_events = get_all_events_flat(API_KEY)

    with ThreadPoolExecutor(max_workers=2) as ex:

        futures = {
            ex.submit(_scan_sport, s, market_events): s
            for s in sports_to_scan
        }

        for fut in as_completed(futures):

            try:

                result = fut.result()

                all_legs.extend(result)

            except Exception as e:
                print(f"[get_picks] thread error: {e}")

    all_legs.sort(
        key=lambda x: x["margin"],
        reverse=True,
    )

    seen = set()

    best_picks = []

    for leg in all_legs:

        key = (
            f"{leg['game']}_"
            f"{leg['type']}_"
            f"{leg.get('player','')}"
        )

        if key not in seen:

            seen.add(key)

            best_picks.append(leg)

        if len(best_picks) >= 12:
            break

    parlays = _build_parlays(all_legs, bankroll)

    return {

        "best_picks": best_picks,

        "parlays": parlays,

        "all_legs": all_legs[:30],

        "sports_scanned": sports_to_scan,

        "total_legs": len(all_legs),
    }