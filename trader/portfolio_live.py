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

PROFILE_LIMITS = {"low": (6, 1800, 1), "normal": (16, 300, 3), "high": (80, 15, 5)}
SCALP_STOP_FRACTION = Decimal("0.0045")
SCALP_TARGET_FRACTION = Decimal("0.0075")
SCALP_MAX_HOLD_SECONDS = 900
TRAILING_OCO_CEILING_FRACTION = Decimal("0.50")
TRAILING_REFRESH_FRACTION = Decimal("0.001")


@dataclass
class Position:
    symbol: str
    quantity: str
    entry_price: str
    quote_spent: str
    opened_at: int
    protective_order_list_id: int | None = None
    protective_order_ids: tuple[int, ...] = ()
    strategy: str = "swing"
    stop_fraction: str | None = None
    target_fraction: str | None = None
    max_hold_seconds: int | None = None
    peak_price: str | None = None
    trailing_active: bool = False
    trailing_stop_price: str | None = None


@dataclass
class PortfolioState:
    day: str
    realized_pnl: str = "0"
    trades_today: int = 0
    cooldown_until: int = 0
    positions: list[Position] | None = None
    pending_action: str | None = None
    pending_client_order_id: str | None = None
    pending_since: int = 0
    pending_strategy: str = "swing"
    pending_stop_fraction: str | None = None
    pending_target_fraction: str | None = None
    pending_max_hold_seconds: int | None = None

    def __post_init__(self) -> None:
        if self.positions is None:
            self.positions = []


@dataclass(frozen=True)
class PortfolioLimits:
    capital_cap: Decimal
    order_size: Decimal
    stop_fraction: Decimal
    target_fraction: Decimal
    daily_loss: Decimal
    max_trades_per_day: int
    cooldown_seconds: int
    max_open_positions: int

    @classmethod
    def from_env(cls) -> "PortfolioLimits":
        return cls.from_values(
            os.getenv("LIVE_CAP_USDC", "100"),
            os.getenv("LIVE_ORDER_USDC", "25"),
            os.getenv("LIVE_STOP_PERCENT", "1"),
            os.getenv("LIVE_TARGET_PERCENT", "2"),
            os.getenv("LIVE_DAILY_LOSS_USDC", "2"),
            max_trades=int(os.getenv("LIVE_MAX_TRADES_PER_DAY", "16")),
            cooldown=int(os.getenv("LIVE_COOLDOWN_SECONDS", "300")),
            max_positions=int(os.getenv("LIVE_MAX_OPEN_POSITIONS", "3")),
        )

    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> "PortfolioLimits":
        profile = str(settings.get("risk_profile", "normal")).lower()
        max_trades, cooldown, max_positions = PROFILE_LIMITS.get(profile, PROFILE_LIMITS["normal"])
        return cls.from_values(
            settings.get("trade_cap_usdc", "100"),
            settings.get("order_size_usdc", "25"),
            settings.get("stop_loss_percent", "1"),
            settings.get("take_profit_percent", "2"),
            settings.get("max_daily_loss_usdc", "2"),
            max_trades=max_trades,
            cooldown=cooldown,
            max_positions=max_positions,
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
        max_trades: int,
        cooldown: int,
        max_positions: int,
    ) -> "PortfolioLimits":
        cap = Decimal(str(cap_value))
        order = Decimal(str(order_value))
        stop = Decimal(str(stop_value)) / Decimal("100")
        target = Decimal(str(target_value)) / Decimal("100")
        daily_loss = Decimal(str(daily_loss_value))
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
        if not (1 <= max_trades <= 100):
            raise ValueError("LIVE_MAX_TRADES_PER_DAY must be between 1 and 100")
        if not (15 <= cooldown <= 86400):
            raise ValueError("LIVE_COOLDOWN_SECONDS is outside the safety range")
        if not (1 <= max_positions <= 10):
            raise ValueError("LIVE_MAX_OPEN_POSITIONS must be between 1 and 10")
        return cls(cap, order, stop, target, daily_loss, max_trades, cooldown, max_positions)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _position_from_raw(raw: dict[str, Any]) -> Position:
    return Position(
        raw["symbol"], raw["quantity"], raw["entry_price"], raw["quote_spent"], int(raw["opened_at"]),
        raw.get("protective_order_list_id"),
        tuple(int(x) for x in raw.get("protective_order_ids", [])),
        str(raw.get("strategy") or "swing"), raw.get("stop_fraction"), raw.get("target_fraction"),
        int(raw["max_hold_seconds"]) if raw.get("max_hold_seconds") is not None else None,
        raw.get("peak_price"), bool(raw.get("trailing_active", False)), raw.get("trailing_stop_price"),
    )


