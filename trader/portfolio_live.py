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

PROFILE_LIMITS = {"low": (6, 1800, 1), "normal": (16, 300, 3), "high": (40, 30, 5)}

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
class PortfolioState:
    day: str
    realized_pnl: str = "0"
    trades_today: int = 0
    cooldown_until: int = 0
    positions: list[Position] | None = None
    pending_action: str | None = None
    pending_client_order_id: str | None = None
    pending_since: int = 0
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
        return cls.from_values(os.getenv("LIVE_CAP_USDC", "100"), os.getenv("LIVE_ORDER_USDC", "25"), os.getenv("LIVE_STOP_PERCENT", "1"), os.getenv("LIVE_TARGET_PERCENT", "2"), os.getenv("LIVE_DAILY_LOSS_USDC", "2"), max_trades=int(os.getenv("LIVE_MAX_TRADES_PER_DAY", "16")), cooldown=int(os.getenv("LIVE_COOLDOWN_SECONDS", "300")), max_positions=int(os.getenv("LIVE_MAX_OPEN_POSITIONS", "3")))
    @classmethod
    def from_settings(cls, settings: dict[str, Any]) -> "PortfolioLimits":
        profile = str(settings.get("risk_profile", "normal")).lower()
        max_trades, cooldown, max_positions = PROFILE_LIMITS.get(profile, PROFILE_LIMITS["normal"])
        return cls.from_values(settings.get("trade_cap_usdc", "100"), settings.get("order_size_usdc", "25"), settings.get("stop_loss_percent", "1"), settings.get("take_profit_percent", "2"), settings.get("max_daily_loss_usdc", "2"), max_trades=max_trades, cooldown=cooldown, max_positions=max_positions)
    @classmethod
    def from_values(cls, cap_value: Any, order_value: Any, stop_value: Any, target_value: Any, daily_loss_value: Any, *, max_trades: int, cooldown: int, max_positions: int) -> "PortfolioLimits":
        cap = Decimal(str(cap_value)); order = Decimal(str(order_value)); stop = Decimal(str(stop_value)) / Decimal("100"); target = Decimal(str(target_value)) / Decimal("100"); daily_loss = Decimal(str(daily_loss_value))
        if cap < Decimal("5"): raise ValueError("Available trading capital must be at least 5 quote units")
        if not (Decimal("5") <= order <= cap): raise ValueError("LIVE_ORDER_USDC must be between 5 and available trading capital")
        if not (Decimal("0.0025") <= stop <= Decimal("0.10")): raise ValueError("LIVE_STOP_PERCENT is outside the safety range")
        if not (Decimal("0.005") <= target <= Decimal("0.25")): raise ValueError("LIVE_TARGET_PERCENT is outside the safety range")
        if not (Decimal("0.5") <= daily_loss <= cap): raise ValueError("LIVE_DAILY_LOSS_USDC is outside the safety range")
        if not (1 <= max_trades <= 100): raise ValueError("LIVE_MAX_TRADES_PER_DAY must be between 1 and 100")
        if not (15 <= cooldown <= 86400): raise ValueError("LIVE_COOLDOWN_SECONDS is outside the safety range")
        if not (1 <= max_positions <= 10): raise ValueError("LIVE_MAX_OPEN_POSITIONS must be between 1 and 10")
        return cls(cap, order, stop, target, daily_loss, max_trades, cooldown, max_positions)

def _today() -> str: return datetime.now(UTC).date().isoformat()
def _position_from_raw(raw: dict[str, Any]) -> Position: return Position(raw["symbol"], raw["quantity"], raw["entry_price"], raw["quote_spent"], int(raw["opened_at"]), raw.get("protective_order_list_id"), tuple(int(x) for x in raw.get("protective_order_ids", [])))
def load_state(path: Path) -> PortfolioState:
    if not path.exists(): return PortfolioState(day=_today())
    raw = json.loads(path.read_text(encoding="utf-8"))
    positions = [_position_from_raw(x) for x in raw.get("positions", [])] if raw.get("positions") is not None else ([_position_from_raw(raw["position"])] if raw.get("position") else [])
    state = PortfolioState(raw.get("day", _today()), raw.get("realized_pnl", "0"), int(raw.get("trades_today", 0)), int(raw.get("cooldown_until", 0)), positions, raw.get("pending_action"), raw.get("pending_client_order_id"), int(raw.get("pending_since", 0)))
    if state.day != _today(): state.day, state.realized_pnl, state.trades_today = _today(), "0", 0
    return state

