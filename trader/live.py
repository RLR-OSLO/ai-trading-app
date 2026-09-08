from __future__ import annotations

import json
import os
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_DOWN
from pathlib import Path
from typing import Any, Callable

from .binance import BinanceError, BinanceSpotClient


PROFILE_LIMITS = {
    "low": (6, 1800),
    "normal": (8, 900),
    "high": (12, 300),
}


@dataclass
class Position:
    symbol: str
    quantity: str
    entry_price: str
    quote_spent: str
    opened_at: int
    protective_order_list_id: int | None = None
    protective_order_ids: tuple[int, ...] = ()


@dataclass
class LiveState:
    day: str
    realized_pnl: str = "0"
    trades_today: int = 0
    cooldown_until: int = 0
    position: Position | None = None
    pending_action: str | None = None
    pending_client_order_id: str | None = None
    pending_since: int = 0


@dataclass(frozen=True)
class LiveLimits:
    capital_cap: Decimal
    order_size: Decimal
    stop_fraction: Decimal
    target_fraction: Decimal
    daily_loss: Decimal
    max_trades_per_day: int
    cooldown_seconds: int

    @classmethod
    def from_env(cls) -> "LiveLimits":
        return cls.from_values(
            os.getenv("LIVE_CAP_USDC", "100"),
            os.getenv("LIVE_ORDER_USDC", "25"),
            os.getenv("LIVE_STOP_PERCENT", "1"),
            os.getenv("LIVE_TARGET_PERCENT", "2"),
            os.getenv("LIVE_DAILY_LOSS_USDC", "2"),
            max_trades=int(os.getenv("LIVE_MAX_TRADES_PER_DAY", "8")),
            cooldown=int(os.getenv("LIVE_COOLDOWN_SECONDS", "900")),
        )

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> "LiveLimits":
        profile = str(settings.get("risk_profile", "normal")).lower()
        max_trades, cooldown = PROFILE_LIMITS.get(profile, PROFILE_LIMITS["normal"])
        return cls.from_values(
            settings.get("trade_cap_usdc", "100"),
            settings.get("order_size_usdc", "25"),
            settings.get("stop_loss_percent", "1"),
            settings.get("take_profit_percent", "2"),
            settings.get("max_daily_loss_usdc", "2"),
            max_trades=max_trades,
            cooldown=cooldown,
        )

    @classmethod
    def from_values(
        cls,
        cap_value: Any,
        order_value: Any,
        stop_value: Any,
        target_value: Any,
        daily_loss_value: Any,
        *,
        max_trades: int | None = None,
        cooldown: int | None = None,
    ) -> "LiveLimits":
        cap = Decimal(str(cap_value))
        order = Decimal(str(order_value))
        stop = Decimal(str(stop_value)) / Decimal("100")
        target = Decimal(str(target_value)) / Decimal("100")
        daily_loss = Decimal(str(daily_loss_value))
        max_trades = max_trades if max_trades is not None else int(os.getenv("LIVE_MAX_TRADES_PER_DAY", "8"))
        cooldown = cooldown if cooldown is not None else int(os.getenv("LIVE_COOLDOWN_SECONDS", "900"))
        if cap < Decimal("5"):
            raise ValueError("Available trading capital must be at least 5 quote units")
        if not (Decimal("5") <= order <= cap):
            raise ValueError("LIVE_ORDER_USDC must be between 5 and available trading capital")
        if not (Decimal("0.0025") <= stop <= Decimal("0.10")):
            raise ValueError("LIVE_STOP_PERCENT is outside the safety range")
        if not (Decimal("0.005") <= target <= Decimal("0.25")):
            raise ValueError("LIVE_TARGET_PERCENT is outside the safety range")
        if not (Decimal("0.5") <= daily_loss <= cap):
            raise ValueError("LIVE_DAILY_LOSS_USDC is outside the safety range")
        if not (1 <= max_trades <= 12):
            raise ValueError("LIVE_MAX_TRADES_PER_DAY must be between 1 and 12")
        if not (60 <= cooldown <= 86_400):
            raise ValueError("LIVE_COOLDOWN_SECONDS is outside the safety range")
        return cls(cap, order, stop, target, daily_loss, max_trades, cooldown)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _position_from_raw(raw: dict[str, Any]) -> Position:
    return Position(
        symbol=raw["symbol"],
        quantity=raw["quantity"],
        entry_price=raw["entry_price"],
        quote_spent=raw["quote_spent"],
        opened_at=int(raw["opened_at"]),
        protective_order_list_id=raw.get("protective_order_list_id"),
        protective_order_ids=tuple(int(item) for item in raw.get("protective_order_ids", [])),
    )


