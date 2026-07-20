from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypedDict

from .models import PaperAccount

MIN_HOLD_SESSIONS = 5
COOLDOWN_SESSIONS = 5
MIN_WEIGHT_GAP = Decimal("0.05")
MIN_TRADE_VALUE = Decimal("1000")


class RiskRule(TypedDict):
    maximum_positions: int
    exposure: dict[str, Decimal]


RISK_RULES: dict[str, RiskRule] = {
    PaperAccount.RiskLevel.CONSERVATIVE: {
        "maximum_positions": 3,
        "exposure": {"strong": Decimal("0.60"), "neutral": Decimal("0.40"), "weak": Decimal("0.20")},
    },
    PaperAccount.RiskLevel.BALANCED: {
        "maximum_positions": 5,
        "exposure": {"strong": Decimal("0.80"), "neutral": Decimal("0.60"), "weak": Decimal("0.40")},
    },
    PaperAccount.RiskLevel.AGGRESSIVE: {
        "maximum_positions": 8,
        "exposure": {"strong": Decimal("1.00"), "neutral": Decimal("0.80"), "weak": Decimal("0.60")},
    },
}


@dataclass(frozen=True)
class PolicyResolution:
    targets: dict[str, Decimal]
    states: dict[str, str]


def scale_strategy_targets(
    *,
    risk_level: str,
    target_weights: dict[str, float],
    selected: list[str],
    market_state: str,
) -> dict[str, Decimal]:
    rules = RISK_RULES[risk_level]
    selected = [symbol for symbol in selected if symbol in target_weights][: rules["maximum_positions"]]
    if not selected:
        return {}
    total = sum((Decimal(str(target_weights[symbol])) for symbol in selected), Decimal("0"))
    if total <= 0:
        return {}
    exposure = rules["exposure"].get(market_state, rules["exposure"]["neutral"])
    return {
        symbol: (Decimal(str(target_weights[symbol])) / total * exposure).quantize(Decimal("0.000001"))
        for symbol in selected
    }


def resolve_stable_targets(
    *,
    raw_targets: dict[str, Decimal],
    current_weights: dict[str, Decimal],
    prior_raw_targets: dict[str, Decimal],
    holding_ages: dict[str, int],
    cooldown_ages: dict[str, int | None],
) -> PolicyResolution:
    targets: dict[str, Decimal] = {}
    states: dict[str, str] = {}
    symbols = set(raw_targets) | set(current_weights) | set(prior_raw_targets)
    for symbol in symbols:
        raw_weight = raw_targets.get(symbol, Decimal("0"))
        current_weight = current_weights.get(symbol, Decimal("0"))
        prior_weight = prior_raw_targets.get(symbol, Decimal("0"))
        held = current_weight > 0
        cooldown_age = cooldown_ages.get(symbol)
        in_cooldown = not held and cooldown_age is not None and cooldown_age < COOLDOWN_SESSIONS
        if raw_weight > 0 and not held:
            if in_cooldown:
                targets[symbol], states[symbol] = Decimal("0"), "cooldown"
            elif prior_weight > 0:
                targets[symbol], states[symbol] = raw_weight, "buy"
            else:
                targets[symbol], states[symbol] = Decimal("0"), "watch"
        elif raw_weight == 0 and held:
            if prior_weight == 0 and holding_ages.get(symbol, 0) >= MIN_HOLD_SESSIONS:
                targets[symbol], states[symbol] = Decimal("0"), "sell"
            else:
                targets[symbol], states[symbol] = current_weight, "hold"
        else:
            targets[symbol], states[symbol] = raw_weight, "hold"
    return PolicyResolution(targets=targets, states=states)


def material_change(*, target_weight: Decimal, current_weight: Decimal, trade_value: Decimal) -> bool:
    return abs(target_weight - current_weight) >= MIN_WEIGHT_GAP and trade_value >= MIN_TRADE_VALUE
