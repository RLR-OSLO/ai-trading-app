from decimal import Decimal


from trader.portfolio_live import PortfolioLimits, Position, PortfolioState, _finalize_sell


def test_partial_sell_allocates_only_sold_cost_basis(tmp_path):
    state = PortfolioState(day="2026-09-11", positions=[
        Position(
            symbol="ETHUSDC",
            quantity="10",
            entry_price="10",
            quote_spent="100",
            opened_at=1,
        )
    ])
    limits = PortfolioLimits.from_values(
        "100", "25", "1", "2", "2",
        max_trades=12, cooldown=300, max_positions=3,
    )

    result = _finalize_sell(
        state, tmp_path / "state.json", state.positions[0],
        Decimal("4"), Decimal("44"), limits, None,
    )

    assert result.startswith("sold:ETHUSDC:pnl=4")
    assert state.realized_pnl == "4"
    assert len(state.positions) == 1
    assert state.positions[0].quantity == "6"
    assert state.positions[0].quote_spent == "60"
