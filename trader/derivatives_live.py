from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from .binance import BinanceCredentials, BinanceError
from .derivatives import BinanceFuturesClient, BinanceMarginClient
from .journal import checkpoint_trade, flush_reports


# Shorting is intentionally conservative: one live short position is tracked,
# the stop/target have room for normal crypto noise, and a profitable move gets
# protected before a reversal can turn it into a loss.
SHORT_MIN_STOP_FRACTION = Decimal("0.015")
SHORT_MIN_TARGET_FRACTION = Decimal("0.030")
SHORT_TRAIL_ACTIVATION_FRACTION = Decimal("0.010")
SHORT_TRAIL_GAP_FRACTION = Decimal("0.0075")
SHORT_TRAIL_LOCK_FRACTION = Decimal("0.0025")
SHORT_SIGNAL_EXIT_MIN_PROFIT_FRACTION = Decimal("0.0040")


@dataclass
class ShortPosition:
    mode: str
    symbol: str
    quantity: str
    entry_price: str
    notional: str
    opened_at: int
    stop_fraction: str
    target_fraction: str
    leverage: int = 1
    protection_ids: tuple[int, ...] = ()
    trough_price: str | None = None
    trailing_active: bool = False
    trailing_stop_price: str | None = None
    user_managed: bool = False


@dataclass
class DerivativesState:
    day: str
    realized_pnl: str = "0"
    trades_today: int = 0
    position: ShortPosition | None = None
    cooldown_until: int = 0
    pending_reports: list[dict[str, Any]] = field(default_factory=list)
    pending_close_id: str | None = None
    pending_open: dict[str, Any] | None = None
    active_command: dict[str, Any] | None = None
    command_receipts: dict[str, Any] = field(default_factory=dict)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def load_state(path: Path) -> DerivativesState:
    if not path.exists():
        return DerivativesState(day=_today())
    raw = json.loads(path.read_text(encoding="utf-8"))
    pos = raw.get("position")
    state = DerivativesState(
        day=raw.get("day", _today()),
        realized_pnl=str(raw.get("realized_pnl", "0")),
        trades_today=int(raw.get("trades_today", 0)),
        position=ShortPosition(**pos) if pos else None,
        cooldown_until=int(raw.get("cooldown_until", 0)),
        pending_reports=raw.get("pending_reports", []),
        pending_close_id=raw.get("pending_close_id"),
        pending_open=raw.get("pending_open"),
        active_command=raw.get("active_command"),
        command_receipts=raw.get("command_receipts", {}),
    )
    if state.day != _today():
        state.day = _today()
        state.realized_pnl = "0"
        state.trades_today = 0
    return state


def save_state(path: Path, state: DerivativesState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), separators=(",", ":"), sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _spot_quantity(client: BinanceMarginClient, symbol: str, notional: Decimal) -> Decimal:
    price = client.ticker_price(symbol)
    info = client.symbol_info(symbol)
    lot = next(x for x in info.get("filters", []) if x.get("filterType") == "LOT_SIZE")
    step = Decimal(str(lot["stepSize"]))
    minimum = Decimal(str(lot.get("minQty", "0")))
    qty = (notional / price / step).to_integral_value(rounding=ROUND_DOWN) * step
    if qty < minimum:
        raise BinanceError(f"Margin quantity below minimum for {symbol}")
    return qty


