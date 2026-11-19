"""
simplify.py — Converts raw arbitrage/value data into beginner-friendly recommendations.
Uses REAL recent form from ESPN instead of fake generated form.
"""

from data.form import get_recent_games


# ── Confidence thresholds ────────────────────────────────────────────────────

def get_confidence(arb=None, value=None):
    if arb:
        p = arb.get("profit_percent", 0)
        if p > 1.5:
            return "high"
        elif p > 0.7:
            return "medium"
        return "low"

    if value:
        e = value.get("edge_percent", 0)
        if e > 8:
            return "high"
        elif e > 4:
            return "medium"
        return "low"

    return "low"


# ── Stake suggestion ─────────────────────────────────────────────────────────

def stake_suggestion(confidence, bankroll):
    pct_map = {
        "high": 0.15,
        "medium": 0.10,
        "low": 0.05
    }

    pct = pct_map.get(confidence, 0.05)

    amount = round(bankroll * pct)
    lo = round(amount * 0.8)
    hi = round(amount * 1.2)

    return {
        "amount": amount,
        "range": f"${lo}–${hi}",
        "percent": int(pct * 100)
    }


# ── Real form helper ─────────────────────────────────────────────────────────

def get_form(team_name: str, sport: str):
    try:
        games = get_recent_games(team_name, sport)

        wins = games.count("W")
        losses = games.count("L")

        if wins >= 4:
            label = "Good form"
        elif wins >= 2:
            label = "Average form"
        else:
            label = "Poor form"

        return {
            "games": games,
            "wins": wins,
            "losses": losses,
            "label": label
        }

    except Exception:
        return {
            "games": [],
            "wins": 0,
            "losses": 0,
            "label": "No data"
        }


def _to_title(s: str) -> str:
    return " ".join(w.capitalize() for w in s.split())


# ── Main simplification logic ────────────────────────────────────────────────

def build_simple_arb(best: dict, bankroll: float, sport: str) -> dict:
    confidence = get_confidence(arb=best)
    stake = stake_suggestion(confidence, bankroll)

    best_outcome = max(
        best["best_odds"].items(),
        key=lambda x: x[1]["price"]
    )

    outcome_name, outcome_info = best_outcome

    teams = [t.strip() for t in best["match"].split(" vs ")]

    reasons = [
        f"Guaranteed profit found across {len(best['best_odds'])} sportsbooks",
        f"Best leg: {_to_title(outcome_name)} @ {outcome_info['price']}",
        f"Expected profit: ${best['profit_amount']}"
    ]

    return {
        "type": "arbitrage",
        "match": best["match"],
        "headline": "Split stake for guaranteed profit",
        "one_liner": "Risk-free return across multiple sportsbooks",
        "confidence": confidence,
        "confidence_label": confidence.upper(),
        "outcome": _to_title(outcome_name),
        "best_odds": outcome_info["price"],
        "bookmaker": outcome_info["bookmaker"],
        "reasons": reasons,
        "stake_suggestion": stake,

        # ✅ REAL FORM
        "form": {
            team: get_form(team, sport)
            for team in teams
        },

        "instructions": best.get("instructions", []),
        "profit_percent": best["profit_percent"],
        "profit_amount": best["profit_amount"],
        "edge_percent": None,
        "raw": best
    }


def build_simple_value(best: dict, bankroll: float, sport: str) -> dict:
    confidence = get_confidence(value=best)
    stake = stake_suggestion(confidence, bankroll)

    outcome = best["outcome"]

    teams = [t.strip() for t in best["match"].split(" vs ")]

    reasons = [
        f"{best['bookmaker']} offering stronger odds than competitors",
        f"Market pricing looks favorable right now",
        f"Worth a smaller value play at {best['best_odds']}"
    ]

    return {
        "type": "value",
        "match": best["match"],
        "headline": f"{_to_title(outcome)} to win",
        "one_liner": "Better odds than the rest of the market",
        "confidence": confidence,
        "confidence_label": confidence.upper(),
        "outcome": _to_title(outcome),
        "best_odds": best["best_odds"],
        "bookmaker": best["bookmaker"],
        "reasons": reasons,
        "stake_suggestion": stake,

        # ✅ REAL FORM
        "form": {
            team: get_form(team, sport)
            for team in teams
        },

        "instructions": [
            f"${stake['amount']} → {_to_title(outcome)} @ {best['bookmaker']}"
        ],

        "profit_percent": None,
        "profit_amount": None,
        "edge_percent": best["edge_percent"],
        "raw": best
    }


# ── Public entry ─────────────────────────────────────────────────────────────

def simplify(arbs, values, bankroll=1000, sport="nba"):
    best = None

    if arbs:
        best = build_simple_arb(arbs[0], bankroll, sport)

    elif values:
        best = build_simple_value(values[0], bankroll, sport)

    return {
        "best": best,
        "all_arbs": arbs,
        "all_values": values
    }