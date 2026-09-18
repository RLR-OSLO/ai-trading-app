"""User-confirmed commands, scoped to one account and one position incarnation.

Commands do not enable autonomous trading. Exchange fills, position changes and
command receipts share the existing atomic journal; uncertain orders are queried,
never resubmitted. The manager runs exactly one worker per account.
"""
from decimal import Decimal
import logging
import time

from . import portfolio_live as spot, derivatives_live as short
from .journal import flush_reports

LOG = logging.getLogger("ai_trader.commands")


def position_key(mode, position):
    return f"{mode}:{position.symbol}:{position.opened_at}"


def position_snapshot(spot_path, short_path):
    rows = []
    for position in spot.load_state(spot_path).positions:
        rows.append({"key": position_key("SPOT", position), "symbol": position.symbol,
            "mode": "SPOT", "quantity": position.quantity, "entry_price": position.entry_price,
            "quote_spent": position.quote_spent, "trailing_active": position.trailing_active,
            "trailing_stop_price": position.trailing_stop_price})
    position = short.load_state(short_path).position
    if position:
        rows.append({"key": position_key(position.mode.upper(), position), "symbol": position.symbol,
            "mode": position.mode.upper(), "quantity": position.quantity, "entry_price": position.entry_price,
            "quote_spent": position.notional, "trailing_active": position.trailing_active,
            "trailing_stop_price": position.trailing_stop_price})
    return rows


def _pending(state):
    return bool(getattr(state, "pending_action", None) or getattr(state, "pending_open", None)
                or getattr(state, "pending_close_id", None))


def _receipt(module, path, command, status, result):
    state = module.load_state(path)
    state.command_receipts[str(command["id"])] = {"status": status, "result": result}
    state.active_command = None
    module.save_state(path, state)


def _acknowledge(module, path, reporter):
    state = module.load_state(path)
    flush_reports(state, path, module.save_state, reporter.record_trade)
    for command_id, receipt in list(state.command_receipts.items()):
        reporter.command_result(command_id, receipt["status"], receipt["result"])
        del state.command_receipts[command_id]
        module.save_state(path, state)


def _resume(client, reporter, settings, module, path, state):
    command = state.active_command
    if not _pending(state):
        # A restart may fall between claiming a command and persisting the order.
        # No automatic retry is permitted across that ambiguous boundary.
        _receipt(module, path, command, "rejected", "Avbrutt før ordrebekreftelse. Kontroller historikken før nytt forsøk.")
        return
    if module is spot:
        spot._reconcile(client, state, path, settings.get("quote_asset", "USDC"),
            spot.PortfolioLimits.from_settings(settings), reporter.record_trade)
    else:
        if state.pending_open:
            pending = state.pending_open
            venue = short.BinanceFuturesClient(client.credentials) if pending["mode"] == "futures" else short.BinanceMarginClient(credentials=client.credentials)
            order = venue.query_order(symbol=pending["symbol"], orig_client_order_id=pending["client_id"])
            short._complete_short_open(venue, state, path, order, reporter.record_trade)
        else:
            position = state.position
            venue = short.BinanceFuturesClient(client.credentials) if position.mode == "futures" else short.BinanceMarginClient(credentials=client.credentials)
            order = venue.query_order(symbol=position.symbol, orig_client_order_id=state.pending_close_id)
            short._finalize_short_close(state, path, order, "user_command_reconciled", reporter.record_trade)
    latest = module.load_state(path)
    if latest.active_command and not _pending(latest):
        _receipt(module, path, command, "rejected", "Binance bekreftet ingen utført handel. Du kan sende en ny forespørsel.")


