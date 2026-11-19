import re


def normalize_name(name):
    """
    Normalize team names for consistent matching across bookmakers.
    """
    if not name:
        return ""

    name = name.lower()
    name = re.sub(r'\b(fc|club)\b', '', name)
    name = re.sub(r'\s+', ' ', name)  # collapse multiple spaces
    return name.strip()


def normalize_data(data):
    """
    Normalize match names and odds structure.
    """

    normalized = []

    for record in data:
        match = record.get("match")

        # Skip bad format safely
        if not match or " vs " not in match:
            continue

        home, away = match.split(" vs ")

        clean_match = f"{normalize_name(home)} vs {normalize_name(away)}"

        clean_odds = {
            normalize_name(team): price
            for team, price in record.get("odds", {}).items()
            if team and price
        }

        if not clean_odds:
            continue

        normalized.append({
            "match": clean_match,
            "bookmaker": record.get("bookmaker"),
            "odds": clean_odds
        })

    return normalized