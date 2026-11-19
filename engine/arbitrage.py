def calculate_stakes(best_odds, total_stake):
    arb_sum = sum(1 / info["price"] for info in best_odds.values())
    outcomes = list(best_odds.keys())

    stakes = {}
    running_total = 0

    for outcome in outcomes[:-1]:
        stake = round(total_stake * (1 / best_odds[outcome]["price"]) / arb_sum, 2)
        stakes[outcome] = stake
        running_total += stake

    # last leg absorbs rounding
    stakes[outcomes[-1]] = round(total_stake - running_total, 2)

    return stakes


def assign_unique_bookmakers(ranked):
    """
    Assign one unique bookmaker per outcome.
    Returns best_odds or None if impossible.
    """
    outcomes = list(ranked.keys())

    assignment = {}
    used_books = set()

    for outcome in outcomes:
        for price, book in ranked[outcome]:
            if book not in used_books:
                assignment[outcome] = (price, book)
                used_books.add(book)
                break
        else:
            return None  # no valid assignment

    return {
        outcome: {"price": price, "bookmaker": book}
        for outcome, (price, book) in assignment.items()
    }


def find_arbitrage(grouped_data, total_stake=1000, min_profit=0.5):
    opportunities = []

    TOP_N = 3
    PAYOUT_TOLERANCE = 0.5

    for match, bookmakers in grouped_data.items():

        # build ranked odds
        ranked = {}
        for bookmaker, odds in bookmakers.items():
            for outcome, price in odds.items():
                ranked.setdefault(outcome, []).append((price, bookmaker))

        # sort best price first
        for outcome in ranked:
            ranked[outcome].sort(key=lambda x: x[0], reverse=True)

        best_odds = assign_unique_bookmakers(ranked)
        if not best_odds:
            continue

        # strict uniqueness check
        books = [info["bookmaker"] for info in best_odds.values()]
        if len(books) != len(set(books)):
            continue

        arb_sum = sum(1 / info["price"] for info in best_odds.values())
        if arb_sum >= 1:
            continue

        profit_percent = round((1 - arb_sum) / arb_sum * 100, 2)
        if profit_percent < min_profit:
            continue

        stakes = calculate_stakes(best_odds, total_stake)

        payouts = {
            outcome: round(stakes[outcome] * info["price"], 2)
            for outcome, info in best_odds.items()
        }

        payout_values = list(payouts.values())

        # ensure near-equal payout
        if max(payout_values) - min(payout_values) > PAYOUT_TOLERANCE:
            continue

        expected_return = min(payout_values)
        profit_amount = round(expected_return - total_stake, 2)

        if profit_amount <= 0:
            continue

        instructions = [
            f"${stakes[outcome]} → {outcome.title()} @ {info['bookmaker']} ({info['price']})"
            for outcome, info in best_odds.items()
        ]

        opportunities.append({
            "match": match,
            "profit_percent": profit_percent,
            "best_odds": best_odds,
            "stakes": stakes,
            "payouts": payouts,
            "total_stake": total_stake,
            "expected_return": expected_return,
            "profit_amount": profit_amount,
            "instructions": instructions
        })

    opportunities.sort(key=lambda x: x["profit_percent"], reverse=True)
    return opportunities[:TOP_N]