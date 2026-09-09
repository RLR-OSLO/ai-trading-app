from __future__ import annotations

import logging
import os
import time
from decimal import Decimal
from pathlib import Path

from .analysis import MarketAnalysis, analyze_market, bullish_btc_regime
from .binance import BinanceCredentials, BinanceError, BinanceSpotClient
from .config import DEFAULT_CONFIG
from .news import NewsMonitor
from .portfolio_live import PortfolioLimits, recover_positions_from_trade_history, run_portfolio_cycle
from .reporting import SupabaseReporter
from .scalping import ScalpAnalysis, analyze_scalp


LOG = logging.getLogger("ai_trader")
RISK_THRESHOLDS = {"low": 7, "normal": 6, "high": 4}
ACTIVE_MARKET_COUNT = 12
MIN_24H_QUOTE_VOLUME = Decimal(os.getenv("MIN_24H_QUOTE_VOLUME", "5000000"))
MIN_24H_TRADES = int(os.getenv("MIN_24H_TRADES", "5000"))
MAX_SPREAD_BPS = Decimal(os.getenv("MAX_SPREAD_BPS", "20"))
BULLRUN_MAX_HOLD_SECONDS = int(os.getenv("BULLRUN_MAX_HOLD_SECONDS", "21600"))
MARKET_UNIVERSE = (
    "BTC", "ETH", "BNB", "SOL", "XRP", "DOGE", "ADA", "TRX", "AVAX", "LINK",
    "SUI", "XLM", "BCH", "LTC", "DOT", "SHIB", "TON", "HBAR", "UNI", "AAVE",
    "NEAR", "APT", "ETC", "FIL", "ICP", "ATOM", "ALGO", "VET", "POL", "ARB",
)


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


def ticker_is_liquid(item: dict[str, object]) -> bool:
    quote_volume = Decimal(str(item.get("quoteVolume", "0")))
    trades = int(item.get("count", 0) or 0)
    bid = Decimal(str(item.get("bidPrice", "0")))
    ask = Decimal(str(item.get("askPrice", "0")))
    if quote_volume < MIN_24H_QUOTE_VOLUME or trades < MIN_24H_TRADES or bid <= 0 or ask <= 0 or ask < bid:
        return False
    mid = (bid + ask) / Decimal("2")
    spread_bps = ((ask - bid) / mid) * Decimal("10000") if mid > 0 else Decimal("999999")
    return spread_bps <= MAX_SPREAD_BPS


def active_pairs(client: BinanceSpotClient, quote_asset: str) -> tuple[str, ...]:
    if quote_asset not in DEFAULT_CONFIG.preferred_quote_assets:
        raise ValueError("Quote asset is outside the approved allowlist")
    requested = {f"{asset}{quote_asset}" for asset in MARKET_UNIVERSE}
    exchange_info = client._request("GET", "/api/v3/exchangeInfo")
    available = {
        item.get("symbol")
        for item in exchange_info.get("symbols", [])
        if item.get("symbol") in requested
        and item.get("status") == "TRADING"
        and item.get("quoteAsset") == quote_asset
        and item.get("isSpotTradingAllowed", True)
    }
    tickers = client._request("GET", "/api/v3/ticker/24hr")
    eligible = [item for item in tickers if item.get("symbol") in available and ticker_is_liquid(item)]
    ordered = sorted(
        eligible,
        key=lambda item: (Decimal(str(item.get("quoteVolume", "0"))), int(item.get("count", 0) or 0)),
        reverse=True,
    )
    selected = tuple(str(item.get("symbol")) for item in ordered[:ACTIVE_MARKET_COUNT])
    if not selected:
        raise BinanceError(
            f"No approved {quote_asset} spot pairs meet liquidity requirements "
            f"(volume>={MIN_24H_QUOTE_VOLUME}, trades>={MIN_24H_TRADES}, spread<={MAX_SPREAD_BPS}bps)"
        )
    return selected


def readiness_check(client: BinanceSpotClient, pairs: tuple[str, ...] | None = None) -> bool:
    client.server_time()
    if pairs:
        info = client.exchange_info(pairs)
        available = {item["symbol"] for item in info.get("symbols", [])}
        missing = set(pairs) - available
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