def load_state(path: Path) -> PortfolioState:
    if not path.exists():
        return PortfolioState(day=_today())
    raw = json.loads(path.read_text(encoding="utf-8"))
    positions = ([_position_from_raw(x) for x in raw.get("positions", [])]
                 if raw.get("positions") is not None
                 else ([_position_from_raw(raw["position"])] if raw.get("position") else []))
    state = PortfolioState(
        raw.get("day", _today()), raw.get("realized_pnl", "0"), int(raw.get("trades_today", 0)),
        int(raw.get("cooldown_until", 0)), positions, raw.get("pending_action"),
        raw.get("pending_client_order_id"), int(raw.get("pending_since", 0)),
        str(raw.get("pending_strategy") or "swing"), raw.get("pending_stop_fraction"),
        raw.get("pending_target_fraction"),
        int(raw["pending_max_hold_seconds"]) if raw.get("pending_max_hold_seconds") is not None else None,
    )
    if state.day != _today():
        state.day, state.realized_pnl, state.trades_today = _today(), "0", 0
    return state


def save_state(path: Path, state: PortfolioState) -> None:
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


def _net_acquired(order: dict[str, Any], base_asset: str) -> Decimal:
    quantity = Decimal(str(order.get("executedQty", "0")))
    for fill in order.get("fills", []):
        if fill.get("commissionAsset") == base_asset:
            quantity -= Decimal(str(fill.get("commission", "0")))
    return max(quantity, Decimal("0"))


def _filters(client: BinanceSpotClient, symbol: str):
    info = client.symbol_info(symbol)
    lot = next(x for x in info.get("filters", []) if x.get("filterType") == "LOT_SIZE")
    price = next(x for x in info.get("filters", []) if x.get("filterType") == "PRICE_FILTER")
    return lot, price


def _sellable_quantity(client: BinanceSpotClient, symbol: str, quantity: Decimal) -> Decimal:
    lot, _ = _filters(client, symbol)
    step = Decimal(str(lot["stepSize"]))
    return (quantity / step).to_integral_value(rounding=ROUND_DOWN) * step


def _tick_price(client: BinanceSpotClient, symbol: str, price: Decimal) -> Decimal:
    _, price_filter = _filters(client, symbol)
    tick = Decimal(str(price_filter["tickSize"]))
    return (price / tick).to_integral_value(rounding=ROUND_DOWN) * tick


def _clear_pending(state: PortfolioState) -> None:
    state.pending_action = None
    state.pending_client_order_id = None
    state.pending_since = 0
    state.pending_strategy = "swing"
    state.pending_stop_fraction = None
    state.pending_target_fraction = None
    state.pending_max_hold_seconds = None


def _find(state: PortfolioState, symbol: str) -> Position | None:
    return next((p for p in state.positions or [] if p.symbol == symbol), None)


def _remove(state: PortfolioState, symbol: str) -> None:
    state.positions = [p for p in state.positions or [] if p.symbol != symbol]


def _client_id(side: str, symbol: str, now: int) -> str:
    return f"ait-{side.lower()}-{symbol.lower()[:8]}-{now}"[:36]


def _protection_enabled() -> bool:
    return os.getenv("EXCHANGE_PROTECTION_ENABLED", "true").strip().lower() in {"1", "true", "yes", "on"}


