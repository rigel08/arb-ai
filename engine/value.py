import statistics


VALUE_THRESHOLD = 0.03   # 3% edge
MIN_ODDS        = 1.5
MAX_ODDS        = 15.0
MIN_BOOKS       = 3


TRUSTED_BOOKS = {
    "draftkings", "fanduel", "betmgm", "caesars", "pointsbetus"
}


def normalize_book(bookmaker: str) -> str:
    if not bookmaker:
        return ""
    return (
        bookmaker.lower()
        .replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
    )


def find_value_bets(grouped_data):
    """
    Identify value bets based on price deviation from market median.
    """

    value_bets = []

    for match, bookmakers in grouped_data.items():
        outcome_prices = {}

        for bookmaker, odds in bookmakers.items():
            key = normalize_book(bookmaker)

            # only trusted US books
            if not any(tb in key for tb in TRUSTED_BOOKS):
                continue

            for outcome, price in odds.items():
                if not price:
                    continue

                outcome_prices.setdefault(outcome, []).append((price, bookmaker))

        for outcome, entries in outcome_prices.items():
            if len(entries) < MIN_BOOKS:
                continue

            prices = [p for p, _ in entries]
            median = statistics.median(prices)

            best_price, best_book = max(entries, key=lambda x: x[0])

            if best_price < MIN_ODDS or best_price > MAX_ODDS:
                continue

            edge = (best_price - median) / median

            if edge >= VALUE_THRESHOLD:
                implied_prob   = round(1 / best_price * 100, 1)
                market_implied = round(1 / median * 100, 1)
                edge_pct       = round(edge * 100, 1)

                value_bets.append({
                    "match": match,
                    "type": "value",
                    "outcome": outcome,
                    "best_odds": best_price,
                    "bookmaker": best_book,
                    "market_median": round(median, 3),
                    "edge_percent": edge_pct,
                    "implied_prob": implied_prob,
                    "market_prob": market_implied,
                    "reason": (
                        f"{best_book} offers {best_price} vs median {round(median, 2)} "
                        f"→ +{edge_pct}% edge "
                        f"({implied_prob}% vs {market_implied}%)"
                    )
                })

    value_bets.sort(key=lambda x: x["edge_percent"], reverse=True)
    return value_bets[:10]