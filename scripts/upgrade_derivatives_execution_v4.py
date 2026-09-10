from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    s = p.read_text(encoding="utf-8")
    if old not in s:
        raise SystemExit(f"marker missing in {path}: {old[:100]!r}")
    p.write_text(s.replace(old, new, 1), encoding="utf-8")
    print(f"patched {path}")


# Worker imports.
replace_once(
    "trader/worker.py",
    "from .analysis import MarketAnalysis, analyze_market, bullish_btc_regime\n",
    "from .analysis import MarketAnalysis, analyze_market, bullish_btc_regime\nfrom .directional import BearishAnalysis, analyze_bearish_market\nfrom .derivatives_live import run_short_cycle\n",
)

# Reuse the already fetched swing candles for bearish analysis; no extra Binance scan load.
replace_once(
    "trader/worker.py",
    '    analyses = {pair: analyze_market(data) for pair, data in swing_frames.items()}\n    aggressive_scalping = risk_profile in {"high", "extreme"}\n',
    '    analyses = {pair: analyze_market(data) for pair, data in swing_frames.items()}\n    bearish_analyses = {pair: analyze_bearish_market(data) for pair, data in swing_frames.items()}\n    aggressive_scalping = risk_profile in {"high", "extreme"}\n',
)

replace_once(
    "trader/worker.py",
    '    signals: dict[str, bool] = {}\n    strategies: dict[str, str] = {}\n',
    '    signals: dict[str, bool] = {}\n    short_signals: dict[str, bool] = {}\n    strategies: dict[str, str] = {}\n',
)

replace_once(
    "trader/worker.py",
    '        signals[pair] = bullrun_signal or scalp_signal or swing_signal\n        strategies[pair] = "bullrun" if bullrun_signal else ("scalp" if scalp_signal else "swing")\n',
    '        signals[pair] = bullrun_signal or scalp_signal or swing_signal\n        strategies[pair] = "bullrun" if bullrun_signal else ("scalp" if scalp_signal else "swing")\n        bearish = bearish_analyses[pair]\n        short_threshold = 7 if risk_profile == "high" else 6\n        short_signals[pair] = (\n            risk_profile in {"high", "extreme"}\n            and bearish.score >= short_threshold\n            and "short_risk_veto" not in bearish.reasons\n            and not hard_news_block\n            and not signals[pair]\n        )\n',
)

replace_once(
    "trader/worker.py",
    '    bullrun_text = ",".join(pair for pair in ranked if bullruns[pair]) or "none"\n    context = (\n',
    '    bullrun_text = ",".join(pair for pair in ranked if bullruns[pair]) or "none"\n    short_text = ",".join(pair for pair in ranked if short_signals[pair]) or "none"\n    context = (\n',
)

replace_once(
    "trader/worker.py",
    '        f"news={news.score:.2f};news_penalty={news_penalty};headlines={news.fresh_headlines};scalp={scalp_signal_text};bullrun={bullrun_text}"\n    )\n    return signals, analyses, scalp_analyses, strategies, context\n',
    '        f"news={news.score:.2f};news_penalty={news_penalty};headlines={news.fresh_headlines};scalp={scalp_signal_text};bullrun={bullrun_text};shorts={short_text}"\n    )\n    return signals, short_signals, analyses, bearish_analyses, scalp_analyses, strategies, context\n',
)

replace_once(
    "trader/worker.py",
    '            signals, analyses, scalp_analyses, strategies, context = market_scan(\n',
    '            signals, short_signals, analyses, bearish_analyses, scalp_analyses, strategies, context = market_scan(\n',
)

replace_once(
    "trader/worker.py",
    '            scalp_score_text = ",".join(f"{pair}:{analysis.score}" for pair, analysis in scalp_analyses.items())\n            LOG.info(\n                "market scan; buy_signals=%s; %s; swing_scores=%s; scalp_scores=%s",\n                signal_text,\n                context,\n                score_text,\n                scalp_score_text,\n            )\n',
    '            scalp_score_text = ",".join(f"{pair}:{analysis.score}" for pair, analysis in scalp_analyses.items())\n            short_score_text = ",".join(f"{pair}:{analysis.score}" for pair, analysis in bearish_analyses.items())\n            LOG.info(\n                "market scan; buy_signals=%s; %s; swing_scores=%s; scalp_scores=%s; short_scores=%s",\n                signal_text,\n                context,\n                score_text,\n                scalp_score_text,\n                short_score_text,\n            )\n',
)

# Run a single protected derivative short position at a time. It remains behind the
# dashboard short/futures toggles and the existing master/dashboard live locks.
replace_once(
    "trader/worker.py",
    '            if not allow_new_entries and result == "paused_new_entries":\n                LOG.info("new entries paused; no open position requires management")\n            else:\n                LOG.warning("live cycle result=%s", result)\n',
    '            if not allow_new_entries and result == "paused_new_entries":\n                LOG.info("new entries paused; no open position requires management")\n            else:\n                LOG.warning("live cycle result=%s", result)\n\n            if client.credentials is not None and settings is not None:\n                spot_state = load_state(state_path)\n                short_confidences = {pair: bearish_analyses[pair].confidence for pair in pairs}\n                short_result = run_short_cycle(\n                    client.credentials,\n                    short_signals,\n                    short_confidences,\n                    settings,\n                    Path(os.getenv("DERIVATIVES_STATE_PATH", "/var/lib/ai-trading-app/derivatives-state.json")),\n                    reporter.record_trade if reporter else None,\n                    spot_realized_pnl=Decimal(spot_state.realized_pnl),\n                    allow_new_entries=allow_new_entries,\n                )\n                if short_result not in {"short_disabled", "no_short_signal", "short_new_entries_paused"}:\n                    LOG.warning("derivatives cycle result=%s", short_result)\n',
)

# Reporting: preserve explicit trade mode so margin/futures do not masquerade as spot.
replace_once(
    "trader/reporting.py",
    '    def record_trade(self, payload: dict[str, Any]) -> None:\n        self._insert("trades", {**payload, "mode": "live"})\n',
    '    def record_trade(self, payload: dict[str, Any]) -> None:\n        clean = dict(payload)\n        mode = str(clean.pop("mode", "live"))\n        if mode not in {"paper", "live", "margin", "futures"}:\n            raise ValueError(f"Unsupported trade mode: {mode}")\n        self._insert("trades", {**clean, "mode": mode})\n',
)

# Dashboard: derivative SELL opens must never reduce the displayed spot holdings.
replace_once(
    "app/trading-dashboard.tsx",
    '    const assetTrades = trades.filter((trade) => trade.symbol === symbol);\n',
    '    const assetTrades = trades.filter((trade) => trade.symbol === symbol && trade.mode === "live");\n',
)
replace_once(
    "app/trading-dashboard.tsx",
    '<b>{trade.side} {trade.symbol}</b>',
    '<b>{trade.mode.toUpperCase()} · {trade.side} {trade.symbol}</b>',
)

print("UPGRADE_DERIVATIVES_EXECUTION_V4_OK")