def _position_limits(position: Position, limits: PortfolioLimits) -> tuple[Decimal, Decimal]:
    return (
        Decimal(position.stop_fraction) if position.stop_fraction is not None else limits.stop_fraction,
        Decimal(position.target_fraction) if position.target_fraction is not None else limits.target_fraction,
    )


def _finalize_sell(state, path, position, quantity, received, limits, report_trade) -> str:
    if quantity <= 0 or received <= 0:
        raise BinanceError("Sell execution returned invalid quantity or proceeds")
    pnl = received - Decimal(position.quote_spent)
    state.realized_pnl = str(Decimal(state.realized_pnl) + pnl)
    _remove(state, position.symbol)
    _clear_pending(state)
    state.trades_today += 1
    state.cooldown_until = int(time.time()) + limits.cooldown_seconds
    save_state(path, state)
    if report_trade:
        report_trade({"symbol": position.symbol, "side": "SELL", "quantity": str(quantity),
                      "entry_price": position.entry_price, "exit_price": str(received / quantity), "pnl": str(pnl)})
    return f"sold:{position.symbol}:pnl={pnl};strategy={position.strategy}"


def _install_protection(client, state, path, position, stop: Decimal, target: Decimal) -> str:
    quantity = _sellable_quantity(client, position.symbol, Decimal(position.quantity))
    if quantity <= 0:
        raise BinanceError("No sellable quantity available for protective OCO")
    response = client.place_protective_oco_sell(
        symbol=position.symbol, quantity=quantity,
        target_price=_tick_price(client, position.symbol, target),
        stop_price=_tick_price(client, position.symbol, stop),
        live_trading_enabled=True,
        list_client_order_id=f"ait-oco-{int(time.time())}-{position.symbol.lower()}"[:36],
    )
    if response.get("orderListId") is None or len(response.get("orders", [])) != 2:
        raise BinanceError("Protective OCO returned an incomplete response")
    position.protective_order_list_id = int(response["orderListId"])
    position.protective_order_ids = tuple(int(x["orderId"]) for x in response["orders"])
    save_state(path, state)
    return f"protected:{position.symbol}:oco={position.protective_order_list_id}"


def _cancel_protection(client, state, path, position: Position) -> bool:
    if position.protective_order_list_id is None and not position.protective_order_ids:
        return True
    cancelled = False
    if position.protective_order_list_id is not None:
        try:
            client.cancel_order_list(symbol=position.symbol, order_list_id=position.protective_order_list_id)
            cancelled = True
        except BinanceError:
            pass
    if not cancelled:
        try:
            open_orders = client.open_orders(symbol=position.symbol)
        except BinanceError:
            return False
        bot_orders = [
            order for order in open_orders
            if str(order.get("clientOrderId") or "").startswith("ait-")
            or int(order.get("orderId", -1)) in set(position.protective_order_ids)
            or (position.protective_order_list_id is not None and int(order.get("orderListId", -1)) == position.protective_order_list_id)
        ]
        for order in bot_orders:
            order_id = int(order.get("orderId", -1))
            if order_id < 0:
                continue
            try:
                client.cancel_order(symbol=position.symbol, order_id=order_id)
                cancelled = True
            except BinanceError:
                continue
        try:
            still_open = client.open_orders(symbol=position.symbol)
        except BinanceError:
            return False
        blocked_ids = set(position.protective_order_ids)
        for order in still_open:
            if (str(order.get("clientOrderId") or "").startswith("ait-")
                or int(order.get("orderId", -1)) in blocked_ids
                or (position.protective_order_list_id is not None and int(order.get("orderListId", -1)) == position.protective_order_list_id)):
                return False
    position.protective_order_list_id = None
    position.protective_order_ids = ()
    save_state(path, state)
    return True


