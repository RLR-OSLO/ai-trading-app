from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from pathlib import Path

from .binance import BinanceCredentials, BinanceError, BinanceSpotClient
from .analysis import MarketAnalysis, analyze_market, bullish_btc_regime
from .config import DEFAULT_CONFIG
from .live import LiveLimits, run_live_cycle
from .news import NewsMonitor
from .reporting import SupabaseReporter


LOG = logging.getLogger("ai_trader")
RISK_THRESHOLDS = {"low": 7, "normal": 6, "high": 5}


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configured_pairs(quote_asset: str | None = None) -> tuple[str, ...]:
    quote = (quote_asset or os.getenv("TRADING_QUOTE_ASSET", "USDC")).upper()
    if quote not in DEFAULT_CONFIG.preferred_quote_assets:
        raise ValueError("Quote asset is outside the approved allowlist")
    return tuple(f"{asset}{quote}" for asset in DEFAULT_CONFIG.symbols)


def build_client() -> BinanceSpotClient:
    api_key = os.getenv("BINANCE_API_KEY", "")
    secret_key = os.getenv("BINANCE_SECRET_KEY", "")
    credentials = None
    if api_key or secret_key:
        credentials = BinanceCredentials(api_key, secret_key)
        credentials.validate()
    return BinanceSpotClient(
        credentials=credentials,
        base_url=os.getenv("BINANCE_BASE_URL", "https://api.binance.com"),
    )


def readiness_check(client: BinanceSpotClient, pairs: tuple[str, ...] | None = None) -> bool:
    active_pairs = pairs or configured_pairs()
    client.server_time()
    info = client.exchange_info(active_pairs)
    available = {item["symbol"] for item in info.get("symbols", [])}
    missing = set(active_pairs) - available
    if missing:
        raise BinanceError(f"Approved pairs unavailable: {sorted(missing)}")
    if client.credentials is not None:
        client.account()
        return True
    return False


def free_quote_balance(client: BinanceSpotClient, quote_asset: str) -> Decimal:
    for balance in client.account().get("balances", []):
        if balance.get("asset") == quote_asset:
            return Decimal(str(balance.get("free", "0")))
    return Decimal("0")


def market_scan(
    client: BinanceSpotClient,
    news_monitor: NewsMonitor,
    pairs: tuple[str, ...],
    risk_profile: str,
) -> tuple[dict[str, bool], dict[str, MarketAnalysis], str]:
    frames = {
        pair: {interval: client.klines(pair, interval, limit=101)[:-1] for interval in ("15m", "1h", "4h")}
        for pair in pairs
    }
    btc_regime = bullish_btc_regime(frames[pairs[0]])
    news = news_monitor.score()
    analyses = {pair: analyze_market(data) for pair, data in frames.items()}
    ordered = sorted(analyses, key=lambda pair: analyses[pair].score, reverse=True)
    threshold = RISK_THRESHOLDS.get(risk_profile, RISK_THRESHOLDS["normal"])
    signals = {
        pair: analyses[pair].score >= threshold
        and "risk_veto" not in analyses[pair].reasons
        and not news.blocks_new_positions
        for pair in ordered
    }
    context = (
        f"threshold={threshold};risk={risk_profile};btc_regime={btc_regime};"
        f"news={news.score:.2f};headlines={news.fresh_headlines}"
    )
    return signals, analyses, context


def main() -> None:
    logging.basicConfig(
        level=os.getenv("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    client = build_client()
    reporter = SupabaseReporter.from_env()
    news_monitor = NewsMonitor()
    master_live = _bool_env("LIVE_TRADING_ENABLED")
    state_path = Path(os.getenv("LIVE_STATE_PATH", "/var/lib/ai-trading-app/live-state.json"))
    last_heartbeat = 0.0
    LOG.info("worker starting; master_live=%s", master_live)

    while True:
        try:
            settings = reporter.get_settings() if reporter else None
            quote_asset = str((settings or {}).get("quote_asset") or os.getenv("TRADING_QUOTE_ASSET", "USDC")).upper()
            risk_profile = str((settings or {}).get("risk_profile") or "normal").lower()
            pairs = configured_pairs(quote_asset)
            authenticated = readiness_check(client, pairs)
            available_balance = free_quote_balance(client, quote_asset) if authenticated else Decimal("0")
            LOG.info(
                "health check passed; authenticated_account_read=%s; available_%s=%s",
                authenticated,
                quote_asset.lower(),
                available_balance,
            )

            signals, analyses, context = market_scan(client, news_monitor, pairs, risk_profile)
            signal_text = ",".join(pair for pair, signal in signals.items() if signal) or "none"
            score_text = ",".join(f"{pair}:{analysis.score}" for pair, analysis in analyses.items())
            LOG.info("market scan; buy_signals=%s; %s; scores=%s", signal_text, context, score_text)

            dashboard_live = (
                bool(settings.get("bot_enabled")) and bool(settings.get("live_trading_enabled"))
                if settings is not None else reporter is None
            )
            allow_new_entries = master_live and dashboard_live

            if reporter and time.time() - last_heartbeat >= 120:
                best_pair = max(analyses, key=lambda pair: analyses[pair].score)
                best = analyses[best_pair]
                reporter.record_event(
                    "heartbeat",
                    f"live={allow_new_entries};available={available_balance};quote={quote_asset};{context};"
                    f"signals={signal_text};scores={score_text};best={best_pair}:{best.score};"
                    f"reasons={','.join(best.reasons)}",
                )
                last_heartbeat = time.time()

            runtime_settings = dict(settings or {})
            runtime_settings["trade_cap_usdc"] = str(max(available_balance, Decimal("5")))
            result = run_live_cycle(
                client,
                signals,
                state_path,
                LiveLimits.from_settings(runtime_settings) if settings else LiveLimits.from_env(),
                reporter.record_trade if reporter else None,
                allow_new_entries=allow_new_entries,
                quote_asset=quote_asset,
            )
            if not allow_new_entries and result == "paused_new_entries":
                LOG.info("new entries paused; no open position requires management")
            else:
                LOG.warning("live cycle result=%s", result)
        except Exception:
            LOG.exception("trading cycle failed; no new order will be submitted")
        time.sleep(int(os.getenv("WORKER_INTERVAL_SECONDS", "30")))


if __name__ == "__main__":
    main()
