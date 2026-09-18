"""Durable reporting tied to each user's existing, atomic state checkpoint."""
from __future__ import annotations

import logging
from datetime import UTC, datetime
from uuid import uuid4

LOG = logging.getLogger("ai_trader.journal")


def flush_reports(state, path, save, report_trade) -> bool:
    if not state.pending_reports:
        return True
    if report_trade is None:
        return False
    while state.pending_reports:
        try:
            report_trade(dict(state.pending_reports[0]))
        except Exception:
            # Keep the original execution ID and timestamp for a safe retry.
            LOG.warning("Trade reporting pending; retained in account state")
            return False
        state.pending_reports.pop(0)
        save(path, state)
    return True


def checkpoint_trade(state, path, save, report_trade, payload) -> None:
    command = getattr(state, "active_command", None)
    if command:
        if command["action"] == "PRIORITY_OPEN":
            positions = getattr(state, "positions", None) or [getattr(state, "position", None)]
            for position in positions:
                if position and position.symbol == payload["symbol"]:
                    position.user_managed = True
        # The command receipt and actual fill are committed with the position.
        # A lost HTTP reply can therefore never cause this command to trade twice.
        state.command_receipts[str(command["id"])] = {
            "status": "executed",
            "result": f"{payload['side']} {payload['quantity']} {payload['symbol']}; bekreftet av Binance",
        }
        state.active_command = None
    if report_trade is not None:
        state.pending_reports.append({
            **payload,
            "execution_key": uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
        })
    # Position/accounting changes and the report become durable together.
    save(path, state)
    flush_reports(state, path, save, report_trade)
