from pathlib import Path

# reporting.py
p = Path('trader/reporting.py')
text = p.read_text()
needle = '''    def record_trade(self, payload: dict[str, Any]) -> None:\n        self._insert("trades", {**payload, "mode": "live"})\n'''
insert = '''    def get_recent_trades(self, limit: int = 1000) -> list[dict[str, Any]]:\n        query = urllib.parse.urlencode({\n            "user_id": f"eq.{self.user_id}",\n            "mode": "eq.live",\n            "select": "symbol,side,quantity,entry_price,created_at",\n            "order": "created_at.asc",\n            "limit": str(limit),\n        })\n        request = urllib.request.Request(\n            f"{self.url}/rest/v1/trades?{query}",\n            headers={"apikey": self.service_role_key, "Authorization": f"Bearer {self.service_role_key}"},\n        )\n        try:\n            with urllib.request.urlopen(request, timeout=10) as response:\n                return json.loads(response.read().decode("utf-8"))\n        except urllib.error.HTTPError as exc:\n            detail = exc.read().decode("utf-8", errors="replace")\n            raise RuntimeError(f"Supabase trades read failed ({exc.code}): {detail}") from exc\n\n    def record_trade(self, payload: dict[str, Any]) -> None:\n        self._insert("trades", {**payload, "mode": "live"})\n'''
if needle not in text:
    raise SystemExit('reporting needle not found')
p.write_text(text.replace(needle, insert))

# binance.py
p = Path('trader/binance.py')
text = p.read_text()
needle = '''    def query_order_list(self, *, order_list_id: int) -> dict[str, Any]:\n        return self._request(\n            "GET",\n            "/api/v3/orderList",\n            {"orderListId": order_list_id},\n            signed=True,\n        )\n\n'''
insert = needle + '''    def open_orders(self, *, symbol: str) -> list[dict[str, Any]]:\n        return self._request("GET", "/api/v3/openOrders", {"symbol": symbol}, signed=True)\n\n'''
if needle not in text:
    raise SystemExit('binance needle not found')
p.write_text(text.replace(needle, insert))

# portfolio_live.py
p = Path('trader/portfolio_live.py')
text = p.read_text()
needle = '''def _reconcile(client, state, path, quote, limits, report_trade):\n'''
recovery = '''def recover_positions_from_trade_history(\n    client: BinanceSpotClient,\n    state_path: Path,\n    trades: list[dict[str, Any]],\n    quote_asset: str,\n) -> list[str]:\n    """Restore missing bot positions from recorded live trades and actual Binance balances."""\n    state = load_state(state_path)\n    existing = {p.symbol for p in state.positions or []}\n    lots: dict[str, dict[str, Any]] = {}\n    for trade in trades:\n        symbol = str(trade.get("symbol") or "")\n        if not symbol.endswith(quote_asset):\n            continue\n        qty = Decimal(str(trade.get("quantity") or "0"))\n        if qty <= 0:\n            continue\n        lot = lots.setdefault(symbol, {"qty": Decimal("0"), "cost": Decimal("0"), "opened_at": 0})\n        if str(trade.get("side") or "").upper() == "BUY":\n            price = Decimal(str(trade.get("entry_price") or "0"))\n            lot["qty"] += qty\n            lot["cost"] += qty * price\n            created = str(trade.get("created_at") or "")\n            try:\n                lot["opened_at"] = max(lot["opened_at"], int(datetime.fromisoformat(created.replace("Z", "+00:00")).timestamp()))\n            except ValueError:\n                pass\n        elif str(trade.get("side") or "").upper() == "SELL" and lot["qty"] > 0:\n            sold = min(qty, lot["qty"])\n            avg = lot["cost"] / lot["qty"] if lot["qty"] > 0 else Decimal("0")\n            lot["qty"] -= sold\n            lot["cost"] = max(Decimal("0"), lot["cost"] - sold * avg)\n            if lot["qty"] <= Decimal("0.00000001"):\n                lot["qty"] = Decimal("0")\n                lot["cost"] = Decimal("0")\n\n    account = client.account()\n    balances = {\n        str(row.get("asset")): Decimal(str(row.get("free", "0"))) + Decimal(str(row.get("locked", "0")))\n        for row in account.get("balances", [])\n    }\n    recovered: list[str] = []\n    now = int(time.time())\n    for symbol, lot in lots.items():\n        if symbol in existing or lot["qty"] <= Decimal("0.00000001"):\n            continue\n        base = symbol.removesuffix(quote_asset)\n        wallet_qty = balances.get(base, Decimal("0"))\n        quantity = min(lot["qty"], wallet_qty)\n        if quantity <= Decimal("0.00000001"):\n            continue\n        avg_price = lot["cost"] / lot["qty"] if lot["qty"] > 0 else Decimal("0")\n        if avg_price <= 0:\n            continue\n        position = Position(\n            symbol=symbol,\n            quantity=str(quantity),\n            entry_price=str(avg_price),\n            quote_spent=str(quantity * avg_price),\n            opened_at=int(lot["opened_at"] or now),\n            strategy="swing",\n        )\n        try:\n            open_orders = client.open_orders(symbol=symbol)\n            bot_orders = [o for o in open_orders if str(o.get("clientOrderId") or "").startswith("ait-")]\n            list_ids = [int(o.get("orderListId")) for o in bot_orders if int(o.get("orderListId", -1)) >= 0]\n            if list_ids:\n                list_id = list_ids[0]\n                position.protective_order_list_id = list_id\n                position.protective_order_ids = tuple(\n                    int(o["orderId"]) for o in bot_orders if int(o.get("orderListId", -1)) == list_id and o.get("orderId") is not None\n                )\n        except BinanceError:\n            pass\n        state.positions.append(position)\n        recovered.append(symbol)\n    if recovered:\n        save_state(state_path, state)\n    return recovered\n\n\n'''
if needle not in text:
    raise SystemExit('portfolio needle not found')
