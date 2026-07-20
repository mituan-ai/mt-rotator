from __future__ import annotations

from decimal import Decimal

from apps.strategies.execution import commission, rebalance


def test_fee_slippage_lot_rounding_and_cash_limit():
    result = rebalance(
        cash=Decimal("100000"),
        positions={},
        target_weights={"510300": 1.0},
        bars={
            "510300": {
                "open": Decimal("4.000"),
                "high": Decimal("4.100"),
                "low": Decimal("3.900"),
                "close": Decimal("4.050"),
                "volume": Decimal("1000000"),
            }
        },
    )
    filled = [item for item in result.items if item.status == "filled"]
    assert len(filled) == 1
    assert filled[0].shares % 100 == 0
    assert filled[0].price == Decimal("4.002000")
    assert result.cash >= 0
    assert commission(Decimal("1000")) == Decimal("5.00")


def test_missing_bar_is_rejected_not_fabricated():
    result = rebalance(
        cash=Decimal("100000"),
        positions={},
        target_weights={"510300": 1.0},
        bars={},
    )
    assert result.positions == {}
    assert result.items[0].status == "rejected"
    assert result.items[0].price is None
