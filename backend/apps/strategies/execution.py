from __future__ import annotations

from dataclasses import dataclass
from decimal import ROUND_DOWN, Decimal

COMMISSION_RATE = Decimal("0.0003")
MIN_COMMISSION = Decimal("5")
SLIPPAGE = Decimal("0.0005")
LOT_SIZE = 100


@dataclass(frozen=True)
class ExecutionItem:
    symbol: str
    side: str
    shares: int
    price: Decimal | None
    fee: Decimal
    status: str
    reason: str = ""


@dataclass(frozen=True)
class ExecutionResult:
    cash: Decimal
    positions: dict[str, int]
    items: list[ExecutionItem]


def commission(amount: Decimal) -> Decimal:
    if amount <= 0:
        return Decimal("0")
    return max(amount * COMMISSION_RATE, MIN_COMMISSION).quantize(Decimal("0.01"))


def estimated_price(side: str, opening: Decimal, high: Decimal, low: Decimal) -> Decimal:
    candidate = opening * (Decimal("1") + SLIPPAGE if side == "buy" else Decimal("1") - SLIPPAGE)
    candidate = min(candidate, high) if side == "buy" else max(candidate, low)
    return candidate.quantize(Decimal("0.000001"))


def _lots_for_value(value: Decimal, price: Decimal) -> int:
    if price <= 0 or value <= 0:
        return 0
    units = int((value / price).to_integral_value(rounding=ROUND_DOWN))
    return units // LOT_SIZE * LOT_SIZE


def rebalance(
    *,
    cash: Decimal,
    positions: dict[str, int],
    target_weights: dict[str, float],
    bars: dict[str, dict[str, Decimal]],
) -> ExecutionResult:
    positions = dict(positions)
    items: list[ExecutionItem] = []
    symbols = sorted(set(positions) | set(target_weights))
    portfolio_value = cash
    for symbol, shares in positions.items():
        bar = bars.get(symbol)
        if bar:
            portfolio_value += Decimal(shares) * bar["open"]

    target_shares: dict[str, int] = {}
    missing_symbols: set[str] = set()
    for symbol in symbols:
        bar = bars.get(symbol)
        if not bar:
            target_shares[symbol] = positions.get(symbol, 0)
            missing_symbols.add(symbol)
            current = positions.get(symbol, 0)
            target_weight = float(target_weights.get(symbol, 0))
            if current > 0 or target_weight > 0:
                items.append(
                    ExecutionItem(
                        symbol,
                        "sell" if current > 0 and target_weight == 0 else "buy",
                        current if current > 0 and target_weight == 0 else 0,
                        None,
                        Decimal("0"),
                        "rejected",
                        "missing_bar",
                    )
                )
            continue
        target_shares[symbol] = _lots_for_value(
            portfolio_value * Decimal(str(target_weights.get(symbol, 0))), bar["open"]
        )

    for symbol in symbols:
        if symbol in missing_symbols:
            continue
        current = positions.get(symbol, 0)
        desired = target_shares[symbol]
        if desired >= current:
            continue
        bar = bars.get(symbol)
        shares = current - desired
        if not bar:
            items.append(ExecutionItem(symbol, "sell", shares, None, Decimal("0"), "rejected", "missing_bar"))
            continue
        price = estimated_price("sell", bar["open"], bar["high"], bar["low"])
        amount = price * shares
        fee = commission(amount)
        cash += amount - fee
        positions[symbol] = desired
        items.append(ExecutionItem(symbol, "sell", shares, price, fee, "filled"))

    for symbol in symbols:
        if symbol in missing_symbols:
            continue
        current = positions.get(symbol, 0)
        desired = target_shares[symbol]
        if desired <= current:
            continue
        bar = bars.get(symbol)
        requested = desired - current
        if not bar:
            items.append(
                ExecutionItem(symbol, "buy", requested, None, Decimal("0"), "rejected", "missing_bar")
            )
            continue
        price = estimated_price("buy", bar["open"], bar["high"], bar["low"])
        shares = requested
        while shares >= LOT_SIZE:
            amount = price * shares
            fee = commission(amount)
            if amount + fee <= cash:
                break
            shares -= LOT_SIZE
        if shares < LOT_SIZE:
            items.append(
                ExecutionItem(symbol, "buy", requested, None, Decimal("0"), "rejected", "insufficient_cash")
            )
            continue
        amount = price * shares
        fee = commission(amount)
        cash -= amount + fee
        positions[symbol] = current + shares
        items.append(ExecutionItem(symbol, "buy", shares, price, fee, "filled"))
        if shares != requested:
            items.append(
                ExecutionItem(
                    symbol, "buy", requested - shares, None, Decimal("0"), "rejected", "insufficient_cash"
                )
            )

    return ExecutionResult(cash=cash.quantize(Decimal("0.01")), positions=positions, items=items)
