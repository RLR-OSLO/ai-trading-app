from __future__ import annotations

import logging
import os
import time
from pathlib import Path

from .binance import BinanceCredentials, BinanceError, BinanceSpotClient
from .analysis import MarketAnalysis, analyze_market, bullish_btc_regime
from .config import DEFAULT_CONFIG
from .live import LiveLimits, run_live_cycle
from .news import NewsMonitor
from .reporting import SupabaseReporter


LOG = logging.getLogger("ai_trader")


def _bool_env(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configured_pairs() -> tuple[str, ...]:
    quote = os.getenv("TRADING_QUOTE_ASSET", "USDC").upper()
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


def readiness_check(client: BinanceSpotClient) -> bool:
    pairs = configured_pairs()
    client.server_time()
    info = client.exchange_info(pairs)
    available = {item["symbol"] for item in info.get("symbols", [])}
    missing = set(pairs) - available
    if missing:
        raise BinanceError(f"Approved pairs unavailable: {sorted(missing)}")
    if client.credentials is not None:
        client.account()
        return True
    return False


def market_scan(client: BinanceSpotClient, news_monitor: NewsMonitor) -> tuple[dict[str, bool], dict[str, MarketAnalysis], str]:
    pairs = configured_pairs()
    frames = {
        pair: {interval: client.klines(pair, interval, limit=101)[:-1] for interval in ("15m", "1h", "4h")}
        for pair in pairs
    }
    regime = bullish_btc_regime(frames[pairs[0]])
    news = news_monitor.score()
    analyses = {pair: analyze_market(data) for pair, data in frames.items()}
    ordered = sorted(analyses, key=lambda pair: analyses[pair].score, reverse=True)
    signals = {
        pair: analyses[pair].signal and not news.blocks_new_positions and (pair == "BTCUSDC" or regime)
        for pair in ordered
    }
    context = f"btc_regime={regime};news={news.score:.2f};headlines={news.fresh_headlines}"
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
    last_heartbeat = 0.0
    LOG.info(
        "worker starting; live_trading=%s; symbols=%s",
        master_live,
        ",".join(configured_pairs()),
    )

    while True:
        try:
            authenticated = readiness_check(client)
            LOG.info(
                "health check passed; authenticated_account_read=%s",
                authenticated,
            )
            signals, analyses, context = market_scan(client, news_monitor)
            LOG.info(
                "market scan; buy_signals=%s; %s; scores=%s",
                ",".join(pair for pair, signal in signals.items() if signal) or "none",
                context,
                ",".join(f"{pair}:{analysis.score}" for pair, analysis in analyses.items()),
            )
            settings = reporter.get_settings() if reporter else None
            dashboard_live = (
                bool(settings.get("bot_enabled")) and bool(settings.get("live_trading_enabled"))
                if settings is not None else reporter is None
            )
            live = master_live and dashboard_live
            if reporter and time.time() - last_heartbeat >= 600:
                best_pair = max(analyses, key=lambda pair: analyses[pair].score)
                best = analyses[best_pair]
                reporter.record_event("heartbeat", f"live={live};{context};best={best_pair}:{best.score};reasons={','.join(best.reasons)}")
                last_heartbeat = time.time()
            if master_live and not live:
                LOG.warning("live cycle paused by dashboard")
            if live:
                result = run_live_cycle(
                    client,
                    signals,
                    Path(os.getenv("LIVE_STATE_PATH", "/var/lib/ai-trading-app/live-state.json")),
                    LiveLimits.from_settings(settings) if settings else LiveLimits.from_env(),
                    reporter.record_trade if reporter else None,
                )
                LOG.warning("live cycle result=%s", result)
        except Exception:
            LOG.exception("health check failed; no orders will be submitted")
        time.sleep(60)


if __name__ == "__main__":
    main()