def _tick(client: BinanceMarginClient, symbol: str, price: Decimal) -> Decimal:
    info = client.symbol_info(symbol)
    filt = next(x for x in info.get("filters", []) if x.get("filterType") == "PRICE_FILTER")
    tick = Decimal(str(filt["tickSize"]))
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def _finalize_short_close(state, path, order, reason, report_trade) -> str:
    position = state.position
    if position is None:
        return "short_no_position"
    status = str(order.get("status", ""))
    if status not in {"FILLED", "EXPIRED", "CANCELED", "REJECTED"}:
        return f"short_pending_exchange_order:{status or 'UNKNOWN'}"
    executed = Decimal(str(order.get("executedQty", "0")))
    tracked = Decimal(position.quantity)
    if executed <= 0 or executed > tracked:
        # Preserve evidence and the pending order. Never infer a fill from the
        # requested quantity or a current ticker price.
        return "short_reconciliation_required:invalid_fill_quantity"
    spent = Decimal(str(order.get("cumQuote", order.get("cummulativeQuoteQty", "0"))))
    if spent <= 0:
        avg = Decimal(str(order.get("avgPrice") or "0"))
        spent = avg * executed
    if spent <= 0:
        return "short_reconciliation_required:missing_fill_price"
    pnl = Decimal(position.entry_price) * executed - spent
    state.realized_pnl = str(Decimal(state.realized_pnl) + pnl)
    state.trades_today += 1
    state.pending_close_id = None
    if executed == tracked:
        state.position = None
    else:
        position.quantity = str(tracked - executed)
        position.notional = str(Decimal(position.entry_price) * (tracked - executed))
        position.protection_ids = ()
    state.cooldown_until = int(time.time()) + 300
    checkpoint_trade(state, path, save_state, report_trade, {
        "mode": position.mode, "symbol": position.symbol, "side": "BUY",
        "quantity": str(executed), "entry_price": position.entry_price,
        "exit_price": str(spent / executed), "pnl": str(pnl), "leverage": position.leverage,
    })
    return f"{position.mode}_short_closed:{position.symbol}:pnl={pnl};reason={reason}"


def _complete_short_open(client, state, path, order, report_trade) -> str:
    pending = state.pending_open
    if not pending:
        return "short_reconciliation_required:missing_entry"
    status = str(order.get("status", ""))
    if status not in {"FILLED", "EXPIRED", "CANCELED", "REJECTED"}:
        return f"short_pending_exchange_order:{status or 'UNKNOWN'}"
    executed = Decimal(str(order.get("executedQty", "0")))
    if executed <= 0:
        if status == "FILLED":
            return "short_reconciliation_required:invalid_entry_fill"
        state.pending_open = None
        state.cooldown_until = int(time.time()) + 300
        save_state(path, state)
        return f"short_open_rejected:{pending['symbol']}:{status}"
    received = Decimal(str(order.get("cumQuote", order.get("cummulativeQuoteQty", "0"))))
    if received <= 0:
        received = Decimal(str(order.get("avgPrice") or "0")) * executed
    if received <= 0:
        return "short_reconciliation_required:missing_entry_price"
    entry = received / executed
    position = ShortPosition(pending["mode"], pending["symbol"], str(executed), str(entry),
        str(received), int(pending["opened_at"]), pending["stop"], pending["target"],
        int(pending["leverage"]), trough_price=str(entry))
    state.position, state.pending_open = position, None
    state.trades_today += 1
    checkpoint_trade(state, path, save_state, report_trade, {
        "mode": position.mode, "symbol": position.symbol, "side": "SELL",
        "quantity": str(executed), "entry_price": str(entry), "exit_price": None,
        "pnl": None, "leverage": position.leverage,
    })
    stop = entry * (Decimal("1") + Decimal(position.stop_fraction))
    target = entry * (Decimal("1") - Decimal(position.target_fraction))
    try:
        if position.mode == "margin":
            protection = client.protective_short_oco(symbol=position.symbol, quantity=executed,
                take_profit_price=_tick(client, position.symbol, target), stop_price=_tick(client, position.symbol, stop),
                live_trading_enabled=True, list_client_order_id=f"ait-mo-{uuid4().hex[:24]}")
            position.protection_ids = (int(protection["orderListId"]),)
        else:
            for order_type, price, prefix in (("STOP_MARKET", stop, "fs"), ("TAKE_PROFIT_MARKET", target, "ft")):
                protection = client.close_algo(symbol=position.symbol, side="BUY", order_type=order_type,
                    trigger_price=price, live_trading_enabled=True, client_algo_id=f"ait-{prefix}-{uuid4().hex[:24]}")
                position.protection_ids += (int(protection["algoId"]),)
                save_state(path, state)
        save_state(path, state)
    except Exception:
        save_state(path, state)
        close = _close_futures if position.mode == "futures" else _close_margin
        close(client, state, path, "protection_failed", report_trade)
        raise
    return f"{position.mode}_short_opened:{position.symbol}:notional={received}:leverage={position.leverage}:stop={stop}:target={target}"


