from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"marker missing in {path}: {old[:140]!r}")
    p.write_text(text.replace(old, new, 1))
    print(f"patched {path}")

# 1) Reporter: user-isolated directive queue.
replace_once(
    "trader/reporting.py",
    "    def record_event(self, event_type: str, message: str, level: str = \"info\") -> None:\n        self._insert(\"bot_events\", {\"level\": level, \"event_type\": event_type, \"message\": message})",
    '''    def get_pending_directive(self) -> dict[str, Any] | None:\n        query = urllib.parse.urlencode({\n            "user_id": f"eq.{self.user_id}",\n            "status": "eq.pending",\n            "expires_at": "gt.now()",\n            "select": "id,symbol,direction,mode,requested_notional,leverage,created_at,expires_at",\n            "order": "created_at.desc",\n            "limit": "1",\n        })\n        request = urllib.request.Request(\n            f"{self.url}/rest/v1/trade_directives?{query}",\n            headers={"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}"},\n        )\n        try:\n            with urllib.request.urlopen(request, timeout=10) as response:\n                rows = json.loads(response.read().decode("utf-8"))\n        except urllib.error.HTTPError as exc:\n            detail = exc.read().decode("utf-8", errors="replace")\n            raise RuntimeError(f"Supabase directive read failed ({exc.code}): {detail}") from exc\n        return rows[0] if rows else None\n\n    def finish_directive(self, directive_id: int, status: str, result: str) -> None:\n        if status not in {"executed", "rejected", "expired"}:\n            raise ValueError(f"Unsupported directive status: {status}")\n        body = json.dumps({"status": status, "result": result[:1000], "handled_at": "now()"}).encode("utf-8")\n        query = urllib.parse.urlencode({"id": f"eq.{directive_id}", "user_id": f"eq.{self.user_id}"})\n        # PostgREST cannot interpret now() inside JSON, so handled_at is omitted; status/result are authoritative.\n        body = json.dumps({"status": status, "result": result[:1000]}).encode("utf-8")\n        request = urllib.request.Request(\n            f"{self.url}/rest/v1/trade_directives?{query}", data=body, method="PATCH",\n            headers={"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}", "Content-Type": "application/json", "Prefer": "return=minimal"},\n        )\n        try:\n            with urllib.request.urlopen(request, timeout=10):\n                return\n        except urllib.error.HTTPError as exc:\n            detail = exc.read().decode("utf-8", errors="replace")\n            raise RuntimeError(f"Supabase directive update failed ({exc.code}): {detail}") from exc\n\n    def record_event(self, event_type: str, message: str, level: str = "info") -> None:\n        self._insert("bot_events", {"level": level, "event_type": event_type, "message": message})'''
)

# 2) Derivative engine: allow a valid directive to pick the symbol and requested notional,
# while keeping all global hard limits and profile/toggle checks.
replace_once(
    "trader/derivatives_live.py",
    '''    allow_new_entries: bool = True,\n) -> str:''',
    '''    allow_new_entries: bool = True,\n    preferred_symbol: str | None = None,\n    requested_notional: Decimal | None = None,\n) -> str:'''
)
replace_once(
    "trader/derivatives_live.py",
    '''    candidates = [symbol for symbol, active in short_signals.items() if active]\n    if not candidates:\n        return "no_short_signal"\n    symbol = max(candidates, key=lambda item: confidences.get(item, Decimal("0")))''',
    '''    candidates = [symbol for symbol, active in short_signals.items() if active]\n    if not candidates:\n        return "no_short_signal"\n    if preferred_symbol and preferred_symbol in candidates:\n        symbol = preferred_symbol\n    else:\n        symbol = max(candidates, key=lambda item: confidences.get(item, Decimal("0")))'''
)
replace_once(
    "trader/derivatives_live.py",
    '''    notional = min(max_position * multiplier, capital_cap)''',
    '''    automatic_notional = min(max_position * multiplier, capital_cap)\n    notional = min(max_position, capital_cap, requested_notional) if requested_notional is not None else automatic_notional'''
)