def _check_protection(client, state, path, position, limits, report_trade):
    if position.protective_order_list_id is None:
        return None
    try:
        order_list = client.query_order_list(order_list_id=position.protective_order_list_id)
    except BinanceError:
        return f"protected_status_unavailable:{position.symbol}"
    if str(order_list.get("listOrderStatus", "")) == "EXECUTING":
        return f"protected:{position.symbol}:oco={position.protective_order_list_id}"
    ids = position.protective_order_ids or tuple(
        int(x["orderId"]) for x in order_list.get("orders", []) if x.get("orderId") is not None
    )
    for order_id in ids:
        try:
            order = client.query_order_by_id(symbol=position.symbol, order_id=order_id)
        except BinanceError:
            continue
        if order.get("status") == "FILLED":
            return _finalize_sell(state, path, position, Decimal(str(order.get("executedQty", "0"))),
                                  Decimal(str(order.get("cummulativeQuoteQty", "0"))), limits, report_trade)
    position.protective_order_list_id = None
    position.protective_order_ids = ()
    save_state(path, state)
    return None


def recover_positions_from_trade_history(
    client: BinanceSpotClient,
    state_path: Path,
    trades: list[dict[str, Any]],
    quote_asset: str,
) -> list[str]:
    """Restore missing bot positions from recorded live trades and actual Binance balances."""
    state = load_state(state_path)
    existing = {p.symbol for p in state.positions or []}
    lots: dict[str, dict[str, Any]] = {}
    for trade in trades:
        symbol = str(trade.get("symbol") or "")
        if not symbol.endswith(quote_asset):
            continue
        qty = Decimal(str(trade.get("quantity") or "0"))
        if qty <= 0:
            continue
        lot = lots.setdefault(symbol, {"qty": Decimal("0"), "cost": Decimal("0"), "opened_at": 0})
        if str(trade.get("side") or "").upper() == "BUY":
            price = Decimal(str(trade.get("entry_price") or "0"))
            lot["qty"] += qty
            lot["cost"] += qty * price
            created = str(trade.get("created_at") or "")
            try:
                lot["opened_at"] = max(lot["opened_at"], int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()))
            except ValueError:
                pass
        elif str(trade.get("side") or "").upper() == "SELL" and lot["qty"] > 0:
            sold = min(qty, lot["qty"])
            avg = lot["cost"] / lot["qty"] if lot["qty"] > 0 else Decimal("0")
            lot["qty"] -= sold
            lot["cost"] = max(Decimal("0"), lot["cost"] - sold * avg)
            if lot["qty"] <= Decimal("0.00000001"):
                lot["qty"] = Decimal("0")
                lot["cost"] = Decimal("0")

    account = client.account()
    balances = {
        str(row.get("asset")): Decimal(str(row.get("free", "0"))) + Decimal(str(row.get("locked", "0")))
        for row in account.get("balances", [])
    }
    recovered: list[str] = []
    now = int(time.time())
    for symbol, lot in lots.items():
        if symbol in existing or lot["qty"] <= Decimal("0.00000001"):
            continue
        base = symbol.removesuffix(quote_asset)
        wallet_qty = balances.get(base, Decimal("0"))
        quantity = min(lot["qty"], wallet_qty)
        if quantity <= Decimal("0.00000001"):
            continue
        avg_price = lot["cost"] / lot["qty"] if lot["qty"] > 0 else Decimal("0")
        if avg_price <= 0:
            continue
        position = Position(
            symbol=symbol,
            quantity=str(quantity),
            entry_price=str(avg_price),
            quote_spent=str(quantity * avg_price),
            opened_at=int(lot["opened_at"] or now),
            strategy="swing",
        )
        try:
            open_orders = client.open_orders(symbol=symbol)
            bot_orders = [o for o in open_orders if str(o.get("clientOrderId") or "").startswith("ait-")]
            list_ids = [int(o.get("orderListId")) for o in bot_orders if int(o.get("orderListId", -1)) >= 0]
            if list_ids:
                list_id = list_ids[0]
                position.protective_order_list_id = list_id
                position.protective_order_ids = tuple(
                    int(o["orderId"]) for o in bot_orders if int(o.get("orderListId", -1)) == list_id and o.get("orderId") is not None
                )
        except BinanceError:
            pass
        state.positions.append(position)
        recovered.append(symbol)
    if recovered:
        save_state(state_path, state)
    return recovered