p.write_text(text.replace(needle, recovery + needle))

# worker.py
p = Path('trader/worker.py')
text = p.read_text()
old = 'from .portfolio_live import PortfolioLimits, run_portfolio_cycle\n'
new = 'from .portfolio_live import PortfolioLimits, recover_positions_from_trade_history, run_portfolio_cycle\n'
if old not in text:
    raise SystemExit('worker import not found')
text = text.replace(old, new)
needle = '''            available_balance = free_quote_balance(client, quote_asset) if authenticated else Decimal("0")\n            LOG.info(\n'''
insert = '''            available_balance = free_quote_balance(client, quote_asset) if authenticated else Decimal("0")\n            if authenticated and reporter:\n                recovered = recover_positions_from_trade_history(\n                    client, state_path, reporter.get_recent_trades(), quote_asset\n                )\n                if recovered:\n                    reporter.record_event("state_recovered", f"recovered={','.join(recovered)}", "warning")\n                    LOG.warning("recovered missing positions from trade history: %s", ",".join(recovered))\n            LOG.info(\n'''
if needle not in text:
    raise SystemExit('worker recovery insertion point not found')
p.write_text(text.replace(needle, insert))

# dashboard total assets
p = Path('app/trading-dashboard.tsx')
text = p.read_text()
needle = '''  const serverOnline = lastEvent ? Date.now() - new Date(lastEvent.created_at).getTime() < 900_000 : false;\n  const maxOrderSize = Math.max(5, availableCapital);\n'''
insert = '''  const portfolioValue = useMemo(() => allocations.reduce((sum, allocation) =>\n    sum + (allocation.owned ? Number(allocation.currentValue ?? allocation.invested) : 0), 0), [allocations]);\n  const investedCost = useMemo(() => allocations.reduce((sum, allocation) =>\n    sum + (allocation.owned ? Number(allocation.invested) : 0), 0), [allocations]);\n  const totalAssets = availableCapital + portfolioValue;\n\n  const serverOnline = lastEvent ? Date.now() - new Date(lastEvent.created_at).getTime() < 900_000 : false;\n  const maxOrderSize = Math.max(5, availableCapital);\n'''
if needle not in text:
    raise SystemExit('dashboard summary insertion point not found')
text = text.replace(needle, insert)
needle = '''    <section className="hero"><div><p className="eyebrow">LIVE SPOT-TRADING</p><h2>Tilgjengelig saldo. Spot-only. Harde tapsgrenser.</h2><p className="muted">Binance-uttak, futures og giring er deaktivert.</p></div><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button></section>\n    <section className="grid metrics">\n'''
insert = '''    <section className="hero"><div><p className="eyebrow">LIVE SPOT-TRADING</p><h2>Tilgjengelig saldo. Spot-only. Harde tapsgrenser.</h2><p className="muted">Binance-uttak, futures og giring er deaktivert.</p></div><button className="danger" onClick={() => void emergencyStop()} disabled={saving}>Nødstopp</button></section>\n    <section className="panel" style={{ marginBottom: 18 }}>\n      <div style={{ display: "grid", gridTemplateColumns: "2fr 1fr 1fr", gap: 18, alignItems: "end" }}>\n        <div><span className="label">TOTAL VERDI</span><strong style={{ display: "block", fontSize: "clamp(2.2rem, 5vw, 4.4rem)", lineHeight: 1.05, marginTop: 8 }}>{money(totalAssets)} {settings.quote_asset}</strong><small>Ledige midler + markedsverdi av åpne posisjoner</small></div>\n        <div><span className="label">Investert nå</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(portfolioValue)} {settings.quote_asset}</strong><small>Kostpris: {money(investedCost)} {settings.quote_asset}</small></div>\n        <div><span className="label">Ikke investert</span><strong style={{ display: "block", fontSize: "1.6rem", marginTop: 8 }}>{money(availableCapital)} {settings.quote_asset}</strong><small>Fri saldo</small></div>\n      </div>\n    </section>\n    <section className="grid metrics">\n'''
if needle not in text:
    raise SystemExit('dashboard hero insertion point not found')
p.write_text(text.replace(needle, insert))

# cleanup temporary files after applying
Path('scripts/apply_state_recovery_total_assets.py').unlink(missing_ok=True)
Path('.github/workflows/apply-state-recovery-total-assets.yml').unlink(missing_ok=True)
