"""Settings, read from environment variables (or a local .env file).

Never commit real keys: .env is ignored by git. See .env.example.
"""
import os
from pathlib import Path

_env_file = Path(__file__).with_name(".env")
if _env_file.exists():
    for _line in _env_file.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _key, _value = _line.split("=", 1)
            os.environ.setdefault(_key.strip(), _value.strip().strip("\"'"))

# The Odds API (https://the-odds-api.com): bookmaker odds for arbitrage, value and live odds.
API_KEY = os.environ.get("ODDS_API_KEY", "")

# Groq (https://console.groq.com): powers the LLM chat assistant.
GROQ_API_KEY = os.environ.get("GROQ_API_KEY", "")

# The live-odds endpoints also read from The Odds API; app.py refers to the key by this name.
STAKE_TOKEN = API_KEY or None
