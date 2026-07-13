import os

# Comma-separated series prefixes to keep (e.g. "KXATPMATCH,KXWTAMATCH").
# Empty/unset means no filtering — all markets pass through.
TICKER_ALLOW_PREFIXES = tuple(
    p.strip() for p in os.getenv("TICKER_ALLOW_PREFIXES", "").split(",") if p.strip()
)


def is_allowed_market(ticker: str) -> bool:
    if not TICKER_ALLOW_PREFIXES:
        return True
    return ticker.startswith(TICKER_ALLOW_PREFIXES)
