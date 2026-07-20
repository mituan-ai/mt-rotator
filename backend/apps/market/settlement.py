from __future__ import annotations

SETTLEMENT_RULES_VERSION = "2026-07-20"

# Shanghai uses dedicated code families for the main T+0 ETF classes. Shenzhen
# products do not share one complete prefix, so only reviewed symbols are listed.
T0_PREFIXES = ("511", "513", "518")
T0_SYMBOLS = frozenset(
    {
        "159001",
        "159003",
        "159005",
        "159920",
        "159934",
        "159937",
        "159941",
        "159954",
        "159960",
        "159980",
        "159981",
        "159985",
        "159866",
        "159869",
    }
)


def settlement_cycle_for(symbol: str) -> str:
    return "t0" if symbol.startswith(T0_PREFIXES) or symbol in T0_SYMBOLS else "t1"