def load_state(path: Path) -> LiveState:
    if not path.exists():
        return LiveState(day=_today())
    raw = json.loads(path.read_text(encoding="utf-8"))
    position = _position_from_raw(raw["position"]) if raw.get("position") else None
    state = LiveState(
        day=raw["day"],
        realized_pnl=raw.get("realized_pnl", "0"),
        trades_today=int(raw.get("trades_today", 0)),
        cooldown_until=int(raw.get("cooldown_until", 0)),
        position=position,
        pending_action=raw.get("pending_action"),
        pending_client_order_id=raw.get("pending_client_order_id"),
        pending_since=int(raw.get("pending_since", 0)),
    )
    if state.day != _today():
        state.day, state.realized_pnl, state.trades_today = _today(), "0", 0
    return state


def save_state(path: Path, state: LiveState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), separators=(",", ":"), sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as handle:
        handle.write(payload)
        temporary = Path(handle.name)
    temporary.replace(path)


def _free_balance(client: BinanceSpotClient, asset: str) -> Decimal:
    for balance in client.account().get("balances", []):
        if balance.get("asset") == asset:
            return Decimal(str(balance.get("free", "0")))
    return Decimal("0")


def _net_acquired(order: dict, base_asset: str) -> Decimal:
    quantity = Decimal(str(order.get("executedQty", "0")))
    for fill in order.get("fills", []):
        if fill.get("commissionAsset") == base_asset:
            quantity -= Decimal(str(fill.get("commission", "0")))
    return max(quantity, Decimal("0"))


def _symbol_filters(client: BinanceSpotClient, symbol: str) -> tuple[dict[str, Any], dict[str, Any]]:
    info = client.symbol_info(symbol)
    lot = next(item for item in info.get("filters", []) if item.get("filterType") == "LOT_SIZE")
    price = next(item for item in info.get("filters", []) if item.get("filterType") == "PRICE_FILTER")
    return lot, price


