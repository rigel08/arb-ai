import time
import requests
from config import API_KEY


SPORTS = {
    "nfl":   "https://api.the-odds-api.com/v4/sports/americanfootball_nfl/odds",
    "nba":   "https://api.the-odds-api.com/v4/sports/basketball_nba/odds",
    "mlb":   "https://api.the-odds-api.com/v4/sports/baseball_mlb/odds",
    "nhl":   "https://api.the-odds-api.com/v4/sports/icehockey_nhl/odds",
    "ncaaf": "https://api.the-odds-api.com/v4/sports/americanfootball_ncaaf/odds",
}

US_BOOKMAKERS = (
    "draftkings,fanduel,betmgm,caesars,"
    "pointsbetus,williamhill_us,bovada,mybookieag,betonlineag,lowvig"
)

# ✅ CACHE
_CACHE = {}
CACHE_TTL = 1800  # 30 minutes


def fetch_odds(sport="nfl", retries=1):
    """
    Fetch odds from The Odds API for a given sport.
    Returns raw API data.
    """

    now = time.time()

    # ✅ Return cached data if still fresh
    if sport in _CACHE:
        cached = _CACHE[sport]

        if now - cached["time"] < CACHE_TTL:
            print(f"⚡ Using cached odds for {sport}")
            return cached["data"]

    url = SPORTS.get(sport, SPORTS["nfl"])

    params = {
        "apiKey": API_KEY,
        "regions": "us",
        "markets": "h2h,totals,spreads",
        "bookmakers": US_BOOKMAKERS,
        "oddsFormat": "decimal",
    }

    for attempt in range(retries + 1):
        try:
            response = requests.get(url, params=params, timeout=10)

            if response.status_code != 200:
                raise Exception(f"API error {response.status_code}: {response.text}")

            data = response.json()

            # attach sport to each match
            for match in data:
                match["sport"] = sport

            # ✅ Save to cache
            _CACHE[sport] = {
                "time": now,
                "data": data
            }

            print(f"🔥 Fresh odds fetched for {sport}")

            return data

        except Exception as e:
            if attempt < retries:
                time.sleep(1)
                continue

            raise Exception(f"Failed to fetch odds: {str(e)}")