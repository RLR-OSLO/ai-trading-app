from pathlib import Path

# --- trader/worker.py: make generic negative news a penalty, not a blanket veto for normal/high ---
p = Path('trader/worker.py')
t = p.read_text(encoding='utf-8')
old = '''    swing_threshold = RISK_THRESHOLDS.get(risk_profile, RISK_THRESHOLDS["normal"])
    scalp_enabled = risk_profile in {"normal", "high"}
    blocked_by_news = news.blocks_new_positions

    bullruns = {pair: bullrun_candidate(analyses[pair], scalp_analyses[pair], risk_profile) for pair in pairs}
'''
new = '''    swing_threshold = RISK_THRESHOLDS.get(risk_profile, RISK_THRESHOLDS["normal"])
    scalp_enabled = risk_profile in {"normal", "high"}
    # Generic negative crypto headlines used to veto every new entry, which made the
    # daytrader unnecessarily idle even when individual markets had strong signals.
    # Low risk keeps the hard veto. Normal/high instead require one extra swing point.
    hard_news_block = news.blocks_new_positions and risk_profile == "low"
    news_penalty = 1 if news.blocks_new_positions and risk_profile in {"normal", "high"} else 0
    effective_swing_threshold = swing_threshold + news_penalty

    bullruns = {pair: bullrun_candidate(analyses[pair], scalp_analyses[pair], risk_profile) for pair in pairs}
'''
if old not in t:
    raise SystemExit('worker news block marker not found')
t = t.replace(old, new, 1)
t = t.replace('''            analyses[pair].score >= swing_threshold
            and "risk_veto" not in analyses[pair].reasons
            and not blocked_by_news
        )
        scalp_signal = scalp_enabled and scalp_analyses[pair].signal and not blocked_by_news
        bullrun_signal = bullruns[pair] and not blocked_by_news
''','''            analyses[pair].score >= effective_swing_threshold
            and "risk_veto" not in analyses[pair].reasons
            and not hard_news_block
        )
        scalp_signal = scalp_enabled and scalp_analyses[pair].signal and not hard_news_block
        bullrun_signal = bullruns[pair] and not hard_news_block
''',1)
t = t.replace('''        f"threshold={swing_threshold};risk={risk_profile};btc_regime={btc_regime};"
        f"news={news.score:.2f};headlines={news.fresh_headlines};scalp={scalp_signal_text};bullrun={bullrun_text}"
''','''        f"threshold={effective_swing_threshold};base_threshold={swing_threshold};risk={risk_profile};btc_regime={btc_regime};"
        f"news={news.score:.2f};news_penalty={news_penalty};headlines={news.fresh_headlines};scalp={scalp_signal_text};bullrun={bullrun_text}"
''',1)
p.write_text(t, encoding='utf-8')

# --- trader/portfolio_live.py: allow more concurrent positions in high risk and honor manual per-order cap ---
p = Path('trader/portfolio_live.py')
t = p.read_text(encoding='utf-8')
t = t.replace('PROFILE_LIMITS = {"low": (6, 1800, 1), "normal": (16, 300, 3), "high": (80, 15, 5)}',
              'PROFILE_LIMITS = {"low": (6, 1800, 1), "normal": (24, 180, 4), "high": (100, 15, 8)}')
t = t.replace('''        if not (Decimal("5") <= order <= cap):
            raise ValueError("LIVE_ORDER_USDC must be between 5 and available trading capital")
''','''        if order < Decimal("5"):
            raise ValueError("LIVE_ORDER_USDC must be at least 5 quote units")
''',1)
t = t.replace('''    if free_quote < limits.order_size:
        return f"insufficient_{quote.lower()}"
''','''    if free_quote < Decimal("5"):
        return f"insufficient_{quote.lower()}"
''',1)
t = t.replace('''    multiplier = max(Decimal("0.5"), min(Decimal("1.5"), Decimal(str((entry_size_multipliers or {}).get(symbol, Decimal("1"))))))
    max_fraction_of_free = Decimal("0.35")
    spend = min(limits.order_size * multiplier, free_quote * max_fraction_of_free, free_quote)
''','''    multiplier = max(Decimal("0.5"), min(Decimal("1.5"), Decimal(str((entry_size_multipliers or {}).get(symbol, Decimal("1"))))))
    # order_size is the user's maximum amount per investment. Risk presets provide
    # a sensible default, but a manual override is honored up to the actual free balance.
    spend = min(limits.order_size * multiplier, free_quote)
''',1)
p.write_text(t, encoding='utf-8')

# --- dashboard: manual order cap can exceed today's free balance; actual execution still caps at Binance free balance ---
p = Path('app/trading-dashboard.tsx')
t = p.read_text(encoding='utf-8')
t = t.replace('  const maxOrderSize = Math.max(5, availableCapital);\n', '')
t = t.replace('''    const safe = { ...settings, trade_cap_usdc: effectiveCapital, order_size_usdc: Math.min(effectiveCapital, Math.max(5, Number(settings.order_size_usdc))), max_daily_loss_usdc: Math.min(effectiveCapital, Math.max(0.5, Number(settings.max_daily_loss_usdc))), updated_at: new Date().toISOString(), user_id: userData.user.id };
''','''    const safe = { ...settings, trade_cap_usdc: effectiveCapital, order_size_usdc: Math.max(5, Number(settings.order_size_usdc)), max_daily_loss_usdc: Math.min(effectiveCapital, Math.max(0.5, Number(settings.max_daily_loss_usdc))), updated_at: new Date().toISOString(), user_id: userData.user.id };
''',1)
t = t.replace('''        <Field label={`Ordrestørrelse (${settings.quote_asset})`} value={settings.order_size_usdc} min={5} max={maxOrderSize} step={5} onChange={(value) => update("order_size_usdc", value)} />
''','''        <Field label={`Maks per investering (${settings.quote_asset})`} value={settings.order_size_usdc} min={5} step={5} onChange={(value) => update("order_size_usdc", value)} />
''',1)
t = t.replace('''<small>Bytte av risikonivå setter automatisk nye standardverdier for ordrestørrelse, stop-loss, gevinstmål og maks dagstap.</small>''','''<small>Bytte av risikonivå setter automatisk nye standardverdier. Du kan deretter overstyre «Maks per investering» manuelt. Boten bruker aldri mer enn faktisk ledig Binance-saldo.</small>''',1)
p.write_text(t, encoding='utf-8')
