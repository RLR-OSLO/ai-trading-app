from __future__ import annotations

import json
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable

from .binance import BinanceCredentials, BinanceError
from .derivatives import BinanceFuturesClient, BinanceMarginClient


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


@dataclass
class DerivativesState:
    day: str
    realized_pnl: str = "0"
    trades_today: int = 0
    position: ShortPosition | None = None


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


def _record(report_trade: Callable[[dict[str, Any]], None] | None, payload: dict[str, Any]) -> None:
    if report_trade:
        report_trade(payload)


def _close_margin(
    client: BinanceMarginClient,
    state: DerivativesState,
    path: Path,
    reason: str,
    report_trade: Callable[[dict[str, Any]], None] | None,
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
    order = client.market_order(
        symbol=position.symbol,
        side="BUY",
        quantity=qty,
        live_trading_enabled=True,
        auto_borrow_repay=True,
        client_order_id=f"ait-mc-{int(time.time())}"[:36],
    )
    executed = Decimal(str(order.get("executedQty", qty)))
    spent = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    if executed <= 0 or spent <= 0:
        raise BinanceError("Margin short close returned invalid fill")
    entry_value = Decimal(position.entry_price) * executed
    pnl = entry_value - spent
    state.realized_pnl = str(Decimal(state.realized_pnl) + pnl)
    state.trades_today += 1
    state.position = None
    save_state(path, state)
    _record(report_trade, {"mode": "margin", "symbol": position.symbol, "side": "BUY", "quantity": str(executed), "entry_price": position.entry_price, "exit_price": str(spent / executed), "pnl": str(pnl), "leverage": 1})
    return f"margin_short_closed:{position.symbol}:pnl={pnl};reason={reason}"


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
    order = client.market_order(
        symbol=symbol,
        side="SELL",
        quantity=quantity,
        live_trading_enabled=True,
        auto_borrow_repay=True,
        client_order_id=f"ait-ms-{int(time.time())}"[:36],
    )
    executed = Decimal(str(order.get("executedQty", "0")))
    received = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    if executed <= 0 or received <= 0:
        raise BinanceError("Margin short entry returned invalid fill")
    entry = received / executed
    take_profit = _tick(client, symbol, entry * (Decimal("1") - target_fraction))
    stop = _tick(client, symbol, entry * (Decimal("1") + stop_fraction))
    position = ShortPosition("margin", symbol, str(executed), str(entry), str(received), int(time.time()), str(stop_fraction), str(target_fraction))
    state.position = position
    save_state(path, state)
    try:
        protection = client.protective_short_oco(
            symbol=symbol,
            quantity=executed,
            take_profit_price=take_profit,
            stop_price=stop,
            live_trading_enabled=True,
            list_client_order_id=f"ait-mo-{int(time.time())}"[:36],
        )
        order_list_id = int(protection["orderListId"])
        position.protection_ids = (order_list_id,)
        save_state(path, state)
    except Exception:
        _close_margin(client, state, path, "protection_failed", report_trade)
        raise
    state.trades_today += 1
    save_state(path, state)
    _record(report_trade, {"mode": "margin", "symbol": symbol, "side": "SELL", "quantity": str(executed), "entry_price": str(entry), "exit_price": None, "pnl": None, "leverage": 1})
    return f"margin_short_opened:{symbol}:notional={received}:stop={stop}:target={take_profit}"


def _close_futures(
    client: BinanceFuturesClient,
    state: DerivativesState,
    path: Path,
    reason: str,
    report_trade: Callable[[dict[str, Any]], None] | None,
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
    order = client.market_order(symbol=position.symbol, side="BUY", quantity=qty, live_trading_enabled=True, reduce_only=True, client_order_id=f"ait-fc-{int(time.time())}"[:36])
    exit_price = Decimal(str(order.get("avgPrice") or client.ticker_price(position.symbol)))
    pnl = (Decimal(position.entry_price) - exit_price) * qty
    state.realized_pnl = str(Decimal(state.realized_pnl) + pnl)
    state.trades_today += 1
    state.position = None
    save_state(path, state)
    _record(report_trade, {"mode": "futures", "symbol": position.symbol, "side": "BUY", "quantity": str(qty), "entry_price": position.entry_price, "exit_price": str(exit_price), "pnl": str(pnl), "leverage": position.leverage})
    return f"futures_short_closed:{position.symbol}:pnl={pnl};reason={reason}"


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
    order = client.market_order(symbol=symbol, side="SELL", quantity=quantity, live_trading_enabled=True, client_order_id=f"ait-fs-{int(time.time())}"[:36])
    entry = Decimal(str(order.get("avgPrice") or client.ticker_price(symbol)))
    if entry <= 0:
        raise BinanceError("Futures short entry returned invalid price")
    position = ShortPosition("futures", symbol, str(quantity), str(entry), str(entry * quantity), int(time.time()), str(stop_fraction), str(target_fraction), leverage)
    state.position = position
    save_state(path, state)
    stop_price = entry * (Decimal("1") + stop_fraction)
    target_price = entry * (Decimal("1") - target_fraction)
    protection_ids: list[int] = []
    try:
        stop = client.close_algo(symbol=symbol, side="BUY", order_type="STOP_MARKET", trigger_price=stop_price, live_trading_enabled=True, client_algo_id=f"ait-fstop-{int(time.time())}"[:36])
        protection_ids.append(int(stop["algoId"]))
        target = client.close_algo(symbol=symbol, side="BUY", order_type="TAKE_PROFIT_MARKET", trigger_price=target_price, live_trading_enabled=True, client_algo_id=f"ait-ftp-{int(time.time())}"[:36])
        protection_ids.append(int(target["algoId"]))
        position.protection_ids = tuple(protection_ids)
        save_state(path, state)
    except Exception:
        position.protection_ids = tuple(protection_ids)
        save_state(path, state)
        _close_futures(client, state, path, "protection_failed", report_trade)
        raise
    state.trades_today += 1
    save_state(path, state)
    _record(report_trade, {"mode": "futures", "symbol": symbol, "side": "SELL", "quantity": str(quantity), "entry_price": str(entry), "exit_price": None, "pnl": None, "leverage": leverage})
    return f"futures_short_opened:{symbol}:notional={entry * quantity}:leverage={leverage}:stop={stop_price}:target={target_price}"


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
) -> str:
    state = load_state(state_path)
    max_daily_loss = Decimal(str(settings.get("max_daily_loss_usdc", "2")))
    combined_realized = spot_realized_pnl + Decimal(state.realized_pnl)
    if combined_realized <= -max_daily_loss:
        allow_new_entries = False

    if state.position:
        position = state.position
        current_signal = bool(short_signals.get(position.symbol, False))
        if position.mode == "futures":
            client = BinanceFuturesClient(credentials)
            exchange_positions = client.position_risk(symbol=position.symbol)
            amount = sum((abs(Decimal(str(x.get("positionAmt", "0")))) for x in exchange_positions), Decimal("0"))
            if amount == 0:
                state.position = None
                save_state(state_path, state)
                return f"futures_short_closed_exchange:{position.symbol}"
            current = client.ticker_price(position.symbol)
            entry = Decimal(position.entry_price)
            if current >= entry * (Decimal("1") + Decimal(position.stop_fraction) * Decimal("1.10")):
                return _close_futures(client, state, state_path, "local_emergency_stop", report_trade)
            return f"futures_short_holding:{position.symbol}:signal={current_signal}"
        client = BinanceMarginClient(credentials=credentials)
        if position.protection_ids:
            try:
                order_list = client.query_order_list(order_list_id=position.protection_ids[0])
                if str(order_list.get("listOrderStatus", "")) != "EXECUTING":
                    state.position = None
                    save_state(state_path, state)
                    return f"margin_short_closed_exchange:{position.symbol}"
            except BinanceError:
                pass
        current = client.ticker_price(position.symbol)
        entry = Decimal(position.entry_price)
        if current >= entry * (Decimal("1") + Decimal(position.stop_fraction) * Decimal("1.10")):
            return _close_margin(client, state, state_path, "local_emergency_stop", report_trade)
        return f"margin_short_holding:{position.symbol}:signal={current_signal}"

    if not allow_new_entries:
        return "short_new_entries_paused"
    if not bool(settings.get("short_enabled")):
        return "short_disabled"

    candidates = [symbol for symbol, active in short_signals.items() if active]
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
    automatic_notional = min(max_position * multiplier, capital_cap)
    notional = min(max_position, capital_cap, requested_notional) if requested_notional is not None else automatic_notional
    if notional < Decimal("5"):
        return "short_notional_below_minimum"

    stop_fraction = Decimal(str(settings.get("stop_loss_percent", "1"))) / Decimal("100")
    target_fraction = Decimal(str(settings.get("take_profit_percent", "2"))) / Decimal("100")
    use_futures = bool(settings.get("futures_enabled")) and str(settings.get("risk_profile", "normal")) == "extreme"
    if use_futures:
        leverage = max(1, min(3, int(settings.get("leverage", 1))))
        return _open_futures(credentials, symbol, notional, leverage, stop_fraction, target_fraction, state, state_path, report_trade)
    return _open_margin(credentials, symbol, notional, stop_fraction, target_fraction, state, state_path, report_trade)