# 3) Worker: consume one fresh directive, prioritize only a still-valid bot signal,
# and mark it complete only after the engine reports an opened position.
replace_once(
    "trader/worker.py",
    '''            dashboard_live = (\n                bool(settings.get("bot_enabled")) and bool(settings.get("live_trading_enabled"))\n                if settings is not None else reporter is None\n            )\n            allow_new_entries = master_live and dashboard_live''',
    '''            dashboard_live = (\n                bool(settings.get("bot_enabled")) and bool(settings.get("live_trading_enabled"))\n                if settings is not None else reporter is None\n            )\n            allow_new_entries = master_live and dashboard_live\n            directive = reporter.get_pending_directive() if reporter and settings is not None else None\n            directive_symbol = str((directive or {}).get("symbol") or "")\n            directive_direction = str((directive or {}).get("direction") or "")\n            directive_mode = str((directive or {}).get("mode") or "")\n            directive_notional = Decimal(str((directive or {}).get("requested_notional") or "0")) if directive else None\n            if directive:\n                valid_symbol = directive_symbol in pairs\n                valid_long = directive_direction == "LONG" and bool(signals.get(directive_symbol)) and directive_mode == "SPOT"\n                configured_short_mode = "FUTURES" if bool(settings.get("futures_enabled")) and risk_profile == "extreme" else "MARGIN"\n                valid_short = directive_direction == "SHORT" and bool(short_signals.get(directive_symbol)) and bool(settings.get("short_enabled")) and directive_mode == configured_short_mode\n                if not valid_symbol or not (valid_long or valid_short):\n                    reporter.finish_directive(int(directive["id"]), "rejected", "Signal/settings changed before execution")\n                    reporter.record_event("trade_directive_rejected", f"symbol={directive_symbol};direction={directive_direction};mode={directive_mode}", "warning")\n                    directive = None\n                    directive_symbol = ""\n                    directive_direction = ""\n                    directive_notional = None\n                else:\n                    reporter.record_event("trade_directive_active", f"symbol={directive_symbol};direction={directive_direction};mode={directive_mode};notional={directive_notional}")'''
)
replace_once(
    "trader/worker.py",
    '''            result = run_portfolio_cycle(\n                client,\n                signals,''',
    '''            if directive and directive_direction == "LONG":\n                signals = {directive_symbol: True, **{k: v for k, v in signals.items() if k != directive_symbol}}\n                if settings and directive_notional is not None:\n                    order_max = max(Decimal("5"), Decimal(str(settings.get("order_size_usdc", "25"))))\n                    size_multipliers[directive_symbol] = max(Decimal("0.25"), min(Decimal("1"), directive_notional / order_max))\n\n            result = run_portfolio_cycle(\n                client,\n                signals,'''
)
replace_once(
    "trader/worker.py",
    '''            if not allow_new_entries and result == "paused_new_entries":\n                LOG.info("new entries paused; no open position requires management")\n            else:\n                LOG.warning("live cycle result=%s", result)''',
    '''            if directive and directive_direction == "LONG" and result.startswith("bought:"):\n                reporter.finish_directive(int(directive["id"]), "executed", result)\n                reporter.record_event("trade_directive_executed", result)\n                directive = None\n            if not allow_new_entries and result == "paused_new_entries":\n                LOG.info("new entries paused; no open position requires management")\n            else:\n                LOG.warning("live cycle result=%s", result)'''
)
replace_once(
    "trader/worker.py",
    '''                    spot_realized_pnl=Decimal(spot_state.realized_pnl),\n                    allow_new_entries=allow_new_entries,\n                )''',
    '''                    spot_realized_pnl=Decimal(spot_state.realized_pnl),\n                    allow_new_entries=allow_new_entries,\n                    preferred_symbol=directive_symbol if directive and directive_direction == "SHORT" else None,\n                    requested_notional=directive_notional if directive and directive_direction == "SHORT" else None,\n                )'''
)
replace_once(
    "trader/worker.py",
    '''                if short_result not in {"short_disabled", "no_short_signal", "short_new_entries_paused"}:\n                    LOG.warning("derivatives cycle result=%s", short_result)''',
    '''                if directive and directive_direction == "SHORT" and (short_result.startswith("margin_short_opened:") or short_result.startswith("futures_short_opened:")):\n                    reporter.finish_directive(int(directive["id"]), "executed", short_result)\n                    reporter.record_event("trade_directive_executed", short_result)\n                    directive = None\n                if short_result not in {"short_disabled", "no_short_signal", "short_new_entries_paused"}:\n                    LOG.warning("derivatives cycle result=%s", short_result)'''
)