def binance_account_summary(client: BinanceSpotClient, quote_asset: str) -> tuple[str, Decimal, Decimal, str]:
    account = client.account()
    balances = {
        str(row.get("asset")): Decimal(str(row.get("free", "0"))) + Decimal(str(row.get("locked", "0")))
        for row in account.get("balances", [])
        if Decimal(str(row.get("free", "0"))) + Decimal(str(row.get("locked", "0"))) > 0
    }
    tickers = client._request("GET", "/api/v3/ticker/price")
    prices = {str(row.get("symbol")): Decimal(str(row.get("price", "0"))) for row in tickers}

    def in_quote(asset: str) -> Decimal | None:
        if asset == quote_asset:
            return Decimal("1")
        direct = prices.get(f"{asset}{quote_asset}")
        if direct and direct > 0:
            return direct
        if quote_asset == "USDC":
            if asset == "USDT":
                usdt_usdc = prices.get("USDTUSDC")
                if usdt_usdc and usdt_usdc > 0:
                    return usdt_usdc
                usdc_usdt = prices.get("USDCUSDT")
                if usdc_usdt and usdc_usdt > 0:
                    return Decimal("1") / usdc_usdt
            via_usdt = prices.get(f"{asset}USDT")
            usdc_usdt = prices.get("USDCUSDT")
            if via_usdt and via_usdt > 0 and usdc_usdt and usdc_usdt > 0:
                return via_usdt / usdc_usdt
            via_btc = prices.get(f"{asset}BTC")
            btc_quote = prices.get("BTCUSDC")
            if via_btc and via_btc > 0 and btc_quote and btc_quote > 0:
                return via_btc * btc_quote
        elif quote_asset == "USDT":
            if asset == "USDC":
                usdc_usdt = prices.get("USDCUSDT")
                if usdc_usdt and usdc_usdt > 0:
                    return usdc_usdt
            via_usdc = prices.get(f"{asset}USDC")
            usdc_usdt = prices.get("USDCUSDT")
            if via_usdc and via_usdc > 0 and usdc_usdt and usdc_usdt > 0:
                return via_usdc * usdc_usdt
            via_btc = prices.get(f"{asset}BTC")
            btc_quote = prices.get("BTCUSDT")
            if via_btc and via_btc > 0 and btc_quote and btc_quote > 0:
                return via_btc * btc_quote
        return None

    total = Decimal("0")
    invested = Decimal("0")
    wallet_values: dict[str, Decimal] = {}
    for asset, quantity in balances.items():
        conversion = in_quote(asset)
        if conversion is None:
            continue
        value = quantity * conversion
        wallet_values[asset] = value
        total += value
        if asset != quote_asset:
            invested += value
    balance_text = ",".join(f"{asset}:{quantity}" for asset, quantity in balances.items()) or "none"
    wallet_value_text = ",".join(f"{asset}:{value}" for asset, value in wallet_values.items()) or "none"
    return balance_text, total, invested, wallet_value_text


def bullrun_candidate(analysis: MarketAnalysis, scalp: ScalpAnalysis, risk_profile: str) -> bool:
    return (
        risk_profile in {"normal", "high"}
        and analysis.score >= 7
        and analysis.volume_ratio_15m >= Decimal("1.25")
        and Decimal("0.35") <= analysis.atr_percent_1h <= Decimal("6")
        and scalp.score >= 4
        and "risk_veto" not in analysis.reasons
    )


def bullrun_profile(analysis: MarketAnalysis, configured_stop_percent: object, risk_profile: str) -> tuple[Decimal, Decimal, Decimal]:
    configured = Decimal(str(configured_stop_percent or "1")) / Decimal("100")
    atr_fraction = analysis.atr_percent_1h / Decimal("100")
    stop = min(Decimal("0.03"), max(configured, atr_fraction * Decimal("1.5")))
    activation = min(Decimal("0.05"), max(Decimal("0.02"), stop * Decimal("1.25")))
    size_multiplier = Decimal("1.50") if risk_profile == "high" else Decimal("1.25")
    return stop, activation, size_multiplier