def save_state(path: Path, state: PortfolioState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(asdict(state), separators=(",", ":"), sort_keys=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=path.parent, delete=False) as h: h.write(payload); tmp = Path(h.name)
    tmp.replace(path)
def _free_balance(client: BinanceSpotClient, asset: str) -> Decimal:
    for b in client.account().get("balances", []):
        if b.get("asset") == asset: return Decimal(str(b.get("free", "0")))
    return Decimal("0")
def _net_acquired(order: dict[str, Any], base_asset: str) -> Decimal:
    q = Decimal(str(order.get("executedQty", "0")))
    for f in order.get("fills", []):
        if f.get("commissionAsset") == base_asset: q -= Decimal(str(f.get("commission", "0")))
    return max(q, Decimal("0"))
def _filters(client: BinanceSpotClient, symbol: str):
    info = client.symbol_info(symbol); lot = next(x for x in info.get("filters", []) if x.get("filterType") == "LOT_SIZE"); price = next(x for x in info.get("filters", []) if x.get("filterType") == "PRICE_FILTER"); return lot, price
def _sellable_quantity(client: BinanceSpotClient, symbol: str, q: Decimal) -> Decimal:
    lot, _ = _filters(client, symbol); step = Decimal(str(lot["stepSize"])); return (q / step).to_integral_value(rounding=ROUND_DOWN) * step
def _tick_price(client: BinanceSpotClient, symbol: str, p: Decimal) -> Decimal:
    _, pf = _filters(client, symbol); tick = Decimal(str(pf["tickSize"])); return (p / tick).to_integral_value(rounding=ROUND_DOWN) * tick
def _clear_pending(state: PortfolioState) -> None: state.pending_action = None; state.pending_client_order_id = None; state.pending_since = 0
def _find(state: PortfolioState, symbol: str) -> Position | None: return next((p for p in state.positions or [] if p.symbol == symbol), None)
def _remove(state: PortfolioState, symbol: str) -> None: state.positions = [p for p in state.positions or [] if p.symbol != symbol]
def _client_id(side: str, symbol: str, now: int) -> str: return f"ait-{side.lower()}-{symbol.lower()[:8]}-{now}"[:36]
def _protection_enabled() -> bool: return os.getenv("EXCHANGE_PROTECTION_ENABLED", "true").strip().lower() in {"1","true","yes","on"}

def _finalize_sell(client_state: PortfolioState, path: Path, position: Position, quantity: Decimal, received: Decimal, limits: PortfolioLimits, report_trade: Callable[[dict[str, Any]], None] | None) -> str:
    if quantity <= 0 or received <= 0: raise BinanceError("Sell execution returned invalid quantity or proceeds")
    pnl = received - Decimal(position.quote_spent); client_state.realized_pnl = str(Decimal(client_state.realized_pnl) + pnl); _remove(client_state, position.symbol); _clear_pending(client_state); client_state.trades_today += 1; client_state.cooldown_until = int(time.time()) + limits.cooldown_seconds; save_state(path, client_state)
    if report_trade: report_trade({"symbol": position.symbol, "side": "SELL", "quantity": str(quantity), "entry_price": position.entry_price, "exit_price": str(received / quantity), "pnl": str(pnl)})
    return f"sold:{position.symbol}:pnl={pnl}"

def _install_protection(client: BinanceSpotClient, state: PortfolioState, path: Path, p: Position, stop: Decimal, target: Decimal) -> str:
    q = _sellable_quantity(client, p.symbol, Decimal(p.quantity))
    if q <= 0: raise BinanceError("No sellable quantity available for protective OCO")
    r = client.place_protective_oco_sell(symbol=p.symbol, quantity=q, target_price=_tick_price(client, p.symbol, target), stop_price=_tick_price(client, p.symbol, stop), live_trading_enabled=True, list_client_order_id=f"ait-oco-{int(time.time())}-{p.symbol.lower()}"[:36])
    if r.get("orderListId") is None or len(r.get("orders", [])) != 2: raise BinanceError("Protective OCO returned an incomplete response")
    p.protective_order_list_id = int(r["orderListId"]); p.protective_order_ids = tuple(int(x["orderId"]) for x in r["orders"]); save_state(path, state); return f"protected:{p.symbol}:oco={p.protective_order_list_id}"

def _check_protection(client: BinanceSpotClient, state: PortfolioState, path: Path, p: Position, limits: PortfolioLimits, report_trade):
    if p.protective_order_list_id is None: return None
    try: ol = client.query_order_list(order_list_id=p.protective_order_list_id)
    except BinanceError: return f"protected_status_unavailable:{p.symbol}"
    if str(ol.get("listOrderStatus", "")) == "EXECUTING": return f"protected:{p.symbol}:oco={p.protective_order_list_id}"
    ids = p.protective_order_ids or tuple(int(x["orderId"]) for x in ol.get("orders", []) if x.get("orderId") is not None)
    for oid in ids:
        try: order = client.query_order_by_id(symbol=p.symbol, order_id=oid)
        except BinanceError: continue
        if order.get("status") == "FILLED": return _finalize_sell(state, path, p, Decimal(str(order.get("executedQty", "0"))), Decimal(str(order.get("cummulativeQuoteQty", "0"))), limits, report_trade)
    p.protective_order_list_id = None; p.protective_order_ids = (); save_state(path, state); return None

def _reconcile(client: BinanceSpotClient, state: PortfolioState, path: Path, quote: str, limits: PortfolioLimits, report_trade):
    if not state.pending_action: return None
    if not state.pending_client_order_id: return f"paused_pending_reconciliation:{state.pending_action}"
    side, symbol = state.pending_action.split(":", 1)
    try: order = client.query_order(symbol=symbol, orig_client_order_id=state.pending_client_order_id)
    except BinanceError as exc:
        if "-2013" in str(exc) and state.pending_since and int(time.time()) - state.pending_since >= 60: _clear_pending(state); save_state(path, state); return "reconciled_missing_order"
        return f"paused_pending_reconciliation:{state.pending_action}"
    status = str(order.get("status", ""))
    if status not in {"FILLED","CANCELED","EXPIRED","REJECTED"}: return f"pending_exchange_order:{side}:{status or 'UNKNOWN'}"
    if status != "FILLED": _clear_pending(state); save_state(path, state); return f"reconciled_{status.lower()}:{side}:{symbol}"
    ex = Decimal(str(order.get("executedQty", "0"))); qq = Decimal(str(order.get("cummulativeQuoteQty", "0"))); now = int(time.time())
    if side == "BUY":
        if ex <= 0 or qq <= 0: return f"paused_pending_reconciliation:{state.pending_action}"
        available = _free_balance(client, symbol.removesuffix(quote)); q = min(ex, available) if available > 0 else ex
        if _find(state, symbol) is None: state.positions.append(Position(symbol, str(q), str(qq / ex), str(qq), state.pending_since or now))
        state.trades_today += 1; _clear_pending(state); save_state(path, state)
        if report_trade: report_trade({"symbol": symbol, "side": "BUY", "quantity": str(q), "entry_price": str(qq / ex), "exit_price": None, "pnl": None})
        return f"reconciled_buy:{symbol}"
    if side == "SELL":
        p = _find(state, symbol)
        if p: return _finalize_sell(state, path, p, ex, qq, limits, report_trade)
    return f"paused_pending_reconciliation:{state.pending_action}"

def run_portfolio_cycle(client: BinanceSpotClient, signals: dict[str, bool], state_path: Path, limits: PortfolioLimits, report_trade: Callable[[dict[str, Any]], None] | None = None, *, allow_new_entries: bool = True, quote_asset: str = "USDC") -> str:
    state = load_state(state_path); now = int(time.time()); quote = quote_asset.upper()
    reconciled = _reconcile(client, state, state_path, quote, limits, report_trade)
    if reconciled: return reconciled
    notes: list[str] = []
    for p in list(state.positions or []):
        checked = _check_protection(client, state, state_path, p, limits, report_trade)
        if checked and checked.startswith("sold:"): return checked
        if checked: notes.append(checked); continue
        current = client.ticker_price(p.symbol); entry = Decimal(p.entry_price); stop = entry * (Decimal("1") - limits.stop_fraction); target = entry * (Decimal("1") + limits.target_fraction)
        if stop < current < target and _protection_enabled():
            try: notes.append(_install_protection(client, state, state_path, p, stop, target))
            except BinanceError: notes.append(f"holding_unprotected:{p.symbol}")
            continue
        if stop < current < target: notes.append(f"holding:{p.symbol}"); continue
        q = _sellable_quantity(client, p.symbol, Decimal(p.quantity))
        if q <= 0: notes.append(f"unsellable:{p.symbol}"); continue
        cid = _client_id("SELL", p.symbol, now); state.pending_action = f"SELL:{p.symbol}"; state.pending_client_order_id = cid; state.pending_since = now; save_state(state_path, state)
        order = client.place_spot_order(symbol=p.symbol, side="SELL", order_type="MARKET", quantity=q, live_trading_enabled=True, client_order_id=cid)
        return _finalize_sell(state, state_path, p, q, Decimal(str(order.get("cummulativeQuoteQty", "0"))), limits, report_trade)
    if not allow_new_entries: return "paused_new_entries" if not notes else ";".join(notes)
    if Decimal(state.realized_pnl) <= -limits.daily_loss: return "paused_daily_loss"
    if state.trades_today >= limits.max_trades_per_day: return "paused_trade_limit"
    if len(state.positions or []) >= limits.max_open_positions: return f"max_positions:{len(state.positions or [])}"
    if now < state.cooldown_until: return "cooldown"
    open_symbols = {p.symbol for p in state.positions or []}; candidates = [s for s, active in signals.items() if active and s not in open_symbols]
    if not candidates: return ";".join(notes) if notes else "no_signal"
    free_quote = _free_balance(client, quote)
    if free_quote < limits.order_size: return f"insufficient_{quote.lower()}"
    symbol = candidates[0]
    if not symbol.endswith(quote): raise BinanceError(f"Signal symbol {symbol} does not match quote asset {quote}")
    spend = min(limits.order_size, free_quote); client.test_market_buy(symbol=symbol, quote_quantity=spend); cid = _client_id("BUY", symbol, now); state.pending_action = f"BUY:{symbol}"; state.pending_client_order_id = cid; state.pending_since = now; save_state(state_path, state)
    order = client.market_buy_by_quote(symbol=symbol, quote_quantity=spend, live_trading_enabled=True, client_order_id=cid); spent = Decimal(str(order.get("cummulativeQuoteQty", "0"))); ex = Decimal(str(order.get("executedQty", "0")))
    if spent <= 0 or ex <= 0: raise BinanceError("Live buy returned no executed quantity")
    net = _net_acquired(order, symbol.removesuffix(quote))
    if net <= 0: raise BinanceError("Live buy returned no net acquired quantity")
    p = Position(symbol, str(net), str(spent / ex), str(spent), now); state.positions.append(p); _clear_pending(state); state.trades_today += 1; state.cooldown_until = now + limits.cooldown_seconds; save_state(state_path, state)
    if report_trade: report_trade({"symbol": symbol, "side": "BUY", "quantity": str(net), "entry_price": str(spent / ex), "exit_price": None, "pnl": None})
    if _protection_enabled():
        entry = Decimal(p.entry_price); stop = entry * (Decimal("1") - limits.stop_fraction); target = entry * (Decimal("1") + limits.target_fraction)
        try: protection = _install_protection(client, state, state_path, p, stop, target); return f"bought:{symbol}:spent={spent};{protection};open={len(state.positions)}"
        except BinanceError: return f"bought:{symbol}:spent={spent};protection=pending;open={len(state.positions)}"
    return f"bought:{symbol}:spent={spent};open={len(state.positions)}"