def _close(client, reporter, settings, command, module, path):
    state = module.load_state(path)
    position = next((p for p in state.positions if p.symbol == command["symbol"]), None) if module is spot else state.position
    if not position or position_key(command["mode"], position) != command["position_key"]:
        return "Posisjonen er allerede avsluttet eller erstattet. Ingen ny posisjon ble solgt."
    if module is short and position.mode.upper() != command["mode"]:
        return "Shortposisjonens modus har endret seg. Ingen ordre ble sendt."
    quantity = min(Decimal(position.quantity), Decimal(str(command["quantity"])))
    if module is spot:
        limits = spot.PortfolioLimits.from_settings(settings)
        checked = spot._check_protection(client, state, path, position, limits, reporter.record_trade)
        if checked and checked.startswith("sold:"):
            return checked
        if checked and checked.startswith("protected_status_unavailable:"):
            return "Kunne ikke bekrefte beskyttelsesordrens status hos Binance"
        if not spot._cancel_protection(client, state, path, position):
            return "Kunne ikke frigjøre posisjonen fra beskyttelsesordren hos Binance"
        # A protection leg can fill while cancellation is in flight. Query the
        # original leg IDs before selling again; a filled leg owns the exit.
        for order_id in command.get("protection_ids", []):
            order = client.query_order_by_id(symbol=position.symbol, order_id=order_id)
            if Decimal(str(order.get("executedQty", "0"))) > 0:
                return spot._finalize_sell(state, path, position,
                    Decimal(str(order["executedQty"])), Decimal(str(order["cummulativeQuoteQty"])), limits, reporter.record_trade)
        return spot._market_sell(client, state, path, position, limits, reporter.record_trade,
            int(time.time()), "user_request", maximum_quantity=quantity)
    if position.mode == "futures":
        venue = short.BinanceFuturesClient(client.credentials)
        # reduceOnly prevents an accidental opposite position on a stale close.
        return short._close_futures(venue, state, path, "user_request", reporter.record_trade, quantity)
    venue = short.BinanceMarginClient(credentials=client.credentials)
    base = position.symbol.removesuffix("USDC").removesuffix("USDT")
    balance = next((row for row in venue.margin_account().get("userAssets", []) if row.get("asset") == base), None)
    if balance is None or "netAsset" not in balance:
        return "Binance bekreftet ikke marginbeholdningen. Ingen ordre ble sendt."
    deficit = max(Decimal(0), -Decimal(str(balance["netAsset"])))
    quantity = spot._sellable_quantity(venue, position.symbol, min(quantity, deficit))
    if quantity <= 0:
        return "Ingen åpen margin-short bekreftet hos Binance. Posisjonen må avstemmes."
    # Cancel and verify every protective leg before submitting a margin buyback.
    for order_list_id in position.protection_ids:
        listing = venue.query_order_list(order_list_id=order_list_id)
        if listing.get("listOrderStatus") == "EXECUTING":
            venue.cancel_order_list(symbol=position.symbol, order_list_id=order_list_id)
        for leg in listing.get("orders", []):
            order = venue.query_order_by_id(symbol=position.symbol, order_id=int(leg["orderId"]))
            if Decimal(str(order.get("executedQty", "0"))) > 0:
                return short._finalize_short_close(state, path, order, "exchange_protection", reporter.record_trade)
            if order.get("status") not in {"CANCELED", "EXPIRED", "REJECTED"}:
                return "Venter på at Binance avslutter beskyttelsesordren"
    position.protection_ids = ()
    short.save_state(path, state)
    return short._close_margin(venue, state, path, "user_request", reporter.record_trade, quantity)