def _sellable_quantity(client: BinanceSpotClient, symbol: str, quantity: Decimal) -> Decimal:
    lot, _ = _symbol_filters(client, symbol)
    step = Decimal(str(lot["stepSize"]))
    return (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step


def _price_for_tick(client: BinanceSpotClient, symbol: str, price: Decimal) -> Decimal:
    _, price_filter = _symbol_filters(client, symbol)
    tick = Decimal(str(price_filter["tickSize"]))
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def _clear_pending(state: LiveState) -> None:
    state.pending_action = None
    state.pending_client_order_id = None
    state.pending_since = 0


def _new_client_order_id(side: str, now: int) -> str:
    return f"ait-{side.lower()}-{now}"


def _finalize_sell(
    state: LiveState,
    state_path: Path,
    position: Position,
    quantity: Decimal,
    received: Decimal,
    limits: LiveLimits,
    report_trade: Callable[[dict[str, Any]], None] | None,
) -> str:
    if quantity <= 0 or received <= 0:
        raise BinanceError("Sell execution returned invalid quantity or proceeds")
    pnl = received - Decimal(position.quote_spent)
    state.realized_pnl = str(Decimal(state.realized_pnl) + pnl)
    state.position = None
    _clear_pending(state)
    state.trades_today += 1
    state.cooldown_until = int(time.time()) + limits.cooldown_seconds
    save_state(state_path, state)
    if report_trade:
        report_trade({
            "symbol": position.symbol,
            "side": "SELL",
            "quantity": str(quantity),
            "entry_price": position.entry_price,
            "exit_price": str(received / quantity),
            "pnl": str(pnl),
        })
    return f"sold:{position.symbol}:pnl={pnl}"


def _exchange_protection_enabled() -> bool:
    return os.getenv("EXCHANGE_PROTECTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _install_exchange_protection(
    client: BinanceSpotClient,
    state: LiveState,
    state_path: Path,
    position: Position,
    stop: Decimal,
    target: Decimal,
) -> str:
    quantity = _sellable_quantity(client, position.symbol, Decimal(position.quantity))
    if quantity <= 0:
        raise BinanceError("No sellable quantity available for protective OCO")
    stop_price = _price_for_tick(client, position.symbol, stop)
    target_price = _price_for_tick(client, position.symbol, target)
    list_client_order_id = f"ait-oco-{int(time.time())}"
    response = client.place_protective_oco_sell(
        symbol=position.symbol,
        quantity=quantity,
        target_price=target_price,
        stop_price=stop_price,
        live_trading_enabled=True,
        list_client_order_id=list_client_order_id,
    )
    order_list_id = response.get("orderListId")
    orders = response.get("orders", [])
    if order_list_id is None or len(orders) != 2:
        raise BinanceError("Protective OCO returned an incomplete response")
    position.protective_order_list_id = int(order_list_id)
    position.protective_order_ids = tuple(int(item["orderId"]) for item in orders)
    save_state(state_path, state)
    return f"protected:{position.symbol}:oco={order_list_id}"


def _check_exchange_protection(
    client: BinanceSpotClient,
    state: LiveState,
    state_path: Path,
    position: Position,
    limits: LiveLimits,
    report_trade: Callable[[dict[str, Any]], None] | None,
) -> str | None:
    if position.protective_order_list_id is None:
        return None
    try:
        order_list = client.query_order_list(order_list_id=position.protective_order_list_id)
    except BinanceError:
        return f"protected_status_unavailable:{position.symbol}"

    list_status = str(order_list.get("listOrderStatus", ""))
    if list_status == "EXECUTING":
        return f"protected:{position.symbol}:oco={position.protective_order_list_id}"

    order_ids = position.protective_order_ids or tuple(
        int(item["orderId"]) for item in order_list.get("orders", []) if item.get("orderId") is not None
    )
    filled_orders: list[dict[str, Any]] = []
    for order_id in order_ids:
        try:
            order = client.query_order_by_id(symbol=position.symbol, order_id=order_id)
        except BinanceError:
            continue
        if order.get("status") == "FILLED":
            filled_orders.append(order)

    if filled_orders:
        filled = max(filled_orders, key=lambda item: Decimal(str(item.get("cummulativeQuoteQty", "0"))))
        quantity = Decimal(str(filled.get("executedQty", "0")))
        received = Decimal(str(filled.get("cummulativeQuoteQty", "0")))
        return _finalize_sell(state, state_path, position, quantity, received, limits, report_trade)

    position.protective_order_list_id = None
    position.protective_order_ids = ()
    save_state(state_path, state)
    return None


def _reconcile_pending(
    client: BinanceSpotClient,
    state: LiveState,
    state_path: Path,
    quote_asset: str,
    limits: LiveLimits,
    report_trade: Callable[[dict[str, Any]], None] | None,
) -> str | None:
    if not state.pending_action:
        return None
    if not state.pending_client_order_id:
        return f"paused_pending_reconciliation:{state.pending_action}"

    side, symbol = state.pending_action.split(":", 1)
    try:
        order = client.query_order(symbol=symbol, orig_client_order_id=state.pending_client_order_id)
    except BinanceError as exc:
        if "-2013" in str(exc) and state.pending_since and int(time.time()) - state.pending_since >= 60:
            _clear_pending(state)
            save_state(state_path, state)
            return "reconciled_missing_order"
        return f"paused_pending_reconciliation:{state.pending_action}"

    status = str(order.get("status", ""))
    if status not in {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
        return f"pending_exchange_order:{side}:{status or 'UNKNOWN'}"

    if status != "FILLED":
        _clear_pending(state)
        save_state(state_path, state)
        return f"reconciled_{status.lower()}:{side}:{symbol}"

    executed = Decimal(str(order.get("executedQty", "0")))
    quote_qty = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    now = int(time.time())

    if side == "BUY":
        if executed <= 0 or quote_qty <= 0:
            return f"paused_pending_reconciliation:{state.pending_action}"
        base_asset = symbol.removesuffix(quote_asset)
        available = _free_balance(client, base_asset)
        quantity = min(executed, available) if available > 0 else executed
        state.position = Position(symbol, str(quantity), str(quote_qty / executed), str(quote_qty), state.pending_since or now)
        state.trades_today += 1
        _clear_pending(state)
        save_state(state_path, state)
        if report_trade:
            report_trade({"symbol": symbol, "side": "BUY", "quantity": str(quantity), "entry_price": str(quote_qty / executed), "exit_price": None, "pnl": None})
        return f"reconciled_buy:{symbol}"

    if side == "SELL" and state.position:
        return _finalize_sell(state, state_path, state.position, executed, quote_qty, limits, report_trade)

    return f"paused_pending_reconciliation:{state.pending_action}"


def run_live_cycle(
    client: BinanceSpotClient,
    signals: dict[str, bool],
    state_path: Path,
    limits: LiveLimits,
    report_trade: Callable[[dict[str, Any]], None] | None = None,
    *,
    allow_new_entries: bool = True,
    quote_asset: str = "USDC",
) -> str:
    state = load_state(state_path)
    now = int(time.time())
    realized = Decimal(state.realized_pnl)
    quote_asset = quote_asset.upper()

    reconciled = _reconcile_pending(client, state, state_path, quote_asset, limits, report_trade)
    if reconciled:
        return reconciled

    if state.position:
        position = state.position
        protected_result = _check_exchange_protection(client, state, state_path, position, limits, report_trade)
        if protected_result:
            return protected_result

        current = client.ticker_price(position.symbol)
        entry = Decimal(position.entry_price)
        stop = entry * (Decimal("1") - limits.stop_fraction)
        target = entry * (Decimal("1") + limits.target_fraction)

        if stop < current < target and _exchange_protection_enabled():
            try:
                return _install_exchange_protection(client, state, state_path, position, stop, target)
            except BinanceError:
                return f"holding_unprotected:{position.symbol}"

        if stop < current < target:
            return f"holding:{position.symbol}"

        quantity = _sellable_quantity(client, position.symbol, Decimal(position.quantity))
        if quantity <= 0:
            raise BinanceError("No sellable quantity remains for the open position")
        client_order_id = _new_client_order_id("SELL", now)
        state.pending_action = f"SELL:{position.symbol}"
        state.pending_client_order_id = client_order_id
        state.pending_since = now
        save_state(state_path, state)
        order = client.place_spot_order(
            symbol=position.symbol,
            side="SELL",
            order_type="MARKET",
            quantity=quantity,
            live_trading_enabled=True,
            client_order_id=client_order_id,
        )
        received = Decimal(str(order.get("cummulativeQuoteQty", "0")))
        return _finalize_sell(state, state_path, position, quantity, received, limits, report_trade)

    if not allow_new_entries:
        return "paused_new_entries"
    if realized <= -limits.daily_loss:
        return "paused_daily_loss"
    if state.trades_today >= limits.max_trades_per_day:
        return "paused_trade_limit"
    if now < state.cooldown_until:
        return "cooldown"

    candidates = [symbol for symbol, active in signals.items() if active]
    if not candidates:
        return "no_signal"
    if _free_balance(client, quote_asset) < limits.order_size:
        return f"insufficient_{quote_asset.lower()}"

    symbol = candidates[0]
    if not symbol.endswith(quote_asset):
        raise BinanceError(f"Signal symbol {symbol} does not match quote asset {quote_asset}")
    client.test_market_buy(symbol=symbol, quote_quantity=limits.order_size)
    client_order_id = _new_client_order_id("BUY", now)
    state.pending_action = f"BUY:{symbol}"
    state.pending_client_order_id = client_order_id
    state.pending_since = now
    save_state(state_path, state)
    order = client.market_buy_by_quote(
        symbol=symbol,
        quote_quantity=limits.order_size,
        live_trading_enabled=True,
        client_order_id=client_order_id,
    )
    spent = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    executed = Decimal(str(order.get("executedQty", "0")))
    if spent <= 0 or executed <= 0:
        raise BinanceError("Live buy returned no executed quantity")
    base_asset = symbol.removesuffix(quote_asset)
    net_quantity = _net_acquired(order, base_asset)
    if net_quantity <= 0:
        raise BinanceError("Live buy returned no net acquired quantity")
    state.position = Position(
        symbol=symbol,
        quantity=str(net_quantity),
        entry_price=str(spent / executed),
        quote_spent=str(spent),
        opened_at=now,
    )
    _clear_pending(state)
    state.trades_today += 1
    save_state(state_path, state)
    if report_trade:
        report_trade({
            "symbol": symbol,
            "side": "BUY",
            "quantity": str(net_quantity),
            "entry_price": str(spent / executed),
            "exit_price": None,
            "pnl": None,
        })

    if _exchange_protection_enabled():
        entry = Decimal(state.position.entry_price)
        stop = entry * (Decimal("1") - limits.stop_fraction)
        target = entry * (Decimal("1") + limits.target_fraction)
        try:
            protection = _install_exchange_protection(client, state, state_path, state.position, stop, target)
            return f"bought:{symbol}:spent={spent};{protection}"
        except BinanceError:
            return f"bought:{symbol}:spent={spent};protection=pending"

    return f"bought:{symbol}:spent={spent}"