def _reconcile(client, state, path, quote, limits, report_trade):
    if not state.pending_action:
        return None
    if not state.pending_client_order_id:
        return f"paused_pending_reconciliation:{state.pending_action}"
    side, symbol = state.pending_action.split(":", 1)
    try:
        order = client.query_order(symbol=symbol, orig_client_order_id=state.pending_client_order_id)
    except BinanceError as exc:
        if "-2013" in str(exc) and state.pending_since and int(time.time()) - state.pending_since >= 60:
            _clear_pending(state); save_state(path, state); return "reconciled_missing_order"
        return f"paused_pending_reconciliation:{state.pending_action}"
    status = str(order.get("status", ""))
    if status not in {"FILLED", "CANCELED", "EXPIRED", "REJECTED"}:
        return f"pending_exchange_order:{side}:{status or 'UNKNOWN'}"
    if status != "FILLED":
        _clear_pending(state); save_state(path, state); return f"reconciled_{status.lower()}:{side}:{symbol}"
    executed = Decimal(str(order.get("executedQty", "0")))
    quote_qty = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    now = int(time.time())
    if side == "BUY":
        if executed <= 0 or quote_qty <= 0:
            return f"paused_pending_reconciliation:{state.pending_action}"
        available = _free_balance(client, symbol.removesuffix(quote))
        quantity = min(executed, available) if available > 0 else executed
        if _find(state, symbol) is None:
            state.positions.append(Position(
                symbol, str(quantity), str(quote_qty / executed), str(quote_qty), state.pending_since or now,
                strategy=state.pending_strategy, stop_fraction=state.pending_stop_fraction,
                target_fraction=state.pending_target_fraction, max_hold_seconds=state.pending_max_hold_seconds,
                peak_price=str(quote_qty / executed),
            ))
        state.trades_today += 1
        strategy = state.pending_strategy
        _clear_pending(state); save_state(path, state)
        if report_trade:
            report_trade({"symbol": symbol, "side": "BUY", "quantity": str(quantity),
                          "entry_price": str(quote_qty / executed), "exit_price": None, "pnl": None})
        return f"reconciled_buy:{symbol};strategy={strategy}"
    if side == "SELL":
        position = _find(state, symbol)
        if position:
            return _finalize_sell(state, path, position, executed, quote_qty, limits, report_trade)
    return f"paused_pending_reconciliation:{state.pending_action}"


def _market_sell(client, state, state_path, position, limits, report_trade, now: int, reason: str) -> str:
    base_asset = position.symbol.removesuffix("USDC") if position.symbol.endswith("USDC") else position.symbol.removesuffix("USDT")
    free_balance = _free_balance(client, base_asset)
    quantity = _sellable_quantity(client, position.symbol, min(Decimal(position.quantity), free_balance))
    if quantity <= 0:
        return f"unsellable:{position.symbol}:free={free_balance}"
    client_id = _client_id("SELL", position.symbol, now)
    state.pending_action = f"SELL:{position.symbol}"
    state.pending_client_order_id = client_id
    state.pending_since = now
    save_state(state_path, state)
    order = client.place_spot_order(symbol=position.symbol, side="SELL", order_type="MARKET", quantity=quantity,
                                    live_trading_enabled=True, client_order_id=client_id)
    result = _finalize_sell(state, state_path, position, quantity,
                            Decimal(str(order.get("cummulativeQuoteQty", "0"))), limits, report_trade)
    return f"{result};reason={reason}"