def process_commands(client, reporter, settings, spot_path, short_path, *, signals=None, short_signals=None):
    """Return True when an order is being processed; skip autonomous orders then.

Called before analysis for exits, then after analysis for priority entries. Only
MFA-authenticated users can insert commands; the service only consumes their rows.
"""
    if not reporter or not reporter.is_compass or not settings or client.credentials is None:
        return False
    states = [(spot, spot_path), (short, short_path)]
    try:
        for module, path in states:
            _acknowledge(module, path, reporter)
            state = module.load_state(path)
            if state.active_command:
                _resume(client, reporter, settings, module, path, state)
                _acknowledge(module, path, reporter)
                return True
        commands = reporter.get_commands()
        # A service restart before the local checkpoint must never replay an
        # already-claimed command. Executed receipts were acknowledged above.
        commands = [c for c in commands if c.get("user_id") == reporter.user_id]
        processing = next((c for c in commands if c["status"] == "processing"), None)
        if processing:
            reporter.command_result(processing["id"], "rejected", "Avbrutt behandling uten ordrekvittering. Kontroller historikken før nytt forsøk.")
            return True
        commands.sort(key=lambda c: c["action"] != "CLOSE")
        for command in commands:
            if command.get("user_id") != reporter.user_id:
                continue
            if command["action"] != "CLOSE" and signals is None:
                continue
            state = spot.load_state(spot_path)
            derivative = short.load_state(short_path)
            if _pending(state) or _pending(derivative) or state.pending_reports or derivative.pending_reports:
                reporter.command_result(command["id"], "pending", "Venter på bekreftelse og rapportering av forrige ordre")
                return False
            module, path = (spot, spot_path) if command["mode"] == "SPOT" else (short, short_path)
            symbol = command["symbol"]
            if command["action"] == "PRIORITY_OPEN":
                signal = (signals if module is spot else short_signals) or {}
                reason = None
                if not signal.get(symbol):
                    reason = "Venter på et gyldig kjøpssignal" if module is spot else "Venter på et gyldig shortsignal"
                if any(p.symbol == symbol for p in state.positions) or (derivative.position and derivative.position.symbol == symbol):
                    reason = "Posisjonen er fortsatt åpen. Prioriteten venter på at den avsluttes."
                if module is short:
                    configured_mode = "FUTURES" if settings.get("futures_enabled") and settings.get("risk_profile") == "extreme" else "MARGIN"
                    if not settings.get("short_enabled") or command["mode"] != configured_mode or int(command["leverage"]) != (int(settings.get("leverage", 1)) if configured_mode == "FUTURES" else 1):
                        reason = "Valgt shortmodus/giring samsvarer ikke med lagrede innstillinger"
                    elif derivative.position:
                        reason = "Venter på at eksisterende shortposisjon avsluttes"
                if not symbol.endswith(settings.get("quote_asset", "USDC")):
                    reason = "Handelsvaluta er endret; send en ny prioritet"
                if reason:
                    if command.get("result") != reason:
                        reporter.command_result(command["id"], "pending", reason)
                    continue
            claimed = reporter.claim_command(command["id"])
            if not claimed:  # User cancellation won the atomic status comparison.
                continue
            tracked = module.load_state(path)
            active = dict(command)
            if module is spot:
                position = next((p for p in tracked.positions if p.symbol == symbol), None)
                active["protection_ids"] = list(position.protective_order_ids) if position else []
            tracked.active_command = active
            module.save_state(path, tracked)
            if command["action"] == "CLOSE":
                result = _close(client, reporter, settings, active, module, path)
            elif module is spot:
                result = spot.run_portfolio_cycle(client, {symbol: True}, path,
                    spot.PortfolioLimits.from_settings(settings), reporter.record_trade,
                    quote_asset=settings.get("quote_asset", "USDC"), user_priority=True, manage_exits=False,
                    requested_notional=Decimal(str(command["requested_notional"])),
                    other_realized_pnl=Decimal(derivative.realized_pnl),
                    other_open_notional=Decimal(derivative.position.notional) if derivative.position else Decimal(0),
                    blocked_symbols=frozenset({derivative.position.symbol}) if derivative.position else frozenset())
            else:
                result = short.run_short_cycle(client.credentials, {symbol: True}, {}, settings, path,
                    reporter.record_trade, user_priority=True, preferred_symbol=symbol,
                    requested_notional=Decimal(str(command["requested_notional"])),
                    spot_realized_pnl=Decimal(state.realized_pnl),
                    spot_open_notional=sum((Decimal(p.quote_spent) for p in state.positions), Decimal(0)),
                    spot_open_symbols=frozenset(p.symbol for p in state.positions))
            latest = module.load_state(path)
            if latest.active_command and not _pending(latest):
                _receipt(module, path, command, "rejected", result)
            _acknowledge(module, path, reporter)
            return True
        return False
    except Exception as exc:
        # Preserve the original client order ID on every uncertain response.
        LOG.exception("User command awaiting reconciliation")
        for module, path in states:
            try:
                command = module.load_state(path).active_command
                if command:
                    reporter.command_result(command["id"], "processing",
                        f"Avventer avstemming; ordren sendes ikke på nytt. {type(exc).__name__}: {str(exc)[:300]}")
            except Exception:
                LOG.warning("Command status could not be reported")
        return True
