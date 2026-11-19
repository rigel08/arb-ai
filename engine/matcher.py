def group_matches(data):
    """
    Group odds by match and bookmaker.

    Output:
    {
        "team a vs team b": {
            "DraftKings": {"team a": 2.1, "team b": 1.8},
            "FanDuel":   {"team a": 2.05, "team b": 1.85}
        }
    }
    """

    grouped = {}

    for record in data:
        match = record.get("match")
        bookmaker = record.get("bookmaker")
        odds = record.get("odds")

        # Skip invalid records safely
        if not match or not bookmaker or not odds:
            continue

        # Initialize match bucket
        if match not in grouped:
            grouped[match] = {}

        # Avoid overwriting same bookmaker (rare but possible)
        if bookmaker not in grouped[match]:
            grouped[match][bookmaker] = odds

    return grouped