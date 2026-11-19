"""
predictor.py — Statistical prediction engine.
Always returns a result for every game.
Primary signal: ESPN moneyline (real market odds, most accurate).
Secondary: Poisson/Normal model from historical schedule data.
Falls back gracefully to league baseline if no history.
"""

import math
import statistics as st
from engine.stats import get_team_schedule, get_recent_results, ml_to_prob

BASELINES = {
    "nfl":    {"avg": 23.0, "std": 9.0},
    "nba":    {"avg": 112.0,"std": 12.0},
    "mlb":    {"avg": 4.5,  "std": 2.5},
    "nhl":    {"avg": 2.9,  "std": 1.5},
    "epl":    {"avg": 1.35, "std": 1.2},
    "laliga": {"avg": 1.45, "std": 1.2},
    "ucl":    {"avg": 1.40, "std": 1.2},
    "mls":    {"avg": 1.50, "std": 1.3},
}

SOCCER = {"epl", "laliga", "ucl", "mls"}


# ── Math ──────────────────────────────────────────────────────────────────────

def _poisson_pmf(k, lam):
    if lam <= 0: return 1.0 if k == 0 else 0.0
    try:    return math.exp(-lam) * (lam ** k) / math.factorial(k)
    except: return 0.0


def _norm_cdf(z):
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2)))


def _poisson_win_probs(lam_h, lam_a, max_g=10):
    hw = draw = aw = 0.0
    for h in range(max_g + 1):
        for a in range(max_g + 1):
            p = _poisson_pmf(h, lam_h) * _poisson_pmf(a, lam_a)
            if   h > a:  hw   += p
            elif h == a: draw += p
            else:        aw   += p
    return hw, draw, aw


def _normal_win_probs(mu_h, mu_a, std):
    d_std = std * math.sqrt(2)
    z     = (mu_h - mu_a) / d_std if d_std else 0
    hw    = _norm_cdf(z)
    aw    = _norm_cdf(-z)
    return max(0.02, hw), 0.0, max(0.02, aw)


def _ou_prob(lam_h, lam_a, line, soccer):
    if soccer:
        over = 0.0
        for h in range(15):
            for a in range(15):
                if (h + a) > line:
                    over += _poisson_pmf(h, lam_h) * _poisson_pmf(a, lam_a)
    else:
        mu    = lam_h + lam_a
        sigma = math.sqrt(lam_h**2 + lam_a**2) * 0.55
        z     = (line - mu) / sigma if sigma else 0
        over  = 1 - _norm_cdf(z)
    under = 1 - over
    return {
        "over":  round(max(0.01, min(0.99, over))  * 100, 1),
        "under": round(max(0.01, min(0.99, under)) * 100, 1),
        "line":  line,
    }


def _history(schedule, team_id):
    scored, conceded = [], []
    for event in reversed(schedule[-20:]):
        try:
            comp  = (event.get("competitions") or [{}])[0]
            comps = comp.get("competitors", [])
            me    = next((c for c in comps if str(c.get("id","")) == str(team_id)), None)
            opp   = next((c for c in comps if str(c.get("id","")) != str(team_id)), None)
            if not me or not opp: continue
            if not event.get("status",{}).get("type",{}).get("completed", False): continue
            scored.append(float(me.get("score") or 0))
            conceded.append(float(opp.get("score") or 0))
            if len(scored) >= 10: break
        except: continue
    return scored, conceded


# ── Main ──────────────────────────────────────────────────────────────────────