def _update_short_position(position: ShortPosition, current: Decimal, current_signal: bool | None) -> str | None:
    """Update a short's best price and return an exit reason when needed.

    The exchange-side stop/target remains the last-resort protection. This local
    layer adds a profit-locking trail and exits a profitable short when the
    bearish signal disappears, without force-selling a trade that is still near
    entry or in loss.
    """
    entry = Decimal(position.entry_price)
    stop_fraction = Decimal(position.stop_fraction)
    target_fraction = Decimal(position.target_fraction)
    trough = Decimal(position.trough_price or position.entry_price)
    if current < trough:
        trough = current
    position.trough_price = str(trough)

    target_price = entry * (Decimal("1") - target_fraction)
    if current <= target_price:
        return "take_profit"

    activation_price = entry * (Decimal("1") - SHORT_TRAIL_ACTIVATION_FRACTION)
    if not position.trailing_active and current <= activation_price:
        position.trailing_active = True
        initial_stop = entry * (Decimal("1") - SHORT_TRAIL_LOCK_FRACTION)
        position.trailing_stop_price = str(max(initial_stop, trough * (Decimal("1") + SHORT_TRAIL_GAP_FRACTION)))
    elif position.trailing_active:
        old_stop = Decimal(position.trailing_stop_price or (entry * (Decimal("1") - SHORT_TRAIL_LOCK_FRACTION)))
        position.trailing_stop_price = str(min(old_stop, trough * (Decimal("1") + SHORT_TRAIL_GAP_FRACTION)))

    if position.trailing_active:
        trailing_stop = Decimal(position.trailing_stop_price or (entry * (Decimal("1") - SHORT_TRAIL_LOCK_FRACTION)))
        if current >= trailing_stop:
            return "trailing_stop"

    if current_signal is False and current <= entry * (Decimal("1") - SHORT_SIGNAL_EXIT_MIN_PROFIT_FRACTION):
        return "signal_reversal"

    hard_stop = entry * (Decimal("1") + stop_fraction)
    if current >= hard_stop:
        return "hard_stop"
    return None


def _close_margin(
    client: BinanceMarginClient,
    state: DerivativesState,
    path: Path,
    reason: str,
    report_trade: Callable[[dict[str, Any]], None] | None,
    maximum_quantity: Decimal | None = None,
) -> str:
    position = state.position
    if position is None:
        return "margin_no_position"
    for order_list_id in position.protection_ids:
        try:
            client.cancel_order_list(symbol=position.symbol, order_list_id=order_list_id)
        except BinanceError:
            pass
    qty = Decimal(position.quantity)
    if maximum_quantity is not None:
        qty = min(qty, maximum_quantity)
    state.pending_close_id = f"ait-mc-{uuid4().hex[:24]}"
    save_state(path, state)
    order = client.market_order(
        symbol=position.symbol,
        side="BUY",
        quantity=qty,
        live_trading_enabled=True,
        auto_borrow_repay=True,
        client_order_id=state.pending_close_id,
    )
    return _finalize_short_close(state, path, order, reason, report_trade)


def _open_margin(
    credentials: BinanceCredentials,
    symbol: str,
    notional: Decimal,
    stop_fraction: Decimal,
    target_fraction: Decimal,
    state: DerivativesState,
    path: Path,
    report_trade: Callable[[dict[str, Any]], None] | None,
) -> str:
    client = BinanceMarginClient(credentials=credentials)
    quantity = _spot_quantity(client, symbol, notional)
    base_asset = symbol[:-4] if symbol.endswith(("USDC", "USDT")) else symbol
    borrowable = client.max_borrowable(asset=base_asset)
    if borrowable < quantity:
        raise BinanceError(f"Insufficient margin borrowable inventory for {symbol}: {borrowable} < {quantity}")
    state.pending_open = {"mode": "margin", "symbol": symbol, "client_id": f"ait-ms-{uuid4().hex[:24]}",
                          "stop": str(stop_fraction), "target": str(target_fraction), "leverage": 1,
                          "opened_at": int(time.time()), "notional": str(notional)}
    save_state(path, state)
    order = client.market_order(symbol=symbol, side="SELL", quantity=quantity,
        live_trading_enabled=True, auto_borrow_repay=True, client_order_id=state.pending_open["client_id"])
    return _complete_short_open(client, state, path, order, report_trade)


