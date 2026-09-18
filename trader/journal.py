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
    if report_trade is not None:
        state.pending_reports.append({
            **payload,
            "execution_key": uuid4().hex,
            "created_at": datetime.now(UTC).isoformat(),
        })
    # Position/accounting changes and the report become durable together.
    save(path, state)
    flush_reports(state, path, save, report_trade)