def predict_game(sport, home_id, away_id, home_name, away_name,
                 ou_line=None, home_ml=None, away_ml=None) -> dict:
    """
    Always returns a full prediction dict.
    Uses market moneyline as primary probability signal when available,
    blends with Poisson/Normal model from schedule history.
    """
    bl      = BASELINES.get(sport, BASELINES["nfl"])
    is_soc  = sport in SOCCER
    league_avg = bl["avg"]

    # ── Real schedule data ────────────────────────────────────────────────
    h_sched = get_team_schedule(sport, home_id)
    a_sched = get_team_schedule(sport, away_id)

    h_sc, h_cn = _history(h_sched, home_id)
    a_sc, a_cn = _history(a_sched, away_id)

    data_pts = min(len(h_sc), len(a_sc), 10)

    h_avg_sc = st.mean(h_sc) if len(h_sc) >= 2 else league_avg
    h_avg_cn = st.mean(h_cn) if len(h_cn) >= 2 else league_avg
    a_avg_sc = st.mean(a_sc) if len(a_sc) >= 2 else league_avg
    a_avg_cn = st.mean(a_cn) if len(a_cn) >= 2 else league_avg

    h_att = h_avg_sc / league_avg if league_avg else 1.0
    h_def = h_avg_cn / league_avg if league_avg else 1.0
    a_att = a_avg_sc / league_avg if league_avg else 1.0
    a_def = a_avg_cn / league_avg if league_avg else 1.0

    home_bonus = 1.08 if is_soc else 1.04
    lam_home   = h_att * a_def * league_avg * home_bonus
    lam_away   = a_att * h_def * league_avg

    # ── Statistical model probabilities ──────────────────────────────────
    if is_soc:
        hw_m, draw_m, aw_m = _poisson_win_probs(lam_home, lam_away)
    else:
        hw_m, draw_m, aw_m = _normal_win_probs(lam_home, lam_away, bl["std"])

    total_m = hw_m + draw_m + aw_m
    if total_m > 0:
        hw_m /= total_m; draw_m /= total_m; aw_m /= total_m

    # ── Market probabilities from moneyline (vig-removed) ─────────────────
    hw_mkt   = ml_to_prob(home_ml) if home_ml else None
    aw_mkt   = ml_to_prob(away_ml) if away_ml else None

    if hw_mkt and aw_mkt:
        total_mkt = hw_mkt + aw_mkt
        hw_mkt  /= total_mkt
        aw_mkt  /= total_mkt
        draw_mkt = max(0.0, 1.0 - hw_mkt - aw_mkt)

        # Blend: 60% market (more accurate), 40% model
        hw    = 0.60 * hw_mkt   + 0.40 * hw_m
        aw    = 0.60 * aw_mkt   + 0.40 * aw_m
        draw  = 0.60 * draw_mkt + 0.40 * draw_m
        blend = "market+model"
    elif hw_mkt:
        hw    = 0.70 * hw_mkt   + 0.30 * hw_m
        aw    = 1.0 - hw
        draw  = draw_m * 0.3
        blend = "market+model"
    else:
        # Pure model
        hw, draw, aw = hw_m, draw_m, aw_m
        blend = "model"

    # Renormalize
    total = hw + draw + aw
    if total > 0:
        hw /= total; draw /= total; aw /= total

    # ── O/U ──────────────────────────────────────────────────────────────
    if ou_line is None:
        ou = {"over": 50.0, "under": 50.0, "line": None}
    else:
        ou = _ou_prob(lam_home, lam_away, ou_line, is_soc)
    

    # ── Form data ─────────────────────────────────────────────────────────
    h_form = get_recent_results(h_sched, home_id)
    a_form = get_recent_results(a_sched, away_id)

    # ── Confidence ────────────────────────────────────────────────────────
    # Based on data available + how far from 50/50
    margin        = abs(max(hw, aw) - 0.5) * 100
    data_conf     = min(40, data_pts * 4)
    margin_conf   = min(40, margin * 2)
    confidence    = int(30 + data_conf + margin_conf)  # 30–100 range

    # ── Favourite ─────────────────────────────────────────────────────────
    best = max(((hw, home_name), (aw, away_name), (draw, "Draw")), key=lambda x: x[0])
    fav_pct, fav = best

    # ── Betting angles ────────────────────────────────────────────────────
    angles = []
    if hw > 0.55:
        angles.append(f"{home_name} favoured at home — {round(hw*100)}% win probability")
    if aw > 0.55:
        angles.append(f"{away_name} favoured — {round(aw*100)}% win probability")
    if draw > 0.30 and is_soc:
        angles.append(f"Draw possible at {round(draw*100)}% — closely matched teams")
    if ou["over"] > 55:
        angles.append(f"Model leans OVER {line} ({ou['over']}% probability)")
    if ou["under"] > 55:
        angles.append(f"Model leans UNDER {line} ({ou['under']}% probability)")
    if h_form.get("form_label") in ("Excellent","Good"):
        angles.append(f"{home_name} in {h_form['form_label'].lower()} form ({h_form.get('wins')}W last {h_form.get('played')})")
    if a_form.get("form_label") in ("Excellent","Good"):
        angles.append(f"{away_name} in {a_form['form_label'].lower()} form ({a_form.get('wins')}W last {a_form.get('played')})")
    if h_form.get("form_label") == "Poor":
        angles.append(f"{home_name} in poor form — {h_form.get('losses')}L last {h_form.get('played')}")
    if a_form.get("form_label") == "Poor":
        angles.append(f"{away_name} in poor form — {a_form.get('losses')}L last {a_form.get('played')}")

    return {
        "home_win_pct":      round(hw   * 100, 1),
        "away_win_pct":      round(aw   * 100, 1),
        "draw_pct":          round(draw * 100, 1),
        "expected_home":     round(lam_home, 1),
        "expected_away":     round(lam_away, 1),
        "over_under":        ou,
        "home_form":         h_form,
        "away_form":         a_form,
        "home_avg_scored":   round(h_avg_sc, 1),
        "away_avg_scored":   round(a_avg_sc, 1),
        "home_avg_conceded": round(h_avg_cn, 1),
        "away_avg_conceded": round(a_avg_cn, 1),
        "favourite":         fav,
        "favourite_pct":     round(fav_pct * 100, 1),
        "confidence":        confidence,
        "model":             "Poisson" if is_soc else "Normal",
        "blend":             blend,
        "data_games":        data_pts,
        "betting_angles":    angles[:4],
    }