def _close_futures(
    client: BinanceFuturesClient,
    state: DerivativesState,
    path: Path,
    reason: str,
    report_trade: Callable[[dict[str, Any]], None] | None,
    maximum_quantity: Decimal | None = None,
) -> str:
    position = state.position
    if position is None:
        return "futures_no_position"
    for algo_id in position.protection_ids:
        try:
            client.cancel_algo(algo_id=algo_id, live_trading_enabled=True)
        except BinanceError:
            pass
    qty = Decimal(position.quantity)
    if maximum_quantity is not None:
        qty = min(qty, maximum_quantity)
    state.pending_close_id = f"ait-fc-{uuid4().hex[:24]}"
    save_state(path, state)
    order = client.market_order(symbol=position.symbol, side="BUY", quantity=qty, live_trading_enabled=True, reduce_only=True, client_order_id=state.pending_close_id)
    return _finalize_short_close(state, path, order, reason, report_trade)


def _open_futures(
    credentials: BinanceCredentials,
    symbol: str,
    notional: Decimal,
    leverage: int,
    stop_fraction: Decimal,
    target_fraction: Decimal,
    state: DerivativesState,
    path: Path,
    report_trade: Callable[[dict[str, Any]], None] | None,
) -> str:
    client = BinanceFuturesClient(credentials)
    client.set_isolated_margin(symbol=symbol, live_trading_enabled=True)
    client.set_leverage(symbol=symbol, leverage=leverage, live_trading_enabled=True)
    quantity = client.quantity_for_notional(symbol=symbol, notional=notional)
    state.pending_open = {"mode": "futures", "symbol": symbol, "client_id": f"ait-fs-{uuid4().hex[:24]}",
                          "stop": str(stop_fraction), "target": str(target_fraction), "leverage": leverage,
                          "opened_at": int(time.time()), "notional": str(notional)}
    save_state(path, state)
    order = client.market_order(symbol=symbol, side="SELL", quantity=quantity, live_trading_enabled=True,
                                client_order_id=state.pending_open["client_id"])
    return _complete_short_open(client, state, path, order, report_trade)