def run_portfolio_cycle(
    client: BinanceSpotClient,
    signals: dict[str, bool],
    state_path: Path,
    limits: PortfolioLimits,
    report_trade: Callable[[dict[str, Any]], None] | None = None,
    *,
    allow_new_entries: bool = True,
    quote_asset: str = "USDC",
    entry_strategies: dict[str, str] | None = None,
) -> str:
    state = load_state(state_path)
    now = int(time.time())
    quote = quote_asset.upper()
    reconciled = _reconcile(client, state, state_path, quote, limits, report_trade)
    if reconciled:
        return reconciled

    notes: list[str] = []
    for position in list(state.positions or []):
        expired_scalp = position.strategy == "scalp" and position.max_hold_seconds is not None and now - position.opened_at >= position.max_hold_seconds
        if expired_scalp:
            if not _cancel_protection(client, state, state_path, position):
                notes.append(f"scalp_expiry_cancel_failed:{position.symbol}")
                continue
            return _market_sell(client, state, state_path, position, limits, report_trade, now, "timeout")

        checked = _check_protection(client, state, state_path, position, limits, report_trade)
        if checked and checked.startswith("sold:"):
            return checked
        if checked and checked.startswith("protected_status_unavailable:"):
            notes.append(checked)
            continue

        current = client.ticker_price(position.symbol)
        entry = Decimal(position.entry_price)
        stop_fraction, activation_fraction = _position_limits(position, limits)
        hard_stop = entry * (Decimal("1") - stop_fraction)
        activation = entry * (Decimal("1") + activation_fraction)
        peak = Decimal(position.peak_price) if position.peak_price is not None else entry

        if not position.trailing_active and current >= activation:
            if position.protective_order_list_id is not None and not _cancel_protection(client, state, state_path, position):
                notes.append(f"trailing_activation_cancel_failed:{position.symbol}")
                continue
            position.trailing_active = True
            peak = max(peak, current)
            position.peak_price = str(peak)
            trailing_stop = peak * (Decimal("1") - stop_fraction)
            position.trailing_stop_price = str(trailing_stop)
            save_state(state_path, state)
            if _protection_enabled():
                ceiling = peak * (Decimal("1") + TRAILING_OCO_CEILING_FRACTION)
                try:
                    _install_protection(client, state, state_path, position, trailing_stop, ceiling)
                except BinanceError:
                    notes.append(f"trailing_unprotected:{position.symbol}")
            notes.append(f"trailing_active:{position.symbol}:peak={peak}:stop={trailing_stop}")
            continue

        if position.trailing_active:
            old_stop = Decimal(position.trailing_stop_price) if position.trailing_stop_price else peak * (Decimal("1") - stop_fraction)
            if current > peak:
                new_peak = current
                new_stop = new_peak * (Decimal("1") - stop_fraction)
                position.peak_price = str(new_peak)
                position.trailing_stop_price = str(new_stop)
                save_state(state_path, state)
                if new_stop >= old_stop * (Decimal("1") + TRAILING_REFRESH_FRACTION) and _protection_enabled():
                    if position.protective_order_list_id is not None and not _cancel_protection(client, state, state_path, position):
                        notes.append(f"trailing_refresh_cancel_failed:{position.symbol}")
                        continue
                    ceiling = new_peak * (Decimal("1") + TRAILING_OCO_CEILING_FRACTION)
                    try:
                        _install_protection(client, state, state_path, position, new_stop, ceiling)
                    except BinanceError:
                        notes.append(f"trailing_unprotected:{position.symbol}")
                notes.append(f"trailing_raise:{position.symbol}:peak={new_peak}:stop={new_stop}")
                continue
            trailing_stop = Decimal(position.trailing_stop_price or old_stop)
            if current <= trailing_stop:
                if position.protective_order_list_id is not None:
                    if not _cancel_protection(client, state, state_path, position):
                        notes.append(f"trailing_stop_cancel_failed:{position.symbol}")
                        continue
                return _market_sell(client, state, state_path, position, limits, report_trade, now, "trailing_stop")
            notes.append(f"trailing_hold:{position.symbol}:peak={peak}:stop={trailing_stop}")
            continue

        if current <= hard_stop:
            if position.protective_order_list_id is not None:
                if not _cancel_protection(client, state, state_path, position):
                    notes.append(f"hard_stop_cancel_failed:{position.symbol}")
                    continue
            return _market_sell(client, state, state_path, position, limits, report_trade, now, "hard_stop")

        if position.protective_order_list_id is None and _protection_enabled():
            ceiling = entry * (Decimal("1") + TRAILING_OCO_CEILING_FRACTION)
            try:
                notes.append(_install_protection(client, state, state_path, position, hard_stop, ceiling))
            except BinanceError:
                notes.append(f"holding_unprotected:{position.symbol}")
            continue
        notes.append(f"holding:{position.symbol}")

    if not allow_new_entries:
        return "paused_new_entries" if not notes else ";".join(notes)
    if Decimal(state.realized_pnl) <= -limits.daily_loss:
        return "paused_daily_loss"
    if state.trades_today >= limits.max_trades_per_day:
        return "paused_trade_limit"
    if len(state.positions or []) >= limits.max_open_positions:
        return f"max_positions:{len(state.positions or [])}"
    if now < state.cooldown_until:
        return "cooldown"

    open_symbols = {p.symbol for p in state.positions or []}
    candidates = [symbol for symbol, active in signals.items() if active and symbol not in open_symbols]
    if not candidates:
        return ";".join(notes) if notes else "no_signal"
    free_quote = _free_balance(client, quote)
    if free_quote < limits.order_size:
        return f"insufficient_{quote.lower()}"

    symbol = candidates[0]
    if not symbol.endswith(quote):
        raise BinanceError(f"Signal symbol {symbol} does not match quote asset {quote}")
    strategy = (entry_strategies or {}).get(symbol, "swing")
    if strategy == "scalp":
        stop_fraction, activation_fraction, max_hold = SCALP_STOP_FRACTION, SCALP_TARGET_FRACTION, SCALP_MAX_HOLD_SECONDS
    else:
        stop_fraction, activation_fraction, max_hold = limits.stop_fraction, limits.target_fraction, None

    spend = min(limits.order_size, free_quote)
    client.test_market_buy(symbol=symbol, quote_quantity=spend)
    client_id = _client_id("BUY", symbol, now)
    state.pending_action = f"BUY:{symbol}"
    state.pending_client_order_id = client_id
    state.pending_since = now
    state.pending_strategy = strategy
    state.pending_stop_fraction = str(stop_fraction)
    state.pending_target_fraction = str(activation_fraction)
    state.pending_max_hold_seconds = max_hold
    save_state(state_path, state)

    order = client.market_buy_by_quote(symbol=symbol, quote_quantity=spend, live_trading_enabled=True, client_order_id=client_id)
    spent = Decimal(str(order.get("cummulativeQuoteQty", "0")))
    executed = Decimal(str(order.get("executedQty", "0")))
    if spent <= 0 or executed <= 0:
        raise BinanceError("Live buy returned no executed quantity")
    net = _net_acquired(order, symbol.removesuffix(quote))
    if net <= 0:
        raise BinanceError("Live buy returned no net acquired quantity")

    entry = spent / executed
    position = Position(symbol, str(net), str(entry), str(spent), now, strategy=strategy,
                        stop_fraction=str(stop_fraction), target_fraction=str(activation_fraction),
                        max_hold_seconds=max_hold, peak_price=str(entry))
    state.positions.append(position)
    _clear_pending(state)
    state.trades_today += 1
    state.cooldown_until = now + limits.cooldown_seconds
    save_state(state_path, state)
    if report_trade:
        report_trade({"symbol": symbol, "side": "BUY", "quantity": str(net), "entry_price": str(entry), "exit_price": None, "pnl": None})

    if _protection_enabled():
        hard_stop = entry * (Decimal("1") - stop_fraction)
        ceiling = entry * (Decimal("1") + TRAILING_OCO_CEILING_FRACTION)
        try:
            protection = _install_protection(client, state, state_path, position, hard_stop, ceiling)
            return f"bought:{symbol}:spent={spent};strategy={strategy};trailing_at={activation_fraction};{protection};open={len(state.positions)}"
        except BinanceError:
            return f"bought:{symbol}:spent={spent};strategy={strategy};trailing_at={activation_fraction};protection=pending;open={len(state.positions)}"
    return f"bought:{symbol}:spent={spent};strategy={strategy};trailing_at={activation_fraction};open={len(state.positions)}"
