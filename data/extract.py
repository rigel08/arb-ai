def extract_data(data):
    extracted = []

    for match in data:
        home = match.get("home_team")
        away = match.get("away_team")

        if not home or not away:
            continue

        match_name = f"{home} vs {away}"

        for bookmaker in match.get("bookmakers", []):
            bookmaker_name = bookmaker.get("title")

            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue

                odds = {}
                for outcome in market.get("outcomes", []):
                    name = outcome.get("name")
                    price = outcome.get("price")

                    if name and price:
                        odds[name] = price

                if odds:
                    extracted.append({
                        "match": match_name,
                        "bookmaker": bookmaker_name,
                        "odds": odds
                    })

    return extracted