def run_short_cycle(
    credentials: BinanceCredentials,
    short_signals: dict[str, bool],
    confidences: dict[str, Decimal],
    settings: dict[str, Any],
    state_path: Path,
    report_trade: Callable[[dict[str, Any]], None] | None = None,
    *,
    spot_realized_pnl: Decimal = Decimal("0"),
    allow_new_entries: bool = True,
    preferred_symbol: str | None = None,
    requested_notional: Decimal | None = None,
    spot_open_notional: Decimal = Decimal("0"),
    spot_open_symbols: frozenset[str] = frozenset(),
    user_priority: bool = False,
) -> str:
    state = load_state(state_path)
    flush_reports(state, state_path, save_state, report_trade)
    max_daily_loss = Decimal(str(settings.get("max_daily_loss_usdc", "2")))
    combined_realized = spot_realized_pnl + Decimal(state.realized_pnl)
    if combined_realized <= -max_daily_loss:
        allow_new_entries = False

    if state.pending_open:
        pending = state.pending_open
        pending_client = BinanceFuturesClient(credentials) if pending["mode"] == "futures" else BinanceMarginClient(credentials=credentials)
        # Read the original order before doing anything else. Never blindly retry
        # a borrow/SELL after a timeout; -2013 remains unresolved for an operator.
        order = pending_client.query_order(symbol=pending["symbol"], orig_client_order_id=pending["client_id"])
        return _complete_short_open(pending_client, state, state_path, order, report_trade)

    if state.position:
        position = state.position
        if state.pending_close_id:
            pending_client = BinanceFuturesClient(credentials) if position.mode == "futures" else BinanceMarginClient(credentials=credentials)
            order = pending_client.query_order(symbol=position.symbol, orig_client_order_id=state.pending_close_id)
            return _finalize_short_close(state, state_path, order, "reconciled_close", report_trade)
        # Absence from the rotating top-five universe is not a reversal.
        current_signal = short_signals.get(position.symbol)
        if position.mode == "futures":
            client = BinanceFuturesClient(credentials)
            exchange_positions = client.position_risk(symbol=position.symbol)
            amount = sum((abs(Decimal(str(x.get("positionAmt", "0")))) for x in exchange_positions), Decimal("0"))
            if amount == 0:
                for algo_id in position.protection_ids:
                    try:
                        algo = client.query_algo(algo_id=algo_id)
                        if algo.get("actualOrderId"):
                            order = client.query_order_by_id(symbol=position.symbol, order_id=int(algo["actualOrderId"]))
                            if Decimal(str(order.get("executedQty", "0"))) > 0:
                                return _finalize_short_close(state, state_path, order, "exchange_protection", report_trade)
                    except BinanceError:
                        continue
                return f"futures_reconciliation_required:{position.symbol}"
            current = client.ticker_price(position.symbol)
            reason = _update_short_position(position, current, current_signal)
            save_state(state_path, state)
            if reason:
                return _close_futures(client, state, state_path, reason, report_trade)
            return f"futures_short_holding:{position.symbol}:signal={current_signal}:trail={position.trailing_active}"
        client = BinanceMarginClient(credentials=credentials)
        if position.protection_ids:
            try:
                order_list = client.query_order_list(order_list_id=position.protection_ids[0])
                if str(order_list.get("listOrderStatus", "")) != "EXECUTING":
                    for leg in order_list.get("orders", []):
                        order = client.query_order_by_id(symbol=position.symbol, order_id=int(leg["orderId"]))
                        if Decimal(str(order.get("executedQty", "0"))) > 0:
                            return _finalize_short_close(state, state_path, order, "exchange_protection", report_trade)
                    # An expired/cancelled OCO does not prove the borrowed asset
                    # was repaid. Retain the position for reconciliation.
                    return f"margin_reconciliation_required:{position.symbol}"
            except BinanceError:
                pass
        current = client.ticker_price(position.symbol)
        reason = _update_short_position(position, current, current_signal)
        save_state(state_path, state)
        if reason:
            return _close_margin(client, state, state_path, reason, report_trade)
        return f"margin_short_holding:{position.symbol}:signal={current_signal}:trail={position.trailing_active}"

    if not allow_new_entries:
        return "short_new_entries_paused"
    if state.pending_reports:
        return "short_reporting_backlog"
    if not bool(settings.get("short_enabled")):
        return "short_disabled"
    if not user_priority and int(time.time()) < state.cooldown_until:
        return "short_cooldown"

    candidates = [symbol for symbol, active in short_signals.items() if active and symbol not in spot_open_symbols]
    if not candidates:
        return "no_short_signal"
    if preferred_symbol and preferred_symbol in candidates:
        symbol = preferred_symbol
    else:
        symbol = max(candidates, key=lambda item: confidences.get(item, Decimal("0")))
    confidence = max(Decimal("0"), min(Decimal("1"), confidences.get(symbol, Decimal("0.5"))))
    multiplier = max(Decimal("0.30"), Decimal("0.20") + confidence * Decimal("0.80"))
    max_position = Decimal(str(settings.get("order_size_usdc", "25")))
    capital_cap = Decimal(str(settings.get("trade_cap_usdc", max_position)))
    remaining_cap = max(Decimal("0"), capital_cap - max(Decimal("0"), spot_open_notional))
    automatic_notional = min(max_position * multiplier, remaining_cap)
    notional = min(max_position, remaining_cap, requested_notional) if requested_notional is not None else automatic_notional
    if notional < Decimal("5"):
        return "short_notional_below_minimum"

    configured_stop = Decimal(str(settings.get("stop_loss_percent", "1"))) / Decimal("100")
    configured_target = Decimal(str(settings.get("take_profit_percent", "2"))) / Decimal("100")
    # Use a wider short stop and a larger target than the old 1%/2% defaults.
    # The local trail protects a winner before the wider hard stop is reached.
    stop_fraction = max(configured_stop, SHORT_MIN_STOP_FRACTION)
    target_fraction = max(configured_target, SHORT_MIN_TARGET_FRACTION)
    use_futures = bool(settings.get("futures_enabled")) and str(settings.get("risk_profile", "normal")) == "extreme"
    try:
        if use_futures:
            leverage = max(1, min(20, int(settings.get("leverage", 1))))
            return _open_futures(credentials, symbol, notional, leverage, stop_fraction, target_fraction, state, state_path, report_trade)
        return _open_margin(credentials, symbol, notional, stop_fraction, target_fraction, state, state_path, report_trade)
    except BinanceError as exc:
        # Reload because a failed protection install may have already closed the
        # position. Avoid another open/failed-protection/close on the next scan.
        latest = load_state(state_path)
        latest.cooldown_until = int(time.time()) + 300
        save_state(state_path, latest)
        # Entry rejections (for example insufficient futures margin) are an
        # expected exchange response, not a failure of the entire trading
        # cycle. Keep surfacing errors if an unprotected position remains.
        if latest.position is not None:
            raise
        return f"short_open_rejected:{symbol}:{exc}"