def market_scan(
    client: BinanceSpotClient,
    news_monitor: NewsMonitor,
    pairs: tuple[str, ...],
    risk_profile: str,
) -> tuple[
    dict[str, bool],
    dict[str, MarketAnalysis],
    dict[str, ScalpAnalysis],
    dict[str, str],
    str,
]:
    swing_frames = {
        pair: {interval: client.klines(pair, interval, limit=101)[:-1] for interval in ("15m", "1h", "4h")}
        for pair in pairs
    }
    scalp_frames = {
        pair: {interval: client.klines(pair, interval, limit=61)[:-1] for interval in ("1m", "5m")}
        for pair in pairs
    }

    btc_pair = next((pair for pair in pairs if pair.startswith("BTC")), pairs[0])
    btc_regime = bullish_btc_regime(swing_frames[btc_pair])
    news = news_monitor.score()
    analyses = {pair: analyze_market(data) for pair, data in swing_frames.items()}
    aggressive_scalping = risk_profile == "high"
    scalp_analyses = {
        pair: analyze_scalp(data, aggressive=aggressive_scalping)
        for pair, data in scalp_frames.items()
    }

    swing_threshold = RISK_THRESHOLDS.get(risk_profile, RISK_THRESHOLDS["normal"])
    scalp_enabled = risk_profile in {"normal", "high"}
    # Generic negative crypto headlines used to veto every new entry, which made the
    # daytrader unnecessarily idle even when individual markets had strong signals.
    # Low risk keeps the hard veto. Normal/high instead require one extra swing point.
    hard_news_block = news.blocks_new_positions and risk_profile == "low"
    news_penalty = 1 if news.blocks_new_positions and risk_profile in {"normal", "high"} else 0
    effective_swing_threshold = swing_threshold + news_penalty

    bullruns = {pair: bullrun_candidate(analyses[pair], scalp_analyses[pair], risk_profile) for pair in pairs}
    ranked = sorted(
        pairs,
        key=lambda pair: (
            2 if bullruns[pair] else (1 if scalp_enabled and scalp_analyses[pair].signal else 0),
            scalp_analyses[pair].score,
            analyses[pair].score,
            analyses[pair].volume_ratio_15m,
        ),
        reverse=True,
    )

    signals: dict[str, bool] = {}
    strategies: dict[str, str] = {}
    for pair in ranked:
        swing_signal = (
            analyses[pair].score >= effective_swing_threshold
            and "risk_veto" not in analyses[pair].reasons
            and not hard_news_block
        )
        scalp_signal = scalp_enabled and scalp_analyses[pair].signal and not hard_news_block
        bullrun_signal = bullruns[pair] and not hard_news_block
        signals[pair] = bullrun_signal or scalp_signal or swing_signal
        strategies[pair] = "bullrun" if bullrun_signal else ("scalp" if scalp_signal else "swing")

    scalp_signal_text = ",".join(pair for pair in ranked if scalp_enabled and scalp_analyses[pair].signal) or "none"
    bullrun_text = ",".join(pair for pair in ranked if bullruns[pair]) or "none"
    context = (
        f"threshold={effective_swing_threshold};base_threshold={swing_threshold};risk={risk_profile};btc_regime={btc_regime};"
        f"news={news.score:.2f};news_penalty={news_penalty};headlines={news.fresh_headlines};scalp={scalp_signal_text};bullrun={bullrun_text}"
    )
    return signals, analyses, scalp_analyses, strategies, context


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
    LOG.info("worker starting; master_live=%s; scalping=1m/5m", master_live)

    while True:
        risk_profile = "normal"
        try:
            settings = reporter.get_settings() if reporter else None
            quote_asset = str((settings or {}).get("quote_asset") or os.getenv("TRADING_QUOTE_ASSET", "USDC")).upper()
            risk_profile = str((settings or {}).get("risk_profile") or "normal").lower()
            authenticated = readiness_check(client)
            pairs = active_pairs(client, quote_asset)
            available_balance = free_quote_balance(client, quote_asset) if authenticated else Decimal("0")
            if authenticated and reporter:
                recovered = recover_positions_from_trade_history(
                    client, state_path, reporter.get_recent_trades(), quote_asset
                )
                if recovered:
                    reporter.record_event("state_recovered", f"recovered={','.join(recovered)}", "warning")
                    LOG.warning("recovered missing positions from trade history: %s", ",".join(recovered))
            LOG.info(
                "health check passed; authenticated_account_read=%s; available_%s=%s; active_pairs=%s",
                authenticated,
                quote_asset.lower(),
                available_balance,
                ",".join(pairs),
            )

            signals, analyses, scalp_analyses, strategies, context = market_scan(
                client,
                news_monitor,
                pairs,
                risk_profile,
            )
            signal_text = ",".join(
                f"{pair}:{strategies[pair]}" for pair, signal in signals.items() if signal
            ) or "none"
            score_text = ",".join(f"{pair}:{analysis.score}" for pair, analysis in analyses.items())
            scalp_score_text = ",".join(f"{pair}:{analysis.score}" for pair, analysis in scalp_analyses.items())
            LOG.info(
                "market scan; buy_signals=%s; %s; swing_scores=%s; scalp_scores=%s",
                signal_text,
                context,
                score_text,
                scalp_score_text,
            )

            dashboard_live = (
                bool(settings.get("bot_enabled")) and bool(settings.get("live_trading_enabled"))
                if settings is not None else reporter is None
            )
            allow_new_entries = master_live and dashboard_live

            if reporter and time.time() - last_heartbeat >= 30:
                best_pair = max(
                    pairs,
                    key=lambda pair: (
                        1 if scalp_analyses[pair].signal else 0,
                        scalp_analyses[pair].score,
                        analyses[pair].score,
                    ),
                )
                price_text = ",".join(f"{pair}:{client.ticker_price(pair)}" for pair in pairs)
                balances_text, account_total, invested_value, wallet_value_text = binance_account_summary(client, quote_asset)
                reporter.record_event(
                    "heartbeat",
                    f"live={allow_new_entries};available={available_balance};quote={quote_asset};{context};"
                    f"signals={signal_text};scores={score_text};scalp_scores={scalp_score_text};"
                    f"prices={price_text};balances={balances_text};wallet_values={wallet_value_text};account_total={account_total};invested_value={invested_value};markets={','.join(pairs)};"
                    f"best={best_pair}:{strategies[best_pair]}:{analyses[best_pair].score}/{scalp_analyses[best_pair].score};"
                    f"reasons={','.join(scalp_analyses[best_pair].reasons if strategies[best_pair] == 'scalp' else analyses[best_pair].reasons)}",
                )
                last_heartbeat = time.time()

            runtime_settings = dict(settings or {})
            runtime_settings["trade_cap_usdc"] = str(max(available_balance, Decimal("5")))
            stop_overrides: dict[str, Decimal] = {}
            activation_overrides: dict[str, Decimal] = {}
            size_multipliers: dict[str, Decimal] = {}
            max_hold_overrides: dict[str, int] = {}
            for pair, strategy in strategies.items():
                if strategy == "bullrun":
                    stop, activation, size_multiplier = bullrun_profile(
                        analyses[pair], (settings or {}).get("stop_loss_percent", "1"), risk_profile
                    )
                    stop_overrides[pair] = stop
                    activation_overrides[pair] = activation
                    size_multipliers[pair] = size_multiplier
                    max_hold_overrides[pair] = BULLRUN_MAX_HOLD_SECONDS

            result = run_portfolio_cycle(
                client,
                signals,
                state_path,
                PortfolioLimits.from_settings(runtime_settings) if settings else PortfolioLimits.from_env(),
                reporter.record_trade if reporter else None,
                allow_new_entries=allow_new_entries,
                quote_asset=quote_asset,
                entry_strategies=strategies,
                entry_stop_fractions=stop_overrides,
                entry_target_fractions=activation_overrides,
                entry_size_multipliers=size_multipliers,
                entry_max_hold_seconds=max_hold_overrides,
            )
            if not allow_new_entries and result == "paused_new_entries":
                LOG.info("new entries paused; no open position requires management")
            else:
                LOG.warning("live cycle result=%s", result)
        except Exception:
            LOG.exception("trading cycle failed; no new order will be submitted")

        default_interval = 15 if risk_profile == "high" else 30
        time.sleep(int(os.getenv("WORKER_INTERVAL_SECONDS", str(default_interval))))


if __name__ == "__main__":
    main()