# 4) Dashboard: button on each active LONG/SHORT suggestion. The click creates a short-lived,
# user-isolated directive; the worker still enforces live toggle, signal, daily loss, capital,
# cooldown, position limits and configured derivative mode.
replace_once(
    "app/trading-dashboard.tsx",
    '''  async function downloadTradesCsv() {''',
    '''  async function prioritizeSetup(setup: { symbol: string; direction: "LONG" | "SHORT" | "VENT"; mode: string; suggested: number }) {\n    if (setup.direction === "VENT") return;\n    const confirmed = window.confirm(`Be boten prioritere og gjennomføre ${setup.direction} ${setup.symbol} via ${setup.mode} for ca. ${money(setup.suggested)} ${settings.quote_asset}? Alle vanlige risikogrenser gjelder fortsatt.`);\n    if (!confirmed) return;\n    const { data: userData } = await supabase.auth.getUser();\n    if (!userData.user) { setMessage("Du må være innlogget."); return; }\n    const cleanMode = setup.mode.startsWith("FUTURES") ? "FUTURES" : setup.mode === "MARGIN" ? "MARGIN" : "SPOT";\n    const { error } = await supabase.from("trade_directives").insert({\n      user_id: userData.user.id,\n      symbol: setup.symbol,\n      direction: setup.direction,\n      mode: cleanMode,\n      requested_notional: Math.max(5, setup.suggested),\n      leverage: cleanMode === "FUTURES" ? Math.max(1, Math.min(3, settings.leverage)) : 1,\n    });\n    setMessage(error ? `Kunne ikke sende direktiv: ${error.message}` : `Direktiv sendt: prioriter ${setup.direction} ${setup.symbol}. Boten forsøker på neste syklus hvis signalet fortsatt er gyldig.`);\n  }\n\n  async function downloadTradesCsv() {'''
)
replace_once(
    "app/trading-dashboard.tsx",
    '''        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>\n      </article>)}</div>}''',
    '''        <small>Foreslått størrelse: <b>{money(setup.suggested)} {settings.quote_asset}</b></small>\n        {setup.direction !== "VENT" && <button type="button" className="primary compact" onClick={() => void prioritizeSetup(setup)}>Prioriter og gjennomfør</button>}\n      </article>)}</div>}'''
)
replace_once(
    "app/trading-dashboard.tsx",
    '''      <p className="muted best-setup-note">Denne rangeringen er beslutningsstøtte. Boten bruker fortsatt stop-loss, maks dagstap, kapitaltak, cooldown og posisjonsgrenser før en faktisk handel kan gjennomføres.</p>''',
    '''      <p className="muted best-setup-note">«Prioriter og gjennomfør» sender et kortvarig direktiv til boten – ikke en Binance-ordre fra nettleseren. Boten gjennomfører bare dersom samme signal fortsatt er gyldig og alle vanlige stop-loss-, dagstap-, kapital-, cooldown- og posisjonsgrenser fortsatt er oppfylt.</p>'''
)

print("UPGRADE_TRADE_DIRECTIVES_V10_OK")
