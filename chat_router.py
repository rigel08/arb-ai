"""
chat_router.py — AI powered by real picks from every game.
No filtering — every game generates legs the AI can talk about.
"""

import time, httpx, logging
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from config import GROQ_API_KEY

from engine.parlay import get_picks
from engine.stats import get_scoreboard, parse_game
from data.fetch import fetch_odds
from data.extract import extract_data
from data.normalize import normalize_data
from engine.matcher import group_matches
from engine.arbitrage import find_arbitrage
from engine.value import find_value_bets

logger  = logging.getLogger(__name__)
router  = APIRouter()
sessions: dict = {}
MAX_HIST = 15
_cache:  dict  = {}
TTL = 60          # cache picks for 60s — they're expensive to compute

SYSTEM = """You are ArbAI — a sharp, straight-talking sports betting analyst.
You have access to REAL picks data below from a live statistical model.

RULES:
- Always reference ACTUAL picks from the data — real team names, real odds, real reasons
- Never say there are no picks — there are ALWAYS picks in the data
- Be direct and punchy — like a friend texting you hot picks
- Bold the actual pick using **Team/Pick**
- For parlays: list every leg with its odds, then the combined odds

FORMAT for a single pick:
**[Pick]** — [Sport]
[One sentence from real data why]
Odds: [odds] · [HIGH/MEDIUM/LOW] confidence · [prob]% model probability

FORMAT for a parlay:
**Leg 1:** [pick] ([odds])
**Leg 2:** [pick] ([odds])
**Combined:** [total odds] → $[stake] wins $[payout]
[probability]% of hitting

Keep responses under 8 lines unless asked for more detail.
Never show raw code or math. Speak like a human.
"""


def _detect_sport(msg: str):
    m = msg.lower()
    for k, v in [
        ("nba","nba"),("basketball","nba"),
        ("nfl","nfl"),("american football","nfl"),
        ("mlb","mlb"),("baseball","mlb"),
        ("nhl","nhl"),("hockey","nhl"),
        ("epl","epl"),("premier league","epl"),("english","epl"),
        ("laliga","laliga"),("la liga","laliga"),("spanish","laliga"),
        ("ucl","ucl"),("champions league","ucl"),
        ("mls","mls"),
        ("soccer","epl"),("football","epl"),
    ]:
        if k in m:
            return v
    return None


def _build_context(sport, bankroll):
    key = f"{sport or 'all'}_{int(bankroll)}"
    now = time.time()
    if key in _cache and now - _cache[key]["ts"] < TTL:
        return _cache[key]["data"]

    lines = ["=== LIVE PICKS (from prediction model) ===\n"]

    try:
        data    = get_picks(sport=sport, bankroll=bankroll)
        picks   = data.get("best_picks", [])
        parlays = data.get("parlays", [])
        total   = data.get("total_legs", 0)
        scanned = data.get("sports_scanned", [])

        lines.append(f"Scanned: {', '.join(s.upper() for s in scanned)}")
        lines.append(f"Total picks generated: {total}\n")

        if picks:
            lines.append("TOP PICKS:")
            for i, p in enumerate(picks[:8], 1):
                lines.append(
                    f"  {i}. [{p['sport_lbl']}] {p['pick']}"
                    f"  |  odds: {p['odds']}"
                    f"  |  model prob: {p['win_pct']}%"
                    f"  |  confidence: {p['conf_label']}"
                )
                lines.append(f"     Game: {p['game']}")
                lines.append(f"     Why: {p['reason']}")
                if p.get("exp_score"):
                    lines.append(f"     Expected score: {p['exp_score']}")
                if p.get("avg_last5"):
                    lines.append(f"     Player avg L5: {p['avg_last5']}  |  hit rate: {p.get('hit_rate','?')}%  |  trend: {p.get('trend','')}")
                lines.append("")

        if parlays:
            lines.append("TOP PARLAYS:")
            for i, parl in enumerate(parlays[:3], 1):
                lines.append(
                    f"  Parlay #{i} — {parl['leg_count']} legs"
                    f"  |  odds: {parl['odds']}x"
                    f"  |  probability: {parl['probability']}%"
                    f"  |  ${parl['stake']} stake → ${parl['payout']} payout"
                    f"  |  profit: +${parl['profit']}"
                )
                for j, leg in enumerate(parl["legs"], 1):
                    lines.append(
                        f"    Leg {j}: {leg['pick']} ({leg['sport_lbl']})"
                        f"  odds: {leg['odds']}  |  {leg['win_pct']}% prob"
                    )
                lines.append("")

    except Exception as e:
        lines.append(f"[Picks engine error: {e}]")

    # Odds API arb/value as bonus context
    try:
        target = sport or "nfl"
        raw  = fetch_odds(sport=target)
        extr = extract_data(raw)
        norm = normalize_data(extr)
        grp  = group_matches(norm)
        arbs = find_arbitrage(grp, total_stake=bankroll)
        vals = find_value_bets(grp)
        if arbs:
            lines.append(f"ARBITRAGE OPPORTUNITIES ({len(arbs)}):")
            for a in arbs[:2]:
                lines.append(f"  {a['match']}: +{a['profit_percent']}% guaranteed · ${a['profit_amount']} profit")
        if vals:
            lines.append(f"VALUE BETS ({len(vals)}):")
            for v in vals[:3]:
                lines.append(f"  {v['match']} — {v['outcome']} @ {v['best_odds']} on {v['bookmaker']} (+{v['edge_percent']}% edge)")
    except Exception:
        pass

    lines.append(f"\nUser bankroll: ${int(bankroll)}")
    ctx = "\n".join(lines)
    _cache[key] = {"data": ctx, "ts": now}
    return ctx


class ChatRequest(BaseModel):
    message:    str
    session_id: str
    sport:      str | None = None
    bankroll:   float      = 1000


@router.post("/api/chat")
async def chat(req: ChatRequest):
    sid = req.session_id
    if sid not in sessions:
        sessions[sid] = []
    sessions[sid].append({"role": "user", "content": req.message})
    history = sessions[sid][-MAX_HIST:]

    sport   = _detect_sport(req.message) or req.sport
    context = _build_context(sport, req.bankroll)

    messages = [
        {"role": "system", "content": f"{SYSTEM}\n\n{context}"},
        *history,
    ]

    try:
        async with httpx.AsyncClient(timeout=25.0) as client:
            resp = await client.post(
                "https://api.groq.com/openai/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {GROQ_API_KEY}",
                    "Content-Type":  "application/json",
                },
                json={
                    "model":       "llama-3.3-70b-versatile",
                    "messages":    messages,
                    "max_tokens":  600,
                    "temperature": 0.3,
                },
            )
        resp.raise_for_status()
        reply = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"[AI] {e}")
        raise HTTPException(status_code=500, detail="AI request failed")

    sessions[sid].append({"role": "assistant", "content": reply})
    return {"reply": reply}


@router.delete("/api/chat/{session_id}")
def clear_session(session_id: str):
    sessions.pop(session_id, None)
    return {"status": "cleared"}